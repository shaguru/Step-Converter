"""Hard-surface flat faces: find the flat regions of a model, fit an exact plane
to each one, snap the reduced mesh onto those planes and remember which face
belongs to which plane, so the STEP writer can merge every flat region into a
single CAD face.

Steps
  1 detect   group the original triangles into flat regions (region growing:
             a triangle joins a region when all its corners lie within the
             flat tolerance of the region's best-fit plane), refit, repeat
  2 label    every face of the reduced mesh takes the plane of the original
             surface underneath it, if it lies on that plane
  3 snap     points on one plane are projected onto it; points where two or
             three planes meet go onto their intersection line / corner, so
             hard edges become exact. A point that would have to move more
             than `max_move` gives its faces back to the free (triangle) area.
Faces that belong to no plane (bevels, rounded and organic areas) stay as they
are.
"""
from __future__ import annotations

import numpy as np
from scipy.sparse import coo_matrix
from scipy.sparse.csgraph import connected_components

from .mesh import PolyMesh


def _fit_plane(P, w):
    c = (P * w[:, None]).sum(0) / w.sum()
    _, _, vt = np.linalg.svd((P - c) * np.sqrt(w)[:, None], full_matrices=False)
    return c, vt[-1]


def _tri_data(V, F):
    T = V[F]
    cr = np.cross(T[:, 1] - T[:, 0], T[:, 2] - T[:, 0])
    area = 0.5 * np.linalg.norm(cr, axis=1)
    n = cr / np.maximum(2 * area, 1e-300)[:, None]
    return T, n, area


def _adjacency(F, nv):
    e = np.concatenate([F[:, [0, 1]], F[:, [1, 2]], F[:, [2, 0]]])
    fid = np.tile(np.arange(len(F)), 3)
    key = np.minimum(e[:, 0], e[:, 1]).astype(np.int64) * (nv + 1) + np.maximum(e[:, 0], e[:, 1])
    o = np.argsort(key, kind="stable")
    ks = key[o]
    same = ks[1:] == ks[:-1]
    return np.stack([fid[o][:-1][same], fid[o][1:][same]], 1)


def detect_planes(mesh: PolyMesh, tol_pct=0.03, seed_angle=1.0, max_angle=10.0, min_area_pct=0.05, rounds=4):
    """Return (per-triangle plane label or -1, planes as (K,2,3) [origin, normal]) for mesh.triangulate()."""
    V = mesh.vertices
    F = mesh.triangulate()
    diag = mesh.diagonal
    dtol = tol_pct / 100.0 * diag
    T, fn, fa = _tri_data(V, F)
    total = fa.sum()
    adj = _adjacency(F, len(V))
    cosd = np.clip((fn[adj[:, 0]] * fn[adj[:, 1]]).sum(1), -1, 1)
    dihedral = np.degrees(np.arccos(cosd))
    nF = len(F)

    # seeds: connected patches of nearly coplanar neighbours
    e = adj[dihedral < seed_angle]
    G = coo_matrix((np.ones(len(e)), (e[:, 0], e[:, 1])), shape=(nF, nF))
    _, comp = connected_components(G, directed=False)
    carea = np.bincount(comp, fa)
    lab = np.full(nF, -1)
    planes = []
    for k in np.flatnonzero(carea > min_area_pct / 100.0 * total):
        f = np.flatnonzero(comp == k)
        c, n = _fit_plane(T[f].reshape(-1, 3), np.repeat(fa[f], 3))
        if (fn[f] @ n).mean() < 0:
            n = -n
        d = np.abs(np.einsum("fkd,d->fk", T[f] - c, n)).max(1)
        good = f[d < dtol]
        if fa[good].sum() > min_area_pct / 100.0 * total:
            lab[good] = len(planes)
            planes.append((c, n))
    if not planes:
        return lab, np.zeros((0, 2, 3))

    cos_max = np.cos(np.radians(max_angle))
    for _ in range(rounds):
        while True:                                  # grow into neighbours that lie on the plane
            a, b = adj[:, 0], adj[:, 1]
            m1 = (lab[a] >= 0) & (lab[b] < 0)
            m2 = (lab[b] >= 0) & (lab[a] < 0)
            cf = np.r_[b[m1], a[m2]]
            cr = np.r_[lab[a[m1]], lab[b[m2]]]
            if not len(cf):
                break
            C = np.array([p[0] for p in planes])
            N = np.array([p[1] for p in planes])
            d = np.abs(np.einsum("fkd,fd->fk", T[cf] - C[cr][:, None], N[cr])).max(1)
            ok = (d < dtol) & ((fn[cf] * N[cr]).sum(1) > cos_max)
            cf, cr, d = cf[ok], cr[ok], d[ok]
            if not len(cf):
                break
            o = np.argsort(d)
            cf, cr = cf[o], cr[o]
            _, first = np.unique(cf, return_index=True)
            lab[cf[first]] = cr[first]
        for k in range(len(planes)):                # refit, then release faces that drifted off
            f = np.flatnonzero(lab == k)
            if len(f):
                c, n = _fit_plane(T[f].reshape(-1, 3), np.repeat(fa[f], 3))
                planes[k] = (c, n if n @ planes[k][1] >= 0 else -n)
        C = np.array([p[0] for p in planes])
        N = np.array([p[1] for p in planes])
        f = np.flatnonzero(lab >= 0)
        d = np.abs(np.einsum("fkd,fd->fk", T[f] - C[lab[f]][:, None], N[lab[f]])).max(1)
        lab[f[d > dtol]] = -1
    return lab, np.array([[p[0], p[1]] for p in planes])


def label_faces(mesh: PolyMesh, ref: PolyMesh, ref_lab, planes, tol, max_angle=15.0):
    """Plane label for each triangle of `mesh` (all-triangle), from the reference surface underneath."""
    from scipy.spatial import cKDTree
    RF = ref.triangulate()
    tree = cKDTree(ref.vertices[RF].mean(1))
    F = mesh.triangulate()
    T, fn, _ = _tri_data(mesh.vertices, F)
    cen = T.mean(1)
    probes = [cen] + [0.5 * cen + 0.5 * T[:, k] for k in range(3)]
    votes = np.stack([ref_lab[tree.query(p, workers=-1)[1]] for p in probes], 1)
    lab = np.full(len(F), -1)
    best = np.full(len(F), np.inf)
    cos_max = np.cos(np.radians(max_angle))
    for j in range(votes.shape[1]):              # every plane seen under the face is a candidate
        cand = votes[:, j]
        f = np.flatnonzero(cand >= 0)
        if not len(f):
            continue
        C, N = planes[cand[f], 0], planes[cand[f], 1]
        d = np.abs(np.einsum("fkd,fd->fk", T[f] - C[:, None], N)).max(1)
        ok = (d < tol) & ((fn[f] * N).sum(1) > cos_max) & (d < best[f])
        lab[f[ok]] = cand[f[ok]]
        best[f[ok]] = d[ok]
    return lab


def _snap_once(V, F, lab, planes, min_angle=8.0):
    N, D = planes[:, 1], (planes[:, 0] * planes[:, 1]).sum(1)
    out = V.copy()
    fv = F.ravel()
    fl = np.repeat(lab, F.shape[1])
    m = fl >= 0
    pairs = np.unique(np.stack([fv[m], fl[m]], 1), axis=0)
    if not len(pairs):
        return out
    cos_par = np.cos(np.radians(min_angle))
    # single-plane points (the vast majority): vectorised projection
    v_ids, start, cnt = np.unique(pairs[:, 0], return_index=True, return_counts=True)
    one = cnt == 1
    v1, l1 = v_ids[one], pairs[start[one], 1]
    out[v1] -= ((V[v1] * N[l1]).sum(1) - D[l1])[:, None] * N[l1]
    for v, s, c in zip(v_ids[~one], start[~one], cnt[~one]):
        ls = pairs[s:s + c, 1]
        keep = [ls[0]]
        for l in ls[1:]:
            if all(abs(N[l] @ N[k]) < cos_par for k in keep):
                keep.append(l)
        A, b = N[keep], D[keep]
        out[v] = V[v] + np.linalg.lstsq(A, b - A @ V[v], rcond=None)[0]
    return out


def flatten(mesh: PolyMesh, reference: PolyMesh, tol_pct=0.03, max_move_pct=0.02, min_area_pct=0.05) -> tuple[PolyMesh, dict]:
    """Snap `mesh` (triangles) onto the flat regions found in `reference`.
    The result carries meta['flat_planes'] (K,2,3) and meta['flat_face_plane'] (per face, -1 = free)."""
    diag = reference.diagonal
    ref_lab, planes = detect_planes(reference, tol_pct=tol_pct, min_area_pct=min_area_pct)
    F = mesh.triangulate()
    out = PolyMesh.from_triangles(mesh.vertices, F, mesh.name)
    out.meta = dict(mesh.meta)
    if not len(planes):
        return out, {"flat_planes": 0}
    lab = label_faces(out, reference, ref_lab, planes, tol=2 * tol_pct / 100.0 * diag)
    V = out.vertices
    max_move = max_move_pct / 100.0 * diag
    on_tol = 3e-7 * diag                          # a flat face's corners must sit on its plane
    for _ in range(12):
        V2 = _snap_once(V, F, lab, planes)
        bad = np.linalg.norm(V2 - V, axis=1) > max_move
        hit = bad[F].any(1) & (lab >= 0)
        f = np.flatnonzero(lab >= 0)
        off = np.abs(np.einsum("fkd,fd->fk", V2[F[f]] - planes[lab[f], 0][:, None], planes[lab[f], 1])).max(1)
        hit[f[off > on_tol]] = True                # e.g. points shared by nearly parallel planes
        if not hit.any():
            break
        lab[hit] = -1
    else:
        V2 = _snap_once(V, F, lab, planes)
    out.vertices = V2
    out.meta["flat_planes"] = planes
    out.meta["flat_face_plane"] = lab
    used = np.unique(lab[lab >= 0])
    tri_area = _tri_data(V2, F)[2]
    return out, {"flat_planes": int(len(used)),
                 "flat_area_pct": round(100.0 * tri_area[lab >= 0].sum() / max(tri_area.sum(), 1e-300), 1)}


# ------------------------------------------------------------------ STEP faces
def _region_loops(F, faces):
    he = np.stack([F[faces].ravel(), F[faces][:, [1, 2, 0]].ravel()], 1)
    s = set(map(tuple, he.tolist()))
    bnd = [(a, b) for a, b in he.tolist() if (b, a) not in s]
    nxt = {}
    for a, b in bnd:
        nxt.setdefault(a, []).append(b)
    loops, used = [], set()
    for a, b in bnd:
        if (a, b) in used:
            continue
        loop, cur = [a], (a, b)
        while cur not in used:
            used.add(cur)
            loop.append(cur[1])
            c = cur[1]
            cands = [x for x in nxt.get(c, []) if (c, x) not in used]
            if not cands:
                break
            cur = (c, cands[0])
        if loop[-1] == loop[0]:
            loop = loop[:-1]
        loops.append(loop)
    return loops


def _merged_once(mesh: PolyMesh, lab, drop_collinear: bool = True):
    """Faces for the STEP writer: list of (loops, normal, origin). Each flat region
    becomes one face (outer loop + holes); free triangles stay single faces.
    Points lying only on the straight line where two flat faces meet are dropped
    (only where both faces see the same two neighbours, so the shell stays closed)."""
    F = mesh.triangulate()
    V = mesh.vertices
    planes = np.asarray(mesh.meta["flat_planes"])
    nv = len(V)
    bad_v = set()
    vl = [set() for _ in range(nv)]
    free_v = np.zeros(nv, bool)
    free_v[F[lab < 0].ravel()] = True
    for f in np.flatnonzero(lab >= 0):
        for v in F[f]:
            vl[v].add(int(lab[f]))
    adj = _adjacency(F, nv)
    same = (lab[adj[:, 0]] == lab[adj[:, 1]]) & (lab[adj[:, 0]] >= 0)
    e = adj[same]
    G = coo_matrix((np.ones(len(e)), (e[:, 0], e[:, 1])), shape=(len(F), len(F)))
    _, comp = connected_components(G, directed=False)
    flat = np.flatnonzero(lab >= 0)
    flat = flat[np.argsort(comp[flat], kind="stable")]
    cuts = np.flatnonzero(np.diff(comp[flat])) + 1
    pieces = []
    for piece in np.split(flat, cuts):
        if len(piece):
            pieces.append((piece, _region_loops(F, piece)))
    drop = np.zeros(nv, bool)
    if drop_collinear:
        cand = np.array([len(s) == 2 and not free_v[i] for i, s in enumerate(vl)])
        seen = {}
        for _, loops in pieces:
            for lp in loops:
                for k, v in enumerate(lp):
                    if cand[v]:
                        seen.setdefault(v, []).append(frozenset((lp[k - 1], lp[(k + 1) % len(lp)])))
        ekeys = set()
        for a, b in np.concatenate([F[:, [0, 1]], F[:, [1, 2]], F[:, [2, 0]]]).tolist():
            ekeys.add((a, b) if a < b else (b, a))
        tol = 1e-6 * max(mesh.diagonal, 1e-12)
        for v, nbs in seen.items():
            if len(nbs) == 2 and nbs[0] == nbs[1] and len(nbs[0]) == 2:
                a, b = sorted(nbs[0])
                if (a, b) in ekeys:                      # u-w already an edge: dropping would duplicate it
                    continue
                d = V[b] - V[a]
                t = np.clip((V[v] - V[a]) @ d / max(d @ d, 1e-300), 0, 1)
                if np.linalg.norm(V[a] + t * d - V[v]) <= tol and 0 < t < 1:
                    drop[v] = True
    out = []
    for piece, loops in pieces:
        o, n = planes[lab[piece[0]]]
        loops = [[v for v in lp if not drop[v]] for lp in loops]

        def sarea(lp):
            P = V[lp]
            return 0.5 * np.dot(np.cross(P, np.roll(P, -1, 0)).sum(0), n)
        areas = [sarea(lp) for lp in loops] if all(len(lp) >= 3 for lp in loops) else []
        pinched = sum(len(lp) for lp in loops) != len(set(v for lp in loops for v in lp))
        if (not areas or pinched or sum(a > 0 for a in areas) != 1
                or min(abs(a) for a in areas) < 1e-12 * mesh.diagonal ** 2):
            # loops touching at a point or degenerate: keep this region as triangles
            seen_v = {}
            for lp in loops:
                for v in lp:
                    seen_v[v] = seen_v.get(v, 0) + 1
            bad_v.update(v for v, c in seen_v.items() if c > 1)
            if not areas or min(abs(a) for a in areas) < 1e-12 * mesh.diagonal ** 2:
                bad_v.update(v for lp in loops if len(lp) < 3 or abs(sarea(lp)) < 1e-12 * mesh.diagonal ** 2
                             for v in lp)
            for f in piece:
                P = V[F[f]]
                nn = np.cross(P[1] - P[0], P[2] - P[0])
                ln = np.linalg.norm(nn)
                if ln > 1e-300:
                    out.append(([list(F[f])], nn / ln, P.mean(0)))
            continue
        loops = [lp for _, lp in sorted(zip(areas, loops), key=lambda t: -t[0])]
        out.append((loops, n, o))
    for f in np.flatnonzero(lab < 0):
        P = V[F[f]]
        nn = np.cross(P[1] - P[0], P[2] - P[0])
        ln = np.linalg.norm(nn)
        if ln > 1e-300:
            out.append(([list(F[f])], nn / ln, P.mean(0)))
    return out, bad_v


def merged_faces(mesh: PolyMesh, drop_collinear: bool = True):
    """Faces for the STEP writer: list of (loops, normal, origin). Each flat region
    becomes one face (outer loop + holes); free triangles stay single faces.
    Where a region's border touches itself at a single point (a pinch), the few
    triangles around that point are handed back to the free area and the region is
    merged again, so one bad spot does not cost the whole face."""
    lab = np.asarray(mesh.meta["flat_face_plane"]).copy()
    F = mesh.triangulate()
    for _ in range(6):
        out, bad_v = _merged_once(mesh, lab, drop_collinear)
        if not bad_v:
            break
        bv = np.zeros(mesh.n_vertices, bool)
        bv[list(bad_v)] = True
        lab[bv[F].any(1)] = -1
    return out


def _closed(faces) -> bool:
    use = {}
    for loops, _, _ in faces:
        for lp in loops:
            for k in range(len(lp)):
                a, b = lp[k], lp[(k + 1) % len(lp)]
                key = (a, b) if a < b else (b, a)
                use[key] = use.get(key, 0) + 1
    return bool(use) and all(c == 2 for c in use.values())


def write_step_merged(mesh: PolyMesh, path: str, unit: str = "MM", make_solid: bool = True, progress=None) -> dict:
    """STEP writer for meshes from flatten(): one PLANE face per flat region (with holes),
    one PLANE face per remaining triangle, all edges shared, closed shell -> solid."""
    import datetime as _dt
    from .step_fast import _UNITS, _fmt_reals, _points, _Writer
    if progress:
        progress(0.05, "STEP: merging flat faces")
    faces = merged_faces(mesh)
    if not _closed(faces):                       # never trade a closed solid for fewer faces
        faces = merged_faces(mesh, drop_collinear=False)
    if not _closed(faces):
        lab = np.full(mesh.n_faces, -1)
        faces, _ = _merged_once(mesh, lab)
    V = mesh.vertices
    w = _Writer()
    name = (mesh.name or "StepConverter").replace("'", "")
    w.add("APPLICATION_PROTOCOL_DEFINITION('international standard','automotive_design',2000,#2)")
    w.add("APPLICATION_CONTEXT('core data for automotive mechanical design processes')")
    w.add("SHAPE_DEFINITION_REPRESENTATION(#4,#10)")
    w.add("PRODUCT_DEFINITION_SHAPE('','',#5)")
    w.add("PRODUCT_DEFINITION('design','',#6,#9)")
    w.add("PRODUCT_DEFINITION_FORMATION('','',#7)")
    w.add(f"PRODUCT('{name}','{name}','',(#8))")
    w.add("PRODUCT_CONTEXT('',#2,'mechanical')")
    w.add("PRODUCT_DEFINITION_CONTEXT('part definition',#2,'design')")
    rep_id = w.reserve()
    w.add("AXIS2_PLACEMENT_3D('',#12,#13,#14)")
    w.add("CARTESIAN_POINT('',(0.,0.,0.))")
    w.add("DIRECTION('',(0.,0.,1.))")
    w.add("DIRECTION('',(1.,0.,0.))")
    body_id, shell_id, ctx_id = w.reserve(), w.reserve(), w.reserve()
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

    used = sorted({v for f in faces for lp in f[0] for v in lp})
    pts = _points(V[used])
    vid = {}
    for v, p in zip(used, pts):
        cp = w.add(f"CARTESIAN_POINT('',{p})")
        vid[v] = (cp, w.add(f"VERTEX_POINT('',#{cp})"))
    edges, use = {}, {}

    def edge(a, b):
        k = (a, b) if a < b else (b, a)
        e = edges.get(k)
        if e is None:
            c = w.add(f"B_SPLINE_CURVE_WITH_KNOTS('',1,(#{vid[k[0]][0]},#{vid[k[1]][0]}),.UNSPECIFIED.,.F.,.F.,"
                      "(2,2),(0.,1.),.PIECEWISE_BEZIER_KNOTS.)")
            e = edges[k] = w.add(f"EDGE_CURVE('',#{vid[k[0]][1]},#{vid[k[1]][1]},#{c},.T.)")
        use[k] = use.get(k, 0) + 1
        return e, a > b

    face_ids = []
    n_flat = 0
    for i, (loops, n, o) in enumerate(faces):
        x = np.cross(n, [1.0, 0, 0]) if abs(n[0]) < 0.9 else np.cross(n, [0, 1.0, 0])
        x /= np.linalg.norm(x)
        r = _fmt_reals(np.concatenate([o, n, x]))
        p = w.add(f"CARTESIAN_POINT('',({r[0]},{r[1]},{r[2]}))")
        d1 = w.add(f"DIRECTION('',({r[3]},{r[4]},{r[5]}))")
        d2 = w.add(f"DIRECTION('',({r[6]},{r[7]},{r[8]}))")
        ax = w.add(f"AXIS2_PLACEMENT_3D('',#{p},#{d1},#{d2})")
        pl = w.add(f"PLANE('',#{ax})")
        bounds = []
        for j, lp in enumerate(loops):
            oes = []
            for k in range(len(lp)):
                e, rev = edge(lp[k], lp[(k + 1) % len(lp)])
                oes.append(w.add(f"ORIENTED_EDGE('',*,*,#{e},{'.F.' if rev else '.T.'})"))
            el = w.add(f"EDGE_LOOP('',({','.join('#%d' % x for x in oes)}))")
            bounds.append(w.add(f"{'FACE_OUTER_BOUND' if j == 0 else 'FACE_BOUND'}('',#{el},.T.)"))
        face_ids.append(w.add(f"ADVANCED_FACE('',({','.join('#%d' % x for x in bounds)}),#{pl},.T.)"))
        n_flat += len(loops[0]) > 3 or len(loops) > 1
        if progress and i % 20000 == 0:
            progress(0.1 + 0.8 * i / max(len(faces), 1), f"STEP: faces {i:,}/{len(faces):,}")
    closed = bool(use) and all(c == 2 for c in use.values())
    fl = ",".join(f"#{i}" for i in face_ids)
    if closed and make_solid:
        w.set(shell_id, f"CLOSED_SHELL('',({fl}))")
        w.set(body_id, f"MANIFOLD_SOLID_BREP('',#{shell_id})")
        w.set(rep_id, f"ADVANCED_BREP_SHAPE_REPRESENTATION('',(#11,#{body_id}),#{ctx_id})")
    else:
        w.set(shell_id, f"OPEN_SHELL('',({fl}))")
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
    return dict(flat_faces=int(n_flat), faces=len(face_ids), closed=closed, solid=bool(closed and make_solid))


# ------------------------------------------------------------------ refine free areas
def refine_free_areas(mesh: PolyMesh, reference: PolyMesh, trials: int = 50000, seed: int = 0,
                      progress=None) -> tuple[PolyMesh, dict]:
    """Random edge flips in the free (non-flat) areas: swap the diagonal shared by two free
    triangles and keep the swap only when the pair fits the reference surface better.
    Points never move, so flat faces, borders and the face count stay exactly as they are."""
    import trimesh
    from scipy.spatial import cKDTree
    from trimesh.triangles import closest_point as tc
    lab = np.asarray(mesh.meta["flat_face_plane"])
    free = lab < 0
    F = mesh.triangulate().copy()
    V = mesh.vertices
    if free.sum() < 2:
        return mesh, {"flips": 0}
    rtm = reference.to_trimesh()
    free_area = 0.5 * np.linalg.norm(np.cross(V[F[free, 1]] - V[F[free, 0]], V[F[free, 2]] - V[F[free, 0]]), axis=1).sum()
    n_s = int(min(400000, max(20000, 400000 * free_area / max(rtm.area, 1e-300))))
    sp, sf = trimesh.sample.sample_surface(rtm, int(n_s / max(free_area / rtm.area, 1e-3)), seed=seed)
    sn = rtm.face_normals[sf]
    _, near = cKDTree(V[F].mean(1)).query(sp, workers=-1)
    keep = free[near]
    sp, sn, near = sp[keep], sn[keep], near[keep]
    if not len(sp):
        return mesh, {"flips": 0}
    stree = cKDTree(sp)
    s_w = free_area / len(sp)
    probe = np.array([[1 / 3, 1 / 3, 1 / 3], [2 / 3, 1 / 6, 1 / 6], [1 / 6, 2 / 3, 1 / 6], [1 / 6, 1 / 6, 2 / 3]])

    def err(tris, S):
        T = V[np.array(tris)]
        e = 0.0
        if len(S):
            d = np.min([((tc(np.repeat(T[j][None], len(S), 0), sp[S]) - sp[S]) ** 2).sum(1)
                        for j in range(len(T))], 0)
            e += d.sum() * s_w
        P = np.einsum("pk,fkd->fpd", probe, T).reshape(-1, 3)
        _, i = stree.query(P)
        dd = ((P - sp[i]) * sn[i]).sum(1)
        a = 0.5 * np.linalg.norm(np.cross(T[:, 1] - T[:, 0], T[:, 2] - T[:, 0]), axis=1)
        return e + (dd.reshape(len(T), 4) ** 2 * (a[:, None] / 4)).sum()

    emap = {}
    for f, t in enumerate(F.tolist()):
        for k in range(3):
            emap[(t[k], t[(k + 1) % 3])] = f
    samples = {}
    for s, f in enumerate(near.tolist()):
        samples.setdefault(f, []).append(s)
    cand = [(a, b) for (a, b), f in emap.items() if a < b and free[f] and free[emap.get((b, a), f)]]
    rng = np.random.default_rng(seed)
    flips = 0
    for t in range(trials):
        if progress and t % 5000 == 0:
            progress(t / trials, f"Refining free areas {t:,}/{trials:,}")
        a, b = cand[rng.integers(len(cand))]
        f1, f2 = emap.get((a, b)), emap.get((b, a))
        if f1 is None or f2 is None or f1 == f2 or not (free[f1] and free[f2]):
            continue
        t1, t2 = F[f1].tolist(), F[f2].tolist()
        c = [x for x in t1 if x not in (a, b)][0]
        d = [x for x in t2 if x not in (a, b)][0]
        if c == d or (c, d) in emap or (d, c) in emap:
            continue
        n_old = np.cross(V[t1[1]] - V[t1[0]], V[t1[2]] - V[t1[0]]) + np.cross(V[t2[1]] - V[t2[0]], V[t2[2]] - V[t2[0]])
        new1, new2 = (c, a, d), (d, b, c)
        nn1 = np.cross(V[a] - V[c], V[d] - V[c])
        nn2 = np.cross(V[b] - V[d], V[c] - V[d])
        if nn1 @ n_old <= 0 or nn2 @ n_old <= 0 or nn1 @ nn2 <= 0:
            continue
        S = samples.get(f1, []) + samples.get(f2, [])
        if err([new1, new2], S) >= err([tuple(t1), tuple(t2)], S):
            continue
        for k in range(3):
            emap.pop((t1[k], t1[(k + 1) % 3]), None)
            emap.pop((t2[k], t2[(k + 1) % 3]), None)
        F[f1], F[f2] = new1, new2
        for f in (f1, f2):
            tt = F[f].tolist()
            for k in range(3):
                emap[(tt[k], tt[(k + 1) % 3])] = f
        cand.append((min(c, d), max(c, d)))
        if S:
            Sa = np.array(S)
            d1 = ((tc(np.repeat(V[list(new1)][None], len(Sa), 0), sp[Sa]) - sp[Sa]) ** 2).sum(1)
            d2 = ((tc(np.repeat(V[list(new2)][None], len(Sa), 0), sp[Sa]) - sp[Sa]) ** 2).sum(1)
            samples[f1], samples[f2] = Sa[d1 <= d2].tolist(), Sa[d1 > d2].tolist()
        flips += 1
    out = PolyMesh.from_triangles(V, F, mesh.name)
    out.meta = dict(mesh.meta)
    return out, {"refine_flips": flips}
