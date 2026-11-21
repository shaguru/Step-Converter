"""Heavy jobs, run in a separate worker process by the UI.

PyMeshLab ships its own Qt libraries; running it inside the PySide6 GUI
process corrupts memory. A child process keeps them apart, lets Cancel stop
a job instantly, and means a crash in a mesh library can't take the app down.
"""
from __future__ import annotations

import importlib
import multiprocessing as mp
import os
import queue
import traceback

from .remesh import Cancelled


# ------------------------------------------------------------------ tasks
def load_task(path, progress=None):
    from . import io_formats
    return io_formats.load_with_progress(path, progress=progress)


def remesh_task(mesh, params, extra, progress=None):
    from .remesh import run_pipeline
    return run_pipeline(mesh, params, progress=progress, extra=extra)


def compare_task(mesh, jobs, extra, progress=None):
    from .remesh import run_pipeline
    out = []
    for k, (name, p) in enumerate(jobs):
        def sub(f, text, k=k, name=name):
            progress((k + f) / len(jobs), f"[{k + 1}/{len(jobs)}] {name}: {text}")
        try:
            m, rep = run_pipeline(mesh, p, progress=sub, extra=extra)
            out.append((name, p, m, rep))
        except Exception as exc:
            out.append((name, p, None, {"error": str(exc)}))
    return out


def export_mesh(mesh, base, fmts, opts, progress=None):
    """Write mesh to base+ext for each ext; returns the written paths."""
    from . import io_formats
    written = []
    for i, ext in enumerate(fmts):
        o = dict(opts)
        if progress:
            o["progress"] = lambda f, t, i=i, ext=ext: progress((i + f) / len(fmts), f"{ext[1:].upper()}: {t}")
            progress(i / len(fmts), f"Writing {ext[1:].upper()}")
        if ext in (".step", ".stp") and o.get("step_mode") == "smooth" and not (mesh.face_sizes == 4).all():
            o["step_mode"] = "auto"            # smooth patches need an all-quad mesh
        written.append(io_formats.save(mesh, base + ext, **o))
    return written


def export_task(mesh, base, fmts, opts, scale=1.0, progress=None):
    if scale != 1.0:
        mesh = mesh.copy()
        mesh.vertices = mesh.vertices * scale
    return export_mesh(mesh, base, fmts, opts, progress)


def batch_task(files, folder, params, extra, fmts, opts, scale=1.0, progress=None):
    from . import io_formats
    from .remesh import run_pipeline
    written, errors = [], []
    for k, path in enumerate(files):
        def sub(f, text, k=k, path=path):
            progress((k + f) / len(files), f"[{k + 1}/{len(files)}] {os.path.basename(path)}: {text}")
        try:
            m = io_formats.load(path)
            if params is not None:
                m, _ = run_pipeline(m, params, progress=lambda f, t: sub(0.7 * f, t), extra=extra)
            if scale != 1.0:
                m.vertices = m.vertices * scale
            base = os.path.join(folder, m.name + ("_quads" if params is not None else ""))
            written += export_mesh(m, base, fmts, opts, lambda f, t: sub(0.7 + 0.3 * f, t))
        except Exception as exc:
            errors.append(f"{os.path.basename(path)}: {exc}")
    return written, errors


# ------------------------------------------------------------------ process runner
def _child(target, args, kw, q):
    try:
        mod, name = target.rsplit(":", 1)
        fn = getattr(importlib.import_module(mod), name)

        def prog(f, t):
            q.put(("p", float(f), str(t)))

        q.put(("done", fn(*args, progress=prog, **kw)))
    except BaseException as exc:  # noqa: BLE001 - report everything to the UI
        q.put(("err", f"{exc}\n\n{traceback.format_exc()}"))


def run_in_process(target: str, *args, progress=None, cancelled=lambda: False, **kw):
    """Run 'module:function'(*args, progress=..., **kw) in a fresh process."""
    ctx = mp.get_context("spawn")
    q = ctx.Queue()
    # not a daemon: jobs may start helper processes of their own (FBX reader)
    proc = ctx.Process(target=_child, args=(target, args, kw, q))
    proc.start()
    try:
        while True:
            try:
                msg = q.get(timeout=0.15)
            except queue.Empty:
                if cancelled():
                    raise Cancelled()
                if not proc.is_alive():
                    try:
                        msg = q.get(timeout=1.0)
                    except queue.Empty:
                        raise RuntimeError(f"The worker process stopped unexpectedly (exit code {proc.exitcode}).")
                else:
                    continue
            if msg[0] == "p":
                if progress:
                    progress(msg[1], msg[2])
                if cancelled():
                    raise Cancelled()
            elif msg[0] == "done":
                return msg[1]
            else:
                raise RuntimeError(msg[1])
    finally:
        if proc.is_alive():
            proc.join(timeout=2)
        if proc.is_alive():
            proc.terminate()


def parallel_workers(n_jobs: int) -> int:
    """How many jobs to run at once: half the CPU cores (each job also uses
    threads for its nearest-point searches), at most 6 to keep memory sane."""
    cores = os.cpu_count() or 2
    return max(1, min(n_jobs, cores // 2, 6))


def run_compare_parallel(mesh, jobs, extra, progress=None, cancelled=lambda: False):
    """Run each (name, params) in its own worker process, several at once.
    Returns [(name, params, mesh|None, report)] in the original order."""
    import threading
    from concurrent.futures import ThreadPoolExecutor

    n = len(jobs)
    frac = [0.0] * n
    lock = threading.Lock()
    workers = parallel_workers(n)

    def one(k):
        name, p = jobs[k]

        def prog(f, text):
            with lock:
                frac[k] = f
                done = sum(frac) / n
                running = sum(1 for x in frac if 0 < x < 1)
            if progress:
                progress(done, f"{running} running at once ({workers} max) - {name}: {text}")

        try:
            m, rep = run_in_process("stepfable.tasks:remesh_task", mesh, p, extra,
                                    progress=prog, cancelled=cancelled)
            return (name, p, m, rep)
        except Cancelled:
            raise
        except Exception as exc:
            return (name, p, None, {"error": str(exc).split("\n\n")[0]})
        finally:
            with lock:
                frac[k] = 1.0

    with ThreadPoolExecutor(max_workers=workers) as ex:
        futs = [ex.submit(one, k) for k in range(n)]
        out = []
        for f in futs:
            out.append(f.result())
    return out
