"""Main Inspection Screen (spec 4.1)."""

from __future__ import annotations

import weakref
from collections.abc import Callable
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
from ...core.imaging import IMAGE_EXTS, list_images
from ...core.inspector import NG, InspectionResult
from ...core.services import BUSY_ALARM_WAIT_MS, REQUIRED_ROLE, ROLES, Actor, AppContext
from ...errors import AoiError
from ...hal import VIEWS
from ...times import to_local
from .. import theme
from ..errors import alarm_text
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
        self.run_board_model: str | None = None  # the board model a run started under: its boards are judged under it
        self.run_actor: Actor = ctx.actor  # who pressed Start: every board of the run is recorded under them (#177)
        self.run_inputs: tuple[str | None, str | None, str | None] | None = None  # what judged the run's last board
        self.last: InspectionResult | None = None
        self.last_path: Path | None = None
        self.last_id: int | None = None  # the record of the last result, for Compare (REQ-INSP-009)
        self.last_board_model: str | None = None  # the board model it was inspected under
        # The empty state of a board that was not inspected (#182): heading, sentence, link and where it leads
        self.skipped: tuple[str, str, str, Callable[[], None]] | None = None
        self.inspector: Inspector | None = None  # built on a board, kept while it is what is active (#243)
        self._engine_gen = 0  # counts the times the engine was dropped, so a board's engine from before is not kept
        self._no_ai_warned: str | None = None  # the board model AOI-TRN-003 was stored for on this page visit (#243)
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
        self.btn_compare = button(self.tr("Compare with Golden board ›"), slot=self.open_compare)
        sl.addWidget(self.btn_compare)
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
        elif self.skipped is not None:  # until the next board starts: which board was not inspected, why, what next
            self.empty.show_state(*self.skipped)
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
        self.queue, self.queue_pos, self.skipped = paths, -1, None
        self._drop_engine()  # a new queue builds its engine from what is active (#243)
        self.queue_label.setText(self.tr("{count} image(s) queued").format(count=len(paths)))
        self.shell.status(self.tr("Loaded {count} image(s)").format(count=len(paths)))
        self._update_buttons()
        self._show_empty()

    # --- run control -------------------------------------------------------------
    def start_run(self) -> None:
        """F5: inspect the queue board after board until Stop or the end of the queue."""
        if not self.need_board_model():
            return
        self.running, self.run_board_model, self.run_actor = True, self.board_model, self.ctx.actor
        self.run_inputs = None
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
        if self.running and bm != self.run_board_model:  # no board of a run is judged under another board model (#172)
            self._stop_for_board_model(bm)
            return
        if self.queue_pos + 1 >= len(self.queue):
            self.running = False
            self.shell.status(self.tr("End of queue"))
            self._update_buttons()
            return
        if self.running and self.ctx.user != self.run_actor.name:  # a board of a run names who pressed Start (#177)
            self._stop_for_user()  # another user signed in; a change of the same user's role goes on
            return
        self.queue_pos += 1
        path = self.queue[self.queue_pos]
        view = str(self.view_combo.currentData())  # the English key the engine stores on every defect
        insp = self.inspector  # None on the first board: built on the pool thread, so no key waits for a model load
        gen = self._engine_gen  # the engine this board builds is kept only while nothing has dropped it meanwhile
        in_run = self.running

        def inspect() -> Outcome:
            # The kept engine only while it is what is active: a training run, an activation or a recipe saved while
            # the page stays shown makes it stale, and the board is judged with what is active now (#243).
            current = insp is not None and self.ctx.engine_is_current(bm, insp)
            engine = self.ctx.inspector(bm, side=view) if insp is None or not current else insp
            engine.side = view  # one worker at a time per page, so nothing else reads it meanwhile
            res = engine.inspect(self.ctx.load_image(path))
            report(res)  # the verdict first, while the save runs; bound before the job starts
            try:  # saved here, on the pool thread, before the result slot can start the next board (REQ-INSP-008)
                iid = self.ctx.log_result(bm, str(path), res, engine)
            except Exception as e:  # the verdict is still shown; the missing record stops the run (_not_saved)
                return path, res, engine, None, e
            return path, res, engine, iid, None

        w = self.worker = Worker(inspect)
        report, ref = w.signals.progress.emit, weakref.ref(w)  # the job and the slots never hold the worker or its
        # signals (#132): Qt keeps the slots as long as the signals, so the worker, its job and the board's result would
        # stay as long as the app runs, and signals the job held could be deleted on a pool thread, which Qt forbids
        self._show_busy(path)  # the response to the action, before the pool thread has started (REQ-INSP-005)
        self._update_buttons()

        def result(out: Outcome) -> None:
            if (worker := ref()) is not None and self.worker is worker:
                self.worker = None  # before _on_result, which may start the next board of a run
                self._update_buttons()  # the controls follow the worker at once, not at the finished signal
            engine, no_ai_model, moved = out[2], False, False
            if engine is not insp and gen == self._engine_gen and bm == self.board_model:
                self.inspector = engine  # the engine this board built serves the next boards while it is current
                # AOI-TRN-003 once per page visit and board model, not again for the engine each new queue builds
                no_ai_model = engine.model is None and self._no_ai_warned != bm
                self._no_ai_warned = bm if engine.model is None else None
            if in_run:  # a run judged with two AI models, recipes or Golden boards says so (#243)
                moved = self.run_inputs is not None and engine.inputs != self.run_inputs
                self.run_inputs = engine.inputs
            self._on_result(out)  # first: the result, and a failed save's error, never wait for the alarm below (#179)
            if no_ai_model:
                msg = self.tr("No AI model for {board_model} yet: only the Golden board comparison runs").format(
                    board_model=bm
                )
                self._alarm("WARN", msg, "AOI-TRN-003")
            if bm != self.board_model:  # the header moved on meanwhile: saved under bm, not the current board (#172)
                self._not_current(out, bm, in_run)
            if moved:  # after _not_current, whose line it is added to
                self._run_moved(out[0], engine)

        def done() -> None:
            if (worker := ref()) is not None and self.worker is worker:
                self.worker = None
            self._update_buttons()

        w.signals.progress.connect(self._show_verdict)  # painted within 100 ms of the engine's result (REQ-INSP-002)
        w.signals.result.connect(result)
        w.signals.error.connect(lambda e: self._not_inspected(path, e))
        w.signals.finished.connect(done)
        start(w, self.ctx.jobs)

    def _not_inspected(self, path: Path, e: BaseException) -> None:
        """The board was not inspected: the run stops, and the page shows that board, not the one before (#182): the
        banner reads "Not inspected" with its shape, the picture and the defect list go, Save Image… and Compare… have
        no result to act on, and the empty state names the board, the error's code and what happened, with Next Board
        to carry on with the queue, or Load Images… when it was the last board. The coded dialog says what happened and
        what to do (REQ-SET-019)."""
        self.running = False
        self.last = self.last_path = self.last_id = self.last_board_model = None
        heading, sentence = self.not_inspected(self.verdict, path.name, e)
        link, go = self.tr("Next Board ›"), self.next_board
        step = self.tr("Press Next Board to carry on with the queue.")
        if self.queue_pos + 1 >= len(self.queue):  # the last board: Next Board would only say "End of queue"
            step = self.tr("No board is left in the queue. Load Images… or Load Folder… to queue more boards.")
            link, go = self.tr("Load Images…"), self.load_files
        self.skipped = heading, " ".join([sentence, step]), link, go
        self.view.set_image(None)
        fill_table(self.table, [])
        summary = self.tr("{file}  ·  not inspected").format(file=path.name)
        self.summary.setText(summary)
        self.shell.status(summary)
        self._update_buttons()
        self._show_empty()
        self.error(e)
        self._refresh_alarms()

    def _not_current(self, out: Outcome, bm: str, in_run: bool) -> None:
        """A board whose result arrived after the header's board model changed is saved under `bm`, the board model it
        was inspected under, and is not the current board: the page clears it as on_board_model_changed clears the
        board shown, so no verdict, picture or defect row is left with a Compare and rows that do nothing, and the line
        under the banner names the board, its verdict and `bm` until the next board; the status line says the same
        until the next line (#243). Its record is on Logs & Export; a failed save said so with AOI-INSP-008. The board
        of a run, which the change stopped, adds how to carry on with the queue, as the "Run stopped" line it replaces
        in the status bar said."""
        path, res, _engine, iid, _error = out
        self.last = self.last_path = self.last_id = self.last_board_model = self.shell.last_inspected = None
        self.view.set_image(None)
        fill_table(self.table, [])
        self._show_verdict(None)
        note = self.tr(
            "{file} was inspected under board model {board_model} and judged {verdict}; the header now shows {header}."
        ).format(file=path.name, board_model=bm, verdict=res.verdict, header=self.board_model or NO_VERDICT)
        parts = [note]
        if iid is not None:
            parts.append(self.tr("Its record is on Logs & Export under {board_model}.").format(board_model=bm))
        if in_run and self.queue_pos + 1 < len(self.queue):
            step = self.tr("The run stopped; press Start to carry on with the queue under {header}.")
            parts.append(step.format(header=self.board_model or NO_VERDICT))
        note = " ".join(parts)
        self.summary.setText(note)
        self.shell.status(note, ms=0)
        self._update_buttons()
        self._show_empty()

    def _show_busy(self, path: Path) -> None:
        """The banner turns grey with "Inspecting…" the moment a board starts (sketch: the busy pattern), painted at
        once so the response to Start or Next Board is on screen within the action itself (REQ-INSP-005)."""
        self.verdict.setText(self.tr("Inspecting…"))
        self.verdict.setStyleSheet(theme.verdict_style("INFO"))
        self.verdict.repaint()
        if self.skipped is not None:  # the board that was not inspected is no longer the one in hand
            self.skipped = None
            self._show_empty()
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
        self.last, self.last_path, self.last_id, self.last_board_model = res, path, iid, self.board_model
        self._update_buttons()  # Save Image… and Compare on with the result, not at the finished slot (#241 review)
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
        """F9: write the last board's picture with its defect boxes to a file the user names; the result itself is
        saved. `AppContext.export_board_image` writes it on the pool (REQ-SET-021) as the user who pressed F9, checks
        the role and records the picture in the audit trail with the record and where it went (#241, REQ-LOG-004); a
        name with no image format (AOI-INSP-002) or a file that cannot be written (AOI-LOG-002) shows a coded error."""
        # All of the board read before the dialog, whose event loop lets a run go on: a board finishing or a board
        # model change meanwhile replaces them, and the entry would name another record than the picture's (#241 review)
        res, path, iid, board_model = self.last, self.last_path, self.last_id, self.last_board_model
        if res is None or path is None or self._bg is not None:  # one save at a time: a second would stop the first
            return
        f, _ = QFileDialog.getSaveFileName(
            self, self.tr("Save annotated image"), f"{path.stem}_{res.verdict}.png", self.tr("PNG (*.png)")
        )
        if not f:
            return
        saved = self.tr("Saved {file}").format(file=Path(f).name)
        board = (res, board_model, iid, path.name)
        self.run_in_background(self.ctx.export_board_image, *board, f, on_result=lambda _: self.shell.status(saved))

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
        """Store an alarm with its code, so it survives a restart, and show the list again (REQ-INSP-006). It never
        raises, as report_error since #171: an alarm the database refuses (another program holds its write lock, the
        disk is full) is logged, and the result, the run's stop or the board model change that raised it goes on. It
        waits BUSY_ALARM_WAIT_MS for that lock, not SQLite's 5 s on the UI thread (#195 review); a board the pool thread
        is saving at that moment holds the database first, up to 5 s."""
        try:
            self.ctx.alarm(level, msg, code, wait_ms=BUSY_ALARM_WAIT_MS)
        except Exception:  # #179: it replaced the result's own error with AOI-SET-007 and left the run on
            self.ctx.log.warning("alarm.not_stored", exc_info=True, extra={"code": code})
        self._refresh_alarms()

    def _refresh_alarms(self) -> None:
        """Show the stored alarms again; when the database cannot be read, the list keeps what it showed (#179)."""
        try:
            rows = self.ctx.alarms()
        except Exception:
            self.ctx.log.warning("alarms.not_read", exc_info=True)
            return
        self.alarms.clear()
        for a in rows:
            self.alarms.addItem(alarm_line(a["time"], a["level"], a["code"], alarm_text(a)))

    def _update_buttons(self) -> None:
        """Enable the actions, and with them the buttons and the keys, for the state: Start and Next Board need a queue
        and a board model in the header (#244: with none, neither can run, and an Operator cannot create one) and wait
        while a board is being inspected (#120), Stop acts while a run is on, Save Image… once there is a result, for a
        role `export_board_image` allows and while no save runs (#241), and Compare while there is a record or a file to
        open (#243): not before the first board, after a board that was not inspected, or after a board model change."""
        has, busy = bool(self.queue) and self.board_model is not None, self.worker is not None
        self.act_start.setEnabled(has and not self.running and not busy)
        self.act_stop.setEnabled(self.running)
        self.act_next.setEnabled(has and not self.running and not busy)
        need = ROLES.index(REQUIRED_ROLE["export_board_image"])  # the service's @requires, never written out again here
        may_save = self.ctx.role in ROLES and ROLES.index(self.ctx.role) >= need
        self.act_save.setEnabled(self.last is not None and may_save and self._bg is None)
        self.btn_compare.setEnabled(self.last_id is not None or self.last_path is not None)

    def update_actions(self) -> None:
        """A Save Image… job starting or ending (`run_in_background`): Save Image… is off while it runs (#241)."""
        self._update_buttons()

    def _drop_engine(self) -> None:
        """The next board builds the engine again, and an engine a board is building at this moment is not kept when
        it arrives: a board model change, a page revisit or a new queue during a board must not leave a stale engine."""
        self.inspector = None
        self._engine_gen += 1

    def _stop_for_board_model(self, name: str | None) -> None:
        """The header shows another board model than the run's: the run stops, so no board of its queue is judged or
        saved under a board model it was not started for; the board in hand keeps the run's (#172)."""
        self.running = False
        self._update_buttons()
        msg = self.tr(
            "Run stopped: the board model changed from {old} to {new}. Boards inspected before the change are saved"
            " under {old}; press Start to carry on with the queue under {new}."
        ).format(old=self.run_board_model, new=name or NO_VERDICT)
        self.shell.status(msg, ms=0)  # until the board in hand, if one is, replaces it with its own line
        self._alarm("WARN", msg, "AOI-INSP-012")

    def _run_moved(self, path: Path, engine: Inspector) -> None:
        """The AI model, recipe or Golden board changed during a run, and `path` is the run's first board judged with
        what is active now: a line under the banner names it, below the next board's "Inspecting …" line or the
        result's summary when the run has ended, and a WARN alarm AOI-INSP-013 keeps it in the alarm log, so the
        operator sees that the run was judged by two (#243). The status bar keeps the next board's busy line, or "End
        of queue"; each record names what judged it. It runs after _on_result, which never waits for an alarm (#179)."""
        msg = self.tr(
            "The AI model, recipe or Golden board changed during this run: {file} was judged with AI model {version},"
            " recipe revision {revision} and Golden board {golden}; each record names what judged it."
        ).format(
            file=path.name,
            version=engine.model_version or NO_VERDICT,
            revision=NO_VERDICT if engine.recipe_rev is None else engine.recipe_rev,
            golden=Path(engine.reference_path).name if engine.reference_path else NO_VERDICT,
        )
        self.summary.setText("\n".join(line for line in (self.summary.text(), msg) if line))
        self._alarm("WARN", msg, "AOI-INSP-013")

    def _stop_for_user(self) -> None:
        """Another user signed in with Switch User during a run: the run stops after the board in hand, which is
        recorded under the user who pressed Start, so no board is recorded under a user who did not start it (#177)."""
        self.running = False
        self._update_buttons()
        msg = self.tr(
            "Run stopped: {user} signed in. The boards of the run so far are recorded under {starter}; press Start to"
            " carry on with the queue as {user}."
        ).format(user=self.ctx.user, starter=self.run_actor.name)
        self.shell.status(msg, ms=0)  # until the next message, so the user now signed in sees why the run stopped

    def on_board_model_changed(self, name: str | None) -> None:
        self._drop_engine()  # rebuilt lazily with the new model/recipe/reference
        self._no_ai_warned = None  # the board model picked again has its AOI-TRN-003 again
        if self.running and name != self.run_board_model:  # stops after the board in hand (#172)
            self._stop_for_board_model(name)
        if self.last is not None and name != self.last_board_model:  # another board model's board is not current
            self.last = self.last_path = self.last_id = None  # so Compare never opens it as this one's (#172)
            self.view.set_image(None)
            fill_table(self.table, [])
            if self.worker is None:  # else the banner reads "Inspecting…" until the board in hand arrives
                self._show_verdict(None)
                self.summary.clear()
        self._update_buttons()  # on every change: Start and Next Board follow the header's board model (#244)
        self._show_empty()

    def on_show(self) -> None:
        self._drop_engine()  # pick up newly trained models or saved recipes
        self._no_ai_warned = None  # each visit says once that a board model has no AI model yet
        self._update_buttons()  # Save Image… follows the role after a Switch User (#241)
        self._refresh_alarms()
        self._show_empty()
