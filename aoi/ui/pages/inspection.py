"""Main Inspection Screen (spec 4.1)."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, TypeAlias

from PySide6.QtCore import Qt
from PySide6.QtGui import QKeySequence
from PySide6.QtWidgets import (
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
from ...core.explain import notes
from ...core.imaging import IMAGE_EXTS, list_images, save_image
from ...core.inspector import NG, InspectionResult, draw_overlay
from ...core.services import AppContext
from ...errors import AoiError
from ...hal import VIEWS
from ...times import to_local
from .. import theme
from ..widgets.empty_state import EmptyState
from ..widgets.image_view import ImageView
from ..workers import Worker, start
from .base import (
    QT_TRANSLATE_NOOP,
    Page,
    action_button,
    button,
    cell_text,
    fill_table,
    make_table,
    sentence_text,
    size_class,
    view_text,
)

if TYPE_CHECKING:
    from ...core.inspector import Inspector  # a type hint only: a page never builds one (REQ-USR-001)
    from ..main_window import MainWindow


# A board's pool job hands the result slot: board, result, engine, record id, save error (one of the last two is None).
Outcome: TypeAlias = "tuple[Path, InspectionResult, Inspector, int | None, Exception | None]"

NO_VERDICT = "—"  # the banner before the first board


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
        self.last_id: int | None = None  # the record of the last result, for Compare (REQ-INSP-009)
        self.inspector: Inspector | None = None  # built on the first board for the board model, recipe and reference
        self._engine_gen = 0  # counts the times the engine was dropped, so a board's engine from before is not kept
        # The board being inspected, if one is: Start and Next Board wait for it (#120).
        self.worker: Worker | None = None

        # Source bar. Every control is an action with a key (REQ-INSP-005); the keys work wherever the focus is on
        # this page, and only while this page is shown.
        self.act_load = self.action(self.tr("Load Images…"), QKeySequence.StandardKey.Open, self.load_files)
        self.act_folder = self.action(self.tr("Load Folder…"), "Ctrl+Shift+O", self.load_folder)
        self.act_view = self.action(self.tr("Next view"), "Alt+V", self.next_view)
        bar = QHBoxLayout()
        self.btn_load = size_class(action_button(self.act_load, show_key=False), "T")  # 48 px: the sketch's size T
        self.btn_folder = size_class(action_button(self.act_folder, show_key=False), "T")
        bar.addWidget(self.btn_load)
        bar.addWidget(self.btn_folder)
        bar.addWidget(QLabel(self.tr("View:")))
        self.view_combo = QComboBox()
        for view in VIEWS:
            self.view_combo.addItem(view_text(view), view)  # the English name is the key the engine stores
        bar.addWidget(size_class(self.view_combo, "T"))
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
        self.verdict = QLabel(NO_VERDICT)
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

        # Run controls (sketch: inspection-run-controls.md): F5, F6, F8, F9 and the large buttons do the same
        self.act_start = self.action(self.tr("▶  Start"), "F5", self.start_run)
        self.act_stop = self.action(self.tr("■  Stop"), "F6", self.stop_run)
        self.act_next = self.action(self.tr("Next Board"), "F8", self.next_board)
        self.act_save = self.action(self.tr("Save Image…"), "F9", self.save_annotated_image)
        ctl = QGridLayout()
        self.btn_start = action_button(self.act_start, "start")
        self.btn_stop = action_button(self.act_stop, "stop")
        self.btn_next = action_button(self.act_next, "primary")
        self.btn_save = action_button(self.act_save)
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
        """F5: inspect the queue board after board until Stop or the end of the queue."""
        if not self.need_board_model():
            return
        self.running = True
        self._update_buttons()
        self.next_board()

    def stop_run(self) -> None:
        """F6: stop after the board being inspected; nothing is deleted, so no confirmation."""
        self.running = False
        if self.worker is not None:
            self.shell.status(self.tr("Stopping after this board…"), ms=0)  # until the board's result replaces it
        else:
            self.shell.status(self.tr("Stopped"))
        self._update_buttons()

    def next_view(self) -> None:
        """Alt+V: cycle the View box (Top, Side, Bottom); the next board carries the new view (REQ-INSP-010)."""
        self.view_combo.setCurrentIndex((self.view_combo.currentIndex() + 1) % self.view_combo.count())
        self.shell.status(self.tr("View: {view}").format(view=self.view_combo.currentText()))

    def next_board(self) -> None:
        """F8: inspect the next board of the queue on the pool thread; one board at a time per page (#120)."""
        if self.worker is not None or (bm := self.checked_board_model()) is None:
            return
        if self.queue_pos + 1 >= len(self.queue):
            self.running = False
            self.shell.status(self.tr("End of queue"))
            self._update_buttons()
            return
        self.queue_pos += 1
        path = self.queue[self.queue_pos]
        view = str(self.view_combo.currentData())  # the English key the engine stores on every defect
        insp = self.inspector  # None on the first board: built on the pool thread, so no key waits for a model load
        gen = self._engine_gen  # the engine this board builds is kept only while nothing has dropped it meanwhile

        def inspect() -> Outcome:
            engine = insp if insp is not None else self.ctx.inspector(bm, side=view)
            engine.side = view  # one worker at a time per page, so nothing else reads it meanwhile
            res = engine.inspect(self.ctx.load_image(path))
            w.signals.progress.emit(res)  # the verdict first, while the save runs; w is bound before the job starts
            try:  # saved here, on the pool thread, before the result slot can start the next board (REQ-INSP-008)
                iid = self.ctx.log_result(bm, str(path), res, engine)
            except Exception as e:  # the verdict is still shown; the missing record stops the run (_not_saved)
                return path, res, engine, None, e
            return path, res, engine, iid, None

        w = self.worker = Worker(inspect)
        self._show_busy(path)  # the response to the action, before the pool thread has started (REQ-INSP-005)
        self._update_buttons()

        def result(out: Outcome) -> None:
            if self.worker is w:
                self.worker = None  # before _on_result, which may start the next board of a run
                self._update_buttons()  # the controls follow the worker at once, not at the finished signal
            if insp is None and self.inspector is None and gen == self._engine_gen and bm == self.board_model:
                self.inspector = out[2]  # the engine this board built serves the rest of the queue
                if out[2].model is None:
                    msg = self.tr("No AI model for {board_model} yet: only the Golden board comparison runs").format(
                        board_model=bm
                    )
                    self._alarm("WARN", msg, "AOI-TRN-003")
            self._on_result(out)

        def done() -> None:
            if self.worker is w:
                self.worker = None
            self._update_buttons()

        w.signals.progress.connect(self._show_verdict)  # painted within 100 ms of the engine's result (REQ-INSP-002)
        w.signals.result.connect(result)
        w.signals.error.connect(lambda e: self._not_inspected(path, e))
        w.signals.finished.connect(done)
        start(w, self.ctx.jobs)

    def _not_inspected(self, path: Path, e: BaseException) -> None:
        """The board was not inspected: the run stops, the banner goes back to the last verdict, and the coded dialog
        says what happened and what to do (REQ-SET-019); Next Board carries on with the queue."""
        self.running = False
        self._show_verdict(self.last)
        summary = self.tr("{file}  ·  not inspected").format(file=path.name)
        self.summary.setText(summary)
        self.shell.status(summary)
        self.error(e)
        self._refresh_alarms()

    def _show_busy(self, path: Path) -> None:
        """The banner turns grey with "Inspecting…" the moment a board starts (sketch: the busy pattern), painted at
        once so the response to Start or Next Board is on screen within the action itself (REQ-INSP-005)."""
        self.verdict.setText(self.tr("Inspecting…"))
        self.verdict.setStyleSheet(theme.verdict_style("INFO"))
        self.verdict.repaint()
        self.summary.setText(self.tr("Inspecting {file}…").format(file=path.name))
        status = self.tr("Inspecting {file} ({n} of {total})…")
        busy = status.format(file=path.name, n=self.queue_pos + 1, total=len(self.queue))
        self.shell.status(busy, ms=0)  # stays until the result or the error replaces it, however long the board takes

    def _show_verdict(self, res: InspectionResult | None) -> None:
        """The verdict banner: colour, shape and word (REQ-INSP-002), painted at once; the idle banner without one."""
        self.verdict.setText(theme.verdict_label(res.verdict) if res is not None else NO_VERDICT)
        self.verdict.setStyleSheet(theme.verdict_style(res.verdict if res is not None else "INFO"))
        self.verdict.repaint()

    def _on_result(self, out: Outcome) -> None:
        path, res, _engine, iid, save_error = out
        self.last, self.last_path, self.last_id = res, path, iid
        self._show_verdict(res)  # painted before the image and the table are built: the verdict first (REQ-INSP-002)
        self.empty.hide()
        self.view.set_image(res.image, keep_view=self.queue_pos > 0)
        for d in res.defects:
            sev = taxonomy.BY_NAME.get(d.type, taxonomy.ANOMALY).severity
            self.view.add_box(
                d.x, d.y, d.w, d.h, theme.SEVERITY_COLORS.get(sev, theme.NG_COLOR), f"{d.no} {d.type} {d.score:.2f}"
            )
        summary = self.tr("{file}  ·  AI score {score:.2f}× threshold  ·  {defects} defect(s)  ·  {ms:.0f} ms").format(
            file=path.name, score=res.score, defects=len(res.defects), ms=res.elapsed_ms
        )
        self.summary.setText("\n".join([summary, *(sentence_text(s) for s in notes(res))]))  # checks that did not run
        self.shell.status(summary)  # in place of "Inspecting …"
        fill_table(self.table, [[d.no, d.type, d.score, view_text(d.side), d.x, d.y] for d in res.defects])
        self.shell.last_inspected = (str(path), res, iid)
        # Saved with its evidence on the pool thread (REQ-INSP-008, REQ-SET-021); a failed save stops the run here.
        if save_error is not None:
            self._not_saved(path, save_error)
            return
        if res.verdict == NG:
            self._refresh_alarms()
        if self.running:
            self.next_board()

    def _not_saved(self, path: Path, e: BaseException) -> None:
        """The result was shown but could not be saved (the disk is full, the workspace cannot be written, a database
        error): the run stops before the next board, the coded dialog says what happened and what to do, and the
        verdict stays on screen (REQ-INSP-008, REQ-SET-019); Next Board carries on with the queue."""
        self.running = False
        self._update_buttons()
        err = AoiError("AOI-INSP-008", detail=f"{type(e).__name__}: {e}", file=path.name)
        err.__cause__ = e  # the log keeps the cause with its trace
        self.error(err)
        self._refresh_alarms()

    def save_annotated_image(self) -> None:
        """F9: write the last board's image with its defect boxes to a picture file; the result itself is saved."""
        res, path = self.last, self.last_path
        if res is None or path is None:
            return
        f, _ = QFileDialog.getSaveFileName(
            self, self.tr("Save annotated image"), f"{path.stem}_{res.verdict}.png", self.tr("PNG (*.png)")
        )
        if f:
            save_image(f, draw_overlay(res))
            self.shell.status(self.tr("Saved {file}").format(file=Path(f).name))

    def open_compare(self) -> None:
        """Compare on the last result in one click: its record as decided (REQ-INSP-009), or its file when not saved."""
        if self.last_id is not None:
            self.shell.open_stored(self.last_id)
        elif self.last_path:
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
        """Enable the actions, and with them the buttons and the keys, for the state: Start and Next Board wait while a
        board is being inspected (#120), Stop acts while a run is on, Save Image… once there is a result."""
        has, busy = bool(self.queue), self.worker is not None
        self.act_start.setEnabled(has and not self.running and not busy)
        self.act_stop.setEnabled(self.running)
        self.act_next.setEnabled(has and not self.running and not busy)
        self.act_save.setEnabled(self.last is not None)

    def _drop_engine(self) -> None:
        """The next board builds the engine again, and an engine a board is building at this moment is not kept when
        it arrives: a board model change or a page revisit during the first board must not leave a stale engine."""
        self.inspector = None
        self._engine_gen += 1

    def on_board_model_changed(self, name: str | None) -> None:
        self._drop_engine()  # rebuilt lazily with the new model/recipe/reference
        self._show_empty()

    def on_show(self) -> None:
        self._drop_engine()  # pick up newly trained models or saved recipes
        self._refresh_alarms()
        self._show_empty()
