"""One start of the app in a process of its own, for REQ-SET-020's start-up budget (stage S55):

    python -m tests.startup_worker   (from the repository root; AOI_WORKSPACE names the folder of settings.json)

Runs main.main() as `python main.py` runs it, with the real QApplication on the platform QT_QPA_PLATFORM names. Once
the window main.main() built is shown and exposed and the events the start queued are processed (its first paint
among them), it prints one line of JSON and closes the window, which ends the app: "usable", the seconds from
AOI_STARTUP_LAUNCHED (the caller's time.time() just before it started this process) to then, so the interpreter's own
start counts; "in_process", the seconds from the top of this module; and the phases, each in seconds: "imports" (main
and what it imports: Qt, the engine, PyTorch), "open_workspace" (settings.json, the database, the start-up archive and
sweeps) and "build_window" (every page, and the first one's data)."""

from __future__ import annotations

from time import perf_counter

T0 = perf_counter()

import json  # noqa: E402
import os  # noqa: E402
import sys  # noqa: E402
import time  # noqa: E402

from PySide6.QtCore import QTimer  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

import main  # noqa: E402
from aoi.core.services import AppContext  # noqa: E402
from aoi.ui.main_window import MainWindow  # noqa: E402

IMPORTED = perf_counter()


def run() -> int:
    marks = {"imports": IMPORTED - T0}
    real_open, real_build = main.open_workspace, main.build_window

    def open_workspace() -> AppContext | None:
        t = perf_counter()
        ctx = real_open()
        marks["open_workspace"] = perf_counter() - t
        return ctx

    def build_window(ctx: AppContext) -> MainWindow | None:
        t = perf_counter()
        win = real_build(ctx)
        marks["build_window"] = perf_counter() - t
        if win is not None:  # main.main() shows it next, then runs the event loop, which fires this first
            QTimer.singleShot(0, lambda: usable(win))
        return win

    def usable(win: MainWindow) -> None:
        exposed = QTest.qWaitForWindowExposed(win)
        QApplication.processEvents()  # the first paint, and whatever else the start queued
        usable_s = time.time() - float(os.environ["AOI_STARTUP_LAUNCHED"])
        print(json.dumps({"usable": usable_s, "in_process": perf_counter() - T0, "exposed": exposed, **marks}))
        win.close()

    main.open_workspace, main.build_window = open_workspace, build_window
    return main.main()


if __name__ == "__main__":
    sys.exit(run())
