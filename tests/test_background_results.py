"""#132: a page's background job lets go of what it made once the page has shown its result.

Qt keeps a slot connected to a worker's signals as long as the signals, which the worker holds. A slot that held its
worker kept the worker, its job and the job's result for as long as the app ran, so every stored result opened on
Compare and every board inspected stayed in memory (about 70 MB each at 5 MP). Each test holds weak references to the
results a page received and checks they are gone once the page shows another. A job holds no worker and no signals
either: with the garbage collector off, a failed board's signals and AI Model Test's worker must go by reference
counting, on the UI thread, rather than with the job, on whichever thread the collector runs.
"""

from __future__ import annotations

import gc
import weakref
from pathlib import Path

import pytest
from pytestqt.qtbot import QtBot

from aoi.core.inspector import InspectionResult
from aoi.core.jobs import Jobs
from aoi.core.services import AppContext
from aoi.ui.pages import model_test
from aoi.ui.pages.compare import ComparePage
from aoi.ui.pages.inspection import InspectionPage, Outcome
from aoi.ui.pages.model_test import ModelTestPage
from aoi.ui.workers import Worker, _live
from tests.test_compare_views import _compare, _open
from tests.test_jobs import count_to
from tests.test_req_done_in_v01 import BOARD, _window


class Payload:
    """What a job returns: weakly referable, unlike a tuple or a dict."""


def test_issue_132_a_background_job_keeps_nothing_once_its_result_is_shown(
    qtbot: QtBot, trained_ctx: AppContext
) -> None:
    """`Page.run_in_background`, as every page calls it (Compare, the Recipe Editor's Try Recipe…, AI Model Test's
    preview, Training's import), under a busy overlay: once a run's result has reached its slot, or a newer run has
    stopped it, nothing holds the run's worker, its job or what the job returned."""
    win = _window(qtbot, trained_ctx, "Engineer")
    page = win.pages["Compare"]
    assert isinstance(page, ComparePage)
    qtbot.waitUntil(lambda: trained_ctx.jobs.idle() and page._bg is None, timeout=20000)
    made: list[weakref.ref[Payload]] = []
    workers = []
    cancelled: list[int | None] = []

    def make() -> Payload:
        made.append(weakref.ref(p := Payload()))
        return p

    for _ in range(3):
        workers.append(weakref.ref(page.run_in_background(make, on_result=lambda p: None, busy=page.busy)))
        qtbot.waitUntil(lambda: page._bg is None, timeout=10000)
    stop = page.run_in_background(
        count_to,
        500,
        with_progress=True,
        on_result=lambda n: None,
        busy=page.busy,
        on_cancel=cancelled.append,
    )
    stopped = weakref.ref(stop)
    del stop
    # the newest run wins: the one before is stopped, its result dropped and its on_cancel called with the steps done
    workers.append(weakref.ref(page.run_in_background(make, on_result=lambda p: None, busy=page.busy)))
    qtbot.waitUntil(lambda: page._bg is None and not _live, timeout=10000)  # every run's last slot has run
    assert len(cancelled) == 1 and cancelled[0] in (None, *range(500))  # #194: the steps done; None: never ran
    gc.collect()
    assert len(made) == 4 and [r() for r in made] == [None] * 4, "what each job returned is freed"
    assert [r() for r in [*workers, stopped]] == [None] * 5, "each worker, and with it its job, is freed"


def test_issue_132_compare_keeps_only_the_result_it_shows(
    qtbot: QtBot,
    trained_ctx: AppContext,
    ng_board: Path,
    synthetic_dataset: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Opening one stored result after another, then Re-evaluate: each result Compare showed before is freed."""
    other = next(p for p in sorted(synthetic_dataset.glob("test/ng/*.png")) if p != ng_board)
    for path in (ng_board, other):
        trained_ctx.inspect_file(BOARD, str(path))
    b_id, a_id = (r["id"] for r in trained_ctx.inspections(board_model=BOARD)[:2])
    page, _ = _compare(qtbot, trained_ctx, monkeypatch)
    shown = [weakref.ref(_open(qtbot, page, i)) for i in (a_id, b_id, a_id)]
    page.run()  # Re-evaluate: a new result, from the board's image file
    qtbot.waitUntil(lambda: page._bg is None and page.stored is None and page.res is not None, timeout=20000)
    gc.collect()
    assert [r() for r in shown] == [None] * 3, "a stored result goes once another result is shown"


def test_issue_132_inspection_keeps_only_the_board_it_shows(
    qtbot: QtBot, trained_ctx: AppContext, ng_board: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Inspecting three boards one after another: the results of the first two are freed as soon as the next is
    shown, by reference counting alone (the test turns the garbage collector off): nothing that holds a result, its
    worker or its job is held by them in turn. Then a board that fails: its job keeps the error, and the error the
    job, so only the collector frees the job; the worker's signals go with the worker all the same, on this thread."""
    win = _window(qtbot, trained_ctx, "Operator")
    page = win.pages["Inspection"]
    assert isinstance(page, InspectionPage)
    seen: list[weakref.ref[InspectionResult]] = []
    show = page._on_result

    def spy(out: Outcome) -> None:
        seen.append(weakref.ref(out[1]))
        show(out)

    monkeypatch.setattr(page, "_on_result", spy)
    broken = tmp_path / "broken.png"
    broken.write_bytes(ng_board.read_bytes()[:200])  # a PNG cut short: it cannot be decoded
    page._set_queue([ng_board, ng_board, ng_board, broken])
    gc.disable()  # from here, a result kept by a reference cycle stays: only the collector could free it
    try:
        for n in range(1, 4):
            page.next_board()
            qtbot.waitUntil(lambda: page.worker is None and len(seen) == n, timeout=60000)  # noqa: B023
        assert [r() is None for r in seen] == [True, True, False], "only the board shown is kept"
        page.next_board()
        assert page.worker is not None
        signals = weakref.ref(page.worker.signals)
        qtbot.waitUntil(lambda: page.worker is None and not _live, timeout=60000)
        assert signals() is None, "a failed board's signals go with its worker, not with its job"
    finally:
        gc.enable()


def test_issue_132_ai_model_test_lets_go_of_its_worker(
    qtbot: QtBot, trained_ctx: AppContext, synthetic_dataset: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Run Test on AI Model Test: once the run's last slot has run, nothing holds its worker, by reference counting
    alone (the garbage collector is off): the job reports through the worker's emit, never the worker itself."""
    win = _window(qtbot, trained_ctx, "Engineer")
    page = win.pages["AI Model Test"]
    assert isinstance(page, ModelTestPage)
    started: list[weakref.ref[Worker]] = []
    real = model_test.start

    def spy(worker: Worker, jobs: Jobs) -> Worker:
        started.append(weakref.ref(worker))
        return real(worker, jobs)

    monkeypatch.setattr(model_test, "start", spy)
    page.folder = str(synthetic_dataset / "test" / "ng")
    gc.disable()
    try:
        page.run()
        qtbot.waitUntil(lambda: page.btn_run.isEnabled() and not _live, timeout=60000)
        assert len(started) == 1 and started[0]() is None, "the worker is freed with its last slot"
    finally:
        gc.enable()
