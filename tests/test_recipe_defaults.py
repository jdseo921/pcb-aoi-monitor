"""Reset to Defaults on the Recipe Editor (Jay, 2026-11-11; #460): every threshold back to the value a new board
model starts with, in the fields only; Save Recipe keeps them as an audited revision and the ROIs stay."""

from __future__ import annotations

from typing import cast

from pytestqt.qtbot import QtBot

from aoi.core.recipe import ROI, Recipe
from aoi.core.services import AppContext
from aoi.ui.pages.recipe_editor import RecipeEditorPage
from tests.test_first_board_model_store import shell

BM = "TBOX-A1"


def test_460_reset_to_defaults_sets_the_fields_and_saves_nothing_until_save_recipe(
    qtbot: QtBot, ctx: AppContext
) -> None:
    ctx.ensure_board_model(BM)
    default = Recipe(board_model=BM)
    changed = Recipe(board_model=BM, diff_threshold=20, ssim_min=0.55, changed_pct_max=3.0, max_diff_regions=4)
    changed.warn_ratio, changed.min_defect_area, changed.rois = 0.6, 90, [ROI("R1", "Presence", 5, 5, 40, 40)]
    ctx.save_recipe(changed, "Loosened for a trial.")
    win = shell(qtbot, ctx, "engineer")
    win.select_board_model(BM)
    win.navigate("Recipe Editor")
    page = cast(RecipeEditorPage, win.pages["Recipe Editor"])
    assert page.diff.value() == 20 and page.ssim.value() == 0.55
    page.act_defaults.trigger()
    assert win.statusBar().currentMessage() == "Default values set. Press Save Recipe to keep them as a new revision."
    shown = page._collect()
    for name in ("diff_threshold", "min_defect_area", "ssim_min", "changed_pct_max", "max_diff_regions", "warn_ratio",
                 "use_ai", "use_compare", "anomaly_threshold", "copper"):  # fmt: skip
        assert getattr(shown, name) == getattr(default, name), name
    assert [r.name for r in shown.rois] == ["R1"]  # the ROIs stay
    stored = ctx.recipe(BM)[1]
    assert stored.diff_threshold == 20 and stored.ssim_min == 0.55  # nothing saved by the button itself
    assert len(ctx.audit_entries(action="recipe.save")) == 1
