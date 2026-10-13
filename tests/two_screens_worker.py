"""A laptop with a projector beside it, as Windows' Extend gives them, for the presenter theme's full screen (#104, ADR
0019 decision 4):

    python -m tests.two_screens_worker   (tests/test_presenter_screens.py runs it)

QT_QPA_PLATFORM names offscreen Qt with a file of two screens, "laptop" and "projector"; AOI_WORKSPACE, a workspace
folder; AOI_MEMORY_KEYS, keys kept in the process. The Admin switches the presenter theme on, and the window is built
on the projector and shown as the app shows it; then a workspace switch, as Load Demo, Reset Demo and Leave Demo
Workspace make, builds the next window. For each window it prints one line of JSON: the "screen" it is on, its
"geometry" (x, y, width, height), whether it is "full_screen", the presenter theme's "small" sizes in use, and the
"dialogs" shown so far (tests/dialog_watch.py), each closed again as Esc closes it."""

from __future__ import annotations

import json
import os
import sys
import time
from typing import Any

from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from aoi.data import credentials
from aoi.ui import theme
from aoi.ui.errors import open_workspace
from aoi.ui.main_window import MainWindow, build_window
from aoi.ui.theme import QSS
from tests.dialog_watch import DialogWatch


def settled(win: MainWindow, watch: DialogWatch) -> dict[str, Any]:
    """Where `win` is once shown and the system has placed it: the events a show queues, processed for 0.5 s."""
    assert QTest.qWaitForWindowExposed(win, 10000)
    end = time.monotonic() + 0.5
    while time.monotonic() < end:
        QApplication.processEvents()
        time.sleep(0.01)
    g, screen = win.geometry(), win.screen()
    where = {"screen": screen.name() if screen is not None else None, "geometry": [g.x(), g.y(), g.width(), g.height()]}
    return where | {"full_screen": win.isFullScreen(), "small": theme.small(), "dialogs": list(watch.shown)}


def run() -> int:
    if os.environ.get("AOI_MEMORY_KEYS"):
        credentials.default = lambda: credentials.MEMORY
    app = QApplication(sys.argv)
    app.setStyleSheet(QSS)
    watch = DialogWatch()
    watch.start()
    projector = next(s for s in app.screens() if s.name() == "projector")
    ctx = open_workspace()
    assert ctx is not None
    ctx.set_user("admin")
    ctx.save_settings({"presenter_theme": True})
    win = build_window(ctx, None, projector)
    assert win is not None
    win.show_for_theme()
    print(json.dumps(settled(win, watch)), flush=True)
    switched = win.switch_workspace(None)  # the station's workspace again, in a new window
    assert switched is not None
    switched.show_for_theme()  # shown already: as the next start shows it
    print(json.dumps(settled(switched, watch)), flush=True)
    switched.close()
    switched.ctx.close()
    watch.stop()
    return 0


if __name__ == "__main__":
    sys.exit(run())
