"""Dataset & Training page: upload sample boards, self-train, manage model versions."""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING, Any

from PySide6.QtCore import Qt
from PySide6.QtGui import QResizeEvent
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
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

from ... import defects as taxonomy
from ...core.imaging import IMAGE_EXTS
from ...core.sample_import import ImportFile, ImportReport, folder_files
from ...core.services import AppContext
from ...errors import AoiError
from ...times import to_local
from .. import theme
from ..errors import phrase_text
from ..widgets.busy import BusyOverlay
from ..widgets.empty_state import EmptyState
from ..widgets.image_view import ImageView
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

if TYPE_CHECKING:
    from ..main_window import MainWindow


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


class NgDialog(QDialog):
    """Ask which of the 33 defect types of the classification table the samples marked NG show: no "Unknown"
    (REQ-TRN-001), and OK stays grey until a type is picked. No view: Mark NG… keeps each sample's."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle(self.tr("Label NG images"))
        f = QFormLayout(self)
        self.cat = QComboBox()
        self.cat.addItem(self.tr("(any)"), None)
        for category in taxonomy.categories():  # names from the classification table, English until it is translated
            self.cat.addItem(category, category)
        self.type = QComboBox()
        self.type.setPlaceholderText(self.tr("Pick one of the 33 defect types"))
        self.cat.currentIndexChanged.connect(self._fill)
        self._fill()
        f.addRow(self.tr("Category"), self.cat)
        f.addRow(self.tr("Defect type"), self.type)
        self.buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        f.addRow(self.buttons)
        self.type.currentIndexChanged.connect(self._allow)
        self._allow()

    def _fill(self, _index: int = 0) -> None:
        cat = self.cat.currentData()
        self.type.clear()
        for d in taxonomy.DEFECT_TYPES:  # the 33: never "Unknown", never the AI model's "Anomaly"
            if cat is None or d.category == cat:
                self.type.addItem(self.tr("{type}  [{severity}]").format(type=d.name, severity=d.severity), d.name)
        self.type.setCurrentIndex(-1)  # a type is picked, never taken by default

    def _allow(self, _index: int = 0) -> None:
        self.buttons.button(QDialogButtonBox.StandardButton.Ok).setEnabled(self.type.currentIndex() >= 0)

    def value(self) -> str | None:
        """The defect type picked, as the services store it (None until one is, which they refuse for NG)."""
        type_name: str | None = self.type.currentData()
        return type_name


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
        self.samples = make_table(
            [self.tr("ID"), self.tr("Label"), self.tr("Defect type"), self.tr("View"), self.tr("File")]
        )
        self.samples.itemSelectionChanged.connect(self._preview)
        self.samples_empty = EmptyState(self.samples)
        self.busy = BusyOverlay(self.samples, self.tr("Importing…"))
        ll.addWidget(self.samples, 1)
        act = QHBoxLayout()
        act.addWidget(button(self.tr("Mark OK"), slot=lambda: self._relabel("OK")))
        act.addWidget(button(self.tr("Mark NG…"), slot=lambda: self._relabel("NG")))
        act.addWidget(button(self.tr("Set Reference"), slot=self._set_reference))
        act.addWidget(button(self.tr("Remove"), "danger", self._remove))  # red, last in its row, never the default
        ll.addLayout(act)
        split.addWidget(left)

        # Middle: preview ----------------------------------------------------------
        self.preview = ImageView(placeholder=self.tr("Select a sample to preview"))
        split.addWidget(self.preview)

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
        split.setSizes([760, 380, 560])  # room for the four dataset buttons with their text; the preview keeps 320 px
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
        the header. While it is open, its Import is the page's one blue primary and Start Training a plain button. One
        import at a time (#194)."""
        if self._bg is not None:
            return
        self.sheet.open_files(board_model, files, base)
        self._primary(self.sheet.btn_import, self.btn_train)

    def _close_sheet(self) -> None:
        """Cancel or Esc: stops an import that runs, keeping what went in (#194); else closes the sheet."""
        if self.sheet.running:
            self.busy.cancel_button.click()
            return
        self.sheet.hide()
        self._primary(self.btn_train, self.sheet.btn_import)

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
        n = {"at": total - len(report.left), "total": total, "imported": len(report.added)}
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
        """The sheet shows what became of each file; a sheet whose board model is no longer the header's (another one
        chosen while the import ran) then closes, so Import again cannot send its files elsewhere."""
        self.sheet.show_report(report, self.coded_text)
        if self.sheet.board_model != self.board_model:
            self._close_sheet()

    def _imported(self, report: ImportReport, total: int) -> None:
        self._report(report)
        n = self._counts(report)
        said = self.tr("Imported {ok} OK and {ng} NG images").format(**n)
        if n["refused"]:
            said = self.tr("Imported {ok} OK and {ng} NG images; {refused} not imported (see the list)").format(**n)
        self.shell.status(said)
        self.refresh()  # the table shows what was imported before the dialog says how far it went
        if (stopped := self._stop_error(report, total)) is not None:
            self.error(stopped)

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
        msg = self.tr("Import cancelled: {ok} OK and {ng} NG images imported before it stopped")
        self.shell.status(msg.format(**self._counts(report)))
        if (stopped := self._stop_error(report, len(files))) is not None:
            self.ctx.report_error(stopped, self.title)

    def _import_failed(self, files: list[ImportFile]) -> None:
        self._report(ImportReport(left=files))
        self.refresh()

    def _selected_ids(self) -> list[int]:
        return [int(cell_text(self.samples, i.row(), 0)) for i in self.samples.selectionModel().selectedRows()]

    def _relabel(self, label: str) -> None:
        ids = self._selected_ids()
        if not ids:
            return
        dtype: str | None = None
        if label == "NG":
            dlg = NgDialog(self)
            if not dlg.exec():
                return
            dtype = dlg.value()
        self._each_sample(ids, lambda i: self.ctx.update_sample(i, label, dtype))

    def _each_sample(self, ids: list[int], write: Callable[[int], None]) -> None:
        """Write each selected sample but the reference, which stays as it is and is named once the others are written
        (AOI-TRN-007), so which rows change never depends on the order they were selected in (#168). Any other refusal
        stops at the sample it names."""
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

    def _preview(self) -> None:
        rows = self.samples.selectionModel().selectedRows()
        if rows:
            p = cell_item(self.samples, rows[0].row(), 4).toolTip()
            if Path(p).exists():
                self.preview.set_image(self.ctx.load_image(p))

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
        fill_table(
            self.samples,
            [
                [
                    r["id"],
                    r["label"],
                    r["defect_type"] or "",
                    view_text(r["side"]) if r["side"] else "",
                    Path(r["path"]).name,
                ]
                for r in s
            ],
            [None if r["label"] == "OK" else theme.NG_TINT for r in s],
            [r["path"] for r in s],
        )
        if s:
            self.samples_empty.hide()
        else:
            what = self.tr("Add at least 20 OK boards with Add OK Images… or Import Folder…")
            heading = self.tr("No samples for {board_model} yet").format(board_model=self.board_model)
            self.samples_empty.show_state(heading, what, self.tr("Import Folder…"), self.import_folder)
        n_ok = sum(r["label"] == "OK" for r in s)
        ref = self.ctx.reference_image(self.board_model)
        reference = Path(ref).name if ref else self.tr("none")
        counts = self.tr("{ok} OK · {ng} NG · reference: {reference}")
        self.counts.set_line(lambda name: counts.format(ok=n_ok, ng=len(s) - n_ok, reference=name), reference)
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
        self.preview.set_image(None)
        if not self.sheet.running:  # its files were picked for the board model shown before; an import that runs
            self._close_sheet()  # goes on into that one, and its sheet closes when it ends (_report)
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
