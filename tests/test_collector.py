"""REQ-INSP-011 (8 hours without a crash): Python's cycle collector runs on the UI thread only, from the timer
`workers.collect_on_ui_thread` starts (main.py, and conftest.py for the suite). The interpreter starts a collection on
whichever thread is allocating when one comes due, and one that an inspection job started freed a Qt object on its pool
thread and crashed Windows CI with an access violation (2026-10-09)."""

from __future__ import annotations

import gc
import threading

from PySide6.QtCore import QObject
from pytestqt.qtbot import QtBot


def test_req_insp_011_a_pool_thread_never_runs_the_collector(qtbot: QtBot) -> None:
    """A job making reference cycles starts no collection on its thread; the UI thread's timer collects once one is
    due, and a cycle holding a Qt object frees it there. Before: the job's thread ran collections and freed it."""
    starts: list[str] = []

    def seen(phase: str, info: dict[str, int]) -> None:
        if phase == "start":
            starts.append(threading.current_thread().name)

    destroyed: list[str] = []
    held = QObject()
    held.destroyed.connect(lambda: destroyed.append(threading.current_thread().name))
    cycle: list[object] = [held]
    cycle.append(cycle)
    del held, cycle

    def job() -> None:
        for _ in range(5000):  # a cycle each: the youngest generation's threshold of 700 passed several times
            loop: list[object] = []
            loop.append(loop)

    gc.callbacks.append(seen)
    try:
        pool = threading.Thread(target=job, name="pool")
        pool.start()
        pool.join()
        assert starts == [] and destroyed == [], "the pool thread ran the collector"
        qtbot.waitUntil(lambda: bool(starts), timeout=5000)  # the timer's next tick: a collection is due
        gc.collect()  # on this thread, what that pass left in an older generation
    finally:
        gc.callbacks.remove(seen)
    assert set(starts) == {"MainThread"} and destroyed == ["MainThread"]
