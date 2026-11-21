"""FBX import.

Primary: ufbx (keeps quads and n-gons, handles axis/unit conversion). The
current ufbx Python binding can crash the interpreter when its objects are
garbage collected, so it runs in a short-lived child process that hands the
arrays back through a temporary .npz file and exits without cleanup.

Fallback: assimp (triangulated) if the child process fails.
"""
from __future__ import annotations

import os
import sys
import tempfile

import numpy as np

from .mesh import PolyMesh


def load_fbx(path: str) -> PolyMesh:
    try:
        return _load_via_child(path)
    except Exception as first_error:
        try:
            return _load_assimp(path)
        except Exception:
            raise RuntimeError(f"Could not read FBX: {first_error}") from first_error


def _load_via_child(path: str) -> PolyMesh:
    """Read the FBX in a separate process (works from source and in the packaged .exe)."""
    import multiprocessing as mp
    fd, out = tempfile.mkstemp(suffix=".npz", prefix="stepconverter_fbx_")
    os.close(fd)
    try:
        ctx = mp.get_context("spawn")
        proc = ctx.Process(target=_child_entry, args=(path, out))
        proc.start()
        proc.join(900)
        if proc.is_alive():
            proc.terminate()
            raise RuntimeError("FBX reader timed out")
        if proc.exitcode != 0 or os.path.getsize(out) == 0:
            raise RuntimeError(f"FBX reader stopped (exit code {proc.exitcode})")
        d = np.load(out)
        return PolyMesh(d["vertices"], d["sizes"].astype(np.int32), d["indices"].astype(np.int64)).compact()
    finally:
        try:
            os.remove(out)
        except OSError:
            pass


def _child_entry(path: str, out: str):
    try:
        _child(path, out)
        code = 0
    except BaseException as exc:  # noqa: BLE001
        sys.stderr.write(f"FBX reader: {exc}\n")
        code = 1
    sys.stdout.flush()
    sys.stderr.flush()
    os._exit(code)          # skip interpreter teardown (avoids the ufbx GC crash)


def _child(path: str, out: str):
    import gc
    import zipfile  # noqa: F401  (np.savez needs it; import before ufbx objects exist)
    gc.disable()    # ufbx objects break the cyclic garbage collector
    import ufbx
    # Load options (axis/unit conversion) crash the current binding, so the
    # file is read as authored and only node transforms are applied.
    scene = ufbx.load_file(path)
    verts, sizes, idx, off = [], [], [], 0
    for node in scene.nodes:
        mesh = node.mesh
        if mesh is None:
            continue
        vl = mesh.vertices
        V = np.array([(p.x, p.y, p.z) for p in vl], dtype=np.float64).reshape(-1, 3)
        vi = mesh.vertex_indices
        VI = np.fromiter((vi[i] for i in range(len(vi))), dtype=np.int64, count=len(vi))
        fl = mesh.faces
        nf = len(fl)
        begins = np.fromiter((fl[i].index_begin for i in range(nf)), dtype=np.int64, count=nf)
        counts = np.fromiter((fl[i].num_indices for i in range(nf)), dtype=np.int64, count=nf)
        ok = counts >= 3
        begins, counts = begins[ok], counts[ok]
        sel = np.repeat(begins, counts) + (np.arange(counts.sum()) - np.repeat(np.cumsum(counts) - counts, counts))
        m = node.geometry_to_world
        M = np.eye(4)
        for c in range(4):
            col = getattr(m, f"c{c}")
            M[:3, c] = (col.x, col.y, col.z)
        V = V @ M[:3, :3].T + M[:3, 3]
        F = VI[sel]
        if np.linalg.det(M[:3, :3]) < 0:     # mirrored node: flip winding per face
            starts = np.cumsum(counts) - counts
            F = F.copy()
            for s, c in zip(starts, counts):
                F[s:s + c] = F[s:s + c][::-1]
        verts.append(V)
        sizes.append(counts)
        idx.append(F + off)
        off += len(V)
    if not verts:
        raise SystemExit("FBX contains no meshes")
    np.savez(out, vertices=np.vstack(verts), sizes=np.concatenate(sizes), indices=np.concatenate(idx))


def _load_assimp(path: str) -> PolyMesh:
    import assimp_py
    flags = assimp_py.Process_Triangulate | assimp_py.Process_JoinIdenticalVertices | \
        assimp_py.Process_PreTransformVertices
    scene = assimp_py.import_file(path, flags)
    parts = []
    for m in scene.meshes:
        V = np.frombuffer(m.vertices, dtype=np.float32).astype(np.float64).reshape(-1, 3)
        F = np.frombuffer(m.indices, dtype=np.uint32).astype(np.int64).reshape(-1, 3)
        parts.append(PolyMesh.from_triangles(V, F))
    if not parts:
        raise ValueError("FBX contains no meshes")
    return PolyMesh.concatenate(parts).merge_vertices()


if __name__ == "__main__":
    _child_entry(sys.argv[1], sys.argv[2])
