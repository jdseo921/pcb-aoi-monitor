"""REQ-SET-021 (stage S17b): no page freezes the window while it inspects, imports, exports or tests 5 MP boards.

`gap_meter` ticks a QTimer every 50 ms on the UI thread for the whole page action and records the longest gap between
ticks: a blocked UI thread shows as one long gap. The budget is the Engineering standard's 2 s. The work runs on a pool
thread, so each page's result is still missing when the action returns and arrives later through a slot; a Qt warning
about a widget touched off the UI thread fails the test as well.
"""

from __future__ import annotations

import math
import os
import re
import shutil
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path
from time import perf_counter, sleep

import cv2
import pytest
from PySide6.QtCore import Qt, QTimer, qInstallMessageHandler
from PySide6.QtWidgets import QFileDialog, QInputDialog, QMessageBox, QWidget
from pytestqt.qtbot import QtBot

from aoi.core.services import AppContext, classification_metrics
from aoi.data import atomic
from aoi.ui import theme
from aoi.ui.pages.training import NgDialog
from aoi.ui.widgets.busy import BusyOverlay
from aoi.ui.workers import Worker, start
from tests.test_jobs import count_to
from tests.test_req_done_in_v01 import BOARD, _window

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
def gap_meter(qtbot: QtBot) -> Iterator[dict[str, float]]:
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


def test_req_set_021_gap_meter_sees_a_blocked_ui_thread(qtbot: QtBot) -> None:
    with gap_meter(qtbot) as g:
        sleep(0.3)  # work on the UI thread: what no page test may show
        qtbot.wait(TICK_MS * 2)
    assert 0.3 <= g["longest_s"] < BUDGET_S


def test_req_set_021_inspection_does_not_freeze(qtbot: QtBot, trained_ctx: AppContext, board_5mp: Path) -> None:
    win = _window(qtbot, trained_ctx, "Operator")
    page = win.pages["Inspection"]
    page._set_queue([board_5mp])
    with gap_meter(qtbot) as g:
        page.next_board()
        assert page.last is None, "the inspection runs on a pool thread: no result before the action returns"
        qtbot.waitUntil(lambda: page.last is not None, timeout=60000)
    assert g["longest_s"] < BUDGET_S, g


def test_req_set_021_compare_does_not_freeze(qtbot: QtBot, trained_ctx: AppContext, board_5mp: Path) -> None:
    win = _window(qtbot, trained_ctx)
    page = win.pages["Compare"]
    with gap_meter(qtbot) as g:
        page.set_test(str(board_5mp))
        assert page.res is None, "the inspection runs on a pool thread: no result before the action returns"
        qtbot.waitUntil(lambda: page.res is not None, timeout=60000)
    assert g["longest_s"] < BUDGET_S, g
    assert page.verdict.text() == theme.verdict_label(page.res.verdict)
    assert page.metrics.rowCount() == len(page.res.checks) + 1


def test_req_set_021_model_test_preview_does_not_freeze(qtbot: QtBot, trained_ctx: AppContext, board_5mp: Path) -> None:
    win = _window(qtbot, trained_ctx)
    page = win.pages["AI Model Test"]
    rows = [{"image": str(board_5mp), "gt": "NG", "ai_result": "NG", "score": 1.0, "defects": 1, "pass_fail": "PASS"}]
    page._show((classification_metrics(rows), rows), str(board_5mp.parent), BOARD)  # the table a finished run leaves
    with gap_meter(qtbot) as g:
        page.table.selectRow(0)  # the row preview inspects the board again
        assert win.last_inspected is None, "the preview runs on a pool thread: nothing shown before the action returns"
        qtbot.waitUntil(lambda: win.last_inspected is not None, timeout=60000)
    assert g["longest_s"] < BUDGET_S, g
    assert win.last_inspected[0] == str(board_5mp) and page.view._pix is not None


def test_req_set_021_recipe_editor_test_run_does_not_freeze(
    qtbot: QtBot, trained_ctx: AppContext, board_5mp: Path
) -> None:
    win = _window(qtbot, trained_ctx)
    page = win.pages["Recipe Editor"]
    with gap_meter(qtbot) as g:
        page.run_test(str(board_5mp))
        assert page.test_verdict.text() == "", "the test run is on a pool thread: no verdict before the action returns"
        qtbot.waitUntil(lambda: page.test_verdict.text().startswith("Try result:"), timeout=60000)
    assert g["longest_s"] < BUDGET_S, g


def test_req_set_021_training_folder_import_does_not_freeze(
    qtbot: QtBot, trained_ctx: AppContext, board_5mp: Path, tmp_path: Path
) -> None:
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


def test_req_set_021_busy_indicator_waits_a_second_then_shows_progress_time_left_and_cancel(
    qtbot: QtBot, ctx: AppContext
) -> None:
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


def test_req_set_021_single_board_job_shows_elapsed_time_and_cancel_but_no_time_left(
    qtbot: QtBot, trained_ctx: AppContext, ng_board: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """#194: past the busy overlay's detail stage, Compare (like the AI Model Test preview and Recipe Test Run, which
    also inspect one board) shows the seconds so far, a bar with no range and Cancel, and no time left: one inspection
    reports no steps, so there is no count to show (docs/ARCHITECTURE.md, the REQ-SET-021 row)."""
    real = trained_ctx.inspect
    monkeypatch.setattr(trained_ctx, "inspect", lambda *a, **k: sleep(2) or real(*a, **k))  # a slow 5 MP board
    win = _window(qtbot, trained_ctx)
    page = win.pages["Compare"]
    win.navigate("Compare")
    page.busy.SHOW_AFTER_S, page.busy.DETAIL_AFTER_S = 0.1, 0.5  # the 1 s and 10 s of the product, shortened
    page.set_test(str(ng_board))
    qtbot.waitUntil(page.busy.cancel_button.isVisible, timeout=10000)
    qtbot.wait(800)  # four more ticks of the overlay past the detail stage
    assert re.fullmatch(r"Inspecting…  \d+ s", page.busy.label.text()), page.busy.label.text()
    assert page.busy.bar.isVisible() and (page.busy.bar.minimum(), page.busy.bar.maximum()) == (0, 0)
    qtbot.mouseClick(page.busy.cancel_button, Qt.MouseButton.LeftButton)
    qtbot.waitUntil(lambda: page._bg is None, timeout=30000)


def _copies_for_a_stall(src: Path, tmp: Path) -> int:
    """How many crash-safe copies of `src` take about 1.5 times the budget on this machine now (20 to 400), so the
    same copies run on the UI thread would stall it past 2 s whatever the disk's speed."""
    t0 = perf_counter()
    for i in range(5):
        atomic.copy_file(src, tmp / f"probe_{i}.png")
    n = min(400, max(20, math.ceil(1.5 * BUDGET_S / ((perf_counter() - t0) / 5))))
    print(f"{n} copies of {src.stat().st_size} bytes")  # shown with -rA
    return n


def _cancel_when_started(qtbot: QtBot, busy: BusyOverlay, started: Callable[[], bool]) -> None:
    """Click Cancel on `busy` once it shows (its 10 s shortened to 0.3 s) and the job has done some of its work."""
    qtbot.waitUntil(lambda: busy.cancel_button.isVisible() and started(), timeout=60000)
    qtbot.mouseClick(busy.cancel_button, Qt.MouseButton.LeftButton)


def test_req_set_021_logs_export_does_not_freeze(
    qtbot: QtBot, trained_ctx: AppContext, board_5mp: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """#194: Export Image Overlays and Export CSV run on a pool thread under the table's busy overlay; Cancel keeps the
    overlays already copied and says how many, and a CSV export cancelled before it writes leaves no file."""
    n = _copies_for_a_stall(board_5mp, tmp_path)
    (tmp_path / "overlays").mkdir()
    for i in range(n):  # one 5 MP overlay per record, each under its own name (hard links: no disk for n copies)
        overlay = tmp_path / "overlays" / f"overlay_{i:03d}.png"
        os.link(board_5mp, overlay)
        rec = {"board_model": BOARD, "result": "OK", "view": "Top", "image_path": str(overlay)}
        trained_ctx.db.add_inspection({**rec, "overlay_path": str(overlay)}, [], None)
    win = _window(qtbot, trained_ctx)  # an Engineer, since exports need the role
    page = win.pages["Logs & Export"]
    win.navigate("Logs & Export")
    assert len(page.rows) == n
    folder = {"out": tmp_path / "out"}
    folder["out"].mkdir()
    monkeypatch.setattr(QMessageBox, "question", staticmethod(lambda *a, **k: QMessageBox.StandardButton.Yes))
    monkeypatch.setattr(QFileDialog, "getExistingDirectory", staticmethod(lambda *a, **k: str(folder["out"])))
    out_csv = tmp_path / "out" / "inspections.csv"
    monkeypatch.setattr(QFileDialog, "getSaveFileName", staticmethod(lambda *a, **k: (str(out_csv), "CSV (*.csv)")))
    status = win.statusBar().currentMessage

    def copied(d: Path) -> int:
        return len(list(d.glob("overlay_*.png")))  # a copy in progress has a temporary name

    with gap_meter(qtbot) as g:
        page.export_overlays()
        assert copied(folder["out"]) < n, "the copy runs on a pool thread: not every overlay before the action returns"
        qtbot.waitUntil(lambda: status().startswith("Copied"), timeout=120000)
    assert g["longest_s"] < BUDGET_S, g
    assert copied(folder["out"]) == n and status() == f"Copied {n} overlay image(s) to {folder['out']}"
    with gap_meter(qtbot) as g:
        page.export_csv()
        assert not out_csv.exists(), "the CSV export runs on a pool thread: no file before the action returns"
        qtbot.waitUntil(lambda: status().startswith("Exported"), timeout=60000)
    assert g["longest_s"] < BUDGET_S, g
    assert out_csv.read_text(encoding="utf-8-sig").count("\n") == n + 1  # the header and one line per record
    assert out_csv.with_name("inspections_checks.csv").exists()

    page.busy.SHOW_AFTER_S, page.busy.DETAIL_AFTER_S = 0.1, 0.3  # the 1 s and 10 s of the product, shortened
    folder["out"] = tmp_path / "out2"
    folder["out"].mkdir()
    page.export_overlays()
    _cancel_when_started(qtbot, page.busy, lambda: copied(folder["out"]) > 0)
    qtbot.waitUntil(lambda: status().startswith("Stopped"), timeout=60000)
    kept = copied(folder["out"])
    assert 0 < kept < n
    assert status() == f"Stopped: copied {kept} overlay image(s) to {folder['out']}; the others were not copied."
    entry = trained_ctx.audit_entries(action="export.overlays")[0]
    assert (entry["after"]["copied"], entry["after"]["cancelled"]) == (kept, True)

    real = trained_ctx.defects_for
    monkeypatch.setattr(trained_ctx, "defects_for", lambda iid: sleep(0.02) or real(iid))  # a slow database
    out_csv = tmp_path / "out2" / "inspections.csv"
    page.export_csv()
    _cancel_when_started(qtbot, page.busy, lambda: True)
    qtbot.waitUntil(lambda: status().startswith("Export CSV stopped"), timeout=60000)
    assert not out_csv.exists() and status() == "Export CSV stopped: no file was written."
    for d in ("out", "out2"):
        shutil.rmtree(tmp_path / d)  # up to 2 GB of copies: free the disk now, not when pytest prunes old runs


def test_req_set_021_training_add_samples_does_not_freeze(
    qtbot: QtBot, trained_ctx: AppContext, board_5mp: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """#194: + OK Images and + NG Images copy the picked files on a pool thread under the dataset's busy overlay; Cancel
    keeps the samples already added and says how many."""
    n = _copies_for_a_stall(board_5mp, tmp_path)
    monkeypatch.setattr(QFileDialog, "getOpenFileNames", staticmethod(lambda *a, **k: ([str(board_5mp)] * n, "")))
    monkeypatch.setattr(QInputDialog, "getItem", staticmethod(lambda *a, **k: ("Top", True)))
    monkeypatch.setattr(NgDialog, "exec", lambda self: 1)  # OK on "Unknown / mixed", Top
    win = _window(qtbot, trained_ctx)
    page = win.pages["Training"]
    win.navigate("Training")
    before = page.samples.rowCount()
    with gap_meter(qtbot) as g:
        page.add_ok()
        assert page.samples.rowCount() == before, "the copies run on a pool thread: the table waits for the result"
        qtbot.waitUntil(lambda: page.samples.rowCount() == before + n, timeout=120000)
    assert g["longest_s"] < BUDGET_S, g
    assert len(trained_ctx.samples(BOARD)) == before + n

    page.busy.SHOW_AFTER_S, page.busy.DETAIL_AFTER_S = 0.1, 0.3  # the 1 s and 10 s of the product, shortened
    ng_dir = trained_ctx.settings.images_dir / BOARD / "NG"
    files_before = len(list(ng_dir.glob("board_5mp_*.png")))
    status = win.statusBar().currentMessage
    page.add_ng()
    _cancel_when_started(qtbot, page.busy, lambda: len(list(ng_dir.glob("board_5mp_*.png"))) > files_before)
    qtbot.waitUntil(lambda: status().startswith("Stopped"), timeout=60000)
    added = len(trained_ctx.samples(BOARD)) - before - n
    assert 0 < added < n and status() == f"Stopped: added {added} of {n} images; the others were not added."
    assert len(list(ng_dir.glob("board_5mp_*.png"))) - files_before == added
    assert page.samples.rowCount() == before + n + added, "the table shows the samples kept"
    entry = trained_ctx.audit_entries(action="sample.import")[0]
    assert (entry["after"]["added"], entry["after"]["cancelled"]) == (added, True)
    for copy in trained_ctx.settings.images_dir.glob(f"{BOARD}/*/board_5mp_*.png"):
        copy.unlink()  # up to 2 GB of copies: free the disk now, not when pytest prunes old runs
