"""Main Inspection Screen (spec 4.1)."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFileDialog,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from ... import defects as taxonomy
from ...core.imaging import IMAGE_EXTS, list_images, load_image, save_image
from ...core.inspector import InspectionResult, draw_overlay
from ...hal import VIEWS
from ...times import to_local
from ..theme import verdict_style
from ..widgets.image_view import ImageView
from ..workers import Worker, start
from .base import Page, button, fill_table, make_table


def alarm_line(time_iso: str, level: str, code: str | None, msg: str) -> str:
    """ISO date, 24-hour local time, level, code and message, as REQ-INSP-006 asks."""
    return "  ".join(part for part in (to_local(time_iso), f"[{level}]", code or "", msg) if part)


class InspectionPage(Page):
    title = "Inspection"
    subtitle = "Stage 1: uploaded images  ·  Stage 2: live camera feed"

    def __init__(self, ctx, shell):
        super().__init__(ctx, shell)
        self.queue: list[Path] = []
        self.pos = -1
        self.running = False
        self.last: InspectionResult | None = None
        self.last_path: Path | None = None
        self.inspector = None

        # Source bar
        bar = QHBoxLayout()
        bar.addWidget(button("Load Images…", slot=self.load_files))
        bar.addWidget(button("Load Folder…", slot=self.load_folder))
        bar.addWidget(QLabel("View:"))
        self.view_combo = QComboBox()
        self.view_combo.addItems(VIEWS)
        bar.addWidget(self.view_combo)
        self.autosave = QCheckBox("Auto-save each board")
        self.autosave.setChecked(True)
        bar.addWidget(self.autosave)
        bar.addStretch(1)
        self.queue_label = QLabel("No images loaded")
        self.queue_label.setObjectName("muted")
        bar.addWidget(self.queue_label)
        self.root.addLayout(bar)

        # Center: image | results
        split = QSplitter(Qt.Horizontal)
        self.view = ImageView(placeholder="Load PCB images to start inspection")
        split.addWidget(self.view)

        side = QWidget()
        sl = QVBoxLayout(side)
        sl.setContentsMargins(8, 0, 0, 0)
        self.verdict = QLabel("—")
        self.verdict.setStyleSheet(verdict_style("INFO"))
        self.verdict.setMinimumHeight(90)
        sl.addWidget(self.verdict)
        self.summary = QLabel("")
        self.summary.setObjectName("muted")
        self.summary.setWordWrap(True)
        sl.addWidget(self.summary)
        self.table = make_table(["No", "Type", "Score", "Side", "X", "Y"])
        self.table.itemSelectionChanged.connect(self._focus_defect)
        sl.addWidget(self.table, 1)
        sl.addWidget(button("Compare with Golden ›", slot=self.open_compare))
        split.addWidget(side)
        split.setSizes([1100, 520])
        self.root.addWidget(split, 1)

        # Controls (large buttons)
        ctl = QGridLayout()
        self.btn_start = button("▶  Start", "start", self.start_run)
        self.btn_stop = button("■  Stop", "stop", self.stop_run)
        self.btn_next = button("Next Board", "primary", self.next_board)
        self.btn_save = button("Save Result", slot=self.save_result)
        for i, b in enumerate((self.btn_start, self.btn_stop, self.btn_next, self.btn_save)):
            b.setMinimumHeight(54)
            ctl.addWidget(b, 0, i)
        self.root.addLayout(ctl)

        # Alarm log
        self.alarms = QListWidget()
        self.alarms.setMaximumHeight(110)
        self.root.addWidget(self.alarms)
        self._update_buttons()

    # --- sources ---------------------------------------------------------------
    def load_files(self):
        exts = " ".join(f"*{e}" for e in sorted(IMAGE_EXTS))
        files, _ = QFileDialog.getOpenFileNames(self, "Select PCB images", "", f"Images ({exts})")
        if files:
            self._set_queue([Path(f) for f in files])

    def load_folder(self):
        d = QFileDialog.getExistingDirectory(self, "Select folder with PCB images")
        if d:
            self._set_queue(list_images(d))

    def _set_queue(self, paths: list[Path]):
        self.queue, self.pos = paths, -1
        self.queue_label.setText(f"{len(paths)} image(s) queued")
        self.shell.status(f"Loaded {len(paths)} image(s)")
        self._update_buttons()

    # --- run control -------------------------------------------------------------
    def start_run(self):
        if not self.need_board_model():
            return
        self.running = True
        self._update_buttons()
        self.next_board()

    def stop_run(self):
        self.running = False
        self._update_buttons()

    def next_board(self):
        if not self.need_board_model():
            return
        if self.pos + 1 >= len(self.queue):
            self.running = False
            self.shell.status("End of queue")
            self._update_buttons()
            return
        self.pos += 1
        path = self.queue[self.pos]
        if self.inspector is None:
            try:
                self.inspector = self.ctx.inspector(self.board_model, side=self.view_combo.currentText())
            except Exception as e:
                return self.error(e)
            if self.inspector.model is None:
                msg = f"No trained model for {self.board_model}: only golden comparison runs"
                self._alarm("WARN", msg, "AOI-TRN-003")
        self.inspector.side = self.view_combo.currentText()
        self.btn_next.setEnabled(False)
        w = Worker(lambda: (path, self.inspector.inspect(load_image(path))))
        w.signals.result.connect(self._on_result)
        w.signals.error.connect(lambda e: (self.error(e), self.stop_run(), self._refresh_alarms()))
        w.signals.finished.connect(self._update_buttons)
        start(w, self.ctx.jobs)

    def _on_result(self, out):
        path, res = out
        self.last, self.last_path = res, path
        self.view.set_image(res.image, keep_view=self.pos > 0)
        for d in res.defects:
            sev = taxonomy.BY_NAME.get(d.type, taxonomy.ANOMALY).severity
            self.view.add_box(
                d.x, d.y, d.w, d.h, taxonomy.SEVERITY_COLOR.get(sev, "#e53935"), f"{d.no} {d.type} {d.score:.2f}"
            )
        self.verdict.setText(res.verdict)
        self.verdict.setStyleSheet(verdict_style(res.verdict))
        self.summary.setText(
            f"{path.name}  ·  score {res.score:.2f}× threshold  ·  "
            f"{len(res.defects)} defect(s)  ·  {res.elapsed_ms:.0f} ms"
            + ("\n" + "\n".join(res.notes) if res.notes else "")
        )
        fill_table(self.table, [[d.no, d.type, d.score, d.side, d.x, d.y] for d in res.defects])
        self.shell.last_inspected = (str(path), res)
        if self.autosave.isChecked():
            self.ctx.log_result(self.board_model, str(path), res, self.inspector)  # an NG result stores an alarm
            self._refresh_alarms()
        if self.running:
            self.next_board()

    def save_result(self):
        if not self.last:
            return
        f, _ = QFileDialog.getSaveFileName(
            self, "Save annotated image", f"{self.last_path.stem}_{self.last.verdict}.png", "PNG (*.png)"
        )
        if f:
            save_image(f, draw_overlay(self.last))
            if not self.autosave.isChecked():
                self.ctx.log_result(self.board_model, str(self.last_path), self.last, self.inspector)
                self._refresh_alarms()
            self.shell.status(f"Saved {Path(f).name}")

    def open_compare(self):
        if self.last_path:
            self.shell.open_compare(str(self.last_path))

    # --- helpers -------------------------------------------------------------------
    def _focus_defect(self):
        rows = self.table.selectionModel().selectedRows()
        if rows and self.last:
            no = int(self.table.item(rows[0].row(), 0).text())
            d = next((d for d in self.last.defects if d.no == no), None)
            if d:
                self.view.center_on_box(d.x, d.y, d.w, d.h)

    def _alarm(self, level: str, msg: str, code: str):
        """Store an alarm with its code, so it survives a restart, and show the list again (REQ-INSP-006)."""
        self.ctx.alarm(level, msg, code)
        self._refresh_alarms()

    def _refresh_alarms(self):
        self.alarms.clear()
        for a in self.ctx.alarms():
            self.alarms.addItem(alarm_line(a["time"], a["level"], a["code"], a["message"]))

    def _update_buttons(self):
        has = bool(self.queue)
        self.btn_start.setEnabled(has and not self.running)
        self.btn_stop.setEnabled(self.running)
        self.btn_next.setEnabled(has and not self.running)
        self.btn_save.setEnabled(self.last is not None)

    def on_board_model_changed(self, name):
        self.inspector = None  # rebuilt lazily with the new model/recipe/reference

    def on_show(self):
        self.inspector = None  # pick up newly trained models or saved recipes
        self._refresh_alarms()
