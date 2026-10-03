"""Background jobs without Qt (REQ-SET-021, stage S17).

Inspection, training, file and database work runs on a pool thread owned by `AppContext.jobs`, so the UI never
freezes (Engineering standard, "Performance budgets"). Nothing here imports Qt: the same jobs run headless (tests,
a CLI, the Stage 3 robot cycle), and `aoi/ui/workers.py` turns the callbacks into Qt signals on the UI thread.
Callbacks run on the pool thread. A job function takes plain values in and returns plain values out; with
`with_progress=True` it also gets `progress(*values)` to report how far it is and `should_stop()` to check for a
cancel. A cancel is a request: the function stops when it next checks, and what it returns is still its result.
A job runs with the context variables of the moment it was submitted (`Jobs(context=...)`), so it acts as the user who
started it (#177).
"""

from __future__ import annotations

import contextvars
import logging
import threading
import time
import weakref
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from typing import Any, Generic, TypeVar

T = TypeVar("T")
MAX_WORKERS = 4  # an inspection, a training run and a test can overlap; more threads would only share the same cores
log = logging.getLogger("aoi")


class JobCancelled(Exception):
    """Raised by `Job.check_cancelled()` after `cancel()`: the job ends with no result and no error, only finished."""


@dataclass(frozen=True)
class Progress:
    """How far a job is: `done` of `total` steps (0 of 0 until the function reports), its last message, the seconds
    it has run and, from the rate so far, the seconds left (None until a step is done)."""

    done: int
    total: int
    message: str
    elapsed_s: float
    left_s: float | None


class Job(Generic[T]):
    """One unit of background work: `fn(*args, **kwargs)`, run by `Jobs.submit` on a pool thread.

    Register listeners before submitting. `on_progress` gets the values the function reports, as a tuple, as often
    as it reports; then exactly one of `on_result` (the return value) or `on_error` (the exception), unless the
    function raised `JobCancelled`; then `on_finished`. A listener that raises is logged and dropped, never the job.
    """

    def __init__(self, name: str, fn: Callable[..., T], *args: Any, with_progress: bool = False, **kwargs: Any) -> None:
        self.name = name
        self._fn, self._args, self._kwargs = fn, args, dict(kwargs)
        if with_progress:
            self._kwargs["progress"] = self.report
            self._kwargs["should_stop"] = lambda: self.cancelled
        self._cancel, self._done = threading.Event(), threading.Event()
        self._started: float | None = None
        self._last: tuple[int, int, str] = (0, 0, "")
        events = ("progress", "result", "error", "finished")
        self._listeners: dict[str, list[Callable[..., None]]] = {k: [] for k in events}
        self.result: T | None = None
        self.error: BaseException | None = None
        self.context: contextvars.Context | None = None  # what `Jobs.submit` gives it: the function runs in it

    def on_progress(self, cb: Callable[[tuple[Any, ...]], None]) -> Job[T]:
        self._listeners["progress"].append(cb)
        return self

    def on_result(self, cb: Callable[[T], None]) -> Job[T]:
        self._listeners["result"].append(cb)
        return self

    def on_error(self, cb: Callable[[BaseException], None]) -> Job[T]:
        self._listeners["error"].append(cb)
        return self

    def on_finished(self, cb: Callable[[], None]) -> Job[T]:
        self._listeners["finished"].append(cb)
        return self

    @property
    def cancelled(self) -> bool:
        return self._cancel.is_set()

    @property
    def done(self) -> bool:
        return self._done.is_set()

    def cancel(self) -> None:
        """Ask the function to stop at its next `should_stop()` or `check_cancelled()`; a queued job never runs."""
        self._cancel.set()

    def check_cancelled(self) -> None:
        if self.cancelled:
            raise JobCancelled(self.name)

    def wait(self, timeout: float | None = None) -> bool:
        return self._done.wait(timeout)

    def report(self, *values: Any) -> None:
        """What the function calls as `progress(...)`: the first two numbers count as done and total and the last
        string as the message, for `progress()`; the whole tuple reaches the `on_progress` listeners."""
        nums = [v for v in values if isinstance(v, (int, float)) and not isinstance(v, bool)]
        text = next((v for v in reversed(values) if isinstance(v, str)), self._last[2])
        done, total = (int(nums[0]), int(nums[1])) if len(nums) >= 2 else self._last[:2]
        self._last = (done, total, text)
        self._call("progress", values)

    def progress(self) -> Progress:
        """The latest report with the seconds run so far and the seconds left, estimated from the rate so far."""
        elapsed = time.monotonic() - self._started if self._started is not None else 0.0
        done, total, text = self._last
        left = elapsed / done * (total - done) if 0 < done <= total else None
        return Progress(done, total, text, elapsed, left)

    def run(self) -> None:
        """Run the function on the calling thread and tell the listeners; `Jobs.submit` calls this on a pool thread."""
        self._started = time.monotonic()
        try:
            self.check_cancelled()  # cancelled while still queued: never run
            if self.context is None:
                value = self._fn(*self._args, **self._kwargs)
            else:
                value = self.context.run(self._fn, *self._args, **self._kwargs)
        except JobCancelled:
            pass
        except Exception as e:  # reaches the user as a coded dialog through on_error; never kills the pool thread
            self.error = e
            self._call("error", e)
        else:
            self.result = value
            self._call("result", value)
        finally:
            self._done.set()
            self._call("finished")

    def _call(self, event: str, *args: Any) -> None:
        for cb in self._listeners[event]:
            try:
                cb(*args)
            except Exception:  # a listener's failure (a widget already closed) is not the job's: the result stands
                log.warning("job.listener_failed", exc_info=True, extra={"job": self.name, "listener": event})


class Jobs:
    """The pool `AppContext` owns. `submit` runs a job on a pool thread; `shutdown` cancels and waits, so a workspace
    folder is removed only once nothing in it is still being written (`AppContext.close`)."""

    def __init__(
        self, max_workers: int = MAX_WORKERS, context: Callable[[], contextvars.Context] = contextvars.copy_context
    ) -> None:
        """`context` gives a job, as it is submitted, the context variables its function runs with: by default the
        submitter's, as `asyncio.to_thread` does; `AppContext` adds the user who submitted it (#177)."""
        self._context = context
        self._pool = ThreadPoolExecutor(max_workers, thread_name_prefix="aoi-job")
        self._jobs: weakref.WeakSet[Job[Any]] = weakref.WeakSet()  # the pool never keeps a finished job's result alive
        self._lock = threading.Lock()

    def submit(self, job: Job[T]) -> Job[T]:
        job.context = self._context()  # taken here, on the submitting thread, not when a pool thread gets to the job
        with self._lock:
            self._jobs.add(job)
        self._pool.submit(job.run)
        return job

    def idle(self) -> bool:
        """True while no submitted job is queued or running; a test waits on it before it takes hold of the pool's work,
        a window may wait on it before it closes."""
        with self._lock:
            return all(job.done for job in self._jobs)

    def shutdown(self, wait: bool = True) -> None:
        """Cancel every job, drop the ones still queued and, with `wait`, block until the running ones return."""
        with self._lock:
            for job in list(self._jobs):
                job.cancel()
        self._pool.shutdown(wait=wait, cancel_futures=True)
