"""REQ-RCP-001 (S49): ROIs moved and resized on the Recipe Editor's Golden board by mouse, finger and keys, with zoom
and pan (sketch docs/sketches/recipe-editor.md): the selected ROI yellow with a handle at each corner and side, saved
ROIs green, a changed ROI yellow and dashed until saved, and every ROI in its place after save and reload."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from PySide6.QtCore import QPoint, QPointF, QRectF, Qt
from PySide6.QtGui import QColor
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QGraphicsItem, QGraphicsRectItem, QMessageBox
from pytestqt.qtbot import QtBot

from aoi.config import Settings
from aoi.core.recipe import ROI
from aoi.core.services import AppContext
from aoi.ui import theme
from aoi.ui.pages.recipe_editor import RecipeEditorPage
from tests.conftest import engineer
from tests.test_label_editor import LEFT, NONE, SHIFT, _at, _drag, _finger, _shift, _wheel
from tests.test_req_done_in_v01 import BOARD, _button, _window

if TYPE_CHECKING:
    from aoi.ui.widgets.box_editor import RoiEditor

YELLOW, GREEN = QColor(theme.ROI_SELECTED).name(), QColor(theme.ROI_COLOR).name()
FIXED = QGraphicsItem.GraphicsItemFlag.ItemIgnoresTransformations  # a handle: the same size at every zoom


def _page(qtbot: QtBot, ctx: AppContext) -> RecipeEditorPage:
    """The Recipe Editor in the active window, the one keys go to."""
    win = _window(qtbot, ctx)
    win.navigate("Recipe Editor")
    qtbot.waitUntil(win.isActiveWindow, timeout=5000)
    page = win.pages["Recipe Editor"]
    assert isinstance(page, RecipeEditorPage)
    return page


def _pens(view: RoiEditor) -> dict[tuple[int, ...], tuple[str, bool]]:
    """Each box drawn on the board, by its place and size: its colour, and whether its line is dashed."""
    out = {}
    for item in view.scene().items():
        # A box, not a label's backing. Not `parentItem() is None`: in PySide6 a parentItem() that returns None hands
        # the item to Python while its scene still holds it, so both free it, and a later garbage collection crashes.
        if isinstance(item, QGraphicsRectItem) and item.topLevelItem() is item and not item.flags() & FIXED:
            r, pen = item.rect(), item.pen()
            box = tuple(round(v) for v in (r.x(), r.y(), r.width(), r.height()))
            out[box] = (pen.color().name(), pen.style() == Qt.PenStyle.DashLine)
    return out


def _handles(view: RoiEditor) -> int:
    return sum(
        isinstance(i, QGraphicsRectItem) and i.topLevelItem() is i and bool(i.flags() & FIXED)
        for i in view.scene().items()
    )


def _box(page: RecipeEditorPage, i: int) -> tuple[int, int, int, int]:
    """ROI `i` as the recipe being edited holds it; the ROI table shows the same, in px without a scale."""
    x = page.edited_recipe.rois[i]
    assert [page.roi_table.item(i, j).text() for j in range(2, 6)] == [str(v) for v in (x.x, x.y, x.w, x.h)]
    return x.x, x.y, x.w, x.h


def test_req_rcp_001_move_resize_survives_reload(
    qtbot: QtBot, trained_ctx: AppContext, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A click on an ROI selects it: yellow, with 8 handles. A drag on its inside, by mouse or finger, moves it by the
    drag and keeps its size, never past the board's edge; a drag on a side's middle moves that side alone and one on a
    corner its two sides, the opposite sides staying; Shift with an arrow key moves it 10 px. An ROI changed and not
    saved is yellow and dashed, a saved one green; after Save Recipe every ROI is green, and each is in its place in a
    new window on a new context over the same workspace."""
    monkeypatch.setattr(QMessageBox, "information", staticmethod(lambda *_: QMessageBox.StandardButton.Ok))
    _, recipe = trained_ctx.recipe(BOARD)
    recipe.rois = [ROI("R1", "Presence", 100, 100, 80, 60), ROI("R2", "Polarity", 300, 200, 60, 60)]
    trained_ctx.save_recipe(recipe)
    page = _page(qtbot, trained_ctx)
    view = page.view
    assert page.ref is not None
    height, width = page.ref.shape[:2]
    assert _pens(view) == {(100, 100, 80, 60): (GREEN, False), (300, 200, 60, 60): (GREEN, False)}
    assert _handles(view) == 0
    QTest.mouseClick(view.viewport(), LEFT, NONE, _at(view, 140, 130))
    assert page._sel_index() == 0 and page.r_name.text() == "R1"
    assert _pens(view)[(100, 100, 80, 60)] == (YELLOW, False) and _handles(view) == 8

    a = _at(view, 140, 130)
    b = a + QPoint(30, 20)
    d = _shift(view, a, b)
    _drag(view, a, b)
    x, y = round(100 + d.x()), round(100 + d.y())
    assert _box(page, 0) == (x, y, 80, 60), "moved by the drag, the same size"
    a = _at(view, x + 80, y + 30)  # the middle of the right side
    b = a + QPoint(25, 40)
    d = _shift(view, a, b)
    _drag(view, a, b)
    w = round(x + 80 + d.x()) - x
    assert _box(page, 0) == (x, y, w, 60), "the right side alone"
    a = _at(view, x, y)  # the top left corner
    b = a + QPoint(-15, -10)
    d = _shift(view, a, b)
    _drag(view, a, b)
    x0, y0 = round(x + d.x()), round(y + d.y())
    assert _box(page, 0) == (x0, y0, x + w - x0, y + 60 - y0), "the top and left sides, the others staying"
    x, y, w, h = _box(page, 0)
    a = _at(view, x + w / 2, y + h / 2)
    b = a + QPoint(-12, 9)
    d = _shift(view, a, b)
    _finger(view, a, b)
    x, y = round(x + d.x()), round(y + d.y())
    assert _box(page, 0) == (x, y, w, h), "a finger moves it as the mouse does"
    QTest.keyClick(view, Qt.Key.Key_Right, SHIFT)
    qtbot.waitUntil(lambda: _box(page, 0) == (x + 10, y, w, h), timeout=5000)  # stored half a second after the key
    _drag(view, _at(view, x + 10 + w / 2, y + h / 2), _at(view, width + 500, -500))  # far past the top right corner
    assert _box(page, 0) == (width - w, 0, w, h), "it stops at the board's edge"

    QTest.mouseClick(view.viewport(), LEFT, NONE, _at(view, 330, 230))
    assert page._sel_index() == 1
    assert _pens(view) == {(width - w, 0, w, h): (YELLOW, True), (300, 200, 60, 60): (YELLOW, False)}
    assert page.edited_recipe.rois[0].mm is None
    qtbot.mouseClick(_button(page, "Save Recipe"), LEFT)
    assert _pens(view) == {(width - w, 0, w, h): (GREEN, False), (300, 200, 60, 60): (GREEN, False)}

    page.window().close()  # a restart: the app closes first, one copy per workspace (#204)
    reopened = engineer(AppContext(Settings(workspace=trained_ctx.settings.workspace, device="cpu")))
    assert [(r.name, r.x, r.y, r.w, r.h) for r in reopened.recipe(BOARD)[1].rois] == [
        ("R1", width - w, 0, w, h),
        ("R2", 300, 200, 60, 60),
    ]
    page = _page(qtbot, reopened)
    assert _box(page, 0) == (width - w, 0, w, h) and _box(page, 1) == (300, 200, 60, 60)


def test_req_rcp_001_a_small_roi_moves_from_inside_and_resizes_from_handles_outside(
    qtbot: QtBot, trained_ctx: AppContext
) -> None:
    """An ROI under three handles across on screen has its handles outside it, so a press anywhere inside it moves it;
    a resize never leaves it under 4 px a side."""
    page = _page(qtbot, trained_ctx)
    view = page.view
    page.view.roiDrawn.emit(QRectF(200, 200, 20, 20))  # what a drag in Draw ROI mode gives
    assert view.mapFromScene(QRectF(200, 200, 20, 20)).boundingRect().width() < 3 * theme.HANDLE_PX
    a = _at(view, 202, 202)  # inside, by its top left corner
    b = a + QPoint(20, 20)
    d = _shift(view, a, b)
    _drag(view, a, b)
    x, y = round(200 + d.x()), round(200 + d.y())
    assert _box(page, 0) == (x, y, 20, 20)
    right = view.mapFromScene(QPointF(x + 20, y + 10)) + QPoint(theme.HANDLE_PX // 2, 0)  # the handle outside the side
    _drag(view, right, right - QPoint(400, 0))
    assert _box(page, 0) == (x, y, 4, 20), "never under 4 px"


def test_req_rcp_001_zoom_pan_and_fit_by_wheel_middle_drag_space_and_home(
    qtbot: QtBot, trained_ctx: AppContext
) -> None:
    """The wheel zooms, a middle-button drag pans in any mode, a drag with Space held pans in Draw ROI mode and draws
    nothing, and Home fits the board to the pane again (sketch: wheel, Space+drag or middle-drag, Home)."""
    page = _page(qtbot, trained_ctx)
    view = page.view
    fitted = view.transform().m11()
    _wheel(view.viewport(), -2)
    assert view.transform().m11() == pytest.approx(fitted * 1.25**2)
    port, h, v = view.viewport(), view.horizontalScrollBar(), view.verticalScrollBar()
    assert h.maximum() > 0 and v.maximum() > 0
    h.setValue(h.maximum() // 2)
    v.setValue(v.maximum() // 2)
    start = (h.value(), v.value())
    a = port.rect().center()
    QTest.mousePress(port, Qt.MouseButton.MiddleButton, NONE, a)
    QTest.mouseMove(port, a + QPoint(-30, -20))
    QTest.mouseRelease(port, Qt.MouseButton.MiddleButton, NONE, a + QPoint(-30, -20))
    assert (h.value(), v.value()) == (start[0] + 30, start[1] + 20)
    qtbot.mouseClick(_button(page, "Draw ROI"), LEFT)
    start = (h.value(), v.value())
    view.setFocus()
    with qtbot.assertNotEmitted(view.roiDrawn):
        QTest.keyPress(view, Qt.Key.Key_Space)
        _drag(view, a, a + QPoint(20, 10))
        QTest.keyRelease(view, Qt.Key.Key_Space)
    assert (h.value(), v.value()) == (start[0] - 20, start[1] - 10)
    with qtbot.waitSignal(view.roiDrawn):
        _drag(view, a, a + QPoint(20, 10))  # Space let go: the drag draws again
    zoomed = view.transform().m11()
    QTest.keyClick(view, Qt.Key.Key_Home)
    home = view.transform().m11()
    view.fit()  # as a double-click does
    assert home == pytest.approx(view.transform().m11()) and home != pytest.approx(zoomed)


def test_req_rcp_001_an_roi_moved_under_a_scale_is_saved_where_it_was_moved(
    qtbot: QtBot, trained_ctx: AppContext, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Under a scale Save Recipe stores each ROI's box in mm (REQ-RCP-006): an ROI moved on the board is stored, and
    read back, where it was moved to, not where its box in mm was before."""
    monkeypatch.setattr(QMessageBox, "information", staticmethod(lambda *_: QMessageBox.StandardButton.Ok))
    scale = trained_ctx.set_scale(BOARD, 476, 10)
    _, recipe = trained_ctx.recipe(BOARD)
    recipe.rois = [ROI("R1", "Presence", 100, 100, 80, 60)]
    trained_ctx.save_recipe(recipe.in_mm(scale))
    page = _page(qtbot, trained_ctx)
    a = _at(page.view, 140, 130)
    d = _shift(page.view, a, a + QPoint(40, 0))
    _drag(page.view, a, a + QPoint(40, 0))
    qtbot.mouseClick(_button(page, "Save Recipe"), LEFT)
    roi = trained_ctx.recipe(BOARD)[1].in_px(scale).rois[0]
    assert roi.mm is not None and (roi.x, roi.y, roi.w, roi.h) == (round(100 + d.x()), 100, 80, 60)


def test_req_rcp_001_calibrate_scale_picks_a_point_on_an_roi_and_moves_none(
    qtbot: QtBot, trained_ctx: AppContext
) -> None:
    """While Calibrate Scale… picks points, a click on an ROI picks a point there and a drag on it moves nothing."""
    page = _page(qtbot, trained_ctx)
    view = page.view
    view.roiDrawn.emit(QRectF(100, 100, 80, 60))
    qtbot.mouseClick(_button(page, "Calibrate Scale…"), LEFT)
    with qtbot.waitSignal(view.pointPicked):
        QTest.mouseClick(view.viewport(), LEFT, NONE, _at(view, 140, 130))
    _drag(view, _at(view, 120, 120), _at(view, 160, 150))
    assert _box(page, 0) == (100, 100, 80, 60) and len(page.sheet.points) == 2
