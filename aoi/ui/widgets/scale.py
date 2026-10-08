"""Sizes at a board model's scale (REQ-RCP-006, S29): the minimum defect size field that the Recipe Editor and Compare
share, an area in px without a scale and a size in mm with one, and the Recipe Editor's Calibrate Scale… sheet."""

from __future__ import annotations

import math

from PySide6.QtCore import QPointF, Qt, Signal
from PySide6.QtGui import QAction, QKeySequence
from PySide6.QtWidgets import (
    QDoubleSpinBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSpinBox,
    QWidget,
)

from ...core.recipe import Recipe, disc_area, disc_width


class DefectSizeField(QWidget):
    """A recipe's minimum defect size: without a scale its area in px, as before S29; with one, its width in mm with the
    px it spans beside it (the sketch's "0.80 mm = 38 px"). `label` is its form row's label, which names the unit."""

    def __init__(self) -> None:
        super().__init__()
        self.px_per_mm: float | None = None
        self._own: tuple[int, float | None] = (40, None)  # the area and mm of the recipe show_recipe() put in the field
        self._shown = 0.0  # as this many mm: while the field shows them, it gives the recipe's own size back
        self.label, self.px = QLabel(), QLabel()
        self.px.setObjectName("muted")
        self.area = QSpinBox()
        self.area.setRange(1, 100000)
        self.mm = QDoubleSpinBox()
        self.mm.setRange(0.01, 1000)
        self.mm.setSingleStep(0.05)
        self.mm.valueChanged.connect(self._follow)
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        for w, stretch in ((self.area, 1), (self.mm, 1), (self.px, 0)):  # a spin box as wide as the form's others
            row.addWidget(w, stretch)
        self.show_recipe(Recipe(board_model=""), None)

    def show_recipe(self, recipe: Recipe, px_per_mm: float | None) -> None:
        """Show `recipe`'s size at `px_per_mm`: in mm its `min_defect_mm`, else the width of a round defect its area."""
        self.px_per_mm = s = px_per_mm
        self._own = (recipe.min_defect_area, recipe.min_defect_mm)
        self.area.setVisible(s is None)
        self.mm.setVisible(s is not None)
        self.px.setVisible(s is not None)
        self.label.setText(self.tr("Minimum defect area (px)") if s is None else self.tr("Minimum defect size (mm)"))
        self.area.setValue(recipe.min_defect_area)
        if s is not None:
            mm = recipe.min_defect_mm
            self.mm.setValue(disc_width(recipe.min_defect_area) / s if mm is None else mm)
        self._shown = self.mm.value()
        self._follow()

    def apply(self, recipe: Recipe) -> None:
        """Put the field's size into `recipe`: without a scale its area in px; with one, the recipe's own size while the
        field shows it, so a size in px stays in px and nothing changes unseen, else the size typed in mm and its area
        at the scale."""
        if self.px_per_mm is None:
            recipe.min_defect_area = self.area.value()
        else:
            recipe.min_defect_area, recipe.min_defect_mm = self._size()

    def _size(self) -> tuple[int, float | None]:
        """At the scale, the minimum defect area and size in mm the field gives (see `apply`)."""
        area, mm = self._own if self.mm.value() == self._shown else (0, self.mm.value())
        return (area if mm is None else disc_area(mm * (self.px_per_mm or 1.0))), mm

    def _follow(self) -> None:
        if (s := self.px_per_mm) is not None:  # the px the engine applies, not those of the 0.01 mm shown
            area, mm = self._size()
            self.px.setText(self.tr("= {px:.1f} px").format(px=disc_width(area) if mm is None else mm * s))


class CalibrationSheet(QGroupBox):
    """Calibrate Scale…, a sheet inline on the page (no dialog): the length between two points clicked on the Golden
    board, or typed, and the distance between them on the board in mm. Set Scale emits both; Cancel closes it."""

    submitted = Signal(float, float)  # length in px, distance in mm
    cancelled = Signal()

    def __init__(self) -> None:
        super().__init__(self.tr("Calibrate Scale"))
        self.points: list[QPointF] = []
        how = QLabel(
            self.tr(
                "Click two points on the Golden board a known distance apart, or type the length between them, then"
                " enter that distance on the board."
            )
        )
        how.setWordWrap(True)
        self.length, self.distance, self.result = QDoubleSpinBox(), QDoubleSpinBox(), QLabel()
        for spin, suffix in ((self.length, self.tr(" px")), (self.distance, self.tr(" mm"))):
            spin.setRange(0, 1e6)
            spin.setSuffix(suffix)
            spin.valueChanged.connect(self._follow)
        self.set_button, cancel = QPushButton(self.tr("Set Scale")), QPushButton(self.tr("Cancel"))
        self.set_button.clicked.connect(lambda: self.submitted.emit(self.length.value(), self.distance.value()))
        cancel.clicked.connect(self.cancelled.emit)
        esc = QKeySequence(Qt.Key.Key_Escape)  # in the sheet, and on the image the page adds it to: Cancel (S29 review)
        self.esc = QAction(self, shortcut=esc, shortcutContext=Qt.ShortcutContext.WidgetWithChildrenShortcut)
        self.esc.triggered.connect(self.cancelled.emit)
        self.addAction(self.esc)
        fields, buttons = QFormLayout(self), QHBoxLayout()  # one field a row: the sheet fits the image pane's width
        fields.addRow(how)
        fields.addRow(self.tr("Length"), self.length)
        fields.addRow(self.tr("Distance"), self.distance)
        fields.addRow(self.result)
        for w in (self.set_button, cancel):
            buttons.addWidget(w)
        buttons.addStretch(1)
        fields.addRow(buttons)
        self.start()

    def start(self) -> None:
        """Empty: no point, no length, no distance."""
        self.points = []
        self.length.setValue(0)
        self.distance.setValue(0)
        self._follow()

    def add_point(self, p: QPointF) -> None:
        """A point clicked on the Golden board: the second gives the length between the two; the first, and a third,
        which starts again, leave Length at 0 until the next."""
        self.points = [*self.points, p] if len(self.points) < 2 else [p]
        a, b = self.points[0], self.points[-1]
        self.length.setValue(math.hypot(b.x() - a.x(), b.y() - a.y()))

    def _follow(self) -> None:
        length, distance = self.length.value(), self.distance.value()
        self.set_button.setEnabled(length > 0 and distance > 0)
        scale = length / distance if distance > 0 else 0.0
        self.result.setText(self.tr("= {scale:.2f} px/mm").format(scale=scale) if scale > 0 else "")
