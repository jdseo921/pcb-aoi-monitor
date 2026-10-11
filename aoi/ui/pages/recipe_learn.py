"""Learn From Labelled Boards…'s sheet on the Recipe Editor (REQ-TRN-018, REQ-RCP-007, ADR 0017): the setting
`AppContext.learn_comparison` chose from the board model's labelled boards beside the recipe's own, each with its
counts on the boards held out of choosing, and Use Learned Values, which puts it in the fields for Save Recipe."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtGui import QAction, QFont, QKeySequence, QResizeEvent
from PySide6.QtWidgets import QGridLayout, QGroupBox, QHBoxLayout, QLabel, QVBoxLayout

from ...core import stats
from ..errors import phrase_text
from .base import button


class WholeLines(QLabel):
    """A word-wrapped line of the sheet that is never given less height than its text needs at the width it has. Its
    minimum height follows its width, so the grid and the column lay it out whole: on Windows the grid gave a count
    over its bound, three lines at 160 px, 73 px where it needed 76, which cut its last line (#389's CI). Its width
    never depends on its height, so one more layout pass settles it."""

    def __init__(self, text: str = "") -> None:
        super().__init__(text)
        self.setWordWrap(True)
        self._need = 0  # the height the text needs at the width it was last given

    def minimumSizeHint(self) -> QSize:
        hint = super().minimumSizeHint()
        return QSize(hint.width(), max(hint.height(), self._need))

    def resizeEvent(self, event: QResizeEvent) -> None:
        super().resizeEvent(event)
        self.fit()

    def fit(self) -> None:
        """Ask for the height the text needs at the width the line has now; after a resize, and after new text."""
        need = max(self.heightForWidth(self.width()), 0) if self.width() > 0 else 0
        if need != self._need:
            self._need = need
            self.updateGeometry()


class LearnSheet(QGroupBox):
    """What Learn From Labelled Boards… found, inline under the Recipe Editor's tabs: on which boards the setting was
    chosen and on which it was counted; a grid of the recipe's setting and the learned one, Pixel difference, Minimum
    defect area and fine alignment, then missed defects, false calls and OK boards called NG on the held-out boards,
    each a count over its 95 % upper bound, word-wrapped so that nothing is cut at any width; why any board was left
    out; Close (Esc) and Use Learned Values, which hands the result to `use` and closes the sheet. It changes nothing
    stored: Save Recipe stores the fields as a revision. The page shows it in the tabs' place, so that it has the
    column's height, and shows the tabs again on `closed`."""

    closed = Signal()

    def __init__(self, use: Callable[[dict[str, Any]], None]) -> None:
        super().__init__(self.tr("Learned From Labelled Boards"))
        self._use = use
        self.found: dict[str, Any] | None = None
        esc = QAction(self, shortcut=QKeySequence(Qt.Key.Key_Escape))
        esc.setShortcutContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
        esc.triggered.connect(self.close_sheet)
        self.addAction(esc)
        lay = QVBoxLayout(self)
        self.what = WholeLines()  # the boards chosen on and counted on
        lay.addWidget(self.what)
        self.grid = QGridLayout()
        self.grid.setColumnStretch(1, 1)
        self.grid.setColumnStretch(2, 1)
        self.cells: dict[tuple[int, int], WholeLines] = {}
        heads = ["", self.tr("This recipe"), self.tr("Learned")]
        names = [
            self.tr("Pixel difference"),
            self.tr("Minimum defect area (px)"),
            self.tr("Fine alignment"),
            self.tr("Missed defects"),
            self.tr("False calls (512 px squares)"),
            self.tr("OK boards called NG"),
        ]
        for c, text in enumerate(heads):
            head = self._cell(0, c, text)
            bold = QFont(head.font())
            bold.setBold(True)
            head.setFont(bold)
        for r, text in enumerate(names, 1):
            self._cell(r, 0, text)
            self._cell(r, 1, "")
            self._cell(r, 2, "")
        lay.addLayout(self.grid)
        self.left = WholeLines()  # why boards were left out, when any was
        self.left.setObjectName("muted")
        lay.addWidget(self.left)
        note = WholeLines(
            self.tr(
                "Counted on the held-out boards, which no value was chosen on. Use Learned Values puts them in the"
                " fields; Save Recipe stores them as a revision."
            )
        )
        note.setObjectName("muted")
        lay.addWidget(note)
        row = QHBoxLayout()
        row.addStretch(1)
        row.addWidget(button(self.tr("Close"), slot=self.close_sheet))
        self.btn_use = button(self.tr("Use Learned Values"), slot=self.use)
        row.addWidget(self.btn_use)
        lay.addLayout(row)
        lay.addStretch(1)
        self.hide()

    def _cell(self, r: int, c: int, text: str) -> WholeLines:
        label = WholeLines(text)
        label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
        self.grid.addWidget(label, r, c)
        self.cells[r, c] = label
        return label

    def text_at(self, r: int, c: int) -> str:
        return self.cells[r, c].text()

    def show_found(self, found: dict[str, Any]) -> None:
        """The sheet for `found`, as `AppContext.learn_comparison` returns it, with the focus on Use Learned Values."""
        self.found = found
        on, held = found["chosen_on"], found["counted_on"]
        chose = self.tr("Chosen on {boards} board(s): {ok} OK and {ng} NG with {boxes} defect box(es).").format(
            boards=on["ok"] + on["ng"], ok=on["ok"], ng=on["ng"], boxes=on["boxes"]
        )
        if held["by"] == "validation":
            counted = self.tr("Counted on {boards} other board(s) of the locked validation set: {ok} OK and {ng} NG.")
        else:
            counted = self.tr(
                "Counted on {boards} other board(s), a third held out with seed {seed}: {ok} OK and {ng} NG."
            )
        self.what.setText(
            f"{chose} "
            + counted.format(boards=held["ok"] + held["ng"], ok=held["ok"], ng=held["ng"], seed=held["seed"])
        )
        for c, key in ((1, "current"), (2, "chosen")):
            setting, rates = found[key], found["held_out"][key]
            self.cells[1, c].setText(str(setting["diff_threshold"]))
            self.cells[2, c].setText(str(setting["min_defect_area"]))
            self.cells[3, c].setText(self.tr("on") if setting["fine_alignment"] else self.tr("off"))
            for r, rate in ((4, "missed"), (5, "false_calls"), (6, "ok_called_ng")):
                self.cells[r, c].setText(self._rate(rates[rate]))
        self.left.setText(self._left_out(found["left_out"]))
        self.left.setVisible(bool(self.left.text()))
        for line in self.findChildren(WholeLines):  # new text at an unchanged width: no resize tells them
            line.fit()
        self.show()
        self.btn_use.setFocus()

    def _rate(self, rate: dict[str, Any]) -> str:
        """A count with its bound on the line under it: "0 of 12" over "95 % upper bound 22.1 %"."""
        count = phrase_text(stats.COUNT_ONLY.fill(n=rate["n"], of=rate["of"]))
        bound = stats.bound_text(rate)
        return count if bound is None else f"{count}\n{phrase_text(bound)}"

    def _left_out(self, left: dict[str, Any]) -> str:
        parts = []
        if left["no_boxes"]:
            parts.append(self.tr("{count} NG image(s) with no defect box").format(count=left["no_boxes"]))
        if left["other_view"]:
            parts.append(self.tr("{count} image(s) of another view").format(count=left["other_view"]))
        if left["unsure"]:
            parts.append(self.tr("{count} image(s) labelled UNSURE").format(count=left["unsure"]))
        if left["unreadable"]:
            parts.append(
                self.tr("{count} image(s) that could not be read, first {why}").format(
                    count=left["unreadable"], why=left["why"]
                )
            )
        return self.tr("Left out: {parts}.").format(parts="; ".join(parts)) if parts else ""

    def reason(self, found: dict[str, Any]) -> str:
        """The reason Save Recipe offers for a revision of the values `found` learned: where they were learned and what
        they counted on the held-out boards, so its audit entry carries the evidence."""
        rates, held = found["held_out"]["chosen"], found["counted_on"]
        said = self.tr(
            "Learned from {chosen} labelled board(s); on {held} held out: missed defects {missed}, false calls {false}."
        )
        return said.format(
            chosen=found["chosen_on"]["ok"] + found["chosen_on"]["ng"],
            held=held["ok"] + held["ng"],
            missed=phrase_text(stats.text(rates["missed"])),
            false=phrase_text(stats.text(rates["false_calls"])),
        )

    def use(self) -> None:
        if self.found is not None:
            self._use(self.found)
        self.close_sheet()

    def close_sheet(self) -> None:
        was_open = not self.isHidden()
        self.hide()
        self.found = None
        if was_open:
            self.closed.emit()
