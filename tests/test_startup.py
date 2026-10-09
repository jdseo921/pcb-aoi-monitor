"""REQ-LOG-005 and REQ-SET-019 at start-up (stage S14, #205): main.main() installs the unhandled-error hook before the
window is built and again with the window as parent, and an error raised while the window is built shows one coded
dialog, logs its trace and closes the workspace, where before the app vanished with the workspace left open."""

from __future__ import annotations

import gc
import sys
from collections.abc import Callable
from typing import Any

import pytest
from PySide6.QtCore import QCoreApplication, QTimer, QTranslator
from PySide6.QtWidgets import QApplication, QMessageBox, QWidget
from pytestqt.qtbot import QtBot

import main
from aoi.config import Settings
from aoi.core.services import AppContext
from aoi.ui import workers
from aoi.ui.main_window import MainWindow
from aoi.ui.pages.training import TrainingPage
from tests.test_alarms_and_errors import UNEXPECTED, _log_rows


class _App:
    """Stands in for QApplication in main.main(): pytest-qt's application already exists, and exec() runs `loop`
    in place of the event loop, returning its exit code."""

    loop: Callable[[], int] = staticmethod(lambda: 0)

    def __init__(self, argv: list[str]) -> None:
        pass

    def setApplicationName(self, name: str) -> None:  # noqa: N802 (Qt's name)
        pass

    def setStyleSheet(self, qss: str) -> None:  # noqa: N802 (Qt's name)
        pass

    def exec(self) -> int:
        return type(self).loop()


@pytest.fixture
def opened(monkeypatch: pytest.MonkeyPatch) -> list[AppContext]:
    """main.main() on the test's default workspace with the stand-in application; the contexts it opened."""
    monkeypatch.setattr(sys, "excepthook", sys.excepthook)  # put the original back after the test
    monkeypatch.setattr(main, "QApplication", _App)
    contexts: list[AppContext] = []
    real = main.open_workspace

    def open_workspace() -> AppContext | None:
        ctx = real()
        if ctx is not None:
            contexts.append(ctx)
        return ctx

    monkeypatch.setattr(main, "open_workspace", open_workspace)
    return contexts


class _StartUpWord(QTranslator):
    """Translates the context word of a start-up error only, as a filled aoi_ko.ts would (#198)."""

    def translate(self, context: str, source: str, disambiguation: str | None = None, n: int = -1) -> str:
        return "«start-up»" if (context, source) == ("Errors", "start-up") else source


def _closed(ctx: AppContext) -> bool:
    """The workspace was let go: another copy opens it (a held lock refuses it with AOI-SET-012, #204)."""
    try:
        AppContext(Settings(workspace=ctx.settings.workspace, device="cpu")).close()
    except Exception:
        return False
    return True


def _shown_window() -> MainWindow:
    (win,) = [w for w in QApplication.topLevelWidgets() if isinstance(w, MainWindow) and w.isVisible()]
    return win


@pytest.mark.qt_no_exception_capture
def test_req_log_005_an_error_while_the_window_is_built_shows_a_coded_dialog_and_closes_the_workspace(
    opened: list[AppContext], dialogs: list[tuple[str, str]], monkeypatch: pytest.MonkeyPatch
) -> None:
    """#205 defect 1: a page's on_board_model_changed raising while MainWindow is built (a damaged samples table did
    it) left main() on Python's default hook: no dialog, no ERROR line, the workspace open. Now the AOI-SET-007 dialog
    shows, the trace is logged, the workspace is closed and the app ends with exit code 2. The dialog names the
    start-up in the UI language (#198)."""

    def broken(self: TrainingPage, board_model: str | None) -> None:
        raise RuntimeError("page hook failed at start-up")

    monkeypatch.setattr(TrainingPage, "on_board_model_changed", broken)
    translator = _StartUpWord()
    assert QCoreApplication.installTranslator(translator)
    try:
        code = main.main()
    finally:
        QCoreApplication.removeTranslator(translator)
    (ctx,) = opened
    assert code == 2
    assert dialogs == [
        (
            UNEXPECTED,
            "An unexpected error (RuntimeError) stopped the last action («start-up»).\n\n"
            "Try again; if it happens again, restart the app and send the log file (the workspace's logs folder) to "
            "support.",
        )
    ]
    (row,) = _log_rows(ctx, "error.shown")
    assert row["level"] == "ERROR" and row["code"] == "AOI-SET-007" and row["context"] == "start-up"
    assert "RuntimeError: page hook failed at start-up" in str(row["trace"]) and "on_board_model_changed" in str(
        row["trace"]
    )
    assert _closed(ctx), "the workspace was left open"
    assert not [w for w in QApplication.topLevelWidgets() if isinstance(w, MainWindow) and w.isVisible()]


@pytest.mark.qt_no_exception_capture
def test_req_log_005_an_error_in_a_slot_while_the_window_is_built_is_shown_with_its_code(
    qtbot: QtBot, opened: list[AppContext], dialogs: list[tuple[str, str]], monkeypatch: pytest.MonkeyPatch
) -> None:
    """#205 defect 1: a slot that raises while the window is built (here the navigation to the last page) reaches
    sys.excepthook, not main(); the hook is in place before the window exists, so it is shown and logged."""

    def broken(self: MainWindow, *_: object) -> None:
        raise RuntimeError("slot failed at start-up")

    def loop() -> int:
        qtbot.addWidget(_shown_window())
        _shown_window().close()
        return 0

    monkeypatch.setattr(MainWindow, "_on_nav", broken)
    monkeypatch.setattr(_App, "loop", staticmethod(loop))
    assert main.main() == 0
    (ctx,) = opened
    assert [title for title, _ in dialogs] == [UNEXPECTED] and "(unhandled)" in dialogs[0][1]
    (row,) = _log_rows(ctx, "error.shown")
    assert "RuntimeError: slot failed at start-up" in str(row["trace"])
    assert _closed(ctx)


@pytest.mark.qt_no_exception_capture
def test_req_log_005_startup_installs_excepthook(
    qtbot: QtBot, opened: list[AppContext], monkeypatch: pytest.MonkeyPatch
) -> None:
    """#205 defect 2: the app itself installs the hook, with the window as the dialog's parent. A slot raising once
    the event loop runs shows AOI-SET-007 over the window, logs error.shown with the trace and stores an ERROR alarm.
    With the install call removed from start-up this test fails."""
    shown: list[tuple[QWidget | None, str]] = []

    def record(parent: QWidget | None, title: str, text: str, *buttons: object) -> QMessageBox.StandardButton:
        shown.append((parent, title))
        return QMessageBox.StandardButton.Ok

    monkeypatch.setattr(QMessageBox, "critical", staticmethod(record))
    seen: dict[str, Any] = {}

    def boom() -> None:
        raise RuntimeError("slot failed while running")

    def loop() -> int:
        win = _shown_window()
        qtbot.addWidget(win)
        seen["hook"], seen["win"] = sys.excepthook, win
        QTimer.singleShot(0, boom)
        qtbot.waitUntil(lambda: bool(shown), timeout=5000)
        seen["alarms"] = win.ctx.alarms()
        win.close()
        return 0

    monkeypatch.setattr(_App, "loop", staticmethod(loop))
    assert main.main() == 0
    (ctx,) = opened
    assert seen["hook"] is not sys.__excepthook__
    assert shown == [(seen["win"], UNEXPECTED)]
    (row,) = _log_rows(ctx, "error.shown")
    assert row["context"] == "unhandled" and "RuntimeError: slot failed while running" in str(row["trace"])
    (alarm,) = seen["alarms"]
    assert alarm["level"] == "ERROR" and alarm["code"] == "AOI-SET-007"


def test_req_insp_011_startup_runs_the_collector_on_the_ui_thread(
    qtbot: QtBot, opened: list[AppContext], monkeypatch: pytest.MonkeyPatch
) -> None:
    """main.main() turns the interpreter's automatic cycle collection off and starts the UI thread's timer that runs it
    (`workers.collect_on_ui_thread`) before the event loop; with the call removed from start-up this test fails."""
    seen: dict[str, Any] = {}

    def loop() -> int:
        win = _shown_window()
        qtbot.addWidget(win)
        seen["automatic"], seen["timers"] = gc.isenabled(), list(workers._collector)
        win.close()
        return 0

    monkeypatch.setattr(_App, "loop", staticmethod(loop))
    suite = list(workers._collector)
    gc.enable()  # as in a new interpreter; conftest.py turned it off for the suite
    try:
        assert main.main() == 0
    finally:
        gc.disable()
    (timer,) = seen["timers"]
    assert seen["automatic"] is False and timer not in suite and timer.isActive()
