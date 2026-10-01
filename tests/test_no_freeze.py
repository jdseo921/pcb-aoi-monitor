"""REQ-SET-021 (stage S17b): no page freezes the window while it inspects, imports or tests a 5 MP board.

`gap_meter` ticks a QTimer every 50 ms on the UI thread for the whole page action and records the longest gap between
ticks: a blocked UI thread shows as one long gap. The budget is the Engineering standard's 2 s. The work runs on a pool
thread, so each page's result is still missing when the action returns and arrives later through a slot; a Qt warning
about a widget touched off the UI thread fails the test as well.
"""

from __future__ import annotations

import shutil
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from time import perf_counter, sleep

import cv2
import pytest
from PySide6.QtCore import Qt, QTimer, qInstallMessageHandler
from PySide6.QtWidgets import QWidget

from aoi.core.services import AppContext, classification_metrics
from aoi.ui import theme
from aoi.ui.widgets.busy import BusyOverlay
from aoi.ui.workers import Worker, start
from tests.test_jobs import count_to
from tests.test_req_done_in_v01 import _window

TICK_MS, BUDGET_S = 50, 2.0
SIZE_5MP = (2592, 1944)


@pytest.fixture(scope="module")
def board_5mp(synthetic_dataset: Path, tmp_path_factory: pytest.TempPathFactory) -> Path:
    """A test-split NG board scaled to the customer's 5 MP."""
    src = next(synthetic_dataset.glob("test/ng/*missing_component*.png"))
    out = tmp_path_factory.mktemp("board_5mp") / "board_5mp.png"
    cv2.imwrite(str(out), cv2.resize(cv2.imread(str(src)), SIZE_5MP, interpolation=cv2.INTER_CUBIC))
    return out


@contextmanager
def gap_meter(qtbot) -> Iterator[dict[str, float]]:
    """The longest UI-thread stall during the block, as `stats["longest_s"]`; Qt thread warnings fail the block."""
    ticks = [perf_counter()]
    warnings: list[str] = []
    timer = QTimer()
    timer.setInterval(TICK_MS)
    timer.timeout.connect(lambda: ticks.append(perf_counter()))
    previous = qInstallMessageHandler(lambda _mode, _ctx, msg: warnings.append(msg) if "thread" in msg else None)
    timer.start()
    stats: dict[str, float] = {}
    try:
        yield stats
    finally:
        timer.stop()
        qInstallMessageHandler(previous)
        ticks.append(perf_counter())
        stats["longest_s"] = max(b - a for a, b in zip(ticks[:-1], ticks[1:], strict=True))
        print(f"longest UI-thread gap {stats['longest_s'] * 1000:.0f} ms over {len(ticks)} ticks")  # shown with -rA
    assert not warnings, warnings


def test_req_set_021_gap_meter_sees_a_blocked_ui_thread(qtbot) -> None:
    with gap_meter(qtbot) as g:
        sleep(0.3)  # work on the UI thread: what no page test may show
        qtbot.wait(TICK_MS * 2)
    assert 0.3 <= g["longest_s"] < BUDGET_S


def test_req_set_021_inspection_does_not_freeze(qtbot, trained_ctx: AppContext, board_5mp: Path) -> None:
    win = _window(qtbot, trained_ctx, "Operator")
    page = win.pages["Inspection"]
    page._set_queue([board_5mp])
    with gap_meter(qtbot) as g:
        page.next_board()
        assert page.last is None, "the inspection runs on a pool thread: no result before the action returns"
        qtbot.waitUntil(lambda: page.last is not None, timeout=60000)
    assert g["longest_s"] < BUDGET_S, g


def test_req_set_021_compare_does_not_freeze(qtbot, trained_ctx: AppContext, board_5mp: Path) -> None:
    win = _window(qtbot, trained_ctx)
    page = win.pages["Compare"]
    with gap_meter(qtbot) as g:
        page.set_test(str(board_5mp))
        assert page.res is None, "the inspection runs on a pool thread: no result before the action returns"
        qtbot.waitUntil(lambda: page.res is not None, timeout=60000)
    assert g["longest_s"] < BUDGET_S, g
    assert page.verdict.text() == theme.verdict_label(page.res.verdict)
    assert page.metrics.rowCount() == len(page.res.checks) + 1


def test_req_set_021_model_test_preview_does_not_freeze(qtbot, trained_ctx: AppContext, board_5mp: Path) -> None:
    win = _window(qtbot, trained_ctx)
    page = win.pages["AI Model Test"]
    rows = [{"image": str(board_5mp), "gt": "NG", "ai_result": "NG", "score": 1.0, "defects": 1, "pass_fail": "PASS"}]
    page._show((classification_metrics(rows), rows))  # the table a finished test run leaves
    with gap_meter(qtbot) as g:
        page.table.selectRow(0)  # the row preview inspects the board again
        assert win.last_inspected is None, "the preview runs on a pool thread: nothing shown before the action returns"
        qtbot.waitUntil(lambda: win.last_inspected is not None, timeout=60000)
    assert g["longest_s"] < BUDGET_S, g
    assert win.last_inspected[0] == str(board_5mp) and page.view._pix is not None


def test_req_set_021_recipe_editor_test_run_does_not_freeze(qtbot, trained_ctx: AppContext, board_5mp: Path) -> None:
    win = _window(qtbot, trained_ctx)
    page = win.pages["Recipe Editor"]
    with gap_meter(qtbot) as g:
        page.run_test(str(board_5mp))
        assert page.test_verdict.text() == "", "the test run is on a pool thread: no verdict before the action returns"
        qtbot.waitUntil(lambda: page.test_verdict.text().startswith("Try result:"), timeout=60000)
    assert g["longest_s"] < BUDGET_S, g


def test_req_set_021_training_folder_import_does_not_freeze(qtbot, trained_ctx, board_5mp: Path, tmp_path) -> None:
    for name in ("ok/a.png", "ok/b.png", "ng/c.png"):
        (tmp_path / "import" / name).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(board_5mp, tmp_path / "import" / name)
    win = _window(qtbot, trained_ctx)
    page = win.pages["Training"]
    before = page.samples.rowCount()
    with gap_meter(qtbot) as g:
        page.import_from(str(tmp_path / "import"))
        assert page.samples.rowCount() == before, "the import runs on a pool thread: the table waits for the result"
        qtbot.waitUntil(lambda: page.samples.rowCount() == before + 3, timeout=60000)
    assert g["longest_s"] < BUDGET_S, g
    assert win.statusBar().currentMessage() == "Imported 2 OK and 1 NG images"


def test_req_set_021_busy_indicator_waits_a_second_then_shows_progress_time_left_and_cancel(qtbot, ctx) -> None:
    host = QWidget()
    qtbot.addWidget(host)
    host.resize(400, 300)
    host.show()
    qtbot.waitExposed(host)
    busy = BusyOverlay(host, "Counting…")
    busy.SHOW_AFTER_S, busy.DETAIL_AFTER_S = 0.1, 0.3  # the 1 s and 10 s of the product, shortened for the test
    results: list[int] = []
    w = Worker(count_to, 1000, with_progress=True)
    w.signals.result.connect(results.append)
    busy.watch(w.job)
    start(w, ctx.jobs)
    assert not busy.isVisible()
    qtbot.waitUntil(busy.isVisible, timeout=5000)
    assert busy.elapsed_s >= 0.1 and busy.label.text().startswith("Counting…") and not busy.cancel_button.isVisible()
    qtbot.waitUntil(busy.cancel_button.isVisible, timeout=5000)
    assert busy.elapsed_s >= 0.3 and busy.bar.maximum() == 1000 and "s left" in busy.label.text()
    assert busy.geometry() == host.rect()
    qtbot.mouseClick(busy.cancel_button, Qt.LeftButton)
    assert w.job.cancelled and not busy.isVisible()
    qtbot.waitUntil(lambda: bool(results), timeout=5000)
    assert results[0] < 1000, "Cancel stops the job at its next step and keeps what it did"
