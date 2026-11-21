"""Accuracy and quad-quality metrics, so remesh settings can be compared."""
from __future__ import annotations

import numpy as np

from .mesh import PolyMesh


def _sample(mesh: PolyMesh, n: int, seed: int = 0):
    import trimesh
    tm = mesh.to_trimesh()
    pts, fid = trimesh.sample.sample_surface(tm, n, seed=seed)
    return np.asarray(pts), np.asarray(tm.face_normals)[fid]


def surface_deviation(result: PolyMesh, reference: PolyMesh, samples: int = 60000) -> dict:
    """Two-sided, sampled surface distance (point-to-plane), in model units
    and as % of the reference bounding-box diagonal."""
    from scipy.spatial import cKDTree
    diag = max(reference.diagonal, 1e-12)
    pr, nr = _sample(reference, samples, 1)
    ps, ns = _sample(result, samples, 2)
    tr, ts = cKDTree(pr), cKDTree(ps)

    def one_way(P, tree, Q, NQ):
        _, i = tree.query(P, k=1, workers=-1)
        d_pt = np.linalg.norm(P - Q[i], axis=1)
        d_pl = np.abs(((P - Q[i]) * NQ[i]).sum(1))
        # point-to-plane is the better estimate but never more than point distance
        return np.minimum(d_pt, np.where(np.isfinite(d_pl), d_pl, d_pt))

    d1 = one_way(ps, tr, pr, nr)     # result -> reference
    d2 = one_way(pr, ts, ps, ns)     # reference -> result (catches lost detail)
    d = np.concatenate([d1, d2])
    out = {
        "mean": float(d.mean()),
        "rms": float(np.sqrt((d ** 2).mean())),
        "p95": float(np.percentile(d, 95)),
        "max": float(d.max()),
    }
    for k in list(out):
        out[k + "_pct"] = 100.0 * out[k] / diag
    return out


def quad_quality(mesh: PolyMesh) -> dict:
    st = mesh.stats()
    q = mesh.faces_of_size(4)
    res = dict(st)
    if len(q):
        P = mesh.vertices[q]
        e_next = np.roll(P, -1, axis=1) - P
        e_prev = np.roll(P, 1, axis=1) - P
        cos = (e_next * e_prev).sum(-1) / np.maximum(
            np.linalg.norm(e_next, axis=-1) * np.linalg.norm(e_prev, axis=-1), 1e-30)
        ang = np.degrees(np.arccos(np.clip(cos, -1, 1)))
        res["angle_dev_mean"] = float(np.abs(ang - 90).mean())
        lens = np.linalg.norm(e_next, axis=-1)
        res["aspect_mean"] = float((lens.max(1) / np.maximum(lens.min(1), 1e-30)).mean())
    # valence: interior vertices of a clean quad mesh want 4 edges
    he = mesh.edges()
    lo, hi = np.minimum(he[:, 0], he[:, 1]), np.maximum(he[:, 0], he[:, 1])
    u = np.unique(lo * (mesh.n_vertices + 1) + hi)
    val = np.bincount(np.r_[u // (mesh.n_vertices + 1), u % (mesh.n_vertices + 1)], minlength=mesh.n_vertices)
    res["irregular_vertices"] = int((val != 4).sum())
    res["irregular_pct"] = 100.0 * res["irregular_vertices"] / max(mesh.n_vertices, 1)
    return res


def full_report(result: PolyMesh, original: PolyMesh, samples: int = 60000) -> dict:
    rep = quad_quality(result)
    rep.update({f"dev_{k}": v for k, v in surface_deviation(result, original, samples).items()})
    return rep
