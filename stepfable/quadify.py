"""StepFable's own triangle -> quad algorithms (pure NumPy, always available).

pair_triangles     greedy "best pairs first" matching of neighbouring
                   triangles into quads; scores favour square, flat, convex
                   quads and never merge across a sharp feature edge.
subdivide_to_quads one linear Catmull-Clark style split: every quad -> 4
                   quads, every leftover triangle -> 3 quads, so the result
                   is 100% quads with no triangles left.
relax_and_project  tangential smoothing that evens out quad sizes, followed
                   by snapping every vertex back onto a reference surface so
                   the shape stays accurate.
"""
from __future__ import annotations

import numpy as np
from scipy.sparse import coo_matrix

from .mesh import PolyMesh


def _unit(v):
    n = np.linalg.norm(v, axis=-1, keepdims=True)
    return v / np.maximum(n, 1e-30)


# ------------------------------------------------------------------ pairing
def pair_triangles(mesh: PolyMesh, feature_angle: float = 40.0,
                   max_corner_angle: float = 160.0, planarity_weight: float = 1.0) -> PolyMesh:
    """Merge triangle pairs into quads. Existing quads/n-gons are kept."""
    tris = mesh.faces_of_size(3)
    others = [mesh.faces_of_size(k) for k in np.unique(mesh.face_sizes) if k != 3]
    V = mesh.vertices
    T = len(tris)
    if T < 2:
        return mesh.copy()

    # half-edges of triangles: (face, local corner) edge = tri[c] -> tri[c+1]
    a = tris.ravel()
    b = tris[:, [1, 2, 0]].ravel()
    face = np.repeat(np.arange(T), 3)
    corner = np.tile(np.arange(3), T)
    lo, hi = np.minimum(a, b), np.maximum(a, b)
    key = lo.astype(np.int64) * (V.shape[0] + 1) + hi
    order = np.argsort(key, kind="stable")
    ks = key[order]
    _, start, cnt = np.unique(ks, return_index=True, return_counts=True)
    first = start[cnt == 2]                     # manifold interior edges only
    h1, h2 = order[first], order[first + 1]
    f1, f2 = face[h1], face[h2]
    ok = (f1 != f2) & (a[h1] == b[h2])          # consistently oriented neighbours
    h1, h2, f1, f2 = h1[ok], h2[ok], f1[ok], f2[ok]

    c1 = corner[h1]
    A = tris[f1, c1]
    B = tris[f1, (c1 + 1) % 3]
    C = tris[f1, (c1 + 2) % 3]
    D = tris[f2, (corner[h2] + 2) % 3]
    quads = np.stack([A, D, B, C], axis=1)

    # ---- scoring
    n1 = _unit(np.cross(V[B] - V[A], V[C] - V[A]))
    n2 = _unit(np.cross(V[A] - V[B], V[D] - V[B]))
    dihedral = np.degrees(np.arccos(np.clip((n1 * n2).sum(1), -1, 1)))
    P = V[quads]                                       # (E,4,3)
    e_next = _unit(np.roll(P, -1, axis=1) - P)
    e_prev = _unit(np.roll(P, 1, axis=1) - P)
    cosang = (e_next * e_prev).sum(-1)                 # cos of corner angle
    ang = np.degrees(np.arccos(np.clip(cosang, -1, 1)))
    qn = n1 + n2
    convex = np.ones(len(quads), bool)
    for i in range(4):
        cr = np.cross(e_next[:, i], e_prev[:, i])     # along +normal at convex CCW corners
        convex &= (cr * qn).sum(1) > 0
    score = np.abs(cosang).sum(1) + planarity_weight * (dihedral / 90.0)
    valid = convex & (dihedral <= feature_angle) & (ang.max(1) <= max_corner_angle)

    idx = np.flatnonzero(valid)
    idx = idx[np.argsort(score[idx], kind="stable")]
    used = np.zeros(T, bool)
    chosen = []
    F1, F2 = f1, f2
    for e in idx:                                      # greedy matching
        x, y = F1[e], F2[e]
        if used[x] or used[y]:
            continue
        used[x] = used[y] = True
        chosen.append(e)
    chosen = np.asarray(chosen, dtype=np.int64)
    q = quads[chosen] if len(chosen) else np.zeros((0, 4), np.int64)
    left = tris[~used]
    polys_sizes = [np.full(len(left), 3), np.full(len(q), 4)]
    polys_idx = [left.ravel(), q.ravel()]
    for o in others:
        polys_sizes.append(np.full(len(o), o.shape[1]))
        polys_idx.append(o.ravel())
    return PolyMesh(V.copy(), np.concatenate(polys_sizes).astype(np.int32),
                    np.concatenate(polys_idx).astype(np.int64), mesh.name, dict(mesh.meta))


# -------------------------------------------------------------- subdivision
def subdivide_to_quads(mesh: PolyMesh) -> PolyMesh:
    """Linear split: n-gon -> n quads (corner, edge mid, centre, edge mid)."""
    V = mesh.vertices
    he = mesh.edges()
    lo, hi = np.minimum(he[:, 0], he[:, 1]), np.maximum(he[:, 0], he[:, 1])
    key = lo * (len(V) + 1) + hi
    uniq, inv = np.unique(key, return_inverse=True)
    ea, eb = uniq // (len(V) + 1), uniq % (len(V) + 1)
    edge_pts = 0.5 * (V[ea] + V[eb])
    o = mesh.offsets
    face_of_corner = np.repeat(np.arange(mesh.n_faces), mesh.face_sizes)
    centroids = np.zeros((mesh.n_faces, 3))
    np.add.at(centroids, face_of_corner, V[mesh.face_indices])
    centroids /= mesh.face_sizes[:, None]

    nv, ne = len(V), len(uniq)
    newV = np.vstack([V, edge_pts, centroids])
    # for each corner i of a face: quad (v_i, e_i, c, e_{i-1}) where e_i = edge i->i+1
    corner_edge = inv + nv                                  # edge after corner
    prev = np.arange(len(he)) - 1
    prev[o[:-1]] = o[1:] - 1                                # wrap around per face
    quads = np.stack([mesh.face_indices, corner_edge, nv + ne + face_of_corner, corner_edge[prev]], axis=1)
    return PolyMesh.from_quads(newV, quads, mesh.name)


# ---------------------------------------------------------- relax + project
class SurfaceProjector:
    """Fast point -> surface projection for dense reference meshes.

    Uses the nearest reference points and their normals (point-to-plane).
    For sculpt-density references this is within a fraction of the sculpt's
    own edge length; if the reference is coarse, it is densified first.
    """

    def __init__(self, ref: PolyMesh, target_spacing: float | None = None):
        from scipy.spatial import cKDTree
        pts = ref.vertices
        nrm = vertex_normals(ref)
        if target_spacing and ref.n_faces:
            tris = ref.triangulate()
            V = ref.vertices
            cr = np.cross(V[tris[:, 1]] - V[tris[:, 0]], V[tris[:, 2]] - V[tris[:, 0]])
            areas = 0.5 * np.linalg.norm(cr, axis=1)
            area = areas.sum()
            elen = np.sqrt(2.0 * area / max(len(tris), 1))         # typical edge length
            if elen > target_spacing * 1.5:
                # densify coarse references so nearest-point projection stays accurate
                count = int(min(4e6, area / (target_spacing ** 2) * 2))
                rng = np.random.default_rng(0)
                fid = rng.choice(len(tris), size=count, p=areas / area)
                r1, r2 = rng.random((2, count))
                flip = r1 + r2 > 1
                r1[flip], r2[flip] = 1 - r1[flip], 1 - r2[flip]
                t = tris[fid]
                sp = V[t[:, 0]] + r1[:, None] * (V[t[:, 1]] - V[t[:, 0]]) + r2[:, None] * (V[t[:, 2]] - V[t[:, 0]])
                pts = np.vstack([pts, sp])
                nrm = np.vstack([nrm, _unit(cr[fid])])
        self.pts, self.nrm = pts, nrm
        self.tree = cKDTree(self.pts, leafsize=24, balanced_tree=False, compact_nodes=False)

    def project(self, P: np.ndarray, k: int = 3) -> np.ndarray:
        d, i = self.tree.query(P, k=k, workers=-1)
        if k == 1:
            i = i[:, None]
            d = d[:, None]
        w = 1.0 / np.maximum(d, 1e-12)
        w /= w.sum(1, keepdims=True)
        base = np.einsum("nk,nkd->nd", w, self.pts[i])
        n = _unit(np.einsum("nk,nkd->nd", w, self.nrm[i]))
        return P - np.einsum("nd,nd->n", P - base, n)[:, None] * n

    def distance(self, P: np.ndarray) -> np.ndarray:
        return np.linalg.norm(self.project(P) - P, axis=1)


def vertex_adjacency(mesh: PolyMesh):
    he = mesh.edges()
    n = mesh.n_vertices
    A = coo_matrix((np.ones(len(he) * 2), (np.r_[he[:, 0], he[:, 1]], np.r_[he[:, 1], he[:, 0]])),
                   shape=(n, n)).tocsr()
    A.data[:] = 1.0
    return A


def boundary_vertices(mesh: PolyMesh) -> np.ndarray:
    he = mesh.edges()
    lo, hi = np.minimum(he[:, 0], he[:, 1]), np.maximum(he[:, 0], he[:, 1])
    key = lo * (mesh.n_vertices + 1) + hi
    u, c = np.unique(key, return_counts=True)
    b = u[c == 1]
    mask = np.zeros(mesh.n_vertices, bool)
    mask[b // (mesh.n_vertices + 1)] = True
    mask[b % (mesh.n_vertices + 1)] = True
    return mask


def vertex_normals(mesh: PolyMesh) -> np.ndarray:
    """Area-weighted vertex normals for any polygons (Newell's method), pure NumPy."""
    V = mesh.vertices
    he = mesh.edges()
    c = np.cross(V[he[:, 0]], V[he[:, 1]])                  # per half-edge contribution
    face = np.repeat(np.arange(mesh.n_faces), mesh.face_sizes)
    fn = np.stack([np.bincount(face, c[:, k], minlength=mesh.n_faces) for k in range(3)], axis=1)
    corner_n = fn[face]
    vn = np.stack([np.bincount(mesh.face_indices, corner_n[:, k], minlength=len(V)) for k in range(3)], axis=1)
    return _unit(vn)


def relax_and_project(mesh: PolyMesh, projector: SurfaceProjector | None, iterations: int = 5,
                      strength: float = 0.5, fix_boundary: bool = True) -> PolyMesh:
    out = mesh.copy()
    if iterations <= 0:
        if projector is not None:
            out.vertices = projector.project(out.vertices)
        return out
    A = vertex_adjacency(out)
    deg = np.asarray(A.sum(1)).ravel()
    fixed = boundary_vertices(out) if fix_boundary else np.zeros(out.n_vertices, bool)
    for _ in range(iterations):
        V = out.vertices
        avg = (A @ V) / np.maximum(deg, 1)[:, None]
        n = vertex_normals(out)
        d = avg - V
        d -= (d * n).sum(1, keepdims=True) * n          # tangential only
        d[fixed] = 0
        out.vertices = V + strength * d
        if projector is not None:
            P = projector.project(out.vertices)
            P[fixed] = out.vertices[fixed]
            out.vertices = P
    return out
