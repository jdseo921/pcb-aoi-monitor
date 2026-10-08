"""REQ-TRN-003, the screen half (stage S33): the label editor beside Training's samples table, where an Engineer draws,
selects, moves and resizes the defect boxes of an NG image, by mouse and by touch, and gives each one of the 33 types,
whose severity the defect table fills in; every change is stored through `AppContext.set_boxes`, which keeps the
boxes before in the image's history (labels sketch, docs/sketches/training-labels.md)."""

from __future__ import annotations

import threading
import time
from pathlib import Path
from typing import TYPE_CHECKING, Any

import cv2
import numpy as np
import pytest
from PySide6.QtCore import QEvent, QItemSelectionModel, QPoint, QPointF, QRectF, Qt
from PySide6.QtGui import QInputDevice, QPointingDevice, QWheelEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QGraphicsSimpleTextItem, QWidget
from pytestqt.qtbot import QtBot

from aoi import defects
from aoi.core.labels import DefectBox
from aoi.core.services import AppContext
from aoi.ui import theme
from aoi.ui.pages.base import cell_text
from aoi.ui.pages.training import TrainingPage
from tests.test_req_done_in_v01 import BOARD, _window

if TYPE_CHECKING:
    from aoi.ui.widgets.box_editor import BoxEditor

LEFT, NONE = Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier
NO_BUTTON = Qt.MouseButton.NoButton
FINGER = (QInputDevice.DeviceType.TouchScreen, QPointingDevice.PointerType.Finger, QInputDevice.Capability.Position)


def _page(qtbot: QtBot, ctx: AppContext) -> TrainingPage:
    win = _window(qtbot, ctx)
    win.navigate("Training")
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
    draws a box with Draw Box."""
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
