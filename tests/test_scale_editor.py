"""REQ-RCP-006 (S29, parts 2 and 5): the sizes the Recipe Editor and Compare show in mm at the board model's scale, and
Calibrate Scale… on the Recipe Editor (sketch recipe-editor.md; Q21: without a scale a recipe saves with its sizes in
px, under AOI-RCP-005); REQ-INSP-014 (part 6): AOI-RCP-007 for a minimum defect size under 4 px."""

from __future__ import annotations

import json
import math
from pathlib import Path

import pytest
from PySide6.QtCore import QPoint, QPointF, QRectF, Qt
from PySide6.QtWidgets import (
    QApplication,
    QGraphicsEllipseItem,
    QGraphicsItem,
    QGraphicsLineItem,
    QGraphicsRectItem,
    QMessageBox,
    QTabWidget,
)
from pytestqt.qtbot import QtBot

from aoi.core.recipe import ROI, Recipe, disc_area, disc_width
from aoi.core.services import AppContext
from aoi.errors import AoiError
from aoi.ui import theme
from aoi.ui.pages.compare import ComparePage
from aoi.ui.pages.recipe_editor import RecipeEditorPage
from aoi.ui.widgets.image_view import ImageView, to_qpixmap
from aoi.ui.widgets.scale import DefectSizeField
from tests.test_ai_threshold_override import MIN_WIDTH
from tests.test_compare_reevaluate import _stored_on_compare
from tests.test_compare_stored import save_to_recipe
from tests.test_req_done_in_v01 import BOARD, _button, _window

HELD = (  # AOI-RCP-009 under the scale: the code, the title and what to do, in view for touch and keys (S29 review)
    "AOI-RCP-009 Sizes are held in px: Press Save Recipe to store them in mm, so that they follow the scale; that"
    " alone changes no verdict at this scale."
)


def _headers(page: RecipeEditorPage) -> list[str]:
    return [page.roi_table.horizontalHeaderItem(i).text() for i in range(page.roi_table.columnCount())]


def _row(page: RecipeEditorPage) -> list[str]:
    return [page.roi_table.item(0, j).text() for j in range(2, 6)]


def _marks(page: RecipeEditorPage) -> tuple[int, int]:
    """The points picked on the image, rings the same size at every zoom, and the lines between them."""
    items = page.view.scene().items()
    rings = [i for i in items if isinstance(i, QGraphicsEllipseItem)]
    assert all(r.flags() & QGraphicsItem.GraphicsItemFlag.ItemIgnoresTransformations for r in rings)
    return len(rings), sum(isinstance(i, QGraphicsLineItem) for i in items)


def _closed(qtbot: QtBot, page: RecipeEditorPage) -> bool:  # and the view as before: it pans, a click picks nothing
    with qtbot.assertNotEmitted(page.view.pointPicked):  # as it would in pick mode, on the board (S29 review)
        qtbot.mouseClick(page.view.viewport(), Qt.MouseButton.LeftButton, pos=page.view.viewport().rect().center())
    pans = page.view.dragMode() == ImageView.DragMode.ScrollHandDrag  # NoDrag while the sheet picks points
    return page.sheet.isHidden() and page.draw_btn.isEnabled() and pans and _marks(page) == (0, 0)


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
    assert not page.scale_text.isVisible() and "Calibrate Scale…" in page.scale_badge.toolTip()
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
    assert size.mm.value() == 0.15 and size.px.text() == "= 7.1 px ✓"  # 40 px of area: a round defect 7.1 px wide

    assert (page._collect().min_defect_mm, page._collect().rois[0].mm) == (None, None)  # in px until saved
    page.save()  # untouched: the same sizes, now in mm, and the same verdict
    saved = ctx.recipe(BOARD)[1]
    assert saved.min_defect_mm == pytest.approx(disc_width(40) / scale) and saved.rois[0].mm == [110 / scale] * 4
    assert (saved.in_px(scale).min_defect_area, saved.in_px(scale).rois[0].x) == (40, 110)
    assert page.held_badge.isHidden(), "saved in mm: no AOI-RCP-009"
    after = ctx.inspect(BOARD, ctx.load_image(ng_board))
    assert (after.verdict, after.checks, after.defects) == (before.verdict, before.checks, before.defects)
    page.min_size.mm.setValue(2.0)
    assert page.min_size.px.text() == "= 95.2 px ✓"
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
    judges by, and Save to Recipe stores it in mm with its area at the scale; left untouched after a scale set again,
    it is no change either (S29 review)."""
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
    assert size.mm.value() == round(disc_width(40) / scale, 2) == 0.07 and size.px.text() == "= 7.1 px ✓"  # not 6.7
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
    ctx.set_scale(BOARD, 476, 10)  # set again: 3.0 mm spans 16016 px of area, where the revision holds 64063
    win.navigate("Recipe Editor")
    win.navigate("Compare")
    qtbot.waitUntil(lambda: ctx.jobs.idle() and compare._bg is None, timeout=20000)
    assert size.mm.value() == 3.0 and not compare.btn_save.isEnabled(), "the size in mm as the recipe holds it"


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


def test_req_rcp_006_a_scale_that_cannot_be_read_is_set_again(
    qtbot: QtBot, trained_ctx: AppContext, dialogs: list[tuple[str, str]]
) -> None:
    """A stored scale damaged past its CHECK, by hand: the window opens, Compare showing the sizes without a scale, the
    Recipe Editor says AOI-RCP-012 as it loads and shows the recipe without a scale, Save Recipe stores nothing, and a
    scale set again replaces it (S29 review)."""
    ctx = trained_ctx
    ctx.db.execute("PRAGMA ignore_check_constraints = ON")
    ctx.db.execute("UPDATE board_models SET px_per_mm = 'abc' WHERE name = ?", (BOARD,))
    win = _window(qtbot, ctx, "Engineer")
    page, compare, rev = win.pages["Recipe Editor"], win.pages["Compare"], ctx.recipe(BOARD)[0]
    assert isinstance(compare, ComparePage) and win.navigate("Compare") and compare.min_size.px_per_mm is None
    assert isinstance(page, RecipeEditorPage) and win.navigate("Recipe Editor") and page.px_per_mm is None
    assert {title for title, _ in dialogs} == {"AOI-RCP-012 Scale cannot be read"}
    with pytest.raises(AoiError) as unread:  # Save Recipe, which the window's excepthook says
        page.save()
    assert unread.value.code == "AOI-RCP-012" and ctx.recipe(BOARD)[0] == rev
    page.set_scale(476, 10)  # Set Scale on Calibrate Scale…'s sheet, which replaces it
    for name in ("", BOARD):  # the editor loads the board model again
        win._on_board_model(name)
    assert page.px_per_mm == 47.6 and page.min_size.label.text() == "Minimum defect size (mm)"
    assert win.navigate("Compare") and compare.min_size.px_per_mm == 47.6


def test_req_rcp_006_calibrate_scale_on_the_golden_board(
    qtbot: QtBot, trained_ctx: AppContext, ng_board: Path, dialogs: list[tuple[str, str]]
) -> None:
    """Calibrate Scale… opens an inline sheet, no dialog: two clicks on the Golden board give the length between them,
    the distance typed in mm the scale, and Set Scale stores it through AppContext.set_scale, audited with that length
    and distance; the page and Compare's form then show the scale and sizes in mm, no revision saved. Each point is a
    ring, with the line between the two, kept when an ROI is selected; a third click starts again. Draw ROI is grey
    while the sheet is open, Set Scale until both numbers are above 0. A click off the board picks nothing. Cancel, Set
    Scale, Esc, another board model, the Golden board replaced, another user or Try Recipe… closes the sheet with its
    points, and the view pans again, picking nothing; Set Scale on a Golden board replaced meanwhile sets nothing and
    says so (AOI-RCP-008). It opens on the Golden board, a Try's verdict gone. With the recipe in px, Set Scale says
    AOI-RCP-009. Without a board model or Golden board, Calibrate Scale… is grey. Closed from inside, the sheet gives
    the focus back to Calibrate Scale…, where one more Space opens it again and sets nothing, or to the image view while
    that is off."""
    ctx = trained_ctx
    win = _window(qtbot, ctx, "Engineer")
    page, compare = win.pages["Recipe Editor"], win.pages["Compare"]
    assert isinstance(page, RecipeEditorPage) and isinstance(compare, ComparePage)
    win.navigate("Compare")
    assert compare.min_size.label.text() == "Minimum defect area (px)"
    qtbot.waitUntil(lambda: ctx.jobs.idle() and compare._bg is None, timeout=20000)
    win.navigate("Recipe Editor")
    page.add_roi(QRectF(110, 110, 110, 110))  # an ROI to select while the sheet holds two points
    page.roi_table.clearSelection()
    calibrate = _button(page, "Calibrate Scale…")
    qtbot.mouseClick(calibrate, Qt.MouseButton.LeftButton)
    assert page.sheet.isVisible() and not page.draw_btn.isEnabled()
    win.activateWindow()  # the focus moves only in the active window
    qtbot.waitUntil(win.isActiveWindow, timeout=5000)
    cancel = _button(page.sheet, "Cancel")
    cancel.setFocus(Qt.FocusReason.TabFocusReason)
    qtbot.keyClick(cancel, Qt.Key.Key_Space)  # Cancel by key: the focus back on Calibrate Scale…, not passed on
    assert page.sheet.isHidden() and win.focusWidget() is calibrate
    qtbot.keyClick(win.focusWidget(), Qt.Key.Key_Space)  # one more Space opens the sheet again, setting nothing
    assert page.sheet.isVisible() and ctx.scale(BOARD) is None
    qtbot.mouseClick(cancel, Qt.MouseButton.LeftButton)
    assert _closed(qtbot, page) and ctx.scale(BOARD) is None
    qtbot.mouseClick(calibrate, Qt.MouseButton.LeftButton)
    page.sheet.distance.setFocus(Qt.FocusReason.TabFocusReason)
    qtbot.keyClick(page.sheet.distance, Qt.Key.Key_Escape)  # Esc in the sheet, as Cancel (S29 review)
    assert page.sheet.isHidden() and win.focusWidget() is calibrate

    qtbot.mouseClick(calibrate, Qt.MouseButton.LeftButton)
    set_scale = _button(page.sheet, "Set Scale")
    view, middle = page.view, page.view.viewport().rect().center()
    clicks = [middle - QPoint(150, 0), middle + QPoint(150, 0)]  # on the Golden board, as a user clicks
    for at in clicks:
        qtbot.mouseClick(view.viewport(), Qt.MouseButton.LeftButton, pos=at)
    a, b = page.sheet.points
    assert [a, b] == [view.mapToScene(at) for at in clicks] and 0 < a.x() < b.x() < 640
    page.roi_table.selectRow(0)  # the ROI selected and drawn again: the points picked stay in view (S29 review)
    assert _marks(page) == (2, 1), "each point a ring at every zoom, with the line between them"
    length = page.sheet.length.value()
    assert length == pytest.approx(math.hypot(b.x() - a.x(), b.y() - a.y()), abs=0.05) and not set_scale.isEnabled()
    page.sheet.distance.setValue(10.0)
    assert page.sheet.result.text() == f"= {length / 10:.2f} px/mm" and set_scale.isEnabled()
    qtbot.mouseClick(set_scale, Qt.MouseButton.LeftButton)
    assert ctx.scale(BOARD) == pytest.approx(length / 10) and win.focusWidget() is calibrate
    entry = ctx.audit_entries(action="board_model.scale")[0]
    assert (entry["after"]["length_px"], entry["after"]["distance_mm"]) == (length, 10.0)
    assert _closed(qtbot, page) and not page.scale_badge.isVisible()
    assert page.held_badge.isVisible() and page.held_badge.text() == HELD  # the recipe still holds its sizes in px
    assert win.statusBar().currentMessage().endswith(f" px/mm. {HELD}")
    assert page.scale_text.text() == f"Scale {length / 10:.2f} px/mm" and _headers(page)[2] == "X (mm)"
    assert page.min_size.label.text() == "Minimum defect size (mm)"
    win.navigate("Compare")  # the scale changed, no revision saved: its form reads in mm too
    assert compare.min_size.label.text() == "Minimum defect size (mm)" and not compare.min_size.mm.isHidden()
    qtbot.waitUntil(lambda: ctx.jobs.idle() and compare._bg is None, timeout=20000)

    win.navigate("Recipe Editor")
    qtbot.mouseClick(calibrate, Qt.MouseButton.LeftButton)
    for at in [*clicks, middle]:  # a third click starts again
        qtbot.mouseClick(view.viewport(), Qt.MouseButton.LeftButton, pos=at)
    assert (len(page.sheet.points), _marks(page), page.sheet.length.value()) == (1, (1, 0), 0)
    ctx.db.set_reference("COPY", str(ctx.reference_image(BOARD)))  # another board model with a Golden board
    win._on_board_model("COPY")  # the point was picked on TINY's: it must not set COPY's scale
    assert _closed(qtbot, page) and calibrate.isEnabled()
    win._on_board_model(BOARD)
    golden = Path(str(ctx.reference_image(BOARD)))
    kept = golden.read_bytes()
    for change in ("esc", "golden", "set", "user"):
        qtbot.mouseClick(calibrate, Qt.MouseButton.LeftButton)
        qtbot.mouseClick(view.viewport(), Qt.MouseButton.LeftButton, pos=middle)
        if change == "esc":
            qtbot.keyClick(view, Qt.Key.Key_Escape)  # on the Golden board it picks points on, as Cancel (S29 review)
        elif change == "golden":
            golden.write_bytes(kept + b"\0")  # replaced: the point was picked on the Golden board before
            win.navigate("Home")
            win.navigate("Recipe Editor")
        elif change == "set":  # replaced with the page shown, as when a training run ends (S29 review)
            golden.write_bytes(kept + b"\0\0")
            page.set_scale(476, 10)  # Set Scale on the sheet
        else:
            win.set_user("admin")  # the page stays; the point picked is the Engineer's
        assert _closed(qtbot, page), change
    assert ctx.scale(BOARD) == pytest.approx(length / 10) and [t for t, _ in dialogs] == ["AOI-RCP-008 Scale not set"]
    assert "its Golden board was replaced after the points were picked on it." in dialogs[0][1]
    golden.write_bytes(kept)
    win.set_user("engineer")
    qtbot.mouseClick(calibrate, Qt.MouseButton.LeftButton)
    view.scale(0.5, 0.5)  # zoomed out, with room around the board: a click there picks no point
    qtbot.mouseClick(view.viewport(), Qt.MouseButton.LeftButton, pos=view.mapFromScene(QPointF(-20, -20)))
    assert page.sheet.points == [] and view.viewport().rect().contains(view.mapFromScene(QPointF(-20, -20)))
    page.run_test(str(ng_board))  # Try Recipe… with the sheet open: the sheet closes, as the Try shows another board
    assert _closed(qtbot, page)
    qtbot.waitUntil(lambda: ctx.jobs.idle() and page.test_verdict.text() != "", timeout=60000)
    qtbot.mouseClick(calibrate, Qt.MouseButton.LeftButton)  # on the Golden board again, the Try's verdict gone
    assert page.ref is not None and view._pix is not None and page.test_verdict.text() == ""
    assert view._pix.pixmap().toImage() == to_qpixmap(page.ref).toImage()
    win._on_board_model("")  # the sheet closes with its board model
    assert win.focusWidget() is page.view and _closed(qtbot, page) and not calibrate.isEnabled()
    ctx.ensure_board_model("ZZZ")
    win._on_board_model("ZZZ")
    assert not calibrate.isEnabled(), "no Golden board to click on"


def test_req_rcp_006_setting_the_scale_again_moves_only_sizes_in_mm(
    qtbot: QtBot, trained_ctx: AppContext, ng_board: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Set Scale on a board model that has a scale: what the recipe holds in px stays in px and what it holds in mm
    moves to its px at the new scale, as the engine applies it, so the editor and Compare show the sizes the engine
    uses. Left unedited, the editor has no unsaved change, so a revision saved meanwhile on Compare loads without a
    question, and Save Recipe untouched then judges the board as before. Set Scale to a scale at which the minimum
    defect size, now held in mm, spans under 4 px says AOI-RCP-007 in the status bar (part 6)."""
    ctx = trained_ctx
    _, recipe = ctx.recipe(BOARD)
    recipe.rois = [ROI("R1", "Presence", 110, 110, 110, 110), ROI("R2", "Presence", mm=[4.0, 3.0, 1.0, 1.0])]
    ctx.save_recipe(recipe)
    ctx.set_scale(BOARD, 476, 10)  # 47.6 px/mm: the minimum defect size and R1 stay in px
    asked: list[object] = []
    monkeypatch.setattr(QMessageBox, "question", lambda *a: asked.append(a) or QMessageBox.StandardButton.No)
    monkeypatch.setattr(QMessageBox, "information", lambda *a: QMessageBox.StandardButton.Ok)
    win = _window(qtbot, ctx, "Engineer")
    page, compare = win.pages["Recipe Editor"], win.pages["Compare"]
    assert isinstance(page, RecipeEditorPage) and isinstance(compare, ComparePage)
    win.navigate("Recipe Editor")
    page.diff.setValue(page.diff.value() + 1)  # an edit, undone after Set Scale: no unsaved change then
    page.set_scale(952, 10)  # Set Scale on the sheet: 95.2 px/mm
    page.diff.setValue(page.diff.value() - 1)
    shown, engine = page._collect(), ctx.inspector(BOARD).recipe
    boxes = [(110, 110, 110, 110), (381, 286, 95, 95)]  # R2: its mm × 95.2, to the nearest px
    assert [(r.x, r.y, r.w, r.h) for r in shown.rois] == [(r.x, r.y, r.w, r.h) for r in engine.rois] == boxes
    assert shown.min_defect_area == engine.min_defect_area == 40 and page.min_size.px.text() == "= 7.1 px ✓"
    assert _row(page) == ["1.16"] * 4 and shown.to_dict() == page._loaded  # the edit undone
    win.navigate("Compare")
    assert (compare.min_size.mm.value(), compare.min_size.px.text()) == (page.min_size.mm.value(), "= 7.1 px ✓")
    qtbot.waitUntil(lambda: ctx.jobs.idle() and compare._bg is None, timeout=20000)
    compare.diff_thr.setValue(compare.diff_thr.value() + 1)  # Save to Recipe stores a threshold changed (S28d)
    saved_on_compare = save_to_recipe(compare)  # a revision saved meanwhile, its sizes untouched
    before = ctx.inspect(BOARD, ctx.load_image(ng_board))
    win.navigate("Recipe Editor")
    assert not asked and page.rev == saved_on_compare == ctx.recipe(BOARD)[0]
    page.save()  # untouched: now in mm, the same sizes and verdict
    assert ctx.recipe(BOARD)[1].rois[1].mm == [4.0, 3.0, 1.0, 1.0], "R2's mm as held, not from its px (review)"
    saved = ctx.inspector(BOARD).recipe
    assert (saved.min_defect_area, [(r.x, r.y, r.w, r.h) for r in saved.rois]) == (40, boxes)
    after = ctx.inspect(BOARD, ctx.load_image(ng_board))
    assert (after.verdict, after.checks, after.defects) == (before.verdict, before.checks, before.defects)
    page.set_scale(476, 20)  # 23.8 px/mm: the size held in mm since Save Recipe, 0.07 mm, spans 1.8 px (S29 review)
    small = "23.80 px/mm. AOI-RCP-007 Minimum defect size under 4 px: Raise it to 0.17 mm or more"
    assert small in win.statusBar().currentMessage() and not page.min_size.notice.isHidden()


def test_req_insp_014_under_4px_warns(qtbot: QtBot, trained_ctx: AppContext, monkeypatch: pytest.MonkeyPatch) -> None:
    """REQ-INSP-014 (S29, part 6): a minimum defect size that spans under 4 px at the board model's scale (without one,
    an area under the 13 px of a round defect 4 px wide) gets AOI-RCP-007, which names the size, the px it spans and
    the least size to give: in amber while it is so, under the field with what to do on the Recipe Editor and in one
    line in the "why" box on Compare, from the size the engine applies, and in full in the audit entry of a recipe saved
    so, which saves all the same (sketch: saving is allowed). At 4 px or more, as with the default recipe, there is
    none, and the px carry a ✓."""
    assert Recipe(board_model=BOARD).size_notice(None) is None
    assert Recipe(board_model=BOARD, min_defect_area=13).size_notice(None) is None
    small = Recipe(board_model=BOARD, min_defect_area=12).size_notice(None)
    assert small is not None and small.code == "AOI-RCP-007"
    assert small.what.startswith("The minimum defect size, 12 px of area, spans 3.9 px in the board images: under 4 px")
    assert small.action.startswith("Raise it to 13 px of area or more")
    assert Recipe(board_model=BOARD, min_defect_mm=4 / 47.6).size_notice(47.6) is None
    tiny = Recipe(board_model=BOARD, min_defect_mm=0.05).size_notice(47.6)
    assert tiny is not None and "0.05 mm, spans 2.4 px" in tiny.what and "Raise it to 0.09 mm" in tiny.action
    assert Recipe(board_model=BOARD, min_defect_area=12).size_notice(47.6) is not None  # a size in px, shown in mm
    field, told = DefectSizeField(compact=True), []
    field.noticeChanged.connect(lambda shown: told.append(field.notice.text() if shown else ""))
    field.show_recipe(Recipe(board_model=BOARD, min_defect_area=12), None)  # a page measures the line it is told of
    assert told == ["AOI-RCP-007 Minimum defect size under 4 px: raise it to 13 px of area or more."]

    ctx = trained_ctx
    ctx.set_scale(BOARD, 476, 10)
    _, edge = ctx.recipe(BOARD)
    edge.min_defect_mm = 4.02 / 47.6  # shown as 0.08 mm, 3.8 px: the notice follows the 4.02 px applied
    ctx.save_recipe(edge)
    assert ctx.audit_entries(action="recipe.save")[0]["reason"] is None
    monkeypatch.setattr(QMessageBox, "information", lambda *a: QMessageBox.StandardButton.Ok)
    win = _window(qtbot, ctx, "Engineer")
    compare = win.pages["Compare"]
    assert isinstance(compare, ComparePage)
    compact = "AOI-RCP-007 Minimum defect size under 4 px: raise it to 0.09 mm or more."  # one line on Compare
    for name, text in (("Compare", compact), ("Recipe Editor", f"AOI-RCP-007 {tiny.title}: {tiny.action}")):
        win.navigate(name)
        field = win.pages[name].min_size
        assert isinstance(field, DefectSizeField) and field.notice.isHidden(), name
        assert (field.mm.value(), field.px.text()) == (0.08, "= 4.0 px ✓"), name
        field.mm.setValue(0.05)
        assert field.notice.text() == text and field.px.text() == "= 2.4 px", name
        in_why = text in compare.why.toPlainText()  # on Compare, in the "why" box, the field's own label hidden
        assert field.notice.isHidden() == in_why == (name == "Compare"), name
        field.mm.setValue(0.1)
        assert field.notice.isHidden() and field.px.text() == "= 4.8 px ✓", name
        assert "AOI-RCP-007" not in compare.why.toPlainText(), name
    editor = win.pages["Recipe Editor"]
    assert isinstance(editor, RecipeEditorPage)
    editor.min_size.mm.setValue(0.05)
    editor.save()
    entry = ctx.audit_entries(action="recipe.save")[0]
    assert entry["after"]["min_defect_mm"] == 0.05 and entry["reason"] == str(tiny)
    assert ctx.recipe(BOARD)[1].min_defect_mm == 0.05 and not editor.min_size.notice.isHidden()
    ctx.save_recipe(ctx.recipe(BOARD)[1], reason="Kept for a trial.")  # a reason given comes first, the notice after
    assert ctx.audit_entries(action="recipe.save")[0]["reason"] == f"Kept for a trial. {tiny}"
    qtbot.waitUntil(lambda: ctx.jobs.idle() and compare._bg is None, timeout=20000)


@pytest.mark.parametrize("state", ["calibrated", "unreadable", "none-trained"])
def test_req_insp_014_the_notice_squeezes_no_row_at_1600_by_900(
    qtbot: QtBot, trained_ctx: AppContext, state: str
) -> None:
    """AOI-RCP-007 on the Recipe Editor and Compare at 1600 x 900 and 1920 x 1080, in each state of the AI score
    threshold's note: no row of either page's thresholds is squeezed for it, the window is no wider, and Compare's "why"
    box keeps theme.WHY_MIN_H (S29 review: on Windows the panel was too short for its rows, which
    test_req_trn_015_tick_and_note_never_widen_the_window checks without the notice)."""
    ctx = trained_ctx
    model = ctx.active_model(BOARD)
    assert model is not None
    if state == "unreadable":
        metrics = {**json.loads(model["metrics"]), "image_threshold": "damaged"}
        ctx.db.execute("UPDATE models SET metrics=? WHERE uuid=?", (json.dumps(metrics), model["uuid"]))
    elif state == "none-trained":
        ctx.db.execute("DELETE FROM models WHERE board_model=?", (BOARD,))
    _, small = ctx.recipe(BOARD)
    small.min_defect_area = 12  # under 4 px: AOI-RCP-007 on both pages
    ctx.save_recipe(small)
    win = _window(qtbot, ctx, "Engineer")
    editor, compare = win.pages["Recipe Editor"], win.pages["Compare"]
    assert isinstance(editor, RecipeEditorPage) and isinstance(compare, ComparePage)
    tabs = editor.findChild(QTabWidget)
    assert tabs is not None
    tabs.setCurrentWidget(editor.ai_thr.parentWidget())  # the Thresholds tab, where the field is
    for size in ((1600, 900), (1920, 1080)):
        win.resize(*size)
        for page in (editor, compare):
            win.navigate(page.title)
            QApplication.processEvents()
            rows = page.ai_thr.parentWidget()
            assert rows.height() >= rows.heightForWidth(rows.width()), (page.title, size, rows.height(), "squeezed")
            said = page.min_size.notice.isVisible() if page is editor else "AOI-RCP-007" in compare.why.toPlainText()
            assert said and win.width() <= max(size[0], MIN_WIDTH), (page.title, size)
        assert compare.why.height() >= theme.WHY_MIN_H, size
