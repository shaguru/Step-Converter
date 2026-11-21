"""Quad mesh -> smooth bicubic surface patches (for CAD/CNC STEP output).

Each quad becomes one bicubic Bezier patch. Patch borders are cubic curves
built only from the two end vertices of that edge and their normals (the
PN / "curved quad" construction), so neighbouring patches share exactly the
same border curve and the STEP body is watertight. Tangent planes agree at
every vertex, so the surface reads smooth to CAM software, while edges that
are sharper than `sharp_angle` stay straight to keep hard creases crisp.

The same patches are evaluated in NumPy for previews and accuracy checks, so
what you measure is what goes into the STEP file.
"""
from __future__ import annotations

import numpy as np

from .mesh import PolyMesh


def _unit(v):
    return v / np.maximum(np.linalg.norm(v, axis=-1, keepdims=True), 1e-30)


def _face_normals(V, Q):
    return _unit(np.cross(V[Q[:, 2]] - V[Q[:, 0]], V[Q[:, 3]] - V[Q[:, 1]]))


def build_patches(mesh: PolyMesh, sharp_angle: float = 50.0, tension: float = 1.0):
    """Return (quads (F,4), poles (F,4,4,3), edge_poles dict-free arrays).

    Only all-quad meshes are accepted; run the pair+split quad step first.
    poles[f, i, j] is the control point at u=i/3, v=j/3 with corners
    q0=(0,0) q1=(1,0) q2=(1,1) q3=(0,1).
    """
    if not len(mesh.face_sizes) or (mesh.face_sizes != 4).any():
        raise ValueError("Smooth STEP needs a 100% quad mesh (use a quad method that gives all quads).")
    V = mesh.vertices
    Q = mesh.faces_of_size(4)
    F = len(Q)
    fn = _face_normals(V, Q)
    # area-weighted vertex normals
    area = np.linalg.norm(np.cross(V[Q[:, 2]] - V[Q[:, 0]], V[Q[:, 3]] - V[Q[:, 1]]), axis=1) * 0.5
    vn = np.zeros_like(V)
    for k in range(4):
        np.add.at(vn, Q[:, k], fn * area[:, None])
    vn = _unit(vn)

    # unique edges and their two faces, for sharpness
    a = Q.ravel()
    b = Q[:, [1, 2, 3, 0]].ravel()
    lo, hi = np.minimum(a, b), np.maximum(a, b)
    nv = len(V) + 1
    key = lo * nv + hi
    ukey, inv = np.unique(key, return_inverse=True)
    face_of = np.repeat(np.arange(F), 4)
    # dihedral per unique edge: compare normals of the faces using it
    n_sum = np.zeros((len(ukey), 3))
    np.add.at(n_sum, inv, fn[face_of])
    cnt = np.bincount(inv, minlength=len(ukey))
    first_face = np.full(len(ukey), -1)
    first_face[inv[::-1]] = face_of[::-1]
    # cos between the two faces: |n1+n2|^2 = 2 + 2cos
    cos = np.clip((np.einsum("ij,ij->i", n_sum, n_sum) - 2.0) / 2.0, -1, 1)
    sharp_edge = (cnt != 2) | (np.degrees(np.arccos(cos)) > sharp_angle)

    # cubic border curve per unique edge, oriented lo -> hi
    E0, E1 = ukey // nv, ukey % nv
    P0, P1 = V[E0], V[E1]
    d = P1 - P0
    t = tension / 3.0
    c1 = P0 + t * (d - (d * vn[E0]).sum(1, keepdims=True) * vn[E0])
    c2 = P1 + t * (-d - (-d * vn[E1]).sum(1, keepdims=True) * vn[E1])
    lin1, lin2 = P0 + d / 3.0, P0 + 2.0 * d / 3.0
    c1[sharp_edge], c2[sharp_edge] = lin1[sharp_edge], lin2[sharp_edge]
    edge_curves = np.stack([P0, c1, c2, P1], axis=1)       # (E,4,3)

    inv = inv.reshape(F, 4)
    rev = (a > b).reshape(F, 4)                             # face walks edge hi -> lo

    def curve(fk):                                          # (F,4,3) along the face's direction
        c = edge_curves[inv[:, fk]].copy()
        r = rev[:, fk]
        c[r] = c[r][:, ::-1]
        return c

    P = np.zeros((F, 4, 4, 3))
    c01, c12, c23, c30 = curve(0), curve(1), curve(2), curve(3)
    P[:, :, 0] = c01                                        # v=0, u: 0->1
    P[:, 3, :] = c12                                        # u=1, v: 0->1
    P[:, :, 3] = c23[:, ::-1]                               # v=1, u: 1->0 reversed
    P[:, 0, :] = c30[:, ::-1]                               # u=0, v: 1->0 reversed
    # interior points: parallelogram rule from each corner
    P[:, 1, 1] = P[:, 1, 0] + P[:, 0, 1] - P[:, 0, 0]
    P[:, 2, 1] = P[:, 2, 0] + P[:, 3, 1] - P[:, 3, 0]
    P[:, 1, 2] = P[:, 1, 3] + P[:, 0, 2] - P[:, 0, 3]
    P[:, 2, 2] = P[:, 2, 3] + P[:, 3, 2] - P[:, 3, 3]
    return Q, P, edge_curves, (E0, E1), inv, rev


def _bernstein(t):
    t = np.asarray(t)
    s = 1 - t
    return np.stack([s ** 3, 3 * s * s * t, 3 * s * t * t, t ** 3], axis=-1)


def tessellate(mesh: PolyMesh, res: int = 4, sharp_angle: float = 50.0) -> PolyMesh:
    """Dense quad mesh of the smooth surface (res x res quads per patch)."""
    Q, P, *_ = build_patches(mesh, sharp_angle)
    u = np.linspace(0, 1, res + 1)
    B = _bernstein(u)                                       # (r,4)
    pts = np.einsum("ui,vj,fijk->fuvk", B, B, P)            # (F,r,r,3)
    F = len(Q)
    n = res + 1
    base = (np.arange(F) * n * n)[:, None, None]
    ii, jj = np.meshgrid(np.arange(res), np.arange(res), indexing="ij")
    v00 = base + ii * n + jj
    quads = np.stack([v00, v00 + n, v00 + n + 1, v00 + 1], axis=-1).reshape(-1, 4)
    out = PolyMesh.from_quads(pts.reshape(-1, 3), quads, mesh.name)
    return out.merge_vertices(tol=1e-9 * max(mesh.diagonal, 1e-9))


def write_smooth_step(mesh: PolyMesh, path: str, sharp_angle: float = 50.0, make_solid: bool = True,
                      unit: str = "MM", progress=None) -> dict:
    from OCP.BRep import BRep_Builder
    from OCP.BRepBuilderAPI import BRepBuilderAPI_MakeEdge, BRepBuilderAPI_MakeVertex
    from OCP.Geom import Geom_BezierCurve, Geom_BezierSurface
    from OCP.Geom2d import Geom2d_BSplineCurve
    from OCP.gp import gp_Pnt, gp_Pnt2d
    from OCP.TopoDS import TopoDS_Face, TopoDS_Shell, TopoDS_Wire

    from .step_io import _arrays, _as_edge, _finish_and_write

    Arr1P2d, Arr2P, Arr1R, Arr1I = _arrays()
    try:
        from OCP.TColgp import TColgp_Array1OfPnt as Arr1P
    except ImportError:
        from OCP.collections import Array1_gp_Pnt as Arr1P

    Q, P, curves, (E0, E1), inv, rev = build_patches(mesh, sharp_angle)
    V = mesh.vertices
    tol = max(1e-7, 1e-6 * mesh.diagonal)
    verts = {}

    def vtx(i):
        v = verts.get(i)
        if v is None:
            v = BRepBuilderAPI_MakeVertex(gp_Pnt(*map(float, V[i]))).Vertex()
            verts[i] = v
        return v

    edges = [None] * len(curves)

    def edge(e):
        if edges[e] is None:
            poles = Arr1P(1, 4)
            for k in range(4):
                poles.SetValue(k + 1, gp_Pnt(*map(float, curves[e, k])))
            edges[e] = BRepBuilderAPI_MakeEdge(Geom_BezierCurve(poles), vtx(int(E0[e])), vtx(int(E1[e]))).Edge()
        return edges[e]

    corner_uv = [(0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0)]
    builder = BRep_Builder()
    shell = TopoDS_Shell()
    builder.MakeShell(shell)
    knots = Arr1R(1, 2)
    knots.SetValue(1, 0.0)
    knots.SetValue(2, 1.0)
    mults = Arr1I(1, 2)
    mults.SetValue(1, 2)
    mults.SetValue(2, 2)
    fails = 0
    for f in range(len(Q)):
        if progress and f % 500 == 0:
            progress(f / len(Q), f"Smooth STEP patches {f}/{len(Q)}")
        try:
            poles = Arr2P(1, 4, 1, 4)
            for i in range(4):
                for j in range(4):
                    poles.SetValue(i + 1, j + 1, gp_Pnt(*map(float, P[f, i, j])))
            surf = Geom_BezierSurface(poles)
            face = TopoDS_Face()
            builder.MakeFace(face, surf, tol)
            wire = TopoDS_Wire()
            builder.MakeWire(wire)
            for k in range(4):
                e = edge(int(inv[f, k]))
                ua, ub = corner_uv[k], corner_uv[(k + 1) % 4]
                if rev[f, k]:                    # edge param runs from face corner k+1 to k
                    ua, ub = ub, ua
                pts = Arr1P2d(1, 2)
                pts.SetValue(1, gp_Pnt2d(*ua))
                pts.SetValue(2, gp_Pnt2d(*ub))
                builder.UpdateEdge(e, Geom2d_BSplineCurve(pts, knots, mults, 1), face, tol)
                builder.Add(wire, _as_edge(e.Reversed()) if rev[f, k] else e)
            builder.Add(face, wire)
            builder.Add(shell, face)
        except Exception:
            fails += 1
    edge_count = np.bincount(inv.ravel(), minlength=len(curves))
    closed = bool((edge_count == 2).all())
    info = _finish_and_write(shell, builder, path, closed, make_solid, unit, mesh.name, progress)
    info.update({"smooth_patches": len(Q) - fails, "failed_faces": fails})
    return info


def edge_polylines(mesh: PolyMesh, samples: int = 6, sharp_angle: float = 50.0):
    """Patch borders sampled on the smooth surface, for drawing the wireframe
    on top of the smooth preview. Returns (points (N,3), VTK line cells)."""
    _, _, curves, *_ = build_patches(mesh, sharp_angle)
    t = np.linspace(0, 1, samples)
    B = _bernstein(t)                                      # (s,4)
    pts = np.einsum("si,eik->esk", B, curves)              # (E,s,3)
    E = len(curves)
    ids = np.arange(E * samples).reshape(E, samples)
    cells = np.hstack([np.full((E, 1), samples), ids]).ravel()
    return pts.reshape(-1, 3), cells
