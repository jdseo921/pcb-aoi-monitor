"""REQ-SET-004 (#104, A7 of the 2026-10 business-readiness brief): a picture keeps what it shows as its pane changes
size, as a window is resized or maximised on a projector. The whole board, once fitted, is fitted again; a defect box
once centred on (Inspection's selected row, Training's Zoom to Box) is centred on again; and a zoom or a pan of the
user's stays as it is, also as the scroll bars it brings come and go (review of A7: a refit there undid Zoom In)."""

from __future__ import annotations

import numpy as np
import pytest
from PySide6.QtCore import QEvent, QPoint, QPointF, QRect, Qt
from PySide6.QtGui import QMouseEvent, QWheelEvent
from PySide6.QtWidgets import QApplication
from pytestqt.qtbot import QtBot

from aoi.ui.widgets.image_view import ImageView

BOARD = (1200, 1600)  # rows, columns


def _view(qtbot: QtBot) -> ImageView:
    view = ImageView(placeholder="")
    qtbot.addWidget(view)
    view.resize(600, 400)
    view.show()
    qtbot.waitExposed(view)
    view.set_image(np.zeros((*BOARD, 3), np.uint8))
    QApplication.processEvents()
    return view


def _whole(view: ImageView) -> QRect:
    """Where the whole board is in the viewport's pixels."""
    return view.mapFromScene(view.sceneRect()).boundingRect()


def _resized(qtbot: QtBot, view: ImageView, width: int, height: int) -> None:
    view.resize(width, height)
    qtbot.waitUntil(lambda: view.width() == width and view.height() == height)
    for _ in range(3):
        QApplication.processEvents()  # scroll bars come or go at the next event


def test_req_set_004_a_fitted_board_is_fitted_again_as_its_pane_grows_or_shrinks(qtbot: QtBot) -> None:
    view = _view(qtbot)
    small = view.transform().m11()
    assert view.fitted and view.viewport().rect().contains(_whole(view))
    _resized(qtbot, view, 1200, 800)
    assert view.transform().m11() > small * 1.9, "the board kept the scale of the smaller pane"
    assert view.viewport().rect().contains(_whole(view))
    _resized(qtbot, view, 450, 300)
    assert view.transform().m11() < small and view.viewport().rect().contains(_whole(view)), "the board was cut"


@pytest.mark.parametrize("x, y", [(700, 500), (1440, 1060)], ids=["inside", "at the corner"])
def test_req_set_004_a_box_centred_on_stays_in_view_as_its_pane_changes_size(qtbot: QtBot, x: int, y: int) -> None:
    """In the middle of the view where the board goes on round it; at the board's corner, as near the middle as the
    board's edge lets it be, and whole."""
    view = _view(qtbot)
    view.add_box(x, y, 120, 100)
    view.center_on_box(x, y, 120, 100)
    QApplication.processEvents()
    (box,) = view.box_rects()
    assert view.viewport().rect().contains(box) and box.width() > 100, "the box was not zoomed to"
    for size in ((1100, 700), (420, 600), (800, 300)):
        _resized(qtbot, view, *size)
        (box,) = view.box_rects()
        port = view.viewport().rect()
        assert port.contains(box), (size, box, port)
        if x < 1000:
            assert abs(box.center().x() - port.center().x()) <= 4 >= abs(box.center().y() - port.center().y()), size


def test_req_set_004_the_users_zoom_stays_through_its_scroll_bars_and_a_resize(qtbot: QtBot) -> None:
    view = _view(qtbot)
    fit = view.transform().m11()
    middle = QPointF(view.viewport().rect().center())
    wheel = QWheelEvent(
        middle,
        view.viewport().mapToGlobal(middle),
        QPoint(0, 0),
        QPoint(0, 120),
        Qt.MouseButton.NoButton,
        Qt.KeyboardModifier.NoModifier,
        Qt.ScrollPhase.NoScrollPhase,
        False,
    )
    QApplication.sendEvent(view.viewport(), wheel)
    for _ in range(3):
        QApplication.processEvents()  # the zoom's scroll bars, which resize the viewport
    assert view.horizontalScrollBar().isVisible(), "the zoom brought no scroll bars, so this checks nothing"
    assert view.transform().m11() == fit * 1.25 and not view.fitted, "the scroll bars fitted the board again"
    _resized(qtbot, view, 900, 500)
    assert view.transform().m11() == fit * 1.25, "a resize undid the user's zoom"


def test_req_set_004_a_tap_that_jitters_keeps_the_board_fitted(qtbot: QtBot) -> None:
    """A press, a move of 3 px and a release on a fitted board, as a finger's tap on a touch screen jitters: nothing
    scrolls, so the board stays fitted and is fitted again at the next resize (review of A7: the hand's drag let go of
    the fit at its first move, and the board kept its small scale in a pane twice as large)."""
    view = _view(qtbot)
    middle = view.viewport().rect().center()
    qtbot.mousePress(view.viewport(), Qt.MouseButton.LeftButton, pos=middle)
    moved = QMouseEvent(
        QEvent.Type.MouseMove,
        QPointF(middle + QPoint(3, 2)),
        QPointF(view.viewport().mapToGlobal(middle + QPoint(3, 2))),
        Qt.MouseButton.NoButton,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )
    QApplication.sendEvent(view.viewport(), moved)
    qtbot.mouseRelease(view.viewport(), Qt.MouseButton.LeftButton, pos=middle + QPoint(3, 2))
    assert view.fitted, "a tap let go of the fit"
    small = view.transform().m11()
    _resized(qtbot, view, 1200, 800)
    assert view.transform().m11() > small * 1.9 and view.viewport().rect().contains(_whole(view))
