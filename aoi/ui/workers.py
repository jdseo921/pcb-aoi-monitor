"""Run slow work (training, batch tests) off the UI thread."""

from __future__ import annotations

import traceback
from collections.abc import Callable

from PySide6.QtCore import QObject, QRunnable, QThreadPool, Signal


class WorkerSignals(QObject):
    progress = Signal(object)
    result = Signal(object)
    error = Signal(str)
    finished = Signal()


class Worker(QRunnable):
    """`fn(*args, progress=emit, should_stop=flag, **kw)`; the two keywords are
    passed only when `with_progress=True`."""

    def __init__(self, fn: Callable, *args, with_progress: bool = False, **kwargs):
        super().__init__()
        self.fn, self.args, self.kwargs = fn, args, kwargs
        self.signals = WorkerSignals()
        self._stop = False
        if with_progress:
            self.kwargs["progress"] = lambda *a: self.signals.progress.emit(a)
            self.kwargs["should_stop"] = lambda: self._stop

    def stop(self) -> None:
        self._stop = True

    def run(self) -> None:
        try:
            self.signals.result.emit(self.fn(*self.args, **self.kwargs))
        except Exception as e:  # surfaced to the user as a dialog
            self.signals.error.emit(f"{e}\n\n{traceback.format_exc()}")
        finally:
            self.signals.finished.emit()


def start(worker: Worker) -> Worker:
    QThreadPool.globalInstance().start(worker)
    return worker
