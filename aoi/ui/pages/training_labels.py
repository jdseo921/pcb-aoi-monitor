"""Training's label editor (REQ-TRN-003, the screen half; stage S33): the box editor of docs/sketches/training-labels.md
beside the samples table. It shows the selected image with its defect boxes; on an NG image boxes are drawn, each of
one of the 33 defect types, whose severity the defect table gives, and the selected box takes the type picked. Every
change is stored at once through `AppContext.set_boxes`, which keeps the boxes before in the image's history and
audits the change (S32); nothing here reads or writes the database itself."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from typing import Any

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFocusEvent, QKeyEvent, QWheelEvent
from PySide6.QtWidgets import QComboBox, QFormLayout, QHBoxLayout, QLabel, QListWidget, QVBoxLayout, QWidget

from ...core.labels import DefectBox
from ...defects import BY_NAME, names
from ...errors import AoiError
from .. import theme
from ..widgets.box_editor import BoxEditor
from ..widgets.empty_state import EmptyState
from .base import Page, breakable, button, view_text


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
        """Show `sample` (a row of `AppContext.samples`) with its stored boxes; None shows nothing. The picture is read
        again only for another sample; one that cannot be read is named with its code in the heading."""
        again = sample is not None and self.sample is not None and sample["uuid"] == self.sample["uuid"]
        self.sample = sample
        if sample is None:
            self.view.set_image(None)
            self.heading.clear()
        elif not again:
            line = self.tr("{file} · {label} · {view}")
            name = breakable(Path(sample["path"]).name)
            self.heading.setText(line.format(file=name, label=sample["label"], view=view_text(sample["side"] or "")))
            try:
                self.view.set_image(self.ctx.load_image(sample["path"]))
            except AoiError as e:  # gone or damaged since it was imported: said here, with no dialog per row
                self.view.set_image(None)
                self.heading.setText(f"{self.heading.text()}\n{self.owner.coded_text(e)}")
        ng = sample is not None and sample["label"] == "NG" and self.view._pix is not None
        self.draw_btn.setEnabled(ng)
        if not ng and self.draw_btn.isChecked():
            self.draw_btn.setChecked(False)
            self._toggle_draw()
        self._load(self.view.chosen if again else -1)

    def _load(self, chosen: int = -1) -> None:
        """The stored boxes of the sample shown, `chosen` selected."""
        rows = self.ctx.boxes(self.sample["uuid"]) if self.sample is not None else []
        boxes = [DefectBox(r["x"], r["y"], r["w"], r["h"], r["dct_type"]) for r in rows]
        self.view.show_boxes(boxes if self.view._pix is not None else [], chosen)  # none over the placeholder
        self._fill_list(boxes)

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
        if boxes or self.sample is None:
            self.box_list_empty.hide()
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
        """Store the boxes shown; a refusal, or any other error, is shown and the stored boxes come back."""
        if self.sample is None:
            return
        try:
            self.ctx.set_boxes(self.sample["uuid"], list(self.view.boxes))
        except Exception as e:  # the coded dialog (an AoiError's own code, else AOI-SET-007), and nothing unsaved shown
            self.owner.error(e)
            self._load()
            return
        self._fill_list()
