"""Training's label editor (REQ-TRN-003, the screen half; stage S33): the box editor of docs/sketches/training-labels.md
beside the samples table. It shows the selected image with its defect boxes; on an NG image boxes are drawn, each of
one of the 33 defect types, whose severity the defect table gives, and the selected box takes the type picked. Every
change is stored at once through `AppContext.set_boxes`, which keeps the boxes before in the image's history and
audits the change (S32); nothing here reads or writes the database itself. The image and its boxes are read, and each
change stored, on a pool thread (REQ-SET-021), one at a time: until it ends the editor takes no other change."""

from __future__ import annotations

import weakref
from collections.abc import Callable
from dataclasses import replace
from functools import partial
from pathlib import Path
from typing import TYPE_CHECKING, Any

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFocusEvent, QKeyEvent, QWheelEvent
from PySide6.QtWidgets import QComboBox, QFormLayout, QHBoxLayout, QLabel, QListWidget, QVBoxLayout, QWidget

from ...core.labels import DefectBox
from ...defects import BY_NAME, names
from ...errors import AoiError
from .. import theme
from ..widgets.box_editor import BoxEditor
from ..widgets.busy import BusyOverlay
from ..widgets.empty_state import EmptyState
from ..workers import Worker, start
from .base import Page, breakable, button, view_text

if TYPE_CHECKING:
    import numpy as np

    from ...core.services import AppContext


def _read(ctx: AppContext, uuid: str, path: str | None) -> tuple[np.ndarray | AoiError | None, list[DefectBox]]:
    """On a pool thread: a sample's stored boxes and, unless `path` is None, its image or the error that refused it."""
    boxes = [DefectBox(r["x"], r["y"], r["w"], r["h"], r["dct_type"]) for r in ctx.boxes(uuid)]
    if path is None:
        return None, boxes
    try:
        return ctx.load_image(path), boxes
    except AoiError as e:  # gone or damaged since it was imported: said under the heading, with no dialog per row
        return e, boxes


class TypeList(QComboBox):
    """The Type list: a type is picked by a choice in the open list, by mouse, finger or keys, or by Enter on the type
    shown, never by the arrow keys, a letter or the wheel, which only show one; the wheel turns it only while it has the
    focus. `left` says the focus went elsewhere, so the editor can show the type picked again."""

    picked = Signal()
    left = Signal()

    def __init__(self) -> None:
        super().__init__()
        self._showing = False  # a key or the wheel turning the type shown
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.activated.connect(self._chosen)

    def _chosen(self, _index: int) -> None:
        if not self._showing:
            self.picked.emit()

    def keyPressEvent(self, e: QKeyEvent) -> None:
        if e.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            self.picked.emit()
            return
        self._showing = True
        super().keyPressEvent(e)
        self._showing = False

    def wheelEvent(self, e: QWheelEvent) -> None:
        if not self.hasFocus():
            e.ignore()  # to the page under the pointer, as a wheel turned on the way to the image
            return
        self._showing = True
        super().wheelEvent(e)
        self._showing = False

    def focusOutEvent(self, e: QFocusEvent) -> None:
        super().focusOutEvent(e)
        if e.reason() != Qt.FocusReason.PopupFocusReason:  # the open list keeps it
            self.left.emit()


class LabelEditor(QWidget):
    """The selected image, its label and its defect boxes, beside Training's samples table (labels sketch)."""

    def __init__(self, page: Page, placeholder: str) -> None:
        super().__init__()
        self.owner = page  # its error dialog and coded lines
        self.ctx = page.ctx
        self.sample: dict[str, Any] | None = None
        lay = QVBoxLayout(self)
        lay.setContentsMargins(theme.SPACE_S, 0, theme.SPACE_S, 0)
        self.heading = QLabel()  # the sketch's "ng_003.png · NG · Top"; the file name may break after each _ and -
        self.heading.setWordWrap(True)
        lay.addWidget(self.heading)
        tools = QHBoxLayout()
        self.draw_btn = button(self.tr("Draw Box"), slot=self._toggle_draw)
        self.draw_btn.setCheckable(True)
        tools.addWidget(self.draw_btn)
        tools.addStretch(1)
        lay.addLayout(tools)
        form = QFormLayout()
        form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.DontWrapRows)  # a row that wrapped moved the image mid-drag
        self.type_box = TypeList()
        self.type_box.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        # 14 widths of X: the Type row then asks no more room than the image below it (IMAGE_MIN_W), so Training
        # fits a 1600 px window beside the import buttons; a longer name shows cut there, whole in the drop-down
        self.type_box.setMinimumContentsLength(14)
        for name in names():  # the 33 types, by category as the defect table lists them; never Anomaly (Q33)
            self.type_box.addItem(name, name)  # names from the classification table, English until it is translated
        self.severity = QLabel()  # read-only: the table's severity of the type
        form.addRow(self.tr("Type"), self.type_box)
        form.addRow(self.tr("Severity"), self.severity)
        lay.addLayout(form)
        self.view = BoxEditor(placeholder=placeholder)
        lay.addWidget(self.view, 1)
        lay.addWidget(QLabel(self.tr("Boxes")))
        self.box_list = QListWidget()
        self.box_list.setWordWrap(True)
        self.box_list.setFixedHeight(4 * theme.TARGET_H)
        self.box_list_empty = EmptyState(self.box_list)
        lay.addWidget(self.box_list)
        self.reading = BusyOverlay(self.view, self.tr("Opening the image…"))
        self.saving = BusyOverlay(self.view, self.tr("Storing the change…"))
        self._reading: Worker | None = None  # the read of the sample shown, the newest asked for
        self._writing: Worker | None = None  # the change being stored: one at a time
        self._image_of: str | None = None  # the sample whose image is shown, or was refused
        self._unread = ""  # the coded line of an image that cannot be read, under the heading
        self._kept: list[DefectBox] = []  # the boxes as stored, or being stored
        self._later: list[dict[str, Any] | None] = []  # a sample to show once the drag or the store in hand has ended
        self.view.settled.connect(self._settled)
        self.view.refused.connect(self._refuse)
        self.view.picked.connect(self._picked)
        self.view.edited.connect(self._store)
        self.box_list.currentRowChanged.connect(self.view.choose)
        self.type_box.currentIndexChanged.connect(self._shown_type)
        self.type_box.picked.connect(self._typed)
        self.type_box.left.connect(lambda: self._picked(self.view.chosen))  # the selected box's type, not one shown
        self._shown_type()
        self.show_sample(None)

    # --- what is shown -------------------------------------------------------------
    def show_sample(self, sample: dict[str, Any] | None) -> None:
        """Show `sample` (a row of `AppContext.samples`) with its label and stored boxes; None shows nothing. The image
        is read again only for another sample, and with the boxes on a pool thread; one that cannot be read is named
        with its code under the heading. A sample asked for mid-drag, or while a change is stored, is shown once that
        has ended."""
        if self.view.dragging() or self._writing is not None:
            self._later = [sample]
            return
        self._later.clear()
        again = sample is not None and sample["uuid"] == self._image_of
        chosen = self.view.chosen if again else -1
        self.sample = sample
        if self._reading is not None:
            self._reading.stop()  # a newer sample is asked for: what it reads is dropped
            self._reading = None
        if not again:  # nothing to draw on until the image is read
            self._image_of, self._unread, self._kept = None, "", []
            self.view.set_image(None)
            self.view.show_boxes([])
            self._fill_list([])
        self._heading()
        if sample is not None:
            path = None if again else str(sample["path"])
            done = partial(self._read_done, chosen=chosen)
            self._reading = self._run(self.reading, done, _read, self.ctx, sample["uuid"], path)
        self._sync()

    def _heading(self) -> None:
        """The sketch's "ng_003.png · NG · Top", breaking after each _ and - of the name; an unread image's code."""
        if self.sample is None:
            self.heading.clear()
            return
        line, name = self.tr("{file} · {label} · {view}"), breakable(Path(self.sample["path"]).name)
        said = line.format(file=name, label=self.sample["label"], view=view_text(self.sample["side"] or ""))
        self.heading.setText(said + self._unread)

    def _read_done(self, result: tuple[np.ndarray | AoiError | None, list[DefectBox]], chosen: int) -> None:
        """The sample's image, unless it was shown already, and its stored boxes, `chosen` selected."""
        image, self._kept = result
        if image is not None and self.sample is not None:
            self._image_of = self.sample["uuid"]
            self.view.set_image(None if isinstance(image, AoiError) else image)
            self._unread = f"\n{self.owner.coded_text(image)}" if isinstance(image, AoiError) else ""
            self._heading()
        self.view.show_boxes(self._kept if self.view._pix is not None else [], chosen)  # none over the placeholder
        self._fill_list(self._kept)

    def busy(self) -> bool:
        """The image or its boxes being read, or a change stored: no change on the image meanwhile."""
        return self._reading is not None or self._writing is not None

    def idle(self) -> bool:
        """Nothing read or stored, or waiting to be shown: what a test, or a screenshot, waits for."""
        return not self.busy() and not self._later

    def _settled(self) -> None:
        if self._later:
            self.show_sample(self._later.pop())

    def _sync(self) -> None:
        """Draw Box on an NG image shown, and Draw mode left on any other; no change on the image while it is read or
        a change is stored."""
        self.view.locked = self.busy()
        ng = self.sample is not None and self.sample["label"] == "NG" and self.view._pix is not None
        self.draw_btn.setEnabled(ng)
        if not ng and self.draw_btn.isChecked():
            self.draw_btn.setChecked(False)
            self._toggle_draw()

    def _fill_list(self, boxes: list[DefectBox] | None = None) -> None:
        """List `boxes`, by default those shown; with no picture shown the list and the Type list are off."""
        boxes = self.view.boxes if boxes is None else boxes
        for w in (self.box_list, self.type_box):
            w.setEnabled(self.view._pix is not None)
        self.box_list.blockSignals(True)
        self.box_list.clear()
        for n, b in enumerate(boxes):
            row = self.tr("{number} {type} ({severity}) {x},{y} {w}×{h} px")
            said = {"number": n + 1, "type": b.dct_type, "severity": BY_NAME[b.dct_type].severity}
            self.box_list.addItem(row.format(**said, x=b.x, y=b.y, w=b.w, h=b.h))
        self.box_list.setCurrentRow(self.view.chosen)
        self.box_list.blockSignals(False)
        if boxes or self.sample is None or self.view._pix is None and self._image_of is None:
            self.box_list_empty.hide()  # nothing yet, or the image still being read
        elif self.sample["label"] == "NG":
            hint = self.tr("Press Draw Box and drag around each defect, then pick its type.")
            self.box_list_empty.show_state(self.tr("No defect box yet"), hint)
        else:
            self.box_list_empty.show_state(self.tr("No defect boxes"), self.tr("Only an NG image takes defect boxes."))

    def _picked(self, chosen: int) -> None:
        """A box selected on the image: its row in the list, and its type in the Type field."""
        self.box_list.blockSignals(True)
        self.box_list.setCurrentRow(chosen)
        self.box_list.blockSignals(False)
        if chosen >= 0:
            self.type_box.setCurrentIndex(self.type_box.findData(self.view.boxes[chosen].dct_type))

    # --- what is changed -------------------------------------------------------------
    def _toggle_draw(self) -> None:
        self.view.set_draw_mode(self.draw_btn.isChecked())

    def _shown_type(self) -> None:
        """The type the Type list shows: its severity beside it, and the type of the next box drawn."""
        kind = str(self.type_box.currentData())
        self.severity.setText(BY_NAME[kind].severity)
        self.view.new_type = kind

    def _typed(self) -> None:
        """The type picked: the selected box's type, stored."""
        kind, chosen = str(self.type_box.currentData()), self.view.chosen
        if chosen >= 0 and self.view.boxes[chosen].dct_type != kind:
            self.view.boxes[chosen] = replace(self.view.boxes[chosen], dct_type=kind)
            self.view.redraw()
            self._store()

    def _store(self) -> None:
        """Store the boxes shown, on a pool thread; while another change is stored the boxes as stored come back."""
        if self.sample is None:
            return
        boxes = list(self.view.boxes)
        if self.write(lambda _uid: self._fill_list(), self.ctx.set_boxes, self.sample["uuid"], boxes):
            self._kept = boxes
        else:
            self.view.show_boxes(self._kept, self.view.chosen)
            self._picked(self.view.chosen)

    def write(self, done: Callable[[Any], None], fn: Callable[..., Any], *args: Any) -> bool:
        """Store a change, `fn(*args)`, on a pool thread, `done` getting what it returns here: one at a time, and none
        while the image is read. False, with a word in the status bar, while one is running. A refusal by the service,
        or any other error, is the coded dialog, and the boxes as stored are read again."""
        if self.busy():
            self._refuse()
            return False
        self._writing = self._run(self.saving, done, fn, *args)
        self._sync()
        return True

    def _refuse(self) -> None:
        self.owner.shell.status(self.tr("Wait until the image is open and the last change is stored"))

    def _run(self, over: BusyOverlay, done: Callable[[Any], None], fn: Callable[..., Any], *args: Any) -> Worker:
        """`fn(*args)` on a pool thread, `over` saying so after a second; `done` gets its result here unless a newer
        read replaced it. A change not stored, by an error or a Cancel, reads the boxes as stored again."""
        w = Worker(fn, *args)
        ref = weakref.ref(w)  # the slots hold the worker weakly, as Page.run_in_background's do (#132)
        got: list[bool] = []
        failed: list[BaseException] = []

        def result(value: Any) -> None:
            if ref() in (self._reading, self._writing):
                got.append(True)
                done(value)

        def finished() -> None:
            worker = ref()
            if worker is None or worker not in (self._reading, self._writing):
                return  # a read replaced by a newer one
            over.finish()
            lost = worker is self._writing and not got
            self._reading, self._writing = (None, self._writing) if worker is self._reading else (self._reading, None)
            if failed:
                self.owner.error(failed[0])
            self._sync()
            if self._later or lost:
                self.show_sample(self._later.pop() if self._later else self.sample)

        w.signals.result.connect(result)
        w.signals.error.connect(failed.append)
        w.signals.finished.connect(finished)
        over.watch(w.job)
        return start(w, self.ctx.jobs)
