"""REQ-RCP-006 (S29): a board model's scale in px per mm, measured on its Golden board, and a recipe whose sizes are in
mm, which the engine applies in px at that scale; a recipe or a board model without one judges exactly as before."""

from __future__ import annotations

import math
import sqlite3
from pathlib import Path

import pytest

from aoi.core.inspector import InspectionResult
from aoi.core.recipe import ROI, Recipe, disc_area, disc_width
from aoi.core.services import AppContext
from aoi.data.paths import to_stored
from aoi.errors import AoiError
from tests.test_re_evaluate import _assert_close, _store
from tests.test_req_done_in_v01 import BOARD

BOARD_PX_PER_MM = 640 / 150  # the synthetic boards are 640 px wide; taken as 150 mm, as the resolution test does


def test_req_rcp_006_a_board_model_stores_its_scale_from_a_known_length(trained_ctx: AppContext) -> None:
    """Migration 0012 adds board_models.px_per_mm, NULL until an Engineer measures a known length on the Golden board:
    set_scale stores length / distance and audits it with the scale before, the length, the distance and the Golden
    board file it was measured on. A length or distance that is not a number above 0, a scale outside 0.01 to 100000
    px/mm, or an unknown board model, is refused with AOI-RCP-008 before anything is written or audited; the database
    refuses 0 or less, text and inf."""
    ctx = trained_ctx
    assert "px_per_mm" in {r["name"] for r in ctx.db.query("PRAGMA table_info(board_models)")}
    assert ctx.scale(BOARD) is None
    before = ctx.audit_entries()
    for board, length, distance in (
        (BOARD, 0, 10), (BOARD, 476, 0), (BOARD, -476, 10), (BOARD, math.nan, 10), (BOARD, 476, math.inf),
        (BOARD, 1e308, 1e-308), (BOARD, True, 10), (BOARD, 476, True), ("NO_SUCH_BOARD", 476, 10),
        (BOARD, "476", 10), (BOARD, 476, None), (BOARD, 1, 1000), (BOARD, 2e6, 10),  # S29 review: text, None, range
    ):  # fmt: skip
        with pytest.raises(AoiError) as refused:
            ctx.set_scale(board, length, distance)
        assert refused.value.code == "AOI-RCP-008", (board, length, distance)
    assert ctx.scale(BOARD) is None and ctx.audit_entries() == before
    assert ctx.set_scale(BOARD, 476.0, 10.0) == ctx.scale(BOARD) == 47.6
    entry = ctx.audit_entries(action="board_model.scale")[0]
    golden = to_stored(Path(str(ctx.reference_image(BOARD))), ctx.settings.root)
    assert (entry["object_type"], entry["object_uuid"], entry["before"]) == ("board_model", BOARD, {"px_per_mm": None})
    assert entry["after"] == {"px_per_mm": 47.6, "length_px": 476.0, "distance_mm": 10.0, "image": golden}
    ctx.set_scale(BOARD, 380, 8)
    assert ctx.audit_entries(action="board_model.scale")[0]["before"] == {"px_per_mm": 47.6}
    for damaged in (0, -47.6, "abc", math.inf):  # text too, which SQLite would order above any number (S29 review)
        with pytest.raises(sqlite3.IntegrityError):
            ctx.db.execute("UPDATE board_models SET px_per_mm = ? WHERE name = ?", (damaged, BOARD))


def test_req_rcp_006_a_recipe_in_px_judges_as_before(trained_ctx: AppContext, ng_board: Path) -> None:
    """A recipe that sets no size in mm, as every recipe stored before S29, is stored as before (its body has no key
    of S29's) and judges a board the same with a scale as without: every check, defect and the verdict."""
    ctx = trained_ctx
    _, recipe = ctx.recipe(BOARD)
    recipe.rois = [ROI("R1", "Presence", 110, 110, 110, 110)]
    ctx.save_recipe(recipe)
    body = ctx.recipe(BOARD)[1].to_dict()
    assert "min_defect_mm" not in body and all("mm" not in roi for roi in body["rois"])
    img = ctx.load_image(ng_board)
    without = ctx.inspect(BOARD, img)
    ctx.set_scale(BOARD, 476, 10)
    scaled = ctx.inspect(BOARD, img)
    assert (scaled.verdict, scaled.checks, scaled.defects) == (without.verdict, without.checks, without.defects)
    assert scaled.px_per_mm == 47.6 and without.px_per_mm is None


def test_req_rcp_006_sizes_in_mm_are_applied_at_the_board_models_scale(trained_ctx: AppContext, ng_board: Path) -> None:
    """The engine applies a size in mm at the board model's scale: the minimum defect size as the area of a round
    defect that wide, rounded up so that a defect of exactly that size is kept, and an ROI's place and size to the
    nearest px; px sizes back to mm and in again give the same px. The record keeps the scale it was judged at, and an
    engine built before a new scale is no longer the current one, so Inspection builds another for its next board, nor
    is what it judged an AI Model Test run with (its JudgedBy, #250), which counts the scale as the engine does."""
    recipe = Recipe(board_model=BOARD, min_defect_mm=0.8, rois=[ROI("R1", w=1, h=1, mm=[2.0, 2.5, 5.0, 1.3])])
    px = recipe.in_px(47.6)
    assert px.min_defect_area == math.ceil(math.pi / 4 * 38.08**2) == 1139
    assert [(r.x, r.y, r.w, r.h, r.mm) for r in px.rois] == [(95, 119, 238, 62, [2.0, 2.5, 5.0, 1.3])]
    assert recipe.in_px(None) is recipe and (recipe.rois[0].w, recipe.min_defect_area) == (1, 40)
    assert all(disc_area(disc_width(area)) == area for area in range(1, 5000)) and disc_area(7.0) == 39  # 38.48 up
    ctx = trained_ctx
    ctx.set_scale(BOARD, 640, 150)
    engine = ctx.inspector(BOARD)
    assert engine.recipe.min_defect_area == 40 and ctx.engine_is_current(BOARD, engine)
    assert ctx.engine_is_current(BOARD, engine.judged_by)  # an AI Model Test run judged at this scale is current
    _, saved = ctx.recipe(BOARD)
    saved.min_defect_mm = 3.0  # 12.8 px at 4.27 px/mm: a round region of 129 px of area or more
    ctx.save_recipe(saved)
    assert ctx.inspector(BOARD).recipe.min_defect_area == 129 and not ctx.engine_is_current(BOARD, engine)
    ctx.inspect_file(BOARD, str(ng_board))
    stored = ctx.inspection_result(ctx.inspections(board_model=BOARD)[0]["id"])
    assert stored is not None and stored.px_per_mm == pytest.approx(640 / 150)
    regions = next(c for c in stored.checks if c.name == "Difference regions")
    assert regions.explain == "blobs ≥ 129 px after noise clean-up"
    engine = ctx.inspector(BOARD)
    ctx.set_scale(BOARD, 1280, 150)
    assert not ctx.engine_is_current(BOARD, engine) and ctx.inspector(BOARD).recipe.min_defect_area == 515
    assert not ctx.engine_is_current(BOARD, engine.judged_by)


def test_req_rcp_006_a_stored_result_is_judged_again_at_its_own_scale(trained_ctx: AppContext, ng_board: Path) -> None:
    """Re-evaluate applies the thresholds' sizes in mm at the scale the result was judged at, which its record keeps,
    not at a scale set since: with the recipe it was judged by, the result gets back its checks, defects and verdict
    after the board model's scale doubles, while inspecting the board at the new scale judges its regions otherwise. A
    result judged without a scale is judged again at the board model's scale now, and the result keeps the scale it
    was judged again at. Its difference regions are found at that scale, as inspecting finds them, also while the AI
    map decodes (#249). A stored scale that is not a number above 0 is refused as it is read, as a damaged time is."""
    ctx = trained_ctx
    without = _store(ctx, ng_board)  # judged before any scale: its record keeps none
    ctx.set_scale(BOARD, 640, 150)
    _, recipe = ctx.recipe(BOARD)
    recipe.min_defect_mm = 3.0
    ctx.save_recipe(recipe)
    again = ctx.re_evaluate(without, recipe)  # 3 mm at 4.27 px/mm, the board model's scale now, which it keeps
    regions = [c.explain for c in again.checks if c.name == "Difference regions"]
    assert regions == ["blobs ≥ 129 px after noise clean-up"] and again.px_per_mm == pytest.approx(640 / 150)
    uuid = _store(ctx, ng_board)
    as_judged = ctx.inspection_result(ctx.inspections(board_model=BOARD)[0]["id"])
    assert as_judged is not None and as_judged.px_per_mm == pytest.approx(640 / 150)
    wide = Recipe.from_dict({**recipe.to_dict(), "min_defect_mm": 50.0})  # 213 px wide here: no region is as big
    _assert_close(ctx.re_evaluate(uuid, wide), ctx.inspect(BOARD, ctx.load_image(ng_board), wide), "50 mm")
    damaged = [("elapsed_ms", "damaged"), *(("px_per_mm", v) for v in ("damaged", 0, -1, math.nan, math.inf, True))]
    for name, value in damaged:  # a damaged scale is refused as it is read, as a damaged time is
        with pytest.raises(ValueError):
            InspectionResult.from_dict({**as_judged.to_dict(), name: value})
    ctx.set_scale(BOARD, 1280, 150)
    again = ctx.re_evaluate(uuid, ctx.recipe(BOARD)[1])
    _assert_close(again, as_judged, "judged again after the scale changed")
    assert again.px_per_mm == as_judged.px_per_mm != ctx.scale(BOARD)  # its own scale, kept
    now = ctx.inspect(BOARD, ctx.load_image(ng_board))
    regions = [c.explain for c in now.checks if c.name == "Difference regions"]
    assert regions == ["blobs ≥ 515 px after noise clean-up"]
