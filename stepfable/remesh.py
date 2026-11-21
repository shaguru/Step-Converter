"""The StepFable remesh pipeline: dense sculpt -> clean, accurate quads.

Stages (each can be switched off):
  1 Cleanup     weld, drop debris, fix non-manifold, close small holes
  2 Voxel       rebuild as one watertight surface (like Blender's voxel remesh)
  3 Smooth      remove voxel stair-steps / sculpt bumps (feature-preserving option)
  4 Reduce      quadric decimation or isotropic remesh to a target density
  5 Quads       pairing / all-quad split / Blender QuadriFlow / Instant Meshes
  6 Relax       even out the quads, snapping back onto the surface each step
  7 Measure     deviation from the original + quad-quality stats
"""
from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass, fields

import numpy as np

from .mesh import PolyMesh

QUAD_METHODS = {
    "none": "Keep triangles",
    "pair": "Pair triangles (quad-dominant, fast)",
    "pair_subdivide": "Pair + split (100% quads, built-in)",
    "quadriflow": "Blender QuadriFlow (100% quads, flowing loops)",
    "instant_meshes": "Instant Meshes (100% quads, field-aligned)",
}
SMOOTH_METHODS = {
    "none": "Off",
    "taubin": "Taubin (no shrinking)",
    "feature": "Feature-preserving (keeps creases)",
    "hc": "HC Laplacian (gentle)",
}
REDUCE_METHODS = {
    "quadric": "Quadric decimation (best accuracy per face)",
    "isotropic": "Isotropic remesh (even triangles, best for quads)",
    "none": "Off",
}
VOXEL_ENGINES = {"meshlab": "Built-in (MeshLab)", "blender": "Blender OpenVDB"}


@dataclass
class RemeshParams:
    # 1 cleanup
    cleanup: bool = True
    weld_tolerance_pct: float = 0.0       # % of bbox diagonal, 0 = exact duplicates only
    min_component_pct: float = 1.0        # drop floating bits smaller than this % of diagonal
    close_holes_max_edges: int = 100      # 0 = keep holes
    # 2 voxel
    voxel: bool = False
    voxel_engine: str = "meshlab"
    voxel_size_pct: float = 0.5           # voxel size as % of bbox diagonal
    # 3 smoothing
    smooth_method: str = "taubin"
    smooth_iterations: int = 10
    smooth_feature_angle: float = 40.0    # feature-preserving: normals differing more are creases
    # 4 reduce
    reduce_method: str = "quadric"
    target_faces: int = 20000             # FINAL face count you want (quads or tris)
    isotropic_iterations: int = 6
    preserve_boundary: bool = True
    # 5 quads
    quad_method: str = "pair_subdivide"
    quad_feature_angle: float = 40.0      # don't merge triangles across sharper edges
    quadriflow_preserve_sharp: bool = False
    quadriflow_symmetry: bool = False
    instant_crease_angle: float = 0.0
    instant_smooth_iters: int = 2
    # 6 relax + project
    relax_iterations: int = 5
    relax_strength: float = 0.5
    project_to: str = "smoothed"          # "smoothed" | "original" | "none"
    # 7 measure
    measure: bool = True
    measure_samples: int = 60000

    @staticmethod
    def from_dict(d: dict) -> "RemeshParams":
        names = {f.name for f in fields(RemeshParams)}
        return RemeshParams(**{k: v for k, v in d.items() if k in names})

    def to_dict(self) -> dict:
        return asdict(self)

    def save(self, path):
        with open(path, "w") as fh:
            json.dump(self.to_dict(), fh, indent=2)

    @staticmethod
    def load(path) -> "RemeshParams":
        with open(path) as fh:
            return RemeshParams.from_dict(json.load(fh))


class Cancelled(Exception):
    pass


# ---------------------------------------------------------------- meshlab glue
def _to_ms(mesh: PolyMesh):
    import pymeshlab as ml
    ms = ml.MeshSet()
    ms.add_mesh(ml.Mesh(vertex_matrix=mesh.vertices, face_matrix=mesh.triangulate().astype(np.int32)))
    return ms


def _from_ms(ms, name) -> PolyMesh:
    m = ms.current_mesh()
    return PolyMesh.from_triangles(m.vertex_matrix(), m.face_matrix(), name)


def _pct(ml, v):
    return ml.PercentageValue(float(v))


# ---------------------------------------------------------------- pipeline
def run_pipeline(original: PolyMesh, p: RemeshParams, progress=None, extra=None) -> tuple[PolyMesh, dict]:
    """Return (result mesh, report dict). progress(fraction, text) may raise Cancelled."""
    import pymeshlab as ml
    extra = extra or {}
    t0 = time.time()
    timings = {}
    report = {"input": original.stats()}

    def step(frac, text):
        if progress:
            progress(frac, text)

    def tick(name, t):
        timings[name] = round(time.time() - t, 2)

    name = original.name
    mesh = original
    all_quads_in = original.n_faces and (original.face_sizes == 4).all()

    # ---- 1 cleanup
    if p.cleanup:
        step(0.02, "Cleaning up")
        t = time.time()
        mesh = mesh.merge_vertices(p.weld_tolerance_pct / 100.0 * mesh.diagonal)
        ms = _to_ms(mesh)
        ms.meshing_remove_duplicate_faces()
        ms.meshing_remove_null_faces()
        if p.min_component_pct > 0:
            ms.meshing_remove_connected_component_by_diameter(mincomponentdiag=_pct(ml, p.min_component_pct))
        ms.meshing_repair_non_manifold_edges()
        ms.meshing_repair_non_manifold_vertices()
        if p.close_holes_max_edges > 0:
            try:
                ms.meshing_close_holes(maxholesize=int(p.close_holes_max_edges))
            except Exception:
                pass
        ms.meshing_remove_unreferenced_vertices()
        mesh = _from_ms(ms, name)
        tick("cleanup", t)

    # ---- 2 voxel
    if p.voxel:
        step(0.12, "Voxel remeshing")
        t = time.time()
        size = p.voxel_size_pct / 100.0 * mesh.diagonal
        if p.voxel_engine == "blender":
            from .external import run_blender
            mesh = run_blender(mesh, "voxel", extra.get("blender"), voxel_size=size)
        else:
            ms = _to_ms(mesh)
            # MeshLab's offset is a 0..100 slider where 50% means "exactly on the surface"
            ms.generate_resampled_uniform_mesh(cellsize=_abs(ml, size, mesh.diagonal),
                                               offset=ml.PercentageValue(50.0),
                                               mergeclosevert=True, discretize=False,
                                               multisample=True, absdist=False)
            ms.meshing_remove_connected_component_by_diameter(mincomponentdiag=_pct(ml, 2.0))
            mesh = _from_ms(ms, name)
        tick("voxel", t)

    # ---- 3 smoothing
    if p.smooth_method != "none" and p.smooth_iterations > 0:
        step(0.25, "Smoothing bumps")
        t = time.time()
        ms = _to_ms(mesh)
        if p.smooth_method == "taubin":
            ms.apply_coord_taubin_smoothing(lambda_=0.5, mu=-0.53, stepsmoothnum=int(p.smooth_iterations))
        elif p.smooth_method == "feature":
            ms.apply_coord_two_steps_smoothing(stepsmoothnum=int(p.smooth_iterations),
                                               normalthr=float(p.smooth_feature_angle),
                                               stepnormalnum=20, stepfitnum=20)
        elif p.smooth_method == "hc":
            for _ in range(int(p.smooth_iterations)):
                ms.apply_coord_hc_laplacian_smoothing()
        mesh = _from_ms(ms, name)
        tick("smooth", t)

    reference = mesh                                     # surface the quads must follow
    step(0.35, "Preparing reference surface")

    # ---- 4 reduce: aim for the face count the quad step needs
    qm = p.quad_method
    if qm == "pair_subdivide":
        tri_target = max(p.target_faces // 2, 100)     # T tris -> ~T/2 quads -> x4 split
    elif qm == "pair":
        tri_target = max(p.target_faces * 2, 100)       # pairs halve the count
    elif qm in ("quadriflow", "instant_meshes"):
        tri_target = max(p.target_faces * 4, 2000)      # give the remesher enough detail
    else:
        tri_target = p.target_faces
    if p.reduce_method != "none" and not all_quads_in:
        n_tris_now = len(mesh.triangulate())
        if n_tris_now > tri_target or p.reduce_method == "isotropic":
            step(0.4, f"Reducing to ~{tri_target:,} triangles")
            t = time.time()
            ms = _to_ms(mesh)
            if p.reduce_method == "isotropic":
                if n_tris_now > tri_target * 4:            # decimate first, it is much faster
                    ms.meshing_decimation_quadric_edge_collapse(targetfacenum=int(tri_target * 2),
                                                                preserveboundary=p.preserve_boundary,
                                                                preservenormal=True, optimalplacement=True,
                                                                planarquadric=True, qualitythr=0.5)
                area = float(mesh.to_trimesh().area)
                edge = np.sqrt(4 * area / (np.sqrt(3) * tri_target))
                ms.meshing_isotropic_explicit_remeshing(iterations=int(p.isotropic_iterations),
                                                        targetlen=_abs(ml, edge, mesh.diagonal),
                                                        featuredeg=float(p.quad_feature_angle),
                                                        checksurfdist=True,
                                                        maxsurfdist=_abs(ml, edge * 0.5, mesh.diagonal))
            else:
                ms.meshing_decimation_quadric_edge_collapse(targetfacenum=int(tri_target),
                                                            preserveboundary=p.preserve_boundary,
                                                            preservenormal=True, optimalplacement=True,
                                                            planarquadric=True, qualitythr=0.5,
                                                            autoclean=True)
            mesh = _from_ms(ms, name)
            tick("reduce", t)

    # ---- 5 quads
    step(0.6, f"Quad step: {QUAD_METHODS.get(qm, qm)}")
    t = time.time()
    from . import quadify
    if all_quads_in and qm in ("pair", "pair_subdivide"):
        pass                                            # already quads
    elif qm == "pair":
        mesh = quadify.pair_triangles(mesh, feature_angle=p.quad_feature_angle)
    elif qm == "pair_subdivide":
        mesh = quadify.subdivide_to_quads(quadify.pair_triangles(mesh, feature_angle=p.quad_feature_angle))
    elif qm == "quadriflow":
        from .external import run_blender
        mesh = run_blender(mesh, "quadriflow", extra.get("blender"), target_faces=p.target_faces,
                           preserve_sharp=p.quadriflow_preserve_sharp, symmetry=p.quadriflow_symmetry,
                           preserve_boundary=p.preserve_boundary)
    elif qm == "instant_meshes":
        from .external import run_instant_meshes
        mesh = run_instant_meshes(mesh, p.target_faces, extra.get("instant_meshes"),
                                  crease_angle=p.instant_crease_angle, smooth_iters=p.instant_smooth_iters)
    tick("quads", t)

    # ---- 6 relax + project
    if p.project_to != "none" or p.relax_iterations > 0:
        step(0.75, "Relaxing and snapping to surface")
        t = time.time()
        proj = None
        if p.project_to != "none":
            ref = original if p.project_to == "original" else reference
            avg_edge = np.sqrt(max(mesh.to_trimesh().area, 1e-30) / max(mesh.n_faces, 1))
            proj = quadify.SurfaceProjector(ref, target_spacing=avg_edge / 2)
        mesh = quadify.relax_and_project(mesh, proj, p.relax_iterations, p.relax_strength,
                                         fix_boundary=p.preserve_boundary)
        tick("relax", t)

    mesh.name = name
    # ---- 7 measure
    if p.measure:
        step(0.9, "Measuring accuracy")
        t = time.time()
        from .metrics import full_report
        report.update(full_report(mesh, original, p.measure_samples))
        tick("measure", t)
    else:
        report.update(mesh.stats())
    report["timings"] = timings
    report["seconds"] = round(time.time() - t0, 2)
    step(1.0, "Done")
    return mesh, report


def _abs(ml, value, diag):
    """Absolute length as a pymeshlab value (falls back to % of diagonal)."""
    if hasattr(ml, "PureValue"):
        return ml.PureValue(float(value))
    return ml.PercentageValue(100.0 * float(value) / max(diag, 1e-30))

