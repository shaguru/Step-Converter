"""Small persistent settings file (tool paths, last folders)."""
from __future__ import annotations

import json
import os

_PATH = os.path.join(os.path.expanduser("~"), ".stepfable.json")
DEFAULTS = {
    "blender": "",
    "instant_meshes": "",
    "last_open_dir": "",
    "last_export_dir": "",
    "export_formats": [".step", ".stl"],
    "step_mode": "smooth",
    "step_unit": "MM",
    "step_sharp_angle": 50.0,
    "wire_max_faces": 1500000,
}


def load() -> dict:
    d = dict(DEFAULTS)
    try:
        with open(_PATH) as fh:
            d.update(json.load(fh))
    except (OSError, ValueError):
        pass
    return d


def save(d: dict):
    try:
        with open(_PATH, "w") as fh:
            json.dump(d, fh, indent=2)
    except OSError:
        pass
