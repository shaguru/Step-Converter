"""STEP (ISO 10303) read/write through OpenCASCADE (cadquery-ocp).

Writing a mesh to STEP builds a proper B-rep: every mesh vertex and edge is
created once and shared between neighbouring faces, so the result is a
watertight shell (and a closed solid when the mesh is closed) rather than a
"polygon soup" that CAD packages refuse to treat as a body.

Face modes
  smooth     one smooth bicubic patch per quad (see smooth_surface.py);
             best for CAD/CNC, needs an all-quad mesh
  auto       planar polygons -> planar faces, non-planar quads -> one exact
             bilinear surface each (keeps quads as single CAD faces)
  triangles  everything triangulated into planar faces (most compatible)
"""
from __future__ import annotations

import numpy as np

from .mesh import PolyMesh


# ===================================================================== write
def write_step(mesh: PolyMesh, path: str, mode: str = "auto", planar_tol: float = 1e-4,
               make_solid: bool = True, unit: str = "MM", progress=None,
               sharp_angle: float = 50.0, engine: str = "fast") -> dict:
    """engine "fast" writes the B-rep text directly (see step_fast.py);
    "occ" builds it through OpenCASCADE (slower, kept as a fallback)."""
    if engine == "fast":
        from .step_fast import write_step_fast
        return write_step_fast(mesh, path, mode=mode, planar_tol=planar_tol, unit=unit,
                               sharp_angle=sharp_angle, make_solid=make_solid, progress=progress)
    from OCP.BRep import BRep_Builder, BRep_Tool
    from OCP.BRepBuilderAPI import (BRepBuilderAPI_MakeEdge, BRepBuilderAPI_MakeFace,
                                    BRepBuilderAPI_MakeVertex, BRepBuilderAPI_MakeWire)
    from OCP.Geom import Geom_BezierSurface
    from OCP.Geom2d import Geom2d_BSplineCurve
    from OCP.gp import gp_Dir, gp_Pln, gp_Pnt, gp_Pnt2d
    TColgp_Array1OfPnt2d, TColgp_Array2OfPnt, TColStd_Array1OfReal, TColStd_Array1OfInteger = _arrays()
    from OCP.TopoDS import TopoDS_Face, TopoDS_Shell, TopoDS_Wire

    if mode == "smooth":
        from .smooth_surface import write_smooth_step
        return write_smooth_step(mesh, path, make_solid=make_solid, unit=unit, progress=progress,
                                 sharp_angle=sharp_angle)
    mesh = mesh.merge_vertices().compact()
    V = mesh.vertices
    diag = max(mesh.diagonal, 1e-9)
    ptol = planar_tol * diag
    tol = max(1e-7, 1e-6 * diag)

    # -------- decide face list: (corner indices, kind) kind: 'plane' | 'bilinear'
    faces = []
    o = mesh.offsets
    for i in range(mesh.n_faces):
        poly = mesh.face_indices[o[i]:o[i + 1]]
        k = len(poly)
        if k == 3:
            faces.append((poly, "plane"))
            continue
        P = V[poly]
        n = _newell(P)
        nn = np.linalg.norm(n)
        if nn < 1e-30:
            continue
        n /= nn
        dev = np.abs((P - P.mean(0)) @ n).max()
        if dev <= ptol:
            faces.append((poly, "plane"))
        elif k == 4 and mode == "auto":
            faces.append((poly, "bilinear"))
        else:
            # split on the shorter diagonal / fan
            if k == 4:
                if np.linalg.norm(P[0] - P[2]) <= np.linalg.norm(P[1] - P[3]):
                    faces += [(poly[[0, 1, 2]], "plane"), (poly[[0, 2, 3]], "plane")]
                else:
                    faces += [(poly[[0, 1, 3]], "plane"), (poly[[1, 2, 3]], "plane")]
            else:
                faces += [(poly[[0, j, j + 1]], "plane") for j in range(1, k - 1)]

    # -------- shared topology
    verts = [BRepBuilderAPI_MakeVertex(gp_Pnt(*map(float, p))).Vertex() for p in V]
    edge_map = {}
    edge_use = {}

    def get_edge(a, b):
        key = (a, b) if a < b else (b, a)
        e = edge_map.get(key)
        if e is None:
            e = BRepBuilderAPI_MakeEdge(verts[key[0]], verts[key[1]]).Edge()
            edge_map[key] = e
        edge_use[key] = edge_use.get(key, 0) + 1
        return e, key, a > b

    builder = BRep_Builder()
    shell = TopoDS_Shell()
    builder.MakeShell(shell)
    n_plane = n_bilin = n_fail = 0
    total = len(faces)

    for fi, (poly, kind) in enumerate(faces):
        if progress and fi % 500 == 0:
            progress(fi / max(total, 1), f"STEP faces {fi}/{total}")
        k = len(poly)
        try:
            if kind == "plane":
                P = V[poly]
                n = _newell(P)
                n /= np.linalg.norm(n)
                c = P.mean(0)
                mw = BRepBuilderAPI_MakeWire()
                for j in range(k):
                    e, _, rev = get_edge(int(poly[j]), int(poly[(j + 1) % k]))
                    mw.Add(_as_edge(e.Reversed()) if rev else e)
                pln = gp_Pln(gp_Pnt(*c), gp_Dir(*n))
                mf = BRepBuilderAPI_MakeFace(pln, mw.Wire(), True)
                if not mf.IsDone():
                    n_fail += 1
                    continue
                builder.Add(shell, mf.Face())
                n_plane += 1
            else:
                # exact bilinear patch through the 4 corners: S(u,v), corners
                # q0=(0,0) q1=(1,0) q2=(1,1) q3=(0,1)  -> CCW in uv = outer wire
                q = [int(x) for x in poly]
                poles = TColgp_Array2OfPnt(1, 2, 1, 2)
                poles.SetValue(1, 1, gp_Pnt(*V[q[0]]))
                poles.SetValue(2, 1, gp_Pnt(*V[q[1]]))
                poles.SetValue(2, 2, gp_Pnt(*V[q[2]]))
                poles.SetValue(1, 2, gp_Pnt(*V[q[3]]))
                surf = Geom_BezierSurface(poles)
                face = TopoDS_Face()
                builder.MakeFace(face, surf, tol)
                uv = {q[0]: (0.0, 0.0), q[1]: (1.0, 0.0), q[2]: (1.0, 1.0), q[3]: (0.0, 1.0)}
                wire = TopoDS_Wire()
                builder.MakeWire(wire)
                for j in range(4):
                    a, b = q[j], q[(j + 1) % 4]
                    e, key, rev = get_edge(a, b)
                    f_, l_ = BRep_Tool.Range_s(e)
                    pa, pb = uv[key[0]], uv[key[1]]
                    pts = TColgp_Array1OfPnt2d(1, 2)
                    pts.SetValue(1, gp_Pnt2d(*pa))
                    pts.SetValue(2, gp_Pnt2d(*pb))
                    kn = TColStd_Array1OfReal(1, 2)
                    kn.SetValue(1, f_)
                    kn.SetValue(2, l_)
                    mu = TColStd_Array1OfInteger(1, 2)
                    mu.SetValue(1, 2)
                    mu.SetValue(2, 2)
                    pc = Geom2d_BSplineCurve(pts, kn, mu, 1)
                    builder.UpdateEdge(e, pc, face, tol)
                    builder.Add(wire, _as_edge(e.Reversed()) if rev else e)
                builder.Add(face, wire)
                builder.Add(shell, face)
                n_bilin += 1
        except Exception as exc:  # keep going, report at the end
            n_fail += 1
            if n_fail <= 3:
                import logging
                logging.getLogger("stepfable").warning("STEP face %d failed: %s", fi, exc)

    closed = bool(edge_use) and all(c == 2 for c in edge_use.values())
    info = _finish_and_write(shell, builder, path, closed, make_solid, unit, mesh.name, progress)
    info.update({"planar_faces": n_plane, "bilinear_faces": n_bilin, "failed_faces": n_fail})
    return info


def _finish_and_write(shell, builder, path, closed, make_solid, unit, name, progress) -> dict:
    """Turn a shell into a solid when closed, then write the STEP file."""
    from OCP.Interface import Interface_Static
    from OCP.STEPControl import STEPControl_AsIs, STEPControl_Writer
    from OCP.TopoDS import TopoDS_Compound

    shape = shell
    solid_ok = False
    if make_solid and closed:
        try:
            from OCP.BRepBuilderAPI import BRepBuilderAPI_MakeSolid
            from OCP.BRepGProp import BRepGProp
            from OCP.GProp import GProp_GProps
            shell.Closed(True)
            ms = BRepBuilderAPI_MakeSolid(shell)
            if ms.IsDone():
                solid = ms.Solid()
                props = GProp_GProps()
                BRepGProp.VolumeProperties_s(solid, props)
                if props.Mass() < 0:          # inside-out mesh: flip the body
                    solid.Reverse()
                shape = solid
                solid_ok = True
        except Exception:
            pass
    if not solid_ok:
        comp = TopoDS_Compound()
        builder.MakeCompound(comp)
        builder.Add(comp, shell)
        shape = comp

    if progress:
        progress(0.97, "Writing STEP file")
    _quiet_occt()
    Interface_Static.SetCVal_s("write.step.schema", "AP214IS")
    Interface_Static.SetCVal_s("write.step.unit", unit.upper())
    Interface_Static.SetCVal_s("write.step.product.name", name or "Step Converter")
    w = STEPControl_Writer()
    w.Transfer(shape, STEPControl_AsIs)
    status = w.Write(path)
    if int(status) != 1:   # IFSelect_RetDone
        raise RuntimeError(f"STEP writer failed with status {status}")
    if progress:
        progress(1.0, "STEP done")
    return {"closed": closed, "solid": solid_ok}


def _quiet_occt():
    """Silence OpenCASCADE's console banners."""
    try:
        from OCP.Message import Message
        printers = Message.DefaultMessenger_s().Printers()
        for i in range(1, printers.Length() + 1):
            printers.Value(i).SetTraceLevel(getattr(__import__("OCP.Message", fromlist=["Message_Gravity"]),
                                                    "Message_Gravity").Message_Fail)
    except Exception:
        pass


def _downcast(kind):
    from OCP.TopoDS import TopoDS
    return getattr(TopoDS, kind + "_s", None) or getattr(TopoDS, kind)


def _as_edge(shape):
    return _downcast("Edge")(shape)


def _as_face(shape):
    return _downcast("Face")(shape)


def _arrays():
    """OCCT 7.x exposes TColgp_* arrays, OCCT 8 moved them to OCP.collections."""
    try:
        from OCP.TColgp import TColgp_Array1OfPnt2d, TColgp_Array2OfPnt
        from OCP.TColStd import TColStd_Array1OfInteger, TColStd_Array1OfReal
        return TColgp_Array1OfPnt2d, TColgp_Array2OfPnt, TColStd_Array1OfReal, TColStd_Array1OfInteger
    except ImportError:
        from OCP.collections import Array1_double, Array1_gp_Pnt2d, Array1_int, Array2_gp_Pnt
        return Array1_gp_Pnt2d, Array2_gp_Pnt, Array1_double, Array1_int


def _newell(P: np.ndarray) -> np.ndarray:
    Q = np.roll(P, -1, axis=0)
    return np.array([
        np.sum((P[:, 1] - Q[:, 1]) * (P[:, 2] + Q[:, 2])),
        np.sum((P[:, 2] - Q[:, 2]) * (P[:, 0] + Q[:, 0])),
        np.sum((P[:, 0] - Q[:, 0]) * (P[:, 1] + Q[:, 1])),
    ])


# ====================================================================== read
def read_step_as_mesh(path: str, deflection: float = 0.0, angle: float = 0.3) -> PolyMesh:
    """Tessellate a STEP file. deflection 0 = automatic (0.05% of size)."""
    from OCP.Bnd import Bnd_Box
    from OCP.BRep import BRep_Tool
    from OCP.BRepBndLib import BRepBndLib
    from OCP.BRepMesh import BRepMesh_IncrementalMesh
    from OCP.IFSelect import IFSelect_RetDone
    from OCP.STEPControl import STEPControl_Reader
    from OCP.TopAbs import TopAbs_FACE, TopAbs_REVERSED
    from OCP.TopExp import TopExp_Explorer
    from OCP.TopLoc import TopLoc_Location

    r = STEPControl_Reader()
    if r.ReadFile(path) != IFSelect_RetDone:
        raise RuntimeError("Could not read STEP file")
    r.TransferRoots()
    shape = r.OneShape()
    if deflection <= 0:
        box = Bnd_Box()
        BRepBndLib.Add_s(shape, box)
        a, b = box.CornerMin(), box.CornerMax()
        deflection = 5e-4 * float(np.linalg.norm([b.X() - a.X(), b.Y() - a.Y(), b.Z() - a.Z()]))
    BRepMesh_IncrementalMesh(shape, deflection, False, angle, True)

    parts = []
    exp = TopExp_Explorer(shape, TopAbs_FACE)
    while exp.More():
        face = _as_face(exp.Current())
        loc = TopLoc_Location()
        tri = BRep_Tool.Triangulation_s(face, loc)
        if tri is not None:
            trsf = loc.Transformation()
            nodes = np.array([_xyz(tri.Node(i + 1).Transformed(trsf)) for i in range(tri.NbNodes())])
            tris = np.array([tri.Triangle(i + 1).Get() for i in range(tri.NbTriangles())], dtype=np.int64) - 1
            if face.Orientation() == TopAbs_REVERSED:
                tris = tris[:, ::-1]
            parts.append(PolyMesh.from_triangles(nodes, tris))
        exp.Next()
    if not parts:
        raise ValueError("STEP file contains no surfaces")
    return PolyMesh.concatenate(parts).merge_vertices(tol=deflection * 1e-3)


def _xyz(p):
    return (p.X(), p.Y(), p.Z())
