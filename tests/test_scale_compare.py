"""REQ-RCP-006 on Compare (S29 part 3): what judged a board counts the scale, at which the engine applies a recipe's
sizes in mm, when an Operator signs in and in a stored result's note."""

from __future__ import annotations

from pathlib import Path

from pytestqt.qtbot import QtBot

from aoi.core.recipe import disc_area
from aoi.core.services import AppContext
from aoi.ui.pages.compare import NO_VERDICT, ComparePage
from tests.test_compare_reevaluate import _stored_on_compare
from tests.test_req_done_in_v01 import BOARD, _window


def test_req_rcp_006_an_operators_sign_in_judges_again_a_board_judged_at_another_scale(
    qtbot: QtBot, trained_ctx: AppContext, ng_board: Path
) -> None:
    """A board an Engineer inspected on Compare, then a scale set and an Operator's sign-in: with every size held in px,
    nothing that judged the board changed, and it keeps its verdict; with the minimum defect size held in mm, the recipe
    gives other px at the new scale, so the board is cleared and judged again by the recipe at that scale, as after a
    revision saved since (S28c's _judging, which now compares the recipe in px at the scale each judges at), and the
    Operator signing in again keeps that board, judged by the recipe in px at the scale (S29 review)."""
    ctx = trained_ctx
    scale = ctx.set_scale(BOARD, 476, 10)
    win = _window(qtbot, ctx, "Engineer")
    compare = win.pages["Compare"]
    assert isinstance(compare, ComparePage) and win.navigate("Compare")
    for mm in (None, 0.5):
        win.set_user("engineer")
        if mm is not None:  # held in mm with its area at the scale, as Save Recipe stores it; taken up when shown
            _, recipe = ctx.recipe(BOARD)
            recipe.min_defect_mm, recipe.min_defect_area = mm, disc_area(mm * scale)
            ctx.save_recipe(recipe)
            ctx.set_scale(BOARD, 714, 10)  # after the save: the board is judged at 71.4 px/mm, not as stored
            win.navigate("Inspection")
            win.navigate("Compare")
        compare.set_test(str(ng_board))
        qtbot.waitUntil(lambda: ctx.jobs.idle() and compare._bg is None and compare.res is not None, timeout=60000)
        judged = compare.res
        win.set_user("operator")
        assert compare.res is judged and compare._bg is None, "nothing that judged the board changed (S29 review)"
        win.set_user("engineer")
        scale = ctx.set_scale(BOARD, 952 if mm is None else 1428, 10)
        win.set_user("operator")
        if mm is None:
            assert compare.res is judged and compare._bg is None, "a size in px judges alike at any scale"
            continue
        assert (compare.verdict.text(), compare.metrics.rowCount(), compare._bg is not None) == (NO_VERDICT, 0, True)
        qtbot.waitUntil(lambda: ctx.jobs.idle() and compare._bg is None and compare.res is not None, timeout=60000)
        judged = compare.res  # judged for the Operator by the recipe in px at the scale, which signing in again keeps
        win.set_user("operator")
        regions = next(c.explain for c in judged.checks if c.name == "Difference regions")
        assert compare.res is judged and regions == f"blobs ≥ {disc_area(mm * scale)} px after noise clean-up"


def test_req_rcp_006_a_stored_result_judged_at_another_scale_names_both(
    qtbot: QtBot, trained_ctx: AppContext, ng_board: Path
) -> None:
    """A stored result judged at one scale, opened on Compare once its board model has another, names both in the line
    under the verdict: Re-evaluate applies sizes in mm at the one it was judged at (ADR 0006), and Try other thresholds
    shows them at the board model's (S29). Judged at the board model's scale, it names none."""
    ctx = trained_ctx
    ctx.set_scale(BOARD, 476, 10)
    _, compare, iid = _stored_on_compare(qtbot, ctx, ng_board, "Engineer")
    assert "scale" not in compare.note.text()
    ctx.set_scale(BOARD, 952, 10)
    compare.show_stored(iid)
    qtbot.waitUntil(lambda: compare.loaded and compare._bg is None, timeout=10000)
    assert compare.note.text().endswith(
        "It was judged at a scale of 47.60 px/mm, at which Re-evaluate applies sizes in mm; the board model's scale, at"
        " which Try other thresholds shows them, is now 95.20 px/mm."
    )
    ctx.set_scale(BOARD, 476.01, 10)  # 47.601 px/mm, 47.60 at two decimals as the result's: told apart (S29 review)
    compare.show_stored(iid)
    qtbot.waitUntil(lambda: compare.loaded and compare._bg is None, timeout=10000)
    assert "scale of 47.600 px/mm, at" in compare.note.text() and compare.note.text().endswith("now 47.601 px/mm.")
