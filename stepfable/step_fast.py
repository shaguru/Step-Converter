"""Direct STEP (AP214) writer: mesh -> watertight B-rep solid as plain text.

Building the solid through OpenCASCADE costs about 0.7 ms per face in
Python, so big meshes took many minutes. This writer emits the same
B-rep entities straight to text: shared vertices and edges, one face per
polygon, closed shell -> MANIFOLD_SOLID_BREP. It is 10-30x faster and the
files are 3-4x smaller (control points shared between neighbouring faces).
The result is checked against OpenCASCADE's validator in the tests.

Face kinds
  smooth     all-quad mesh -> one bicubic Bezier patch per quad, cubic edges
  auto       planar polygon -> PLANE face, twisted quad -> exact bilinear patch
  triangles  everything triangulated -> PLANE faces
"""
from __future__ import annotations

import datetime as _dt

import numpy as np

from .mesh import PolyMesh

_UNITS = {
    "MM": "( LENGTH_UNIT() NAMED_UNIT(*) SI_UNIT(.MILLI.,.METRE.) )",
    "CM": "( LENGTH_UNIT() NAMED_UNIT(*) SI_UNIT(.CENTI.,.METRE.) )",
    "M": "( LENGTH_UNIT() NAMED_UNIT(*) SI_UNIT($,.METRE.) )",
}


def _fmt_reals(a: np.ndarray) -> list[str]:
    """STEP REALs: must contain a decimal point ('1.' not '1')."""
    out = []
    for x in np.asarray(a, dtype=np.float64).ravel().tolist():
        s = "%.10G" % x
        if "." not in s:
            if "E" in s:
                m, e = s.split("E")
                s = m + ".E" + e
            else:
                s += "."
        out.append(s)
    return out


def _points(xyz: np.ndarray) -> list[str]:
    r = _fmt_reals(xyz)
    return [f"({r[i]},{r[i + 1]},{r[i + 2]})" for i in range(0, len(r), 3)]


def _signed_volume(mesh: PolyMesh) -> float:
    t = mesh.triangulate()
    V = mesh.vertices
    return float(np.einsum("ij,ij->i", V[t[:, 0]], np.cross(V[t[:, 1]], V[t[:, 2]])).sum() / 6.0)


def _edges(mesh: PolyMesh):
    """Unique undirected edges, per-corner edge index and direction."""
    he = mesh.edges()
    a, b = he[:, 0], he[:, 1]
    lo, hi = np.minimum(a, b), np.maximum(a, b)
    nv = mesh.n_vertices + 1
    key, inv = np.unique(lo * nv + hi, return_inverse=True)
    use = np.bincount(inv, minlength=len(key))
    return key // nv, key % nv, inv.ravel(), a > b, use


class _Writer:
    def __init__(self):
        self.lines = []
        self.n = 0

    def add(self, text) -> int:
        self.n += 1
        self.lines.append(f"#{self.n}={text};")
        return self.n

    def reserve(self) -> int:
        self.n += 1
        self.lines.append(None)
        return self.n

    def set(self, idx, text):
        self.lines[idx - 1] = f"#{idx}={text};"


def write_step_fast(mesh: PolyMesh, path: str, mode: str = "smooth", planar_tol: float = 1e-4,
                    unit: str = "MM", sharp_angle: float = 50.0, make_solid: bool = True,
                    progress=None) -> dict:
    mesh = mesh.merge_vertices().compact()
    if mode == "triangles":
        mesh = PolyMesh.from_triangles(mesh.vertices, mesh.triangulate(), mesh.name)
    if mode == "smooth" and (mesh.face_sizes != 4).any():
        mode = "auto"
    if _signed_volume(mesh) < 0:                 # inside-out: flip so faces point outward
        mesh = mesh.flipped()
    lab = mesh.meta.get("flat_face_plane")
    if (mode != "triangles" and lab is not None and len(lab) == mesh.n_faces
            and (mesh.face_sizes == 3).all()):
        from .hard_surface import write_step_merged   # flat regions -> one CAD face each
        return write_step_merged(mesh, path, unit=unit, make_solid=make_solid, progress=progress)

    w = _Writer()
    name = (mesh.name or "StepConverter").replace("'", "")
    # ---------------------------------------------------------- product + context
    w.add("APPLICATION_PROTOCOL_DEFINITION('international standard','automotive_design',2000,#2)")
    w.add("APPLICATION_CONTEXT('core data for automotive mechanical design processes')")
    w.add("SHAPE_DEFINITION_REPRESENTATION(#4,#10)")
    w.add("PRODUCT_DEFINITION_SHAPE('','',#5)")
    w.add("PRODUCT_DEFINITION('design','',#6,#9)")
    w.add("PRODUCT_DEFINITION_FORMATION('','',#7)")
    w.add(f"PRODUCT('{name}','{name}','',(#8))")
    w.add("PRODUCT_CONTEXT('',#2,'mechanical')")
    w.add("PRODUCT_DEFINITION_CONTEXT('part definition',#2,'design')")
    rep_id = w.reserve()                                     # 10: shape representation
    w.add("AXIS2_PLACEMENT_3D('',#12,#13,#14)")
    w.add("CARTESIAN_POINT('',(0.,0.,0.))")
    w.add("DIRECTION('',(0.,0.,1.))")
    w.add("DIRECTION('',(1.,0.,0.))")
    body_id = w.reserve()                                    # 15: solid / surface model
    shell_id = w.reserve()                                   # 16: shell
    ctx_id = w.reserve()                                     # 17: geometric context
    u = unit.upper()
    if u in ("INCH", "IN"):
        mm = w.add(_UNITS["MM"])
        dim = w.add("DIMENSIONAL_EXPONENTS(1.,0.,0.,0.,0.,0.,0.)")
        conv = w.add(f"LENGTH_MEASURE_WITH_UNIT(LENGTH_MEASURE(25.4),#{mm})")
        len_unit = w.add(f"( CONVERSION_BASED_UNIT('INCH',#{conv}) LENGTH_UNIT() NAMED_UNIT(#{dim}) )")
    else:
        len_unit = w.add(_UNITS.get(u, _UNITS["MM"]))
    ang = w.add("( NAMED_UNIT(*) PLANE_ANGLE_UNIT() SI_UNIT($,.RADIAN.) )")
    sol = w.add("( NAMED_UNIT(*) SI_UNIT($,.STERADIAN.) SOLID_ANGLE_UNIT() )")
    tol = max(1e-7, 1e-6 * mesh.diagonal)
    unc = w.add(f"UNCERTAINTY_MEASURE_WITH_UNIT(LENGTH_MEASURE({_fmt_reals([tol])[0]}),#{len_unit},"
                "'distance_accuracy_value','confusion accuracy')")
    w.set(ctx_id, f"( GEOMETRIC_REPRESENTATION_CONTEXT(3) GLOBAL_UNCERTAINTY_ASSIGNED_CONTEXT((#{unc})) "
                  f"GLOBAL_UNIT_ASSIGNED_CONTEXT((#{len_unit},#{ang},#{sol})) "
                  "REPRESENTATION_CONTEXT('Context #1','3D Context with UNIT and UNCERTAINTY') )")
    w.add("PRODUCT_RELATED_PRODUCT_CATEGORY('part',$,(#7))")

    # ---------------------------------------------------------- vertices
    V = mesh.vertices
    if progress:
        progress(0.05, "STEP: vertices")
    vp = _points(V)
    v_cp = w.n + 1
    w.lines += [f"#{v_cp + i}=CARTESIAN_POINT('',{p});" for i, p in enumerate(vp)]
    w.n += len(vp)
    v_vp = w.n + 1
    w.lines += [f"#{v_vp + i}=VERTEX_POINT('',#{v_cp + i});" for i in range(len(vp))]
    w.n += len(vp)

    E0, E1, inv, rev, use = _edges(mesh)
    nE = len(E0)
    o = mesh.offsets
    face_ids = []

    if mode == "smooth":
        from .smooth_surface import build_patches
        if progress:
            progress(0.1, "STEP: building smooth patches")
        Q, P, curves, _, inv4, rev4 = build_patches(mesh, sharp_angle)
        # edge interior control points (2 per edge) + cubic curves + edge curves
        ecp = _points(curves[:, 1:3].reshape(-1, 3))
        e_cp = w.n + 1
        w.lines += [f"#{e_cp + i}=CARTESIAN_POINT('',{p});" for i, p in enumerate(ecp)]
        w.n += len(ecp)
        e_crv = w.n + 1
        w.lines += [f"#{e_crv + e}=B_SPLINE_CURVE_WITH_KNOTS('',3,(#{v_cp + E0[e]},#{e_cp + 2 * e},"
                    f"#{e_cp + 2 * e + 1},#{v_cp + E1[e]}),.UNSPECIFIED.,.F.,.F.,(4,4),(0.,1.),"
                    ".PIECEWISE_BEZIER_KNOTS.);" for e in range(nE)]
        w.n += nE
        e_ec = w.n + 1
        w.lines += [f"#{e_ec + e}=EDGE_CURVE('',#{v_vp + E0[e]},#{v_vp + E1[e]},#{e_crv + e},.T.);"
                    for e in range(nE)]
        w.n += nE
        # control-point id grid per patch (borders shared with the edge curves)
        F = len(Q)
        eid = np.stack([v_cp + E0, e_cp + 2 * np.arange(nE), e_cp + 2 * np.arange(nE) + 1, v_cp + E1], 1)

        def dir_ids(k):
            c = eid[inv4[:, k]].copy()
            r = rev4[:, k]
            c[r] = c[r][:, ::-1]
            return c
        G = np.zeros((F, 4, 4), dtype=np.int64)
        G[:, :, 0] = dir_ids(0)
        G[:, 3, :] = dir_ids(1)
        G[:, :, 3] = dir_ids(2)[:, ::-1]
        G[:, 0, :] = dir_ids(3)[:, ::-1]
        inner = _points(P[:, [1, 2, 1, 2], [1, 1, 2, 2]].reshape(-1, 3))
        f_cp = w.n + 1
        w.lines += [f"#{f_cp + i}=CARTESIAN_POINT('',{p});" for i, p in enumerate(inner)]
        w.n += len(inner)
        base = f_cp + 4 * np.arange(F)
        G[:, 1, 1], G[:, 2, 1], G[:, 1, 2], G[:, 2, 2] = base, base + 1, base + 2, base + 3
        if progress:
            progress(0.4, "STEP: faces")

        out = []
        n = w.n
        for f in range(F):
            g = G[f]
            rows = ",".join("(" + ",".join(f"#{x}" for x in g[i]) + ")" for i in range(4))
            surf = n + 1
            out.append(f"#{surf}=B_SPLINE_SURFACE_WITH_KNOTS('',3,3,({rows}),.UNSPECIFIED.,.F.,.F.,.F.,"
                       "(4,4),(4,4),(0.,1.),(0.,1.),.PIECEWISE_BEZIER_KNOTS.);")
            oe = []
            for k in range(4):
                n_oe = surf + 1 + k
                out.append(f"#{n_oe}=ORIENTED_EDGE('',*,*,#{e_ec + inv4[f, k]},{'.F.' if rev4[f, k] else '.T.'});")
                oe.append(f"#{n_oe}")
            loop, bound, face = surf + 5, surf + 6, surf + 7
            out.append(f"#{loop}=EDGE_LOOP('',({','.join(oe)}));")
            out.append(f"#{bound}=FACE_BOUND('',#{loop},.T.);")
            out.append(f"#{face}=ADVANCED_FACE('',(#{bound}),#{surf},.T.);")
            face_ids.append(face)
            n = face
            if progress and f % 20000 == 0:
                progress(0.4 + 0.5 * f / F, f"STEP: faces {f:,}/{F:,}")
        w.lines += out
        w.n = n
        kinds = {"smooth_patches": F}
    else:
        # straight edges: degree-1 curves between the two vertex points
        e_crv = w.n + 1
        w.lines += [f"#{e_crv + e}=B_SPLINE_CURVE_WITH_KNOTS('',1,(#{v_cp + E0[e]},#{v_cp + E1[e]}),"
                    ".UNSPECIFIED.,.F.,.F.,(2,2),(0.,1.),.PIECEWISE_BEZIER_KNOTS.);" for e in range(nE)]
        w.n += nE
        e_ec = w.n + 1
        w.lines += [f"#{e_ec + e}=EDGE_CURVE('',#{v_vp + E0[e]},#{v_vp + E1[e]},#{e_crv + e},.T.);"
                    for e in range(nE)]
        w.n += nE
        diag = max(mesh.diagonal, 1e-12)
        out = []
        n = w.n
        n_plane = n_bilin = 0
        sizes = mesh.face_sizes
        fi_all = mesh.face_indices
        for f in range(mesh.n_faces):
            s0, s1 = o[f], o[f + 1]
            poly = fi_all[s0:s1]
            Pp = V[poly]
            nrm = _newell(Pp)
            ln = np.linalg.norm(nrm)
            if ln < 1e-300:
                continue
            nrm /= ln
            c = Pp.mean(0)
            planar = sizes[f] == 3 or np.abs((Pp - c) @ nrm).max() <= planar_tol * diag
            oe = []
            if planar:
                ref = Pp[1] - Pp[0]
                ref -= (ref @ nrm) * nrm
                ref /= max(np.linalg.norm(ref), 1e-300)
                pts = _fmt_reals(np.concatenate([c, nrm, ref]))
                out.append(f"#{n + 1}=CARTESIAN_POINT('',({pts[0]},{pts[1]},{pts[2]}));")
                out.append(f"#{n + 2}=DIRECTION('',({pts[3]},{pts[4]},{pts[5]}));")
                out.append(f"#{n + 3}=DIRECTION('',({pts[6]},{pts[7]},{pts[8]}));")
                out.append(f"#{n + 4}=AXIS2_PLACEMENT_3D('',#{n + 1},#{n + 2},#{n + 3});")
                out.append(f"#{n + 5}=PLANE('',#{n + 4});")
                surf = n + 5
                n_plane += 1
            else:                                   # twisted quad: exact bilinear patch
                q = v_cp + poly
                out.append(f"#{n + 1}=B_SPLINE_SURFACE_WITH_KNOTS('',1,1,((#{q[0]},#{q[3]}),(#{q[1]},#{q[2]})),"
                           ".UNSPECIFIED.,.F.,.F.,.F.,(2,2),(2,2),(0.,1.),(0.,1.),.PIECEWISE_BEZIER_KNOTS.);")
                surf = n + 1
                n_bilin += 1
            n = surf
            for k in range(s0, s1):
                n += 1
                out.append(f"#{n}=ORIENTED_EDGE('',*,*,#{e_ec + inv[k]},{'.F.' if rev[k] else '.T.'});")
                oe.append(f"#{n}")
            out.append(f"#{n + 1}=EDGE_LOOP('',({','.join(oe)}));")
            out.append(f"#{n + 2}=FACE_BOUND('',#{n + 1},.T.);")
            out.append(f"#{n + 3}=ADVANCED_FACE('',(#{n + 2}),#{surf},.T.);")
            n += 3
            face_ids.append(n)
            if progress and f % 20000 == 0:
                progress(0.3 + 0.6 * f / max(mesh.n_faces, 1), f"STEP: faces {f:,}/{mesh.n_faces:,}")
        w.lines += out
        w.n = n
        kinds = {"planar_faces": n_plane, "bilinear_faces": n_bilin}

    closed = bool(nE) and bool((use == 2).all())
    faces = ",".join(f"#{i}" for i in face_ids)
    if closed and make_solid:
        w.set(shell_id, f"CLOSED_SHELL('',({faces}))")
        w.set(body_id, f"MANIFOLD_SOLID_BREP('',#{shell_id})")
        w.set(rep_id, f"ADVANCED_BREP_SHAPE_REPRESENTATION('',(#11,#{body_id}),#{ctx_id})")
    else:
        w.set(shell_id, f"OPEN_SHELL('',({faces}))")
        w.set(body_id, f"SHELL_BASED_SURFACE_MODEL('',(#{shell_id}))")
        w.set(rep_id, f"MANIFOLD_SURFACE_SHAPE_REPRESENTATION('',(#11,#{body_id}),#{ctx_id})")

    if progress:
        progress(0.95, "STEP: writing file")
    stamp = _dt.datetime.now().replace(microsecond=0).isoformat()
    with open(path, "w", newline="\n") as fh:
        fh.write("ISO-10303-21;\nHEADER;\n")
        fh.write("FILE_DESCRIPTION(('Step Converter model'),'2;1');\n")
        fh.write(f"FILE_NAME('{name}','{stamp}',(''),(''),'Step Converter','Step Converter','');\n")
        fh.write("FILE_SCHEMA(('AUTOMOTIVE_DESIGN { 1 0 10303 214 1 1 1 1 }'));\nENDSEC;\nDATA;\n")
        fh.write("\n".join(w.lines))
        fh.write("\nENDSEC;\nEND-ISO-10303-21;\n")
    if progress:
        progress(1.0, "STEP done")
    return dict(kinds, closed=closed, solid=bool(closed and make_solid), faces=len(face_ids))


def _newell(P):
    Q = np.roll(P, -1, axis=0)
    return np.array([np.sum((P[:, 1] - Q[:, 1]) * (P[:, 2] + Q[:, 2])),
                     np.sum((P[:, 2] - Q[:, 2]) * (P[:, 0] + Q[:, 0])),
                     np.sum((P[:, 0] - Q[:, 0]) * (P[:, 1] + Q[:, 1]))])
