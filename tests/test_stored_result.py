"""#246 (stage S25): a save that is refused leaves no picture in results/ that no record names (REQ-INSP-008), and a
record judged with the AI check turned off says so where it names the AI model active then (REQ-INSP-012,
REQ-CMP-003)."""

from __future__ import annotations

import copy
import csv
import json
import sqlite3
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pytest
from PySide6.QtWidgets import QFileDialog, QMessageBox
from pytestqt.qtbot import QtBot

from aoi.config import Settings
from aoi.core import explain, inspector, maps, services
from aoi.core.inspector import NOT_AI_JUDGED_NOTE
from aoi.core.recipe import Recipe
from aoi.core.services import AppContext
from aoi.data.db import Database
from aoi.ui.pages.compare import ComparePage
from tests.test_req_done_in_v01 import BOARD, _window

EVIDENCE = ("overlay_path", "diff_map_path", "ai_map_path")
AI_OFF_TEXT = (  # the plain words of AI_OFF_NOTE, on Compare and under the Inspection summary
    "The recipe turns the AI check off, so the AI check did not run and no AI model judged the board: an Engineer can"
    " turn it on in the Recipe Editor."
)


def _files(ctx: AppContext) -> list[str]:
    """Every file under results/, by name."""
    return sorted(p.name for p in ctx.settings.results_dir.rglob("*") if p.is_file())


def test_req_insp_008_a_save_the_database_refuses_leaves_no_file_in_results(
    trained_ctx: AppContext, ng_board: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The re-test's scenario: the database refuses the record of an NG board twice (another program holds aoi.sqlite).
    Before, each refused save left its overlay, difference map and AI map in results/<day>/ with no record naming
    them, and neither the OK-map sweep nor a restart removed them (6 files); now none is left."""
    ctx = trained_ctx
    assert _files(ctx) == []

    def locked(*args: object, **kwargs: object) -> int:
        raise sqlite3.OperationalError("database is locked")

    monkeypatch.setattr(Database, "add_inspection", locked)
    for _ in range(2):
        with pytest.raises(sqlite3.OperationalError, match="database is locked"):
            ctx.inspect_file(BOARD, str(ng_board))
    monkeypatch.undo()
    assert ctx.inspections() == [] and _files(ctx) == []
    ctx.close()
    again = AppContext(Settings(workspace=ctx.settings.workspace, device="cpu"))  # a restart sweeps nothing either
    assert again.inspections() == [] and _files(again) == []
    again.close()


@pytest.mark.parametrize("failing", ["_diff.png", maps.AI_FILE])
def test_req_insp_008_a_map_write_that_fails_leaves_no_file(
    trained_ctx: AppContext, ng_board: Path, monkeypatch: pytest.MonkeyPatch, failing: str
) -> None:
    """The difference map's write fails after the overlay's, or the AI map's after both: the files written before it
    are removed and no record is saved. Before, the overlay (and the difference map) stayed in results/."""
    ctx = trained_ctx
    real, written = maps.save_image, []

    def save_image(path: Path, img: np.ndarray, params: tuple[int, ...] = ()) -> None:
        if str(path).endswith(failing):
            raise OSError(28, "No space left on device")
        real(path, img, params)
        written.append(Path(path).name.rsplit("_NG", 1)[1])  # ".png" for the overlay, then the map's ending

    monkeypatch.setattr(services, "save_image", save_image)
    monkeypatch.setattr(maps, "save_image", save_image)
    insp = ctx.inspector(BOARD)
    res = insp.inspect(ctx.load_image(str(ng_board)))
    with pytest.raises(OSError, match="No space left"):
        ctx.log_result(BOARD, str(ng_board), res, insp)
    assert written == ([".png"] if failing == "_diff.png" else [".png", "_diff.png"]), written
    assert ctx.inspections() == [] and _files(ctx) == [], "the overlay and the map written before are removed"


def test_req_insp_008_a_failure_after_the_record_is_saved_removes_no_file(
    trained_ctx: AppContext, ng_board: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Once the record has committed, its files are named and stay, even when the log line after it fails."""
    ctx = trained_ctx
    real = ctx.log.info

    def info(msg: str, *args: object, **kwargs: object) -> None:
        if msg == "inspection.saved":
            raise OSError(5, "Input/output error")
        real(msg, *args, **kwargs)

    monkeypatch.setattr(ctx.log, "info", info)
    with pytest.raises(OSError, match="Input/output error"):
        ctx.inspect_file(BOARD, str(ng_board))
    (rec,) = ctx.inspections()
    assert all(rec[k] and Path(rec[k]).is_file() for k in EVIDENCE) and len(_files(ctx)) == 3


def _ai_off(ctx: AppContext) -> Recipe:
    """The latest recipe, saved again as a new revision with the AI check turned off."""
    recipe = copy.deepcopy(ctx.recipe(BOARD)[1])
    recipe.use_ai = False
    ctx.save_recipe(recipe)
    return recipe


def test_req_insp_012_a_record_judged_with_the_ai_check_off_says_so_and_re_evaluate_keeps_it(
    trained_ctx: AppContext, ng_board: Path
) -> None:
    """The re-test's scenario: a recipe with the AI check off, on a board model with an active AI model, so the board is
    judged by the Golden board comparison alone. Its record names the AI model active then and the AI-off recipe
    revision, as every record names both (REQ-INSP-012), and its result carries AI_OFF_NOTE, in plain words on Compare;
    Re-evaluate under that recipe keeps the note, and under one with the AI check on puts NOT_AI_JUDGED_NOTE in its
    place. Before, the result carried no note, so nothing on the record said that no AI model judged the board."""
    ctx = trained_ctx
    active = ctx.active_model(BOARD)
    assert active is not None
    off = _ai_off(ctx)
    res = ctx.inspect_file(BOARD, str(ng_board))
    assert {c.source for c in res.checks} == {"Compare"} and res.anomaly_map is None
    (rec,) = ctx.inspections(board_model=BOARD)
    revision = ctx.recipe_history(BOARD)[0]
    assert (rec["model_version"], rec["model_uuid"]) == (active["version"], str(active["uuid"]))
    assert (rec["recipe_rev"], rec["recipe_uuid"], rec["ai_map_path"]) == (revision["revision"], revision["uuid"], None)
    stored = ctx.inspection_result(rec["id"])
    assert stored is not None
    assert [s.text() for s in explain.notes(stored)] == [AI_OFF_TEXT]
    assert stored.notes == res.notes == [inspector.AI_OFF_NOTE]
    assert inspector.ai_check(stored) == inspector.ai_check(replace(stored, notes=[])) == "OFF", "as before #246"
    assert ctx.re_evaluate(str(rec["uuid"]), off).notes == [inspector.AI_OFF_NOTE], "the same recipe keeps it"
    on = copy.deepcopy(off)
    on.use_ai = True
    assert ctx.re_evaluate(str(rec["uuid"]), on).notes == [NOT_AI_JUDGED_NOTE], "the AI check on drops it"


def test_req_cmp_003_compare_says_the_ai_check_was_off(qtbot: QtBot, trained_ctx: AppContext, ng_board: Path) -> None:
    """On Compare, a record judged with the AI check off reads as what it is: the line under the verdict names the AI
    model active then and the AI-off recipe revision, and the explanation says the AI check was off. Before, the line
    named the AI model and nothing on the page said that it had not judged the board."""
    ctx = trained_ctx
    active = ctx.active_model(BOARD)
    assert active is not None
    _ai_off(ctx)
    ctx.inspect_file(BOARD, str(ng_board))
    (rec,) = ctx.inspections(board_model=BOARD)
    win = _window(qtbot, ctx)
    compare = win.pages["Compare"]
    assert isinstance(compare, ComparePage)
    win.navigate("Compare")
    compare.show_stored(rec["id"])
    line = f": AI model {active['version']}, recipe revision {rec['recipe_rev']},"
    assert line in compare.note.text(), compare.note.text()
    assert AI_OFF_TEXT in compare.why.toPlainText(), compare.why.toPlainText()
    qtbot.waitUntil(ctx.jobs.idle, timeout=20000)


def test_req_insp_012_both_csv_files_say_whether_the_ai_check_ran(
    qtbot: QtBot, trained_ctx: AppContext, ng_board: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Four records of one board: judged with the AI check on and an active AI model (it ran), with the AI check on and
    no AI model, with the AI check off, and one stored without its result (as before migration 0006). Both CSV files
    of Logs & Export name the AI model each record names and say whether the AI check ran: RAN, NO_AI_MODEL, OFF, or
    empty when the record does not tell. Before, neither file had the column, so an AI-off record's rows named the AI
    model active then with nothing to say that it had not judged the board."""
    ctx = trained_ctx
    active = ctx.active_model(BOARD)
    assert active is not None
    ids = {}
    ctx.inspect_file(BOARD, str(ng_board))
    ids["RAN"] = ctx.inspections(board_model=BOARD)[0]["id"]  # newest first
    insp = ctx.inspector(BOARD)
    insp.model = insp.model_version = insp.model_uuid = None  # the AI check on, as if no AI model were trained
    ids["NO_AI_MODEL"] = ctx.log_result(BOARD, str(ng_board), insp.inspect(ctx.load_image(str(ng_board))), insp)
    _ai_off(ctx)
    for key in ("OFF", ""):
        ctx.inspect_file(BOARD, str(ng_board))
        ids[key] = ctx.inspections(board_model=BOARD)[0]["id"]
    ctx.db.execute("UPDATE inspections SET result_json=NULL WHERE id=?", (ids[""],))
    win = _window(qtbot, ctx)
    win.navigate("Logs & Export")
    out = tmp_path / "inspections.csv"
    monkeypatch.setattr(QFileDialog, "getSaveFileName", staticmethod(lambda *a, **k: (str(out), "CSV (*.csv)")))
    monkeypatch.setattr(QMessageBox, "question", staticmethod(lambda *a, **k: QMessageBox.StandardButton.Yes))
    win.pages["Logs & Export"].export_csv()
    qtbot.waitUntil(lambda: win.statusBar().currentMessage().startswith("Exported"), timeout=30000)
    named = (active["version"], str(active["uuid"]))
    want = {ids["RAN"]: (*named, "RAN"), ids["NO_AI_MODEL"]: ("", "", "NO_AI_MODEL"), ids["OFF"]: (*named, "OFF")}
    want[ids[""]] = (*named, "")
    for name, key in (("inspections.csv", "id"), ("inspections_checks.csv", "inspection_id")):
        with (tmp_path / name).open(encoding="utf-8-sig", newline="") as f:
            got = {(int(r[key]), r["model_version"], r["model_uuid"], r.get("ai_check")) for r in csv.DictReader(f)}
        assert got == {(i, *w) for i, w in want.items()}, name


def test_req_insp_012_a_stored_result_that_cannot_be_read_does_not_stop_the_csv_export(
    qtbot: QtBot,
    trained_ctx: AppContext,
    ng_board: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    dialogs: list[tuple[str, str]],
) -> None:
    """Three records whose stored result cannot be read (not JSON, JSON that is no result, a result without its score)
    beside one that can: Export CSV still writes both files, with an empty ai_check for each damaged record (the record
    does not tell) and its other columns as stored, and logs each by its id. Before (the #246 review), the export read
    the stored results for ai_check, so one such record stopped it with AOI-SET-007 and neither file was written."""
    ctx = trained_ctx
    for _ in range(4):
        ctx.inspect_file(BOARD, str(ng_board))
    ids = [r["id"] for r in ctx.inspections(board_model=BOARD)]  # newest first: the first one stays whole
    damaged = dict(zip(ids[1:], ("{not json", "[]", '{"verdict": "NG"}'), strict=True))
    for i, doc in damaged.items():
        ctx.db.execute("UPDATE inspections SET result_json=? WHERE id=?", (doc, i))
    win = _window(qtbot, ctx)
    win.navigate("Logs & Export")
    out = tmp_path / "inspections.csv"
    monkeypatch.setattr(QFileDialog, "getSaveFileName", staticmethod(lambda *a, **k: (str(out), "CSV (*.csv)")))
    win.pages["Logs & Export"].export_csv()
    qtbot.waitUntil(lambda: bool(dialogs) or win.statusBar().currentMessage().startswith("Exported"), timeout=30000)
    assert dialogs == []
    assert win.statusBar().currentMessage().startswith("Exported 4 records")
    version = ctx.inspections(board_model=BOARD)[0]["model_version"]
    for name, key in (("inspections.csv", "id"), ("inspections_checks.csv", "inspection_id")):
        with (tmp_path / name).open(encoding="utf-8-sig", newline="") as f:
            got = {(int(r[key]), r["model_version"], r["ai_check"]) for r in csv.DictReader(f)}
        assert got == {(ids[0], version, "RAN"), *((i, version, "") for i in damaged)}, name
    log = ctx.settings.root / "logs" / f"aoi-{datetime.now(UTC):%Y-%m-%d}.jsonl"
    rows = [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines()]
    assert sorted(r["inspection_id"] for r in rows if r["event"] == "export.result_not_read") == sorted(damaged)
