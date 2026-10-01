"""Dataset & Training page: upload sample boards, self-train, manage model versions."""

from __future__ import annotations

import json
from pathlib import Path

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
from ...core.imaging import IMAGE_EXTS, list_images, load_image
from ...errors import AoiError
from ...hal import VIEWS
from ...times import to_local
from .. import theme
from ..widgets.busy import BusyOverlay
from ..widgets.image_view import ImageView
from ..workers import Worker, start
from .base import Page, button, fill_table, make_table


class NgDialog(QDialog):
    """Ask which defect type an uploaded NG batch shows (taxonomy from the classification table)."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Label NG images")
        f = QFormLayout(self)
        self.cat = QComboBox()
        self.cat.addItems(["(any)"] + taxonomy.categories())
        self.type = QComboBox()
        self.side = QComboBox()
        self.side.addItems(VIEWS)
        self.cat.currentTextChanged.connect(self._fill)
        self._fill("(any)")
        f.addRow("Category", self.cat)
        f.addRow("Defect type", self.type)
        f.addRow("View", self.side)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        f.addRow(bb)

    def _fill(self, cat):
        self.type.clear()
        self.type.addItem("Unknown / mixed")
        for d in taxonomy.DEFECT_TYPES:
            if cat == "(any)" or d.category == cat:
                self.type.addItem(f"{d.name}  [{d.severity}]", d.name)

    def value(self):
        return self.type.currentData(), self.side.currentText()


class TrainingPage(Page):
    title = "Training"
    subtitle = "Upload good (OK) and defective (NG) boards; the model trains itself on this board model"
    roles = ("Engineer", "Admin")

    def __init__(self, ctx, shell):
        super().__init__(ctx, shell)
        self.worker: Worker | None = None

        split = QSplitter(Qt.Horizontal)

        # Left: dataset ------------------------------------------------------------
        left = QWidget()
        ll = QVBoxLayout(left)
        ll.setContentsMargins(0, 0, 8, 0)
        up = QHBoxLayout()
        up.addWidget(button("+ OK Images", "start", self.add_ok))
        up.addWidget(button("+ NG Images", "stop", self.add_ng))
        up.addWidget(button("Import Folder…", slot=self.import_folder))
        ll.addLayout(up)
        self.counts = QLabel("")
        self.counts.setObjectName("muted")
        ll.addWidget(self.counts)
        self.samples = make_table(["ID", "Label", "Defect type", "View", "File"])
        self.samples.itemSelectionChanged.connect(self._preview)
        self.busy = BusyOverlay(self.samples, self.tr("Importing…"))
        ll.addWidget(self.samples, 1)
        act = QHBoxLayout()
        act.addWidget(button("Mark OK", slot=lambda: self._relabel("OK")))
        act.addWidget(button("Mark NG…", slot=lambda: self._relabel("NG")))
        act.addWidget(button("Set Reference", slot=self._set_reference))
        act.addWidget(button("Remove", slot=self._remove))
        ll.addLayout(act)
        split.addWidget(left)

        # Middle: preview ----------------------------------------------------------
        self.preview = ImageView(placeholder="Select a sample to preview")
        split.addWidget(self.preview)

        # Right: training + model versions ----------------------------------------
        right = QWidget()
        rl = QVBoxLayout(right)
        rl.setContentsMargins(8, 0, 0, 0)
        g = QGroupBox("Self-training")
        f = QFormLayout(g)
        self.epochs = QSpinBox()
        self.epochs.setRange(5, 1000)
        self.epochs.setValue(ctx.settings.default_epochs)
        self.size = QComboBox()
        self.size.addItems(["128", "256", "384", "512"])
        self.size.setCurrentText(str(ctx.settings.image_size))
        f.addRow("Epochs", self.epochs)
        f.addRow("Network input size", self.size)
        f.addRow("Device", QLabel(ctx.device.upper()))
        row = QHBoxLayout()
        self.btn_train = button("Start Training", "primary", self.train)
        self.btn_stop = button("Stop", slot=self.stop)
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
        rl.addWidget(QLabel("Model versions"))
        self.models = make_table(["ID", "Version", "Created", "Threshold", "OK/NG", "Active"])
        rl.addWidget(self.models, 1)
        mrow = QHBoxLayout()
        mrow.addWidget(button("Activate Selected", slot=self.activate))
        mrow.addWidget(button("Export Model…", slot=self.export_model))
        rl.addLayout(mrow)
        split.addWidget(right)
        split.setSizes([620, 520, 560])
        self.root.addWidget(split, 1)

    # --- dataset ----------------------------------------------------------------
    def _pick(self) -> list[str]:
        exts = " ".join(f"*{e}" for e in sorted(IMAGE_EXTS))
        files, _ = QFileDialog.getOpenFileNames(self, "Select PCB images", "", f"Images ({exts})")
        return files

    def add_ok(self):
        if self.need_board_model() and (files := self._pick()):
            side, ok = QInputDialog.getItem(self, "View", "Camera view of these images", list(VIEWS), 0, False)
            if ok:
                self.ctx.import_samples(self.board_model, files, "OK", side=side)
                self.refresh()

    def add_ng(self):
        if self.need_board_model() and (files := self._pick()):
            dlg = NgDialog(self)
            if dlg.exec():
                dtype, side = dlg.value()
                self.ctx.import_samples(self.board_model, files, "NG", dtype, side)
                self.refresh()

    def import_folder(self):
        """Folder with ok/ and ng/ sub-folders (ng/<defect type>/ also accepted)."""
        if not self.need_board_model():
            return
        d = QFileDialog.getExistingDirectory(self, "Folder containing ok/ and ng/ sub-folders")
        if d:
            self.import_from(d)

    def import_from(self, folder: str) -> None:
        """Import on a pool thread (REQ-SET-021): the table shows the result; Cancel keeps what was imported so far."""
        self.run_in_background(
            self._import, self.board_model, folder, with_progress=True,
            on_result=self._imported, busy=self.busy, on_cancel=self.refresh,
        )  # fmt: skip

    def _import(self, board_model, folder, progress, should_stop):
        """Pool thread: files and the service layer only, never a widget."""
        n_ok = n_ng = 0
        files = list_images(folder)
        for i, p in enumerate(files, 1):
            if should_stop():
                break
            parts = [x.lower() for x in p.relative_to(folder).parts[:-1]]
            if any(x in ("ok", "good") for x in parts):
                n_ok += self.ctx.import_samples(board_model, [str(p)], "OK")
            elif any(x in ("ng", "bad", "defect", "defects") for x in parts):
                sub = p.parent.name.replace("_", " ").title()
                dtype = sub if sub in taxonomy.BY_NAME else None
                n_ng += self.ctx.import_samples(board_model, [str(p)], "NG", dtype)
            progress(i, len(files))
        return n_ok, n_ng

    def _imported(self, counts):
        n_ok, n_ng = counts
        self.shell.status(f"Imported {n_ok} OK and {n_ng} NG images")
        self.refresh()

    def _selected_ids(self) -> list[int]:
        return [int(self.samples.item(i.row(), 0).text()) for i in self.samples.selectionModel().selectedRows()]

    def _relabel(self, label):
        ids = self._selected_ids()
        if not ids:
            return
        dtype = None
        if label == "NG":
            dlg = NgDialog(self)
            if not dlg.exec():
                return
            dtype = dlg.value()[0]
        for i in ids:
            self.ctx.update_sample(i, label, dtype)
        self.refresh()

    def _set_reference(self):
        ids = self._selected_ids()
        if ids:
            self.ctx.set_reference(self.board_model, ids[0])
            self.shell.status("Reference image set; the next training run re-learns the golden template from it")

    def _remove(self):
        ids = self._selected_ids()
        if (
            ids
            and QMessageBox.question(self, "Remove", f"Remove {len(ids)} sample(s) from the dataset?")
            == QMessageBox.Yes
        ):
            for i in ids:
                self.ctx.delete_sample(i)
            self.refresh()

    def _preview(self):
        rows = self.samples.selectionModel().selectedRows()
        if rows:
            p = self.samples.item(rows[0].row(), 4).toolTip()
            if Path(p).exists():
                self.preview.set_image(load_image(p))

    # --- training ---------------------------------------------------------------
    def train(self):
        if not self.need_board_model():
            return
        n_ok = len(self.ctx.samples(self.board_model, "OK"))
        if n_ok < 2:
            return self.error(AoiError("AOI-TRN-002", found=n_ok))
        self.log.clear()
        self.bar.setRange(0, self.epochs.value())
        self.bar.setValue(0)
        self.btn_train.setEnabled(False)
        self.btn_stop.setEnabled(True)
        self.worker = Worker(
            self.ctx.train, self.board_model, self.epochs.value(), int(self.size.currentText()), with_progress=True
        )
        self.worker.signals.progress.connect(self._on_progress)
        self.worker.signals.result.connect(self._on_done)
        self.worker.signals.error.connect(self.error)
        self.worker.signals.finished.connect(self._finished)
        start(self.worker, self.ctx.jobs)

    def stop(self):
        if self.worker:
            self.worker.stop()

    def _on_progress(self, a):
        ep, total, loss, msg = a
        if total > 1:
            self.bar.setMaximum(total)
            self.bar.setValue(ep)
        if msg:
            self.log.appendPlainText(msg)
        elif ep % 5 == 0 or ep == 1:
            self.log.appendPlainText(f"epoch {ep}/{total}  loss {loss:.4f}")

    def _on_done(self, meta):
        self.log.appendPlainText(f"Saved model {meta['version']} ({meta['train_seconds']} s). Golden template updated.")
        self.shell.status(f"Model {meta['version']} trained and activated")
        self.refresh()

    def _finished(self):
        self.btn_train.setEnabled(True)
        self.btn_stop.setEnabled(False)
        self.worker = None

    # --- model registry ---------------------------------------------------------
    def activate(self):
        rows = self.models.selectionModel().selectedRows()
        if rows:
            self.ctx.activate_model(int(self.models.item(rows[0].row(), 0).text()))
            self.refresh()

    def export_model(self):
        rows = self.models.selectionModel().selectedRows()
        if not rows:
            return
        mid = int(self.models.item(rows[0].row(), 0).text())
        src = Path(self.ctx.model(mid)["path"])
        f, _ = QFileDialog.getSaveFileName(self, "Export model", src.name, "PyTorch model (*.pt)")
        if f:
            self.ctx.export_model(mid, f)

    def refresh(self):
        if not self.board_model:
            self.samples.setRowCount(0)
            self.models.setRowCount(0)
            self.counts.setText("")
            return
        s = self.ctx.samples(self.board_model)
        fill_table(
            self.samples,
            [[r["id"], r["label"], r["defect_type"] or "", r["side"], Path(r["path"]).name] for r in s],
            [None if r["label"] == "OK" else theme.NG_TINT for r in s],
        )
        for i, r in enumerate(s):
            self.samples.item(i, 4).setToolTip(r["path"])
        n_ok = sum(r["label"] == "OK" for r in s)
        ref = self.ctx.reference_image(self.board_model)
        self.counts.setText(
            f"{n_ok} OK · {len(s) - n_ok} NG · reference: {Path(ref).name if ref else 'none'}"
            + ("" if n_ok >= 20 else "  ·  tip: 20+ OK images give a steadier threshold")
        )
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

    def on_board_model_changed(self, name):
        self.preview.set_image(None)
        self.refresh()

    def on_show(self):
        self.refresh()
