"""Run slow work off the UI thread (REQ-SET-021): the Qt face of `aoi.core.jobs`.

A `Worker` wraps a `Job` and turns its callbacks, which arrive on the pool thread, into Qt signals whose slots run on
the UI thread, the only place a widget changes. A job function never touches a widget: plain values in, plain out.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from PySide6.QtCore import QObject, Signal

from ..core.jobs import Job, Jobs


class WorkerSignals(QObject):
    progress = Signal(object)  # the tuple the function reported: (done, total) or training's (epoch, total, loss, msg)
    result = Signal(object)
    error = Signal(object)  # the exception itself; Page.error turns it into a coded dialog and a log line
    finished = Signal()


class Worker:
    """`fn(*args, progress=report, should_stop=flag, **kw)`; the two keywords are passed only when
    `with_progress=True`. Connect the signals, then `start(worker, ctx.jobs)`."""

    def __init__(self, fn: Callable[..., Any], *args: Any, with_progress: bool = False, **kwargs: Any) -> None:
        self.signals = WorkerSignals()
        self.job: Job[Any] = Job(getattr(fn, "__name__", "job"), fn, *args, with_progress=with_progress, **kwargs)
        self.job.on_progress(self.signals.progress.emit)
        self.job.on_result(self.signals.result.emit)
        self.job.on_error(self.signals.error.emit)
        self.job.on_finished(self.signals.finished.emit)

    def stop(self) -> None:
        """Ask the job to stop; a function that checks `should_stop()` returns what it has done so far."""
        self.job.cancel()


_live: dict[int, Worker] = {}  # workers whose finished slot has not run yet, by id: the slot must not hold the worker


def start(worker: Worker, jobs: Jobs) -> Worker:
    """Submit the worker's job. Connect every slot first: the worker is kept alive until its last `finished` slot has
    run on the UI thread, so the signals outlive the pool thread and no queued slot is lost; then it is released."""
    key = id(worker)
    _live[key] = worker
    worker.signals.finished.connect(lambda: _live.pop(key, None))
    jobs.submit(worker.job)
    return worker
