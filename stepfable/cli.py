"""Command line / batch use.

  python -m stepfable convert in.fbx out.step [out.stl ...] [--preset P.json]
                              [--step-mode smooth|auto|triangles] [--unit MM] [--scale 1]
  python -m stepfable remesh  in.obj out.obj --preset presets/"01 Sculpt to CNC - smooth STEP.json"
"""
from __future__ import annotations

import argparse
import json
import os
import sys

from . import io_formats
from .remesh import RemeshParams, run_pipeline


def main(argv=None):
    ap = argparse.ArgumentParser(prog="stepfable", description="Convert and remesh 3D models.")
    ap.add_argument("command", choices=["convert", "remesh"],
                    help="convert = as-is; remesh = run the quad pipeline first")
    ap.add_argument("input")
    ap.add_argument("outputs", nargs="+")
    ap.add_argument("--preset", help="JSON preset with remesh parameters")
    ap.add_argument("--set", action="append", default=[], metavar="NAME=VALUE",
                    help="override one remesh parameter, e.g. --set target_faces=5000")
    ap.add_argument("--step-mode", default="smooth", choices=["smooth", "auto", "triangles"])
    ap.add_argument("--unit", default="MM")
    ap.add_argument("--scale", type=float, default=1.0)
    ap.add_argument("--report", help="write the accuracy report as JSON here")
    a = ap.parse_args(argv if argv is not None else sys.argv[1:])

    def prog(f, t):
        print(f"\r[{f * 100:5.1f}%] {t:<60}", end="", flush=True)

    mesh = io_formats.load(a.input)
    print(f"Loaded {a.input}: {mesh.stats()}")
    if a.command == "remesh":
        p = RemeshParams.load(a.preset) if a.preset else RemeshParams()
        d = p.to_dict()
        for s in a.set:
            k, v = s.split("=", 1)
            try:
                d[k] = json.loads(v)          # numbers, true/false
            except ValueError:
                d[k] = v                      # plain words like "isotropic"
        p = RemeshParams.from_dict(d)
        mesh, rep = run_pipeline(mesh, p, progress=prog)
        print()
        for k in ["faces", "quad_pct", "irregular_pct", "dev_mean_pct", "dev_p95_pct", "dev_max_pct", "seconds"]:
            if k in rep:
                print(f"  {k:15s} {rep[k]}")
        if a.report:
            with open(a.report, "w") as fh:
                json.dump(rep, fh, indent=2)
    if a.scale != 1.0:
        mesh.vertices = mesh.vertices * a.scale
    for out in a.outputs:
        mode = a.step_mode
        if mode == "smooth" and not (mesh.face_sizes == 4).all():
            mode = "auto"
        io_formats.save(mesh, out, step_mode=mode, step_unit=a.unit, progress=prog)
        print(f"\nWrote {os.path.abspath(out)}")


if __name__ == "__main__":
    main()
