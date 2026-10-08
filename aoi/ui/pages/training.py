"""Dataset & Training page: upload sample boards, self-train, manage model versions."""

from __future__ import annotations

import json
from collections import Counter
from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING, Any

from PySide6.QtCore import QEvent, QItemSelectionModel, QObject, Qt
from PySide6.QtGui import QKeyEvent, QResizeEvent
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QComboBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QSizePolicy,
    QSpinBox,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from ...core.imaging import IMAGE_EXTS
from ...core.labels import DefectBox
from ...core.sample_import import ImportFile, ImportReport, folder_files
from ...core.services import AppContext
from ...errors import AoiError
from ...times import to_local
from .. import theme
from ..errors import phrase_text
from ..widgets.busy import BusyOverlay
from ..widgets.empty_state import EmptyState
from ..workers import Worker, start
from .base import (
    QT_TRANSLATE_NOOP,
    Page,
    action_button,
    button,
    cell_item,
    cell_text,
    fill_table,
    make_table,
    view_text,
)
from .training_import import ImportSheet
from .training_labels import LabelEditor, State

if TYPE_CHECKING:
    from ..main_window import MainWindow

SELECT_ROW = QItemSelectionModel.SelectionFlag.Select | QItemSelectionModel.SelectionFlag.Rows
CHOOSE_ROW = QItemSelectionModel.SelectionFlag.ClearAndSelect | QItemSelectionModel.SelectionFlag.Rows
NOT_TYPING = Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.AltModifier | Qt.KeyboardModifier.MetaModifier
EDIT_ON_KEY = QAbstractItemView.EditTrigger.AnyKeyPressed


def _each(ids: list[int], write: Callable[[int], None]) -> AoiError | None:
    """Write each sample but the reference, which stays as it is and is named once the others are written (AOI-TRN-007),
    so which rows change never depends on the order they were selected in (#168); any other refusal stops at the sample
    it names. Returns the refusal to show, if any."""
    refused: AoiError | None = None
    try:
        for i in ids:
            try:
                write(i)
            except AoiError as e:
                if e.code != "AOI-TRN-007":
                    raise
                refused = e
    except AoiError as e:
        refused = e
    return refused


def _sample_counts(model: dict[str, Any]) -> str:
    """The OK/NG sample counts training stored in an AI model registry row; empty for a row whose counts cannot be read
    (only a change by hand leaves one), so the Threshold cell beside it says why with its code (REQ-TRN-015)."""
    try:
        meta = json.loads(model["metrics"] or "{}")
    except (ValueError, TypeError):
        return ""
    counts = [meta.get(key, 0) for key in ("n_ok_train", "n_ok_val", "n_ng")] if isinstance(meta, dict) else []
    if len(counts) != 3 or not all(type(c) is int for c in counts):  # bool is an int, but not a count
        return ""
    return f"{counts[0] + counts[1]}/{counts[2]}"


class _Counts(QLabel):
    """The line over the samples table: the sample counts and the reference image's name. It never sets the page's
    minimum width, which the window takes from its widest page (#245): the name is cut at its end to the width the line
    gets, as the File column cuts it, and the tooltip then shows the whole line."""

    def __init__(self) -> None:
        super().__init__("")
        self.setObjectName("muted")
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self._line: Callable[[str], str] = lambda _name: ""
        self._name = ""

    def set_line(self, line: Callable[[str], str], name: str) -> None:
        """Show `line(name)`, `name` cut at its end when the whole line does not fit."""
        self._line, self._name = line, name
        self._fit()

    def resizeEvent(self, event: QResizeEvent) -> None:
        super().resizeEvent(event)
        self._fit()

    def _fit(self) -> None:
        fm, whole = self.fontMetrics(), self._line(self._name)
        room = self.contentsRect().width() - 2 * self.margin() - fm.horizontalAdvance(self._line(""))
        shown = self._line(fm.elidedText(self._name, Qt.TextElideMode.ElideRight, max(room, 0)))
        self.setText(shown)
        self.setToolTip(whole if shown != whole else "")


class TrainingPage(Page):
    title = QT_TRANSLATE_NOOP("Page", "Training")
    subtitle = QT_TRANSLATE_NOOP(
        "Page", "Upload good (OK) and defective (NG) boards; the AI model trains itself on them"
    )
    roles = ("Engineer", "Admin")

    def __init__(self, ctx: AppContext, shell: MainWindow) -> None:
        super().__init__(ctx, shell)
        self.worker: Worker | None = None

        split = QSplitter(Qt.Orientation.Horizontal)

        # Left: dataset ------------------------------------------------------------
        left = QWidget()
        ll = QVBoxLayout(left)
        ll.setContentsMargins(0, 0, 8, 0)
        up = QHBoxLayout()
        # the sketch's keys, each in its button's tooltip; verdict colours mean verdicts, not add buttons
        self.adds = [
            self.action(self.tr("Add OK Images…"), "Ctrl+O", self.add_ok),
            self.action(self.tr("Add NG Images…"), "Ctrl+N", self.add_ng),
            self.action(self.tr("Import Folder…"), "Ctrl+Shift+O", self.import_folder),
        ]
        self.btn_ok, self.btn_ng, self.btn_folder = (action_button(a, show_key=False) for a in self.adds)
        for b in (self.btn_ok, self.btn_ng, self.btn_folder):
            up.addWidget(b)
        ll.addLayout(up)
        self.counts = _Counts()
        ll.addWidget(self.counts)
        self.tip = QLabel(self.tr("Tip: 20+ OK images give a steadier threshold"))  # its own line: the name keeps room
        self.tip.setObjectName("muted")
        self.tip.setWordWrap(True)
        ll.addWidget(self.tip)
        self.sheet = ImportSheet(self._run_import, self._close_sheet)
        ll.addWidget(self.sheet, 2)
        self._listed: tuple[str, str] | None = None  # the status line naming the sheet's list, and once it is gone
        self._left = False  # the user who started the import that runs has signed out: its sheet closes as it ends
        self._by = ""  # the user who pressed Import: only they get the dialog of an error that stops it (#206)
        self.samples = make_table(
            [self.tr("ID"), self.tr("Label"), self.tr("Defect type"), self.tr("View"), self.tr("File")]
        )
        self.samples.itemSelectionChanged.connect(self._preview)
        self.samples_empty = EmptyState(self.samples)
        self.busy = BusyOverlay(self.samples, self.tr("Importing…"))
        ll.addWidget(self.samples, 1)
        marks = QHBoxLayout()  # the labels sketch's row, a key each, a list, a field or the import sheet gets first
        self.act_ok = self.action(self.tr("Mark OK"), "O", lambda: self._relabel("OK"))
        self.act_ng = self.action(self.tr("Mark NG"), "N", lambda: self._relabel("NG"))
        self.act_unsure = self.action(self.tr("Mark UNSURE"), "U", lambda: self._relabel("UNSURE"))
        for a in (self.act_ok, self.act_ng, self.act_unsure):
            marks.addWidget(action_button(a, show_key=False))
        self.act_next = self.action(self.tr("Next image"), "PgDown", lambda: self._step(1))  # keys only (sketch)
        self.act_previous = self.action(self.tr("Previous image"), "PgUp", lambda: self._step(-1))
        ll.addLayout(marks)
        shell.installEventFilter(self)  # the keys typed in a drop-down list or the import sheet reach the window last
        act = QHBoxLayout()
        act.addWidget(button(self.tr("Set Reference"), slot=self._set_reference))
        act.addWidget(button(self.tr("Remove"), "danger", self._remove))  # red, last in its row, never the default
        ll.addLayout(act)
        split.addWidget(left)

        # Middle: the label editor, the selected image with its defect boxes (REQ-TRN-003) ----------------------
        self.shown: dict[int, dict[str, Any]] = {}  # the samples in the table, by id
        self.editor = LabelEditor(self, self.tr("Select a sample to preview"))
        self.editor.undone.connect(self._show_samples)
        self.editor.stored.connect(self._show_types)
        split.addWidget(self.editor)

        # Right: training + model versions ----------------------------------------
        right = QWidget()
        rl = QVBoxLayout(right)
        rl.setContentsMargins(8, 0, 0, 0)
        g = QGroupBox(self.tr("Self-training"))
        f = QFormLayout(g)
        self.epochs = QSpinBox()
        self.epochs.setRange(5, 1000)
        self.epochs.setValue(ctx.settings.default_epochs)
        self.input_size = QComboBox()
        self.input_size.addItems(["128", "256", "384", "512"])
        self.input_size.setCurrentText(str(ctx.settings.image_size))
        self._defaults = (ctx.settings.default_epochs, ctx.settings.image_size)  # the saved defaults the boxes show
        f.addRow(self.tr("Epochs"), self.epochs)
        f.addRow(self.tr("Network input size"), self.input_size)
        self.device_label = QLabel(ctx.device.upper())  # the device in use, read again on show (#201)
        f.addRow(self.tr("Device"), self.device_label)
        row = QHBoxLayout()
        self.btn_train = button(self.tr("Start Training"), "primary", self.train)
        self.btn_stop = button(self.tr("Stop"), slot=self.stop)
        self.btn_stop.setEnabled(False)
        row.addWidget(self.btn_train)
        row.addWidget(self.btn_stop)
        f.addRow(row)
        self.bar = QProgressBar()
        f.addRow(self.bar)
        rl.addWidget(g)
        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setMaximumHeight(170)
        rl.addWidget(self.log)
        rl.addWidget(QLabel(self.tr("AI model versions")))
        self.models = make_table(
            [
                self.tr("ID"),
                self.tr("Version"),
                self.tr("Created"),
                self.tr("Threshold"),
                self.tr("OK/NG"),
                self.tr("Active"),
            ]
        )
        self.models_empty = EmptyState(self.models)
        rl.addWidget(self.models, 1)
        self.models_note = QLabel()  # each AOI-TRN-012 row's coded line, which a tooltip gives no touch or key to read
        self.models_note.setObjectName("muted")
        self.models_note.setWordWrap(True)
        self.models_note.hide()
        rl.addWidget(self.models_note)
        mrow = QHBoxLayout()
        mrow.addWidget(button(self.tr("Activate Selected"), slot=self.activate))
        mrow.addWidget(button(self.tr("Export AI Model…"), slot=self.export_model))
        rl.addLayout(mrow)
        split.addWidget(right)
        # the table as wide as its reference line needs at 1920 px, the editor next; with S31's import sheet open the
        # table takes 750 px and the training panel keeps 418 px, its buttons whole
        split.setSizes([650, 500, 460])
        self.root.addWidget(split, 1)

    # --- dataset ----------------------------------------------------------------
    def _pick(self) -> list[str]:
        exts = " ".join(f"*{e}" for e in sorted(IMAGE_EXTS))
        files, _ = QFileDialog.getOpenFileNames(
            self, self.tr("Select PCB images"), "", self.tr("Images ({extensions})").format(extensions=exts)
        )
        return files

    def add_ok(self) -> None:
        if (bm := self.checked_board_model()) and (files := self._pick()):
            self._open_sheet(bm, [ImportFile(f, "OK") for f in files])

    def add_ng(self) -> None:
        if (bm := self.checked_board_model()) and (files := self._pick()):
            self._open_sheet(bm, [ImportFile(f, "NG") for f in files])

    def import_folder(self) -> None:
        """Folder with ok/ and ng/ sub-folders (ng/<defect type>/ pre-fills the type)."""
        if self._bg is not None or not self.need_board_model():  # one import at a time (#194)
            return
        d = QFileDialog.getExistingDirectory(self, self.tr("Folder containing ok/ and ng/ sub-folders"))
        if d:
            self.import_from(d)

    def import_from(self, folder: str) -> None:
        """Open the import sheet on the images under `folder`, each labelled by its sub-folders (REQ-TRN-001); a folder
        with none opens no sheet, and the status line says so."""
        if (bm := self.checked_board_model()) is None:
            return
        if not (files := folder_files(folder)):
            none = self.tr("No images in {folder} or its sub-folders: nothing to import")
            self.shell.status(none.format(folder=folder))
            return
        self._open_sheet(bm, files, folder)

    def _open_sheet(self, board_model: str, files: list[ImportFile], base: str | None = None) -> None:
        """The import sheet in place of nothing: never a dialog over the file picker (sketch), for the board model in
        the header. While it is open, its Import is the page's one blue primary and Start Training a plain button, the
        other way round while its line names its board model under another in the header (`_follow_header`). One
        import at a time (#194)."""
        if self._bg is not None:
            return
        self._unlist()
        self.sheet.open_files(board_model, files, base)
        self._primary(self.sheet.btn_import, self.btn_train)

    def _close_sheet(self) -> None:
        """Cancel or Esc: stops an import that runs, keeping what went in (#194); else closes the sheet."""
        if self.sheet.running:
            self.busy.cancel_button.click()
            return
        self.sheet.hide()
        self._unlist()
        self._left = False
        self._primary(self.btn_train, self.sheet.btn_import)

    def on_user_changed(self) -> None:
        """A sign-in closes the sheet the user before left, so the next user never imports its files (review); an
        import that runs goes on as the user who started it (#177), and its sheet closes once that import ends."""
        self.editor.forget()  # and the next user never undoes what the user before changed
        if self.sheet.running:
            self._left = True
        else:
            self._close_sheet()

    def _close_if_left(self) -> None:
        if self._left:
            self._close_sheet()

    def _unlist(self) -> None:
        """The status line says "(see the list)" only while the sheet shows that list."""
        if self._listed is not None and self.shell.statusBar().currentMessage() == self._listed[0]:
            self.shell.status(self._listed[1])
        self._listed = None

    def _primary(self, blue: QPushButton, plain: QPushButton) -> None:
        for b, name in ((blue, "primary"), (plain, "")):
            b.setObjectName(name)
            b.style().unpolish(b)
            b.style().polish(b)

    def _run_import(self, files: list[ImportFile]) -> None:
        """Import the sheet's files on a pool thread into the board model the sheet was opened for, never the header's
        (REQ-SET-021, REQ-TRN-001): one call per file, so Cancel keeps what went in (#194); the busy overlay shows
        progress, time left and Cancel after 10 s."""
        if self._bg is not None or (bm := self.sheet.board_model) is None:
            self._report(ImportReport(left=files))
            return
        self._by = self.ctx.user
        self.run_in_background(
            self.ctx.import_files, bm, files, with_progress=True,
            on_result=lambda report: self._imported(report, len(files)), busy=self.busy,
            on_cancel=lambda report: self._import_stopped(report, files),
            on_error=lambda _e: self._import_failed(files),
        )  # fmt: skip

    def _stop_error(self, report: ImportReport, total: int) -> BaseException | None:
        """The error an import stopped at, as its dialog says it: a file that cannot be copied is AOI-TRN-009 (#178);
        any other error after a file went in AOI-TRN-010 with the count (#206); a copy refused as too long before any
        went in AOI-TRN-011 for all the files (#245); any other, as it is."""
        if report.stopped is None:
            return None
        f, e = report.stopped
        n: dict[str, object] = {"at": total - len(report.left), "total": total, "imported": len(report.added)}
        n["name"] = self.sheet.board_model  # the board model to pick in the header before Import again
        if isinstance(e, AoiError) and e.code == "AOI-TRN-008":  # this one file not copied
            reason, code = e.params["reason"], "AOI-TRN-009"
        elif n["imported"]:  # files went in before it: the message must say how many (#206)
            title = QT_TRANSLATE_NOOP("Errors", "{code} {title}")  # the title in the UI language (#198)
            reason = title.fill(code=e.code, title=e.title) if isinstance(e, AoiError) else type(e).__name__
            code = "AOI-TRN-010"
        elif isinstance(e, AoiError) and e.code == "AOI-TRN-011":  # none of the images went in, not 1
            return AoiError("AOI-TRN-011", e.detail, path=f.path, workspace=e.params["workspace"], count=total)
        else:  # nothing imported yet: the error is shown as it is
            return e
        stopped = AoiError(code, e.detail if isinstance(e, AoiError) else str(e), path=f.path, reason=reason, **n)
        stopped.__cause__ = e
        return stopped

    def _counts(self, report: ImportReport) -> dict[str, int]:
        ok = sum(f.label == "OK" for f in report.added)
        return {"ok": ok, "ng": len(report.added) - ok, "refused": len(report.refused)}

    def _report(self, report: ImportReport) -> None:
        """The sheet shows what became of each file and keeps its list; under another board model in the header (one
        chosen while the import ran) its Import is off and a line names its own until that one is back (REQ-SET-021)."""
        self.sheet.show_report(report, self.coded_text)
        self._follow_header(self.board_model)

    def _follow_header(self, name: str | None) -> None:
        """While the sheet's line names its board model, Import is off and Start Training the page's one blue primary;
        once that board model is back in the header, the sheet's Import is again (review)."""
        self.sheet.follow_header(name)
        if self.sheet.isHidden():
            return
        if self.sheet.away.isHidden():
            self._primary(self.sheet.btn_import, self.btn_train)
        else:
            self._primary(self.btn_train, self.sheet.btn_import)

    def _imported(self, report: ImportReport, total: int) -> None:
        """The status line names the board model the files went into and, while the sheet shows them, its list. The
        error the import stopped at opens its dialog for the user who pressed Import; for anyone signed in since, it is
        logged and alarmed with no dialog, as for an import cancelled (#206), and the status line points at the alarm
        list (review)."""
        self._report(report)
        n, bm = self._counts(report), self.sheet.board_model
        said = self.tr("Imported {ok} OK and {ng} NG images into {board_model}").format(board_model=bm, **n)
        if n["refused"]:
            listed = self.tr(
                "Imported {ok} OK and {ng} NG images into {board_model}; {refused} not imported (see the list)"
            )
            gone = self.tr("Imported {ok} OK and {ng} NG images into {board_model}; {refused} not imported")
            self._listed = listed.format(board_model=bm, **n), gone.format(board_model=bm, **n)
            said = self._listed[0]
        self.shell.status(said)
        self.refresh()  # the table shows what was imported before the dialog says how far it went
        self._close_if_left()
        if (stopped := self._stop_error(report, total)) is None or report.stopped is None:
            return
        if self.ctx.user == self._by:
            self.error(stopped)
            return
        self.ctx.report_error(stopped, self.title)  # logged and alarmed, as for an import cancelled (#206)
        msg = self.tr("Import into {board_model} stopped at {file}: see the alarm list")
        self.shell.status(msg.format(board_model=self.sheet.board_model, file=Path(report.stopped[0].path).name))

    def _import_stopped(self, report: ImportReport | None, files: list[ImportFile]) -> None:
        """Cancel stopped the import: the sheet, the table and the status line show what it imported, and a file it
        could not import is logged and alarmed with no dialog, since the user has left that import (#206). No newer
        import can stop it: one import runs at a time (#194)."""
        if report is None:  # stopped before it ran, or it raised (run_in_background reported that)
            self._import_failed(files)
            return
        if not report.left and report.stopped is None:  # Cancel after the last file: nothing was left out (#194)
            self._imported(report, len(files))
            return
        self.refresh()
        self._report(report)
        msg = self.tr("Import cancelled: {ok} OK and {ng} NG images imported into {board_model} before it stopped")
        self.shell.status(msg.format(board_model=self.sheet.board_model, **self._counts(report)))
        self._close_if_left()
        if (stopped := self._stop_error(report, len(files))) is not None:
            self.ctx.report_error(stopped, self.title)

    def _import_failed(self, files: list[ImportFile]) -> None:
        self._report(ImportReport(left=files))
        self.refresh()
        self._close_if_left()

    def _selected_ids(self) -> list[int]:
        return [int(cell_text(self.samples, i.row(), 0)) for i in self.samples.selectionModel().selectedRows()]

    def eventFilter(self, watched: QObject, e: QEvent) -> bool:
        """While this page is shown, a letter, digit or sign typed in a drop-down list, such as the Type list, in a
        table or list that a typed key edits, or anywhere in S31's import sheet goes there, never to the page's keys
        (O, N, U, D, Z, +, - and 0): the window takes its ShortcutOverride. A spin box or a text field, such as Epochs,
        needs none of this: its line edit accepts the ShortcutOverride of a key it types first."""
        if e.type() == QEvent.Type.ShortcutOverride and self.isVisible() and isinstance(e, QKeyEvent):
            typed = e.text().isprintable() and e.text() != "" and not e.modifiers() & NOT_TYPING
            if typed and self._takes_keys(QApplication.focusWidget()):
                e.accept()
                return True
        return super().eventFilter(watched, e)

    def _takes_keys(self, focus: QWidget | None) -> bool:
        """Whether `focus` takes the keys typed in it: a drop-down list; a table or list a typed key edits, such as the
        import sheet's, whose cell opens its drop-down on the key; and every control of the import sheet (review)."""
        if focus is None:
            return False
        edits = isinstance(focus, QAbstractItemView) and bool(focus.editTriggers() & EDIT_ON_KEY)
        return isinstance(focus, QComboBox) or edits or self.sheet.isAncestorOf(focus)

    def _relabel(self, label: str) -> None:
        """Mark OK, Mark NG, Mark UNSURE (O, N, U): each selected image not already so labelled, on a pool thread, with
        no question and no defect type, which the boxes give; the rows stay selected, and Undo puts back each image's
        label and boxes. Mark NG then puts the focus on the image, for its boxes (labels sketch). A label carried over
        with no labeller is labelled again, keeping its type, so that it can be checked (S32), which Undo leaves. The
        marks write through set_label, which takes UNSURE and an NG with no type until its boxes are drawn, where
        update_sample keeps the import's rule, OK or NG with one of the 33 types (S31)."""
        ctx = self.ctx
        before = [s for i in self._selected_ids() if (s := self.shown[i])["label"] != label or not s["labelled_by"]]
        if not before:
            return
        changed: list[State] = []

        def write(i: int) -> None:  # on a pool thread: the sample as it was, for Undo, then its new label
            s = next(s for s in before if s["id"] == i)
            boxes = [DefectBox(b["x"], b["y"], b["w"], b["h"], b["dct_type"]) for b in ctx.boxes(s["uuid"])]
            ctx.set_label(s["uuid"], label, s["defect_type"] if s["label"] == label else None)
            if s["label"] != label:
                changed.append((s["uuid"], s["label"], s["defect_type"], boxes))

        def done(refused: AoiError | None) -> None:
            if changed:
                self.editor.remember(changed)
            if refused is not None:
                self.error(refused)
            self.refresh()
            if label == "NG":
                self.editor.view.setFocus()

        self.editor.write(done, _each, [s["id"] for s in before], write)

    def _each_sample(self, ids: list[int], write: Callable[[int], None]) -> None:
        """Write each selected sample as `_each` does, then show the refusal, if any, and the table again."""
        refused = _each(ids, write)
        if refused is not None:
            self.error(refused)
        self.refresh()

    def _set_reference(self) -> None:
        ids = self._selected_ids()
        if ids and (bm := self.board_model):  # a selected sample implies a board model: the table is empty without one
            try:
                self.ctx.set_reference(bm, ids[0])
            except AoiError as e:  # an NG sample is never the reference (AOI-TRN-006)
                self.error(e)
                return
            self.shell.status(
                self.tr("Reference image set: inspections compare against it now, until training learns a Golden board")
            )

    def _remove(self) -> None:
        ids = self._selected_ids()
        if not ids:
            return
        question = self.tr("Remove {count} sample(s) from the dataset?").format(count=len(ids))
        yes, no = QMessageBox.StandardButton.Yes, QMessageBox.StandardButton.No
        if QMessageBox.question(self, self.tr("Remove"), question, yes | no, no) == yes:  # Enter keeps them (#182)
            self._each_sample(ids, self.ctx.delete_sample)

    def _show_samples(self, uuids: list[str]) -> None:
        """The table again, the rows of these samples alone selected, the first in view, and the topmost in the label
        editor: an Undo may change back an image other than the one shown, or its label."""
        self.refresh()
        self._select(lambda s: s["uuid"] in uuids, scroll=True)

    def _select(self, keep: Callable[[dict[str, Any]], bool], scroll: bool = False) -> None:
        """Select the rows whose sample `keep` holds for, the first in view with `scroll`; the editor follows once."""
        picks = self.samples.selectionModel()
        picks.blockSignals(True)
        picks.clearSelection()
        for row in range(self.samples.rowCount()):
            if keep(self.shown[int(cell_text(self.samples, row, 0))]):
                if scroll and not picks.hasSelection():
                    self.samples.scrollTo(self.samples.model().index(row, 0))
                picks.select(self.samples.model().index(row, 0), SELECT_ROW)
        picks.blockSignals(False)
        self.samples.viewport().update()
        self._preview()

    def _step(self, by: int) -> None:
        """PgDn, PgUp: the next or previous image of the table, as it is sorted, from the topmost selected row (the
        first row with none), alone selected and in view; the label editor follows. The ends stay where they are."""
        rows = sorted(i.row() for i in self.samples.selectionModel().selectedRows())
        if self.samples.rowCount():
            row = min(max(rows[0] + by, 0), self.samples.rowCount() - 1) if rows else 0
            index = self.samples.model().index(row, 0)
            self.samples.selectionModel().setCurrentIndex(index, CHOOSE_ROW)
            self.samples.scrollTo(index)

    def _preview(self) -> None:
        """The label editor on the selected sample, the topmost row when several are selected; none: nothing."""
        rows = sorted(i.row() for i in self.samples.selectionModel().selectedRows())
        self.editor.show_sample(self.shown.get(int(cell_text(self.samples, rows[0], 0))) if rows else None)

    def _types(self, kinds: list[str], given: str | None) -> str:
        """The Defect type column: the types of an image's boxes, each once with its count ("Solder Bridge ×2,
        Missing Component", the sketch's Defect types), else the type given at import, if any."""
        if not kinds:
            return given or ""
        each = self.tr("{type} ×{count}")
        return ", ".join(kind if n == 1 else each.format(type=kind, count=n) for kind, n in Counter(kinds).items())

    def _show_types(self, uuid: str, boxes: list[DefectBox]) -> None:
        """The boxes of a sample just stored: its row's Defect type, with no read of the database."""
        for row in range(self.samples.rowCount()):
            s = self.shown[int(cell_text(self.samples, row, 0))]
            if s["uuid"] == uuid:
                cell_item(self.samples, row, 2).setText(self._types([b.dct_type for b in boxes], s["defect_type"]))

    # --- training ---------------------------------------------------------------
    def train(self) -> None:
        if (bm := self.checked_board_model()) is None:
            return
        n_ok = len(self.ctx.samples(bm, "OK"))
        if n_ok < 2:
            self.error(AoiError("AOI-TRN-002", found=n_ok))
            return
        self.log.clear()
        self.bar.setRange(0, self.epochs.value())
        self.bar.setValue(0)
        self.btn_train.setEnabled(False)
        self.btn_stop.setEnabled(True)
        size = int(self.input_size.currentText())
        self.worker = Worker(self.ctx.train, bm, self.epochs.value(), size, with_progress=True)
        self.worker.signals.progress.connect(self._on_progress)
        self.worker.signals.result.connect(self._on_done)
        self.worker.signals.error.connect(self.error)
        self.worker.signals.finished.connect(self._finished)
        start(self.worker, self.ctx.jobs)

    def stop(self) -> None:
        if self.worker:
            self.worker.stop()

    def _on_progress(self, a: tuple[int, int, float, str]) -> None:
        ep, total, loss, msg = a
        if total > 1:
            self.bar.setMaximum(total)
            self.bar.setValue(ep)
        if msg:  # a phrase of the engine, shown in the UI language (#199)
            self.log.appendPlainText(phrase_text(msg))
        elif ep % 5 == 0 or ep == 1:
            self.log.appendPlainText(
                self.tr("epoch {epoch}/{total}  loss {loss:.4f}").format(epoch=ep, total=total, loss=loss)
            )

    def _on_done(self, meta: dict[str, Any]) -> None:
        saved = self.tr("Saved AI model {version} ({seconds} s). Golden board updated.")
        self.log.appendPlainText(saved.format(version=meta["version"], seconds=meta["train_seconds"]))
        self.shell.status(self.tr("AI model {version} trained and activated").format(version=meta["version"]))
        self.refresh()

    def _finished(self) -> None:
        if self.worker is not None and self.worker.job.cancelled and self.worker.job.result is None:  # Stop (#171)
            self.log.appendPlainText(self.tr("Stopped: no AI model was saved; the active AI model is unchanged."))
        self.btn_stop.setEnabled(False)
        self.worker = None
        self.device_label.setText(self.ctx.device.upper())  # a device saved during the run applies from the next one
        self.update_actions()

    def update_actions(self) -> None:
        """One import at a time, and no training while one runs (#194): a second import, also from the empty table's
        Import Folder… link, would stop the first, and training would learn from part of the images."""
        idle = self._bg is None
        for a in self.adds:
            a.setEnabled(idle)  # its button and its key
        self.samples_empty.link.setEnabled(idle)
        self.btn_train.setEnabled(idle and self.worker is None)

    # --- model registry ---------------------------------------------------------
    def activate(self) -> None:
        rows = self.models.selectionModel().selectedRows()
        if rows:
            self.ctx.activate_model(int(cell_text(self.models, rows[0].row(), 0)))
            self.refresh()

    def export_model(self) -> None:
        rows = self.models.selectionModel().selectedRows()
        if not rows:
            return
        mid = int(cell_text(self.models, rows[0].row(), 0))
        src = Path(self.ctx.model(mid)["path"])
        f, _ = QFileDialog.getSaveFileName(self, self.tr("Export AI model"), src.name, self.tr("AI model file (*.pt)"))
        if f:
            self.ctx.export_model(mid, f)

    def refresh(self) -> None:
        if not self.board_model:
            self.samples.setRowCount(0)
            self.models.setRowCount(0)
            self.models_note.hide()
            self.counts.set_line(lambda _name: "", "")
            self.tip.hide()
            self.samples_empty.show_state(*self.no_board_model())
            self.models_empty.hide()
            return
        s = self.ctx.samples(self.board_model)
        self.shown = {r["id"]: r for r in s}
        kept = set(self._selected_ids())
        self.samples.selectionModel().blockSignals(True)  # the editor follows once the rows are selected again
        fill_table(
            self.samples,
            [
                [
                    r["id"],
                    r["label"],
                    self._types(
                        [b["dct_type"] for b in self.ctx.boxes(r["uuid"])] if r["label"] == "NG" else [],
                        r["defect_type"],
                    ),
                    view_text(r["side"]) if r["side"] else "",
                    Path(r["path"]).name,
                ]
                for r in s
            ],
            [theme.NG_TINT if r["label"] == "NG" else None for r in s],  # UNSURE is not NG (REQ-TRN-002)
            [r["path"] for r in s],
        )
        self.samples.selectionModel().blockSignals(False)
        self._select(lambda r: r["id"] in kept)
        if s:
            self.samples_empty.hide()
        else:
            what = self.tr("Add at least 20 OK boards with Add OK Images… or Import Folder…")
            heading = self.tr("No samples for {board_model} yet").format(board_model=self.board_model)
            self.samples_empty.show_state(heading, what, self.tr("Import Folder…"), self.import_folder)
        n_ok, n_ng = (sum(r["label"] == label for r in s) for label in ("OK", "NG"))  # UNSURE counts as neither
        ref = self.ctx.reference_image(self.board_model)
        reference = Path(ref).name if ref else self.tr("none")
        counts = self.tr("{ok} OK · {ng} NG · reference: {reference}")
        self.counts.set_line(lambda name: counts.format(ok=n_ok, ng=n_ng, reference=name), reference)
        self.tip.setVisible(n_ok < 20)
        ms = self.ctx.models(self.board_model)
        rows, tips = [], []
        for m in ms:
            tip = None
            try:  # read as Recipe Editor and Compare read it (REQ-TRN-015)
                threshold: float | str = self.ctx.calibration_of(m)
            except AoiError as e:  # AOI-TRN-012: a registry row changed by hand
                threshold, tip = e.code, self.coded_text(e)
            active = "●" if m["active"] else ""
            rows.append([m["id"], m["version"], to_local(m["created_at"]), threshold, _sample_counts(m), active])
            tips.append(tip)
        fill_table(self.models, rows, tooltips=tips)
        # each row's AOI-TRN-012, with what happened and what to do, under the table
        said = [tip for tip in tips if tip]
        self.models_note.setText("\n".join(said))
        self.models_note.setVisible(bool(said))
        if ms:
            self.models_empty.hide()
        else:
            self.models_empty.show_state(
                self.tr("No AI model yet"), self.tr("Start Training once 20 OK boards are in.")
            )

    def on_board_model_changed(self, name: str | None) -> None:
        self.editor.show_sample(None)
        self.editor.forget()  # Undo never changes another board model's image
        if self.sheet.running or self.sheet.reported:  # an import goes on into its board model, and a list stays,
            self._follow_header(name)  # with Import off until that board model is back (REQ-SET-021)
        else:  # files picked for the board model shown before, none imported yet
            self._close_sheet()
        self.refresh()

    def on_show(self) -> None:
        """Read what Settings may have changed since the last show (#201): the device in use, kept as the run's own
        while a run goes on, and the default epochs and input size, set in the boxes only when the saved defaults
        changed, so a value the user chose for the next run stays otherwise."""
        if self.worker is None:
            self.device_label.setText(self.ctx.device.upper())
        defaults = (self.ctx.settings.default_epochs, self.ctx.settings.image_size)
        if defaults != self._defaults:
            self._defaults = defaults
            self.epochs.setValue(defaults[0])
            self.input_size.setCurrentText(str(defaults[1]))
        self.refresh()
