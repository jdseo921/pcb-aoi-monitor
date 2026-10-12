"""One start of the app in a process of its own, for REQ-SET-020's start-up budget (stage S55):

    python -m tests.startup_worker [--demo]   (from the repository root; AOI_WORKSPACE: the folder of settings.json)

Runs main.main() as `python main.py` runs it, with the real QApplication, its dialogs watched from the start, on the
platform QT_QPA_PLATFORM names. Once the window main.main() built is shown and exposed and the events the start queued
are processed (its first paint among them), it prints one line of JSON and closes the window, which ends the app:
"usable", the seconds from AOI_STARTUP_LAUNCHED (the caller's time.time() just before it started this process) to then,
so the interpreter's own start counts; "in_process", the seconds from the top of this module; and the phases, each in
seconds: "imports" (main and what it imports: Qt, the engine, PyTorch), "open_workspace" (settings.json, the database,
the start-up archive and sweeps; with --demo, the demo workspace loaded beside the station's first when it is not there)
and "build_window" (every page, and the first one's data). It names what the start opened, too: "user" and "role" signed
in, "page", "presenter" (the presenter theme on) and "demo" (the demo workspace, with --demo), and "dialogs": every
dialog the start showed, its kind and title (tests/dialog_watch.py), each closed again as Esc closes it so none waits
for a click. When main.main() returns it prints the last line again, with "exit", its return code, and "dialogs" as they
stand then, those shown while closing included, so the last line of a run that ends is always that one. An error in what
this module does from the event loop ends the process at once with its trace (code 1), and so does a window that does
not close (code 4), so no caller waits out its timeout. With AOI_MEMORY_KEYS set, the keys a start writes (the demo
store's) stay in the process, never in the station's key store (Windows Credential Manager).

With AOI_STARTUP_THEN set, the presenter goes on after the first line, as the 5-minute demo script starts (A8 of the
2026-10 business-readiness brief, F14): the presenter theme switched on on Settings, at a pace of 1 s a board,
Inspection, and Start; then "crash" ends the process mid-run as a crash ends it, with no close and nothing saved on the
way out (os._exit, code 3), while a board after the first is inspected; and "close" closes the window as a presenter
closes it, while the run waits at its NG board. Before either it prints a line of JSON: "then", the "page" shown, the
"records" saved, "inspecting" (a board's inspection under way) and the "dialogs" shown since the start."""

from __future__ import annotations

from time import perf_counter

T0 = perf_counter()

import json  # noqa: E402
import os  # noqa: E402
import sys  # noqa: E402
import time  # noqa: E402
import traceback  # noqa: E402
from collections.abc import Callable  # noqa: E402
from typing import Any  # noqa: E402

from PySide6.QtCore import QDeadlineTimer, QTimer  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

import main  # noqa: E402
from aoi.core.services import AppContext  # noqa: E402
from aoi.data import credentials  # noqa: E402
from aoi.ui import theme  # noqa: E402
from aoi.ui.main_window import MainWindow  # noqa: E402
from aoi.ui.pages.base import Page  # noqa: E402
from tests.dialog_watch import DialogWatch  # noqa: E402

IMPORTED = perf_counter()


def wait_for(condition: Callable[[], bool], timeout_ms: int = 60000) -> None:
    deadline = QDeadlineTimer(timeout_ms)
    while not condition():
        if deadline.hasExpired():
            raise TimeoutError("the demo did not get there")
        QApplication.processEvents()
        time.sleep(0.01)


LAST: dict[str, Any] = {}  # the last line printed


def emit(line: dict[str, Any]) -> None:
    """Print `line` as one line of JSON, and keep it as the last."""
    LAST.clear()
    LAST.update(line)
    print(json.dumps(line), flush=True)


def guarded(step: Callable[[], None]) -> None:
    """Run `step` from the event loop; an error in it ends the process at once, its trace on stderr. Left to the app,
    its handler would show the error in a box the watch closes, the loop would go on, and the caller would wait out its
    timeout without the trace."""
    try:
        step()
    except BaseException:
        traceback.print_exc()
        sys.stderr.flush()
        os._exit(1)


def close(win: MainWindow) -> None:
    """Close the window as its user does. One that stays open, as when the watch answers a question No, ends the
    process with an error instead of leaving the app running."""
    win.close()
    if win.isVisible():
        print("the window did not close", file=sys.stderr, flush=True)
        os._exit(4)


def page_title(win: MainWindow) -> str | None:
    page = win.stack.currentWidget()
    return page.title if isinstance(page, Page) else None


def go_on(win: MainWindow, then: str, watch: DialogWatch) -> None:
    """As a presenter goes on after the start, then the end `then` names (module docstring)."""
    settings: Any = win.pages["Settings"]
    assert win.navigate("Settings")
    settings.demo.pace.setValue(1)
    if not theme.presenter():
        settings.presenter.click()
    assert win.navigate("Inspection")
    page: Any = win.pages["Inspection"]
    page.btn_start.click()

    def records() -> int:
        return int(win.ctx.db.query("SELECT COUNT(*) AS n FROM inspections")[0]["n"])

    if then == "crash":
        wait_for(lambda: records() >= 1 and page.worker is not None)  # a board after the first being inspected
    else:
        wait_for(lambda: not page.running and page.worker is None)  # waiting at the NG board, the fourth
    done = {"then": then, "page": page_title(win), "records": records(), "inspecting": page.worker is not None}
    emit(done | {"dialogs": watch.shown})
    if then == "crash":
        os._exit(3)  # no close event, no settings saved, no workspace closed: as a crash ends the app
    close(win)


def run() -> int:
    marks = {"imports": IMPORTED - T0}
    watch = DialogWatch()
    real_open, real_demo, real_build = main.open_workspace, main.open_demo, main.build_window

    def open_workspace() -> AppContext | None:
        t = perf_counter()
        ctx = real_open()
        marks["open_workspace"] = perf_counter() - t
        return ctx

    def open_demo() -> AppContext | None:
        t = perf_counter()
        ctx = real_demo()
        marks["open_workspace"] = perf_counter() - t
        return ctx

    def build_window(ctx: AppContext) -> MainWindow | None:
        t = perf_counter()
        win = real_build(ctx)
        marks["build_window"] = perf_counter() - t
        if win is not None:  # main.main() shows it next, then runs the event loop, which fires this first
            QTimer.singleShot(0, lambda: guarded(lambda: usable(win)))
        return win

    def usable(win: MainWindow) -> None:
        exposed = QTest.qWaitForWindowExposed(win)
        QApplication.processEvents()  # the first paint, and whatever else the start queued
        usable_s = time.time() - float(os.environ["AOI_STARTUP_LAUNCHED"])
        opened = {"user": win.ctx.user, "role": win.ctx.role, "page": page_title(win)}
        opened |= {"presenter": theme.presenter(), "demo": win.in_demo, "exposed": exposed, "dialogs": watch.shown}
        emit({"usable": usable_s, "in_process": perf_counter() - T0, **marks, **opened})
        if then := os.environ.get("AOI_STARTUP_THEN"):
            go_on(win, then, watch)
        else:
            close(win)

    main.open_workspace, main.open_demo, main.build_window = open_workspace, open_demo, build_window
    if os.environ.get("AOI_MEMORY_KEYS"):
        credentials.default = lambda: credentials.MEMORY

    class Watched(QApplication):  # the application main.main() makes, its dialogs watched from the start
        def __init__(self, argv: list[str]) -> None:
            super().__init__(argv)
            self.installEventFilter(watch)

    main.QApplication = Watched  # type: ignore[misc]
    code = main.main()
    emit(LAST | {"exit": code, "dialogs": watch.shown})  # the last line again, with every dialog, closing's included
    return code


if __name__ == "__main__":
    sys.exit(run())
