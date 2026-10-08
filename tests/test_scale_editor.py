"""REQ-RCP-006 (S29, parts 2 and 3): the sizes the Recipe Editor and Compare show in mm at the board model's scale, and
Calibrate Scale… on the Recipe Editor (sketch recipe-editor.md; Q21: without a scale a recipe saves with its sizes in
px, under AOI-RCP-005)."""

from __future__ import annotations

from pathlib import Path

import pytest
from PySide6.QtWidgets import QGraphicsRectItem, QMessageBox
from pytestqt.qtbot import QtBot

from aoi.core.recipe import ROI, disc_area, disc_width
from aoi.core.services import AppContext
from aoi.ui.pages.compare import ComparePage
from aoi.ui.pages.recipe_editor import RecipeEditorPage
from tests.test_compare_reevaluate import _stored_on_compare
from tests.test_compare_stored import save_to_recipe
from tests.test_req_done_in_v01 import BOARD, _window

HELD = (  # AOI-RCP-009 under the scale: the code, the title and what to do, in view for touch and keys (S29 review)
    "AOI-RCP-009 Sizes are held in px: Press Save Recipe to store them in mm, so that they follow the scale; that"
    " alone changes no verdict at this scale."
)


def _headers(page: RecipeEditorPage) -> list[str]:
    return [page.roi_table.horizontalHeaderItem(i).text() for i in range(page.roi_table.columnCount())]


def _row(page: RecipeEditorPage) -> list[str]:
    return [page.roi_table.item(0, j).text() for j in range(2, 6)]


def test_req_rcp_006_sizes_show_in_mm_at_the_board_models_scale(
    qtbot: QtBot, trained_ctx: AppContext, ng_board: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Without a scale the Recipe Editor shows its sizes in px beside the amber AOI-RCP-005 (Q21). With one, it names
    the scale, and the ROI table and the minimum defect size show mm, the size with the px it spans beside it; a recipe
    saved untouched holds its sizes in mm and judges the board as before, a size typed in mm is saved as typed, and
    Compare's what-if form shows it in mm too. Without a board model the page shows neither the scale nor the badge."""
    ctx = trained_ctx
    _, recipe = ctx.recipe(BOARD)
    recipe.rois = [ROI("R1", "Presence", 110, 110, 110, 110)]
    ctx.save_recipe(recipe)
    before = ctx.inspect(BOARD, ctx.load_image(ng_board))
    monkeypatch.setattr(QMessageBox, "information", lambda *a: QMessageBox.StandardButton.Ok)
    win = _window(qtbot, ctx, "Engineer")
    page = win.pages["Recipe Editor"]
    assert isinstance(page, RecipeEditorPage)
    win.navigate("Recipe Editor")
    assert page.scale_badge.isVisible() and page.scale_badge.text() == "AOI-RCP-005 Sizes are shown in px"
    tip = page.scale_badge.toolTip()
    assert not page.scale_text.isVisible() and tip.endswith("from a known distance on its Golden board.")
    assert _headers(page)[2:6] == ["X (px)", "Y (px)", "W (px)", "H (px)"] and _row(page) == ["110"] * 4
    assert page.min_size.label.text() == "Minimum defect area (px)" and page.min_size.area.value() == 40

    scale = ctx.set_scale(BOARD, 476, 10)
    page.load()  # as on a board model change
    assert page.scale_text.isVisible() and page.scale_text.text() == "Scale 47.60 px/mm"
    assert not page.scale_badge.isVisible()
    assert page.held_badge.isVisible() and page.held_badge.text() == HELD and page.held_badge.wordWrap()  # until saved
    held = f"Revision {ctx.recipe(BOARD)[0]} of board model {BOARD} holds 2 of its 2 size(s) in px of its images"
    assert page.held_badge.toolTip().startswith(held) and "Press Save Recipe" in page.held_badge.toolTip()
    assert _headers(page)[2:6] == ["X (mm)", "Y (mm)", "W (mm)", "H (mm)"] and _row(page) == ["2.31"] * 4
    size = page.min_size
    assert size.label.text() == "Minimum defect size (mm)" and not size.mm.isHidden() and size.area.isHidden()
    assert size.mm.value() == 0.15 and size.px.text() == "= 7.1 px"  # 40 px of area: a round defect 7.1 px wide

    assert (page._collect().min_defect_mm, page._collect().rois[0].mm) == (None, None)  # in px until saved
    page.save()  # untouched: the same sizes, now in mm, and the same verdict
    saved = ctx.recipe(BOARD)[1]
    assert saved.min_defect_mm == pytest.approx(disc_width(40) / scale) and saved.rois[0].mm == [110 / scale] * 4
    assert (saved.in_px(scale).min_defect_area, saved.in_px(scale).rois[0].x) == (40, 110)
    assert page.held_badge.isHidden(), "saved in mm: no AOI-RCP-009"
    after = ctx.inspect(BOARD, ctx.load_image(ng_board))
    assert (after.verdict, after.checks, after.defects) == (before.verdict, before.checks, before.defects)
    page.min_size.mm.setValue(2.0)
    assert page.min_size.px.text() == "= 95.2 px"
    page.save()
    saved = ctx.recipe(BOARD)[1]
    assert (saved.min_defect_mm, saved.min_defect_area) == (2.0, disc_area(2 * scale))
    ctx.set_scale(BOARD, 952, 10)  # twice the scale, set outside the editor: R1, held in mm now, is twice as large
    page.load()  # the editor holds and draws R1 where the engine judges it, not where it was saved (S29 review)
    engine = [(r.x, r.y, r.w, r.h) for r in ctx.inspector(BOARD).recipe.rois]
    drawn = [i.rect() for i in page.view._overlay_items if isinstance(i, QGraphicsRectItem)]
    assert [(r.x, r.y, r.w, r.h) for r in page._collect().rois] == engine == [(220, 220, 220, 220)]
    assert [(d.x(), d.y(), d.width(), d.height()) for d in drawn] == engine

    win.navigate("Compare")
    compare = win.pages["Compare"]
    assert isinstance(compare, ComparePage)
    assert compare.min_size.label.text() == "Minimum defect size (mm)" and compare.min_size.mm.value() == 2.0
    qtbot.waitUntil(lambda: ctx.jobs.idle() and compare._bg is None, timeout=20000)
    win._on_board_model("")  # no board model: the Recipe Editor names no scale, and no AOI-RCP-005
    assert page.scale_text.isHidden() and page.scale_badge.isHidden() and page.held_badge.isHidden()


def test_req_rcp_006_compare_follows_a_scale_set_without_a_new_revision(
    qtbot: QtBot, trained_ctx: AppContext, ng_board: Path
) -> None:
    """Compare's what-if form shows the minimum defect size in mm once the board model has a scale, also when no
    revision was saved since it was filled, with the px the engine applies beside it; left untouched, it is no change
    (Save to Recipe stays off, S28d), and Save to Recipe of another threshold keeps the size the recipe holds, in px, so
    nothing changes unseen, and the Recipe Editor then shows AOI-RCP-009. A size typed in mm is the one Re-evaluate
    judges by, and Save to Recipe stores it in mm with its area at the scale."""
    ctx = trained_ctx
    win = _window(qtbot, ctx, "Engineer")
    compare = win.pages["Compare"]
    assert isinstance(compare, ComparePage)
    win.navigate("Compare")
    size, rev = compare.min_size, ctx.recipe(BOARD)[0]
    assert size.label.text() == "Minimum defect area (px)" and size.mm.isHidden() and size.area.value() == 40
    scale = ctx.set_scale(BOARD, 952, 10)  # 95.2 px/mm; no revision saved
    win.navigate("Recipe Editor")
    win.navigate("Compare")
    assert size.label.text() == "Minimum defect size (mm)" and not size.mm.isHidden() and size.area.isHidden()
    assert size.mm.value() == round(disc_width(40) / scale, 2) == 0.07 and size.px.text() == "= 7.1 px"  # not 6.7
    qtbot.waitUntil(lambda: ctx.jobs.idle() and compare._bg is None, timeout=20000)
    assert not compare.btn_save.isEnabled()
    compare.diff_thr.setValue(compare.diff_thr.value() + 1)
    save_to_recipe(compare)
    saved = ctx.recipe(BOARD)
    assert saved[0] == rev + 1 and (saved[1].min_defect_area, saved[1].min_defect_mm) == (40, None)
    win.navigate("Recipe Editor")  # the revision saved on Compare still holds its size in px
    editor = win.pages["Recipe Editor"]
    assert isinstance(editor, RecipeEditorPage)
    badge = editor.held_badge
    assert badge.isVisible() and badge.text() == HELD
    assert "1 of its 1 size(s) in px" in badge.toolTip()
    win.navigate("Compare")
    size.mm.setValue(3.0)  # typed in mm: Re-evaluate judges by it, and Save to Recipe stores it
    compare.set_test(str(ng_board))
    qtbot.waitUntil(lambda: ctx.jobs.idle() and compare._bg is None and compare.res is not None, timeout=60000)
    assert compare.res is not None
    regions = next(c.explain for c in compare.res.checks if c.name == "Difference regions")
    assert regions == f"blobs ≥ {disc_area(3.0 * scale)} px after noise clean-up"
    save_to_recipe(compare)
    saved = ctx.recipe(BOARD)
    assert saved[0] == rev + 2 and (saved[1].min_defect_area, saved[1].min_defect_mm) == (disc_area(3.0 * scale), 3.0)


def test_req_rcp_006_a_size_typed_in_mm_on_compare_changes_a_threshold(
    qtbot: QtBot, trained_ctx: AppContext, ng_board: Path
) -> None:
    """At a scale, a minimum defect size typed in mm on Compare changes a threshold as one typed in px does: the verdict
    Re-evaluate gave a stored result goes (S28c), and Save to Recipe is on at once, off again once the size shown is
    back (S28d). Before, only the px field, hidden at a scale, was wired to both."""
    ctx = trained_ctx
    ctx.set_scale(BOARD, 952, 10)
    _, compare, _ = _stored_on_compare(qtbot, ctx, ng_board, "Engineer")
    size, shown = compare.min_size, compare.min_size.mm.value()
    compare.re_evaluate()
    qtbot.waitUntil(compare.would_be.isVisible, timeout=10000)
    assert not compare.btn_save.isEnabled() and not size.mm.isHidden()
    size.mm.setValue(3.0)
    assert compare.would_be.isHidden() and compare.btn_save.isEnabled()
    size.mm.setValue(shown)
    assert not compare.btn_save.isEnabled(), "the size shown again is the recipe's own: nothing to save"
