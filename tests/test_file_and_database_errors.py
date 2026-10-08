"""#195 (REQ-SET-019, REQ-LOG-002): a file the user names that cannot be written, and a database another program holds
while the app works, are shown with a code that says what to do, not as an unexpected error (AOI-SET-007); and the two
files of the Logs & Export CSV are written together or not at all."""

from __future__ import annotations

import sqlite3
import sys
from collections.abc import Callable
from pathlib import Path
from time import perf_counter

import pytest
from PySide6.QtWidgets import QFileDialog, QMessageBox
from pytestqt.qtbot import QtBot

from aoi.core.services import AppContext, ErrorReport
from aoi.errors import AoiError
from aoi.ui.errors import install_excepthook
from tests.test_req_done_in_v01 import _inspect_one, _window


def _as_the_app_runs(ctx: AppContext, monkeypatch: pytest.MonkeyPatch, slot: Callable[[], object]) -> None:
    """Call a page's slot as a button press does in the app: what it lets escape reaches the excepthook."""
    monkeypatch.setattr(sys, "excepthook", sys.excepthook)  # put the original back after the test
    install_excepthook(ctx, None)
    try:
        slot()
    except Exception as e:
        sys.excepthook(type(e), e, e.__traceback__)


@pytest.mark.parametrize(
    ("name", "code"),
    [
        ("lot.txt", "AOI-INSP-002 Image cannot be written"),  # a suffix OpenCV has no encoder for
        ("board_v1.2", "AOI-INSP-002 Image cannot be written"),
        ("taken.png", "AOI-LOG-002 Export not written"),  # a folder there: a file another program holds
    ],
)
def test_req_set_019_save_image_to_a_name_that_cannot_be_written_says_why(
    qtbot: QtBot,
    trained_ctx: AppContext,
    ng_board: Path,
    tmp_path: Path,
    dialogs: list[tuple[str, str]],
    monkeypatch: pytest.MonkeyPatch,
    name: str,
    code: str,
) -> None:
    page = _inspect_one(qtbot, _window(qtbot, trained_ctx, "Operator"), ng_board)
    out = tmp_path / "out"
    (out / "taken.png").mkdir(parents=True)
    target = out / name
    monkeypatch.setattr(QFileDialog, "getSaveFileName", staticmethod(lambda *a, **k: (str(target), "")))
    _as_the_app_runs(trained_ctx, monkeypatch, page.save_annotated_image)
    assert [title for title, _ in dialogs] == [code]
    assert trained_ctx.alarms()[0]["code"] == code.split()[0]
    assert [p.name for p in out.iterdir()] == ["taken.png"], "no file written, not even a temporary one"


def test_req_log_002_export_csv_onto_a_held_file_says_so_and_writes_both_files_or_neither(
    qtbot: QtBot,
    trained_ctx: AppContext,
    ng_board: Path,
    tmp_path: Path,
    dialogs: list[tuple[str, str]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A folder at the export path stands in for a file Excel holds open on Windows: both refuse the move into place.
    The export runs on the pool (#194), so each one is awaited; its questions (#182) are answered Yes."""
    trained_ctx.inspect_file("TINY", str(ng_board))
    win = _window(qtbot, trained_ctx)
    logs = win.pages["Logs & Export"]
    win.navigate("Logs & Export")
    out = tmp_path / "exports"
    out.mkdir()
    records, checks = out / "inspections.csv", out / "inspections_checks.csv"
    monkeypatch.setattr(QFileDialog, "getSaveFileName", staticmethod(lambda *a, **k: (str(records), "")))
    monkeypatch.setattr(QMessageBox, "question", staticmethod(lambda *a, **k: QMessageBox.StandardButton.Yes))

    def export() -> None:
        _as_the_app_runs(trained_ctx, monkeypatch, logs.export_csv)
        qtbot.waitUntil(lambda: logs._bg is None, timeout=60000)

    refused = ["AOI-LOG-002 Export not written"]

    records.mkdir()  # (a) the records file is held
    export()
    assert [title for title, _ in dialogs] == refused and str(records) in dialogs[0][1]
    assert not checks.exists() and trained_ctx.audit_entries(action="export.csv") == []
    records.rmdir()

    dialogs.clear()
    records.write_text("an earlier export", encoding="utf-8")
    checks.mkdir()  # (b) only the checks file is held: the earlier records file stays, no half export
    export()
    assert [title for title, _ in dialogs] == refused and str(checks) in dialogs[0][1]
    assert records.read_text(encoding="utf-8") == "an earlier export"
    assert trained_ctx.audit_entries(action="export.csv") == []
    assert sorted(p.name for p in out.iterdir()) == ["inspections.csv", "inspections_checks.csv"], "no temporary file"
    checks.rmdir()

    dialogs.clear()
    export()  # once the other program lets go
    assert dialogs == [] and records.read_text(encoding="utf-8-sig").startswith("id,time,")
    assert checks.read_text(encoding="utf-8-sig").startswith("inspection_id,")
    assert sorted(e["object_type"] for e in trained_ctx.audit_entries(action="export.csv")) == ["checks", "inspections"]


def test_req_log_002_every_export_names_the_file_it_could_not_write(
    trained_ctx: AppContext, ng_board: Path, tmp_path: Path
) -> None:
    ctx = trained_ctx
    ctx.inspect_file("TINY", str(ng_board))
    held = tmp_path / "held"
    held.mkdir()  # a folder where the file goes
    taken = tmp_path / "taken"
    taken.write_text("a file where the overlays folder goes", encoding="utf-8")
    audited = len(ctx.audit_entries())
    for call in (
        lambda: ctx.export_csv(held, [{"a": 1}]),
        lambda: ctx.export_model(ctx.models("TINY")[0]["id"], held),
    ):
        with pytest.raises(Exception) as e:
            call()
        assert ErrorReport.of(e.value).code == "AOI-LOG-002" and e.value.params["path"] == str(held), e.value
    assert len(ctx.audit_entries()) == audited
    with pytest.raises(AoiError) as stopped:  # an overlay export says how far it got, and records that (#178)
        ctx.export_overlays(ctx.inspections(), taken)
    assert stopped.value.code == "AOI-LOG-001" and stopped.value.params["folder"] == str(taken)
    (entry,) = ctx.audit_entries()[: len(ctx.audit_entries()) - audited]  # newest first
    assert (entry["action"], entry["after"]["copied"]) == ("export.overlays", 0)


def test_req_set_019_a_save_while_another_program_holds_the_database_says_so_without_a_second_wait(
    qtbot: QtBot, trained_ctx: AppContext, dialogs: list[tuple[str, str]], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Save Recipe while a database tool holds aoi.sqlite's write lock: SQLite waits 5 s and refuses; the dialog then
    names the lock (AOI-SET-013) at once, where it said AOI-SET-007 after another 5 s spent on its alarm."""
    win = _window(qtbot, trained_ctx)
    editor = win.pages["Recipe Editor"]
    win.navigate("Recipe Editor")
    revisions = trained_ctx.recipe_history("TINY")
    took: list[float] = []
    report_error = trained_ctx.report_error

    def timed(exc: BaseException, context: str = "") -> ErrorReport:
        start = perf_counter()
        try:
            return report_error(exc, context)
        finally:
            took.append(perf_counter() - start)

    monkeypatch.setattr(trained_ctx, "report_error", timed)
    other = sqlite3.connect(trained_ctx.db.path, isolation_level=None)
    other.execute("BEGIN IMMEDIATE")
    try:
        _as_the_app_runs(trained_ctx, monkeypatch, editor.save)
    finally:
        other.close()
    assert [title for title, _ in dialogs] == ["AOI-SET-013 Workspace database busy"]
    assert str(trained_ctx.db.path) in dialogs[0][1] and took[0] < 2.0, took
    assert trained_ctx.recipe_history("TINY") == revisions
    assert trained_ctx.db.query("PRAGMA busy_timeout")[0]["timeout"] == 5000, "later writes wait as before"
