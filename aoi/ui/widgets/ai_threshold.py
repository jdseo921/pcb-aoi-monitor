"""The AI score threshold of a recipe (REQ-TRN-015; sketches recipe-editor.md, Thresholds tab, and
compare-decision-table.md, "AI threshold override"): the AI model's calibrated value, or an Engineer's override of it
for the board model.

While the tick is clear, the field shows the calibrated value greyed and the recipe keeps no threshold of its own, so
the value of whichever AI model is active applies, a newly trained one's included. Ticked, the field holds the
override, which the recipe keeps; clearing the tick restores the calibrated value. With none to name (no AI model
trained or active, or one whose calibration cannot be read), the tick's text stays short and the note says why, with
the error's code where there is one; the field shows once ticked. Pages give the words, as they do for `EmptyState`,
and place the note, a row of its own as wide as their form, so its words never widen the window.
"""

from __future__ import annotations

import math

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QCheckBox, QDoubleSpinBox, QHBoxLayout, QLabel, QWidget

DECIMALS = 3


class AiThresholdField(QWidget):
    changed = Signal()  # the tick or the override changed

    def __init__(self, texts: tuple[str, str]) -> None:
        """`texts`: the tick's text naming the calibrated value as {value}, and its text while there is none to name,
        both short, as the tick sits beside the field."""
        super().__init__()
        self._texts = texts
        self._calibrated: float | None = None
        self._kept: float | None = None  # the override as the recipe holds it, or the calibrated value ticked from
        self._kept_shown = math.nan  # what the field showed for `_kept`: `override()` gives `_kept` back until edited
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.tick = QCheckBox()
        self.field = QDoubleSpinBox()
        self.field.setObjectName("calibrated")  # greyed while it shows the calibrated value (the tick clear)
        self.field.setDecimals(DECIMALS)
        self.field.setRange(10**-DECIMALS, 1e4)  # above 0: the engine reads 0 as no override
        self.field.setSingleStep(0.1)
        layout.addWidget(self.tick)
        layout.addWidget(self.field, 1)
        self.note = QLabel(self)  # why no calibrated value is named; the page lays it out (see the module docstring)
        self.note.setObjectName("muted")
        self.note.setWordWrap(True)
        self.note.hide()
        self.tick.toggled.connect(self._toggled)
        self.field.valueChanged.connect(self._edited)
        self.show_calibrated(None)

    def show_calibrated(self, value: float | None, why: str = "") -> None:
        """The calibrated value that applies while the tick is clear, named by the tick and shown in the field; None
        while there is none to name, which `why` says in the note (no AI model trained or active, or the coded error
        of a calibration that cannot be read; nothing with no board model)."""
        self._calibrated = value
        self.tick.setText(self._texts[1] if value is None else self._texts[0].format(value=f"{value:.{DECIMALS}f}"))
        self.note.setText(why if value is None else "")
        self.note.setVisible(value is None and bool(why))
        self._show()

    def set_override(self, value: float | None) -> None:
        """The recipe's override, or None (or 0, which the engine reads the same) for none; the tick is set when there
        is one, and `override()` gives it back as the recipe holds it until it is edited, even where the field cannot
        show it (more decimals than 3, or outside 0.001 to 10000)."""
        self._kept = value or None
        if self._kept is not None:
            self.field.setValue(self._kept)
        self._kept_shown = self.field.value()
        self.tick.setChecked(self._kept is not None)
        self._show()

    def override(self) -> float | None:
        """The threshold the recipe keeps: while ticked, what the field holds, given back exactly as kept until it is
        edited; else None (the calibrated value applies)."""
        if not self.tick.isChecked():
            return None
        shown = self.field.value()
        return self._kept if self._kept is not None and shown == self._kept_shown else shown

    def _show(self) -> None:
        ticked = self.tick.isChecked()
        self.field.setEnabled(ticked)
        self.field.setVisible(ticked or self._calibrated is not None)
        if not ticked and self._calibrated is not None:
            self.field.setValue(self._calibrated)  # clearing the tick restores the calibrated value

    def _toggled(self, on: bool) -> None:
        if not on:
            self._kept = None  # the override goes with the tick
        elif self._kept is None:  # ticked by hand: from the calibrated value, kept exactly until the field is edited
            self._kept, self._kept_shown = self._calibrated, self.field.value()
        self._show()
        self.changed.emit()

    def _edited(self, _value: float) -> None:
        if self.tick.isChecked():  # the calibrated value shown while clear is not an edit
            self.changed.emit()
