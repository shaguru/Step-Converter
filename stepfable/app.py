"""Step Converter desktop UI (PySide6 + PyVista)."""
from __future__ import annotations

import glob
import os
import sys
from dataclasses import fields

import numpy as np
from PySide6.QtCore import QObject, QSize, Qt, QThread, Signal
from PySide6.QtGui import QAction, QColor, QKeySequence
from PySide6.QtWidgets import (QAbstractItemView, QApplication, QCheckBox, QComboBox, QDialog,
                               QDialogButtonBox, QDoubleSpinBox, QFileDialog, QFormLayout,
                               QGroupBox, QHBoxLayout, QHeaderView, QInputDialog, QLabel,
                               QLineEdit, QListWidget, QListWidgetItem, QMainWindow, QMessageBox,
                               QProgressBar, QPushButton, QScrollArea, QSpinBox, QSplitter,
                               QTableWidget, QTableWidgetItem, QToolBar, QVBoxLayout, QWidget)

from . import help_text, io_formats, paths, settings
from .external import find_blender, find_instant_meshes
from .mesh import PolyMesh
from .remesh import (QUAD_METHODS, REDUCE_METHODS, SMOOTH_METHODS, VOXEL_ENGINES, Cancelled,
                     RemeshParams)
from .tasks import run_compare_parallel, run_in_process


# ------------------------------------------------------------------ parameter UI spec
# name: (label, kind, extra, tooltip)
PARAM_UI = [
    ("1  Cleanup", [
        ("cleanup", "Enable cleanup", "bool", None, "Weld duplicates, remove debris and non-manifold bits, close small holes."),
        ("weld_tolerance_pct", "Weld distance %", "float", (0, 2, 0.01, 3), "Merge vertices closer than this % of the model size. 0 = exact duplicates only."),
        ("min_component_pct", "Drop pieces smaller than %", "float", (0, 50, 0.5, 1), "Floating fragments smaller than this % of the model size are deleted."),
        ("close_holes_max_edges", "Close holes up to (edges)", "int", (0, 100000, 10), "Fill holes whose border has at most this many edges. 0 keeps holes."),
    ]),
    ("2  Voxel remesh", [
        ("voxel", "Enable voxel remesh", "bool", None, "Rebuild everything as one watertight surface (like Blender's voxel remesh). Fixes self-intersections and overlapping shells."),
        ("voxel_engine", "Engine", "choice", VOXEL_ENGINES, "Built-in needs nothing extra. Blender uses OpenVDB (faster on huge meshes)."),
        ("voxel_size_pct", "Voxel size %", "float", (0.05, 5, 0.05, 2), "Smaller = more detail, slower. % of model size."),
    ]),
    ("3  Smooth bumps", [
        ("smooth_method", "Method", "choice", SMOOTH_METHODS, "Taubin smooths without shrinking. Feature-preserving keeps creases sharp."),
        ("smooth_iterations", "Iterations", "int", (0, 500, 1), "More = smoother surface (and more detail lost)."),
        ("smooth_feature_angle", "Crease angle °", "float", (1, 180, 1, 0), "Feature-preserving only: normals differing more than this count as creases."),
    ]),
    ("4  Reduce", [
        ("reduce_method", "Method", "choice", REDUCE_METHODS, "Isotropic gives even triangles = better quads. Quadric keeps most detail per face."),
        ("target_faces", "Target faces", "int", (100, 5000000, 500), "Final face count you want."),
        ("isotropic_iterations", "Isotropic iterations", "int", (1, 50, 1), "Isotropic only: more = more even."),
        ("preserve_boundary", "Keep open borders", "bool", None, "Don't move border edges of open meshes."),
    ]),
    ("5  Quads", [
        ("quad_method", "Method", "choice", QUAD_METHODS, "How triangles become quads."),
        ("quad_feature_angle", "Don't pair across °", "float", (1, 180, 1, 0), "Built-in pairing never merges triangles across edges sharper than this."),
        ("quadriflow_preserve_sharp", "QuadriFlow: keep sharp", "bool", None, ""),
        ("quadriflow_symmetry", "QuadriFlow: use symmetry", "bool", None, ""),
        ("instant_crease_angle", "Instant Meshes crease °", "float", (0, 180, 1, 0), "0 = off."),
        ("instant_smooth_iters", "Instant Meshes smoothing", "int", (0, 10, 1), ""),
    ]),
    ("6  Relax + snap", [
        ("relax_iterations", "Relax iterations", "int", (0, 100, 1), "Evens out quad sizes; every step snaps back onto the surface."),
        ("relax_strength", "Relax strength", "float", (0, 1, 0.05, 2), ""),
        ("project_to", "Snap to", "choice", {"smoothed": "Smoothed surface", "original": "Original sculpt", "none": "Don't snap"},
         "Smoothed keeps the bumps removed; Original hugs the raw sculpt."),
    ]),
    ("7  Measure", [
        ("measure", "Measure accuracy", "bool", None, "Compare the result to the original after every run."),
        ("measure_samples", "Samples", "int", (2000, 2000000, 10000), "More = more precise numbers, slower."),
    ]),
]

REPORT_COLUMNS = [("Run", None), ("Faces", "faces"), ("Quads %", "quad_pct"), ("Irregular %", "irregular_pct"),
                  ("Angle dev °", "angle_dev_mean"), ("Mean dev %", "dev_mean_pct"), ("95% dev %", "dev_p95_pct"),
                  ("Max dev %", "dev_max_pct"), ("Mean dev", "dev_mean"), ("Time s", "seconds")]


# ------------------------------------------------------------------ workers
class Worker(QObject):
    """Runs a stepfable.tasks job in a child process and relays progress."""
    progress = Signal(float, str)
    done = Signal(object)
    failed = Signal(str)

    def __init__(self, target, *args, **kw):
        super().__init__()
        self.target, self.args, self.kw = target, args, kw
        self.cancel = False

    def run(self):
        try:
            if callable(self.target):        # runs here and starts its own worker processes
                res = self.target(*self.args, progress=self.progress.emit,
                                  cancelled=lambda: self.cancel, **self.kw)
            else:
                res = run_in_process(self.target, *self.args, progress=self.progress.emit,
                                     cancelled=lambda: self.cancel, **self.kw)
            self.done.emit(res)
        except Cancelled:
            self.failed.emit("Cancelled")
        except Exception as exc:
            self.failed.emit(str(exc))


# ------------------------------------------------------------------ viewer
class Viewer(QWidget):
    BG = "#232427"
    COLORS = ("#a29f99", "#8f969e")          # original: warm ash, result: cool ash
    WIRE = "#1b1c1f"

    def __init__(self, parent=None):
        super().__init__(parent)
        import pyvista as pv
        from pyvistaqt import QtInteractor
        pv.global_theme.background = self.BG
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        self.plotter = QtInteractor(self, shape=(1, 2), border=False)
        lay.addWidget(self.plotter.interactor)
        self.show_edges = True
        self.wire_max_faces = 1_500_000
        self.smooth_preview = False
        self.heatmap = False
        self._proj = None                 # cached projector onto the original
        self.meshes = [None, None]
        self.infos = ["", ""]
        for i, title in enumerate(["Original", "Result"]):
            self.plotter.subplot(0, i)
            self.plotter.add_text(title, font_size=10, color="#d0d0d0", name=f"title{i}")
        self.plotter.link_views()

    def set_mesh(self, slot: int, mesh: PolyMesh | None, info: str = ""):
        if slot == 0:
            self._proj = None
        self.meshes[slot] = mesh
        self.infos[slot] = info
        self._draw(slot, reset_camera=(slot == 0 or self.meshes[0] is None))

    def _draw(self, slot, reset_camera=False):
        import pyvista as pv
        p = self.plotter
        p.subplot(0, slot)
        ren = p.renderers[slot]          # plotter.remove_actor would clear every viewport
        for name in (f"mesh{slot}", f"wire{slot}", f"info{slot}"):
            ren.remove_actor(name)
        m = self.meshes[slot]
        if m is None or m.n_faces == 0:
            p.render()
            return
        smooth = slot == 1 and self.smooth_preview and (m.face_sizes == 4).all()
        show = m
        if smooth:
            from .smooth_surface import tessellate
            show = tessellate(m, 3)
        pd = show.to_pyvista()
        kw = dict(color=self.COLORS[slot])
        if slot == 1 and self.heatmap and self.meshes[0] is not None:
            # distance of every result point from the original sculpt, as % of model size
            from .quadify import SurfaceProjector
            if self._proj is None:
                self._proj = SurfaceProjector(self.meshes[0])
            diag = max(self.meshes[0].diagonal, 1e-12)
            pd["deviation %"] = 100.0 * self._proj.distance(np.asarray(pd.points)) / diag
            hi = float(np.percentile(pd["deviation %"], 99)) or 1e-6
            kw = dict(scalars="deviation %", cmap="turbo", clim=[0, hi],
                      scalar_bar_args=dict(title="dev %", color="#d0d0d0", n_labels=3, title_font_size=12,
                                           label_font_size=10, vertical=True, position_x=0.88,
                                           position_y=0.25, height=0.45, width=0.06))
        actor = p.add_mesh(pd, name=f"mesh{slot}", smooth_shading=smooth, specular=0.15,
                           diffuse=0.85, ambient=0.12, **kw)
        # push the surface back a little so the wireframe drawn on it stays visible
        try:
            actor.mapper.SetResolveCoincidentTopologyToPolygonOffset()
            actor.mapper.SetRelativeCoincidentTopologyPolygonOffsetParameters(1.0, 1.0)
        except Exception:
            pass
        if not (slot == 1 and self.heatmap):
            try:
                p.remove_scalar_bar("dev %")
            except Exception:
                pass
        # wireframe overlay: the quad cage, drawn on the smooth surface when previewing
        if self.show_edges and m.n_faces <= self.wire_max_faces:
            if smooth:
                from .smooth_surface import edge_polylines
                pts, cells = edge_polylines(m)
                wire = pv.PolyData(pts, lines=cells)
            else:
                wire = m.to_pyvista().extract_all_edges()
            p.add_mesh(wire, name=f"wire{slot}", color=self.WIRE, line_width=1, opacity=0.7,
                       lighting=False)
        st = m.stats()
        txt = f"{st['faces']:,} faces   {st['quad_pct']:.0f}% quads"
        if self.show_edges and m.n_faces > self.wire_max_faces:
            txt += "   (wireframe hidden: too many faces)"
        info = self.infos[slot]
        p.add_text(txt + ("\n" + info if info else ""), position="lower_left", font_size=8,
                   color="#d0d0d0", name=f"info{slot}")
        if reset_camera:
            p.reset_camera()
        p.render()

    def redraw(self):
        for i in range(2):
            self._draw(i)

    def reset(self):
        self.plotter.subplot(0, 0)
        self.plotter.reset_camera()
        self.plotter.render()


# ------------------------------------------------------------------ settings dialog
class SettingsDialog(QDialog):
    def __init__(self, cfg, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Step Converter settings")
        self.cfg = cfg
        form = QFormLayout(self)
        self.blender = QLineEdit(cfg.get("blender") or (find_blender() or ""))
        self.im = QLineEdit(cfg.get("instant_meshes") or (find_instant_meshes() or ""))
        self.wire = QSpinBox()
        self.wire.setRange(1000, 50_000_000)
        self.wire.setSingleStep(100_000)
        self.wire.setGroupSeparatorShown(True)
        self.wire.setValue(int(cfg.get("wire_max_faces", 1_500_000)))
        self.wire.setToolTip("Above this many faces the wireframe is not drawn (it would just look solid dark).")
        for label, edit, filt in [("Blender (blender.exe)", self.blender, "blender.exe (*.exe);;All (*)"),
                                  ("Instant Meshes", self.im, "Executable (*.exe);;All (*)")]:
            row = QHBoxLayout()
            row.addWidget(edit)
            b = QPushButton("…")
            b.setFixedWidth(30)
            b.clicked.connect(lambda _=False, e=edit, f=filt: self._browse(e, f))
            row.addWidget(b)
            form.addRow(label, row)
        form.addRow("Wireframe up to (faces)", self.wire)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        form.addRow(bb)

    def _browse(self, edit, filt):
        p, _ = QFileDialog.getOpenFileName(self, "Locate program", edit.text(), filt)
        if p:
            edit.setText(p)

    def values(self):
        return {"blender": self.blender.text().strip(), "instant_meshes": self.im.text().strip(),
                "wire_max_faces": self.wire.value()}


# ------------------------------------------------------------------ main window
class _HelpHover(QObject):
    """Shows a widget's long explanation in the box under the settings on hover or focus."""
    def __init__(self, win):
        super().__init__(win)
        self.win = win

    def eventFilter(self, obj, ev):
        from PySide6.QtCore import QEvent
        if ev.type() in (QEvent.Enter, QEvent.FocusIn):
            html = obj.property("help_html")
            if html and hasattr(self.win, "help_box"):
                self.win._show_help(html)
        return False


class HelpDialog(QDialog):
    """The full user guide (docs/USER_GUIDE.md) inside the app."""
    def __init__(self, parent=None):
        super().__init__(parent)
        from PySide6.QtWidgets import QTextBrowser
        self.setWindowTitle("Step Converter Help")
        self.resize(900, 800)
        lay = QVBoxLayout(self)
        view = QTextBrowser()
        view.setOpenExternalLinks(True)
        path = paths.docs_path("USER_GUIDE.md")
        try:
            with open(path, encoding="utf-8") as fh:
                text = fh.read()
        except OSError:
            text = f"# Help\n\nThe user guide was not found at `{path}`."
        view.setMarkdown(text)
        view.document().setDefaultStyleSheet("")
        lay.addWidget(view)
        close = QPushButton("Close")
        close.clicked.connect(self.close)
        lay.addWidget(close, 0, Qt.AlignRight)


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Step Converter")
        self.resize(1600, 950)
        self.setAcceptDrops(True)
        self.cfg = settings.load()
        self.files: list[str] = []
        self.original: PolyMesh | None = None
        self.result: PolyMesh | None = None
        self.runs: list[dict] = []          # {"name", "params", "mesh", "report"}
        self.thread = None
        self.worker = None
        self.param_widgets = {}
        self._help_filter = _HelpHover(self)

        self._build_toolbar()
        self._build_central()
        self.statusBar().showMessage("Drop FBX, glTF, GLB, OBJ, STL, PLY or STEP files anywhere in the window.")
        self._load_presets()

    # ---------------- layout
    def _build_toolbar(self):
        tb = QToolBar("Main")
        tb.setIconSize(QSize(16, 16))
        tb.setToolButtonStyle(Qt.ToolButtonTextOnly)
        self.addToolBar(tb)

        def act(text, slot, key=None):
            a = QAction(text, self)
            a.triggered.connect(slot)
            if key:
                a.setShortcut(QKeySequence(key))
            tb.addAction(a)
            return a

        act("Open…", self.open_files, "Ctrl+O")
        act("Open example", self.open_example)
        tb.addSeparator()
        self.run_act = act("▶ Remesh", self.run_remesh, "F5")
        act("Compare presets…", self.compare_presets)
        self.cancel_act = act("■ Cancel", self.cancel_job)
        self.cancel_act.setEnabled(False)
        tb.addSeparator()
        act("Export…", self.export_current, "Ctrl+E")
        act("Batch convert files…", self.batch_export)
        tb.addSeparator()
        self.edges_act = act("Wireframe", self.toggle_edges, "W")
        self.edges_act.setCheckable(True)
        self.edges_act.setChecked(True)
        self.smooth_act = act("Smooth STEP preview", self.toggle_smooth)
        self.smooth_act.setCheckable(True)
        self.heat_act = act("Deviation colours", self.toggle_heat, "H")
        self.heat_act.setCheckable(True)
        act("Reset view", lambda: self.viewer.reset(), "R")
        tb.addSeparator()
        act("Settings…", self.open_settings)
        act("? Help", self.show_help_dialog, "F1")

    def _build_central(self):
        split = QSplitter(Qt.Horizontal)
        # left: files
        left = QWidget()
        ll = QVBoxLayout(left)
        ll.addWidget(QLabel("<b>Files</b>  (drop here)"))
        self.file_list = QListWidget()
        self.file_list.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.file_list.currentRowChanged.connect(self._file_selected)
        ll.addWidget(self.file_list)
        rm = QPushButton("Remove selected")
        rm.clicked.connect(self._remove_files)
        ll.addWidget(rm)
        split.addWidget(left)

        # centre: viewer + report table
        centre = QSplitter(Qt.Vertical)
        self.viewer = Viewer()
        self.viewer.wire_max_faces = int(self.cfg.get("wire_max_faces", 1_500_000))
        centre.addWidget(self.viewer)
        rep = QWidget()
        rl = QVBoxLayout(rep)
        rl.setContentsMargins(4, 4, 4, 4)
        hdr = QHBoxLayout()
        hdr.addWidget(QLabel("<b>Runs</b> — click a row to view it, lower deviation = more accurate"))
        hdr.addStretch(1)
        b = QPushButton("Use these settings")
        b.clicked.connect(self._apply_run_params)
        hdr.addWidget(b)
        b = QPushButton("Clear")
        b.clicked.connect(self._clear_runs)
        hdr.addWidget(b)
        rl.addLayout(hdr)
        self.table = QTableWidget(0, len(REPORT_COLUMNS))
        self.table.setHorizontalHeaderLabels([c[0] for c in REPORT_COLUMNS])
        for i, (col, _k) in enumerate(REPORT_COLUMNS):
            if col in help_text.RUNS_COLUMNS:
                self.table.horizontalHeaderItem(i).setToolTip(help_text.RUNS_COLUMNS[col])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.currentCellChanged.connect(lambda r, *_: self._show_run(r))
        rl.addWidget(self.table)
        centre.addWidget(rep)
        centre.setSizes([700, 220])
        split.addWidget(centre)

        # right: params + export
        right = QWidget()
        rlay = QVBoxLayout(right)
        prow = QHBoxLayout()
        prow.addWidget(QLabel("Preset"))
        self.preset_combo = QComboBox()
        self.preset_combo.activated.connect(self._preset_chosen)
        prow.addWidget(self.preset_combo, 1)
        sb = QPushButton("Save…")
        sb.clicked.connect(self._save_preset)
        prow.addWidget(sb)
        rlay.addLayout(prow)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        inner = QWidget()
        il = QVBoxLayout(inner)
        defaults = RemeshParams()
        for title, items in PARAM_UI:
            box = QGroupBox(title)
            stage = help_text.STAGES.get(title, "")
            box.setToolTip(f"<b>{title.split('  ', 1)[-1]}</b><br>{stage}")
            box.setProperty("help_html", f"<b>{title.split('  ', 1)[-1]}</b> {stage}")
            box.installEventFilter(self._help_filter)
            form = QFormLayout(box)
            for name, label, kind, extra, _short in items:
                w = self._make_widget(kind, extra, getattr(defaults, name))
                lab = QLabel(label)
                self._attach_help(help_text.PARAMS[name], w, lab)
                form.addRow(lab, w)
                self.param_widgets[name] = (kind, w)
            il.addWidget(box)
        il.addWidget(self._build_export_box())
        il.addStretch(1)
        scroll.setWidget(inner)
        rlay.addWidget(scroll, 1)
        self.help_box = QLabel()
        self.help_box.setWordWrap(True)
        self.help_box.setTextFormat(Qt.RichText)
        self.help_box.setObjectName("helpBox")
        self.help_box.setMinimumHeight(110)
        self.help_box.setAlignment(Qt.AlignTop | Qt.AlignLeft)
        self.help_box.setStyleSheet("#helpBox { background: #2a2c30; border: 1px solid #45484c; "
                                    "border-radius: 4px; padding: 6px; color: #c9ccd0; }")
        self._show_help(None)
        rlay.addWidget(self.help_box)
        self.progress = QProgressBar()
        self.progress.setTextVisible(True)
        self.progress.setFormat("Ready")
        rlay.addWidget(self.progress)
        run = QPushButton("▶  Remesh")
        run.setMinimumHeight(36)
        run.clicked.connect(self.run_remesh)
        rlay.addWidget(run)
        exp = QPushButton("Export…")
        exp.setMinimumHeight(30)
        exp.clicked.connect(self.export_current)
        rlay.addWidget(exp)
        split.addWidget(right)
        split.setSizes([220, 1000, 380])
        self.setCentralWidget(split)

    def _build_export_box(self):
        box = QGroupBox("Export")
        form = QFormLayout(box)
        fmt_row = QHBoxLayout()
        self.fmt_checks = {}
        for ext in io_formats.EXPORT_EXTS:
            cb = QCheckBox(ext[1:].upper())
            cb.setChecked(ext in self.cfg.get("export_formats", []))
            self.fmt_checks[ext] = cb
            fmt_row.addWidget(cb)
        w = QWidget()
        w.setLayout(fmt_row)
        lab = QLabel("Formats")
        self._attach_help(help_text.EXPORT["formats"], w, lab, *self.fmt_checks.values())
        form.addRow(lab, w)
        self.step_mode = QComboBox()
        for k, v in [("smooth", "Smooth surfaces (CAD/CNC, needs all quads)"),
                     ("auto", "Flat faces, quads kept"),
                     ("triangles", "Flat triangles (most compatible)")]:
            self.step_mode.addItem(v, k)
        self.step_mode.setCurrentIndex(max(0, self.step_mode.findData(self.cfg.get("step_mode", "smooth"))))
        lab = QLabel("STEP surfaces")
        self._attach_help(help_text.EXPORT["step_mode"], self.step_mode, lab)
        form.addRow(lab, self.step_mode)
        self.step_unit = QComboBox()
        for u in ["MM", "CM", "M", "INCH"]:
            self.step_unit.addItem(u)
        self.step_unit.setCurrentText(self.cfg.get("step_unit", "MM"))
        lab = QLabel("STEP units")
        self._attach_help(help_text.EXPORT["step_unit"], self.step_unit, lab)
        form.addRow(lab, self.step_unit)
        self.sharp_angle = QDoubleSpinBox()
        self.sharp_angle.setRange(1, 180)
        self.sharp_angle.setValue(float(self.cfg.get("step_sharp_angle", 50)))
        lab = QLabel("Smooth: crease above °")
        self._attach_help(help_text.EXPORT["step_sharp_angle"], self.sharp_angle, lab)
        form.addRow(lab, self.sharp_angle)
        self.scale_spin = QDoubleSpinBox()
        self.scale_spin.setDecimals(4)
        self.scale_spin.setRange(0.0001, 10000)
        self.scale_spin.setValue(1.0)
        lab = QLabel("Scale on export")
        self._attach_help(help_text.EXPORT["scale"], self.scale_spin, lab)
        form.addRow(lab, self.scale_spin)
        return box

    # ---------------- help
    def _attach_help(self, entry, *widgets):
        tip = "<div style='max-width: 380px'>" + help_text.tooltip(entry) + "</div>"
        label, what, how = entry
        html = f"<b>{label}</b><br>{what}<br><br><span style='color:#a9c3d9'>{how}</span>"
        for w in widgets:
            w.setToolTip(tip)
            w.setProperty("help_html", html)
            w.installEventFilter(self._help_filter)

    def _show_help(self, html):
        self.help_box.setText(html or "<span style='color:#8d9095'>Point at any setting to see what it does "
                                      "and how to set it. Press <b>F1</b> for the full guide.</span>")

    def show_help_dialog(self):
        HelpDialog(self).show()

    def _make_widget(self, kind, extra, value):
        if kind == "bool":
            w = QCheckBox()
            w.setChecked(bool(value))
        elif kind == "int":
            w = QSpinBox()
            lo, hi, step = extra
            w.setRange(lo, hi)
            w.setSingleStep(step)
            w.setValue(int(value))
            w.setGroupSeparatorShown(True)
        elif kind == "float":
            w = QDoubleSpinBox()
            lo, hi, step, dec = extra
            w.setDecimals(dec)
            w.setRange(lo, hi)
            w.setSingleStep(step)
            w.setValue(float(value))
        else:
            w = QComboBox()
            for k, label in extra.items():
                w.addItem(label, k)
            w.setCurrentIndex(max(0, w.findData(value)))
        return w

    # ---------------- params
    def params(self) -> RemeshParams:
        d = {}
        for name, (kind, w) in self.param_widgets.items():
            d[name] = (w.isChecked() if kind == "bool" else w.value() if kind in ("int", "float")
                       else w.currentData())
        return RemeshParams.from_dict(d)

    def set_params(self, p: RemeshParams):
        for f in fields(RemeshParams):
            if f.name not in self.param_widgets:
                continue
            kind, w = self.param_widgets[f.name]
            v = getattr(p, f.name)
            if kind == "bool":
                w.setChecked(bool(v))
            elif kind in ("int", "float"):
                w.setValue(v)
            else:
                w.setCurrentIndex(max(0, w.findData(v)))

    def _load_presets(self):
        self.preset_combo.clear()
        self.preset_combo.addItem("(current settings)", None)
        seen = {}
        for d in (paths.bundled_presets_dir(), paths.user_presets_dir()):
            for p in glob.glob(os.path.join(d, "*.json")):
                seen[os.path.splitext(os.path.basename(p))[0]] = p      # user copy wins
        for name in sorted(seen):
            self.preset_combo.addItem(name, seen[name])
        if self.preset_combo.count() > 1:
            self.preset_combo.setCurrentIndex(1)
            self._preset_chosen(1)

    def _preset_chosen(self, idx):
        path = self.preset_combo.itemData(idx)
        if path:
            self.set_params(RemeshParams.load(path))

    def _save_preset(self):
        name, ok = QInputDialog.getText(self, "Save preset", "Preset name:")
        if ok and name.strip():
            path = os.path.join(paths.user_presets_dir(), name.strip() + ".json")
            self.params().save(path)
            self._load_presets()
            self.preset_combo.setCurrentIndex(self.preset_combo.findData(path))

    # ---------------- files
    def dragEnterEvent(self, e):
        if e.mimeData().hasUrls():
            e.acceptProposedAction()

    def dropEvent(self, e):
        self.add_files([u.toLocalFile() for u in e.mimeData().urls()])

    def open_files(self):
        filt = "3D models (" + " ".join("*" + x for x in io_formats.IMPORT_EXTS) + ")"
        paths, _ = QFileDialog.getOpenFileNames(self, "Open models", self.cfg.get("last_open_dir", ""), filt)
        if paths:
            self.cfg["last_open_dir"] = os.path.dirname(paths[0])
            self.add_files(paths)

    def open_example(self):
        for root in (paths.app_dir(), paths.resource_dir()):
            p = os.path.join(root, "samples", "monkeyGeo.fbx")
            if os.path.isfile(p):
                self.add_files([p])
                self.statusBar().showMessage("Example loaded. Pick preset 01 and press Remesh (F5).")
                return
        QMessageBox.information(self, "Step Converter", "The example model (samples\\monkeyGeo.fbx) was not found.")

    def add_files(self, paths):
        first_new = None
        for p in paths:
            if os.path.isdir(p):
                self.add_files([os.path.join(p, f) for f in os.listdir(p)])
                continue
            if io_formats.ext_of(p) not in io_formats.IMPORT_EXTS or p in self.files:
                continue
            self.files.append(p)
            it = QListWidgetItem(os.path.basename(p))
            it.setToolTip(p)
            self.file_list.addItem(it)
            if first_new is None:
                first_new = self.file_list.count() - 1
        if first_new is not None:
            self.file_list.setCurrentRow(first_new)

    def _remove_files(self):
        for it in self.file_list.selectedItems():
            row = self.file_list.row(it)
            self.file_list.takeItem(row)
            self.files.pop(row)

    def _file_selected(self, row):
        if row < 0 or row >= len(self.files) or self._busy():
            return
        path = self.files[row]
        self._start("stepfable.tasks:load_task", path, on_done=self._loaded, label=f"Loading {os.path.basename(path)}")

    def _loaded(self, mesh):
        self.original = mesh
        self.result = None
        self.runs.clear()
        self.table.setRowCount(0)
        self.viewer.set_mesh(0, mesh)
        self.viewer.set_mesh(1, None)
        lo, hi = mesh.bounds
        size = hi - lo
        self.statusBar().showMessage(
            f"{mesh.name}: {mesh.n_faces:,} faces, size {size[0]:.4g} × {size[1]:.4g} × {size[2]:.4g}")
        # suggest a sensible target if the default is larger than the input
        kind, w = self.param_widgets["target_faces"]
        if w.value() >= mesh.n_faces:
            w.setValue(max(500, mesh.n_faces // 10))

    # ---------------- jobs
    def _busy(self):
        return self.thread is not None

    def _start(self, target, *args, on_done, label="Working", **kw):
        if self._busy():
            return
        self.thread = QThread()
        self.worker = Worker(target, *args, **kw)
        self.worker.moveToThread(self.thread)
        self.thread.started.connect(self.worker.run)
        self.worker.progress.connect(self._on_progress)
        self._on_done = on_done
        # bound methods of this (GUI-thread) object -> queued, run on the GUI thread
        self.worker.done.connect(self._job_done)
        self.worker.failed.connect(self._job_failed)
        self.progress.setFormat(label)
        self.progress.setValue(0)
        self.cancel_act.setEnabled(True)
        self.thread.start()

    def _job_done(self, result):
        self._finish()
        self._on_done(result)

    def _job_failed(self, msg):
        self._finish()
        self._error(msg)

    def _finish(self):
        self.thread.quit()
        self.thread.wait()
        self.thread = None
        self.worker = None
        self.cancel_act.setEnabled(False)
        self.progress.setValue(100)
        self.progress.setFormat("Ready")

    def _on_progress(self, f, text):
        self.progress.setValue(int(f * 100))
        self.progress.setFormat(text + "  %p%")

    def _error(self, msg):
        if msg == "Cancelled":
            self.statusBar().showMessage("Cancelled")
            return
        box = QMessageBox(QMessageBox.Warning, "Step Converter", msg.split("\n\n")[0], parent=self)
        box.setDetailedText(msg)
        box.exec()

    def cancel_job(self):
        if self.worker:
            self.worker.cancel = True

    # ---------------- remesh + compare
    def _extra(self):
        return {"blender": self.cfg.get("blender") or None, "instant_meshes": self.cfg.get("instant_meshes") or None}

    def run_remesh(self):
        if self.original is None:
            QMessageBox.information(self, "Step Converter", "Open or drop a model first.")
            return
        p = self.params()
        label = self.preset_combo.currentText()
        self._start("stepfable.tasks:remesh_task", self.original, p, self._extra(),
                    on_done=lambda r, p=p, label=label: self._remeshed(r, p, label), label="Remeshing")

    def compare_presets(self):
        if self.original is None:
            QMessageBox.information(self, "Step Converter", "Open or drop a model first.")
            return
        names = [self.preset_combo.itemText(i) for i in range(1, self.preset_combo.count())]
        dlg = QDialog(self)
        dlg.setWindowTitle("Compare presets")
        lay = QVBoxLayout(dlg)
        lay.addWidget(QLabel("Run each checked preset on this model and list the results:"))
        lst = QListWidget()
        for n in names:
            it = QListWidgetItem(n)
            it.setFlags(it.flags() | Qt.ItemIsUserCheckable)
            ext = "QuadriFlow" in n or "Instant" in n
            it.setCheckState(Qt.Unchecked if ext else Qt.Checked)
            lst.addItem(it)
        lay.addWidget(lst)
        cur = QCheckBox("Also run the current settings")
        cur.setChecked(True)
        lay.addWidget(cur)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.accepted.connect(dlg.accept)
        bb.rejected.connect(dlg.reject)
        lay.addWidget(bb)
        if dlg.exec() != QDialog.Accepted:
            return
        jobs = []
        if cur.isChecked():
            jobs.append(("current settings", self.params()))
        for i in range(lst.count()):
            if lst.item(i).checkState() == Qt.Checked:
                path = self.preset_combo.itemData(i + 1)
                jobs.append((lst.item(i).text(), RemeshParams.load(path)))
        if not jobs:
            return
        self._start(run_compare_parallel, self.original, jobs, self._extra(),
                    on_done=self._compared, label="Comparing presets")

    def _compared(self, results):
        errors = []
        for name, p, m, rep in results:
            if m is None:
                errors.append(f"{name}: {rep.get('error')}")
            else:
                self._remeshed((m, rep), p, name)
        if errors:
            QMessageBox.warning(self, "Some presets failed", "\n\n".join(errors))

    def _remeshed(self, res, params, label):
        mesh, rep = res
        self.runs.append({"name": label, "params": params, "mesh": mesh, "report": rep})
        r = self.table.rowCount()
        self.table.insertRow(r)
        for c, (title, key) in enumerate(REPORT_COLUMNS):
            if key is None:
                txt = f"{r + 1}. {label}"
            else:
                v = rep.get(key, "")
                txt = f"{v:,}" if isinstance(v, int) else (f"{v:.4g}" if isinstance(v, float) else str(v))
            it = QTableWidgetItem(txt)
            if key:
                it.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            self.table.setItem(r, c, it)
        self._highlight_best()
        self.table.selectRow(r)
        self._show_run(r)

    def _highlight_best(self):
        col = [c[1] for c in REPORT_COLUMNS].index("dev_mean_pct")
        vals = [run["report"].get("dev_mean_pct", np.inf) for run in self.runs]
        best = int(np.argmin(vals)) if vals else -1
        for r in range(self.table.rowCount()):
            it = self.table.item(r, col)
            if it:
                it.setBackground(QColor("#3e5a47") if r == best else QColor(0, 0, 0, 0))

    def _show_run(self, row):
        if 0 <= row < len(self.runs):
            run = self.runs[row]
            self.result = run["mesh"]
            rep = run["report"]
            info = (f"mean dev {rep.get('dev_mean_pct', 0):.4f}%   max {rep.get('dev_max_pct', 0):.3f}%"
                    if "dev_mean_pct" in rep else "")
            self.viewer.set_mesh(1, self.result, info)

    def _apply_run_params(self):
        r = self.table.currentRow()
        if 0 <= r < len(self.runs):
            self.set_params(self.runs[r]["params"])
            self.preset_combo.setCurrentIndex(0)

    def _clear_runs(self):
        self.runs.clear()
        self.table.setRowCount(0)
        self.result = None
        self.viewer.set_mesh(1, None)

    # ---------------- export
    def _export_opts(self):
        return dict(step_mode=self.step_mode.currentData(), step_unit=self.step_unit.currentText(),
                    step_sharp_angle=self.sharp_angle.value())

    def _formats(self):
        f = [ext for ext, cb in self.fmt_checks.items() if cb.isChecked()]
        self.cfg["export_formats"] = f
        self.cfg["step_mode"] = self.step_mode.currentData()
        self.cfg["step_unit"] = self.step_unit.currentText()
        self.cfg["step_sharp_angle"] = self.sharp_angle.value()
        return f

    def export_current(self):
        mesh = self.result or self.original
        if mesh is None:
            QMessageBox.information(self, "Step Converter", "Nothing to export yet.")
            return
        fmts = self._formats()
        if not fmts:
            QMessageBox.information(self, "Step Converter", "Tick at least one export format.")
            return
        mode = self.step_mode.currentData()
        if ".step" in fmts and mode == "smooth" and not (mesh.face_sizes == 4).all():
            if QMessageBox.question(self, "Step Converter",
                                    "Smooth STEP needs a 100% quad mesh. This mesh isn't all quads, "
                                    "so the STEP will use flat faces instead.\n\nContinue?") != QMessageBox.Yes:
                return
        if ".step" in fmts and mesh.n_faces > 100000:
            smooth = mode == "smooth" and (mesh.face_sizes == 4).all()
            mb = mesh.n_faces * (1.7 if smooth else 1.1) / 1000
            box = QMessageBox(QMessageBox.Warning, "Large STEP file",
                              f"This mesh has {mesh.n_faces:,} faces. Every face becomes its own CAD surface, "
                              f"so the STEP file will be about {mb:,.0f} MB and slow to open in CAD/CAM.\n\n"
                              "For CNC, set Reduce to Isotropic with a few thousand target faces and remesh: "
                              "it is usually just as accurate and far smaller.", parent=self)
            skip = box.addButton("Skip STEP, export the rest", QMessageBox.AcceptRole)
            anyway = box.addButton("Export STEP anyway", QMessageBox.DestructiveRole)
            box.addButton(QMessageBox.Cancel)
            box.setDefaultButton(skip)
            box.exec()
            if box.clickedButton() is skip:
                fmts = [f for f in fmts if f != ".step"]
                if not fmts:
                    return
            elif box.clickedButton() is not anyway:
                return
        folder = QFileDialog.getExistingDirectory(self, "Export to folder", self.cfg.get("last_export_dir", ""))
        if not folder:
            return
        self.cfg["last_export_dir"] = folder
        suffix = "" if mesh is self.original else "_quads"
        base = os.path.join(folder, (mesh.name or "model") + suffix)
        self._start("stepfable.tasks:export_task", mesh, base, fmts, self._export_opts(),
                    self.scale_spin.value(), on_done=self._exported, label="Exporting")

    def _exported(self, written):
        msg = "Exported:\n" + "\n".join(written)
        self.statusBar().showMessage(f"Exported {len(written)} file(s)")
        QMessageBox.information(self, "Step Converter", msg)

    def batch_export(self):
        """Run the current settings (or plain conversion) on every file in the list."""
        if not self.files:
            QMessageBox.information(self, "Step Converter", "Add files to the list first.")
            return
        fmts = self._formats()
        if not fmts:
            QMessageBox.information(self, "Step Converter", "Tick at least one export format.")
            return
        choice = QMessageBox.question(
            self, "Batch convert",
            f"{len(self.files)} file(s) → {', '.join(x[1:].upper() for x in fmts)}\n\n"
            "Yes = remesh each file with the current settings first\nNo = convert as-is",
            QMessageBox.Yes | QMessageBox.No | QMessageBox.Cancel)
        if choice == QMessageBox.Cancel:
            return
        remesh = choice == QMessageBox.Yes
        folder = QFileDialog.getExistingDirectory(self, "Export to folder", self.cfg.get("last_export_dir", ""))
        if not folder:
            return

        def done(res):
            written, errors = res
            msg = f"Wrote {len(written)} file(s) to {folder}"
            if errors:
                msg += "\n\nProblems:\n" + "\n".join(errors)
            QMessageBox.information(self, "Batch convert", msg)

        self._start("stepfable.tasks:batch_task", list(self.files), folder,
                    self.params() if remesh else None, self._extra(), fmts, self._export_opts(),
                    self.scale_spin.value(), on_done=done, label="Batch converting")

    # ---------------- view toggles + settings
    def toggle_edges(self):
        self.viewer.show_edges = self.edges_act.isChecked()
        self.viewer.redraw()

    def toggle_smooth(self):
        self.viewer.smooth_preview = self.smooth_act.isChecked()
        self.viewer.redraw()

    def toggle_heat(self):
        self.viewer.heatmap = self.heat_act.isChecked()
        self.viewer.redraw()

    def open_settings(self):
        dlg = SettingsDialog(self.cfg, self)
        if dlg.exec() == QDialog.Accepted:
            self.cfg.update(dlg.values())
            settings.save(self.cfg)
            self.viewer.wire_max_faces = int(self.cfg["wire_max_faces"])
            self.viewer.redraw()

    def closeEvent(self, e):
        self._formats()
        settings.save(self.cfg)
        if self.worker:
            self.worker.cancel = True
        if self.thread:
            self.thread.quit()
            self.thread.wait(5000)
        self.viewer.plotter.close()
        super().closeEvent(e)


def apply_dark_theme(app):
    """Subdued ash-grey dark theme."""
    from PySide6.QtGui import QPalette
    app.setStyle("Fusion")
    c = {"window": "#2e3033", "base": "#26282b", "alt": "#303236", "text": "#d6d6d6",
         "button": "#3a3c40", "hi": "#5d7389", "dim": "#8a8d91"}
    pal = QPalette()
    pal.setColor(QPalette.Window, QColor(c["window"]))
    pal.setColor(QPalette.WindowText, QColor(c["text"]))
    pal.setColor(QPalette.Base, QColor(c["base"]))
    pal.setColor(QPalette.AlternateBase, QColor(c["alt"]))
    pal.setColor(QPalette.ToolTipBase, QColor(c["button"]))
    pal.setColor(QPalette.ToolTipText, QColor(c["text"]))
    pal.setColor(QPalette.Text, QColor(c["text"]))
    pal.setColor(QPalette.Button, QColor(c["button"]))
    pal.setColor(QPalette.ButtonText, QColor(c["text"]))
    pal.setColor(QPalette.Highlight, QColor(c["hi"]))
    pal.setColor(QPalette.HighlightedText, QColor("#ffffff"))
    pal.setColor(QPalette.PlaceholderText, QColor(c["dim"]))
    for role in (QPalette.WindowText, QPalette.Text, QPalette.ButtonText):
        pal.setColor(QPalette.Disabled, role, QColor("#6c6f73"))
    app.setPalette(pal)
    app.setStyleSheet(
        "QToolTip { color: #d6d6d6; background: #3a3c40; border: 1px solid #55585c; }"
        "QGroupBox { border: 1px solid #45484c; border-radius: 4px; margin-top: 10px; padding-top: 6px; }"
        "QGroupBox::title { subcontrol-origin: margin; left: 8px; padding: 0 4px; color: #b9bcc0; }"
        "QToolBar { background: #2a2c2f; border-bottom: 1px solid #3c3f43; spacing: 4px; }"
        "QToolButton:checked { background: #46505b; border-radius: 3px; }"
        "QProgressBar { border: 1px solid #45484c; border-radius: 3px; text-align: center; background: #26282b; }"
        "QProgressBar::chunk { background: #5d7389; }"
        "QHeaderView::section { background: #33353a; color: #c8c8c8; border: 0; padding: 3px; }")


def main():
    import multiprocessing
    multiprocessing.freeze_support()
    os.environ.setdefault("QT_API", "pyside6")
    app = QApplication.instance() or QApplication(sys.argv)
    app.setApplicationName("Step Converter")
    apply_dark_theme(app)
    w = MainWindow()
    w.show()
    for arg in sys.argv[1:]:
        if os.path.exists(arg):
            w.add_files([arg])
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
