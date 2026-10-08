from __future__ import annotations

import weakref
from collections.abc import Callable, Sequence
from typing import TYPE_CHECKING, Any, TypeVar

from PySide6.QtCore import QCoreApplication, Qt
from PySide6.QtGui import QAction, QColor, QFont, QKeySequence
from PySide6.QtWidgets import (
    QAbstractItemView,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ...core.explain import Sentence
from ...core.services import AppContext
from .. import theme
from ..errors import show_error
from ..widgets.busy import BusyOverlay
from ..workers import Worker, start

if TYPE_CHECKING:
    from ..main_window import MainWindow


def QT_TRANSLATE_NOOP(context: str, text: str) -> str:
    """Mark `text` for pyside6-lupdate under `context` and hand it back unchanged. Qt's own QT_TRANSLATE_NOOP does the
    same but is typed as returning object, which a `title: str` class attribute refuses; lupdate finds the call by its
    name, so pages import this one."""
    return text


def sentence_text(s: Sentence) -> str:
    """A plain-word sentence of aoi/core/explain.py in the UI language: its template translated under the context
    "Explain", then filled in, so a translation can put the values in its own order (REQ-CMP-004)."""
    return QCoreApplication.translate("Explain", s.template).format(**s.values)


def page_text(text: str) -> str:
    """A page title or subtitle, marked in its class with QT_TRANSLATE_NOOP("Page", …), in the UI language."""
    return QCoreApplication.translate("Page", text)


def role_text(role: str) -> str:
    """A role name in the UI language; the English name stays the key the services check (REQ-USR-001)."""
    return QCoreApplication.translate("Role", role)


ROLES = (
    QT_TRANSLATE_NOOP("Role", "Operator"),
    QT_TRANSLATE_NOOP("Role", "Engineer"),
    QT_TRANSLATE_NOOP("Role", "Admin"),
)


def view_text(view: str) -> str:
    """A camera view name (`aoi.hal.VIEWS`) in the UI language; the English name stays the key the engine stores."""
    return QCoreApplication.translate("View", view)


VIEW_NAMES = (QT_TRANSLATE_NOOP("View", "Top"), QT_TRANSLATE_NOOP("View", "Side"), QT_TRANSLATE_NOOP("View", "Bottom"))


class Page(QWidget):
    """Base for every navigation page.

    Visible strings go through `self.tr()` in a page class and through `QCoreApplication.translate("Page", …)` here:
    `self.tr()` takes the most-derived class name as its context, so a string wrapped in this base class would be
    looked up under the subclass name and never found (REQ-SET-005). Titles are marked with
    `QT_TRANSLATE_NOOP("Page", …)` and translated by `page_text()` where they are shown; the English title stays
    the navigation key.
    """

    title: str = "Page"
    subtitle: str = ""
    roles: tuple[str, ...] = ROLES  # who may open it (spec 8)

    def __init__(self, ctx: AppContext, shell: MainWindow) -> None:
        super().__init__()
        self.setObjectName("page")
        self.ctx = ctx
        self.shell = shell  # MainWindow: navigation + shared state
        self._bg: Worker | None = None  # the page's background action, if one is running (REQ-SET-021)
        self._bg_busy: BusyOverlay | None = None  # the overlay that action covers, if any
        self.root = QVBoxLayout(self)
        self.root.setContentsMargins(20, 14, 20, 14)
        head = QHBoxLayout()
        t = QLabel(page_text(self.title))
        t.setObjectName("h1")
        head.addWidget(t)
        if self.subtitle:
            s = QLabel(self.subtitle_text())
            s.setObjectName("muted")
            head.addWidget(s, 1, Qt.AlignmentFlag.AlignBottom)
        else:
            head.addStretch(1)
        self.head = head
        self.root.addLayout(head)

    @property
    def board_model(self) -> str | None:
        return self.shell.board_model

    def subtitle_text(self) -> str:
        """The subtitle in the UI language; a page whose subtitle carries a value overrides this."""
        return page_text(self.subtitle)

    def no_board_model(self) -> tuple[str, str]:
        """Heading and sentence of the empty state every page shows until a board model is chosen (REQ-SET-019)."""
        return (
            QCoreApplication.translate("Page", "No board model yet"),
            QCoreApplication.translate("Page", "Pick a board model in the header first."),
        )

    # Hooks called by the shell.
    def on_show(self) -> None: ...
    def on_board_model_changed(self, name: str | None) -> None: ...

    def need_board_model(self) -> bool:
        if not self.board_model:
            QMessageBox.information(
                self,
                QCoreApplication.translate("Page", "Board model"),
                QCoreApplication.translate("Page", "Create or select a board model in the top bar first."),
            )
            return False
        return True

    def checked_board_model(self) -> str | None:
        """The board model after `need_board_model()`: its name, or None once the user has been told to pick one."""
        return self.board_model if self.need_board_model() else None

    def empty_step(self, sentence: str, target: str) -> tuple[str, str, Callable[[], object] | None]:
        """What to do and where, for an `EmptyState`: `sentence` with the link "Open <target> ›", or, for a role that
        cannot open that page, "Ask an Engineer to do this on <target>." with no link (REQ-SET-019)."""
        page = page_text(target)
        if self.ctx.role in self.shell.pages[target].roles:
            link = QCoreApplication.translate("Page", "Open {page} ›").format(page=page)
            return sentence, link, lambda: self.shell.navigate(target)
        ask = QCoreApplication.translate("Page", "Ask an Engineer to do this on {page}.").format(page=page)
        return ask, "", None

    def error(self, exc: BaseException) -> None:
        """Show an error the way the standard asks: its code, what happened and what to do (REQ-SET-019)."""
        show_error(self, self.ctx.report_error(exc, self.title))

    def action(self, text: str, key: str | QKeySequence.StandardKey, slot: Callable[[], object]) -> QAction:
        """An action a button and a key share (REQ-INSP-005): `action_button()` makes the button, and the key works
        wherever the focus is on this page, while this page is the one shown (a window shortcut owned by the page
        widget is active only while the widget is visible). Enabling or disabling the action does both at once."""
        a = QAction(text, self)
        a.setShortcut(QKeySequence(key))
        a.setShortcutContext(Qt.ShortcutContext.WindowShortcut)
        a.triggered.connect(slot)
        self.addAction(a)
        return a

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
            if self._bg_busy is not None and self._bg_busy is not busy:  # its finished slot will not finish it
                self._bg_busy.finish()
        w = self._bg = Worker(fn, *args, **kwargs)
        self._bg_busy = busy
        ref = weakref.ref(w)  # Qt keeps a slot as long as the worker's signals, so a slot that held the worker would
        # keep it, its job and the job's result for as long as the app runs (#132): the slots hold it weakly

        def current(slot: Callable[..., None]) -> Callable[..., None]:
            def guarded(*a: Any) -> None:
                worker = ref()
                if worker is not None and worker is self._bg and not worker.job.cancelled:
                    slot(*a)

            return guarded

        def finished() -> None:
            worker = ref()
            if worker is not None and worker is self._bg:
                self._bg = None
                if busy is not None:
                    busy.finish()
            if worker is not None and worker.job.cancelled and on_cancel is not None:
                on_cancel()

        w.signals.result.connect(current(on_result))
        w.signals.error.connect(current(self.error))
        w.signals.finished.connect(finished)
        if busy is not None:
            busy.watch(w.job)
        return start(w, self.ctx.jobs)


W = TypeVar("W", bound=QWidget)


def size_class(w: W, cls: str) -> W:
    """Mark a control with a sketch size class, "T" (operator target, 48 px) or "T+" (run control, 56 px), which the
    stylesheet sizes (`[sizeClass="T+"]`). `setMinimumHeight()` is undone when the stylesheet is applied, since
    QStyleSheetStyle sets the minimum from its own min-height rule: that is how the run controls shipped at 42 px."""
    w.setProperty("sizeClass", cls)  # not "size": that is QWidget's own QSize property
    return w


def button(text: str, kind: str = "", slot: Callable[..., object] | None = None) -> QPushButton:
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


def action_button(action: QAction, kind: str = "", show_key: bool = True) -> QPushButton:
    """A theme button that triggers `action`, enabled exactly when the action is, so that button and key do the same
    (REQ-INSP-005). The key is in the label ("Next Board  F8", the sketch's run controls) or, with `show_key` off, in
    the tooltip. `kind` as for `button()`."""
    key = action.shortcut().toString(QKeySequence.SequenceFormat.NativeText)
    label = QCoreApplication.translate("Page", "{action}  {key}").format(action=action.text(), key=key)
    b = button(label if show_key else action.text(), kind, action.trigger)
    if not show_key:
        b.setToolTip(key)
    b.setEnabled(action.isEnabled())
    action.enabledChanged.connect(b.setEnabled)
    return b


def make_table(headers: list[str], sortable: bool = True) -> QTableWidget:
    t = QTableWidget(0, len(headers))
    t.setHorizontalHeaderLabels(headers)
    t.setAlternatingRowColors(True)
    t.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
    t.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
    t.verticalHeader().setVisible(False)
    t.horizontalHeader().setStretchLastSection(True)
    t.setSortingEnabled(sortable)
    return t


def fill_table(
    t: QTableWidget,
    rows: Sequence[Sequence[object]],
    colors: Sequence[str | None] | None = None,
    tooltips: Sequence[str | None] | None = None,
) -> None:
    """Replace the rows of `t`; `colors[i]` and `tooltips[i]` go on every cell of row `i`.

    Sorting is off while the rows are set and comes back at the end, which sorts the table at once by the header's
    indicator; so anything a row carries is set here, never by a loop over the data after this returns (#111)."""
    sortable = t.isSortingEnabled()
    t.setSortingEnabled(False)
    t.setRowCount(len(rows))
    t.ensurePolished()  # the theme's font, so a coloured cell keeps its 14 pt
    bold = QFont(t.font())
    bold.setBold(True)  # white on green or red reads at 3:1 only as large text, and bold 14 pt counts (WCAG 1.4.3)
    for i, row in enumerate(rows):
        color = colors[i] if colors else None
        tip = tooltips[i] if tooltips else None
        for j, v in enumerate(row):
            it = QTableWidgetItem()
            if isinstance(v, float):
                it.setData(Qt.ItemDataRole.DisplayRole, round(v, 4))
            elif isinstance(v, int):
                it.setData(Qt.ItemDataRole.DisplayRole, v)
            else:
                it.setText("" if v is None else str(v))
            if color:
                it.setBackground(QColor(color))
                it.setForeground(QColor(theme.on_color(color)))
                it.setFont(bold)
            if tip:
                it.setToolTip(tip)
            t.setItem(i, j, it)
    t.resizeColumnsToContents()
    t.setSortingEnabled(sortable)


def cell_text(t: QTableWidget, row: int, column: int) -> str:
    """The text of a cell, or "" where the table holds no item there (`QTableWidget.item()` returns None then)."""
    item = t.item(row, column)
    return item.text() if item is not None else ""


def cell_item(t: QTableWidget, row: int, column: int) -> QTableWidgetItem:
    """The item of a cell `fill_table` filled, for its tooltip. `QTableWidget.item()` is typed as optional; a cell the
    table never filled is a bug, not a case, so it raises."""
    item = t.item(row, column)
    if item is None:
        raise LookupError(f"the table has no item at row {row}, column {column}")
    return item
