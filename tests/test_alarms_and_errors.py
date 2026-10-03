"""REQ-INSP-006, REQ-LOG-005 and the error half of REQ-SET-019 (stage S14): alarms with codes that survive a
restart, unhandled errors shown as a plain coded message with the trace in the log, and the last page reopened."""

from __future__ import annotations

import json
import re
import sqlite3
import sys
import threading
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

import numpy as np
import pytest
from PySide6.QtWidgets import QMessageBox
from pytestqt.qtbot import QtBot

from aoi.config import APP_VERSION, Settings, default_workspace
from aoi.core.imaging import list_images
from aoi.core.inspector import InspectionResult, Inspector
from aoi.core.services import ALARM_LIMIT, AppContext
from aoi.errors import AoiError
from aoi.ui.errors import install_excepthook
from aoi.ui.main_window import MainWindow
from aoi.ui.pages.inspection import InspectionPage
from aoi.ui.pages.settings import SettingsPage
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


def test_req_set_019_an_error_is_shown_when_the_database_refuses_its_alarm(
    ctx: AppContext, dialogs: list[tuple[str, str]], monkeypatch: pytest.MonkeyPatch
) -> None:
    """#171: when the database refuses writes (another program holds its lock, the disk is full), the error being
    reported is often that refusal, and its ERROR alarm cannot be stored either. report_error logs that instead and
    still returns the report, so the coded dialog shows; through the excepthook too, which fell back to stderr."""
    ctx.db._conn.execute("PRAGMA busy_timeout = 100")  # not SQLite's 5 s wait
    other = sqlite3.connect(ctx.db.path, isolation_level=None)
    other.execute("BEGIN IMMEDIATE")
    err = AoiError("AOI-INSP-008", detail="OperationalError: database is locked", file="b.png")
    assert ctx.report_error(err, "Inspection").code == "AOI-INSP-008"
    monkeypatch.setattr(sys, "excepthook", sys.excepthook)  # put the original back after the test
    install_excepthook(ctx, None)
    try:
        raise err
    except AoiError as e:
        sys.excepthook(type(e), e, e.__traceback__)
    other.close()  # the other program lets go
    assert [title for title, _ in dialogs] == ["AOI-INSP-008 Result not saved"]
    assert [r["code"] for r in _log_rows(ctx, "alarm.not_stored")] == ["AOI-INSP-008", "AOI-INSP-008"]
    assert [r["code"] for r in _log_rows(ctx, "error.shown")] == ["AOI-INSP-008", "AOI-INSP-008"]
    assert ctx.alarms() == []


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


def test_req_log_005_the_app_keeps_hand_edits_to_settings_json(
    qtbot: QtBot, ctx: AppContext, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Remembering the page in use and saving the Settings page each write their own keys over settings.json as it is
    on disk now (#170), so an Admin's edit made while the app runs, such as a raised image limit, stays. Before, every
    page change wrote the whole settings held in memory and put the old limit back."""
    monkeypatch.setattr(QMessageBox, "information", staticmethod(lambda *a: QMessageBox.StandardButton.Ok))
    win = MainWindow(ctx)  # an empty workspace opens as Admin
    qtbot.addWidget(win)
    f = default_workspace() / "settings.json"
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text('{"max_image_megapixels": 120, "map_retention_days_ok": 3, "unknown_key": 1}', encoding="utf-8")
    assert win.navigate("Logs & Export")
    page = cast(SettingsPage, win.pages["Settings"])
    page.lang.setCurrentIndex(page.lang.findData("ko"))
    page.save()
    saved = json.loads(f.read_text(encoding="utf-8"))
    assert (saved["last_page"], saved["language"]) == ("Logs & Export", "ko")
    assert [saved.get(k) for k in ("max_image_megapixels", "map_retention_days_ok", "unknown_key")] == [120, 3, 1]


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


def test_req_set_019_the_app_opens_when_the_golden_board_file_is_gone(
    qtbot: QtBot, trained_ctx: AppContext, dialogs: list[tuple[str, str]]
) -> None:
    """With the Golden board's file of the board model in use gone or damaged, the main window did not open: the
    Recipe Editor read the file when the board model was selected at start-up, and its error escaped the window, so no
    Engineer could reach Training to set another. Now the window opens as at every start, with the Operator signed in,
    and shows no error for it: the Recipe Editor and Compare say on their Golden board pane that it cannot be opened,
    with the code, what happened and the next step for the role signed in, built again when an Engineer signs in, and
    no alarm is stored. Inspecting a board, on Compare too, still refuses it with AOI-INSP-009; once the step is done
    (Set Reference on another OK sample), both panes show the new Golden board when shown again, and Compare judges the
    board it refused (#176 review: Compare showed AOI-INSP-009 and stored an alarm at every start, the Recipe Editor
    kept the Operator's "Ask an Engineer" text, and both kept the error after the remedy)."""
    fix = "choose another OK sample with Set Reference on Training."
    board = trained_ctx.samples(BOARD, "OK")[-1]["path"]
    for change, code in ((Path.unlink, "AOI-INSP-001"), (lambda p: p.write_bytes(b"no image"), "AOI-INSP-004")):
        golden = Path(str(trained_ctx.reference_image(BOARD)))
        change(golden)
        alarms = trained_ctx.alarms()
        trained_ctx.set_user("operator")  # as at every start: the pages load the board model first
        win = _window(qtbot, trained_ctx, "Operator")
        compare, editor = win.pages["Compare"], win.pages["Recipe Editor"]
        qtbot.waitUntil(lambda page=compare: trained_ctx.jobs.idle() and page._bg is None, timeout=20000)
        win.navigate("Compare")
        heading = f"The Golden board for {BOARD} cannot be opened"
        assert (compare.ref_empty.heading.text(), compare.ref_empty.link.isVisible()) == (heading, False)
        assert compare.ref_empty.sentence.text().startswith(f"{code} ")
        assert compare.ref_empty.sentence.text().endswith(f"Ask an Engineer to put the file back, or to {fix}")
        win.set_user("engineer")
        for page, empty in (("Recipe Editor", editor.view_empty), ("Compare", compare.ref_empty)):
            win.navigate(page)
            assert empty.isVisible() and empty.heading.text() == heading and empty.link.text() == "Open Training ›"
            assert empty.sentence.text().startswith(f"{code} ") and empty.sentence.text().endswith(f"or {fix}")
        qtbot.waitUntil(lambda page=compare: trained_ctx.jobs.idle() and page._bg is None, timeout=20000)
        assert compare.ref_empty.isVisible() and compare.ref_empty.link.text() == "Open Training ›"
        assert trained_ctx.alarms() == alarms
        with pytest.raises(AoiError) as refused:
            trained_ctx.inspect_file(BOARD, board, save=False)
        assert refused.value.code == "AOI-INSP-009"
        assert dialogs == [], "no error dialog on the way"
        compare.set_test(board)  # a board to judge, which the Golden board keeps from being judged
        qtbot.waitUntil(lambda: bool(dialogs), timeout=20000)
        assert [d[0] for d in dialogs] == ["AOI-INSP-009 Golden board file not available"] and compare.res is None
        dialogs.clear()
        other = next(s for s in trained_ctx.samples(BOARD, "OK") if Path(s["path"]) not in (golden, Path(board)))
        trained_ctx.set_reference(BOARD, other["id"])  # the step the panes give, done on Training
        win.navigate("Recipe Editor")
        assert editor.ref is not None and not editor.view_empty.isVisible()
        win.navigate("Compare")
        qtbot.waitUntil(lambda page=compare: page.res is not None and page._bg is None, timeout=20000)
        assert not compare.ref_empty.isVisible() and not compare.ref_view._placeholder.isVisible()
    assert dialogs == []


def test_req_set_019_compare_says_why_a_board_is_not_judged_and_judges_it_once_it_can(
    qtbot: QtBot, trained_ctx: AppContext, dialogs: list[tuple[str, str]]
) -> None:
    """A test board on Compare whose Golden board file went after it was judged: Re-evaluate refuses it with
    AOI-INSP-009, its dialog and alarm, and now also clears the verdict of the board before and says on the Golden
    board pane that the file cannot be opened; once a Golden board can be read again, showing the page judges the
    board. Showing the page while the new Golden board cannot be read either names the new file on the pane, with no
    dialog or alarm (#176 review: the pane kept the old picture and a stale OK, and the board was never judged again;
    a later show raised a dialog and an alarm while the pane named the old file)."""
    board = trained_ctx.samples(BOARD, "OK")[-1]["path"]
    win = _window(qtbot, trained_ctx)
    compare = win.pages["Compare"]
    win.navigate("Compare")
    compare.set_test(board)
    qtbot.waitUntil(lambda: compare.res is not None and compare._bg is None, timeout=60000)
    golden = Path(str(trained_ctx.reference_image(BOARD)))
    golden.unlink()
    compare.run()  # Re-evaluate
    qtbot.waitUntil(lambda: bool(dialogs) and compare._bg is None, timeout=20000)
    assert [d[0] for d in dialogs] == ["AOI-INSP-009 Golden board file not available"]
    assert compare.res is None and compare.verdict.text() == "—" and compare.test_empty.isVisible()
    assert compare.test_empty.heading.text() == "Board not inspected"
    assert compare.ref_empty.heading.text() == f"The Golden board for {BOARD} cannot be opened"
    assert golden.name in compare.ref_empty.sentence.text() and compare.ref_empty.link.text() == "Open Training ›"
    dialogs.clear()
    alarms = trained_ctx.alarms()
    oks = [s for s in trained_ctx.samples(BOARD, "OK") if Path(s["path"]) not in (golden, Path(board))]
    trained_ctx.set_reference(BOARD, oks[0]["id"])
    Path(oks[0]["path"]).unlink()  # the new Golden board cannot be read either
    win.navigate("Home")
    win.navigate("Compare")
    qtbot.waitUntil(lambda: trained_ctx.jobs.idle() and compare._bg is None, timeout=20000)
    assert dialogs == [] and trained_ctx.alarms() == alarms and compare.res is None
    assert Path(oks[0]["path"]).name in compare.ref_empty.sentence.text()
    trained_ctx.set_reference(BOARD, oks[1]["id"])
    win.navigate("Home")
    win.navigate("Compare")
    qtbot.waitUntil(lambda: compare.res is not None and compare._bg is None, timeout=60000)
    assert not compare.ref_empty.isVisible() and not compare.test_empty.isVisible() and dialogs == []


def test_req_cmp_003_a_stored_result_on_compare_is_never_inspected_again_on_show(
    qtbot: QtBot,
    trained_ctx: AppContext,
    ng_board: Path,
    dialogs: list[tuple[str, str]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A stored result opened on Compare while today's Golden board cannot be read, whose stored maps cannot be read
    either (AOI-CMP-003), stayed the stored result until a new Golden board was set: showing the page then inspected
    the board again with today's Golden board and dropped the stored verdict, unasked (#176 review, REQ-CMP-003)."""
    win = _window(qtbot, trained_ctx)
    page = _inspect_one(qtbot, win, ng_board)
    rid = page.last_id
    assert rid is not None
    golden = Path(str(trained_ctx.reference_image(BOARD)))
    golden.unlink()
    compare = win.pages["Compare"]
    win.navigate("Compare")
    qtbot.waitUntil(lambda: trained_ctx.jobs.idle() and compare._bg is None, timeout=20000)
    assert compare.golden_error is not None

    def damaged(*a: object, **k: object) -> None:
        raise AoiError("AOI-CMP-003", file="map.png", reason="damaged for the test")

    monkeypatch.setattr(trained_ctx, "judged_reference", damaged)
    compare.show_stored(rid)
    qtbot.waitUntil(lambda: bool(dialogs) and compare._bg is None, timeout=20000)
    assert [d[0].split()[0] for d in dialogs] == ["AOI-CMP-003"]
    dialogs.clear()
    other = next(s for s in trained_ctx.samples(BOARD, "OK") if Path(s["path"]) != golden)
    trained_ctx.set_reference(BOARD, other["id"])
    win.navigate("Home")
    win.navigate("Compare")
    qtbot.waitUntil(lambda: trained_ctx.jobs.idle() and compare._bg is None, timeout=20000)
    assert compare.stored is not None and compare.test_label.text().endswith("(stored result)") and dialogs == []


def test_req_set_019_compare_says_no_golden_board_yet_for_the_role_signed_in(
    qtbot: QtBot, trained_ctx: AppContext
) -> None:
    """Compare's "No Golden board yet" pane is built at start-up for the Operator; an Engineer who signs in reads the
    step for the Engineer with its link, as on the Recipe Editor (#176 review)."""
    trained_ctx.ensure_board_model("ZZZ")
    trained_ctx.set_user("operator")
    win = _window(qtbot, trained_ctx, "Operator")
    compare = win.pages["Compare"]
    win._on_board_model("ZZZ")
    win.navigate("Compare")
    qtbot.waitUntil(lambda: trained_ctx.jobs.idle() and compare._bg is None, timeout=20000)
    assert compare.ref_empty.heading.text() == "No Golden board for ZZZ yet" and not compare.ref_empty.link.isVisible()
    win.set_user("engineer")
    assert compare.ref_empty.isVisible() and compare.ref_empty.link.text() == "Open Training ›"


def test_req_set_019_both_golden_board_panes_follow_a_new_reference(
    qtbot: QtBot, trained_ctx: AppContext, ng_board: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """With a readable Golden board, Set Reference, or the file replaced where it is, shows on the Recipe Editor and
    Compare when they are shown again, and a Try judged against the Golden board before is dropped (#176 review: the
    Recipe Editor kept its Try verdict under another Golden board, and neither page read a file replaced in place)."""
    win = _window(qtbot, trained_ctx)
    editor, compare = win.pages["Recipe Editor"], win.pages["Compare"]
    shown: list[object] = []
    keep = compare._show_reference
    monkeypatch.setattr(compare, "_show_reference", lambda ref, judged=None: (shown.append(ref), keep(ref, judged)))
    win.navigate("Recipe Editor")
    editor.run_test(str(ng_board))
    qtbot.waitUntil(lambda: editor.test_verdict.text().startswith("Try result:"), timeout=60000)
    golden = Path(str(trained_ctx.reference_image(BOARD)))
    one, two = [s["path"] for s in trained_ctx.samples(BOARD, "OK") if Path(s["path"]) != golden][:2]
    trained_ctx.set_reference(BOARD, next(s["id"] for s in trained_ctx.samples(BOARD, "OK") if s["path"] == one))
    for step, path in (("Set Reference", one), ("the file replaced", two)):
        if step == "the file replaced":
            Path(one).write_bytes(Path(two).read_bytes())
        win.navigate("Home")
        win.navigate("Recipe Editor")
        assert editor.ref is not None and np.array_equal(editor.ref, trained_ctx.load_image(path)), step
        assert editor.test_verdict.text() == "", step
        win.navigate("Compare")
        qtbot.waitUntil(lambda page=compare: trained_ctx.jobs.idle() and page._bg is None, timeout=20000)
        assert np.array_equal(cast(np.ndarray, shown[-1]), trained_ctx.load_image(path)), step


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


def _hold_write_lock(ctx: AppContext) -> sqlite3.Connection:
    """Another program takes the database's write lock and keeps it until closed; the app waits 200 ms, not 5 s."""
    ctx.db._conn.execute("PRAGMA busy_timeout = 200")
    other = sqlite3.connect(ctx.db.path, isolation_level=None, check_same_thread=False)
    other.execute("BEGIN IMMEDIATE")
    return other


def test_req_insp_006_an_ng_record_and_its_alarm_are_saved_together(
    qtbot: QtBot,
    trained_ctx: AppContext,
    ng_board: Path,
    dialogs: list[tuple[str, str]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """#179: the NG alarm was a second commit after the record's. When another program took the write lock between
    the two, the saved NG board was reported as "Result not saved" (AOI-INSP-008, whose advice adds a duplicate), had
    no alarm, and Compare opened its file, not its record. The record and its alarm now commit together."""
    real, holders = trained_ctx.db.add_inspection, []

    def add_then_lock(*args: Any, **kwargs: Any) -> int:
        iid = real(*args, **kwargs)
        holders.append(_hold_write_lock(trained_ctx))  # the moment the record's transaction has committed
        return iid

    monkeypatch.setattr(trained_ctx.db, "add_inspection", add_then_lock)
    win = _window(qtbot, trained_ctx, "Operator")
    page = _inspect_one(qtbot, win, ng_board)
    qtbot.waitUntil(lambda: page.worker is None, timeout=30000)
    for other in holders:
        other.close()
    assert dialogs == []
    (rec,) = trained_ctx.inspections()
    assert rec["result"] == "NG" and page.last_id == rec["id"] and page.last is not None
    ng = [(a["code"], a["message"]) for a in trained_ctx.alarms() if a["level"] == "NG"]
    assert ng == [("AOI-INSP-003", f"{ng_board.name}: {len(page.last.defects)} defect(s)")]
    assert "AOI-INSP-003" in _alarm_lines(win)[0]


def test_req_insp_008_an_ng_record_whose_alarm_is_refused_is_not_saved(trained_ctx: AppContext, ng_board: Path) -> None:
    """#179: a refused NG alarm left the record saved and the board reported as not saved; now neither is stored,
    so the AOI-INSP-008 the Inspection page shows is true and inspecting the board again adds no duplicate."""
    insp = trained_ctx.inspector(BOARD)
    res = insp.inspect(trained_ctx.load_image(str(ng_board)))
    assert res.verdict == "NG"
    trained_ctx.db._conn.execute(
        "CREATE TEMP TRIGGER refuse_alarm BEFORE INSERT ON alarms BEGIN SELECT RAISE(ABORT, 'alarm refused'); END"
    )
    with pytest.raises(sqlite3.IntegrityError, match="alarm refused"):
        trained_ctx.log_result(BOARD, str(ng_board), res, insp)
    assert trained_ctx.inspections() == [] and trained_ctx.alarms() == []


@pytest.mark.qt_no_exception_capture
def test_req_set_019_a_refused_alarm_never_replaces_the_result_not_saved_error(
    qtbot: QtBot,
    ctx: AppContext,
    synthetic_dataset: Path,
    ng_board: Path,
    dialogs: list[tuple[str, str]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """#179: a board model with a Golden board and no AI model yet, inspected while another program holds the write
    lock: the "No AI model" WARN alarm raised from the result slot, so AOI-SET-007 showed in place of AOI-INSP-008 and
    the run stayed on with Start and Next Board off. The alarm refused, and an alarm list that cannot be read, are now
    logged; the result and its error show."""
    ctx.import_samples("NOAI", [str(p) for p in list_images(synthetic_dataset / "train" / "ok")[:3]], "OK")
    assert ctx.reference_image("NOAI") is not None and ctx.load_model("NOAI") is None
    win = MainWindow(ctx)
    qtbot.addWidget(win)
    win.show()
    qtbot.waitExposed(win)
    monkeypatch.setattr(sys, "excepthook", sys.excepthook)  # put the original back after the test
    install_excepthook(ctx, win)
    win.set_user("operator")
    win.bm_combo.setCurrentText("NOAI")
    win.navigate("Inspection")
    page = cast(InspectionPage, win.pages["Inspection"])
    page._set_queue([ng_board])
    other = _hold_write_lock(ctx)

    def unreadable(*_: object) -> list[dict[str, Any]]:
        raise sqlite3.OperationalError("disk I/O error")

    monkeypatch.setattr(ctx, "alarms", unreadable)  # nor can the alarm list be read: it keeps what it showed
    page.start_run()
    qtbot.waitUntil(lambda: page.worker is None, timeout=30000)
    qtbot.wait(500)
    other.close()
    assert [title for title, _ in dialogs] == ["AOI-INSP-008 Result not saved"]
    assert not page.running and page.act_start.isEnabled() and page.act_next.isEnabled()
    assert win.statusBar().currentMessage().startswith(f"{ng_board.name}  ·  AI score")
    assert [r["code"] for r in _log_rows(ctx, "alarm.not_stored")] == ["AOI-INSP-008", "AOI-TRN-003"]
    assert _log_rows(ctx, "alarms.not_read")


@pytest.mark.qt_no_exception_capture
def test_req_set_019_a_refused_alarm_never_stops_a_board_model_change(
    qtbot: QtBot,
    trained_ctx: AppContext,
    synthetic_dataset: Path,
    dialogs: list[tuple[str, str]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """#179: the header's board model changed during a run while another program holds the write lock: the run-stopped
    WARN alarm (AOI-INSP-012) raised, AOI-SET-007 showed and the pages after Inspection never heard of the change.
    Now the run stops, every page follows the header, and the alarm refused is logged."""
    trained_ctx.ensure_board_model("ZZZ")
    win = _window(qtbot, trained_ctx, "Operator")
    monkeypatch.setattr(sys, "excepthook", sys.excepthook)  # put the original back after the test
    install_excepthook(trained_ctx, win)
    page = cast(InspectionPage, win.pages["Inspection"])
    win.navigate("Inspection")
    qtbot.waitUntil(trained_ctx.jobs.idle, timeout=10000)
    heard: dict[str, str | None] = {}
    for title, p in win.pages.items():
        keep = p.on_board_model_changed
        monkeypatch.setattr(p, "on_board_model_changed", lambda n, t=title, k=keep: (heard.__setitem__(t, n), k(n)))
    gate, started, real = threading.Event(), [], Inspector.inspect

    def inspect(engine: Inspector, image: np.ndarray) -> InspectionResult:
        started.append(1)
        assert gate.wait(30), "the test did not release the board"
        return real(engine, image)

    monkeypatch.setattr(Inspector, "inspect", inspect)
    page._set_queue(list_images(synthetic_dataset / "test" / "ok")[:2])
    page.start_run()
    qtbot.waitUntil(lambda: len(started) == 1, timeout=60000)  # the first board is in hand
    other = _hold_write_lock(trained_ctx)
    win.bm_combo.setCurrentText("ZZZ")
    other.close()
    gate.set()
    qtbot.waitUntil(lambda: page.worker is None and trained_ctx.jobs.idle(), timeout=60000)
    assert dialogs == []
    assert heard == dict.fromkeys(win.pages, "ZZZ") and not page.running
    assert [r["code"] for r in _log_rows(trained_ctx, "alarm.not_stored")] == ["AOI-INSP-012"]
    assert [r["board_model"] for r in trained_ctx.inspections()] == [BOARD], "the board in hand kept TINY"
