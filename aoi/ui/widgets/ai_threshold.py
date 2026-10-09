"""The AI score threshold of a recipe (REQ-TRN-015; sketches recipe-editor.md, Thresholds tab, and
compare-decision-table.md, "AI threshold override"): the AI model's calibrated value, or an Engineer's override of it
for the board model.

While the tick is clear, the field shows the calibrated value greyed and the recipe keeps no threshold of its own, so
the value of whichever AI model is active applies, a newly trained one's included. Ticked, the field holds the
override, which the recipe keeps; clearing the tick restores the calibrated value. With none to name (no AI model
trained or active, or one whose calibration cannot be read), the tick's text stays short and the note says why, with
the error's code where there is one; the field shows once ticked, from 0, which is no override, as the engine reads
it, until a value is typed: never from a value it showed before, such as another board model's. Pages give the words,
as they do for `EmptyState`, and place the note, a row of its own as wide as their form, so its words never widen the
window; a page whose sketch gives the tick longer words places the tick naming a value in such a row too (Compare).
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QCheckBox, QDoubleSpinBox, QHBoxLayout, QLabel, QWidget

DECIMALS = 3


class AiThresholdField(QWidget):
    changed = Signal()  # the tick or the override changed
    ticking = Signal()  # ticked by hand: the page names the calibrated value again, which the field then starts from

    def __init__(self, texts: tuple[str, str], own_row: bool = False) -> None:
        """`texts`: the tick's text naming the calibrated value as {value}, and its text while there is none to name,
        short, beside the field. With `own_row`, the tick naming a value sits in `tick_row`, a row of its own that the
        page lays out under the field, for longer words (Compare's sketch's); with none to name it goes back beside
        the field, so that it and the note never both take a row (a panel that tall cut the note at 1600 x 900)."""
        super().__init__()
        self._texts = texts
        self._calibrated: float | None = None
        # The override as the recipe holds it, or the calibrated value ticked from: `override()` gives it back until the
        # field is first edited, and never after, even when typed back to what the field showed (review).
        self._kept: float | None = None
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.tick = QCheckBox()
        self.field = QDoubleSpinBox()
        self.field.setObjectName("calibrated")  # greyed while it shows the calibrated value (the tick clear)
        self.field.setDecimals(DECIMALS)
        self.field.setRange(0, 1e4)  # 0 is no override, as the engine reads it
        self.field.setSingleStep(0.1)
        layout.addWidget(self.tick)
        layout.addWidget(self.field, 1)
        self._own_row = own_row
        self.tick_row = QWidget(self)  # the tick's row of its own, which a page with `own_row` lays out under the field
        QHBoxLayout(self.tick_row).setContentsMargins(0, 0, 0, 0)
        self.tick_row.hide()
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
        if self._own_row:
            self._place_tick(in_row=value is not None)
        self.note.setText(why if value is None else "")
        self.note.setVisible(value is None and bool(why))
        self._show()

    def set_override(self, value: float | None) -> None:
        """The recipe's override, or None (or 0, which the engine reads the same) for none; the tick is set when there
        is one, and `override()` gives it back as the recipe holds it until it is edited, even where the field cannot
        show it (more decimals than 3, or outside 0 to 10000)."""
        kept = value or None
        if kept is not None:
            self.field.setValue(kept)  # which clears `_kept` while ticked: it is set after
        self._kept = kept
        self.tick.setChecked(kept is not None)
        self._show()

    def override(self) -> float | None:
        """The threshold the recipe keeps: while ticked, what the field holds, given back exactly as kept until it is
        edited; else None (the calibrated value applies), as for 0."""
        if not self.tick.isChecked():
            return None
        return self._kept if self._kept is not None else self.field.value() or None

    def _place_tick(self, in_row: bool) -> None:
        """The tick in `tick_row`, shown, or beside the field, the row hidden. Tab keeps the reading order, the tick
        under the field after it and beside it before it, and a tick that had the focus keeps it: a move to another
        parent takes it away, and it went to the next field, which the next keys then edited (review round 2b)."""
        beside, row = self.layout(), self.tick_row.layout()
        assert isinstance(beside, QHBoxLayout) and isinstance(row, QHBoxLayout)
        old, new = (beside, row) if in_row else (row, beside)
        moved, focused = new.indexOf(self.tick) < 0, self.tick.hasFocus()
        if moved:
            old.removeWidget(self.tick)
            new.insertWidget(0, self.tick)
            self.tick.show()
            QWidget.setTabOrder(*((self.field, self.tick) if in_row else (self.tick, self.field)))
        self.tick_row.setVisible(in_row)
        if moved and focused:
            self.tick.setFocus(Qt.FocusReason.OtherFocusReason)

    def _show(self) -> None:
        ticked = self.tick.isChecked()
        self.field.setEnabled(ticked)
        self.field.setVisible(ticked or self._calibrated is not None)
        if not ticked:  # clearing the tick restores the calibrated value, or none: never a value shown before
            self.field.setValue(0 if self._calibrated is None else self._calibrated)

    def _toggled(self, on: bool) -> None:
        if not on:
            self._kept = None  # the override goes with the tick
        elif self._kept is None:  # ticked by hand: from the calibrated value as it is now (an AI model trained since
            self.ticking.emit()  # the page was shown), kept exactly until the field is edited, or 0 with none named
            self.field.blockSignals(True)  # not an edit
            self.field.setValue(0 if self._calibrated is None else self._calibrated)
            self.field.blockSignals(False)
            self._kept = self._calibrated
        self._show()
        self.changed.emit()

    def _edited(self, _value: float) -> None:
        if self.tick.isChecked():  # the calibrated value shown while clear is not an edit
            self._kept = None  # the field holds the override from the first edit on (review)
            self.changed.emit()
