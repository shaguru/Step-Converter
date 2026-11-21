# PyInstaller spec for Step Converter.
#   pyinstaller packaging/step_converter.spec                 -> dist/StepConverter/  (folder app)
#   set STEPCONV_ONEFILE=1 & pyinstaller packaging/...spec   -> dist/StepConverter.exe (single file)
import os
import sys
from PyInstaller.utils.hooks import collect_all, collect_data_files, collect_dynamic_libs

ROOT = os.path.abspath(os.path.join(SPECPATH, ".."))
ONEFILE = os.environ.get("STEPCONV_ONEFILE") == "1"
CONSOLE = os.environ.get("STEPCONV_CONSOLE") == "1"   # debug builds

datas = [
    (os.path.join(ROOT, "presets"), "presets"),
    (os.path.join(ROOT, "docs"), "docs"),
    (os.path.join(ROOT, "samples", "monkeyGeo.fbx"), "samples"),
    (os.path.join(ROOT, "LICENSE"), "."),
]
binaries = []
hiddenimports = ["OCP.OCP", "stepfable.tasks", "stepfable.cli", "stepfable.app",
                 "scipy.spatial._ckdtree", "pyvistaqt"]

# Packages with native plugins or data files that PyInstaller can't find by itself.
for pkg in ("pymeshlab", "ufbx", "assimp_py", "trimesh"):
    d, b, h = collect_all(pkg)
    datas += d
    binaries += b
    hiddenimports += h
binaries += collect_dynamic_libs("OCP")
datas += collect_data_files("pyvista")

excludes = ["tkinter", "skimage", "networkx", "IPython", "jupyter", "notebook", "pytest",
            "PySide6.QtWebEngineCore", "PySide6.QtWebEngineWidgets", "PySide6.Qt3DCore",
            "PySide6.QtQuick", "PySide6.QtQml", "PySide6.QtMultimedia", "PySide6.QtPdf",
            "PyQt5", "PyQt6"]

a = Analysis(
    [os.path.join(ROOT, "step_converter.py")],
    pathex=[ROOT],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    excludes=excludes,
    noarchive=False,
)
pyz = PYZ(a.pure)
icon = os.path.join(ROOT, "packaging", "icon.ico")
icon = icon if os.path.isfile(icon) else None

if ONEFILE:
    exe = EXE(pyz, a.scripts, a.binaries, a.datas, [],
              name="StepConverter", console=CONSOLE, icon=icon, upx=False,
              disable_windowed_traceback=not CONSOLE,
              runtime_tmpdir=None)
else:
    exe = EXE(pyz, a.scripts, [], exclude_binaries=True,
              name="StepConverter", console=CONSOLE, icon=icon, upx=False,
              disable_windowed_traceback=not CONSOLE)
    coll = COLLECT(exe, a.binaries, a.datas, name="StepConverter", upx=False)
