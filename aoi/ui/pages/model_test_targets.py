"""AI Model Test's Agreed Targets sheet (REQ-TST-008): the targets a customer agreed, before testing, for a board
model's validation (Customers & Launch, "Validation", step 2)."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from PySide6.QtCore import Qt
from PySide6.QtGui import QAction, QKeySequence
from PySide6.QtWidgets import (
    QDoubleSpinBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QSpinBox,
    QVBoxLayout,
)

from ...core import report
from .base import button


class TargetsSheet(QGroupBox):
    """The sheet under AI Model Test's targets line: the most missed Critical defects, the highest false call rate and
    the longest engine time per image the customer agreed, and with whom, then Cancel and Save Targets, a plain button,
    as the page keeps one blue primary. Each field offers only its range (`report.TARGET_LIMITS`); Save Targets is off
    until someone is named. Esc in the sheet or Cancel closes it; `confirm` saves what `values()` gives."""

    def __init__(self, confirm: Callable[[], None]) -> None:
        super().__init__()
        self.setTitle(self.tr("Agreed Targets"))
        self._confirm = confirm
        self.board_model: str | None = None  # the board model it is open for, which Save Targets records them for
        lay = QVBoxLayout(self)
        self.heading = QLabel()
        self.heading.setWordWrap(True)
        self.heading.setTextFormat(Qt.TextFormat.PlainText)  # a board model's name is never read as markup
        lay.addWidget(self.heading)
        limits = report.TARGET_LIMITS
        self.missed = QSpinBox()
        self.missed.setRange(*(int(x) for x in limits["missed_critical"]))
        self.false_calls = QDoubleSpinBox()  # in percent, as a customer states it; stored as a fraction
        self.false_calls.setDecimals(1)
        self.false_calls.setRange(*(x * 100 for x in limits["false_call_rate"]))
        self.false_calls.setSingleStep(0.5)
        self.seconds = QDoubleSpinBox()
        self.seconds.setDecimals(2)
        self.seconds.setRange(*limits["seconds_per_image"])
        self.seconds.setSingleStep(0.1)
        self.agreed_with = QLineEdit()
        self.agreed_with.setMaxLength(report.AGREED_WITH_CHARS)
        self.agreed_with.textChanged.connect(self._sync)
        self.agreed_with.returnPressed.connect(self.confirm)
        form = QFormLayout()
        form.addRow(self.tr("Missed Critical defects, at most"), self.missed)
        form.addRow(self.tr("False call rate, at most (%)"), self.false_calls)
        form.addRow(self.tr("Engine time per image, 95th percentile, at most (s)"), self.seconds)
        form.addRow(self.tr("Agreed with (customer, name and role)"), self.agreed_with)
        lay.addLayout(form)
        row = QHBoxLayout()
        row.addStretch(1)
        row.addWidget(button(self.tr("Cancel"), slot=self.close_sheet))
        self.btn_save = button(self.tr("Save Targets"), slot=self.confirm)
        row.addWidget(self.btn_save)
        lay.addLayout(row)
        esc = QAction(self, shortcut=QKeySequence(Qt.Key.Key_Escape))
        esc.setShortcutContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
        esc.triggered.connect(self.close_sheet)
        self.addAction(esc)
        self.hide()

    def open_for(self, board_model: str, in_force: dict[str, Any] | None) -> None:
        """Show the sheet for `board_model` with the targets in force (`AppContext.validation_targets`), or the proposed
        defaults while none were agreed; who agreed them is typed again for each change."""
        self.board_model = board_model
        heading = self.tr(
            "Targets for {board_model}, as agreed with the customer in writing before testing. The next run is held to"
            " them; a run made before keeps the targets it started with."
        )
        self.heading.setText(heading.format(board_model=board_model))
        values = report.target_values(in_force) or report.DEFAULT_TARGETS
        self.missed.setValue(int(values["missed_critical"]))
        self.false_calls.setValue(values["false_call_rate"] * 100)
        self.seconds.setValue(values["seconds_per_image"])
        self.agreed_with.clear()
        self.show()
        self.missed.setFocus()
        self._sync()

    def values(self) -> tuple[int, float, float, str]:
        """The sheet's targets as the service takes them: missed Critical defects, the false call rate as a fraction,
        seconds per image, and who agreed them."""
        rate = round(self.false_calls.value() / 100, 6)  # 7.5 % is 0.075, not 0.07500000000000001
        return self.missed.value(), rate, self.seconds.value(), self.agreed_with.text().strip()

    def _sync(self, *_: object) -> None:
        self.btn_save.setEnabled(bool(self.agreed_with.text().strip()))

    def confirm(self) -> None:
        if self.btn_save.isEnabled():
            self._confirm()

    def close_sheet(self) -> None:
        self.hide()
        self.agreed_with.clear()
