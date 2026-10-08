"""The defect boxes of an NG image, drawn on it (REQ-TRN-003; labels sketch, S33).

`BoxEditor` is an `ImageView` (zoom, pan, fit and its Draw mode) that holds the image's boxes, each a `DefectBox` in
image pixels.
"""

from __future__ import annotations

from PySide6.QtCore import QRectF, Signal
from PySide6.QtWidgets import QWidget

from ...core.labels import DefectBox
from ...defects import BY_NAME, names
from .. import theme
from .image_view import ImageView


class BoxEditor(ImageView):
    """An image with its defect boxes, the selected one yellow and the others green, each labelled with its number,
    type and severity. In Draw mode a drag adds a box of `new_type`, which ends in `edited`."""

    edited = Signal()  # the boxes changed: the page stores them
    picked = Signal(int)  # the selected box, -1 for none

    def __init__(self, parent: QWidget | None = None, placeholder: str = "") -> None:
        super().__init__(parent, placeholder)
        self.boxes: list[DefectBox] = []
        self.chosen = -1
        self.new_type = names()[0]
        self.roiDrawn.connect(self._drawn)

    def show_boxes(self, boxes: list[DefectBox], chosen: int = -1) -> None:
        """Show `boxes`, `chosen` selected (-1 or past the end: none)."""
        self.boxes = list(boxes)
        self.chosen = chosen if 0 <= chosen < len(self.boxes) else -1
        self.redraw()

    def choose(self, chosen: int) -> None:
        """Select box `chosen` (-1: none) and say so with `picked`."""
        chosen = chosen if 0 <= chosen < len(self.boxes) else -1
        if chosen != self.chosen:
            self.chosen = chosen
            self.redraw()
            self.picked.emit(chosen)

    def redraw(self) -> None:
        self.clear_overlays()
        for n, b in enumerate(self.boxes):
            label = self.tr("{number} {type} ◆ {severity}")
            label = label.format(number=n + 1, type=b.dct_type, severity=BY_NAME[b.dct_type].severity)
            self.add_box(b.x, b.y, b.w, b.h, theme.ROI_SELECTED if n == self.chosen else theme.ROI_COLOR, label)

    def _drawn(self, rect: QRectF) -> None:
        """A box dragged out in Draw mode, already cut to the image and at least 4 px a side: the next box, of
        `new_type`, selected."""
        x0, y0, x1, y1 = (round(v) for v in (rect.left(), rect.top(), rect.right(), rect.bottom()))
        self.boxes.append(DefectBox(x0, y0, x1 - x0, y1 - y0, self.new_type))
        self.choose(len(self.boxes) - 1)
        self.edited.emit()
