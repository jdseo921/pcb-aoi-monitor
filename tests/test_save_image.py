"""#241 (REQ-LOG-004, REQ-USR-001, REQ-SET-021): Save Image… (F9) on Inspection writes the board picture through
`AppContext.export_board_image` on a pool thread, which checks the role and records every picture that leaves in the
audit trail; before, the page wrote the picture itself, to any folder, with neither."""

from __future__ import annotations

import shutil
import sqlite3
import threading
from pathlib import Path
from typing import Any

import pytest
from PySide6.QtWidgets import QFileDialog
from pytestqt.qtbot import QtBot

from aoi.core.services import REQUIRED_ROLE, AppContext
from aoi.data import atomic
from aoi.errors import AoiError
from aoi.ui.pages.inspection import InspectionPage
from aoi.ui.workers import _live
from tests.test_req_done_in_v01 import BOARD, _inspect_one, _window


def _inspected(qtbot: QtBot, trained_ctx: AppContext, role: str, board: Path) -> InspectionPage:
    """The window signed in as `role`, `board` inspected and its job ended: the buttons are set for the result."""
    page = _inspect_one(qtbot, _window(qtbot, trained_ctx, role), board)
    qtbot.waitUntil(lambda: page.worker is None and not _live, timeout=30000)  # its finished slot, which sets them, ran
    return page


def _save_as(page: InspectionPage, qtbot: QtBot, monkeypatch: pytest.MonkeyPatch, out: Path) -> None:
    """Press F9's action with the file dialog answering `out`, and wait for the save's pool job to end."""
    monkeypatch.setattr(QFileDialog, "getSaveFileName", staticmethod(lambda *a, **k: (str(out), "PNG (*.png)")))
    assert page.act_save.isEnabled(), "F9 is on for the result"
    page.act_save.trigger()
    qtbot.waitUntil(lambda: page._bg is None, timeout=30000)


def _refuse(*a: object, **k: object) -> str:
    raise sqlite3.OperationalError("database or disk is full")


def test_req_log_004_save_image_records_who_saved_which_record_and_where(
    qtbot: QtBot, trained_ctx: AppContext, ng_board: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Before #241 an Operator's F9 wrote the picture to a folder outside the workspace (a USB stick) and added no
    audit entry. Now the service runs once per save, on a pool thread as the Operator who pressed F9, and writes one
    `export.image` entry: the record's UUID as the object, the destination in full outside the workspace and relative
    to it inside, the board model, the board's file name and the verdict."""
    real = vars(AppContext).get("export_board_image")
    on_ui: list[bool] = []

    def recorded(ctx: AppContext, *args: Any, **kwargs: Any) -> Any:
        on_ui.append(threading.current_thread() is threading.main_thread())
        assert real is not None
        return real(ctx, *args, **kwargs)

    monkeypatch.setattr(AppContext, "export_board_image", recorded, raising=False)
    page = _inspected(qtbot, trained_ctx, "Operator", ng_board)
    assert page.last_id is not None and page.last is not None and page.act_save.isEnabled()
    record = trained_ctx.inspection(page.last_id)
    assert record is not None
    operator, verdict = trained_ctx.db.user_uuid("operator"), page.last.verdict
    earlier = {e["uuid"] for e in trained_ctx.audit_entries()}

    usb = tmp_path / "usb_stick"
    usb.mkdir()
    _save_as(page, qtbot, monkeypatch, usb / "board.png")
    assert (usb / "board.png").stat().st_size > 0 and page.shell.statusBar().currentMessage() == "Saved board.png"
    new = [e for e in trained_ctx.audit_entries() if e["uuid"] not in earlier]
    seen = [(e["action"], e["role"], e["user_uuid"], e["object_type"], e["object_uuid"]) for e in new]
    assert seen == [("export.image", "Operator", operator, "inspection", record["uuid"])], "one entry per picture"
    after = {"path": str(usb / "board.png"), "board_model": BOARD, "board": ng_board.name, "verdict": verdict}
    assert new[0]["after"] == after and new[0]["before"] is None
    assert on_ui == [False], "the service ran once, on a pool thread"

    inside = trained_ctx.settings.root / "exports" / "board_in.png"
    _save_as(page, qtbot, monkeypatch, inside)
    assert inside.exists() and on_ui == [False, False]
    entry = trained_ctx.audit_entries(action="export.image")[0]
    assert entry["after"]["path"] == "exports/board_in.png", "inside the workspace: stored relative to it (#196)"


def test_req_log_004_a_save_image_whose_entry_cannot_be_written_leaves_no_file(
    qtbot: QtBot,
    trained_ctx: AppContext,
    ng_board: Path,
    tmp_path: Path,
    dialogs: list[tuple[str, str]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A picture leaves the station only with its entry (#178). Before #241, F9 wrote none, so with the audit trail
    refusing every entry the picture was still written; now it is removed and the coded error is shown."""
    page = _inspected(qtbot, trained_ctx, "Operator", ng_board)
    monkeypatch.setattr(AppContext, "audit", _refuse)
    usb = tmp_path / "usb_stick"
    usb.mkdir()
    _save_as(page, qtbot, monkeypatch, usb / "board.png")
    assert list(usb.iterdir()) == [], "the picture left with no audit entry"
    assert [title.split()[0] for title, _ in dialogs] == ["AOI-SET-007"]


def test_req_usr_001_save_image_follows_the_role_its_service_requires(
    qtbot: QtBot, trained_ctx: AppContext, ng_board: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Before #241, Save Image… came on for every role once there was a result, whatever the service allows. Now the
    action, its button and F9 follow the role `export_board_image`'s @requires names (REQUIRED_ROLE), also after a
    Switch User on the page. The role shipped is Operator, so every role keeps F9 (REQ-INSP-005); Admin is the role
    Jay's option 2 under #151 would set."""
    monkeypatch.setitem(REQUIRED_ROLE, "export_board_image", "Admin")
    page = _inspected(qtbot, trained_ctx, "Operator", ng_board)
    win = page.shell
    assert (page.act_save.isEnabled(), page.btn_save.isEnabled()) == (False, False), "an Operator under Admin"
    win.set_user("admin")
    assert (page.act_save.isEnabled(), page.btn_save.isEnabled()) == (True, True), "after Switch User to the Admin"
    win.set_user("engineer")
    assert not page.act_save.isEnabled()
    monkeypatch.setitem(REQUIRED_ROLE, "export_board_image", "Operator")  # as shipped
    for user in ("operator", "engineer", "admin"):
        win.set_user(user)
        assert page.act_save.isEnabled(), user


def test_req_log_004_f9_during_a_run_names_the_record_whose_picture_it_saved(
    qtbot: QtBot,
    trained_ctx: AppContext,
    ng_board: Path,
    synthetic_dataset: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """F9 stays on during a run (REQ-INSP-005), and the file dialog's event loop lets the run go on. The first fix of
    #241 read the record's id and the board model after the dialog, so the next board finishing meanwhile made the
    entry name that board's record with the first board's picture (review of #241); now the page reads them when F9
    is pressed. The second board waits for F9 here, so it cannot finish before it."""
    win = _window(qtbot, trained_ctx, "Operator")
    page = win.pages["Inspection"]
    assert isinstance(page, InspectionPage)
    win.navigate("Inspection")
    ok = sorted(synthetic_dataset.glob("test/ok/*.png"))[0]
    pressed, real_load = threading.Event(), AppContext.load_image

    def load(ctx: AppContext, path: str | Path) -> Any:
        if Path(path) == ok:
            assert pressed.wait(30), "F9 pressed during the first board's result"
        return real_load(ctx, path)

    monkeypatch.setattr(AppContext, "load_image", load)
    out = tmp_path / "usb_stick" / "board.png"
    out.parent.mkdir()
    page._set_queue([ng_board, ok])
    try:
        page.start_run()
        qtbot.waitUntil(lambda: page.last_id is not None and page.act_save.isEnabled(), timeout=30000)
        first = trained_ctx.inspection(page.last_id) if page.last_id is not None else None
        assert first is not None and first["image_path"] == str(ng_board) and page.last is not None and page.running
        verdict = page.last.verdict

        def named_while_the_run_goes_on(*a: object, **k: object) -> tuple[str, str]:
            pressed.set()  # the Operator takes a few seconds to name the file, and the second board finishes meanwhile
            qtbot.waitUntil(lambda: page.last_id not in (None, first["id"]), timeout=30000)
            return str(out), "PNG (*.png)"

        monkeypatch.setattr(QFileDialog, "getSaveFileName", staticmethod(named_while_the_run_goes_on))
        page.act_save.trigger()
    finally:
        pressed.set()  # the second board never waits past the test, whatever failed
    qtbot.waitUntil(lambda: page._bg is None and not page.running and page.worker is None and not _live, timeout=30000)
    second = trained_ctx.inspection(page.last_id) if page.last_id is not None else None
    assert second is not None and second["image_path"] == str(ok), "the second board was saved during the dialog"
    (entry,) = trained_ctx.audit_entries(action="export.image")
    assert entry["object_uuid"] == first["uuid"], "the entry names the record whose picture was saved"
    assert entry["after"] == {"path": str(out), "board_model": BOARD, "board": ng_board.name, "verdict": verdict}


def test_req_log_004_a_read_that_fails_leaves_no_picture(
    trained_ctx: AppContext, ng_board: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The second fix of #241 read the Golden board between writing the picture and its entry, so a read failing there
    left the picture with no entry (#178, review of #241). Now the one read the entry needs, the record, comes first."""
    insp = trained_ctx.inspector(BOARD)
    res = insp.inspect(trained_ctx.load_image(ng_board))
    iid = trained_ctx.log_result(BOARD, str(ng_board), res, insp)
    monkeypatch.setattr(trained_ctx.db, "inspection", _refuse)
    with pytest.raises(sqlite3.OperationalError):
        trained_ctx.export_board_image(res, BOARD, iid, ng_board.name, tmp_path / "out" / "board.png")
    assert not (tmp_path / "out").exists(), "a picture left with no entry after the record read failed"
    assert trained_ctx.audit_entries(action="export.image") == []


def test_req_log_004_a_refused_entry_leaves_every_destination_as_it_was(
    trained_ctx: AppContext, ng_board: Path, synthetic_dataset: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The picture was written over the file at the destination before its entry, so a refused entry deleted that file
    (a dataset sample, a board on a USB stick) or left the picture in its place with no entry: over the Golden board,
    every later board was judged NG (third review of #241). Now the picture goes into place only with its entry: each
    file keeps its bytes, no picture, folder or temporary file is left, and later boards are judged as before. The
    overlay is another record's: the record's own holds this very picture, so writing over it changes no byte."""
    usb = tmp_path / "usb_stick"
    usb.mkdir()
    board = Path(shutil.copy(ng_board, usb))
    insp = trained_ctx.inspector(BOARD)
    res = insp.inspect(trained_ctx.load_image(board))
    iid = trained_ctx.log_result(BOARD, str(board), res, insp)
    oks = sorted(synthetic_dataset.glob("test/ok/*.png"))[:3]
    results = [insp.inspect(trained_ctx.load_image(p)) for p in oks]
    other = trained_ctx.inspection(trained_ctx.log_result(BOARD, str(oks[0]), results[0], insp))
    golden = trained_ctx.reference_image(BOARD)
    assert other is not None and golden is not None
    held = [Path(golden), Path(other["overlay_path"]), Path(trained_ctx.samples(BOARD, "NG")[0]["path"]), board]
    before, verdicts = [p.read_bytes() for p in held], [r.verdict for r in results]
    monkeypatch.setattr(AppContext, "audit", _refuse)
    for dest in [*held, usb / "board.png", usb / "new" / "board.png"]:
        with pytest.raises(sqlite3.OperationalError):
            trained_ctx.export_board_image(res, BOARD, iid, board.name, dest)
    kept = [p.is_file() and p.read_bytes() == b for p, b in zip(held, before, strict=True)]
    assert kept == [True, True, True, True], "the Golden board, an overlay, a sample and the USB board as they were"
    assert sorted(usb.iterdir()) == [board], "no picture and no folder left on the USB stick"
    assert [t for p in held for t in p.parent.glob(".*.tmp")] == [], "no temporary file left"
    judged = [trained_ctx.inspector(BOARD).inspect(trained_ctx.load_image(p)).verdict for p in oks]
    assert judged == verdicts, "later boards are judged against the Golden board as before"


class _CommitFails:
    """The database connection, whose commits fail as on a full disk; everything else goes to the real one."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn

    def __getattr__(self, name: str) -> Any:
        return getattr(self.conn, name)

    def commit(self) -> None:
        raise sqlite3.OperationalError("disk I/O error")


@pytest.mark.parametrize("fails", ["move", "commit"])
def test_req_log_004_a_save_whose_move_or_commit_fails_leaves_the_file_as_it_was(
    trained_ctx: AppContext, ng_board: Path, monkeypatch: pytest.MonkeyPatch, fails: str
) -> None:
    """The entry and the picture in place commit together (third review of #241): a move into place that fails, as
    over a file another program holds, rolls the entry back and is AOI-LOG-002, and a commit that fails after the move
    puts back the file the picture replaced. Either way the Golden board keeps its bytes and no entry is stored."""
    res = trained_ctx.inspect_file(BOARD, str(ng_board), save=False)
    golden = Path(trained_ctx.reference_image(BOARD) or "")
    before, real, moves = golden.read_bytes(), atomic.os.replace, list[str]()

    def replace(src: Any, dst: Any) -> None:  # the move onto the Golden board fails; putting it back does not
        moves.append(str(dst))
        if moves.count(str(golden)) == 1 and Path(dst) == golden:
            raise PermissionError(13, "Permission denied", str(dst))
        real(src, dst)

    with monkeypatch.context() as m:
        if fails == "move":
            m.setattr(atomic.os, "replace", replace)
        else:
            m.setattr(trained_ctx.db, "_conn", _CommitFails(trained_ctx.db._conn))
        with pytest.raises(AoiError if fails == "move" else sqlite3.OperationalError) as e:
            trained_ctx.export_board_image(res, BOARD, None, ng_board.name, golden)
    assert fails == "commit" or getattr(e.value, "code", None) == "AOI-LOG-002"
    same = golden.is_file() and golden.read_bytes() == before  # a bool: pytest would diff 400 kB of bytes for minutes
    assert same, "the Golden board as it was"
    assert list(golden.parent.glob(".*.tmp")) == [] and trained_ctx.audit_entries(action="export.image") == []


def test_req_insp_005_save_image_and_compare_come_on_with_the_result(
    qtbot: QtBot, trained_ctx: AppContext, ng_board: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The board's result slot set the buttons before the page kept the result, so Save Image… (F9) and Compare came
    on only at the finished slot after it (review of #241). Now they come on as the result is shown."""
    seen: list[tuple[bool, bool]] = []
    real = InspectionPage._on_result

    def on_result(page: InspectionPage, out: Any) -> None:
        real(page, out)
        seen.append((page.act_save.isEnabled(), page.btn_compare.isEnabled()))

    monkeypatch.setattr(InspectionPage, "_on_result", on_result)
    _inspected(qtbot, trained_ctx, "Operator", ng_board)
    assert seen == [(True, True)]
