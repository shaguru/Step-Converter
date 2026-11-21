"""Minimal binary FBX 7.4 writer for static polygon meshes.

Writes one Model + Geometry per mesh with polygons kept as-is (quads stay
quads). No materials, skinning or animation: StepFable deals in geometry.
"""
from __future__ import annotations

import struct
import zlib

import numpy as np

_HEADER = b"Kaydara FBX Binary  \x00\x1a\x00"
_VERSION = 7400
_FOOT_ID = b"\xfa\xbc\xab\x09\xd0\xc8\xd4\x66\xb1\x76\xfb\x83\x1c\xf7\x26\x7e"
_FOOT_MAGIC = b"\xf8\x5a\x8c\x6a\xde\xf5\xd9\x7e\xec\xe9\x0c\xe3\x75\x8f\x29\x0b"


class _Node:
    def __init__(self, name, *props):
        self.name = name.encode("ascii")
        self.props = list(props)
        self.children = []

    def add(self, name, *props):
        n = _Node(name, *props)
        self.children.append(n)
        return n

    # ---- property encoding
    @staticmethod
    def _enc(p) -> bytes:
        if isinstance(p, tuple) and p and p[0] == "raw_str":
            b = p[1]
            return b"S" + struct.pack("<I", len(b)) + b
        if isinstance(p, bool):
            return b"C" + struct.pack("<?", p)
        if isinstance(p, (int, np.integer)) and not isinstance(p, bool):
            p = int(p)
            if -2**31 <= p < 2**31:
                return b"I" + struct.pack("<i", p)
            return b"L" + struct.pack("<q", p)
        if isinstance(p, tuple) and p and p[0] == "L":
            return b"L" + struct.pack("<q", int(p[1]))
        if isinstance(p, (float, np.floating)):
            return b"D" + struct.pack("<d", float(p))
        if isinstance(p, str):
            b = p.encode("utf-8")
            return b"S" + struct.pack("<I", len(b)) + b
        if isinstance(p, np.ndarray):
            code = {np.dtype("float64"): b"d", np.dtype("float32"): b"f",
                    np.dtype("int32"): b"i", np.dtype("int64"): b"l"}[p.dtype]
            raw = np.ascontiguousarray(p).tobytes()
            data = zlib.compress(raw, 1) if len(raw) > 128 else raw
            enc = 1 if len(raw) > 128 else 0
            return code + struct.pack("<III", len(p), enc, len(data)) + data
        raise TypeError(f"Unsupported FBX property {type(p)}")

    def encode(self, offset: int) -> bytes:
        props = b"".join(self._enc(p) for p in self.props)
        head_len = 13 + len(self.name)
        body_start = offset + head_len + len(props)
        chunks, pos = [], body_start
        for c in self.children:
            b = c.encode(pos)
            chunks.append(b)
            pos += len(b)
        if self.children or not self.props:
            chunks.append(b"\x00" * 13)
            pos += 13
        head = struct.pack("<IIIB", pos, len(self.props), len(props), len(self.name)) + self.name
        return head + props + b"".join(chunks)


def _p70(parent, entries):
    p = parent.add("Properties70")
    for e in entries:
        p.add("P", *e)
    return p


def write_fbx(meshes, path: str, unit_scale_cm: float = 1.0, up_axis: str = "Y"):
    """Write one or more PolyMesh objects to a binary FBX file.

    unit_scale_cm: how many centimetres one unit of the coordinates is
    (FBX native unit is cm: 1 = cm, 0.1 = mm, 100 = metres).
    """
    if not isinstance(meshes, (list, tuple)):
        meshes = [meshes]
    up = 1 if up_axis.upper() == "Y" else 2
    front = 2 if up == 1 else 1
    front_sign = 1 if up == 1 else -1

    top = []
    hdr = _Node("FBXHeaderExtension")
    hdr.add("FBXHeaderVersion", 1003)
    hdr.add("FBXVersion", _VERSION)
    hdr.add("Creator", "Step Converter")
    top.append(hdr)

    gs = _Node("GlobalSettings")
    gs.add("Version", 1000)
    _p70(gs, [
        ("UpAxis", "int", "Integer", "", up),
        ("UpAxisSign", "int", "Integer", "", 1),
        ("FrontAxis", "int", "Integer", "", front),
        ("FrontAxisSign", "int", "Integer", "", front_sign),
        ("CoordAxis", "int", "Integer", "", 0),
        ("CoordAxisSign", "int", "Integer", "", 1),
        ("OriginalUpAxis", "int", "Integer", "", up),
        ("OriginalUpAxisSign", "int", "Integer", "", 1),
        ("UnitScaleFactor", "double", "Number", "", float(unit_scale_cm)),
        ("OriginalUnitScaleFactor", "double", "Number", "", float(unit_scale_cm)),
    ])
    top.append(gs)

    docs = _Node("Documents")
    docs.add("Count", 1)
    d = docs.add("Document", ("L", 1000000000), "", "Scene")
    d.add("RootNode", ("L", 0))
    top.append(docs)
    top.append(_Node("References"))

    defs = _Node("Definitions")
    defs.add("Version", 100)
    defs.add("Count", 1 + 2 * len(meshes))
    defs.add("ObjectType", "GlobalSettings").add("Count", 1)
    defs.add("ObjectType", "Model").add("Count", len(meshes))
    defs.add("ObjectType", "Geometry").add("Count", len(meshes))
    top.append(defs)

    objs = _Node("Objects")
    conns = _Node("Connections")
    next_id = 2000000
    for m in meshes:
        gid, mid = next_id, next_id + 1
        next_id += 2
        name = (m.name or "mesh").replace("\x00", "")
        geo = objs.add("Geometry", ("L", gid), ("raw_str", name.encode() + b"\x00\x01Geometry"), "Mesh")
        geo.add("Vertices", np.ascontiguousarray(m.vertices, dtype=np.float64).ravel())
        idx = m.face_indices.astype(np.int32).copy()
        last = m.offsets[1:] - 1
        idx[last] = -idx[last] - 1
        geo.add("PolygonVertexIndex", idx)
        geo.add("GeometryVersion", 124)
        layer = geo.add("Layer", 0)
        layer.add("Version", 100)

        mdl = objs.add("Model", ("L", mid), ("raw_str", name.encode() + b"\x00\x01Model"), "Mesh")
        mdl.add("Version", 232)
        _p70(mdl, [("DefaultAttributeIndex", "int", "Integer", "", 0)])
        mdl.add("Shading", True)
        mdl.add("Culling", "CullingOff")

        conns.add("C", "OO", ("L", gid), ("L", mid))
        conns.add("C", "OO", ("L", mid), ("L", 0))
    top += [objs, conns]

    out = bytearray(_HEADER + struct.pack("<I", _VERSION))
    for n in top:
        out += n.encode(len(out))
    out += b"\x00" * 13
    out += _FOOT_ID + b"\x00" * 4
    pad = ((len(out) + 15) & ~15) - len(out)
    out += b"\x00" * (pad or 16)
    out += struct.pack("<I", _VERSION) + b"\x00" * 120 + _FOOT_MAGIC
    with open(path, "wb") as fh:
        fh.write(out)
