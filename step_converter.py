"""Entry point for the packaged Windows app (PyInstaller) and for `python step_converter.py`."""
import multiprocessing
import os
import sys


def _quiet_streams():
    # A windowed .exe has no console, so sys.stdout/sys.stderr are None and any
    # write would crash. Send them to a log file in %APPDATA%\StepConverter instead.
    if sys.stdout is not None and sys.stderr is not None:
        return
    try:
        from stepfable.paths import user_dir
        os.makedirs(user_dir(), exist_ok=True)
        log = open(os.path.join(user_dir(), "step_converter.log"), "a", encoding="utf-8", buffering=1)
    except OSError:
        log = open(os.devnull, "w")
    if sys.stdout is None:
        sys.stdout = log
    if sys.stderr is None:
        sys.stderr = log


if __name__ == "__main__":
    _quiet_streams()
    multiprocessing.freeze_support()   # worker processes of the frozen app start here
    from stepfable.__main__ import _run
    _run()
