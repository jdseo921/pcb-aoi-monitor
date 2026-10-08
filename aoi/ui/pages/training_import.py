"""Training's import sheet (REQ-TRN-001, stage S31; docs/sketches/training-import.md): inline above the samples table,
never a dialog over the file picker. It lists the files picked or found in a folder, each with its label, defect type
and view, set for all at once and per row, and after Import what became of each one."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from PySide6.QtCore import QAbstractItemModel, QModelIndex, QPersistentModelIndex, Qt
from PySide6.QtGui import QAction, QGuiApplication, QKeySequence
from PySide6.QtWidgets import (
    QAbstractItemView,
    QButtonGroup,
    QComboBox,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QRadioButton,
    QStyledItemDelegate,
    QStyleOptionViewItem,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ... import defects as taxonomy
from ...core.sample_import import ImportFile, ImportReport
from ...errors import AoiError
from ...hal import VIEWS
from .. import theme
from ..errors import phrase_text
from .base import QT_TRANSLATE_NOOP, button, cell_item, cell_text, make_table, size_class, view_text

FILE, LABEL, TYPE, VIEW, STATUS = range(5)
CODE_TITLE = QT_TRANSLATE_NOOP("Errors", "{code} {title}")  # the status of a file not imported, in the UI language
Choices = list[tuple[str, str]]


class _RowChoice(QStyledItemDelegate):
    """A row's own label, defect type or view, picked from a drop-down in its cell (the sketch's row override), opened
    by a tap on a selected cell, a double click, F2 or a typed key."""

    def __init__(self, sheet: ImportSheet) -> None:
        super().__init__(sheet)
        self.sheet = sheet

    def createEditor(
        self, parent: QWidget, option: QStyleOptionViewItem, index: QModelIndex | QPersistentModelIndex
    ) -> QWidget:
        box = QComboBox(parent)  # only a cell `_show_row` made editable gets here
        for text, key in self.sheet.choices(index.row(), index.column()):
            box.addItem(text, key)
        box.activated.connect(lambda _i: self.commitData.emit(box))  # a pick is kept at once: Enter is Import
        return box

    def setEditorData(self, editor: QWidget, index: QModelIndex | QPersistentModelIndex) -> None:
        if isinstance(editor, QComboBox):
            editor.setCurrentIndex(max(0, editor.findData(index.data(Qt.ItemDataRole.UserRole))))

    def setModelData(
        self, editor: QWidget, model: QAbstractItemModel, index: QModelIndex | QPersistentModelIndex
    ) -> None:
        if isinstance(editor, QComboBox):
            self.sheet.set_cell(index.row(), index.column(), editor.currentData())


class ImportSheet(QGroupBox):
    """The files of one import and what to import them as. `on_import(files)` runs the import (the page puts it on
    the pool) and `on_close()` closes the sheet; Import is off until every NG file has one of the 33 DCT types, and
    the files left without a label are listed as such (AOI-TRN-016)."""

    def __init__(self, on_import: Callable[[list[ImportFile]], None], on_close: Callable[[], None]) -> None:
        super().__init__()
        self._on_import, self._on_close = on_import, on_close
        self.files: list[ImportFile] = []
        self.done: set[int] = set()  # rows imported or skipped as already there: Import again sends the others
        self.running = False
        self._base: Path | None = None
        lay = QVBoxLayout(self)
        row = QHBoxLayout()
        row.addWidget(QLabel(self.tr("View")))
        self.views = self._choice_row(row, [(view_text(v), v) for v in VIEWS], lambda v: self._for_all(VIEW, v))
        row.addSpacing(theme.SPACE)
        row.addWidget(QLabel(self.tr("Label for all")))
        labels = [(self.tr("OK"), "OK"), (self.tr("NG"), "NG")]
        self.labels = self._choice_row(row, labels, lambda v: self._for_all(LABEL, v))
        row.addStretch(1)
        lay.addLayout(row)
        types = QHBoxLayout()
        types.addWidget(QLabel(self.tr("Defect type for NG files")))
        self.category = QComboBox()
        self.category.addItem(self.tr("All categories"), None)
        for category in taxonomy.categories():  # the classification table's names, English until it is translated
            self.category.addItem(category, category)
        self.category.currentIndexChanged.connect(self._fill_types)
        self.type_box = QComboBox()
        self.type_box.setPlaceholderText(self.tr("Pick one of the 33 defect types"))
        self.type_box.activated.connect(lambda _i: self._for_all(TYPE, self.type_box.currentData()))
        self._fill_types()
        types.addWidget(self.category)
        types.addWidget(self.type_box, 1)
        lay.addLayout(types)
        heads = [self.tr("File"), self.tr("Label"), self.tr("Defect type"), self.tr("View"), self.tr("Status")]
        self.table = make_table(heads, sortable=False)
        self.table.setItemDelegate(_RowChoice(self))
        edit = QAbstractItemView.EditTrigger
        self._edits = edit.SelectedClicked | edit.DoubleClicked | edit.EditKeyPressed | edit.AnyKeyPressed
        lay.addWidget(self.table, 1)
        foot = QHBoxLayout()
        self.note = QLabel()
        self.note.setWordWrap(True)
        foot.addWidget(self.note, 1)
        self.btn_copy = button(self.tr("Copy List"), slot=self.copy_list)
        self.btn_cancel = button(self.tr("Cancel"), slot=self._cancel)
        self.btn_import = button(self.tr("Import"), slot=self.start)
        for b in (self.btn_copy, self.btn_cancel, self.btn_import):
            foot.addWidget(b)
        lay.addLayout(foot)
        for key, slot in (
            (Qt.Key.Key_Escape, self._cancel),
            (Qt.Key.Key_Return, self.start),
            (Qt.Key.Key_Enter, self.start),
        ):
            act = QAction(self)
            act.setShortcut(QKeySequence(key))
            act.setShortcutContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)  # in the sheet, not over the page
            act.triggered.connect(slot)
            self.addAction(act)
        self.hide()

    def _choice_row(self, row: QHBoxLayout, choices: Choices, chosen: Callable[[str], None]) -> QButtonGroup:
        group = QButtonGroup(self)
        for i, (text, key) in enumerate(choices):
            b = size_class(QRadioButton(text), "T")
            b.setProperty("key", key)
            group.addButton(b, i)
            row.addWidget(b)
        group.buttonClicked.connect(lambda b: chosen(str(b.property("key"))))
        return group

    def _fill_types(self, _index: int = 0) -> None:
        category = self.category.currentData()
        self.type_box.clear()
        for d in taxonomy.DEFECT_TYPES:  # the 33: never "Unknown", never the AI model's "Anomaly"
            if category is None or d.category == category:
                self.type_box.addItem(self.tr("{type} · {severity}").format(type=d.name, severity=d.severity), d.name)
        self.type_box.setCurrentIndex(-1)  # a pick, not a category change, sets the NG rows' type

    # --- the files ------------------------------------------------------------------------------------------------
    def open_files(self, files: list[ImportFile], base: str | Path | None = None) -> None:
        """Show `files` (named relative to `base`, the folder they were found in, when given), with Top checked for
        all (decision Q32) and their labels and types as given."""
        self.files, self.done, self._base = files, set(), Path(base) if base else None
        self.setTitle(self.tr("Import {count} file(s)").format(count=len(files)))
        self.views.button(0).setChecked(True)
        labels = {f.label for f in files}
        self.labels.setExclusive(False)  # a mixed folder has no label for all until one is picked
        for b in self.labels.buttons():
            b.setChecked(labels == {b.property("key")})
        self.labels.setExclusive(True)
        self.type_box.setCurrentIndex(-1)
        self.table.setRowCount(len(files))
        for i in range(len(files)):
            self._show_row(i, None)
        self.btn_cancel.setText(self.tr("Cancel"))
        self.note.setText("")
        self._sync()
        self.show()
        self.table.setFocus()

    def choices(self, row: int, column: int) -> Choices:
        """What a row's cell offers: a file's name, its status and an OK file's type are not picked."""
        if column == LABEL:
            return [(self.tr("OK"), "OK"), (self.tr("NG"), "NG")]
        if column == TYPE and self.files[row].label == "NG":
            return [(d.name, d.name) for d in taxonomy.DEFECT_TYPES]
        return [(view_text(v), v) for v in VIEWS] if column == VIEW else []

    def set_cell(self, row: int, column: int, key: str) -> None:
        f = self.files[row]
        if column == LABEL:
            f.label, f.defect_type = key, f.defect_type if key == "NG" else None
        elif column == TYPE:
            f.defect_type = key
        elif column == VIEW:
            f.side = key
        self._show_row(row, None)
        self._sync()

    def _for_all(self, column: int, key: str) -> None:
        for i, f in enumerate(self.files):
            if i not in self.done and (column != TYPE or f.label == "NG"):
                self.set_cell(i, column, key)

    def _show_row(self, row: int, status: str | None) -> None:
        f = self.files[row]
        name = Path(f.path).relative_to(self._base).as_posix() if self._base else Path(f.path).name
        label = f.label or "—"
        kind = f.defect_type or (self.tr("pick a type") if f.label == "NG" else "—")
        if status is None:
            status = self.tr("ready")
            if f.label is None:
                status = self.tr("unsorted: pick a label")
            elif f.label == "NG" and not f.defect_type:
                status = self.tr("waiting: type needed")
        keys = (None, f.label, f.defect_type, f.side, None)
        picked = (False, True, f.label == "NG", True, False)  # the cells a row overrides, until its file is in
        flag = Qt.ItemFlag
        for column, text in enumerate((name, label, kind, view_text(f.side), status)):
            item = QTableWidgetItem(text)
            item.setData(Qt.ItemDataRole.UserRole, keys[column])
            item.setToolTip(f.path if column == FILE else "")
            editable = flag.ItemIsEditable if picked[column] and row not in self.done else flag.NoItemFlags
            item.setFlags(flag.ItemIsEnabled | flag.ItemIsSelectable | editable)
            self.table.setItem(row, column, item)

    def _sync(self) -> None:
        """Import is on while the sheet is idle and every NG file waiting to go in has its type (REQ-TRN-001)."""
        waiting = [i for i in range(len(self.files)) if i not in self.done]
        untyped = sum(self.files[i].label == "NG" and not self.files[i].defect_type for i in waiting)
        self.btn_import.setEnabled(not self.running and bool(waiting) and not untyped)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers if self.running else self._edits)
        for w in (*self.views.buttons(), *self.labels.buttons(), self.category, self.type_box):
            w.setEnabled(not self.running)  # the files are the pool's while they are imported
        if untyped and not self.running:
            self.note.setText(self.tr("{count} NG file(s) need a defect type").format(count=untyped))

    # --- the import -----------------------------------------------------------------------------------------------
    def start(self) -> None:
        if self.btn_import.isEnabled():
            self.running = True
            self._sync()
            self.note.setText(self.tr("Importing…"))
            self._on_import([f for i, f in enumerate(self.files) if i not in self.done])

    def show_report(self, report: ImportReport, coded: Callable[[AoiError], str]) -> None:
        """What became of each file sent: copied, skipped or refused with its code and title (the row's tooltip, and
        Copy List, hold what happened and what to do), stopped at, or not imported (`coded(e)` is that line)."""
        self.running = False
        rows = {id(f): i for i, f in enumerate(self.files)}
        for f in report.added:
            self.done.add(rows[id(f)])
            self._show_row(rows[id(f)], self.tr("copied"))
        problems = [*report.refused, *([report.stopped] if report.stopped else [])]
        for f, e in problems:
            i = rows[id(f)]
            if not isinstance(e, AoiError):  # as the error dialog shows a plain exception (AppContext.report_error)
                e = AoiError("AOI-SET-007", error_type=type(e).__name__, context="")
            if e.code == "AOI-TRN-015":
                self.done.add(i)
            self._show_row(i, phrase_text(CODE_TITLE.fill(code=e.code, title=e.title)))
            cell_item(self.table, i, STATUS).setToolTip(coded(e))
        for f in report.left:
            self._show_row(rows[id(f)], self.tr("not imported"))
        n = len(problems) + len(report.left)
        if report.refused and not (report.added or report.stopped or report.left):  # the sketch's empty state
            self.note.setText(self.tr("Nothing to import: every file was refused (see the list)."))
        else:
            said = self.tr("{added} imported · {count} not imported")
            self.note.setText(said.format(added=len(report.added), count=n))
        self.btn_cancel.setText(self.tr("Close"))
        self._sync()

    def copy_list(self) -> None:
        """Every row as a line, its file, label, type, view and status with what happened, to paste into a report."""
        lines = []
        for i in range(self.table.rowCount()):
            cells = [cell_text(self.table, i, c) for c in range(LABEL, STATUS + 1)]
            lines.append("\t".join([self.files[i].path, *cells, cell_item(self.table, i, STATUS).toolTip()]).rstrip())
        QGuiApplication.clipboard().setText("\n".join(lines))

    def _cancel(self) -> None:
        self._on_close()
