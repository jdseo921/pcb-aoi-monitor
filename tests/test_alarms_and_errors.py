"""REQ-INSP-006, REQ-LOG-005 and the error half of REQ-SET-019 (stage S14): alarms with codes that survive a
restart, unhandled errors shown as a plain coded message with the trace in the log, and the last page reopened."""

from __future__ import annotations

import json
import re
import sys
from datetime import UTC, datetime
from pathlib import Path

import pytest
from PySide6.QtWidgets import QMessageBox
from pytestqt.qtbot import QtBot

from aoi.config import APP_VERSION, Settings, default_workspace
from aoi.core.services import ALARM_LIMIT, AppContext
from aoi.ui.errors import install_excepthook
from aoi.ui.main_window import MainWindow
from tests.test_req_done_in_v01 import BOARD, _inspect_one, _window

# ISO date, 24-hour time, level, code and message, two spaces apart (REQ-INSP-006)
ALARM_LINE = re.compile(r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}  \[(NG|WARN|ERROR)\]  AOI-[A-Z0-9]+-\d{3}  .+$")
UNEXPECTED = "AOI-SET-007 Unexpected error"


def _restart(ctx: AppContext) -> AppContext:
    """A new AppContext on the same workspace, as a restart of the app creates."""
    return AppContext(Settings(workspace=ctx.settings.workspace, device="cpu"))


def _log_rows(ctx: AppContext, event: str) -> list[dict[str, object]]:
    path = ctx.settings.root / "logs" / f"aoi-{datetime.now(UTC):%Y-%m-%d}.jsonl"
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    return [r for r in rows if r["event"] == event]


def _alarm_lines(win: MainWindow) -> list[str]:
    page = win.pages["Inspection"]
    return [page.alarms.item(i).text() for i in range(page.alarms.count())]


def test_req_insp_006_alarms_show_time_level_code_message_and_survive_restart(
    qtbot: QtBot, trained_ctx: AppContext, ng_board: Path, dialogs: list[tuple[str, str]]
) -> None:
    page = _inspect_one(qtbot, _window(qtbot, trained_ctx, "Operator"), ng_board)
    assert page.last.verdict == "NG"
    trained_ctx.report_error(ValueError("disk on fire"), "test")  # the raw text goes to the log, never to a screen
    win = _window(qtbot, _restart(trained_ctx), "Operator")
    win.navigate("Inspection")
    lines = _alarm_lines(win)
    assert len(lines) == 2 and all(ALARM_LINE.match(line) for line in lines), lines
    assert lines[0].split("  ")[1:3] == ["[ERROR]", "AOI-SET-007"] and "disk on fire" not in lines[0]
    assert lines[1].split("  ")[1:3] == ["[NG]", "AOI-INSP-003"] and ng_board.name in lines[1]
    rows = win.ctx.alarms()
    assert [r["level"] for r in rows] == ["ERROR", "NG"] and all(r["time"].endswith("+00:00") for r in rows)
    assert rows[1]["code"] == "AOI-INSP-003" and rows[1]["message"].startswith(ng_board.name)
    assert dialogs == []  # report_error alone shows nothing; the screen that called it does


def test_req_insp_006_the_last_1000_alarms_survive(ctx: AppContext) -> None:
    for i in range(ALARM_LIMIT + 5):
        ctx.db.alarm("WARN", f"alarm {i}", "AOI-TRN-003")
    rows = _restart(ctx).alarms()
    assert ALARM_LIMIT == 1000 and len(rows) == ALARM_LIMIT
    assert rows[0]["message"] == f"alarm {ALARM_LIMIT + 4}" and rows[-1]["message"] == "alarm 5"  # newest first


def test_req_log_005_unhandled_error_is_logged_with_the_version_and_shown_with_its_code(
    ctx: AppContext, dialogs: list[tuple[str, str]], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(sys, "excepthook", sys.excepthook)  # put the original back after the test
    install_excepthook(ctx, None)
    try:
        raise RuntimeError("secret detail")
    except RuntimeError as e:
        sys.excepthook(type(e), e, e.__traceback__)
    (shown,) = dialogs
    assert shown == (
        UNEXPECTED,
        "An unexpected error (RuntimeError) stopped the last action (unhandled).\n\n"
        "Try again; if it happens again, restart the app and send the log file (the workspace's logs folder) to "
        "support.",
    )
    (row,) = _log_rows(ctx, "error.shown")
    assert row["level"] == "ERROR" and row["app_version"] == APP_VERSION and row["code"] == "AOI-SET-007"
    assert row["context"] == "unhandled" and "RuntimeError: secret detail" in str(row["trace"])
    (alarm,) = ctx.alarms()
    assert alarm["level"] == "ERROR" and alarm["code"] == "AOI-SET-007" and "secret detail" not in alarm["message"]


def test_req_log_005_reopens_on_the_last_page(qtbot: QtBot, trained_ctx: AppContext) -> None:
    _window(qtbot, trained_ctx, "Operator").navigate("Inspection")
    saved = json.loads((default_workspace() / "settings.json").read_text(encoding="utf-8"))
    assert saved["last_page"] == "Inspection" and saved["workspace"] == trained_ctx.settings.workspace

    def reopened() -> str:
        win = MainWindow(AppContext(Settings.load()))  # what main.py does at start-up
        qtbot.addWidget(win)
        return win.stack.currentWidget().title

    assert reopened() == "Inspection"
    for last_page in ("Training", "Nowhere"):  # a page the start-up role cannot open, or one that no longer exists
        settings = Settings.load()
        settings.last_page = last_page
        settings.save()
        assert reopened() == "Home"


def test_req_set_019_page_errors_show_code_what_and_action_never_a_trace(
    qtbot: QtBot, trained_ctx: AppContext, tmp_path: Path, dialogs: list[tuple[str, str]]
) -> None:
    win = _window(qtbot, trained_ctx, "Operator")
    win.pages["Compare"].save_recipe()
    assert dialogs[-1] == (
        "AOI-USR-001 Not allowed for this role",
        "Changing recipes needs the Engineer or Admin role.\n\nSign in as a user with that role, or ask one to do it.",
    )
    win.pages["Compare"].error(ValueError("secret detail"))
    title, text = dialogs[-1]
    assert title == UNEXPECTED and text.startswith("An unexpected error (ValueError) stopped the last action (Compare)")
    assert "secret detail" not in text and "Traceback" not in text
    page = win.pages["Inspection"]  # an error inside the worker thread reaches the operator the same way
    win.navigate("Inspection")
    page._set_queue([tmp_path / "missing.png"])
    page.next_board()
    qtbot.waitUntil(lambda: len(dialogs) == 3, timeout=10000)
    assert dialogs[-1][0] == "AOI-INSP-001 Image cannot be read" and "missing.png" in dialogs[-1][1]
    assert not page.running and "AOI-INSP-001" in _alarm_lines(win)[0]
    rows = _log_rows(trained_ctx, "error.shown")
    assert [r["code"] for r in rows] == ["AOI-USR-001", "AOI-SET-007", "AOI-INSP-001"]
    assert rows[1]["context"] == "Compare" and "ValueError: secret detail" in str(rows[1]["trace"])
    assert [a["code"] for a in trained_ctx.alarms()] == ["AOI-INSP-001", "AOI-SET-007", "AOI-USR-001"]


def test_req_set_019_compare_save_to_recipe_without_a_board_model_asks_for_one(
    qtbot: QtBot, trained_ctx: AppContext, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Before S22b the save reached the database with no board model and came back as an unexpected-error dialog."""
    win = _window(qtbot, trained_ctx)
    before = trained_ctx.recipe_history(BOARD)
    asked: list[tuple[str, str]] = []

    def record(parent: object, title: str, text: str, *buttons: object) -> QMessageBox.StandardButton:
        asked.append((title, text))
        return QMessageBox.StandardButton.Ok

    monkeypatch.setattr(QMessageBox, "information", staticmethod(record))
    win._on_board_model("")  # the top bar cleared, as after the last board model is removed
    assert win.board_model is None
    win.pages["Compare"].save_recipe()
    assert asked == [("Board model", "Create or select a board model in the top bar first.")]
    assert trained_ctx.recipe_history(BOARD) == before
