"""REQ-SET-021 (stage S17a): the Qt-free job API in aoi/core/jobs.py and its Qt face in aoi/ui/workers.py. A job runs
on a pool thread with progress, cancel and finished callbacks; the Worker turns those into signals whose slots run on
the UI thread, which is where widgets may change."""

from __future__ import annotations

import gc
import logging
import subprocess
import sys
import threading
import time
import weakref
from collections.abc import Callable, Iterator
from pathlib import Path

import pytest
from pytestqt.qtbot import QtBot

from aoi.core.jobs import Job, Jobs
from aoi.core.services import AppContext
from aoi.ui.workers import Worker, start

ROOT = Path(__file__).resolve().parents[1]


def count_to(n: int, progress: Callable[..., None], should_stop: Callable[[], bool]) -> int:
    """A job function: `n` steps of 10 ms, each reported; stops early when asked and returns the steps done."""
    done = 0
    for i in range(1, n + 1):
        if should_stop():
            break
        time.sleep(0.01)
        progress(i, n, f"step {i}")
        done = i
    return done


@pytest.fixture
def jobs() -> Iterator[Jobs]:
    pool = Jobs(max_workers=2)
    yield pool
    pool.shutdown()


def test_req_set_021_jobs_api_imports_no_qt() -> None:
    qt = ("PySide6", "shiboken6")
    code = f"import sys, aoi.core.jobs; print(sorted(m for m in sys.modules if m.split('.')[0] in {qt!r}))"
    out = subprocess.run([sys.executable, "-c", code], cwd=ROOT, capture_output=True, text=True, check=True).stdout
    assert out.strip() == "[]"


def test_req_set_021_job_reports_progress_then_result_then_finished(jobs: Jobs) -> None:
    events: list[tuple] = []
    job = Job("count", count_to, 5, with_progress=True)
    job.on_progress(lambda v: events.append(("progress", v))).on_result(lambda r: events.append(("result", r)))
    job.on_error(lambda e: events.append(("error", e))).on_finished(lambda: events.append(("finished",)))
    jobs.submit(job)
    assert job.wait(10) and (job.result, job.error, job.cancelled) == (5, None, False)
    assert [e[1] for e in events if e[0] == "progress"] == [(i, 5, f"step {i}") for i in range(1, 6)]
    assert events[-2:] == [("result", 5), ("finished",)]
    p = job.progress()
    assert (p.done, p.total, p.message, p.left_s) == (5, 5, "step 5", 0.0)
    assert 0 < p.elapsed_s < 10  # 50 ms of sleeps can read 47 ms: the Windows monotonic clock ticks every 15.6 ms


def test_req_set_021_cancel_stops_a_job_between_steps_and_keeps_its_partial_result(jobs: Jobs) -> None:
    job = jobs.submit(Job("count", count_to, 1000, with_progress=True))
    deadline = time.monotonic() + 10
    while job.progress().done < 3 and time.monotonic() < deadline:
        time.sleep(0.005)
    estimate = job.progress()
    job.cancel()
    assert job.wait(10) and job.cancelled and job.result is not None and 3 <= job.result < 1000
    expected_left = estimate.elapsed_s / estimate.done * (1000 - estimate.done)  # from the rate so far
    assert estimate.left_s == pytest.approx(expected_left)


def test_req_set_021_neither_an_error_nor_a_cancel_kills_the_pool(jobs: Jobs) -> None:
    def boom() -> None:
        raise ValueError("bad input")

    seen: list[BaseException] = []
    failed = jobs.submit(Job("boom", boom).on_error(seen.append))
    assert failed.wait(10) and isinstance(failed.error, ValueError) and seen == [failed.error]
    events: list[str] = []
    waiting = Job("count", count_to, 1, with_progress=True)
    waiting.on_result(lambda r: events.append("result")).on_error(lambda e: events.append("error"))
    waiting.on_finished(lambda: events.append("finished")).cancel()  # cancelled while still queued: never runs
    jobs.submit(waiting)
    assert waiting.wait(10) and events == ["finished"] and (waiting.result, waiting.error) == (None, None)
    assert jobs.submit(Job("after", count_to, 1, with_progress=True)).wait(10)  # the pool still runs jobs


def test_req_set_021_shutdown_cancels_the_running_job_and_drops_queued_ones() -> None:
    pool = Jobs(max_workers=1)
    ran: list[int] = []
    first = pool.submit(Job("slow", count_to, 1000, with_progress=True))
    queued = pool.submit(Job("queued", ran.append, 1))
    pool.shutdown()
    assert first.done and first.cancelled and first.result is not None and first.result < 1000
    assert ran == [] and queued.cancelled and not queued.done


def test_req_set_021_a_failing_listener_is_logged_and_the_job_still_finishes(jobs: Jobs) -> None:
    records: list[logging.LogRecord] = []
    handler = logging.Handler()
    handler.emit = records.append  # type: ignore[method-assign]
    logging.getLogger("aoi").addHandler(handler)
    try:
        job = jobs.submit(Job("count", count_to, 1, with_progress=True).on_result(lambda r: 1 / 0))
        assert job.wait(10) and job.result == 1
    finally:
        logging.getLogger("aoi").removeHandler(handler)
    (record,) = records
    assert record.getMessage() == "job.listener_failed" and record.exc_info and record.exc_info[0] is ZeroDivisionError
    assert (record.job, record.event) == ("count", "result")  # type: ignore[attr-defined]


def test_req_set_021_worker_signals_arrive_on_the_ui_thread_even_when_nothing_references_it(
    qtbot: QtBot, jobs: Jobs
) -> None:
    ui = threading.get_ident()
    seen: dict[str, list] = {"progress": [], "result": [], "finished": []}

    def click() -> weakref.ref[Worker]:  # a page keeps no reference to the worker it starts: a local in a slot
        w = Worker(count_to, 3, with_progress=True)
        w.signals.progress.connect(lambda v: seen["progress"].append((threading.get_ident(), v)))
        w.signals.result.connect(lambda r: seen["result"].append((threading.get_ident(), r)))
        w.signals.finished.connect(lambda: seen["finished"].append(threading.get_ident()))
        return weakref.ref(start(w, jobs))

    ref = click()
    gc.collect()
    qtbot.waitUntil(lambda: bool(seen["finished"]), timeout=10000)
    assert seen["result"] == [(ui, 3)] and seen["finished"] == [ui]
    assert [v for _, v in seen["progress"]] == [(i, 3, f"step {i}") for i in (1, 2, 3)]
    assert {t for t, _ in seen["progress"]} == {ui}
    qtbot.wait(10)  # the finished slots have run
    gc.collect()
    assert ref() is None, "a finished worker, its signals and its job (which may hold an image) are released"


def test_req_set_021_worker_stop_keeps_partial_work_and_an_error_arrives_as_the_exception(
    qtbot: QtBot, jobs: Jobs
) -> None:
    w = Worker(count_to, 1000, with_progress=True)
    results: list[int] = []
    w.signals.result.connect(results.append)
    start(w, jobs)
    qtbot.waitUntil(lambda: w.job.progress().done >= 3, timeout=10000)
    w.stop()
    qtbot.waitUntil(lambda: bool(results), timeout=10000)
    assert 3 <= results[0] < 1000
    errors: list[BaseException] = []
    failing = Worker(lambda: 1 / 0)
    failing.signals.error.connect(errors.append)  # before start(): a warm pool thread can finish before start() returns
    start(failing, jobs)
    qtbot.waitUntil(lambda: bool(errors), timeout=10000)
    assert isinstance(errors[0], ZeroDivisionError)


def test_req_set_021_appcontext_owns_the_pool_and_close_shuts_it_down(ctx: AppContext) -> None:
    job = ctx.jobs.submit(Job("count", count_to, 2, with_progress=True))
    assert job.wait(10) and job.result == 2
    ctx.close()
    with pytest.raises(RuntimeError):
        ctx.jobs.submit(Job("late", count_to, 1, with_progress=True))
