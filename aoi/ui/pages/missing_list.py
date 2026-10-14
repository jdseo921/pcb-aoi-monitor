"""What is missing (REQ-TRN-021; B3 of the 2026-10 business-readiness brief, F6; docs/sketches/what-is-missing.md): the
list Home and Training show for the board model in the header. It opens with the one sentence that says how many
images a board model needs (`datasets.needs`), then a line for each thing `AppContext.missing` counts, its count against
what it needs and the one button that fixes it. Validated or Trial picks the list: a Trial version needs no second-user
check and no agreement check (ADR 0020)."""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QButtonGroup,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QRadioButton,
    QVBoxLayout,
)

from ...core import datasets
from ...core.services import Missing, Need
from .. import theme
from ..errors import phrase_text
from ..widgets.flow import FlowLayout
from ..widgets.reflow import WrappedGroup
from .base import QT_TRANSLATE_NOOP, button, size_class, view_text

if TYPE_CHECKING:
    from .base import Page

NAMES = {  # each line's name, by `Need.key`
    "ok": QT_TRANSLATE_NOOP("MissingList", "OK images"),
    "ng": QT_TRANSLATE_NOOP("MissingList", "NG images"),
    "ng_boxed": QT_TRANSLATE_NOOP("MissingList", "NG images with every defect boxed"),
    "ng_checked": QT_TRANSLATE_NOOP("MissingList", "NG labels checked by a second user"),
    "ok_checked": QT_TRANSLATE_NOOP("MissingList", "OK labels checked by a second user (10 %)"),
    "calibration": QT_TRANSLATE_NOOP("MissingList", "Images labelled OK or NG for a calibration set"),
    "agreement": QT_TRANSLATE_NOOP("MissingList", "Agreement check that reached its targets"),
    "locked": QT_TRANSLATE_NOOP("MissingList", "Locked validation set"),
    "trained": QT_TRANSLATE_NOOP("MissingList", "Trained AI model"),
    "active": QT_TRANSLATE_NOOP("MissingList", "Active AI model"),
}
FIX_TEXT = {  # each fix's button, as the control that takes the step on Training names it
    "add_ok": QT_TRANSLATE_NOOP("MissingList", "Add OK Images…"),
    "add_ng": QT_TRANSLATE_NOOP("MissingList", "Add NG Images…"),
    "draw_boxes": QT_TRANSLATE_NOOP("MissingList", "Draw Boxes ›"),
    "show_unchecked": QT_TRANSLATE_NOOP("MissingList", "Show Unchecked ›"),
    "draw_ok_checks": QT_TRANSLATE_NOOP("MissingList", "Draw OK Labels to Check"),
    "agreement": QT_TRANSLATE_NOOP("MissingList", "Open Labeller Agreement ›"),
    "freeze": QT_TRANSLATE_NOOP("MissingList", "Freeze Dataset…"),
    "split": QT_TRANSLATE_NOOP("MissingList", "Split and Lock Validation Set…"),
    "train": QT_TRANSLATE_NOOP("MissingList", "Start Training"),
    "activate": QT_TRANSLATE_NOOP("MissingList", "Activate AI Model"),
}
CALLS = {  # the AppContext call each fix makes, whose role greys its button for a role that may not (REQ-USR-001)
    "add_ok": "import_samples",
    "add_ng": "import_samples",
    "draw_boxes": "set_boxes",
    "show_unchecked": "check_label",
    "draw_ok_checks": "draw_ok_checks",
    "agreement": "run_agreement_check",
    "freeze": "freeze_dataset",
    "split": "lock_validation_set",
    "train": "start_training",
    "activate": "activate_model",
}


class _Line:
    """One line's widgets: its mark, its name with its count, what it waits for under them, and its button."""

    def __init__(self, mark: QLabel, name: QLabel, first: QLabel, fix: QPushButton) -> None:
        self.mark, self.name, self.first, self.fix = mark, name, first, fix


class MissingList(WrappedGroup):
    """What is missing for the board model in the header: the sentence, Validated or Trial, and a line per need, ✓ once
    it is met, else its button, greyed while a line above it must be met first (named under the line, as a touch
    screen shows no tooltip) or for a role that may not take the step (its tooltip, and the status bar on a press).
    `fix(missing, need)` takes the step; Home opens Training first. The list is read again on every `show_for`."""

    def __init__(self, page: Page, fix: Callable[[Missing, Need], None]) -> None:
        super().__init__()
        self.setTitle(self.tr("What is missing"))
        self.page, self.ctx, self._fix = page, page.ctx, fix
        self.missing: Missing | None = None
        self.picked: bool | None = None  # Trial (True) or Validated (False) as the user picked it; None: as read
        self._board_model: str | None = None
        lay = QVBoxLayout(self)
        self.sentence = QLabel()  # how many images a board model needs, in the words every screen and document use
        self.sentence.setObjectName("muted")
        self.sentence.setWordWrap(True)
        lay.addWidget(self.sentence)
        kinds = FlowLayout(gap=theme.ROW_GAP)  # on two lines where the list is narrow, as in the presenter theme (A7)
        kinds.addWidget(QLabel(self.tr("Checks")))
        self.kinds = QButtonGroup(self)
        self.validated = size_class(QRadioButton(self.tr("Validated")), "T")
        self.trial = size_class(QRadioButton(self.tr("Trial: one person, no checks")), "T")
        for i, b in enumerate((self.validated, self.trial)):
            self.kinds.addButton(b, i)
            kinds.addWidget(b)
        self.kinds.idToggled.connect(self._picked)
        lay.addLayout(kinds)
        self.view_line = QLabel()  # the board model and view the counts are of
        self.view_line.setWordWrap(True)
        lay.addWidget(self.view_line)
        grid = QGridLayout()  # the count in the name's line, so a 1366 px presenter screen needs no scroll across (A7)
        grid.setHorizontalSpacing(theme.SPACE)
        grid.setColumnStretch(0, 1)
        self.lines: dict[str, _Line] = {}
        for row, key in enumerate(NAMES):
            mark, name, first = QLabel(), QLabel(), QLabel()
            name.setWordWrap(True)
            first.setObjectName("muted")
            first.setWordWrap(True)
            text = QVBoxLayout()  # the name, and under it the line it waits for
            text.setSpacing(0)
            text.addWidget(name)
            text.addWidget(first)
            cell = QHBoxLayout()  # the mark on the name's first line
            cell.setSpacing(theme.SPACE_S)
            cell.addWidget(mark, 0, Qt.AlignmentFlag.AlignTop)
            cell.addLayout(text, 1)
            centred = QVBoxLayout()  # centred on the row's button by stretches: an alignment cut a wrapped name short
            centred.addStretch(1)
            centred.addLayout(cell)
            centred.addStretch(1)
            fix_button = button("", slot=lambda _=False, k=key: self._take(k))
            grid.addLayout(centred, row, 0)
            grid.addWidget(fix_button, row, 1)
            self.lines[key] = _Line(mark, name, first, fix_button)
        lay.addLayout(grid)
        self.done_line = QLabel()  # nothing left: what that means for the kind picked
        self.done_line.setWordWrap(True)
        lay.addWidget(self.done_line)

    def show_for(self, board_model: str | None, trial: bool | None = None) -> None:
        """Read What is missing for `board_model` again, for the kind picked while it stays the same board model, or
        for Trial (`trial` True) or Validated (False), as a press on its button picks it."""
        if board_model != self._board_model:
            self.picked = None  # another board model: the list of its newest version's kind
        if trial is not None:
            self.picked = trial
        self._board_model = board_model
        if board_model is None:
            self.missing = None
            self.hide()
            return
        self.missing = m = self.ctx.missing(board_model, self.picked)
        self.sentence.setText(phrase_text(datasets.needs()))
        self.kinds.blockSignals(True)
        (self.trial if m.trial else self.validated).setChecked(True)
        self.kinds.blockSignals(False)
        line = self.tr("{board_model}, {view} view: {left} of {lines} still missing")
        if m.left and m.needs[-1].done:  # the AI model is there; the lines left are those of a next version
            line = self.tr(
                "{board_model}, {view} view: an AI model is active; {left} of {lines} still missing for a next version"
            )
        self.view_line.setText(
            line.format(board_model=board_model, view=view_text(m.view), left=m.left, lines=len(m.needs))
        )
        shown = {n.key: n for n in m.needs}
        for key, w in self.lines.items():
            need = shown.get(key)
            for widget in (w.mark, w.name, w.fix):
                widget.setVisible(need is not None)
            w.first.setVisible(need is not None and not need.done and need.after is not None)
            if need is None:
                continue
            w.mark.setText("✓" if need.done else "○")
            count = self.tr("{have} of {need}").format(have=need.have, need=need.need).replace(" ", "\u00a0")  # 1 line
            w.name.setText(self.tr("{name}: {count}").format(name=self.tr(NAMES[key]), count=count))
            w.fix.setText(self.tr(FIX_TEXT[need.fix]).replace("&", "&&"))
            first = self.tr("First: {line}").format(line=self.tr(NAMES[need.after])) if need.after else ""
            w.first.setText(first)
            self.page.gates.own_tip(w.fix, first)  # a greyed button says what comes first, as the line under it does
            self.page.gates.gate(w.fix, CALLS[need.fix], not need.done and need.after is None)
            w.fix.setVisible(not need.done)
        if m.left:
            self.done_line.hide()
        else:
            self.done_line.setText(
                self.tr(
                    "Nothing a Trial version needs is missing: {board_model} has an active AI model. Pick Validated to"
                    " see what a Validated version needs."
                ).format(board_model=board_model)
                if m.trial
                else self.tr("Nothing is missing: {board_model} has an active AI model.").format(
                    board_model=board_model
                )
            )
            self.done_line.show()
        self.show()

    def _picked(self, _id: int, on: bool) -> None:
        """Validated or Trial picked: the list of that kind, kept while the board model stays the same."""
        if on:
            self.picked = self.trial.isChecked()
            self.show_for(self._board_model)

    def _take(self, key: str) -> None:
        """A line's button: its step, for the list as it was last read."""
        need = next((n for n in self.missing.needs if n.key == key), None) if self.missing else None
        if self.missing is not None and need is not None and not need.done and need.after is None:
            self._fix(self.missing, need)
