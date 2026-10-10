"""REQ-TRN-003, the screen half (stage S33): the label editor beside Training's samples table, where an Engineer draws,
selects, moves and resizes the defect boxes of an NG image, by mouse and by touch, and gives each one of the 33 types,
whose severity the defect table fills in; every change is stored through `AppContext.set_boxes`, which keeps the
boxes before in the image's history (labels sketch, docs/sketches/training-labels.md)."""

from __future__ import annotations

import sqlite3
import threading
import time
from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING, Any

import cv2
import numpy as np
import pytest
from PySide6.QtCore import QEvent, QItemSelectionModel, QPoint, QPointF, QRectF, Qt, qInstallMessageHandler
from PySide6.QtGui import QInputDevice, QKeyEvent, QPointingDevice, QWheelEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QDialog,
    QGraphicsSimpleTextItem,
    QMessageBox,
    QPushButton,
    QWidget,
)
from pytestqt.qtbot import QtBot

from aoi import defects
from aoi.core.labels import DefectBox
from aoi.core.sample_import import ImportFile
from aoi.core.services import AppContext
from aoi.ui import theme
from aoi.ui.pages.base import cell_text
from aoi.ui.pages.training import TrainingPage
from aoi.ui.pages.training_import import LABEL, TYPE
from tests.test_req_done_in_v01 import BOARD, _window

if TYPE_CHECKING:
    from aoi.ui.widgets.box_editor import BoxEditor

LEFT, NONE, CTRL = Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, Qt.KeyboardModifier.ControlModifier
NO_BUTTON = Qt.MouseButton.NoButton
PRESS, RELEASE, SHIFT = QEvent.Type.KeyPress, QEvent.Type.KeyRelease, Qt.KeyboardModifier.ShiftModifier
FINGER = (QInputDevice.DeviceType.TouchScreen, QPointingDevice.PointerType.Finger, QInputDevice.Capability.Position)


def _page(qtbot: QtBot, ctx: AppContext) -> TrainingPage:
    """Training in the active window, the one a key's shortcut works in, as it is for a hand at the keyboard."""
    win = _window(qtbot, ctx)
    win.navigate("Training")
    qtbot.waitUntil(win.isActiveWindow, timeout=5000)
    page = win.pages["Training"]
    assert isinstance(page, TrainingPage)
    return page


def _select(page: TrainingPage, *ids: int) -> None:
    """Select the rows of these sample ids in the samples table, as a click and Ctrl+clicks do."""
    page.samples.clearSelection()
    rows = {int(cell_text(page.samples, r, 0)): r for r in range(page.samples.rowCount())}
    flags = QItemSelectionModel.SelectionFlag.Select | QItemSelectionModel.SelectionFlag.Rows
    for i in ids:
        page.samples.selectionModel().select(page.samples.model().index(rows[i], 0), flags)


def _open(qtbot: QtBot, ctx: AppContext, sample: dict[str, Any]) -> TrainingPage:
    """Training with `sample` selected and shown in the label editor."""
    page = _page(qtbot, ctx)
    _select(page, sample["id"])
    _wait(page)
    assert page.editor.sample is not None and page.editor.sample["uuid"] == sample["uuid"]
    QApplication.processEvents()  # laid out, as the page is before a hand can reach it: the heading on all its lines
    return page


def _wait(page: TrainingPage) -> None:
    """Until the label editor has read, or stored, what it was last given, on its pool thread, and shown the result."""
    end = time.monotonic() + 20
    while not page.editor.idle():
        assert time.monotonic() < end, "the label editor's read or store did not end"
        QTest.qWait(5)


def _key(w: QWidget, key: Qt.Key, modifiers: Qt.KeyboardModifier = NONE) -> None:
    """`key` typed with the focus put on `w`, sent to the widget that has the focus then, as a keyboard sends it."""
    w.setFocus()
    QTest.keyClick(QApplication.focusWidget(), key, modifiers)


def _stored(page: TrainingPage, uuid: str) -> list[tuple[int, int, int, int, str, str]]:
    """The sample's boxes as stored, once the editor's store in hand has ended."""
    _wait(page)
    return [(b["x"], b["y"], b["w"], b["h"], b["dct_type"], b["severity"]) for b in page.ctx.boxes(uuid)]


def _at(view: BoxEditor, x: float, y: float) -> QPoint:
    """The viewport point over image pixel (x, y)."""
    return view.mapFromScene(QPointF(x, y))


def _shift(view: BoxEditor, a: QPoint, b: QPoint) -> QPointF:
    """How far a drag from `a` to `b` moves on the image, in image pixels."""
    return view.mapToScene(b) - view.mapToScene(a)


def _drag(view: BoxEditor, a: QPoint, b: QPoint) -> None:
    """A mouse drag on the image from `a` to `b`, through the point half way."""
    port = view.viewport()
    QTest.mousePress(port, LEFT, NONE, a)
    QTest.mouseMove(port, (a + b) / 2)
    QTest.mouseMove(port, b)
    QTest.mouseRelease(port, LEFT, NONE, b)


def _finger(view: BoxEditor, *points: QPoint) -> None:
    """A finger pressed at the first viewport point, moved through the others and lifted at the last, sent as a touch
    screen sends it, in the window's own points (Qt turns it into the mouse events the view takes)."""
    finger = QPointingDevice("finger", 1, *FINGER, 10, 0)
    window = view.window()
    touch = QTest.touchEvent(window.windowHandle(), finger)
    touch.press(0, view.viewport().mapTo(window, points[0])).commit()
    for p in points[1:]:
        touch.move(0, view.viewport().mapTo(window, p)).commit()
    touch.release(0, view.viewport().mapTo(window, points[-1])).commit()


def _big(ctx: AppContext, folder: Path) -> dict[str, Any]:
    """A 5472 x 3648 px NG board image, as a 20 MP camera takes it, imported: its sample."""
    img = np.full((3648, 5472, 3), (40, 120, 40), np.uint8)
    img[1400:1700, 1800:2300] = (30, 30, 30)
    cv2.imwrite(str(folder / "big_ng.png"), img)
    ctx.import_samples(BOARD, [str(folder / "big_ng.png")], "NG", "Missing Component")  # S31: NG with its type
    return next(s for s in ctx.samples(BOARD, "NG") if "big_ng" in s["path"])


def _labels_whole(view: BoxEditor) -> None:
    """Each box's label, with its backing, lies within the pane, cut at neither edge."""
    for item in view.scene().items():
        if isinstance(item, QGraphicsSimpleTextItem) and item.isVisible():
            shown = item.deviceTransform(view.viewportTransform()).mapRect(item.boundingRect().adjusted(-4, 0, 4, 0))
            assert 0 <= shown.left() and shown.right() <= view.viewport().width(), item.text()


def _wheel(w: QWidget, down: int) -> None:
    """`down` notches of the mouse wheel turned towards the user, the pointer over the middle of `w`."""
    at, step = QPointF(w.width() / 2, w.height() / 2), QPoint(0, -120 if down > 0 else 120)
    for _ in range(abs(down)):
        e = QWheelEvent(at, w.mapToGlobal(at), QPoint(), step, NO_BUTTON, NONE, Qt.ScrollPhase.NoScrollPhase, False)
        QApplication.sendEvent(w, e)


def test_req_trn_003_editor_draw(qtbot: QtBot, trained_ctx: AppContext) -> None:
    """Draw Box, then a drag on an NG image, stores one box where the drag went, in image pixels, with the type in the
    Type field and its severity; it is selected, listed and labelled on the image. A drag past the image's edge ends at
    the edge, one under 4 px draws nothing, and corners between pixels are rounded to whole ones. An OK image takes no
    box: Draw Box is off and the list says why; nor does an image whose file is gone, which the heading names: its
    stored boxes are listed but not drawn over the placeholder, and the list and the Type list are off. Draw Box looks
    on in Draw mode, for a finger that has no cursor to show it. A label the pane's right edge would cut ends at its
    box's right edge, or at the pane's left edge."""
    ctx = trained_ctx
    sample = ctx.samples(BOARD, "NG")[0]
    page = _open(qtbot, ctx, sample)
    editor, view = page.editor, page.editor.view
    assert editor.box_list.count() == 0 and editor.box_list_empty.isVisibleTo(editor)
    assert editor.box_list_empty.heading.text() == "No defect box yet"
    editor.type_box.setCurrentIndex(editor.type_box.findData("Polarity Error"))
    assert editor.severity.text() == "Critical"
    off = editor.draw_btn.grab().toImage()
    editor.draw_btn.click()
    assert editor.draw_btn.isChecked() and editor.draw_btn.grab().toImage() != off, "Draw Box looks on"
    a, b = _at(view, 100, 120), _at(view, 180, 200)
    rows = len(ctx.label_history(sample["uuid"]))
    _drag(view, a, b)
    start, end = view.mapToScene(a), view.mapToScene(b)
    x, y = round(start.x()), round(start.y())
    box = (x, y, round(end.x()) - x, round(end.y()) - y, "Polarity Error", "Critical")
    assert _stored(page, sample["uuid"]) == [box]
    assert len(ctx.label_history(sample["uuid"])) == rows + 1, "one drag, one label row"
    entry = ctx.audit_entries(action="label.set")[0]
    assert entry["object_uuid"] == sample["uuid"] and entry["after"]["boxes"][0]["dct_type"] == "Polarity Error"
    assert view.chosen == 0 and editor.box_list.currentRow() == 0 and not editor.box_list_empty.isVisibleTo(editor)
    assert editor.box_list.item(0).text() == f"1 Polarity Error (Critical) {x},{y} {box[2]}×{box[3]} px"
    labels = [i.text() for i in view.scene().items() if isinstance(i, QGraphicsSimpleTextItem) and i.isVisible()]
    assert "1 Polarity Error ◆ Critical" in labels

    _drag(view, _at(view, 600, 440), _at(view, 700, 560))  # past the bottom right corner of the 640 x 480 image
    edge = _stored(page, sample["uuid"])[1]
    assert (edge[0] + edge[2], edge[1] + edge[3]) == (640, 480)
    _drag(view, _at(view, 300, 300), _at(view, 301, 301))  # a slip of the hand, not a box
    assert len(_stored(page, sample["uuid"])) == 2
    view.roiDrawn.emit(QRectF(100.4, 120.6, 79.7, 80.2))  # a drag between pixels, as ImageView reports one
    shown, stored = view.boxes[2], _stored(page, sample["uuid"])[2]
    assert stored[:4] == (100, 121, 80, 80), "the corners rounded to whole pixels"
    assert all(type(v) is int for v in (shown.x, shown.y, shown.w, shown.h, *stored[:4])), "set_boxes gets no float"
    editor.type_box.setCurrentIndex(editor.type_box.findData("Missing Component"))  # a long label near the left edge
    view.roiDrawn.emit(QRectF(150, 300, 20, 20))
    _labels_whole(view)  # this one and the one at the right edge

    ok = ctx.samples(BOARD, "OK")[1]
    _select(page, ok["id"])
    _wait(page)
    assert editor.sample is not None and editor.sample["uuid"] == ok["uuid"]
    assert not editor.draw_btn.isEnabled() and not editor.draw_btn.isChecked()
    assert editor.box_list_empty.heading.text() == "No defect boxes"
    _drag(view, _at(view, 100, 100), _at(view, 200, 200))
    assert ctx.boxes(ok["uuid"]) == [] and ctx.label_history(ok["uuid"])[0]["label"] == "OK"

    gone = ctx.samples(BOARD, "NG")[1]
    ctx.set_boxes(gone["uuid"], [DefectBox(50, 60, 70, 80, "Scratch")])
    Path(ctx.sample_path(gone["id"])).unlink()  # removed from the workspace since it was imported
    _select(page, gone["id"])
    _wait(page)
    assert editor.sample is not None and editor.sample["uuid"] == gone["uuid"]
    assert "AOI-INSP-001" in editor.heading.text() and view._pix is None and not editor.draw_btn.isEnabled()
    assert view.boxes == [] and editor.box_list.count() == 1, "listed, not drawn over the placeholder"
    assert not editor.box_list.isEnabled() and not editor.type_box.isEnabled()


def test_req_trn_003_editor_move(qtbot: QtBot, trained_ctx: AppContext) -> None:
    """A box dragged by its inside, with the mouse or a finger, moves by the drag and keeps its size; one drag stores
    one label row, and a box stops at the image's edge. A click on a box selects it and stores nothing. A drag whose
    release is lost, the pointer leaving the window, is stored there, and a row selected mid-drag is shown after it."""
    ctx = trained_ctx
    sample, other = ctx.samples(BOARD, "NG")[:2]
    ctx.set_boxes(sample["uuid"], [DefectBox(100, 100, 60, 40, "Scratch"), DefectBox(300, 200, 50, 50, "Tombstone")])
    page = _open(qtbot, ctx, sample)
    editor, view = page.editor, page.editor.view
    rows = len(ctx.label_history(sample["uuid"]))
    QTest.mouseClick(view.viewport(), LEFT, NONE, _at(view, 325, 225))
    assert view.chosen == 1 and editor.box_list.currentRow() == 1
    assert len(ctx.label_history(sample["uuid"])) == rows, "a click stores nothing"
    a = _at(view, 325, 225)
    b = a + QPoint(30, -20)
    _drag(view, a, b)
    d = _shift(view, a, b)
    moved = (round(300 + d.x()), round(200 + d.y()), 50, 50, "Tombstone", "Major")
    assert _stored(page, sample["uuid"]) == [(100, 100, 60, 40, "Scratch", "Minor"), moved]
    assert len(ctx.label_history(sample["uuid"])) == rows + 1

    _drag(view, _at(view, moved[0] + 25, moved[1] + 25), _at(view, 1000, 1000))  # far past the bottom right corner
    assert _stored(page, sample["uuid"])[1][:4] == (590, 430, 50, 50)

    a, b = _at(view, 130, 120), _at(view, 130, 120) + QPoint(-20, 25)
    d = _shift(view, a, b)
    _finger(view, a, b)
    assert _stored(page, sample["uuid"])[0] == (round(100 + d.x()), round(100 + d.y()), 60, 40, "Scratch", "Minor")
    assert view.chosen == 0 and len(ctx.label_history(sample["uuid"])) == rows + 3
    first = _stored(page, sample["uuid"])[0]
    a = _at(view, first[0] + 30, first[1] + 20)
    port = view.viewport()
    QTest.mousePress(port, LEFT, NONE, a)
    QTest.mouseMove(port, a + QPoint(20, 20))
    page.refresh()  # as an import ending meanwhile refreshes the page
    _select(page, other["id"])  # and another row selected meanwhile, shown once the drag has ended
    QTest.mouseMove(port, a + QPoint(40, 40))
    QApplication.sendEvent(view, QEvent(QEvent.Type.Leave))  # the release lost: the pointer left the window
    d = _shift(view, a, a + QPoint(40, 40))
    moved = (round(first[0] + d.x()), round(first[1] + d.y()), 60, 40, "Scratch", "Minor")
    assert _stored(page, sample["uuid"])[0] == moved, "stored as the drag left it"
    assert page.editor.sample is not None and page.editor.sample["uuid"] == other["uuid"], "then the row shown"
    QTest.mouseRelease(port, LEFT, NONE, a + QPoint(80, 80))  # a stray release later changes nothing
    assert _stored(page, sample["uuid"])[0] == moved and len(ctx.label_history(sample["uuid"])) == rows + 4


def test_req_trn_003_editor_real_size(qtbot: QtBot, trained_ctx: AppContext, tmp_path: Path) -> None:
    """On a 5472 x 3648 px image at the editor's fit, a 40 x 32 px box is a few screen pixels: a finger's drag inside
    the selected box moves it and keeps its size, its handles sit outside it, and a drag on one resizes it; a finger
    draws a box with Draw Box, and Enter places one 64 px a side on screen. Zoom In, Zoom Out and Fit, by a click or
    a tap and by the keys +, - and 0, zoom with no wheel, and Z fills the view with the selected box. None of the
    page's keys does anything typed in Epochs, whose line edit takes each."""
    ctx = trained_ctx
    sample = _big(ctx, tmp_path)
    ctx.set_boxes(sample["uuid"], [DefectBox(2000, 1500, 40, 32, "Polarity Error")])
    page = _open(qtbot, ctx, sample)
    editor, view = page.editor, page.editor.view
    assert 40 * view.transform().m11() < 4, "a few screen pixels at fit"
    a = _at(view, 2020, 1516)
    _finger(view, a)
    assert view.chosen == 0
    _finger(view, a, a + QPoint(30, 20), a + QPoint(60, 40))
    x, y, w, h = _stored(page, sample["uuid"])[0][:4]
    assert (w, h) == (40, 32) and (x, y) != (2000, 1500), "moved, not resized"
    corner = _at(view, x + w, y + h) + QPoint(theme.HANDLE_PX // 2, theme.HANDLE_PX // 2)  # its bottom right handle
    _finger(view, corner, corner + QPoint(20, 10))
    x2, y2, w2, h2 = _stored(page, sample["uuid"])[0][:4]
    assert (x2, y2) == (x, y) and w2 > w and h2 > h
    editor.draw_btn.click()
    _finger(view, _at(view, 500, 500), _at(view, 1500, 1000))
    assert len(_stored(page, sample["uuid"])) == 2
    _key(view, Qt.Key.Key_Return)
    placed = _stored(page, sample["uuid"])[2]
    assert abs(placed[2] * view.transform().m11() - 64) <= 1 and placed[2] > 900, "64 px on screen, 1000 of the image"

    def scale() -> float:
        return view.transform().m11()

    fit = scale()
    zoom_in, zoom_out, whole = (
        next(b for b in page.findChildren(QPushButton) if b.text() == name) for name in ("Zoom In", "Zoom Out", "Fit")
    )
    qtbot.mouseClick(zoom_in, LEFT)
    assert scale() == pytest.approx(fit * 1.25)
    _key(view, Qt.Key.Key_Plus)
    assert scale() == pytest.approx(fit * 1.25**2)
    qtbot.mouseClick(zoom_out, LEFT)
    _key(view, Qt.Key.Key_Minus)
    assert scale() == pytest.approx(fit / 1.25 * 1.25)
    editor.box_list.setCurrentRow(0)
    _key(view, Qt.Key.Key_Z)
    x, y, w, h = _stored(page, sample["uuid"])[0][:4]
    shown, port = view.mapFromScene(QRectF(x, y, w, h)).boundingRect(), view.viewport().rect()
    assert shown.width() > port.width() / 4 and port.contains(shown), "the selected box filling the view"
    qtbot.mouseClick(whole, LEFT)
    assert scale() == pytest.approx(fit)
    qtbot.mouseClick(zoom_in, LEFT)
    _key(page.samples, Qt.Key.Key_0)
    assert scale() == pytest.approx(fit)
    editor.box_list.setCurrentRow(0)

    def state() -> tuple[object, ...]:
        _wait(page)
        rows = len(ctx.label_history(sample["uuid"]))
        return rows, editor.draw_btn.isChecked(), scale(), view.chosen, page.samples.currentRow()

    before = state()
    for key in "ONUDZ+-0":  # Mark OK, NG and UNSURE, Draw Box, Zoom to Box, Zoom In, Zoom Out and Fit
        _key(page.epochs, Qt.Key(ord(key)))
    assert state() == before


def test_req_trn_003_editor_resize(qtbot: QtBot, trained_ctx: AppContext) -> None:
    """The selected box has a handle at each corner: dragging one moves that corner while the opposite one stays, never
    past the image's edge and never closer than 4 px to the opposite corner."""
    ctx = trained_ctx
    sample = ctx.samples(BOARD, "NG")[0]
    ctx.set_boxes(sample["uuid"], [DefectBox(200, 150, 80, 60, "Bent Lead")])
    page = _open(qtbot, ctx, sample)
    view = page.editor.view
    QTest.mouseClick(view.viewport(), LEFT, NONE, _at(view, 240, 180))
    assert view.chosen == 0
    a = _at(view, 280, 210)  # the bottom right handle
    b = a + QPoint(30, 20)
    _drag(view, a, b)
    d = _shift(view, a, b)
    x1, y1 = round(280 + d.x()), round(210 + d.y())
    assert _stored(page, sample["uuid"]) == [(200, 150, x1 - 200, y1 - 150, "Bent Lead", "Major")]
    a = _at(view, 200, 150)  # the top left handle, inwards
    b = a + QPoint(10, 15)
    _drag(view, a, b)
    d = _shift(view, a, b)
    x0, y0 = round(200 + d.x()), round(150 + d.y())
    assert _stored(page, sample["uuid"])[0][:4] == (x0, y0, x1 - x0, y1 - y0)
    _drag(view, _at(view, x1, y0), _at(view, 900, -90))  # the top right handle, past the image's top right corner
    assert _stored(page, sample["uuid"])[0][:4] == (x0, 0, 640 - x0, y1)
    _drag(view, _at(view, x0, y1), _at(view, 700, -50))  # the bottom left handle, past the opposite corner
    assert _stored(page, sample["uuid"])[0][:4] == (636, 0, 4, 4)


def test_req_trn_003_editor_type_and_severity(qtbot: QtBot, trained_ctx: AppContext) -> None:
    """The Type field offers the 33 defect types of aoi/defects.py, by category and with no Anomaly; the selected box
    takes the type picked, by Enter on the type shown or by a choice in the open list, stored with the severity the
    defect table gives it, shown beside the field, in the list and on the image. The arrow keys only show a type, which
    leaving the list puts back; the wheel turns it only while the list has the focus, and stores nothing. With no box
    selected, the type picked goes to the next box drawn and nothing is stored."""
    ctx = trained_ctx
    sample = ctx.samples(BOARD, "NG")[0]
    ctx.set_boxes(sample["uuid"], [DefectBox(50, 60, 40, 30, "Scratch")])
    page = _open(qtbot, ctx, sample)
    editor, view, types = page.editor, page.editor.view, page.editor.type_box
    offered = [types.itemData(i) for i in range(types.count())]
    assert offered == defects.names() and len(offered) == 33 and "Anomaly" not in offered
    editor.box_list.setCurrentRow(0)
    assert view.chosen == 0 and types.currentData() == "Scratch" and editor.severity.text() == "Minor"
    rows = len(ctx.label_history(sample["uuid"]))
    _wheel(types, 3)  # three notches down with the pointer over the list and the focus elsewhere
    assert types.currentData() == "Scratch" and len(ctx.label_history(sample["uuid"])) == rows, "the wheel on the way"
    types.setFocus()
    for _ in range(3):
        QTest.keyClick(types, Qt.Key.Key_Down)
    third = defects.names()[defects.names().index("Scratch") + 3]
    assert types.currentData() == third and _stored(page, sample["uuid"])[0][4] == "Scratch", "shown, not picked"
    editor.box_list.setFocus()
    assert types.currentData() == "Scratch", "leaving the list puts back the type picked"
    for kind in defects.DEFECT_TYPES:
        types.setFocus()
        types.setCurrentIndex(types.findData(kind.name))  # as the arrow keys or a letter show it
        QTest.keyClick(types, Qt.Key.Key_Return)
        assert _stored(page, sample["uuid"]) == [(50, 60, 40, 30, kind.name, kind.severity)]
        assert editor.severity.text() == kind.severity
        assert editor.box_list.item(0).text() == f"1 {kind.name} ({kind.severity}) 50,60 40×30 px"
    assert len(ctx.label_history(sample["uuid"])) == rows + 33, "one label row per type picked, each a change"
    on_image = [i.text() for i in view.scene().items() if isinstance(i, QGraphicsSimpleTextItem) and i.isVisible()]
    last = defects.DEFECT_TYPES[-1]
    assert f"1 {last.name} ◆ {last.severity}" in on_image
    types.showPopup()  # the open list, by mouse or finger: the type above the one shown
    above = defects.DEFECT_TYPES[-2]
    spot = types.view().visualRect(types.model().index(len(offered) - 2, 0)).center()
    QTest.mouseClick(types.view().viewport(), LEFT, NONE, spot)
    assert _stored(page, sample["uuid"])[0][4:] == (above.name, above.severity) and not types.view().isVisible()
    rows = len(ctx.label_history(sample["uuid"]))
    editor.box_list.setCurrentRow(-1)
    assert view.chosen == -1
    types.setCurrentIndex(types.findData("Solder Ball"))
    QTest.keyClick(types, Qt.Key.Key_Return)
    assert len(ctx.label_history(sample["uuid"])) == rows and editor.severity.text() == "Minor"
    editor.draw_btn.click()
    _drag(view, _at(view, 300, 300), _at(view, 340, 330))
    assert [b[4:] for b in _stored(page, sample["uuid"])] == [(above.name, above.severity), ("Solder Ball", "Minor")]


def test_req_trn_003_editor_reads_and_stores_off_the_ui_thread(
    qtbot: QtBot, trained_ctx: AppContext, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The image and its boxes are read, and each change stored, on a pool thread, never on the UI thread. While a
    change is stored the editor says so after a second and takes no other: a second box drawn or a type picked is
    refused with a word in the status bar, the stored boxes staying as they are; a row selected meanwhile is shown once
    the change is stored, and an image slow to open says so too."""
    ctx = trained_ctx
    first, other = ctx.samples(BOARD, "NG")[:2]
    page = _page(qtbot, ctx)
    _select(page, first["id"])
    qtbot.waitUntil(page.editor.draw_btn.isEnabled)  # the image and its boxes read
    editor, view, types = page.editor, page.editor.view, page.editor.type_box
    on_ui: dict[str, set[bool]] = {}  # each call watched: made on the UI thread or not
    gates = {"set_boxes": threading.Event(), "load_image": threading.Event()}  # held until the test lets them go

    def watch(name: str) -> None:
        call = getattr(ctx, name)

        def watched(*args: Any) -> Any:
            ui = threading.current_thread() is threading.main_thread()
            on_ui.setdefault(name, set()).add(ui)
            if name in gates and not ui:
                gates[name].wait(10)
            return call(*args)

        monkeypatch.setattr(ctx, name, watched)

    for name in ("set_boxes", "load_image", "boxes"):
        watch(name)
    rows, kind = len(ctx.label_history(first["uuid"])), types.currentData()
    editor.draw_btn.click()
    port = view.viewport()
    for a, b in ((_at(view, 100, 100), _at(view, 160, 150)), (_at(view, 300, 300), _at(view, 360, 350))):
        QTest.mousePress(port, LEFT, NONE, a)
        QTest.mouseMove(port, b)
        QTest.mouseRelease(port, LEFT, NONE, b)
        qtbot.waitUntil(lambda: "set_boxes" in on_ui)
        assert on_ui == {"set_boxes": {False}}, "stored on a pool thread"
    assert len(view.boxes) == 1, "the second box refused while the first is stored"
    wait = "Wait until the image is open and the last change is stored"
    assert page.shell.statusBar().currentMessage() == wait
    qtbot.waitUntil(editor.saving.isVisible, timeout=3000)  # after a second, over the image
    types.setFocus()
    types.setCurrentIndex(types.findData("Scratch" if kind != "Scratch" else "Tombstone"))
    QTest.keyClick(types, Qt.Key.Key_Return)
    assert view.boxes[0].dct_type == kind and types.currentData() == kind, "the type picked refused"
    _select(page, other["id"])
    assert editor.sample is not None and editor.sample["uuid"] == first["uuid"], "shown once the change is stored"
    gates["set_boxes"].set()
    qtbot.waitUntil(editor.reading.isVisible, timeout=3000)  # the other image, held, read after the store
    assert editor.sample["uuid"] == other["uuid"] and not editor.draw_btn.isEnabled()
    gates["load_image"].set()
    _wait(page)
    assert editor.sample["uuid"] == other["uuid"] and view._pix is not None and not editor.saving.isVisible()
    assert on_ui == {"set_boxes": {False}, "load_image": {False}, "boxes": {False}}, "nothing on the UI thread"
    assert [b[4] for b in _stored(page, first["uuid"])] == [kind] and len(ctx.label_history(first["uuid"])) == rows + 1


def test_req_trn_003_editor_delete_and_undo(
    qtbot: QtBot, trained_ctx: AppContext, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Delete Box, red and the last in its row, is on only while a box is selected: it deletes that box at once, with
    no question, the box kept in the image's history, and the Delete key does the same. Undo beside it and Ctrl+Z, on
    only while there is a change to undo, put back the boxes as they were before the last change stored, one change
    per press, each as a new label, on whichever image it was, which is then selected and shown. Switch User and
    another board model leave nothing to undo."""
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: pytest.fail("Delete Box asks nothing"))
    ctx = trained_ctx
    sample, other = ctx.samples(BOARD, "NG")[:2]
    both = [(100, 100, 60, 40, "Scratch", "Minor"), (300, 200, 50, 50, "Tombstone", "Major")]
    ctx.set_boxes(sample["uuid"], [DefectBox(*b[:5]) for b in both])
    page = _open(qtbot, ctx, sample)
    editor, view, win = page.editor, page.editor.view, page.shell
    undo, delete = (next(b for b in page.findChildren(QPushButton) if b.text() == t) for t in ("Undo", "Delete Box"))
    assert delete.objectName() == "danger" and not delete.isEnabled() and not undo.isEnabled()
    assert undo.y() == delete.y() and undo.x() < delete.x(), "Undo beside Delete Box, which comes last"
    editor.box_list.setCurrentRow(0)
    assert delete.isEnabled()
    rows = len(ctx.label_history(sample["uuid"]))
    qtbot.mouseClick(delete, LEFT)
    assert _stored(page, sample["uuid"]) == both[1:] and editor.box_list.count() == 1
    history = ctx.label_history(sample["uuid"])
    assert len(history) == rows + 1 and [b["dct_type"] for b in history[1]["boxes"]] == ["Scratch", "Tombstone"]
    assert view.chosen == -1 and not delete.isEnabled() and undo.isEnabled()
    assert win.statusBar().currentMessage() == "Box 1 deleted; Undo or Ctrl+Z brings it back"
    _key(page.samples, Qt.Key.Key_Z, CTRL)  # wherever the focus is on the page
    assert _stored(page, sample["uuid"]) == both and len(ctx.label_history(sample["uuid"])) == rows + 2
    assert editor.box_list.count() == 2 and not undo.isEnabled()
    editor.box_list.setCurrentRow(1)
    _key(editor.box_list, Qt.Key.Key_Delete)
    assert _stored(page, sample["uuid"]) == both[:1]
    assert win.statusBar().currentMessage() == "Box 2 deleted; Undo or Ctrl+Z brings it back"
    editor.box_list.setCurrentRow(0)
    _drag(view, _at(view, 130, 120), _at(view, 230, 220))  # a move, then two undos: the move, then the delete
    assert _stored(page, sample["uuid"]) != both[:1]
    _key(view, Qt.Key.Key_Z, CTRL)
    assert _stored(page, sample["uuid"]) == both[:1]
    qtbot.mouseClick(undo, LEFT)  # a click or a tap
    assert _stored(page, sample["uuid"]) == both and not undo.isEnabled()
    assert len(ctx.label_history(sample["uuid"])) == rows + 6, "each delete, move and undo a label row of its own"

    editor.box_list.setCurrentRow(0)
    qtbot.mouseClick(delete, LEFT)
    _select(page, other["id"])
    _wait(page)
    _key(page.samples, Qt.Key.Key_Z, CTRL)  # the change was on the image before
    assert _stored(page, sample["uuid"]) == both and page._selected_ids() == [sample["id"]]
    assert editor.sample is not None and editor.sample["uuid"] == sample["uuid"] and editor.box_list.count() == 2

    editor.box_list.setCurrentRow(0)
    qtbot.mouseClick(delete, LEFT)
    _wait(page)
    win.set_user("admin")  # Switch User: the next user cannot undo what the one before did
    assert not undo.isEnabled()
    win.set_user("engineer")
    _key(page.samples, Qt.Key.Key_Z, CTRL)
    assert _stored(page, sample["uuid"]) == both[1:] and not undo.isEnabled()
    _select(page, sample["id"])
    _wait(page)
    editor.box_list.setCurrentRow(0)
    qtbot.mouseClick(delete, LEFT)
    assert _stored(page, sample["uuid"]) == [] and undo.isEnabled()
    ctx.ensure_board_model("OTHER")
    win._on_board_model("OTHER")
    win._on_board_model(BOARD)
    assert not undo.isEnabled()


def test_req_trn_003_editor_mark(qtbot: QtBot, trained_ctx: AppContext, monkeypatch: pytest.MonkeyPatch) -> None:
    """Mark OK, Mark NG and Mark UNSURE, and the keys O, N and U, relabel each selected image not already so labelled,
    with no question and on a pool thread; the table and the label editor show the new label, the rows still
    selected. An image relabelled OK or UNSURE keeps its boxes in history only; Mark NG puts the focus on the image.
    Undo and Ctrl+Z undo a mark too, the images getting back their label and boxes. A letter typed in a text field or
    in the Type list goes to it, and marks nothing. A label carried over with no labeller is labelled again by the
    same mark, so that it can be checked, which Undo does not take back."""
    monkeypatch.setattr(QDialog, "exec", lambda self: pytest.fail("Mark NG asks nothing"))
    ctx = trained_ctx
    ng = ctx.samples(BOARD, "NG")[0]
    ctx.set_boxes(ng["uuid"], [DefectBox(100, 100, 60, 40, "Scratch")])
    box = [(100, 100, 60, 40, "Scratch", "Minor")]
    page = _open(qtbot, ctx, ng)
    editor = page.editor
    marks = {b.text(): b for b in page.findChildren(QPushButton) if b.text().startswith("Mark")}
    assert sorted(marks) == ["Mark NG", "Mark OK", "Mark UNSURE"]
    rows = len(ctx.label_history(ng["uuid"]))
    on_ui: set[bool] = set()
    relabel = ctx.set_label  # the marks' call (S32's), which takes UNSURE and an NG with no type yet

    def watched(*args: Any) -> None:
        on_ui.add(threading.current_thread() is threading.main_thread())
        relabel(*args)

    monkeypatch.setattr(ctx, "set_label", watched)

    def now(sample: dict[str, Any]) -> str:
        """The image's label as stored, as the table shows it and, for the image in the editor, as its heading says."""
        _wait(page)
        label = ctx.label_history(sample["uuid"])[0]["label"]
        row = next(r for r in range(page.samples.rowCount()) if int(cell_text(page.samples, r, 0)) == sample["id"])
        assert cell_text(page.samples, row, 1) == label
        if editor.sample is not None and editor.sample["uuid"] == sample["uuid"]:
            assert f" · {label} · " in editor.heading.text() and editor.sample["label"] == label
        return label

    qtbot.mouseClick(marks["Mark OK"], LEFT)
    assert now(ng) == "OK" and len(ctx.label_history(ng["uuid"])) == rows + 1 and page._selected_ids() == [ng["id"]]
    assert ctx.boxes(ng["uuid"]) == [] and len(ctx.label_history(ng["uuid"])[1]["boxes"]) == 1, "kept in history"
    assert not editor.draw_btn.isEnabled() and editor.box_list_empty.heading.text() == "No defect boxes"
    assert on_ui == {False}, "relabelled on a pool thread"
    qtbot.mouseClick(marks["Mark OK"], LEFT)
    assert now(ng) == "OK" and len(ctx.label_history(ng["uuid"])) == rows + 1, "already OK: no label row"
    _key(page.samples, Qt.Key.Key_U)
    assert now(ng) == "UNSURE" and not editor.draw_btn.isEnabled()
    _key(page.samples, Qt.Key.Key_N)
    assert now(ng) == "NG" and ctx.label_history(ng["uuid"])[0]["defect_type"] is None
    assert editor.draw_btn.isEnabled() and QApplication.focusWidget() is editor.view
    assert editor.box_list_empty.heading.text() == "No defect box yet"
    assert len(ctx.audit_entries(action="label.set", object_uuid=ng["uuid"])) == 4  # the box set first, O, U and N
    _key(page.samples, Qt.Key.Key_Z, CTRL)  # N undone, then U, then O: NG again with its box
    assert now(ng) == "UNSURE"
    _key(page.samples, Qt.Key.Key_Z, CTRL)
    assert now(ng) == "OK"
    _key(page.samples, Qt.Key.Key_Z, CTRL)
    assert now(ng) == "NG" and _stored(page, ng["uuid"]) == box and editor.box_list.count() == 1
    assert ctx.label_history(ng["uuid"])[0]["defect_type"] == ng["defect_type"]

    oks = ctx.samples(BOARD, "OK")[1:3]
    _select(page, *(s["id"] for s in oks))
    _key(editor.box_list, Qt.Key.Key_U)  # from any control but a text field or a drop-down list
    assert [now(s) for s in oks] == ["UNSURE", "UNSURE"]
    assert sorted(page._selected_ids()) == sorted(s["id"] for s in oks), "the rows stay selected"
    qtbot.mouseClick(editor.undo_btn, LEFT)
    assert [now(s) for s in oks] == ["OK", "OK"] and sorted(page._selected_ids()) == sorted(s["id"] for s in oks)
    for key in (Qt.Key.Key_O, Qt.Key.Key_N, Qt.Key.Key_U):  # typed in Epochs, whose line edit takes them: no mark
        _key(page.epochs, key)
    _key(page.shell.bm_combo, Qt.Key.Key_U)  # nor in the header's drop-down list of board models
    _select(page, ng["id"])
    _wait(page)
    editor.box_list.setCurrentRow(0)
    _key(editor.type_box, Qt.Key.Key_O)  # the Type list shows Open Circuit, and nothing is marked or stored
    assert editor.type_box.currentData() == "Open Circuit" and _stored(page, ng["uuid"]) == box
    assert [now(s) for s in (ng, *oks)] == ["NG", "OK", "OK"]
    carried = ctx.samples(BOARD, "OK")[3]
    ctx.db.add_label(carried["uuid"], "OK", None, [], None)  # as migration 0014 carries a label over: no labeller
    page.refresh()
    _select(page, carried["id"])
    _key(page.samples, Qt.Key.Key_O)
    assert now(carried) == "OK" and ctx.label_history(carried["uuid"])[0]["labelled_by"] == ctx.user_uuid
    assert not editor.undo_btn.isEnabled(), "labelled again for its check: no label or box to put back"


def test_req_trn_003_editor_types_in_the_table(qtbot: QtBot, trained_ctx: AppContext) -> None:
    """The samples table's Defect type shows the types of an image's boxes, each once with its count, as soon as one
    is stored; with no box, the type given at import or none. The label's own defect type stays as it was."""
    ctx = trained_ctx
    ng = ctx.samples(BOARD, "NG")[0]
    page = _open(qtbot, ctx, ng)
    editor, view = page.editor, page.editor.view

    def shown() -> str:
        _wait(page)
        return next(
            cell_text(page.samples, r, 2)
            for r in range(page.samples.rowCount())
            if int(cell_text(page.samples, r, 0)) == ng["id"]
        )

    given = ng["defect_type"] or ""
    assert shown() == given
    editor.draw_btn.click()
    for kind, x in (("Solder Bridge", 100), ("Missing Component", 200), ("Solder Bridge", 300)):
        editor.type_box.setCurrentIndex(editor.type_box.findData(kind))
        _drag(view, _at(view, x, 100), _at(view, x + 40, 140))
        _wait(page)
    assert shown() == "Solder Bridge ×2, Missing Component"
    page.refresh()
    assert shown() == "Solder Bridge ×2, Missing Component", "as the table is filled again"
    assert ctx.label_history(ng["uuid"])[0]["defect_type"] == ng["defect_type"], "the label's own type as it was"
    for _ in range(3):
        editor.box_list.setCurrentRow(0)
        editor.act_delete.trigger()
        _wait(page)
    assert shown() == given


def test_req_trn_003_editor_next_and_previous(qtbot: QtBot, trained_ctx: AppContext) -> None:
    """PgDn and PgUp move the label editor to the next and previous image of the samples table, as it is sorted, with
    the focus anywhere but a text field: that row alone is selected, and the ends stay where they are. From several
    rows selected they move from the topmost; with none selected PgDn starts at the first row."""
    page = _page(qtbot, trained_ctx)
    editor, table = page.editor, page.samples

    def order() -> list[int]:
        return [int(cell_text(table, r, 0)) for r in range(table.rowCount())]

    def key(target: QWidget, k: Qt.Key, expected: int) -> None:
        _key(target, k)
        _wait(page)
        assert page._selected_ids() == [expected] and editor.sample is not None and editor.sample["id"] == expected

    ids = order()
    _select(page, ids[0])
    key(table, Qt.Key.Key_PageDown, ids[1])
    key(editor.view, Qt.Key.Key_PageDown, ids[2])  # from the image as from the table
    key(editor.box_list, Qt.Key.Key_PageUp, ids[1])
    key(table, Qt.Key.Key_PageUp, ids[0])
    key(table, Qt.Key.Key_PageUp, ids[0])  # the first row stays
    _select(page, ids[-1])
    key(table, Qt.Key.Key_PageDown, ids[-1])  # and so does the last
    files = next(c for c in range(table.columnCount()) if table.horizontalHeaderItem(c).text() == "File")
    table.sortItems(files, Qt.SortOrder.DescendingOrder)  # by File, Z to A: the order the rows are seen in
    seen = order()
    assert seen != ids and sorted(seen) == sorted(ids)
    _select(page, seen[0])
    key(table, Qt.Key.Key_PageDown, seen[1])
    _select(page, seen[4], seen[2])
    key(table, Qt.Key.Key_PageDown, seen[3])
    table.clearSelection()
    _wait(page)
    assert editor.sample is None
    key(table, Qt.Key.Key_PageDown, seen[0])


def test_req_trn_003_editor_keyboard_only(qtbot: QtBot, trained_ctx: AppContext) -> None:
    """Every step of labelling an image by keys alone, each sent to the widget with the focus: PgDn to an OK image, N to
    mark it NG, the focus then on the image; D for Draw mode and Enter for a box of the Type list's type, 64 px a side
    on screen, at the middle of the image shown; the arrows move it 1 px, Shift 10 px, and Ctrl sizes it from its bottom
    right corner, the keys of a burst, or a key held down, stored once half a second after the last; Shift+Tab to the
    Type list, Down and Enter for the next type, D typed there going to the list; Tab to the Boxes list and Down to
    select a box; Delete and Ctrl+Z; Esc to leave Draw mode; U and O to mark the image. A page key on Enter, as the
    sketch's Check Label will be, takes neither the image's Enter nor the Type list's."""
    ctx, page = trained_ctx, _page(qtbot, trained_ctx)
    editor, view = page.editor, page.editor.view
    page.action("Check", "Return", lambda: pytest.fail("the page took the image's or the Type list's Enter"))

    def press(key: Qt.Key, modifier: Qt.KeyboardModifier = NONE) -> None:
        QTest.keyClick(QApplication.focusWidget(), key, modifier)

    def box() -> tuple[int, int, int, int, str, str]:
        assert editor.sample is not None
        [stored] = _stored(page, editor.sample["uuid"])
        return stored

    def rows() -> int:
        _wait(page)
        assert editor.sample is not None
        return len(ctx.label_history(editor.sample["uuid"]))

    page.samples.setFocus()
    for _ in range(page.samples.rowCount()):
        press(Qt.Key.Key_PageDown)
        _wait(page)
        if editor.sample is not None and editor.sample["label"] == "OK":
            break
    assert editor.sample is not None and editor.sample["label"] == "OK" and editor.draw_btn.toolTip() == "D"
    press(Qt.Key.Key_N)
    _wait(page)
    assert editor.sample["label"] == "NG" and QApplication.focusWidget() is view and not editor.draw_btn.isChecked()
    press(Qt.Key.Key_D)
    assert editor.draw_btn.isChecked() and QApplication.focusWidget() is view
    middle = view.mapToScene(view.viewport().rect().center())
    press(Qt.Key.Key_Return)
    x, y, w, h, kind, severity = box()
    assert abs(w * view.transform().m11() - 64) <= 1 and w == h, "64 px a side on screen"
    assert (kind, severity) == (editor.type_box.currentData(), defects.BY_NAME[kind].severity)
    assert abs(x + w / 2 - middle.x()) <= 1 and abs(y + h / 2 - middle.y()) <= 1 and view.chosen == 0
    before = rows()
    press(Qt.Key.Key_Right)
    press(Qt.Key.Key_Down)
    press(Qt.Key.Key_Left, SHIFT)
    assert box()[:4] == (x - 9, y + 1, w, h) and rows() == before + 1, "three keys, one burst, one label row"
    press(Qt.Key.Key_Right, CTRL)
    press(Qt.Key.Key_Down, CTRL | SHIFT)
    assert box()[:4] == (x - 9, y + 1, w + 1, h + 10) and rows() == before + 2
    for kind_of, repeat in [(PRESS, False)] + [(t, True) for _ in range(3) for t in (RELEASE, PRESS)]:
        QApplication.sendEvent(view, QKeyEvent(kind_of, Qt.Key.Key_Up, NONE, "", repeat))
    QApplication.sendEvent(view, QKeyEvent(RELEASE, Qt.Key.Key_Up, NONE, "", False))
    assert box()[:4] == (x - 9, y - 3, w + 1, h + 10) and rows() == before + 3, "a key held down, one label row"
    press(Qt.Key.Key_Tab, SHIFT)
    assert QApplication.focusWidget() is editor.type_box
    press(Qt.Key.Key_D)  # typed in the list: it shows Damaged Component, and Draw mode stays on
    assert editor.type_box.currentData() == "Damaged Component" and editor.draw_btn.isChecked()
    assert box()[4] == kind, "shown, not picked"
    editor.type_box.setCurrentIndex(editor.type_box.findData(kind))
    press(Qt.Key.Key_Down)
    press(Qt.Key.Key_Return)
    after = defects.names()[defects.names().index(kind) + 1]
    assert box()[4:] == (after, defects.BY_NAME[after].severity)
    press(Qt.Key.Key_Tab)
    assert QApplication.focusWidget() is view
    press(Qt.Key.Key_Delete)
    assert _stored(page, editor.sample["uuid"]) == []
    press(Qt.Key.Key_Z, CTRL)
    assert box()[4] == after and view.chosen == -1
    press(Qt.Key.Key_Tab)
    press(Qt.Key.Key_Down)
    assert QApplication.focusWidget() is editor.box_list and view.chosen == 0
    press(Qt.Key.Key_Tab, SHIFT)
    press(Qt.Key.Key_Right, SHIFT)
    assert QApplication.focusWidget() is view and box()[:4] == (x + 1, y - 3, w + 1, h + 10)
    press(Qt.Key.Key_Escape)
    assert not editor.draw_btn.isChecked()
    press(Qt.Key.Key_U)
    _wait(page)
    assert editor.sample["label"] == "UNSURE" and not editor.draw_btn.isEnabled()
    press(Qt.Key.Key_O)
    _wait(page)
    assert editor.sample["label"] == "OK"


def test_req_trn_003_editor_keys_typed_in_the_import_sheet_go_to_it(
    qtbot: QtBot, trained_ctx: AppContext, tmp_path: Path
) -> None:
    """With S31's import sheet open beside the label editor, a key typed in the sheet goes to the sheet, never to the
    page's keys O, N, U, D, Z, +, - and 0: typed in a row's Label or Defect type cell it opens the cell's drop-down on
    the value it starts, where there is one. The images selected in the samples table keep their labels and boxes, no
    label or audit entry is stored, Draw mode stays off and the zoom as it was (the review of the joined stack)."""
    ctx = trained_ctx
    ng, ok = ctx.samples(BOARD, "NG")[0], ctx.samples(BOARD, "OK")[2]
    ctx.set_boxes(ng["uuid"], [DefectBox(100, 100, 60, 40, "Scratch")])
    page = _page(qtbot, ctx)
    page.samples.sortItems(1, Qt.SortOrder.AscendingOrder)  # NG rows first: the NG image shown, the OK one selected too
    _select(page, ng["id"], ok["id"])
    _wait(page)
    editor, view, table = page.editor, page.editor.view, page.sheet.table
    assert editor.sample is not None and editor.sample["uuid"] == ng["uuid"]
    editor.box_list.setCurrentRow(0)  # a box selected: Z and Delete Box on, as Draw Box is
    assert editor.act_to_box.isEnabled() and editor.act_draw.isEnabled() and not editor.draw_btn.isChecked()
    before = [(ctx.label_history(s["uuid"]), ctx.boxes(s["uuid"])) for s in (ng, ok)], ctx.audit_entries()
    scale = view.transform().m11()
    page._open_sheet(BOARD, [ImportFile(str(tmp_path / "board.png"), "NG")])
    keys = [Qt.Key.Key_O, Qt.Key.Key_N, Qt.Key.Key_U, Qt.Key.Key_D, Qt.Key.Key_Z, Qt.Key.Key_Plus, Qt.Key.Key_Minus]

    def typed(column: int, key: Qt.Key) -> object:
        """`key` typed on the sheet's cell: the value its drop-down shows, which Esc then closes."""
        table.setCurrentCell(0, column)
        _key(table, key)
        box = QApplication.focusWidget()
        assert isinstance(box, QComboBox) and table.isAncestorOf(box), (column, key, box)
        shown = box.currentData()
        QTest.keyClick(box, Qt.Key.Key_Escape)  # the drop-down closes, the sheet stays
        assert QApplication.focusWidget() is table and page.sheet.isVisible()
        return shown

    assert [typed(LABEL, k) for k in [*keys, Qt.Key.Key_0]] == ["OK", "NG", "NG", "NG", "NG", "NG", "NG", "NG"]
    kinds = [typed(TYPE, k) for k in [*keys, Qt.Key.Key_0]]
    assert kinds == ["Open Circuit"] * 3 + ["Damaged Component"] * 5
    assert (page.sheet.files[0].label, page.sheet.files[0].defect_type) == ("NG", "Damaged Component")
    _wait(page)
    after = [(ctx.label_history(s["uuid"]), ctx.boxes(s["uuid"])) for s in (ng, ok)], ctx.audit_entries()
    assert after == before, "no image of the samples table was marked or changed"
    assert not editor.draw_btn.isChecked() and view.transform().m11() == scale and view.chosen == 0
    assert sorted(page._selected_ids()) == sorted([ng["id"], ok["id"]]) and not editor.act_undo.isEnabled()


def test_req_trn_003_editor_esc_closes_the_import_sheet_or_leaves_draw_mode(
    qtbot: QtBot, trained_ctx: AppContext, tmp_path: Path
) -> None:
    """With Draw mode on and S31's import sheet open, Esc with the focus anywhere in the sheet closes the sheet, Draw
    mode staying on; with the focus anywhere else on the page it leaves Draw mode, the sheet staying open. Neither is
    an ambiguous shortcut, which Qt logs and acts on neither of (the review of the joined stack)."""
    ctx = trained_ctx
    page = _open(qtbot, ctx, ctx.samples(BOARD, "NG")[0])
    editor, sheet = page.editor, page.sheet
    logged: list[str] = []
    previous = qInstallMessageHandler(lambda _mode, _context, message: logged.append(message))
    try:
        for inside in (sheet.table, sheet.type_box, sheet.btn_copy):
            page._open_sheet(BOARD, [ImportFile(str(tmp_path / "board.png"), "OK")])
            editor.draw_btn.click()
            assert editor.draw_btn.isChecked() and editor.act_leave.isEnabled()
            _key(inside, Qt.Key.Key_Escape)
            assert sheet.isHidden() and editor.draw_btn.isChecked(), type(inside).__name__
            editor.draw_btn.click()
        for outside in (page.samples, editor.view, editor.box_list):
            page._open_sheet(BOARD, [ImportFile(str(tmp_path / "board.png"), "OK")])
            editor.draw_btn.click()
            _key(outside, Qt.Key.Key_Escape)
            assert not editor.draw_btn.isChecked() and sheet.isVisible(), type(outside).__name__
            page._close_sheet()
    finally:
        qInstallMessageHandler(previous)
    assert not [m for m in logged if "mbiguous" in m], logged


def _held(n: int, real: Callable[..., Any]) -> Callable[..., Any]:
    """`real`, whose n-th call raises SQLite's "database is locked", as one does once the busy timeout ends (db.py)."""
    calls: list[object] = []

    def call(*args: Any, **kwargs: Any) -> Any:
        calls.append(args)
        if len(calls) == n:
            held = sqlite3.OperationalError("database is locked")
            held.sqlite_errorcode = sqlite3.SQLITE_BUSY
            raise held
        return real(*args, **kwargs)

    return call


def test_req_trn_003_editor_a_batch_an_error_stops_shows_what_it_stored(
    qtbot: QtBot, trained_ctx: AppContext, monkeypatch: pytest.MonkeyPatch, dialogs: list[tuple[str, str]]
) -> None:
    """A mark of three images that an error other than a refusal stops at the second, such as a database another
    program holds past the busy timeout, keeps what it stored: the table shows it, the error is the coded dialog as
    before (AOI-SET-013), and Undo puts it back. An Undo, and Remove, stopped so show what they changed before the
    error, with its dialog (the review of the joined stack)."""
    ctx = trained_ctx
    oks = ctx.samples(BOARD, "OK")[1:4]
    page = _open(qtbot, ctx, oks[0])
    real = ctx.set_label

    def stored() -> list[str]:
        """Each image's label as stored, which the table shows."""
        _wait(page)
        rows = {int(cell_text(page.samples, r, 0)): r for r in range(page.samples.rowCount())}
        labels = [ctx.label_history(s["uuid"])[0]["label"] for s in oks]
        assert labels == [cell_text(page.samples, rows[s["id"]], 1) for s in oks]
        return sorted(labels)

    monkeypatch.setattr(ctx, "set_label", _held(2, real))
    _select(page, *(s["id"] for s in oks))
    page.act_unsure.trigger()
    assert stored() == ["OK", "OK", "UNSURE"] and page.editor.act_undo.isEnabled()
    assert [t[:11] for t, _ in dialogs] == ["AOI-SET-013"]
    monkeypatch.setattr(ctx, "set_label", real)
    page.editor.act_undo.trigger()
    assert stored() == ["OK", "OK", "OK"] and not page.editor.act_undo.isEnabled()

    _select(page, *(s["id"] for s in oks))  # Undo selected the one image it put back
    page.act_unsure.trigger()
    assert stored() == ["UNSURE", "UNSURE", "UNSURE"]
    monkeypatch.setattr(ctx, "set_label", _held(2, real))
    page.editor.act_undo.trigger()  # put back one, then stopped
    assert stored() == ["OK", "UNSURE", "UNSURE"] and [t[:11] for t, _ in dialogs] == ["AOI-SET-013"] * 2

    ctx.set_user("admin")  # only an Admin removes a sample (REQ-LOG-003)
    monkeypatch.setattr(ctx, "delete_sample", _held(2, ctx.delete_sample))
    _select(page, *(s["id"] for s in oks))
    page._remove()
    _wait(page)
    left = {s["id"] for s in ctx.samples(BOARD)}
    assert sum(s["id"] in left for s in oks) == 2 and len(dialogs) == 3
    assert {int(cell_text(page.samples, r, 0)) for r in range(page.samples.rowCount())} == left


def test_req_trn_003_editor_a_store_ending_after_a_sign_in_leaves_nothing_to_undo(
    qtbot: QtBot, trained_ctx: AppContext, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A change whose store ends only after another user signed in, or another board model was picked, is stored, but
    Undo stays empty, as for one stored before: the next user never undoes it, nor Undo changes an image of the board
    model before (the review of the joined stack)."""
    ctx = trained_ctx
    ng = ctx.samples(BOARD, "NG")[0]
    ctx.set_boxes(ng["uuid"], [DefectBox(100, 100, 60, 40, "Scratch"), DefectBox(200, 100, 60, 40, "Scratch")])
    page = _open(qtbot, ctx, ng)
    editor, win = page.editor, page.shell
    real, go = ctx.set_boxes, threading.Event()

    def slow(*args: Any) -> str:  # stored, but its end reaches the page late, as from a slow network share
        uid = real(*args)
        assert go.wait(10)
        return uid

    def delete_first() -> None:
        go.clear()
        editor.box_list.setCurrentRow(0)
        editor.act_delete.trigger()
        assert editor.busy(), "still being stored"

    monkeypatch.setattr(ctx, "set_boxes", slow)
    delete_first()
    win.set_user("admin")
    go.set()
    _wait(page)
    assert len(ctx.boxes(ng["uuid"])) == 1 and not editor.act_undo.isEnabled()
    ctx.ensure_board_model("OTHER")
    delete_first()
    win._on_board_model("OTHER")
    go.set()
    _wait(page)
    win._on_board_model(BOARD)
    _wait(page)
    assert ctx.boxes(ng["uuid"]) == [] and not editor.act_undo.isEnabled()


def test_req_trn_003_editor_mark_after_a_box_adds_no_row(qtbot: QtBot, trained_ctx: AppContext) -> None:
    """A label carried over with no labeller, then a box drawn on it, which stores a label row as the user acting:
    Mark NG then finds it NG with a labeller and adds no label row and no audit entry (ADR 0009, decision 2). Before,
    it went by the table as read before the box and stored a copy of that row (review of main, 2026-10-09)."""
    ctx = trained_ctx
    ng = ctx.samples(BOARD, "NG")[0]
    ctx.db.add_label(ng["uuid"], "NG", ng["defect_type"], [], None)  # as migration 0014 carries a label over
    page = _open(qtbot, ctx, ng)
    view = page.editor.view
    page.editor.draw_btn.click()
    _drag(view, _at(view, 100, 100), _at(view, 160, 140))
    assert len(_stored(page, ng["uuid"])) == 1 and ctx.label_history(ng["uuid"])[0]["labelled_by"] == ctx.user_uuid
    rows = len(ctx.label_history(ng["uuid"]))
    audits = len(ctx.audit_entries(action="label.set", object_uuid=ng["uuid"]))
    _key(page.samples, Qt.Key.Key_N)
    _wait(page)
    assert len(ctx.label_history(ng["uuid"])) == rows, "no second row for the label the box stored"
    assert len(ctx.audit_entries(action="label.set", object_uuid=ng["uuid"])) == audits


def test_req_trn_003_editor_mark_ng_drops_a_type_not_of_the_33(
    qtbot: QtBot, trained_ctx: AppContext, dialogs: list[tuple[str, str]]
) -> None:
    """An NG image whose label an earlier version stored with a type that is not one of the 33 (Missing), carried over
    with no labeller, takes no box: AOI-TRN-030 says so and that Mark NG labels it NG again with no type. Mark NG does,
    as the user acting, and its boxes are then drawn; Mark OK on another such image, then Undo, puts it back NG with no
    type, the one it can take (the review of the joined stack)."""
    ctx = trained_ctx
    ng, other = ctx.samples(BOARD, "NG")[:2]
    for s in (ng, other):
        ctx.db.add_label(s["uuid"], "NG", "Missing", [], None)  # as migration 0014 carries an earlier label over
    page = _open(qtbot, ctx, ng)
    editor, view = page.editor, page.editor.view
    rows = len(ctx.label_history(ng["uuid"]))
    editor.draw_btn.click()
    _drag(view, _at(view, 100, 100), _at(view, 160, 140))
    assert _stored(page, ng["uuid"]) == [] and [t[:11] for t, _ in dialogs] == ["AOI-TRN-030"]
    assert "Missing, is not one of the 33" in dialogs[0][1] and "Mark NG" in dialogs[0][1]
    _key(page.samples, Qt.Key.Key_N)
    _wait(page)
    label = ctx.label_history(ng["uuid"])[0]
    assert (label["label"], label["defect_type"], label["labelled_by"]) == ("NG", None, ctx.user_uuid)
    assert len(ctx.label_history(ng["uuid"])) == rows + 1 and len(dialogs) == 1
    _drag(view, _at(view, 100, 100), _at(view, 160, 140))
    assert len(_stored(page, ng["uuid"])) == 1 and len(dialogs) == 1

    _select(page, other["id"])
    _wait(page)
    _key(page.samples, Qt.Key.Key_O)
    _wait(page)
    _key(page.samples, Qt.Key.Key_Z, CTRL)
    _wait(page)
    label = ctx.label_history(other["uuid"])[0]
    assert (label["label"], label["defect_type"]) == ("NG", None) and len(dialogs) == 1
