"""Dataset & Training page: upload sample boards, self-train, manage model versions."""

from __future__ import annotations

import json
from collections import Counter
from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING, Any

from PySide6.QtCore import QEvent, QItemSelectionModel, QObject, Qt
from PySide6.QtGui import QAction, QKeyEvent, QKeySequence, QResizeEvent
from PySide6.QtWidgets import (
    QAbstractItemView,
    QAbstractSpinBox,
    QApplication,
    QComboBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QSizePolicy,
    QSpinBox,
    QSplitter,
    QStackedWidget,
    QTabBar,
    QVBoxLayout,
    QWidget,
)

from ...core.imaging import IMAGE_EXTS
from ...core.jobs import Job
from ...core.labels import DefectBox
from ...core.run_progress import RunProgress
from ...core.sample_import import ImportFile, ImportReport, folder_files
from ...core.services import AppContext
from ...defects import names
from ...errors import AoiError
from ...hal import VIEWS
from ...times import to_local
from .. import theme
from ..errors import phrase_text
from ..widgets.box_editor import ENTER
from ..widgets.busy import BusyOverlay
from ..widgets.empty_state import EmptyState
from ..workers import Worker, keep
from .base import (
    QT_TRANSLATE_NOOP,
    Page,
    action_button,
    button,
    cell_item,
    cell_text,
    fill_table,
    make_table,
    time_left_text,
    view_text,
)
from .training_agreement import AgreementPanel, BlindPanel
from .training_import import ImportSheet
from .training_labels import LabelEditor, State
from .training_versions import VersionsPanel, WorkingSetPanel

if TYPE_CHECKING:
    from ..main_window import MainWindow

SELECT_ROW = QItemSelectionModel.SelectionFlag.Select | QItemSelectionModel.SelectionFlag.Rows
CHOOSE_ROW = QItemSelectionModel.SelectionFlag.ClearAndSelect | QItemSelectionModel.SelectionFlag.Rows
NOT_TYPING = Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.AltModifier | Qt.KeyboardModifier.MetaModifier
EDIT_ON_KEY = QAbstractItemView.EditTrigger.AnyKeyPressed
FIELDS = (QAbstractSpinBox, QComboBox, QLineEdit)  # a field whose Enter is its own, never Check Label's
SHOWN = (  # the samples filter of the labels sketch: what each shows, by its key
    ("All", QT_TRANSLATE_NOOP("TrainingPage", "All")),
    ("OK", QT_TRANSLATE_NOOP("TrainingPage", "OK")),
    ("NG", QT_TRANSLATE_NOOP("TrainingPage", "NG")),
    ("UNSURE", QT_TRANSLATE_NOOP("TrainingPage", "UNSURE")),
    ("Unchecked", QT_TRANSLATE_NOOP("TrainingPage", "Unchecked")),
)


def _each(ids: list[int], write: Callable[[int], None]) -> Exception | None:
    """Write each sample but the reference, which stays as it is and is named once the others are written (AOI-TRN-007),
    so which rows change never depends on the order they were selected in (#168); any other refusal stops at the sample
    it names, and so does any other error, such as a database another program holds, the samples written before it
    staying written (review). Returns the refusal or error to show, if any."""
    refused: Exception | None = None
    try:
        for i in ids:
            try:
                write(i)
            except AoiError as e:
                if e.code != "AOI-TRN-007":
                    raise
                refused = e
    except Exception as e:  # what was written before it is shown, and a mark can be undone, whatever stopped it
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
        # the Samples tab: the page's keys are its actions (`action`), so none acts over the Datasets tab
        self.keys = QWidget()
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
        self.checks_line = QLabel()  # the second-user checks a freeze needs (REQ-TRN-004), every view together
        self.checks_line.setObjectName("muted")
        self.checks_line.setWordWrap(True)
        ll.addWidget(self.checks_line)
        self.tip = QLabel(self.tr("Training needs 20 OK images or more in a dataset version's training set"))
        self.tip.setObjectName("muted")
        self.tip.setWordWrap(True)
        ll.addWidget(self.tip)
        self.sheet = ImportSheet(self._run_import, self._close_sheet)
        ll.addWidget(self.sheet, 2)
        self._listed: tuple[str, str] | None = None  # the status line naming the sheet's list, and once it is gone
        self._left = False  # the user who started the import that runs has signed out: its sheet closes as it ends
        self._by = ""  # the user who pressed Import: only they get the dialog of an error that stops it (#206)
        show = QHBoxLayout()  # the labels sketch's filter, Unchecked the labels a freeze still needs checked
        show.addWidget(QLabel(self.tr("Show")))
        self.filter = QComboBox()
        for key, text in SHOWN:
            self.filter.addItem(self.tr(text), key)
        self.filter.currentIndexChanged.connect(self._fill_samples)
        show.addWidget(self.filter)
        show.addStretch(1)
        ll.addLayout(show)
        self.samples = make_table(
            [
                self.tr("ID"),
                self.tr("Label"),
                self.tr("Defect type"),
                self.tr("View"),
                self.tr("Labelled"),
                self.tr("Checked"),
                self.tr("File"),
            ]
        )
        self.samples.itemSelectionChanged.connect(self._preview)
        self.samples_empty = EmptyState(self.samples)
        self.busy = BusyOverlay(self.samples, self.tr("Importing…"))
        ll.addWidget(self.samples, 1)
        marks = QHBoxLayout()  # the labels sketch's row, a key each, a list, a field or the import sheet gets first
        self.act_ok = self.action(self.tr("Mark OK"), "O", lambda: self._relabel("OK"))
        self.act_ng = self.action(self.tr("Mark NG"), "N", lambda: self._relabel("NG"))
        self.act_unsure = self.action(self.tr("Mark UNSURE"), "U", lambda: self._relabel("UNSURE"))
        # Return, as the labels sketch has it: a field, a drop-down list or the image keeps its own (eventFilter)
        self.act_check = self.action(self.tr("Check Label"), "Return", self._check)
        for a in (self.act_ok, self.act_ng, self.act_unsure):
            marks.addWidget(action_button(a, show_key=False))
        self.btn_check = action_button(self.act_check, show_key=False)  # its tooltip says why it is off
        marks.addWidget(self.btn_check)
        self.act_next = self.action(self.tr("Next image"), "PgDown", lambda: self._step(1))  # keys only (sketch)
        self.act_previous = self.action(self.tr("Previous image"), "PgUp", lambda: self._step(-1))
        ll.addLayout(marks)
        shell.installEventFilter(self)  # the keys typed in a drop-down list or the import sheet reach the window last
        act = QHBoxLayout()
        act.addWidget(button(self.tr("Set Reference"), slot=self._set_reference))
        self.btn_draw = button(self.tr("Draw OK Labels to Check"), slot=self._draw)
        act.addWidget(self.btn_draw)
        act.addWidget(button(self.tr("Remove"), "danger", self._remove))  # red, last in its row, never the default
        ll.addLayout(act)
        split.addWidget(left)

        # Middle: the label editor, the selected image with its defect boxes (REQ-TRN-003) ----------------------
        self.shown: dict[int, dict[str, Any]] = {}  # the board model's samples, by id; the filter picks the table's
        self._boxes: dict[int, list[str]] = {}  # each NG sample's box types, by id
        self._statuses: list[dict[str, Any]] = []  # label_check_status of each view with an OK or NG label
        self._to_check: set[str] = set()  # the samples whose label a freeze still needs checked: the filter Unchecked
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
        self.dataset_version = QComboBox()  # the board model's frozen versions, newest first (REQ-TRN-007)
        self.dataset_version.currentIndexChanged.connect(self._show_version)
        f.addRow(self.tr("Dataset version"), self.dataset_version)
        self.version_line = QLabel()  # its validation set and training set, or why there is nothing to train from
        self.version_line.setObjectName("muted")
        self.version_line.setWordWrap(True)
        f.addRow(self.version_line)
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
        self.btn_stop = button(self.tr("Cancel"), slot=self.stop)  # stops the run within a step (REQ-TRN-008)
        self.btn_stop.setEnabled(False)
        row.addWidget(self.btn_train)
        row.addWidget(self.btn_stop)
        f.addRow(row)
        self.bar = QProgressBar()  # the percent of the run's time gone, as estimated
        self.bar.setRange(0, 100)
        f.addRow(self.bar)
        self.phase_line = QLabel()  # what the run does now and its time left
        self.phase_line.setWordWrap(True)
        f.addRow(self.phase_line)
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
        self.btn_rollback = button(self.tr("Roll Back"), slot=self.rollback)  # its label names the version (Q41)
        mrow.addWidget(self.btn_rollback)
        mrow.addWidget(button(self.tr("AI Model Card"), slot=self.show_card))
        mrow.addWidget(button(self.tr("Export AI Model…"), slot=self.export_model))
        rl.addLayout(mrow)
        self.card_view = (
            QPlainTextEdit()
        )  # the selected version's card, read-only, shown on AI Model Card (REQ-TRN-011)
        self.card_view.setReadOnly(True)
        self.card_view.hide()
        rl.addWidget(self.card_view, 1)
        # the table as wide as its reference line needs at 1920 px, the editor next; with S31's import sheet open the
        # table takes 742 px and the editor 407 px, its buttons whole, the training panel keeping its 457 px (outer)
        split.setSizes([650, 500])
        kl = QVBoxLayout(self.keys)
        kl.setContentsMargins(0, 0, 0, 0)
        kl.addWidget(split)
        self.datasets_tab = QWidget()  # the working set, the labeller agreement and the versions (Datasets stage)
        dl = QVBoxLayout(self.datasets_tab)
        dl.setContentsMargins(0, 0, 0, 0)
        self.working = WorkingSetPanel(self)
        self.agreement = AgreementPanel(self)
        self.versions = VersionsPanel(self)
        for w in (self.working, self.working.sheet, self.versions.split, self.agreement):
            dl.addWidget(w)  # a sheet in the agreement's place while it is open (show_sheet)
        dl.addWidget(self.versions, 1)  # the table takes the height left
        # the sketches' Samples and Datasets tabs, on the title row as they draw them, so the page is no taller than
        # before them (Training fits a 1600 x 900 screen); the training panel stays beside both
        self.tabs = QTabBar()
        self.tabs.addTab(self.tr("Samples"))
        self.tabs.addTab(self.tr("Datasets"))
        self.head.addWidget(self.tabs, 0, Qt.AlignmentFlag.AlignBottom)
        # Label Blind… shows the blind panel in the tabs' place, the tab bar hidden: none of their keys acts meanwhile
        self.blind = BlindPanel(self)
        self.blind.closed.connect(self._blind_closed)
        self.stack = QStackedWidget()  # the tab shown, or the blind panel
        self.stack.addWidget(self.keys)
        self.stack.addWidget(self.datasets_tab)
        self.stack.addWidget(self.blind)
        self.tabs.currentChanged.connect(self.stack.setCurrentIndex)
        outer = QSplitter(Qt.Orientation.Horizontal)
        outer.addWidget(self.stack)
        outer.addWidget(right)
        outer.setSizes([1150, 460])
        self.root.addWidget(outer, 1)

    def action(self, text: str, key: str | QKeySequence.StandardKey, slot: Callable[[], object]) -> QAction:
        """A key of the Samples tab's: the action is the tab's, not the page's, so its key acts only while the tab is
        shown (a window shortcut is active only while a widget it is added to is visible)."""
        a = super().action(text, key, slot)
        self.removeAction(a)
        self.keys.addAction(a)
        return a

    def dataset_action(self, text: str, key: str, slot: Callable[[], object]) -> QAction:
        """A key of the Datasets tab's, acting only while the tab is shown, as `action` makes the Samples tab's."""
        a = super().action(text, key, slot)
        self.removeAction(a)
        self.datasets_tab.addAction(a)
        return a

    def idle(self) -> bool:
        """No import, draw or freeze of the page's runs: one job of the page's at a time (#194)."""
        return self._bg is None

    def show_sheet(self, sheet: QWidget | None) -> None:
        """A sheet of the Datasets tab, Freeze or Split and Lock, in the labeller agreement's place, or with None the
        agreement back: what it replaces hidden first, so the page keeps the height a 1600 x 900 screen gives it."""
        if sheet is not None:
            self.agreement.hide()
        for s in (self.working.sheet, self.versions.split):
            s.setVisible(s is sheet)
        if sheet is None:
            self.agreement.show()
        self.working.sync()  # Freeze Dataset… and Split and Lock Validation Set…, off while a sheet is open
        self.versions.sync()

    def sheet_open(self) -> bool:
        """Whether a sheet of the Datasets tab is open: one at a time."""
        return self.working.sheet.isVisible() or self.versions.split.isVisible()

    def open_blind(self, set_uuid: str, images: list[str], paths: dict[str, str]) -> None:
        """Label Blind…: the blind panel in the tabs' place, from the set's first image the user has not labelled."""
        self.tabs.hide()
        self.stack.setCurrentWidget(self.blind)
        self.blind.label_set(set_uuid, images, paths)

    def _blind_closed(self) -> None:
        """The tabs back, the focus on Label Blind…, or on the set once the user has labelled every image of it."""
        self.tabs.show()
        self.stack.setCurrentIndex(self.tabs.currentIndex())
        self.refresh()
        if self.isVisible():
            panel = self.agreement
            (panel.btn_blind if panel.btn_blind.isEnabled() else panel.sets).setFocus()

    def _stop_blind(self) -> None:
        """A sign-in or another board model ends blind labelling: the next user never labels as the one before."""
        if self.stack.currentWidget() is self.blind:
            self.blind.stop()

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
        self._stop_blind()
        self.working.sheet.leave()  # the Freeze sheet too; a freeze that runs goes on, as an import does
        self.versions.split.close_sheet()  # and the Split sheet; a lock that runs ends as the user who started it
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
        needs none of this: its line edit accepts the ShortcutOverride of a key it types first. Enter typed in a spin
        box, a text field or a drop-down list is the field's too, never Check Label's (labels sketch)."""
        if e.type() == QEvent.Type.ShortcutOverride and self.isVisible() and isinstance(e, QKeyEvent):
            focus = QApplication.focusWidget()
            typed = e.text().isprintable() and e.text() != "" and not e.modifiers() & NOT_TYPING
            if (typed and self._takes_keys(focus)) or (e.key() in ENTER and isinstance(focus, FIELDS)):
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
        with no labeller is labelled again, keeping its type if it is one of the 33, so that it can be checked (S32),
        which Undo leaves; a type an earlier version stored that is not one of the 33 goes, with no other in its place
        (the boxes give the types), and Undo puts back none either (review). The marks write through set_label, which
        takes UNSURE and an NG with no type until its boxes are drawn, where update_sample keeps the import's rule, OK
        or NG with one of the 33 types (S31). A batch an error stops part-way shows what it stored, which Undo puts
        back, then the error (review)."""
        ctx = self.ctx
        before = [s for i in self._selected_ids() if (s := self.shown[i])["label"] != label or not s["labelled_by"]]
        if not before:
            return
        changed: list[State] = []
        since = self.editor.forgotten  # a sign-in or another board model meanwhile: nothing to undo

        def write(i: int) -> None:  # on a pool thread: the sample as it is, for Undo, then its new label
            uuid = next(s["uuid"] for s in before if s["id"] == i)
            now = ctx.label_history(uuid)[0]  # not the table's row: a box stored since gave the label a labeller
            if now["label"] == label and now["labelled_by"]:
                return
            kind = now["defect_type"] if now["defect_type"] in names() else None
            boxes = [DefectBox(b["x"], b["y"], b["w"], b["h"], b["dct_type"]) for b in ctx.boxes(uuid)]
            ctx.set_label(uuid, label, kind if now["label"] == label else None)
            if now["label"] != label:
                changed.append((uuid, now["label"], kind, boxes))

        def done(refused: Exception | None) -> None:
            if changed:
                self.editor.remember(changed, since)
            self.refresh()  # what was stored, before the dialog says why the rest was not
            if refused is not None:
                self.error(refused)
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
        """The label editor on the selected sample, the topmost row when several are selected; none: nothing. Check
        Label follows the rows selected."""
        rows = sorted(i.row() for i in self.samples.selectionModel().selectedRows())
        self.editor.show_sample(self.shown.get(int(cell_text(self.samples, rows[0], 0))) if rows else None)
        self._sync_check()

    def _fill_samples(self) -> None:
        """The samples the filter shows, in the table, with the rows selected before selected again; the editor
        follows once. An empty list says what the filter looks for, and what to do."""
        if not self.board_model:
            return
        shown = self.filter.currentData()
        s = [
            r
            for r in self.shown.values()
            if shown == "All" or r["label"] == shown or (shown == "Unchecked" and r["uuid"] in self._to_check)
        ]
        kept = set(self._selected_ids())
        self.samples.selectionModel().blockSignals(True)  # the editor follows once the rows are selected again
        fill_table(
            self.samples,
            [
                [
                    r["id"],
                    r["label"],
                    self._types(self._boxes.get(r["id"], []), r["defect_type"]),
                    view_text(r["side"]) if r["side"] else "",
                    r["labelled_by_name"] or "—",
                    self._checker(r),
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
        elif not self.shown:
            what = self.tr("Add at least 20 OK boards with Add OK Images… or Import Folder…")
            heading = self.tr("No samples for {board_model} yet").format(board_model=self.board_model)
            self.samples_empty.show_state(heading, what, self.tr("Import Folder…"), self.import_folder)
        elif shown == "Unchecked" and self._statuses and all(st["ready"] for st in self._statuses):
            done = self.tr("A second user has checked every NG label and every OK label drawn.")
            self.samples_empty.show_state(self.tr("Nothing left to check"), done)
        elif shown == "Unchecked":
            draw = self.tr(
                "No label waits for a check: Draw OK Labels to Check draws the OK labels a second user checks."
            )
            self.samples_empty.show_state(self.tr("Nothing to check yet"), draw)
        else:
            heading = self.tr("No {label} images").format(label=shown)
            self.samples_empty.show_state(heading, self.tr("Show All lists every image."))

    def _checker(self, sample: dict[str, Any]) -> str:
        """The Checked column: who checked the sample's current label (labels sketch), else "—"."""
        if sample["checked_by"] is None:
            return "—"
        return self.tr("{user} ✓").format(user=sample["checked_by_name"] or "—")

    def _check_status(self) -> None:
        """The second-user checks of each view with an OK or NG label (REQ-TRN-004), and the labels still to check."""
        views = [v for v in VIEWS if any(r["side"] == v and r["label"] in ("OK", "NG") for r in self.shown.values())]
        self._statuses = [self.ctx.label_check_status(self.board_model or "", v) for v in views]
        self._to_check = {u for st in self._statuses for u in st["ng_unchecked"]}
        self._to_check |= {u for st in self._statuses for u in st["ok_drawn"] if u not in st["ok_checked"]}

    def _show_checks(self) -> None:
        """The line over the table: the NG labels checked and the OK labels checked of the 10 % a freeze needs, every
        view together, with ✓ once every view is ready to freeze; none without an OK or NG label."""
        st = self._statuses
        self.checks_line.setVisible(bool(st))
        ng, need, ok = (sum(x[k] for x in st) for k in ("ng", "ok_needed", "ok"))
        ng_checked = ng - sum(len(x["ng_unchecked"]) for x in st)
        ok_checked = sum(min(len(x["ok_checked"]), x["ok_needed"]) for x in st)
        if need and not any(x["ok_drawn"] for x in st):
            line = self.tr(
                "{ng_checked} of {ng} NG labels checked · {ok_checked} of {need} OK labels checked (10 % of {ok},"
                " none drawn yet)"
            )
        else:
            line = self.tr(
                "{ng_checked} of {ng} NG labels checked · {ok_checked} of {need} OK labels checked (10 % of {ok})"
            )
        text = line.format(ng_checked=ng_checked, ng=ng, ok_checked=ok_checked, need=need, ok=ok)
        if st and all(x["ready"] for x in st):
            text = self.tr("{line} ✓").format(line=text)
        self.checks_line.setText(text)

    def _picked(self) -> list[dict[str, Any]]:
        """The samples selected in the table, topmost first."""
        rows = sorted(i.row() for i in self.samples.selectionModel().selectedRows())
        return [self.shown[int(cell_text(self.samples, r, 0))] for r in rows]

    def _why_not(self, sample: dict[str, Any]) -> str | None:
        """Why the user signed in cannot check the sample's label, as check_label refuses it; None when they can."""
        if sample["checked_by"] is not None:
            return self.tr("Checked by {user}").format(user=sample["checked_by_name"] or "—")
        if sample["label"] == "UNSURE":
            return self.tr("An UNSURE image is left out of training, so its label is not checked")
        if sample["label"] == "NG" and not self._boxes.get(sample["id"]):
            return self.tr("Draw its defect boxes first")
        if sample["labelled_by"] is None:
            return self.tr("No labeller is recorded for it: label it again first")
        if sample["labelled_by"] == self.ctx.user_uuid:
            return self.tr("You labelled this image")
        return None

    def _sync_check(self) -> None:
        """Check Label on while the user signed in can check a selected image's label; off, its tooltip says why for
        the topmost selected image, or that none is selected (labels sketch)."""
        why = [self._why_not(s) for s in self._picked()]
        can = None in why
        self.act_check.setEnabled(can)
        key = self.act_check.shortcut().toString(QKeySequence.SequenceFormat.NativeText)
        self.btn_check.setToolTip(key if can else (why[0] or "") if why else self.tr("Select the images to check"))

    def _check(self) -> None:
        """Check Label (Return): record the user signed in as the second user who checked each selected image's label
        that they can check (REQ-TRN-004), on a pool thread as the marks write; the others stay as they are, and the
        status line counts them and says why for the first. A refusal or an error stops at the image it names, the
        checks before it staying stored."""
        picked = self._picked()
        can = {s["id"]: s["uuid"] for s in picked if self._why_not(s) is None}
        left = [(s, why) for s in picked if (why := self._why_not(s)) is not None]
        if not can:
            return

        def done(refused: Exception | None) -> None:
            self.refresh()
            if refused is not None:
                self.error(refused)
            elif left:
                line = self.tr("Checked {count} label(s); {left} left unchecked, {file} first: {reason}")
                file = Path(left[0][0]["path"]).name
                self.shell.status(line.format(count=len(can), left=len(left), file=file, reason=left[0][1]))
            else:
                self.shell.status(self.tr("Checked {count} label(s)").format(count=len(can)))

        self.editor.write(done, _each, list(can), lambda i: self.ctx.check_label(can[i]))

    def _draw(self) -> None:
        """Draw OK Labels to Check: in each view with an OK label, draw at random the OK labels a second user checks,
        10 % of them rounded up, on a pool thread; the filter then shows Unchecked (REQ-TRN-004)."""
        if (board_model := self.checked_board_model()) is None:
            return
        views = [v for v in VIEWS if any(r["side"] == v and r["label"] == "OK" for r in self.shown.values())]

        def draw() -> list[dict[str, Any]]:
            return [d for v in views if (d := self.ctx.draw_ok_checks(board_model, v)) is not None]

        self.run_in_background(draw, on_result=self._drawn)

    def _drawn(self, draws: list[dict[str, Any]]) -> None:
        self.refresh()
        need = sum(st["ok_needed"] for st in self._statuses)
        if draws:
            self.filter.setCurrentIndex(self.filter.findData("Unchecked"))
            line = self.tr("Drew {count} OK label(s) for a second user to check; Show Unchecked lists them")
            self.shell.status(line.format(count=sum(len(d["sample_uuids"]) for d in draws)))
        elif need:
            drawn = sum(min(len(st["ok_drawn"]), st["ok_needed"]) for st in self._statuses)
            line = self.tr("The OK labels drawn are enough: {drawn} of the {needed} needed")
            self.shell.status(line.format(drawn=drawn, needed=need))
        else:
            self.shell.status(self.tr("No OK label to draw yet: add or mark OK images first"))

    def _types(self, kinds: list[str], given: str | None) -> str:
        """The Defect type column: the types of an image's boxes, each once with its count ("Solder Bridge ×2,
        Missing Component", the sketch's Defect types), else the type given at import, if any."""
        if not kinds:
            return given or ""
        each = self.tr("{type} ×{count}")
        return ", ".join(kind if n == 1 else each.format(type=kind, count=n) for kind, n in Counter(kinds).items())

    def _show_types(self, uuid: str, boxes: list[DefectBox]) -> None:
        """The boxes of a sample just stored: its row's Defect type, with no read of the database, and its label row
        now the user's own, with no check (REQ-TRN-004), which the checks line and Check Label follow."""
        for s in self.shown.values():
            if s["uuid"] == uuid:
                self._boxes[s["id"]] = [b.dct_type for b in boxes]
                s |= {"labelled_by": self.ctx.user_uuid, "labelled_by_name": self.ctx.user}
                s |= {"checked_by": None, "checked_by_name": None}
        for row in range(self.samples.rowCount()):
            s = self.shown[int(cell_text(self.samples, row, 0))]
            if s["uuid"] == uuid:
                cell_item(self.samples, row, 2).setText(self._types(self._boxes[s["id"]], s["defect_type"]))
                cell_item(self.samples, row, 4).setText(s["labelled_by_name"] or "—")
                cell_item(self.samples, row, 5).setText(self._checker(s))
        self._check_status()
        self._show_checks()
        self._sync_check()

    # --- training ---------------------------------------------------------------
    def train(self) -> None:
        """Train from the dataset version picked, as a job of the context that goes on whatever page is shown
        (REQ-TRN-008); the run refuses a version it cannot train from before reading an image."""
        if self.checked_board_model() is None or (version := self.dataset_version.currentData()) is None:
            return
        size = int(self.input_size.currentText())
        try:
            self.ctx.start_training(version, self.epochs.value(), size, listen=self._follow)
        except AoiError as e:  # a run already going on (AOI-TRN-047)
            self.error(e)
            return
        self.log.clear()  # the run's first report is still queued for this thread
        self.bar.setValue(0)
        self.phase_line.setText("")
        self.btn_train.setEnabled(False)
        self.btn_stop.setEnabled(True)

    def _follow(self, job: Job[dict[str, Any]]) -> None:
        """Show the run `job` here: its reports, result and end reach this page's slots on the UI thread."""
        self.worker = Worker.of(job)
        self.worker.signals.progress.connect(self._on_progress)
        self.worker.signals.result.connect(self._on_done)
        self.worker.signals.error.connect(self.error)
        self.worker.signals.finished.connect(self._finished)
        keep(self.worker, self.ctx.jobs)

    def stop(self) -> None:
        """Cancel: the run stops after the image, training step or map in hand, and saves nothing (REQ-TRN-008)."""
        if self.worker:
            self.worker.stop()

    def _on_progress(self, values: tuple[RunProgress]) -> None:
        p = values[0]
        self.bar.setValue(p.percent)
        line = self.tr("{phase} · {percent} % · {left}")  # the engine's phrases, shown in the UI language (#199)
        left = time_left_text(p.left_s)
        self.phase_line.setText(line.format(phase=phrase_text(p.phase), percent=p.percent, left=left))
        if p.note:
            self.log.appendPlainText(phrase_text(p.note))

    def _on_done(self, meta: dict[str, Any]) -> None:
        self.bar.setValue(self.bar.maximum())
        saved = self.tr("Saved AI model {version} ({seconds} s) with its Golden board and AI model card.")
        self.log.appendPlainText(saved.format(version=meta["version"], seconds=meta["train_seconds"]))
        done = self.tr("AI model {version} trained: select it and press Activate Selected to judge boards with it")
        self.shell.status(done.format(version=meta["version"]))  # it installs inactive (REQ-TRN-010)
        self.refresh()

    def _finished(self) -> None:
        if self.worker is not None and self.worker.job.cancelled and self.worker.job.result is None:  # Cancel (#171)
            self.log.appendPlainText(self.tr("Cancelled: no AI model was saved; the active AI model is unchanged."))
        self.phase_line.setText("")
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
        self.btn_draw.setEnabled(idle)  # a draw would stop the import that runs: one job of the page's at a time
        self.samples_empty.link.setEnabled(idle)
        self.working.sync()  # Freeze Dataset… and Freeze, off while a job runs
        self.versions.sync()  # and Split and Lock Validation Set…, Lock and Verify Manifest
        self.btn_train.setEnabled(idle and self.worker is None and self.dataset_version.currentData() is not None)

    def _fill_versions(self) -> None:
        """The board model's frozen versions, newest first: the one picked before while it is listed, else the newest
        whose validation set is locked, the one Training trains from (AppContext.training_version)."""
        kept = self.dataset_version.currentData()
        try:
            newest = self.ctx.training_version(self.board_model)["uuid"] if self.board_model else None
        except AoiError:  # no version of it is locked: the newest is picked, and its line says why it cannot train
            newest = None
        self.dataset_version.blockSignals(True)  # one line shown, once the list is whole
        self.dataset_version.clear()
        for v in self.ctx.datasets(self.board_model) if self.board_model else []:
            self.dataset_version.addItem(v["name"], v["uuid"])
        pick = self.dataset_version.findData(kept) if kept is not None else -1
        self.dataset_version.setCurrentIndex(pick if pick >= 0 else max(self.dataset_version.findData(newest), 0))
        self.dataset_version.blockSignals(False)
        self._show_version()

    def _show_version(self) -> None:
        """The line under the dataset version: its locked validation set and its training set, as the sketch counts
        them, or why Start Training has nothing to train from."""
        uuid = self.dataset_version.currentData()
        self.dataset_version.setEnabled(uuid is not None)
        if uuid is None and not self.board_model:
            text = ""
        elif uuid is None:
            text = self.tr(
                "No frozen dataset version of {board_model} yet; training reads only a frozen version's training set,"
                " once its validation set is locked."
            ).format(board_model=self.board_model or "")
        elif (split := self.ctx.validation_split(uuid)) is None:
            text = self.tr("Validation set not locked: training needs it locked, and reads only the training set.")
        else:
            label = {i["uuid"]: i["label"] for i in self.ctx.dataset_items(uuid)}
            n = Counter((part, label[u]) for part in ("train", "validation") for u in split[part])
            line = self.tr(
                "Validation set locked ✓ {val_ok} OK / {val_ng} NG · training set {ok} OK, {ng} NG"
                " · NG used for calibration only"
            )
            text = line.format(
                val_ok=n["validation", "OK"], val_ng=n["validation", "NG"], ok=n["train", "OK"], ng=n["train", "NG"]
            )
        self.version_line.setText(text)
        self.update_actions()

    # --- model registry ---------------------------------------------------------
    def activate(self) -> None:
        rows = self.models.selectionModel().selectedRows()
        if rows:
            self.ctx.activate_model(int(cell_text(self.models, rows[0].row(), 0)))
            self.refresh()

    def rollback(self) -> None:
        """One click back to the version active before the active one, with its Golden board (REQ-TRN-010)."""
        if self.board_model:
            back = self.ctx.rollback_model(self.board_model)
            self.shell.status(self.tr("Rolled back to AI model {version}").format(version=back["version"]))
            self.refresh()

    def show_card(self) -> None:
        """The selected version's model card under the table, or a line saying it has none (REQ-TRN-011)."""
        rows = self.models.selectionModel().selectedRows()
        if not rows:
            self.card_view.hide()
            return
        text = self.ctx.card_text(int(cell_text(self.models, rows[0].row(), 0)))
        no_card = self.tr("AI model {version} has no AI model card: train again to make a version that has one.")
        self.card_view.setPlainText(text or no_card.format(version=cell_text(self.models, rows[0].row(), 1)))
        self.card_view.show()

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
        self._fill_versions()
        if not self.board_model:
            self.samples.setRowCount(0)
            self.models.setRowCount(0)
            self.models_note.hide()
            self.card_view.hide()
            self.btn_rollback.setText(self.tr("Roll Back"))
            self.btn_rollback.setEnabled(False)
            self.counts.set_line(lambda _name: "", "")
            self.checks_line.hide()
            self.tip.hide()
            self.samples_empty.show_state(*self.no_board_model())
            self.models_empty.hide()
            self.agreement.show_board_model(None, [])
            self.working.show_board_model(None, [])
            self.versions.show_board_model(None)
            return
        s = self.ctx.samples(self.board_model)
        self.agreement.show_board_model(self.board_model, s)
        self.working.show_board_model(self.board_model, s)
        self.versions.show_board_model(self.board_model)  # after the working set, whose views its empty state reads
        self.shown = {r["id"]: r for r in s}
        self._boxes = {r["id"]: [b["dct_type"] for b in self.ctx.boxes(r["uuid"])] for r in s if r["label"] == "NG"}
        self._check_status()
        self._fill_samples()
        n_ok, n_ng = (sum(r["label"] == label for r in s) for label in ("OK", "NG"))  # UNSURE counts as neither
        ref = self.ctx.reference_image(self.board_model)
        reference = Path(ref).name if ref else self.tr("none")
        counts = self.tr("{ok} OK · {ng} NG · reference: {reference}")
        self.counts.set_line(lambda name: counts.format(ok=n_ok, ng=n_ng, reference=name), reference)
        self._show_checks()
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
        self.card_view.hide()  # a card shown was the selected row's; the selection is gone
        back = self.ctx.previous_model(self.board_model)  # Roll Back names the version it goes to (Q41)
        label = self.tr("Roll Back to {version}").format(version=back["version"]) if back else self.tr("Roll Back")
        self.btn_rollback.setText(label)
        self.btn_rollback.setEnabled(back is not None)
        # each row's AOI-TRN-012, with what happened and what to do, under the table
        said = [tip for tip in tips if tip]
        self.models_note.setText("\n".join(said))
        self.models_note.setVisible(bool(said))
        if ms:
            self.models_empty.hide()
        else:
            self.models_empty.show_state(
                self.tr("No AI model yet"), self.tr("Start Training from a frozen dataset version.")
            )

    def on_board_model_changed(self, name: str | None) -> None:
        self._stop_blind()
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
