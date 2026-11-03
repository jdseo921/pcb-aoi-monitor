"""The inspection cycle (#447; production plan PR 3.1): one board from its frame to its saved record, with no screen.
For each board it checks that the engine it keeps is still what is active and builds it again when not (#243), loads
the image unless the source gave the frame, inspects the board, saves its record with `AppContext.log_result`
(REQ-INSP-008) and tells a run judged by two engines (#243, S29). It stores the four operational alarms: AOI-TRN-003
and AOI-TRN-051 (no active AI model), AOI-INSP-012 (a run stopped by a board model change) and AOI-INSP-013 (a run
whose engine changed). The Inspection page drives it board by board; a driver with no screen calls `run`."""

from __future__ import annotations

from collections.abc import Callable, Iterator
from dataclasses import dataclass, replace
from pathlib import Path
from typing import TYPE_CHECKING, Any, Protocol

import numpy as np

from ..errors import QT_TRANSLATE_NOOP, Phrase
from ..hal import VIEWS
from .inspector import InspectionResult, Inspector

if TYPE_CHECKING:
    from .services import AppContext

NO_VALUE = "—"  # a version, revision or Golden board the engine has none of
# The page's texts before #447, in its translation context, so a translation made of them still applies
NO_AI_MODEL = QT_TRANSLATE_NOOP("Page", "No AI model for {board_model} yet: only the Golden board comparison runs")
NOT_ACTIVE = QT_TRANSLATE_NOOP(
    "Page",
    "AI model {version} of {board_model} is not active: only the Golden board comparison runs. An Engineer activates it"
    " with Activate {version}.",
)
BOARD_MODEL_CHANGED = QT_TRANSLATE_NOOP(
    "Page",
    "Run stopped: the board model changed from {old} to {new}. Boards inspected before the change are saved under"
    " {old}; press Start to carry on with the queue under {new}.",
)
MOVED_WITH_AI = QT_TRANSLATE_NOOP(
    "Page",
    "The AI model, recipe, scale or Golden board changed during this run: {file} was judged with AI model {version},"
    " recipe revision {revision}, Golden board {golden} and {scale}; each record names the recipe revision and Golden"
    " board that judged it and the AI model version active then.",
)
MOVED_NO_AI = QT_TRANSLATE_NOOP(
    "Page",
    "The recipe, scale or Golden board changed during this run: {file} was judged with the AI check off, recipe"
    " revision {revision}, Golden board {golden} and {scale}; each record names the recipe revision and Golden board"
    " that judged it and the AI model version active then.",
)
NO_SCALE = QT_TRANSLATE_NOOP("Page", "no scale")
A_SCALE = QT_TRANSLATE_NOOP("Page", "a scale of {scale:.2f} px/mm")


@dataclass(frozen=True)
class FrameMeta:
    """A frame's file, which names the record, and the view it shows (REQ-INSP-010)."""

    path: Path
    view: str = VIEWS[0]


class FrameSource(Protocol):
    """`grab()`: the next frame with its metadata, or None when none is left; a None frame is read from its path."""

    def grab(self) -> tuple[np.ndarray | None, FrameMeta] | None: ...


@dataclass(frozen=True)
class Outcome:
    """One board through the cycle: `record_id` is None when the save failed, with `save_error`; the verdict stands.
    `settle` fills the last three fields."""

    board_model: str
    path: Path
    result: InspectionResult
    engine: Inspector
    record_id: int | None
    save_error: Exception | None
    generation: int  # the cycle's engine generation when the board started
    built: bool  # the board built its engine rather than use the one kept
    kept: bool = False  # the cycle keeps this board's engine for the next boards
    no_ai_model: bool = False  # AOI-TRN-003 or AOI-TRN-051 is due
    moved: bool = False  # what judges the run's boards changed with this board (AOI-INSP-013)


class InspectionCycle:
    """One driver's cycle: the engine it keeps and the run it is in. The driver runs `board`'s job on any thread, then
    `settle` on its own thread with the outcome."""

    def __init__(self, ctx: AppContext) -> None:
        self.ctx = ctx
        self.engine: Inspector | None = None  # kept while it is what is active (#243)
        self.generation = 0  # counts the drops, so an engine built from before one is not kept
        self.run_inputs: tuple[str | None, str | None, str | None, float | None] | None = None
        self.no_ai_warned: str | None = None  # the board model AOI-TRN-003 was stored for since `forget_warnings`

    def drop_engine(self) -> None:
        """The next board builds the engine again, and one a board is building now is not kept."""
        self.engine = None
        self.generation += 1

    def forget_warnings(self) -> None:
        """AOI-TRN-003 may be stored again: a page visit, or another board model picked."""
        self.no_ai_warned = None

    def start_run(self) -> None:
        self.run_inputs = None

    def board(
        self,
        board_model: str,
        meta: FrameMeta,
        frame: np.ndarray | None = None,
        report: Callable[[InspectionResult], None] | None = None,
    ) -> Callable[[], Outcome]:
        """The job that inspects and saves one board with the engine kept now; `report` gets the verdict before the save
        (REQ-INSP-002). A failed save is in the outcome, so the driver stops its run on the missing record."""
        kept, gen, ctx = self.engine, self.generation, self.ctx

        def inspect() -> Outcome:
            # a training run, an activation or a recipe saved meanwhile makes the kept engine stale (#243)
            current = kept is not None and ctx.engine_is_current(board_model, kept)
            engine = kept if kept is not None and current else ctx.inspector(board_model, side=meta.view)
            engine.side = meta.view  # one job at a time per cycle, so nothing else reads it meanwhile
            res = engine.inspect(ctx.load_image(meta.path) if frame is None else frame)
            if report is not None:
                report(res)
            iid, error = None, None
            try:
                iid = ctx.log_result(board_model, str(meta.path), res, engine)
            except Exception as e:
                error = e
            return Outcome(board_model, meta.path, res, engine, iid, error, gen, engine is not kept)

        return inspect

    def settle(self, out: Outcome, header: str | None, in_run: bool) -> Outcome:
        """Keep the engine the board built while nothing dropped it and `header` is still its board model; tell whether
        AOI-TRN-003 is due (once per board model) and whether the run's engine moved (#246: by what judged it)."""
        kept = no_ai_model = moved = False
        if out.built and out.generation == self.generation and out.board_model == header:
            self.engine, kept = out.engine, True
            no_ai_model = out.engine.model is None and self.no_ai_warned != out.board_model
            self.no_ai_warned = out.board_model if out.engine.model is None else None
        if in_run:
            moved = self.run_inputs is not None and out.engine.judging_inputs != self.run_inputs
            self.run_inputs = out.engine.judging_inputs
        return replace(out, kept=kept, no_ai_model=no_ai_model, moved=moved)

    def no_ai_model_alarm(self, out: Outcome, waiting: dict[str, Any] | None) -> Phrase | None:
        """When due: AOI-TRN-003, or AOI-TRN-051 for `waiting`, a version trained but not active (decision D3)."""
        if not out.no_ai_model:
            return None
        if waiting is None:
            return self._alarm(NO_AI_MODEL.fill(board_model=out.board_model), "AOI-TRN-003")
        return self._alarm(NOT_ACTIVE.fill(version=waiting["version"], board_model=out.board_model), "AOI-TRN-051")

    def moved_alarm(self, out: Outcome) -> Phrase | None:
        """When the run's engine moved: AOI-INSP-013, naming what judged the board (with the AI check off, no model)."""
        if not out.moved:
            return None
        e, s = out.engine, out.engine.px_per_mm
        msg = (MOVED_WITH_AI if e.recipe.use_ai else MOVED_NO_AI).fill(
            file=out.path.name,
            version=e.model_version or NO_VALUE,
            revision=NO_VALUE if e.recipe_rev is None else e.recipe_rev,
            golden=Path(e.reference_path).name if e.reference_path else NO_VALUE,
            scale=NO_SCALE if s is None else A_SCALE.fill(scale=s),
        )
        return self._alarm(msg, "AOI-INSP-013")

    def board_model_alarm(self, old: str | None, new: str | None) -> Phrase:
        """AOI-INSP-012: a run stopped because the board model changed (#172)."""
        return self._alarm(BOARD_MODEL_CHANGED.fill(old=old or NO_VALUE, new=new or NO_VALUE), "AOI-INSP-012")

    def _waiting(self, board_model: str) -> dict[str, Any] | None:
        """The version trained but not active, as `AppContext.inactive_model`; none when it cannot be read (logged)."""
        try:
            return self.ctx.inactive_model(board_model)
        except Exception:
            self.ctx.log.warning("models.not_read", exc_info=True)
            return None

    def _alarm(self, msg: Phrase, code: str) -> Phrase:
        """A WARN alarm with its phrase; never raises: one the database refuses is logged; the run goes on (#179)."""
        from .services import BUSY_ALARM_WAIT_MS  # services imports this module

        try:
            self.ctx.alarm("WARN", msg, code, wait_ms=BUSY_ALARM_WAIT_MS)
        except Exception:
            self.ctx.log.warning("alarm.not_stored", exc_info=True, extra={"code": code})
        return msg

    def run(self, board_model: str, source: FrameSource) -> Iterator[Outcome]:
        """Every frame of `source` as one run, with its alarms, until none is left or a record is not saved (the last
        outcome then). As on the page, no board is taken while the shift check stops it (AOI-INSP-016, REQ-INSP-017),
        and each record names the context's user."""
        self.start_run()
        while self.ctx.require_shift_check(board_model) and (got := source.grab()) is not None:
            out = self.settle(self.board(board_model, got[1], got[0])(), board_model, in_run=True)
            if out.no_ai_model:
                self.no_ai_model_alarm(out, self._waiting(board_model))
            self.moved_alarm(out)
            yield out
            if out.save_error is not None:
                return
