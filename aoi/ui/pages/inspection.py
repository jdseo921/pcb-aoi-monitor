"""Main Inspection Screen (spec 4.1)."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

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
from ...core.imaging import IMAGE_EXTS, list_images, save_image
from ...core.inspector import InspectionResult, draw_overlay
from ...core.services import AppContext
from ...hal import VIEWS
from ...times import to_local
from .. import theme
from ..widgets.empty_state import EmptyState
from ..widgets.image_view import ImageView
from ..workers import Worker, start
from .base import QT_TRANSLATE_NOOP, Page, button, cell_text, fill_table, make_table, size_class, view_text

if TYPE_CHECKING:
    from ...core.inspector import Inspector  # a type hint only: a page never builds one (REQ-USR-001)
    from ..main_window import MainWindow


def alarm_line(time_iso: str, level: str, code: str | None, msg: str) -> str:
    """ISO date, 24-hour local time, level, code and message, as REQ-INSP-006 asks."""
    return "  ".join(part for part in (to_local(time_iso), f"[{level}]", code or "", msg) if part)


class InspectionPage(Page):
    title = QT_TRANSLATE_NOOP("Page", "Inspection")
    subtitle = QT_TRANSLATE_NOOP("Page", "Stage 1: uploaded images  ·  Stage 2: live camera feed")

    def __init__(self, ctx: AppContext, shell: MainWindow) -> None:
        super().__init__(ctx, shell)
        self.queue: list[Path] = []
        self.queue_pos = -1
        self.running = False
        self.last: InspectionResult | None = None
        self.last_path: Path | None = None
        self.last_inspector: Inspector | None = None  # produced `last`; a saved result records its model version
        self.inspector: Inspector | None = None  # built on the first board for the board model, recipe and reference

        # Source bar
        bar = QHBoxLayout()
        bar.addWidget(button(self.tr("Load Images…"), slot=self.load_files))
        bar.addWidget(button(self.tr("Load Folder…"), slot=self.load_folder))
        bar.addWidget(QLabel(self.tr("View:")))
        self.view_combo = QComboBox()
        for view in VIEWS:
            self.view_combo.addItem(view_text(view), view)  # the English name is the key the engine stores
        bar.addWidget(self.view_combo)
        self.autosave = QCheckBox(self.tr("Auto-save each board"))
        self.autosave.setChecked(True)
        bar.addWidget(self.autosave)
        bar.addStretch(1)
        self.queue_label = QLabel(self.tr("No images loaded"))
        self.queue_label.setObjectName("muted")
        bar.addWidget(self.queue_label)
        self.root.addLayout(bar)

        # Center: image | results
        split = QSplitter(Qt.Orientation.Horizontal)
        self.view = ImageView(placeholder="")
        self.empty = EmptyState(self.view)
        split.addWidget(self.view)

        side = QWidget()
        sl = QVBoxLayout(side)
        sl.setContentsMargins(8, 0, 0, 0)
        self.verdict = QLabel("—")
        self.verdict.setStyleSheet(theme.verdict_style("INFO"))
        self.verdict.setMinimumHeight(theme.BANNER_H)
        sl.addWidget(self.verdict)
        self.summary = QLabel("")
        self.summary.setObjectName("muted")
        self.summary.setWordWrap(True)
        sl.addWidget(self.summary)
        self.table = make_table(
            [
                self.tr("No", "defect number"),
                self.tr("Type"),
                self.tr("Score"),
                self.tr("Side"),
                self.tr("X"),
                self.tr("Y"),
            ]
        )
        self.table.verticalHeader().setDefaultSectionSize(theme.TARGET_H)  # a defect row is an operator target
        self.table.itemSelectionChanged.connect(self._focus_defect)
        sl.addWidget(self.table, 1)
        sl.addWidget(button(self.tr("Compare with Golden board ›"), slot=self.open_compare))
        split.addWidget(side)
        split.setSizes([1100, 520])
        self.root.addWidget(split, 1)

        # Controls (large buttons)
        ctl = QGridLayout()
        self.btn_start = button(self.tr("▶  Start"), "start", self.start_run)
        self.btn_stop = button(self.tr("■  Stop"), "stop", self.stop_run)
        self.btn_next = button(self.tr("Next Board"), "primary", self.next_board)
        self.btn_save = button(self.tr("Save Result"), slot=self.save_result)
        for i, b in enumerate((self.btn_start, self.btn_stop, self.btn_next, self.btn_save)):
            ctl.addWidget(size_class(b, "T+"), 0, i)  # 56 px tall through the stylesheet
        self.root.addLayout(ctl)

        # Alarm log
        self.alarms = QListWidget()
        self.alarms.setMaximumHeight(110)
        self.root.addWidget(self.alarms)
        self._update_buttons()

    def _show_empty(self) -> None:
        if self.last is not None:
            self.empty.hide()
        elif not self.board_model:
            self.empty.show_state(*self.no_board_model())
        elif not self.queue:
            what = self.tr("Load Images… or Load Folder… to queue boards. In Stage 2 the camera fills this view.")
            self.empty.show_state(self.tr("No images loaded"), what, self.tr("Load Images…"), self.load_files)
        else:
            self.empty.hide()

    # --- sources ---------------------------------------------------------------
    def load_files(self) -> None:
        exts = " ".join(f"*{e}" for e in sorted(IMAGE_EXTS))
        files, _ = QFileDialog.getOpenFileNames(
            self, self.tr("Select PCB images"), "", self.tr("Images ({extensions})").format(extensions=exts)
        )
        if files:
            self._set_queue([Path(f) for f in files])

    def load_folder(self) -> None:
        d = QFileDialog.getExistingDirectory(self, self.tr("Select folder with PCB images"))
        if d:
            self._set_queue(list_images(d))

    def _set_queue(self, paths: list[Path]) -> None:
        self.queue, self.queue_pos = paths, -1
        self.queue_label.setText(self.tr("{count} image(s) queued").format(count=len(paths)))
        self.shell.status(self.tr("Loaded {count} image(s)").format(count=len(paths)))
        self._update_buttons()
        self._show_empty()

    # --- run control -------------------------------------------------------------
    def start_run(self) -> None:
        if not self.need_board_model():
            return
        self.running = True
        self._update_buttons()
        self.next_board()

    def stop_run(self) -> None:
        self.running = False
        self._update_buttons()

    def next_board(self) -> None:
        if (bm := self.checked_board_model()) is None:
            return
        if self.queue_pos + 1 >= len(self.queue):
            self.running = False
            self.shell.status(self.tr("End of queue"))
            self._update_buttons()
            return
        self.queue_pos += 1
        path = self.queue[self.queue_pos]
        insp = self.inspector
        if insp is None:
            try:
                insp = self.ctx.inspector(bm, side=str(self.view_combo.currentData()))
            except Exception as e:
                self.error(e)
                return
            self.inspector = insp
            if insp.model is None:
                msg = self.tr("No AI model for {board_model} yet: only the Golden board comparison runs").format(
                    board_model=bm
                )
                self._alarm("WARN", msg, "AOI-TRN-003")
        insp.side = str(self.view_combo.currentData())  # the English key the engine stores on every defect
        self.btn_next.setEnabled(False)
        w = Worker(lambda: (path, insp.inspect(self.ctx.load_image(path)), insp))

        def failed(e: BaseException) -> None:
            self.error(e)
            self.stop_run()
            self._refresh_alarms()

        w.signals.result.connect(self._on_result)
        w.signals.error.connect(failed)
        w.signals.finished.connect(self._update_buttons)
        start(w, self.ctx.jobs)

    def _on_result(self, out: tuple[Path, InspectionResult, Inspector]) -> None:
        path, res, insp = out
        self.last, self.last_path, self.last_inspector = res, path, insp
        self.empty.hide()
        self.view.set_image(res.image, keep_view=self.queue_pos > 0)
        for d in res.defects:
            sev = taxonomy.BY_NAME.get(d.type, taxonomy.ANOMALY).severity
            self.view.add_box(
                d.x, d.y, d.w, d.h, theme.SEVERITY_COLORS.get(sev, theme.NG_COLOR), f"{d.no} {d.type} {d.score:.2f}"
            )
        self.verdict.setText(theme.verdict_label(res.verdict))
        self.verdict.setStyleSheet(theme.verdict_style(res.verdict))
        summary = self.tr("{file}  ·  AI score {score:.2f}× threshold  ·  {defects} defect(s)  ·  {ms:.0f} ms").format(
            file=path.name, score=res.score, defects=len(res.defects), ms=res.elapsed_ms
        )
        self.summary.setText("\n".join([summary, *res.notes]))
        fill_table(self.table, [[d.no, d.type, d.score, view_text(d.side), d.x, d.y] for d in res.defects])
        self.shell.last_inspected = (str(path), res)
        if self.autosave.isChecked():
            self.ctx.log_result(insp.recipe.board_model, str(path), res, insp)  # an NG result stores an alarm
            self._refresh_alarms()
        if self.running:
            self.next_board()

    def save_result(self) -> None:
        res, path, insp = self.last, self.last_path, self.last_inspector
        if res is None or path is None or insp is None:
            return
        f, _ = QFileDialog.getSaveFileName(
            self, self.tr("Save annotated image"), f"{path.stem}_{res.verdict}.png", self.tr("PNG (*.png)")
        )
        if f:
            save_image(f, draw_overlay(res))
            if not self.autosave.isChecked():
                self.ctx.log_result(insp.recipe.board_model, str(path), res, insp)
                self._refresh_alarms()
            self.shell.status(self.tr("Saved {file}").format(file=Path(f).name))

    def open_compare(self) -> None:
        if self.last_path:
            self.shell.open_compare(str(self.last_path))

    # --- helpers -------------------------------------------------------------------
    def _focus_defect(self) -> None:
        rows = self.table.selectionModel().selectedRows()
        if rows and self.last:
            no = int(cell_text(self.table, rows[0].row(), 0))
            d = next((d for d in self.last.defects if d.no == no), None)
            if d:
                self.view.center_on_box(d.x, d.y, d.w, d.h)

    def _alarm(self, level: str, msg: str, code: str) -> None:
        """Store an alarm with its code, so it survives a restart, and show the list again (REQ-INSP-006)."""
        self.ctx.alarm(level, msg, code)
        self._refresh_alarms()

    def _refresh_alarms(self) -> None:
        self.alarms.clear()
        for a in self.ctx.alarms():
            self.alarms.addItem(alarm_line(a["time"], a["level"], a["code"], a["message"]))

    def _update_buttons(self) -> None:
        has = bool(self.queue)
        self.btn_start.setEnabled(has and not self.running)
        self.btn_stop.setEnabled(self.running)
        self.btn_next.setEnabled(has and not self.running)
        self.btn_save.setEnabled(self.last is not None)

    def on_board_model_changed(self, name: str | None) -> None:
        self.inspector = None  # rebuilt lazily with the new model/recipe/reference
        self._show_empty()

    def on_show(self) -> None:
        self.inspector = None  # pick up newly trained models or saved recipes
        self._refresh_alarms()
        self._show_empty()
