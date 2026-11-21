"""Where things live, both when run from source and inside the packaged .exe."""
from __future__ import annotations

import os
import sys

FROZEN = getattr(sys, "frozen", False)


def resource_dir() -> str:
    """Bundled read-only files (presets, docs, samples)."""
    if FROZEN:
        return getattr(sys, "_MEIPASS", os.path.dirname(sys.executable))
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def app_dir() -> str:
    """Folder of the program itself (next to the .exe, or the repo root)."""
    if FROZEN:
        return os.path.dirname(os.path.abspath(sys.executable))
    return resource_dir()


def user_dir() -> str:
    base = os.environ.get("APPDATA") or os.path.expanduser("~")
    d = os.path.join(base, "StepConverter")
    os.makedirs(d, exist_ok=True)
    return d


def bundled_presets_dir() -> str:
    return os.path.join(resource_dir(), "presets")


def user_presets_dir() -> str:
    """Saved presets: the repo's presets folder from source, AppData in the .exe."""
    d = os.path.join(user_dir(), "presets") if FROZEN else bundled_presets_dir()
    os.makedirs(d, exist_ok=True)
    return d


def docs_path(name: str) -> str:
    return os.path.join(resource_dir(), "docs", name)


def tools_dirs() -> list[str]:
    return [os.path.join(app_dir(), "tools"), os.path.join(user_dir(), "tools")]
