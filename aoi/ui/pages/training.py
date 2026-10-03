"""Dataset & Training page: upload sample boards, self-train, manage model versions."""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING, Any

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QSpinBox,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from ... import defects as taxonomy
from ...core.imaging import IMAGE_EXTS, list_images
from ...core.services import AppContext
from ...errors import AoiError
from ...hal import VIEWS
from ...times import to_local
from .. import theme
from ..errors import phrase_text
from ..widgets.busy import BusyOverlay
from ..widgets.empty_state import EmptyState
from ..widgets.image_view import ImageView
from ..workers import Worker, start
from .base import QT_TRANSLATE_NOOP, Page, button, cell_item, cell_text, fill_table, make_table, view_text

if TYPE_CHECKING:
    from ..main_window import MainWindow


class NgDialog(QDialog):
    """Ask which defect type an uploaded NG batch shows (taxonomy from the classification table)."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle(self.tr("Label NG images"))
        f = QFormLayout(self)
        self.cat = QComboBox()
        self.cat.addItem(self.tr("(any)"), None)
        for category in taxonomy.categories():  # names from the classification table, English until it is translated
            self.cat.addItem(category, category)
        self.type = QComboBox()
        self.side = QComboBox()
        for view in VIEWS:
            self.side.addItem(view_text(view), view)  # the English name is the key the services store
        self.cat.currentIndexChanged.connect(self._fill)
        self._fill()
        f.addRow(self.tr("Category"), self.cat)
        f.addRow(self.tr("Defect type"), self.type)
        f.addRow(self.tr("View"), self.side)
        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        f.addRow(bb)

    def _fill(self, _index: int = 0) -> None:
        cat = self.cat.currentData()
        self.type.clear()
        self.type.addItem(self.tr("Unknown / mixed"))
        for d in taxonomy.DEFECT_TYPES:
            if cat is None or d.category == cat:
                self.type.addItem(self.tr("{type}  [{severity}]").format(type=d.name, severity=d.severity), d.name)

    def value(self) -> tuple[str | None, str]:
        """The defect type (None for "Unknown / mixed") and the camera view, as the services store them."""
        return self.type.currentData(), self.side.currentData()


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
        self.btn_ok = button(self.tr("+ OK Images"), slot=self.add_ok)  # verdict colours mean verdicts, not add buttons
        self.btn_ng = button(self.tr("+ NG Images"), slot=self.add_ng)
        self.btn_folder = button(self.tr("Import Folder…"), slot=self.import_folder)
        for b in (self.btn_ok, self.btn_ng, self.btn_folder):
            up.addWidget(b)
        ll.addLayout(up)
        self.counts = QLabel("")
        self.counts.setObjectName("muted")
        ll.addWidget(self.counts)
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
            names = [view_text(v) for v in VIEWS]
            side, ok = QInputDialog.getItem(
                self, self.tr("View"), self.tr("Camera view of these images"), names, 0, False
            )
            if ok:
                self._add(bm, files, "OK", None, VIEWS[names.index(side)])

    def add_ng(self) -> None:
        if (bm := self.checked_board_model()) and (files := self._pick()):
            dlg = NgDialog(self)
            if dlg.exec():
                dtype, side = dlg.value()
                self._add(bm, files, "NG", dtype, side)

    def _add(self, board_model: str, files: list[str], label: str, dtype: str | None, side: str) -> None:
        """Copy the picked files on a pool thread (REQ-SET-021, #194); Cancel keeps the samples added so far."""
        if self._bg is not None:  # one import at a time: a second would stop this one (#194)
            return
        self.run_in_background(
            self.ctx.import_samples, board_model, files, label, dtype, side, with_progress=True,
            on_result=lambda _added: self.refresh(), busy=self.busy,
            on_cancel=lambda added: self._add_stopped(added or 0, len(files)),
        )  # fmt: skip

    def _add_stopped(self, added: int, total: int) -> None:
        if added < total:  # Cancel after the last file: every image was added, so nothing to say (#194)
            stopped = self.tr("Stopped: added {added} of {total} images; the others were not added.")
            self.shell.status(stopped.format(added=added, total=total))
        self.refresh()

    def import_folder(self) -> None:
        """Folder with ok/ and ng/ sub-folders (ng/<defect type>/ also accepted)."""
        if self._bg is not None or not self.need_board_model():  # one import at a time (#194)
            return
        d = QFileDialog.getExistingDirectory(self, self.tr("Folder containing ok/ and ng/ sub-folders"))
        if d:
            self.import_from(d)

    def import_from(self, folder: str) -> None:
        """Import on a pool thread (REQ-SET-021): the table shows the result; Cancel keeps what was imported so far."""
        if self._bg is not None or (bm := self.checked_board_model()) is None:  # one import at a time (#194)
            return
        self.run_in_background(
            self._import, bm, folder, with_progress=True,
            on_result=self._imported, busy=self.busy, on_cancel=self._import_stopped,
            on_error=lambda _e: self.refresh(),
        )  # fmt: skip

    def _import(
        self, board_model: str, folder: str, progress: Callable[[int, int], None], should_stop: Callable[[], bool]
    ) -> tuple[int, int, AoiError | None]:
        """Pool thread: files and the service layer only, never a widget. One file per call, so what was imported
        before a file that cannot be copied stays, and the error returned (AOI-TRN-009) says so (#178); any other
        error after a file went in is returned as AOI-TRN-010 with the same count (#206)."""
        n_ok = n_ng = 0
        files = list_images(folder)
        for i, p in enumerate(files, 1):
            if should_stop():
                break
            parts = [x.lower() for x in p.relative_to(folder).parts[:-1]]
            try:
                if any(x in ("ok", "good") for x in parts):
                    n_ok += self.ctx.import_samples(board_model, [str(p)], "OK")
                elif any(x in ("ng", "bad", "defect", "defects") for x in parts):
                    sub = p.parent.name.replace("_", " ").title()
                    dtype = sub if sub in taxonomy.BY_NAME else None
                    n_ng += self.ctx.import_samples(board_model, [str(p)], "NG", dtype)
            except Exception as e:
                n = {"at": i, "total": len(files), "imported": n_ok + n_ng}
                if isinstance(e, AoiError) and e.code == "AOI-TRN-008":  # this one file not copied
                    reason, code = e.params["reason"], "AOI-TRN-009"
                elif n["imported"]:  # files went in before it: the message must say how many (#206)
                    title = QT_TRANSLATE_NOOP("Errors", "{code} {title}")  # the title in the UI language (#198)
                    reason = title.fill(code=e.code, title=e.title) if isinstance(e, AoiError) else type(e).__name__
                    code = "AOI-TRN-010"
                else:  # nothing imported yet: the error is shown as it is
                    raise
                detail = e.detail if isinstance(e, AoiError) else str(e)
                stopped = AoiError(code, detail, path=str(p), reason=reason, folder=folder, **n)
                stopped.__cause__ = e
                return n_ok, n_ng, stopped
            progress(i, len(files))
        return n_ok, n_ng, None

    def _imported(self, outcome: tuple[int, int, AoiError | None]) -> None:
        n_ok, n_ng, stopped = outcome
        self.shell.status(self.tr("Imported {ok} OK and {ng} NG images").format(ok=n_ok, ng=n_ng))
        self.refresh()  # the table shows what was imported before the dialog says how far it went
        if stopped is not None:
            self.error(stopped)

    def _import_stopped(self, outcome: tuple[int, int, AoiError | None] | None) -> None:
        """Cancel stopped the import: the table and the status line show what it imported, and a file it could not
        import is logged and alarmed with no dialog, since the user has left that import (#206). No newer import can
        stop it: one import runs at a time (#194)."""
        self.refresh()
        if outcome is None:  # stopped before it ran, or it raised (run_in_background reported that)
            return
        n_ok, n_ng, stopped = outcome
        msg = self.tr("Import cancelled: {ok} OK and {ng} NG images imported before it stopped")
        self.shell.status(msg.format(ok=n_ok, ng=n_ng))
        if stopped is not None:
            self.ctx.report_error(stopped, self.title)

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
            dtype = dlg.value()[0]
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
        for b in (self.btn_ok, self.btn_ng, self.btn_folder, self.samples_empty.link):
            b.setEnabled(idle)
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
        f, _ = QFileDialog.getSaveFileName(self, self.tr("Export AI model"), src.name, self.tr("PyTorch model (*.pt)"))
        if f:
            self.ctx.export_model(mid, f)

    def refresh(self) -> None:
        if not self.board_model:
            self.samples.setRowCount(0)
            self.models.setRowCount(0)
            self.counts.setText("")
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
            what = self.tr("Add at least 20 OK boards with + OK Images or Import Folder…")
            heading = self.tr("No samples for {board_model} yet").format(board_model=self.board_model)
            self.samples_empty.show_state(heading, what, self.tr("Import Folder…"), self.import_folder)
        n_ok = sum(r["label"] == "OK" for r in s)
        ref = self.ctx.reference_image(self.board_model)
        reference = Path(ref).name if ref else self.tr("none")
        counts = self.tr("{ok} OK · {ng} NG · reference: {reference}").format(
            ok=n_ok, ng=len(s) - n_ok, reference=reference
        )
        if n_ok < 20:
            counts += "  ·  " + self.tr("tip: 20+ OK images give a steadier threshold")
        self.counts.setText(counts)
        ms = self.ctx.models(self.board_model)
        rows = []
        for m in ms:
            meta = json.loads(m["metrics"] or "{}")
            rows.append(
                [
                    m["id"],
                    m["version"],
                    to_local(m["created_at"]),
                    float(meta.get("image_threshold", 0)),
                    f"{meta.get('n_ok_train', 0) + meta.get('n_ok_val', 0)}/{meta.get('n_ng', 0)}",
                    "●" if m["active"] else "",
                ]
            )
        fill_table(self.models, rows)
        if ms:
            self.models_empty.hide()
        else:
            self.models_empty.show_state(
                self.tr("No AI model yet"), self.tr("Start Training once 20 OK boards are in.")
            )

    def on_board_model_changed(self, name: str | None) -> None:
        self.preview.set_image(None)
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
