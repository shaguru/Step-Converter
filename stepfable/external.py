"""Optional external remeshers: Blender (QuadriFlow, OpenVDB voxel remesh)
and Instant Meshes. StepFable works without them; they show up in the UI
when found."""
from __future__ import annotations

import glob
import os
import re
import shutil
import subprocess
import tempfile

from .mesh import PolyMesh


# ------------------------------------------------------------------ discovery
def find_blender(explicit: str | None = None) -> str | None:
    if explicit and os.path.isfile(explicit):
        return explicit
    env = os.environ.get("STEPFABLE_BLENDER")
    if env and os.path.isfile(env):
        return env
    cands = []
    for root in [r"C:\Program Files\Blender Foundation", r"C:\Program Files (x86)\Blender Foundation",
                 os.path.expanduser(r"~\AppData\Local\Programs\Blender Foundation")]:
        cands += glob.glob(os.path.join(root, "*", "blender.exe"))
    cands += glob.glob(r"C:\Program Files (x86)\Steam\steamapps\common\Blender\blender.exe")

    def ver(p):
        m = re.search(r"(\d+)\.(\d+)", p)
        return (int(m.group(1)), int(m.group(2))) if m else (0, 0)

    if cands:
        return sorted(cands, key=ver)[-1]
    return shutil.which("blender")


def find_instant_meshes(explicit: str | None = None) -> str | None:
    if explicit and os.path.isfile(explicit):
        return explicit
    from .paths import tools_dirs
    cands = [os.environ.get("STEPFABLE_INSTANT_MESHES", "")]
    for d in tools_dirs():
        cands += [os.path.join(d, "Instant Meshes.exe"), os.path.join(d, "instant-meshes", "Instant Meshes.exe")]
    for p in cands:
        if p and os.path.isfile(p):
            return p
    return shutil.which("Instant Meshes") or shutil.which("instant-meshes")


# ------------------------------------------------------------------ Blender
_BLENDER_SCRIPT = r'''
import bpy, sys, json
args = json.loads(sys.argv[sys.argv.index("--") + 1])
bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.wm.obj_import(filepath=args["inp"])
obj = bpy.context.selected_objects[0]
bpy.context.view_layer.objects.active = obj
if args["op"] == "voxel":
    obj.data.remesh_voxel_size = args["voxel_size"]
    obj.data.remesh_voxel_adaptivity = args.get("adaptivity", 0.0)
    bpy.ops.object.voxel_remesh()
elif args["op"] == "quadriflow":
    res = bpy.ops.object.quadriflow_remesh(
        mode="FACES", target_faces=int(args["target_faces"]),
        use_preserve_sharp=args.get("preserve_sharp", False),
        use_preserve_boundary=args.get("preserve_boundary", True),
        use_mesh_symmetry=args.get("symmetry", False),
        smooth_normals=False, seed=int(args.get("seed", 0)))
    print("QUADRIFLOW", res)
bpy.ops.wm.obj_export(filepath=args["out"], export_selected_objects=False,
                      export_materials=False, export_uv=False, export_normals=False,
                      forward_axis="NEGATIVE_Z", up_axis="Y")
'''


def run_blender(mesh: PolyMesh, op: str, blender: str | None = None, timeout: int = 1800, **kw) -> PolyMesh:
    import json
    from .io_formats import _load_obj, _save_obj
    exe = find_blender(blender)
    if not exe:
        raise RuntimeError("Blender not found. Set its path in Settings.")
    with tempfile.TemporaryDirectory(prefix="stepfable_") as tmp:
        inp, out, script = (os.path.join(tmp, n) for n in ("in.obj", "out.obj", "run.py"))
        _save_obj(mesh, inp)
        with open(script, "w") as fh:
            fh.write(_BLENDER_SCRIPT)
        args = json.dumps(dict(inp=inp, out=out, op=op, **kw))
        # Blender's OBJ importer turns Y-up files into Z-up; exporting with the
        # matching axes round-trips coordinates unchanged.
        proc = subprocess.run([exe, "-b", "--factory-startup", "--python", script, "--", args],
                              capture_output=True, text=True, timeout=timeout,
                              creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        if not os.path.isfile(out):
            raise RuntimeError("Blender failed:\n" + (proc.stdout[-2000:] + proc.stderr[-2000:]))
        res = _load_obj(out)
    res.name = mesh.name
    return res


# ------------------------------------------------------------ Instant Meshes
def run_instant_meshes(mesh: PolyMesh, target_faces: int, exe: str | None = None,
                       crease_angle: float = 0.0, smooth_iters: int = 2, pure_quad: bool = True,
                       align_boundaries: bool = True, timeout: int = 1800) -> PolyMesh:
    from .io_formats import _load_obj, _save_obj
    exe = find_instant_meshes(exe)
    if not exe:
        raise RuntimeError("Instant Meshes not found. Put 'Instant Meshes.exe' in the app's tools folder or set it in Settings.")
    with tempfile.TemporaryDirectory(prefix="stepfable_") as tmp:
        inp, out = os.path.join(tmp, "in.obj"), os.path.join(tmp, "out.obj")
        _save_obj(mesh, inp)
        cmd = [exe, "-o", out, "-f", str(int(target_faces)), "-S", str(int(smooth_iters)), "-d"]
        if crease_angle > 0:
            cmd += ["-c", str(float(crease_angle))]
        if not pure_quad:
            cmd += ["-D"]
        if align_boundaries:
            cmd += ["-b"]
        cmd.append(inp)
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout,
                              creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        if not os.path.isfile(out):
            raise RuntimeError("Instant Meshes failed:\n" + proc.stdout[-2000:] + proc.stderr[-2000:])
        res = _load_obj(out)
    res.name = mesh.name
    return res
