"""REQ-INSP-012 (stage S25a): a saved result names the region, metric and threshold of every check and the AI model
version and recipe revision that decided it, by version and by UUID, and reads back as it was decided (the evidence
REQ-INSP-008 asks to save with every result; S25b saves every result)."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest

from aoi.config import Settings
from aoi.core.imaging import list_images
from aoi.core.inspector import NG, Check, InspectionResult, Inspector
from aoi.core.recipe import ROI, Recipe
from aoi.core.services import AppContext
from aoi.data.db import Database
from tests.conftest import TrainedModel
from tests.regression import make_regression_set as rs
from tests.test_req_done_in_v01 import BOARD

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
    score, checks, defects, compare metrics and regions, notes, view and time; only the images are left behind."""
    engine = _engine(tiny_model)
    results = [engine.inspect(tiny_model.ctx.load_image(ng_board))]
    engine.reference = None  # no golden board: the comparison is skipped with a note
    results.append(engine.inspect(tiny_model.ctx.load_image(ng_board)))
    assert results[0].compare is not None and results[1].compare is None and results[1].notes
    for res in results:
        d = res.to_dict()
        text = json.dumps(d, allow_nan=False)  # a NumPy scalar or a NaN would be refused here
        back = InspectionResult.from_dict(json.loads(text))
        assert back.to_dict() == d
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
    """Every result of the regression set, saved through the service the Inspection page calls, names in the database
    the region, metric and threshold of every check and the AI model version and recipe revision that decided it, by
    version and by UUID; the checks table and the stored result agree row for row. The CSV part follows in S25b."""
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
