"""Core polygon mesh container used everywhere in StepFable.

A PolyMesh keeps arbitrary polygons (triangles, quads, n-gons) in a compact
"sizes + flat indices" layout, the same layout VTK/PyVista uses, so quads
survive every step of the pipeline instead of being silently triangulated.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np


@dataclass
class PolyMesh:
    vertices: np.ndarray                      # (N, 3) float64
    face_sizes: np.ndarray                    # (F,) int32, polygon sizes
    face_indices: np.ndarray                  # (sum(face_sizes),) int64
    name: str = "mesh"
    meta: dict = field(default_factory=dict)

    # ------------------------------------------------------------------ build
    @staticmethod
    def from_triangles(vertices, triangles, name="mesh") -> "PolyMesh":
        tri = np.asarray(triangles, dtype=np.int64).reshape(-1, 3)
        return PolyMesh(np.asarray(vertices, dtype=np.float64).reshape(-1, 3),
                        np.full(len(tri), 3, dtype=np.int32), tri.ravel(), name)

    @staticmethod
    def from_quads(vertices, quads, name="mesh") -> "PolyMesh":
        q = np.asarray(quads, dtype=np.int64).reshape(-1, 4)
        return PolyMesh(np.asarray(vertices, dtype=np.float64).reshape(-1, 3),
                        np.full(len(q), 4, dtype=np.int32), q.ravel(), name)

    @staticmethod
    def from_polygons(vertices, polygons, name="mesh") -> "PolyMesh":
        sizes = np.fromiter((len(p) for p in polygons), dtype=np.int32, count=len(polygons))
        flat = np.fromiter((i for p in polygons for i in p), dtype=np.int64, count=int(sizes.sum()))
        return PolyMesh(np.asarray(vertices, dtype=np.float64).reshape(-1, 3), sizes, flat, name)

    @staticmethod
    def from_tris_and_quads(vertices, tris, quads, name="mesh") -> "PolyMesh":
        tris = np.asarray(tris, dtype=np.int64).reshape(-1, 3)
        quads = np.asarray(quads, dtype=np.int64).reshape(-1, 4)
        sizes = np.concatenate([np.full(len(tris), 3), np.full(len(quads), 4)]).astype(np.int32)
        flat = np.concatenate([tris.ravel(), quads.ravel()])
        return PolyMesh(np.asarray(vertices, dtype=np.float64), sizes, flat, name)

    @staticmethod
    def concatenate(meshes, name="merged") -> "PolyMesh":
        meshes = [m for m in meshes if m.n_faces]
        if not meshes:
            return PolyMesh(np.zeros((0, 3)), np.zeros(0, np.int32), np.zeros(0, np.int64), name)
        verts, sizes, idx, off = [], [], [], 0
        for m in meshes:
            verts.append(m.vertices)
            sizes.append(m.face_sizes)
            idx.append(m.face_indices + off)
            off += len(m.vertices)
        return PolyMesh(np.vstack(verts), np.concatenate(sizes), np.concatenate(idx), name)

    def copy(self) -> "PolyMesh":
        return PolyMesh(self.vertices.copy(), self.face_sizes.copy(), self.face_indices.copy(),
                        self.name, dict(self.meta))

    # ------------------------------------------------------------- properties
    @property
    def n_vertices(self) -> int:
        return len(self.vertices)

    @property
    def n_faces(self) -> int:
        return len(self.face_sizes)

    @property
    def offsets(self) -> np.ndarray:
        o = np.zeros(len(self.face_sizes) + 1, dtype=np.int64)
        np.cumsum(self.face_sizes, out=o[1:])
        return o

    def faces_of_size(self, k: int) -> np.ndarray:
        """(M, k) array of all faces with exactly k corners."""
        mask = self.face_sizes == k
        if not mask.any():
            return np.zeros((0, k), dtype=np.int64)
        starts = self.offsets[:-1][mask]
        return self.face_indices[starts[:, None] + np.arange(k)[None, :]]

    def polygons(self):
        o = self.offsets
        fi = self.face_indices
        return [fi[o[i]:o[i + 1]] for i in range(self.n_faces)]

    @property
    def bounds(self):
        if not len(self.vertices):
            return np.zeros(3), np.zeros(3)
        return self.vertices.min(0), self.vertices.max(0)

    @property
    def diagonal(self) -> float:
        lo, hi = self.bounds
        return float(np.linalg.norm(hi - lo))

    # -------------------------------------------------------------- converters
    def triangulate(self) -> np.ndarray:
        """Fan-triangulate every polygon. Quads are split on the shorter diagonal."""
        out = [self.faces_of_size(3)]
        q = self.faces_of_size(4)
        if len(q):
            v = self.vertices
            d02 = np.linalg.norm(v[q[:, 0]] - v[q[:, 2]], axis=1)
            d13 = np.linalg.norm(v[q[:, 1]] - v[q[:, 3]], axis=1)
            use02 = d02 <= d13
            a = np.where(use02[:, None], q[:, [0, 1, 2]], q[:, [0, 1, 3]])
            b = np.where(use02[:, None], q[:, [0, 2, 3]], q[:, [1, 2, 3]])
            out += [a, b]
        big = np.unique(self.face_sizes[self.face_sizes > 4])
        for k in big:
            p = self.faces_of_size(int(k))
            for j in range(1, k - 1):
                out.append(p[:, [0, j, j + 1]])
        return np.vstack(out) if out else np.zeros((0, 3), dtype=np.int64)

    def to_trimesh(self, process=False):
        import trimesh
        return trimesh.Trimesh(self.vertices, self.triangulate(), process=process)

    @staticmethod
    def from_trimesh(tm, name="mesh") -> "PolyMesh":
        return PolyMesh.from_triangles(np.asarray(tm.vertices), np.asarray(tm.faces), name)

    def to_pyvista(self):
        import pyvista as pv
        cells = np.empty(self.n_faces + len(self.face_indices), dtype=np.int64)
        o = self.offsets
        pos = o[:-1] + np.arange(self.n_faces)
        cells[pos] = self.face_sizes
        mask = np.ones(len(cells), bool)
        mask[pos] = False
        cells[mask] = self.face_indices
        return pv.PolyData(self.vertices, cells)

    # ------------------------------------------------------------------- tidy
    def compact(self) -> "PolyMesh":
        """Drop unreferenced vertices and degenerate faces (repeated corners)."""
        keep = np.ones(self.n_faces, bool)
        o = self.offsets
        for k in np.unique(self.face_sizes):
            mask = self.face_sizes == k
            f = self.face_indices[o[:-1][mask][:, None] + np.arange(k)]
            s = np.sort(f, axis=1)
            bad = (s[:, 1:] == s[:, :-1]).any(axis=1) if k > 1 else np.zeros(len(f), bool)
            keep[np.flatnonzero(mask)[bad]] = False
        sizes = self.face_sizes[keep]
        idx_mask = np.repeat(keep, self.face_sizes)
        idx = self.face_indices[idx_mask]
        used = np.zeros(self.n_vertices, bool)
        used[idx] = True
        remap = np.cumsum(used) - 1
        return PolyMesh(self.vertices[used], sizes, remap[idx], self.name, dict(self.meta))

    def merge_vertices(self, tol: float = 0.0) -> "PolyMesh":
        """Weld vertices closer than tol (0 = exact duplicates)."""
        v = self.vertices
        if tol > 0:
            key = np.round(v / tol).astype(np.int64)
        else:
            key = v
        _, first, inv = np.unique(key, axis=0, return_index=True, return_inverse=True)
        inv = inv.ravel()
        out = PolyMesh(v[first], self.face_sizes.copy(), inv[self.face_indices], self.name, dict(self.meta))
        return out.compact()

    def transformed(self, matrix4) -> "PolyMesh":
        m = np.asarray(matrix4, dtype=np.float64)
        v = self.vertices @ m[:3, :3].T + m[:3, 3]
        out = self.copy()
        out.vertices = v
        if np.linalg.det(m[:3, :3]) < 0:   # mirrored: flip winding
            out = out.flipped()
        return out

    def flipped(self) -> "PolyMesh":
        o = self.offsets
        idx = self.face_indices.copy()
        for i in range(self.n_faces):
            idx[o[i]:o[i + 1]] = idx[o[i]:o[i + 1]][::-1]
        return PolyMesh(self.vertices.copy(), self.face_sizes.copy(), idx, self.name, dict(self.meta))

    def edges(self) -> np.ndarray:
        """All directed half-edges as (E, 2)."""
        o = self.offsets
        nxt = np.arange(len(self.face_indices)) + 1
        ends = o[1:] - 1
        nxt[ends] = o[:-1]
        return np.stack([self.face_indices, self.face_indices[nxt]], axis=1)

    def stats(self) -> dict:
        sizes = self.face_sizes
        n = max(self.n_faces, 1)
        return {
            "vertices": int(self.n_vertices),
            "faces": int(self.n_faces),
            "triangles": int((sizes == 3).sum()),
            "quads": int((sizes == 4).sum()),
            "ngons": int((sizes > 4).sum()),
            "quad_pct": 100.0 * float((sizes == 4).sum()) / n,
        }
