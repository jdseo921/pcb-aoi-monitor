"""REQ-INSP-012 (stage S25a) and REQ-INSP-008 (S25b): a saved result names the region, metric and threshold of every
check and the AI model version and recipe revision that decided it, by version and by UUID, reads back as it was
decided, and every result is saved with that evidence before the next board starts."""

from __future__ import annotations

import csv
import json
from pathlib import Path

import numpy as np
import pytest
from PySide6.QtWidgets import QFileDialog, QMessageBox
from pytestqt.qtbot import QtBot

from aoi.config import Settings
from aoi.core.imaging import list_images
from aoi.core.inspector import NG, NO_GOLDEN_NOTE, Check, InspectionResult, Inspector
from aoi.core.recipe import ROI, Recipe
from aoi.core.services import AppContext, export_csv
from aoi.data.db import Database
from aoi.ui import theme
from tests.conftest import TrainedModel
from tests.regression import make_regression_set as rs
from tests.test_req_done_in_v01 import BOARD, _window

CHECKS = ["SSIM similarity", "Changed area %", "Difference regions", "Alignment inliers", "AI anomaly score"]
ROI_CHECK, ROI_REGION = "ROI R1 [Presence]", "R1 @ 110,110 110x110"


@pytest.fixture(scope="module")
def regression_boards(tmp_path_factory: pytest.TempPathFactory) -> list[Path]:
    out = tmp_path_factory.mktemp("regression")
    return [out / b.name for b in rs.generate(out)]


def _engine(tiny_model: TrainedModel) -> Inspector:
    recipe = Recipe(board_model=BOARD, rois=[ROI("R1", "Presence", 110, 110, 110, 110)])  # the IC the NG board lacks
    return Inspector(recipe, tiny_model.model, tiny_model.reference, model_version=tiny_model.version)


def test_results_round_trip_json(tiny_model: TrainedModel, ng_board: Path, synthetic_dataset: Path) -> None:
    """`to_dict` holds plain values only, so JSON writes it unchanged, and `from_dict` gives back the same verdict,
    score, checks, defects, compare metrics and regions, notes, view and time; only the images are left behind. The
    second result is a Side board with the no-golden-board note, so neither can pass on `from_dict`'s defaults (#246:
    before, `to_dict` without its notes or its view passed, as both sides of `back.to_dict() == d` then lacked it)."""
    engine = _engine(tiny_model)
    results = [engine.inspect(tiny_model.ctx.load_image(ng_board))]
    engine.reference, engine.side = None, "Side"  # no golden board: the comparison is skipped with a note
    results.append(engine.inspect(tiny_model.ctx.load_image(ng_board)))
    assert results[0].compare is not None and results[1].compare is None and results[1].notes == [NO_GOLDEN_NOTE]
    for res in results:
        d = res.to_dict()
        text = json.dumps(d, allow_nan=False)  # a NumPy scalar or a NaN would be refused here
        back = InspectionResult.from_dict(json.loads(text))
        assert back.to_dict() == d and {"notes", "view", "elapsed_ms"} <= d.keys()
        assert (back.notes, back.view, back.elapsed_ms) == (res.notes, res.view, res.elapsed_ms)
        assert back.checks == res.checks and back.defects == res.defects and back.metrics_dict() == res.metrics_dict()
        assert [c.region for c in back.checks] == ["Board"] * (len(back.checks) - 1) + [ROI_REGION]
        assert back.image is None and back.reference is None and back.anomaly_map is None
        if res.compare is not None:
            assert back.compare is not None and back.compare.diff_map is None and back.compare.aligned is None
            assert back.compare.regions == res.compare.regions and back.compare.metrics == res.compare.metrics
        else:
            assert back.compare is None
    assert results[0].defects and results[0].compare is not None and results[0].compare.regions
    # NumPy scalars, should a check ever carry one, become the Python values they hold (SQLite would store a float32
    # as a blob and json.dumps refuses it); a field a later build adds to the JSON is left out when read.
    odd = InspectionResult(NG, np.float32(1.5), [Check("x", np.float32(2.0), np.float64(1.0), "r", NG, "AI")])
    plain = json.loads(json.dumps(odd.to_dict(), allow_nan=False))
    assert type(plain["score"]) is float and type(plain["checks"][0]["value"]) is float
    plain["checks"][0]["future_field"], plain["future_field"] = 1, 2
    assert InspectionResult.from_dict(plain).checks == [Check("x", 2.0, 1.0, "r", NG, "AI")]


def test_req_insp_012_all_five_present_in_db(
    trained_ctx: AppContext, tiny_model: TrainedModel, regression_boards: list[Path]
) -> None:
    """Every result of the synthetic regression set, saved through the service the Inspection page calls, names in the
    database the region, metric and threshold of every check and the AI model version and recipe revision that decided
    it, by version and by UUID; the checks table and the stored result agree row for row. The CSV part follows in
    S25b."""
    ctx = trained_ctx
    recipe = ctx.recipe(BOARD)[1]
    recipe.rois.append(ROI("R1", "Presence", 110, 110, 110, 110))  # one ROI check, so a region other than the board
    rev = ctx.save_recipe(recipe)
    latest = next(h for h in ctx.recipe_history(BOARD) if h["revision"] == rev)
    active = ctx.active_model(BOARD)
    assert active is not None and rev == 2, "revision 1 is the stored default, this is the saved one"
    for path in regression_boards:
        ctx.inspect_file(BOARD, str(path))
    rows = ctx.inspections(board_model=BOARD)
    assert len(rows) == len(regression_boards) == rs.N_OK + rs.N_NG
    for row in rows:
        assert (row["model_version"], row["model_uuid"]) == (active["version"], active["uuid"])
        assert (row["recipe_rev"], row["recipe_uuid"]) == (rev, latest["uuid"])
        checks = ctx.checks_for(row["id"])
        assert [c["metric"] for c in checks] == [*CHECKS, ROI_CHECK]
        assert [c["region"] for c in checks] == ["Board"] * len(CHECKS) + [ROI_REGION]
        for c in checks:
            assert isinstance(c["value"], float) and isinstance(c["threshold"], float) and c["rule"]
            assert c["result"] in ("OK", "WARN", "NG", "INFO") and c["source"] in ("AI", "Compare", "ROI")
        assert checks[4]["threshold"] == pytest.approx(tiny_model.model.image_threshold)  # the recipe sets none
        assert checks[5]["threshold"] == pytest.approx(recipe.rois[0].ai_score)
        stored = ctx.inspection_result(row["id"])
        assert stored is not None and stored.verdict == row["result"] and stored.view == row["view"] == "Top"
        assert len(stored.defects) == row["defect_count"] and len(ctx.defects_for(row["id"])) == row["defect_count"]
        assert [(c.region, c.name, c.value, c.threshold, c.rule, c.verdict) for c in stored.checks] == [
            (c["region"], c["metric"], c["value"], c["threshold"], c["rule"], c["result"]) for c in checks
        ]
    assert {r["result"] for r in rows} >= {"OK", "NG"}, "boards the engine passes and fails (OK depends on the model)"
    # The engine names the stored revision it applies, also when handed that recipe; an unsaved recipe (the Compare
    # page's what-if thresholds) names none, so no record can claim a revision that did not decide it.
    assert ctx.inspector(BOARD, recipe=ctx.recipe(BOARD)[1]).recipe_uuid == latest["uuid"]
    unsaved = ctx.inspector(BOARD, recipe=Recipe(board_model=BOARD, ssim_min=0.5))
    assert (unsaved.recipe_rev, unsaved.recipe_uuid, unsaved.model_uuid) == (None, None, active["uuid"])


def test_req_insp_012_a_workspace_from_before_gets_revision_1_at_the_first_start(
    tmp_path: Path, ctx: AppContext, synthetic_dataset: Path
) -> None:
    """A board model made before S25 has no stored recipe revision: the first start stores the default as revision 1 by
    the system, with one audit entry, and a second start adds nothing; importing a board model's first samples stores
    it too, as creating the board model does (tested in test_services_api)."""
    ws = tmp_path / "old_workspace"
    old = Database(ws / "aoi.sqlite", ws)  # the data layer alone, as a workspace from before this stage
    old.ensure_board_model("OLD")
    old.close()
    for start in (1, 2):
        app = AppContext(Settings(workspace=str(ws), device="cpu"))
        history = app.recipe_history("OLD")
        assert [(h["revision"], h["user"]) for h in history] == [(1, "system")], f"start {start}"
        entries = app.audit_entries(object_type="recipe", action="recipe.default")
        assert len(entries) == 1 and (entries[0]["user_uuid"], entries[0]["role"]) == (None, None)
        assert entries[0]["object_uuid"] == history[0]["uuid"] and entries[0]["after"] == app.recipe("OLD")[1].to_dict()
        app.close()
    ctx.import_samples("FRESH", [str(p) for p in list_images(synthetic_dataset / "train" / "ok")[:2]], "OK")
    assert [h["revision"] for h in ctx.recipe_history("FRESH")] == [1]


def test_req_insp_008_saved_before_next_board(
    qtbot: QtBot, trained_ctx: AppContext, synthetic_dataset: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """In a run, each board's record, with its checks, is in the database before the next board's inspection starts;
    there is no Auto-save switch to leave off, and Save Image… (F9) writes a picture, never a second record. (The read
    on the pool thread is exact: the save commits under the database lock before the next board is submitted; a save
    moved after `next_board()` is caught because the pool starts the next board within the save's time, almost always.)
    """
    boards = list_images(synthetic_dataset / "test" / "ng")[:3]
    win = _window(qtbot, trained_ctx, "Operator")
    page = win.pages["Inspection"]
    win.navigate("Inspection")
    qtbot.waitUntil(trained_ctx.jobs.idle, timeout=10000)  # the Compare page's start-up load of the golden board
    saved_at_start: list[int] = []
    without_checks: list[int] = []
    real = Inspector.inspect

    def inspect(engine: Inspector, image: np.ndarray) -> InspectionResult:
        rows = trained_ctx.inspections(board_model=BOARD)  # read on the pool thread, as this board starts
        without_checks.extend(r["id"] for r in rows if not trained_ctx.checks_for(r["id"]))
        saved_at_start.append(len(rows))
        return real(engine, image)

    monkeypatch.setattr(Inspector, "inspect", inspect)
    assert not hasattr(page, "autosave") and page.act_save.text() == "Save Image…"
    page._set_queue(boards)
    page.start_run()
    qtbot.waitUntil(lambda: not page.running and page.worker is None, timeout=60000)
    assert saved_at_start == [0, 1, 2], "each record was written before the next board started"
    assert without_checks == [], "a record without its checks"
    rows = trained_ctx.inspections(board_model=BOARD)
    assert [Path(r["image_path"]).name for r in rows] == [b.name for b in reversed(boards)]  # newest first
    out = tmp_path / "picture.png"
    monkeypatch.setattr(QFileDialog, "getSaveFileName", staticmethod(lambda *a, **k: (str(out), "PNG (*.png)")))
    page.act_save.trigger()
    qtbot.waitUntil(lambda: page._bg is None, timeout=30000)  # the save runs on the pool (#241)
    assert out.exists() and len(trained_ctx.inspections(board_model=BOARD)) == 3, "Save Image… adds no record"


def test_req_insp_012_all_five_present_in_csv(
    qtbot: QtBot,
    trained_ctx: AppContext,
    regression_boards: list[Path],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The Logs & Export CSV carries the evidence too: a second file beside the records with one row per check (region,
    metric, source, value, threshold, rule, result) and the UUIDs of the AI model version and recipe revision, equal to
    the checks table row for row; the records file keeps its columns and gains the UUIDs after them."""
    ctx = trained_ctx
    for path in regression_boards[:3]:
        ctx.inspect_file(BOARD, str(path))
    older = {"board_model": BOARD, "result": "OK", "view": "Top", "image_path": str(regression_boards[3])}
    ctx.db.add_inspection(older, [], None)  # as a record from before migration 0006: no checks stored
    win = _window(qtbot, ctx)  # an Engineer, since exports need the role
    logs = win.pages["Logs & Export"]
    win.navigate("Logs & Export")
    out = tmp_path / "inspections.csv"
    monkeypatch.setattr(QFileDialog, "getSaveFileName", staticmethod(lambda *a, **k: (str(out), "CSV (*.csv)")))
    monkeypatch.setattr(QMessageBox, "question", staticmethod(lambda *a, **k: QMessageBox.StandardButton.Yes))
    logs.export_csv()  # on a pool thread since #194: the files are there once the status line says so
    qtbot.waitUntil(lambda: win.statusBar().currentMessage().startswith("Exported"), timeout=30000)
    with out.open(encoding="utf-8-sig", newline="") as f:
        records = list(csv.DictReader(f))
    with (tmp_path / "inspections_checks.csv").open(encoding="utf-8-sig", newline="") as f:
        exported = list(csv.DictReader(f))
    rows = ctx.inspections(board_model=BOARD)
    active = ctx.active_model(BOARD)
    assert active is not None and [int(r["id"]) for r in records] == [r["id"] for r in rows] and len(rows) == 4
    assert list(records[0])[:4] == ["id", "time", "board_model", "view"] and list(records[0])[-3:] == [
        "uuid", "model_uuid", "recipe_uuid",
    ]  # fmt: skip
    for rec, r in zip(records, rows, strict=True):
        assert (rec["uuid"], rec["model_uuid"], rec["recipe_uuid"]) == tuple(
            r[k] or "" for k in ("uuid", "model_uuid", "recipe_uuid")
        )
    assert records[0]["model_uuid"] == "" and ctx.checks_for(rows[0]["id"]) == [], "the older record, newest first"
    expected = [(r, c) for r in rows for c in ctx.checks_for(r["id"])]
    assert len(exported) == len(expected) == 3 * len(CHECKS)  # the default recipe: no ROI check; the older record: none
    for row, (r, c) in zip(exported, expected, strict=True):
        assert (int(row["inspection_id"]), row["inspection_uuid"], int(row["no"])) == (r["id"], r["uuid"], c["no"])
        assert (row["region"], row["metric"], row["source"], row["rule"], row["result"]) == (
            c["region"], c["metric"], c["source"], c["rule"], c["result"],
        )  # fmt: skip
        assert (float(row["value"]), float(row["threshold"])) == (c["value"], c["threshold"])
        assert (row["model_version"], row["model_uuid"]) == (active["version"], active["uuid"])
        assert (int(row["recipe_rev"]), row["recipe_uuid"]) == (r["recipe_rev"], r["recipe_uuid"]) and row[
            "recipe_uuid"
        ]
        assert (row["time"], row["board_model"], row["view"]) == (r["time"], BOARD, "Top")
    tail = f"{len(exported)} check rows to {tmp_path}: inspections.csv, inspections_checks.csv"
    assert win.statusBar().currentMessage().endswith(tail)
    export_csv(tmp_path / "none.csv", [], ["a", "b"])  # no record has checks: the file still names its columns
    assert (tmp_path / "none.csv").read_bytes() == b"\xef\xbb\xbfa,b\r\n"


def test_req_insp_008_a_result_that_cannot_be_saved_stops_the_run_with_its_code(
    qtbot: QtBot,
    trained_ctx: AppContext,
    synthetic_dataset: Path,
    monkeypatch: pytest.MonkeyPatch,
    dialogs: list[tuple[str, str]],
) -> None:
    """The disk is full (or the workspace cannot be written, or the database fails) while a result is saved: the verdict
    stays on screen, the run stops before the next board, the dialog carries AOI-INSP-008 with the file name, the
    alarm is listed, nothing half-written is in the database or in results/ (#246: the overlay and maps stayed there),
    and Next Board carries on with the queue."""
    boards = list_images(synthetic_dataset / "test" / "ng")[:2]
    win = _window(qtbot, trained_ctx, "Operator")
    page = win.pages["Inspection"]
    win.navigate("Inspection")
    qtbot.waitUntil(trained_ctx.jobs.idle, timeout=10000)

    def no_space(*args: object, **kwargs: object) -> int:
        raise OSError(28, "No space left on device")

    monkeypatch.setattr(Database, "add_inspection", no_space)
    page._set_queue(boards)
    page.start_run()
    qtbot.waitUntil(lambda: len(dialogs) == 1, timeout=30000)
    assert dialogs[-1][0] == "AOI-INSP-008 Result not saved" and boards[0].name in dialogs[-1][1]
    assert not page.running and page.worker is None and page.queue_pos == 0, "the run stopped before the next board"
    assert page.last is not None and page.verdict.text() == theme.verdict_label(page.last.verdict)
    assert "AOI-INSP-008" in page.alarms.item(0).text() and trained_ctx.inspections(board_model=BOARD) == []
    assert [p.name for p in trained_ctx.settings.results_dir.rglob("*") if p.is_file()] == []
    assert page.act_next.isEnabled() and not page.act_stop.isEnabled()
