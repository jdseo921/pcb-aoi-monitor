from __future__ import annotations

from collections.abc import Callable
from typing import Any

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QFont
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ...core.services import AppContext
from .. import theme
from ..errors import show_error
from ..widgets.busy import BusyOverlay
from ..workers import Worker, start


class Page(QWidget):
    """Base for every navigation page."""

    title = "Page"
    subtitle = ""
    roles = ("Operator", "Engineer", "Admin")  # who may open it (spec 8)

    def __init__(self, ctx: AppContext, shell):
        super().__init__()
        self.setObjectName("page")
        self.ctx = ctx
        self.shell = shell  # MainWindow: navigation + shared state
        self._bg: Worker | None = None  # the page's background action, if one is running (REQ-SET-021)
        self.root = QVBoxLayout(self)
        self.root.setContentsMargins(20, 14, 20, 14)
        head = QHBoxLayout()
        t = QLabel(self.title)
        t.setObjectName("h1")
        head.addWidget(t)
        if self.subtitle:
            s = QLabel(self.subtitle)
            s.setObjectName("muted")
            head.addWidget(s, 1, Qt.AlignBottom)
        else:
            head.addStretch(1)
        self.head = head
        self.root.addLayout(head)

    @property
    def board_model(self) -> str | None:
        return self.shell.board_model

    # Hooks called by the shell.
    def on_show(self) -> None: ...
    def on_board_model_changed(self, name: str | None) -> None: ...

    def need_board_model(self) -> bool:
        if not self.board_model:
            QMessageBox.information(self, "Board model", "Create or select a board model in the top bar first.")
            return False
        return True

    def empty_step(self, sentence: str, target: str) -> tuple[str, str, Callable[[], None] | None]:
        """What to do and where, for an `EmptyState`: `sentence` with the link "Open <target> ›", or, for a role that
        cannot open that page, "Ask an Engineer to do this on <target>." with no link (REQ-SET-019)."""
        if self.ctx.role in self.shell.pages[target].roles:
            return sentence, f"Open {target} ›", lambda: self.shell.navigate(target)
        return f"Ask an Engineer to do this on {target}.", "", None

    def error(self, exc: BaseException) -> None:
        """Show an error the way the standard asks: its code, what happened and what to do (REQ-SET-019)."""
        show_error(self, self.ctx.report_error(exc, self.title))

    def run_in_background(
        self,
        fn: Callable[..., Any],
        *args: Any,
        on_result: Callable[[Any], None],
        busy: BusyOverlay | None = None,
        on_cancel: Callable[[], None] | None = None,
        **kwargs: Any,
    ) -> Worker:
        """Run `fn(*args, **kwargs)` on a pool thread (REQ-SET-021); `on_result` gets its return value on the UI thread
        and an error becomes the coded dialog. The newest call wins: an earlier run is stopped and its result dropped.
        `busy` covers where the result will appear; Cancel drops the result and calls `on_cancel` when the job stops."""
        if self._bg is not None:
            self._bg.stop()
        w = self._bg = Worker(fn, *args, **kwargs)

        def current(slot: Callable[..., None]) -> Callable[..., None]:
            def guarded(*a: Any) -> None:
                if w is self._bg and not w.job.cancelled:
                    slot(*a)

            return guarded

        def finished() -> None:
            if w is self._bg:
                self._bg = None
                if busy is not None:
                    busy.finish()
            if w.job.cancelled and on_cancel is not None:
                on_cancel()

        w.signals.result.connect(current(on_result))
        w.signals.error.connect(current(self.error))
        w.signals.finished.connect(finished)
        if busy is not None:
            busy.watch(w.job)
        return start(w, self.ctx.jobs)


def button(text: str, kind: str = "", slot=None) -> QPushButton:
    """A theme button. `kind` is "primary" (the one blue button on a page), "start", or the red "stop" and
    "danger" (removes data): red buttons sit last in their row and are never the default (REQ-SET-018)."""
    b = QPushButton(text.replace("&", "&&"))
    if kind:
        b.setObjectName(kind)
    if kind in ("stop", "danger"):
        b.setAutoDefault(False)  # Enter in a dialog never fires a red button
    if slot:
        b.clicked.connect(slot)
    return b


def make_table(headers: list[str], sortable: bool = True) -> QTableWidget:
    t = QTableWidget(0, len(headers))
    t.setHorizontalHeaderLabels(headers)
    t.setAlternatingRowColors(True)
    t.setSelectionBehavior(QTableWidget.SelectRows)
    t.setEditTriggers(QTableWidget.NoEditTriggers)
    t.verticalHeader().setVisible(False)
    t.horizontalHeader().setStretchLastSection(True)
    t.setSortingEnabled(sortable)
    return t


def fill_table(t: QTableWidget, rows: list[list], colors: list[str | None] | None = None) -> None:
    sortable = t.isSortingEnabled()
    t.setSortingEnabled(False)
    t.setRowCount(len(rows))
    t.ensurePolished()  # the theme's font, so a coloured cell keeps its 14 pt
    bold = QFont(t.font())
    bold.setBold(True)  # white on green or red reads at 3:1 only as large text, and bold 14 pt counts (WCAG 1.4.3)
    for i, row in enumerate(rows):
        for j, v in enumerate(row):
            it = QTableWidgetItem()
            if isinstance(v, float):
                it.setData(Qt.DisplayRole, round(v, 4))
            elif isinstance(v, int):
                it.setData(Qt.DisplayRole, v)
            else:
                it.setText("" if v is None else str(v))
            if colors and colors[i]:
                it.setBackground(QColor(colors[i]))
                it.setForeground(QColor(theme.on_color(colors[i])))
                it.setFont(bold)
            t.setItem(i, j, it)
    t.resizeColumnsToContents()
    t.setSortingEnabled(sortable)
