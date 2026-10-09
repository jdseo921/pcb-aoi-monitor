"""Run slow work off the UI thread (REQ-SET-021): the Qt face of `aoi.core.jobs`.

A `Worker` wraps a `Job` and turns its callbacks, which arrive on the pool thread, into Qt signals whose slots run on
the UI thread, the only place a widget changes. A job function never touches a widget: plain values in, plain out.
`collect_on_ui_thread` keeps Python's cycle collector on the UI thread too (REQ-INSP-011).
"""

from __future__ import annotations

import gc
from collections.abc import Callable
from typing import Any

from PySide6.QtCore import QCoreApplication, QEvent, QObject, QTimer, Signal

from ..core.jobs import Job, Jobs


class WorkerSignals(QObject):
    progress = Signal(object)  # the tuple the function reported: (done, total), or training's (RunProgress,)
    result = Signal(object)
    error = Signal(object)  # the exception itself; Page.run_in_background logs and alarms it, with a coded dialog
    # unless the run was cancelled or replaced (#206)
    finished = Signal()


class Worker:
    """`fn(*args, progress=report, should_stop=flag, **kw)`; the two keywords are passed only when
    `with_progress=True`. Connect the signals, then `start(worker, ctx.jobs)`."""

    def __init__(self, fn: Callable[..., Any], *args: Any, with_progress: bool = False, **kwargs: Any) -> None:
        self._follow(Job(getattr(fn, "__name__", "job"), fn, *args, with_progress=with_progress, **kwargs))

    @classmethod
    def of(cls, job: Job[Any]) -> Worker:
        """A worker whose signals follow `job`, a job another owner made and submits (AppContext.start_training,
        REQ-TRN-008): made before the job is submitted, its slots connected, then `keep(worker, jobs)`."""
        worker = cls.__new__(cls)
        worker._follow(job)
        return worker

    def _follow(self, job: Job[Any]) -> None:
        self.signals = WorkerSignals()
        self.jobs: Jobs | None = None  # the pool its job is submitted to
        self.job: Job[Any] = job
        job.on_progress(self.signals.progress.emit)
        job.on_result(self.signals.result.emit)
        job.on_error(self.signals.error.emit)
        job.on_finished(self.signals.finished.emit)

    def stop(self) -> None:
        """Ask the job to stop; a function that checks `should_stop()` returns what it has done so far."""
        self.job.cancel()


_live: dict[int, Worker] = {}  # workers whose finished slot has not run yet, by id: the slot must not hold the worker


def start(worker: Worker, jobs: Jobs) -> Worker:
    """Submit the worker's job. Connect every slot first: the worker is kept alive until its last `finished` slot has
    run on the UI thread, so the signals outlive the pool thread and no queued slot is lost; then it is released."""
    keep(worker, jobs)
    jobs.submit(worker.job)
    return worker


def keep(worker: Worker, jobs: Jobs) -> Worker:
    """Keep the worker alive until its last `finished` slot has run, as `start` does, for a job submitted to `jobs` by
    its own owner (`Worker.of`): call it once every slot is connected, before the job is submitted."""
    key = id(worker)
    _live[key] = worker
    worker.jobs = jobs
    worker.signals.finished.connect(lambda: _live.pop(key, None))
    return worker


def drop_queued(jobs: Jobs) -> None:
    """Once `jobs` has shut down (the window closing, #171): drop the slots its jobs queued, unrun, so none meets the
    closed context, and let go of their workers, whose `finished` slot was among those dropped or, for a job dropped
    while still queued, never comes."""
    QCoreApplication.removePostedEvents(None, QEvent.Type.MetaCall)  # type: ignore[arg-type]  # None: every receiver
    for key, worker in list(_live.items()):
        if worker.jobs is jobs:
            del _live[key]


COLLECT_MS = 200  # how often the UI thread runs a collection that has come due
_collector: list[QTimer] = []  # the timer `collect_on_ui_thread` started, kept while the app runs


def collect_due() -> int:
    """Run the collection the interpreter would start now, on the calling thread: once more container objects were
    made than freed than the youngest generation's threshold allows, the oldest generation over its threshold. The
    generation collected, or -1 when none is due."""
    counts, limits = gc.get_count(), gc.get_threshold()
    if limits[0] == 0 or counts[0] <= limits[0]:
        return -1
    gen = max(g for g in range(3) if counts[g] > limits[g])
    gc.collect(gen)
    return gen


def collect_on_ui_thread(interval_ms: int = COLLECT_MS) -> QTimer:
    """Turn Python's automatic cycle collection off and run each collection that comes due from a timer on the calling
    thread, the UI thread (`main.py`, after the QApplication; REQ-INSP-011). The interpreter starts a collection on
    whichever thread is allocating when one comes due, so a pool thread could free a reference cycle that holds a Qt
    object and delete the object off its own thread, which Qt forbids: on Windows CI a collection that started inside
    an inspection job crashed the test process with an access violation (2026-10-09). Calling it again replaces the
    timer."""
    for old in _collector:
        old.stop()
    gc.disable()
    timer = QTimer()
    timer.timeout.connect(collect_due)
    timer.start(interval_ms)
    _collector[:] = [timer]
    return timer
