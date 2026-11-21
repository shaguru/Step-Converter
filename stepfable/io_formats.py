"""Load and save every format StepFable supports.

Import:  FBX, glTF, GLB, OBJ, STL, PLY, STEP/STP
Export:  FBX, glTF, GLB, OBJ, STL, PLY, STEP/STP

Polygons (quads) are preserved for OBJ, FBX and STEP. glTF/GLB/STL/PLY are
triangle formats, so quads are split on their shorter diagonal on export.
"""
from __future__ import annotations

import os

import numpy as np

from .mesh import PolyMesh

IMPORT_EXTS = [".fbx", ".gltf", ".glb", ".obj", ".stl", ".ply", ".step", ".stp"]
EXPORT_EXTS = [".step", ".stl", ".obj", ".fbx", ".glb", ".gltf", ".ply"]


def ext_of(path: str) -> str:
    return os.path.splitext(path)[1].lower()


# =============================================================== load
def load(path: str, step_deflection: float = 0.0) -> PolyMesh:
    ext = ext_of(path)
    name = os.path.splitext(os.path.basename(path))[0]
    if ext == ".obj":
        m = _load_obj(path)
    elif ext == ".fbx":
        m = _load_fbx(path)
    elif ext in (".gltf", ".glb", ".stl", ".ply"):
        m = _load_trimesh(path)
    elif ext in (".step", ".stp"):
        from .step_io import read_step_as_mesh
        m = read_step_as_mesh(path, deflection=step_deflection)
    else:
        raise ValueError(f"Unsupported input format: {ext}")
    m.name = name
    m.meta["source"] = path
    return m


def _load_obj(path: str) -> PolyMesh:
    with open(path, "rb") as fh:
        data = fh.read()
    lines = data.splitlines()
    vlines = [ln[2:] for ln in lines if ln[:2] == b"v "]
    if not vlines:
        raise ValueError("OBJ has no vertices")
    ncols = len(vlines[0].split())
    try:
        verts = np.array(b" ".join(vlines).split(), dtype=np.float64).reshape(-1, ncols)[:, :3]
    except ValueError:   # ragged rows (mixed colours) - slow path
        verts = np.array([[float(x) for x in ln.split()[:3]] for ln in vlines])
    nv = len(verts)
    sizes, flat = [], []
    for ln in lines:
        if ln[:2] != b"f ":
            continue
        toks = ln[2:].split()
        poly = []
        for t in toks:
            i = int(t.split(b"/", 1)[0])
            poly.append(i - 1 if i > 0 else nv + i)
        if len(poly) >= 3:
            sizes.append(len(poly))
            flat.extend(poly)
    m = PolyMesh(verts, np.asarray(sizes, np.int32), np.asarray(flat, np.int64))
    return m.compact() if m.n_faces else m


def _load_fbx(path: str) -> PolyMesh:
    from .fbx_reader import load_fbx
    return load_fbx(path)


def _load_trimesh(path: str) -> PolyMesh:
    import trimesh
    obj = trimesh.load(path, force="scene", process=False)
    if isinstance(obj, trimesh.Scene):
        tm = obj.to_geometry() if hasattr(obj, "to_geometry") else obj.dump(concatenate=True)
    else:
        tm = obj
    if not isinstance(tm, trimesh.Trimesh) or len(tm.faces) == 0:
        raise ValueError("No triangle geometry found")
    return PolyMesh.from_trimesh(tm).merge_vertices()


# =============================================================== save
def save(mesh: PolyMesh, path: str, **opts) -> str:
    ext = ext_of(path)
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    if ext == ".obj":
        _save_obj(mesh, path)
    elif ext == ".fbx":
        from .fbx_writer import write_fbx
        write_fbx(mesh, path, unit_scale_cm=opts.get("fbx_unit_cm", 1.0))
    elif ext in (".stl", ".ply", ".glb", ".gltf"):
        _save_trimesh(mesh, path)
    elif ext in (".step", ".stp"):
        from .step_io import write_step
        write_step(mesh, path,
                   mode=opts.get("step_mode", "auto"),
                   planar_tol=opts.get("step_planar_tol", 1e-4),
                   make_solid=opts.get("step_solid", True),
                   unit=opts.get("step_unit", "MM"),
                   sharp_angle=opts.get("step_sharp_angle", 50.0),
                   engine=opts.get("step_engine", "fast"),
                   progress=opts.get("progress"))
    else:
        raise ValueError(f"Unsupported output format: {ext}")
    return path


def _save_obj(mesh: PolyMesh, path: str):
    with open(path, "w", newline="\n") as fh:
        fh.write("# Step Converter OBJ\n")
        fh.write(f"o {mesh.name}\n")
        np.savetxt(fh, mesh.vertices, fmt="v %.7g %.7g %.7g")
        idx = mesh.face_indices + 1
        for k in np.unique(mesh.face_sizes):
            f = mesh.faces_of_size(int(k)) + 1
            np.savetxt(fh, f, fmt="f " + " ".join(["%d"] * int(k)))
        del idx


def _save_trimesh(mesh: PolyMesh, path: str):
    tm = mesh.to_trimesh()
    ext = ext_of(path)
    if ext == ".gltf":
        from trimesh.exchange.gltf import export_gltf
        files = export_gltf(tm.scene() if hasattr(tm, "scene") else tm, embed_buffers=True)
        key = next(k for k in files if k.endswith(".gltf"))
        with open(path, "wb") as fh:
            fh.write(files[key])
    else:
        tm.export(path)


def load_with_progress(path: str, progress=None) -> PolyMesh:
    if progress:
        progress(0.1, f"Reading {os.path.basename(path)}")
    m = load(path)
    if progress:
        progress(1.0, "Loaded")
    return m
