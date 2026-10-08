"""REQ-TRN-003, the screen half (stage S33): the label editor beside Training's samples table, where an Engineer draws
the defect boxes of an NG image and gives each one of the 33 types, whose severity the defect table fills in; every
change is stored through `AppContext.set_boxes`, which keeps the boxes before in the image's history (labels sketch,
docs/sketches/training-labels.md)."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any

from PySide6.QtCore import QItemSelectionModel, QPoint, QPointF, QRectF, Qt
from PySide6.QtGui import QWheelEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QGraphicsSimpleTextItem, QWidget
from pytestqt.qtbot import QtBot

from aoi import defects
from aoi.core.labels import DefectBox
from aoi.core.services import AppContext
from aoi.ui.pages.base import cell_text
from aoi.ui.pages.training import TrainingPage
from tests.test_req_done_in_v01 import BOARD, _window

if TYPE_CHECKING:
    from aoi.ui.widgets.box_editor import BoxEditor

LEFT, NONE = Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier
NO_BUTTON = Qt.MouseButton.NoButton


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
    qtbot.waitUntil(lambda: page.editor.sample is not None and page.editor.sample["uuid"] == sample["uuid"])
    QApplication.processEvents()  # laid out, as the page is before a hand can reach it: the heading on all its lines
    return page


def _stored(ctx: AppContext, uuid: str) -> list[tuple[int, int, int, int, str, str]]:
    return [(b["x"], b["y"], b["w"], b["h"], b["dct_type"], b["severity"]) for b in ctx.boxes(uuid)]


def _at(view: BoxEditor, x: float, y: float) -> QPoint:
    """The viewport point over image pixel (x, y)."""
    return view.mapFromScene(QPointF(x, y))


def _drag(view: BoxEditor, a: QPoint, b: QPoint) -> None:
    """A mouse drag on the image from `a` to `b`, through the point half way."""
    port = view.viewport()
    QTest.mousePress(port, LEFT, NONE, a)
    QTest.mouseMove(port, (a + b) / 2)
    QTest.mouseMove(port, b)
    QTest.mouseRelease(port, LEFT, NONE, b)


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
    on in Draw mode, for a finger that has no cursor to show it."""
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
    assert _stored(ctx, sample["uuid"]) == [box]
    assert len(ctx.label_history(sample["uuid"])) == rows + 1, "one drag, one label row"
    entry = ctx.audit_entries(action="label.set")[0]
    assert entry["object_uuid"] == sample["uuid"] and entry["after"]["boxes"][0]["dct_type"] == "Polarity Error"
    assert view.chosen == 0 and editor.box_list.currentRow() == 0 and not editor.box_list_empty.isVisibleTo(editor)
    assert editor.box_list.item(0).text() == f"1 Polarity Error (Critical) {x},{y} {box[2]}×{box[3]} px"
    labels = [i.text() for i in view.scene().items() if isinstance(i, QGraphicsSimpleTextItem) and i.isVisible()]
    assert "1 Polarity Error ◆ Critical" in labels

    _drag(view, _at(view, 600, 440), _at(view, 700, 560))  # past the bottom right corner of the 640 x 480 image
    edge = _stored(ctx, sample["uuid"])[1]
    assert (edge[0] + edge[2], edge[1] + edge[3]) == (640, 480)
    _drag(view, _at(view, 300, 300), _at(view, 301, 301))  # a slip of the hand, not a box
    assert len(_stored(ctx, sample["uuid"])) == 2
    view.roiDrawn.emit(QRectF(100.4, 120.6, 79.7, 80.2))  # a drag between pixels, as ImageView reports one
    shown, stored = view.boxes[2], _stored(ctx, sample["uuid"])[2]
    assert stored[:4] == (100, 121, 80, 80), "the corners rounded to whole pixels"
    assert all(type(v) is int for v in (shown.x, shown.y, shown.w, shown.h, *stored[:4])), "set_boxes gets no float"

    ok = ctx.samples(BOARD, "OK")[1]
    _select(page, ok["id"])
    qtbot.waitUntil(lambda: editor.sample is not None and editor.sample["uuid"] == ok["uuid"])
    assert not editor.draw_btn.isEnabled() and not editor.draw_btn.isChecked()
    assert editor.box_list_empty.heading.text() == "No defect boxes"
    _drag(view, _at(view, 100, 100), _at(view, 200, 200))
    assert ctx.boxes(ok["uuid"]) == [] and ctx.label_history(ok["uuid"])[0]["label"] == "OK"

    gone = ctx.samples(BOARD, "NG")[1]
    ctx.set_boxes(gone["uuid"], [DefectBox(50, 60, 70, 80, "Scratch")])
    Path(ctx.sample_path(gone["id"])).unlink()  # removed from the workspace since it was imported
    _select(page, gone["id"])
    qtbot.waitUntil(lambda: editor.sample is not None and editor.sample["uuid"] == gone["uuid"])
    assert "AOI-INSP-001" in editor.heading.text() and view._pix is None and not editor.draw_btn.isEnabled()
    assert view.boxes == [] and editor.box_list.count() == 1, "listed, not drawn over the placeholder"
    assert not editor.box_list.isEnabled() and not editor.type_box.isEnabled()


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
    assert types.currentData() == third and _stored(ctx, sample["uuid"])[0][4] == "Scratch", "shown, not picked"
    editor.box_list.setFocus()
    assert types.currentData() == "Scratch", "leaving the list puts back the type picked"
    for kind in defects.DEFECT_TYPES:
        types.setFocus()
        types.setCurrentIndex(types.findData(kind.name))  # as the arrow keys or a letter show it
        QTest.keyClick(types, Qt.Key.Key_Return)
        assert _stored(ctx, sample["uuid"]) == [(50, 60, 40, 30, kind.name, kind.severity)]
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
    assert _stored(ctx, sample["uuid"])[0][4:] == (above.name, above.severity) and not types.view().isVisible()
    rows = len(ctx.label_history(sample["uuid"]))
    editor.box_list.setCurrentRow(-1)
    assert view.chosen == -1
    types.setCurrentIndex(types.findData("Solder Ball"))
    QTest.keyClick(types, Qt.Key.Key_Return)
    assert len(ctx.label_history(sample["uuid"])) == rows and editor.severity.text() == "Minor"
    editor.draw_btn.click()
    _drag(view, _at(view, 300, 300), _at(view, 340, 330))
    assert [b[4:] for b in _stored(ctx, sample["uuid"])] == [(above.name, above.severity), ("Solder Ball", "Minor")]
