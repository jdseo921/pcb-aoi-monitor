"""Screen 3 of the first-run guide on Home (REQ-TRN-021; B5, docs/sketches/first-run-guide.md, Q72 to Q74): Train, what
it made, and the handover to Inspection.

Before Train, the screen says what is ready and what Train does, with the images it keeps apart and trains on, and asks
the board revision, R1 at first (Q74), checked as it is typed. Train (Enter) runs `AppContext.guide_train`'s five parts
as the context's one training run (`start_guide_train`), off the window's thread: one line says the part in hand, the
percent and the time left of the whole press, with Cancel (Esc). Other pages can be used meanwhile, and the line is
there again when Home is. A part done before is not done again, so a Train after a Cancel goes on from where it stopped.

What Train made is read from the database (`AppContext.guide_result`), so it shows after a restart too: the AI model
that judges the board model's boards, the images it was trained on and kept apart, its missed defects and false calls
on those, counts first (`stats.text`), the Trial line and the shift check. Inspect a Board… (Enter) opens Inspection's
Load Images… on the folder above screen 2's and inspects the boards picked, in the view Train trained on (Q69); Open
Logs & Export › opens the board model's history, and Start the Checks › Training's What is missing with Validated
picked. A refusal is said under Train, with its code; the screen shows no dialog of its own."""

from __future__ import annotations

import math
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

from PySide6.QtCore import Signal
from PySide6.QtGui import QAction, QKeySequence
from PySide6.QtWidgets import QHBoxLayout, QLabel, QLineEdit, QVBoxLayout, QWidget

from ...core import datasets, stats
from ...errors import AoiError
from ...times import to_local
from .. import theme
from ..errors import phrase_text
from ..workers import Worker, keep
from .base import PressSays, button, size_class, time_left_text, view_text
from .training_versions import REVISION_LENGTH

if TYPE_CHECKING:
    from collections.abc import Callable

    from ...core.jobs import Job
    from ...core.run_progress import RunProgress
    from .base import Page
    from .inspection import InspectionPage
    from .logs import LogsPage
    from .training import TrainingPage

CALL = "start_guide_train"  # Train's call: an Engineer's, as Training's is
FIRST_REVISION = "R1"  # the board revision Train takes unless another is typed (Q74)
ENTER = ("Enter", "Return")  # F1 names the first, as the buttons do


class GuideTrain(QWidget):
    """Screen 3 for `board_model` (`show_for`); `changed` follows the end of a Train, for Home to read the guide's steps
    again. `folder` gives screen 2's folder, whose parent Inspect a Board… opens on."""

    changed = Signal()

    def __init__(self, page: Page, status: Callable[[str], object], folder: Callable[[], str]) -> None:
        super().__init__()
        self.page, self.ctx, self.status, self.folder = page, page.ctx, status, folder
        self.board_model: str | None = None
        self.view = "Top"  # the view of the images Train trains on, and Inspection's after it
        self.worker: Worker | None = None  # the Train this screen started, followed to its end
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        self._before(lay)
        self._result(lay)

    # --- the layout ---------------------------------------------------------------------------------------------
    def _before(self, lay: QVBoxLayout) -> None:
        """What is ready, what Train does, the board revision, Train, and its line with Cancel while it runs."""
        self.before = QWidget()
        before = QVBoxLayout(self.before)
        before.setContentsMargins(0, 0, 0, 0)
        self.ready = QLabel()  # "90 OK and 10 NG images of the Top view are ready, every defect boxed."
        self.ready.setWordWrap(True)
        self.plan = QLabel()  # what Train does, with the images it keeps apart and trains on
        self.plan.setWordWrap(True)
        before.addWidget(self.ready)
        before.addWidget(self.plan)
        row = QHBoxLayout()
        row.addWidget(QLabel(self.tr("Board revision")))
        self.revision = QLineEdit(FIRST_REVISION)
        self.revision.setMaxLength(REVISION_LENGTH)
        self.revision.setMinimumWidth(theme.FIELD_W)
        self.revision.textChanged.connect(self._sync)
        row.addWidget(self.revision)
        hint = QLabel(self.tr("as printed on the board; leave R1 if it shows none"))
        hint.setObjectName("muted")
        hint.setWordWrap(True)
        row.addWidget(hint, 1)
        before.addLayout(row)
        self.revision_line = QLabel()  # a revision Train cannot take, said as it is typed
        self.revision_line.setWordWrap(True)
        self.revision_line.hide()
        before.addWidget(self.revision_line)
        self.said = QLabel()  # a refusal of Train with its code, or what a Cancel kept
        self.said.setWordWrap(True)
        self.said.hide()
        before.addWidget(self.said)
        self.btn_train = size_class(button(self.tr("Train  Enter"), "primary", self.train), "T+")
        PressSays(self.btn_train, self._train_off, self.status)
        train = QAction(self.tr("Train"), self.before)  # its text for F1's list (`keys`)
        train.setShortcuts([QKeySequence(k) for k in ENTER])
        train.triggered.connect(self.train)
        self.before.addAction(train)  # while the screen before Train's end shows
        row = QHBoxLayout()
        row.addStretch(1)
        row.addWidget(self.btn_train)
        before.addLayout(row)
        self.run_row = QWidget()  # the training panel's line while Train runs, with Cancel
        run = QHBoxLayout(self.run_row)
        run.setContentsMargins(0, 0, 0, 0)
        self.run_line = QLabel()
        self.run_line.setWordWrap(True)
        run.addWidget(self.run_line, 1)
        self.btn_cancel = button(self.tr("Cancel  Esc"), slot=self.cancel)
        run.addWidget(self.btn_cancel)
        esc = QAction(self.tr("Cancel"), self.run_row)
        esc.setShortcut(QKeySequence("Esc"))
        esc.triggered.connect(self.cancel)
        self.run_row.addAction(esc)  # while Train runs
        self.run_row.hide()
        before.addWidget(self.run_row)
        lay.addWidget(self.before)

    def _result(self, lay: QVBoxLayout) -> None:
        """What Train made, and the three ways on."""
        self.result = QWidget()
        result = QVBoxLayout(self.result)
        result.setContentsMargins(0, 0, 0, 0)
        self.done_line = QLabel()  # "✓ AI model v1.0 (Trial) judges TBOX-A1's boards."
        self.done_line.setObjectName("guideSteps")
        self.done_line.setWordWrap(True)
        self.trained_line = QLabel()  # the images trained on, and kept apart
        self.trained_line.setWordWrap(True)
        rates = QHBoxLayout()
        self.missed = QLabel()  # "Missed defects  0 of 3, 95 % upper bound 63.2 %"
        self.false_calls = QLabel()
        rates.addWidget(self.missed)
        rates.addSpacing(theme.FIELD_W // 4)
        rates.addWidget(self.false_calls)
        rates.addStretch(1)
        self.untested = QLabel()  # the test on the images kept apart did not run
        self.untested.setWordWrap(True)
        trial = QLabel(self.tr("Trial: one person labelled the images and no one else checked them."))
        trial.setWordWrap(True)
        self.shift_line = QLabel()  # the shift check: passed, failed, or not run
        self.shift_line.setWordWrap(True)
        self.shift_next = QLabel(self.tr("Boards are inspected only after every master sample is judged right."))
        self.shift_next.setWordWrap(True)
        result.addWidget(self.done_line)
        result.addWidget(self.trained_line)
        result.addLayout(rates)
        for w in (self.untested, trial, self.shift_line, self.shift_next):
            result.addWidget(w)
        self.btn_inspect = size_class(button(self.tr("Inspect a Board…  Enter"), "primary", self.inspect), "T")
        inspect = QAction(self.tr("Inspect a Board…"), self.result)  # its text for F1's list (`keys`)
        inspect.setShortcuts([QKeySequence(k) for k in ENTER])
        inspect.triggered.connect(self.inspect)
        self.result.addAction(inspect)  # while what Train made shows
        self.btn_logs = button(self.tr("Open Logs & Export ›").replace("&", "&&"), slot=self.open_logs)
        self.btn_checks = button(self.tr("Start the Checks ›"), slot=self.start_checks)
        row = QHBoxLayout()
        for b in (self.btn_inspect, self.btn_logs, self.btn_checks):
            row.addWidget(b)
        row.addStretch(1)
        result.addLayout(row)
        self.result.hide()
        lay.addWidget(self.result)

    # --- what shows --------------------------------------------------------------------------------------------
    def show_for(self, board_model: str) -> None:
        """Screen 3 for `board_model`: before Train, with its line while it runs, or what it made; afresh for another
        board model."""
        if board_model != self.board_model:
            self.said.hide()
            self.revision.blockSignals(True)
            self.revision.setText(FIRST_REVISION)
            self.revision.blockSignals(False)
        self.board_model = board_model
        self.refresh()

    def refresh(self) -> None:
        bm = self.board_model
        if bm is None:
            return
        running = self.ctx.guide_running(bm)
        made = None if running else self.ctx.guide_result(bm)
        self.before.setVisible(made is None)
        self.result.setVisible(made is not None)
        self.run_row.setVisible(running)
        if running and self.ctx.training_progress is not None:
            self._progress((self.ctx.training_progress,))
        if made is None:
            self._show_plan(bm)
        else:
            self._show_made(bm, made)
        self._sync()

    def done(self) -> bool:
        """Train has made the AI model that judges the board model's boards: the guide marks its step 3 done."""
        return not self.result.isHidden()

    def keys(self) -> list[QAction]:
        """The keys of the parts of screen 3 shown, for F1's list of Home's keys."""
        parts = (self.before, self.run_row, self.result)
        return [a for part in parts if not part.isHidden() for a in part.actions()]

    def focus_first(self) -> None:
        """Train, as screen 3 shows itself (Q69), or Inspect a Board… once Train has made the AI model."""
        (self.btn_inspect if self.done() else self.btn_train).setFocus()

    def _show_plan(self, bm: str) -> None:
        """What is ready, and what Train does with it: the images it keeps apart, as the validation set takes them from
        a first set of images (`datasets.VALIDATION_OK`, `VALIDATION_NG`), and those it trains on."""
        missing = self.ctx.missing(bm, trial=True)
        needs = {n.key: n for n in missing.needs}
        self.view = missing.view
        ok, ng = needs["ok"].have, needs["ng"].have
        held_ok, held_ng = min(datasets.VALIDATION_OK, ok), math.ceil(ng * datasets.VALIDATION_NG)
        ready = self.tr("{ok} OK and {ng} NG images of the {view} view are ready, every defect boxed.")
        self.ready.setText(ready.format(ok=ok, ng=ng, view=view_text(missing.view)))
        if self.ctx.shift_check(bm)["state"] == "off":
            plan = self.tr(
                "Train keeps {held_ok} OK and {held_ng} NG images apart, trains the AI model on the other {ok} OK and"
                " {ng} NG as a Trial, since one person labelled them, makes it the AI model that judges"
                " {board_model}'s boards and tests it on the images kept apart. Other pages can be used while it runs."
            )
        else:
            plan = self.tr(
                "Train keeps {held_ok} OK and {held_ng} NG images apart, trains the AI model on the other {ok} OK and"
                " {ng} NG as a Trial, since one person labelled them, makes it the AI model that judges"
                " {board_model}'s boards, tests it on the images kept apart and runs the first shift check. Other"
                " pages can be used while it runs."
            )
        self.plan.setText(
            plan.format(held_ok=held_ok, held_ng=held_ng, ok=ok - held_ok, ng=ng - held_ng, board_model=bm)
        )

    def _show_made(self, bm: str, made: dict[str, Any]) -> None:
        """What Train made (`AppContext.guide_result`): the AI model, the images, its rates on those kept apart, counts
        first, or that the test did not run, and the shift check."""
        model, run, held, trained = made["model"], made["run"], made["held"], made["trained"]
        self.view = str(made["dataset"]["view"])
        judges = self.tr("✓ AI model {version} judges {board_model}'s boards.")  # "v1.0 (Trial)", as its name
        self.done_line.setText(judges.format(version=model["version"], board_model=bm))
        said = self.tr("Trained on {ok} OK and {ng} NG images.").format(ok=trained["ok"], ng=trained["ng"])
        if run is not None:
            apart = self.tr("On the {ok} OK and {ng} NG images kept apart:").format(ok=held["ok"], ng=held["ng"])
            said = f"{said} {apart}"
            rates = run["metrics"]["rates"]
            missed = self.tr("Missed defects  {rate}").format(rate=phrase_text(stats.text(rates["missed_defects"])))
            false_calls = self.tr("False calls  {rate}").format(rate=phrase_text(stats.text(rates["false_calls"])))
            self.missed.setText(missed)
            self.false_calls.setText(false_calls)
        self.trained_line.setText(said)
        for w in (self.missed, self.false_calls):
            w.setVisible(run is not None)
        untested = self.tr("Not tested yet on the {ok} OK and {ng} NG images kept apart: AI Model Test tests it.")
        self.untested.setText(untested.format(ok=held["ok"], ng=held["ng"]))
        self.untested.setVisible(run is None)
        shift = made["shift"]
        state = shift["state"]
        if state == "passed":
            line = self.tr("✓ Shift check: every verdict right · boards may be inspected until {until}")
            line = line.format(until=to_local(shift["until"])[:16])
        elif state == "failed":
            rows = shift["check"]["rows"]
            line = self.tr("Shift check of {board_model}: {right} of {count} master samples judged right.")
            line = line.format(board_model=bm, right=sum(r["right"] for r in rows), count=len(rows))
        elif state == "off":
            line = ""
        else:  # none, expired or changed: Inspection asks for it before the first board (AOI-INSP-016)
            line = self.tr("No shift check counts now: Inspection asks for Shift Check (F7) before the first board.")
        self.shift_line.setText(line)
        self.shift_line.setVisible(bool(line))
        self.shift_next.setVisible(state == "failed")

    def _sync(self) -> None:
        """Train on for a role that may train, while no training runs and the board revision is one Train can take;
        the board revision off while a training runs; the line under it says why one cannot be taken."""
        busy = self.ctx.training is not None and not self.ctx.training.done
        taken = bool(datasets.REVISION.fullmatch(self.revision.text().strip()))
        self.revision_line.setText(self.tr("Type the board revision: 1 to 16 letters and digits, such as R1."))
        self.revision_line.setVisible(not taken)
        self.page.gates.gate(self.btn_train, CALL, taken and not busy)
        self.page.gates.gate(self.revision, CALL, not busy)

    def _train_off(self) -> str:
        """Why Train is off, said on a press on it or on Enter: the role it needs, Train running, another training
        running, or the board revision."""
        why = self.page.gates.why.get(self.btn_train)
        if why:
            return why
        if self.board_model is not None and self.ctx.guide_running(self.board_model):
            return self.tr("Train is running: Cancel (Esc) stops it.")
        if self.ctx.training is not None and not self.ctx.training.done:
            return self.tr("Wait for the training under way to end, then press Train again.")
        return self.tr("Type the board revision: 1 to 16 letters and digits, such as R1.")

    # --- Train ---------------------------------------------------------------------------------------------------
    def train(self) -> None:
        """Train (Enter): the five parts in one press, as the context's one training run; while Train is off, the
        status bar says why."""
        bm = self.board_model
        if bm is None or self.before.isHidden():
            return
        if not self.btn_train.isEnabled():
            self.status(self._train_off())
            return
        self.said.hide()
        try:
            self.ctx.start_guide_train(bm, self.view, self.revision.text().strip(), listen=self._follow)
        except AoiError as e:  # a training run started meanwhile (AOI-TRN-047), or the role
            self._say(self._coded(e))
            return
        self.run_line.setText(self.tr("Starting Train…"))
        self.refresh()

    def _follow(self, job: Job[dict[str, Any]]) -> None:
        """Follow Train's run: its reports, an error and its end reach this screen on the window's thread."""
        self.worker = Worker.of(job)
        self.worker.signals.progress.connect(self._progress)
        self.worker.signals.error.connect(lambda e: self._say(self._coded(e)))
        self.worker.signals.finished.connect(self._ended)
        keep(self.worker, self.ctx.jobs)

    def _progress(self, values: tuple[RunProgress]) -> None:
        p = values[0]
        line = self.tr("{phase} · {percent} % · {left}")  # the training panel's line (sketch)
        self.run_line.setText(line.format(phase=phrase_text(p.phase), percent=p.percent, left=time_left_text(p.left_s)))

    def cancel(self) -> None:
        """Cancel (Esc): Train stops at the step in hand; the parts done are kept, and the next Train goes on from
        there."""
        if self.worker is not None:
            self.worker.stop()
            self.run_line.setText(self.tr("Stopping Train after the step in hand…"))

    def _ended(self) -> None:
        w, self.worker = self.worker, None
        if w is not None and w.job.cancelled and w.job.result is None and w.job.error is None:
            self._say(self.tr("Train was cancelled. What it had done is kept, and the next Train goes on from there."))
        self.refresh()
        self.changed.emit()

    def _coded(self, e: BaseException) -> str:
        """An error as the guide says it: logged and alarmed, then its code, what happened and what to do."""
        report = self.ctx.report_error(e, "Home")
        return " ".join([report.code, phrase_text(report.what), phrase_text(report.action)])

    def _say(self, said: str) -> None:
        self.said.setText(said)
        self.said.show()

    # --- the handover --------------------------------------------------------------------------------------------
    def inspect(self) -> None:
        """Inspect a Board… (Enter): Inspection, its Load Images… dialog on the folder above screen 2's, and the boards
        picked inspected at once, in the view Train trained on (Q69)."""
        if self.result.isHidden():
            return
        folder = self.folder()
        shell = self.page.shell
        if shell.navigate("Inspection"):
            page = cast("InspectionPage", shell.pages["Inspection"])
            page.inspect_from(str(Path(folder).parent) if folder else "", self.view)

    def open_logs(self) -> None:
        """Open Logs & Export ›: the history of this board model."""
        shell = self.page.shell
        if self.board_model is not None and shell.navigate("Logs & Export"):
            cast("LogsPage", shell.pages["Logs & Export"]).show_board_model(self.board_model)

    def start_checks(self) -> None:
        """Start the Checks ›: Training's What is missing with Validated picked, each check with its button (B3)."""
        shell = self.page.shell
        if shell.navigate("Training"):
            cast("TrainingPage", shell.pages["Training"]).show_validated_needs()
