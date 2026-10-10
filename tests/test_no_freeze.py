"""REQ-SET-021 (stage S17b): no page freezes the window while it inspects, imports, exports or tests 5 MP boards.

`gap_meter` ticks a QTimer every 50 ms on the UI thread for the whole page action and records the longest gap between
ticks: a blocked UI thread shows as one long gap. The budget is the Engineering standard's 2 s. The work runs on a pool
thread, so each page's result is still missing when the action returns and arrives later through a slot; a Qt warning
about a widget touched off the UI thread fails the test as well.

A 5 MP board's decode, inspection and save take about 0.5 s, which fits the budget even on the UI thread, and a result
that arrives through a slot says nothing of where the work ran (#208). So `heavy_calls` wraps the calls that do the
work and records the thread of each, and `assert_off_ui_thread` fails a page whose work ran on the UI thread or never
reached a wrapped call; the first engine inspection (or sample import, or export) also stalls past the budget, so the
gap meter fails such a page as well, whatever the board size or the machine's speed.
"""

from __future__ import annotations

import functools
import math
import os
import re
import shutil
import threading
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path
from time import perf_counter, sleep

import cv2
import numpy as np
import pytest
from PySide6.QtCore import Qt, QTimer, qInstallMessageHandler
from PySide6.QtWidgets import QFileDialog, QMessageBox, QWidget
from pytestqt.qtbot import QtBot

from aoi.core.imaging import checked_bytes
from aoi.core.inspector import Inspector
from aoi.core.services import AppContext, classification_metrics
from aoi.data import atomic
from aoi.ui import theme
from aoi.ui.widgets.busy import BusyOverlay
from aoi.ui.workers import Worker, start
from tests.conftest import distinct_copies, listed
from tests.test_jobs import count_to
from tests.test_req_done_in_v01 import BOARD, _window

TICK_MS, BUDGET_S = 50, 2.0
SIZE_5MP = (2592, 1944)
STALL_S = BUDGET_S + 0.5  # longer than the budget: on the UI thread it is one gap the meter cannot miss
HEAVY: dict[type, tuple[str, ...]] = {
    AppContext: ("load_image", "inspector", "inspect", "inspect_file", "log_result", "import_samples")
    + ("re_evaluate",)  # Compare's Re-evaluate on a stored result (REQ-CMP-005)
    + ("checks_for_many", "export_csv_files", "export_overlays"),  # the Logs exports' work (#194)
    Inspector: ("inspect",),
}


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


@contextmanager
def heavy_calls(stall: str = "Inspector.inspect") -> Iterator[list[tuple[str, bool]]]:
    """Wrap the calls in HEAVY for the block and record each as `(name, ran on the UI thread)`; the first call to
    `stall` sleeps STALL_S before it works. Pass the list to `assert_off_ui_thread` once the page's result is in."""
    calls: list[tuple[str, bool]] = []
    stalled = threading.Event()

    def wrap(name: str, fn: Callable[..., object]) -> Callable[..., object]:
        @functools.wraps(fn)
        def recorded(*args: object, **kwargs: object) -> object:
            calls.append((name, threading.current_thread() is threading.main_thread()))
            if name == stall and not stalled.is_set():
                stalled.set()
                sleep(STALL_S)
            return fn(*args, **kwargs)

        return recorded

    with pytest.MonkeyPatch.context() as mp:
        for cls, names in HEAVY.items():
            for n in names:
                mp.setattr(cls, n, wrap(f"{cls.__name__}.{n}", getattr(cls, n)))
        yield calls


def assert_off_ui_thread(calls: list[tuple[str, bool]], *expected: str) -> None:
    """Each of `expected` was called (the wrappers are on the page's path) and no wrapped call ran on the UI thread."""
    names = {n for n, _ in calls}
    assert names >= set(expected), f"the page never called {sorted(set(expected) - names)}; it called {sorted(names)}"
    on_ui = [n for n, ui in calls if ui]
    assert not on_ui, f"work ran on the UI thread: {on_ui}"


def test_req_set_021_heavy_calls_see_work_on_the_ui_thread(qtbot: QtBot, ctx: AppContext, tmp_path: Path) -> None:
    """The helper's self-test: a call on the UI thread fails it, the same call on the pool passes, a call never made
    fails it, the stall falls once, on the named call, and each class holds its own methods again after the block."""
    originals = {(cls, n): cls.__dict__[n] for cls, names in HEAVY.items() for n in names}
    img = tmp_path / "a.png"
    cv2.imwrite(str(img), np.full((48, 64, 3), 128, np.uint8))
    with heavy_calls(stall="AppContext.load_image") as calls:
        t0 = perf_counter()
        ctx.load_image(img)
        assert perf_counter() - t0 >= STALL_S
        t0 = perf_counter()
        ctx.load_image(img)
        assert perf_counter() - t0 < STALL_S
    assert calls == [("AppContext.load_image", True)] * 2
    with pytest.raises(AssertionError, match="work ran on the UI thread"):
        assert_off_ui_thread(calls, "AppContext.load_image")
    with heavy_calls(stall="none") as calls:
        results: list[object] = []
        w = Worker(ctx.load_image, img)
        w.signals.result.connect(results.append)
        start(w, ctx.jobs)
        qtbot.waitUntil(lambda: bool(results), timeout=5000)
    assert_off_ui_thread(calls, "AppContext.load_image")
    with pytest.raises(AssertionError, match="never called"):
        assert_off_ui_thread(calls, "Inspector.inspect")
    left = [f"{cls.__name__}.{n}" for (cls, n), fn in originals.items() if cls.__dict__[n] is not fn]
    assert not left, f"wrappers left in place after the block: {left}"  # functools.wraps hides them from __qualname__


def test_req_set_021_gap_meter_sees_a_blocked_ui_thread(qtbot: QtBot) -> None:
    with gap_meter(qtbot) as g:
        sleep(0.3)  # work on the UI thread: what no page test may show
        qtbot.wait(TICK_MS * 2)
    assert 0.3 <= g["longest_s"] < BUDGET_S


def test_req_set_021_inspection_does_not_freeze(qtbot: QtBot, trained_ctx: AppContext, board_5mp: Path) -> None:
    win = _window(qtbot, trained_ctx, "Operator")
    page = win.pages["Inspection"]
    page._set_queue([board_5mp])
    with heavy_calls() as calls, gap_meter(qtbot) as g:
        page.next_board()
        assert page.last is None, "the inspection runs on a pool thread: no result before the action returns"
        qtbot.waitUntil(lambda: page.last_id is not None, timeout=60000)
    assert_off_ui_thread(calls, "AppContext.load_image", "Inspector.inspect", "AppContext.log_result")
    assert g["longest_s"] < BUDGET_S, g


def test_req_set_021_compare_does_not_freeze(qtbot: QtBot, trained_ctx: AppContext, board_5mp: Path) -> None:
    win = _window(qtbot, trained_ctx)
    page = win.pages["Compare"]
    with heavy_calls() as calls, gap_meter(qtbot) as g:
        page.set_test(str(board_5mp))
        assert page.res is None, "the inspection runs on a pool thread: no result before the action returns"
        qtbot.waitUntil(lambda: page.res is not None, timeout=60000)
    assert_off_ui_thread(calls, "AppContext.load_image", "AppContext.inspect", "Inspector.inspect")
    assert g["longest_s"] < BUDGET_S, g
    assert page.verdict.text() == theme.verdict_label(page.res.verdict)
    assert page.metrics.rowCount() == len(page.res.checks) + 1


def test_req_set_021_model_test_preview_does_not_freeze(qtbot: QtBot, trained_ctx: AppContext, board_5mp: Path) -> None:
    win = _window(qtbot, trained_ctx)
    page = win.pages["AI Model Test"]
    rows = [{"image": str(board_5mp), "gt": "NG", "ai_result": "NG", "score": 1.0, "defects": 1, "pass_fail": "PASS"}]
    judged_by = trained_ctx.inspector(BOARD).judged_by  # judged by what is in use, so the row is previewed (#250)
    page._show((classification_metrics(rows), rows, judged_by), str(board_5mp.parent), BOARD)  # a finished run's table
    with heavy_calls() as calls, gap_meter(qtbot) as g:
        page.table.selectRow(0)  # the row preview inspects the board again
        assert win.last_inspected is None, "the preview runs on a pool thread: nothing shown before the action returns"
        qtbot.waitUntil(lambda: win.last_inspected is not None, timeout=60000)
    assert_off_ui_thread(calls, "AppContext.inspect_file", "AppContext.load_image", "Inspector.inspect")
    assert g["longest_s"] < BUDGET_S, g
    assert win.last_inspected[0] == str(board_5mp) and page.view._pix is not None


def test_req_set_021_recipe_editor_test_run_does_not_freeze(
    qtbot: QtBot, trained_ctx: AppContext, board_5mp: Path
) -> None:
    win = _window(qtbot, trained_ctx)
    page = win.pages["Recipe Editor"]
    with heavy_calls() as calls, gap_meter(qtbot) as g:
        page.run_test(str(board_5mp))
        assert page.test_verdict.text() == "", "the test run is on a pool thread: no verdict before the action returns"
        qtbot.waitUntil(lambda: page.test_verdict.text().startswith("Try result:"), timeout=60000)
    assert_off_ui_thread(calls, "AppContext.inspector", "AppContext.load_image", "Inspector.inspect")
    assert g["longest_s"] < BUDGET_S, g


def test_req_set_021_training_folder_import_does_not_freeze(
    qtbot: QtBot, trained_ctx: AppContext, board_5mp: Path, tmp_path: Path
) -> None:
    boards = distinct_copies(board_5mp, tmp_path / "boards", 3)  # three images: one is imported once (Q31)
    for board, name in zip(boards, ("ok/a.png", "ok/b.png", "ng/missing_component/c.png"), strict=True):
        (tmp_path / "import" / name).parent.mkdir(parents=True, exist_ok=True)  # an NG image is imported with its type
        shutil.copy(board, tmp_path / "import" / name)
    win = _window(qtbot, trained_ctx)
    page = win.pages["Training"]
    before = page.samples.rowCount()
    with heavy_calls(stall="AppContext.import_samples") as calls, gap_meter(qtbot) as g:
        page.import_from(str(tmp_path / "import"))  # the import sheet, each file labelled by its folder
        page.sheet.btn_import.click()
        assert page.samples.rowCount() == before, "the import runs on a pool thread: the table waits for the result"
        qtbot.waitUntil(lambda: page.samples.rowCount() == before + 3, timeout=60000)
    assert_off_ui_thread(calls, "AppContext.import_samples")
    assert g["longest_s"] < BUDGET_S, g
    assert win.statusBar().currentMessage() == f"Imported 2 OK and 1 NG images into {BOARD}"


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


def _copies_for_a_stall(src: Path, tmp: Path, checked: bool = False) -> int:
    """How many crash-safe copies of `src` take about 1.5 times the budget on this machine now (20 to 400), so the
    same copies run on the UI thread would stall it past 2 s whatever the disk's speed; `checked`, each copy after
    the checks and decoding an import makes (REQ-TRN-001)."""
    t0 = perf_counter()
    for i in range(5):
        if checked:
            checked_bytes(src)
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
    win = _window(qtbot, trained_ctx, "Admin")  # only an Admin exports (Q58, #151)
    page = win.pages["Logs & Export"]
    win.navigate("Logs & Export")
    listed(qtbot, page)
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

    with heavy_calls(stall="AppContext.export_overlays") as calls, gap_meter(qtbot) as g:
        page.export_overlays()
        assert copied(folder["out"]) < n, "the copy runs on a pool thread: not every overlay before the action returns"
        qtbot.waitUntil(lambda: status().startswith("Copied"), timeout=120000)
    assert_off_ui_thread(calls, "AppContext.export_overlays")
    assert g["longest_s"] < BUDGET_S, g
    assert copied(folder["out"]) == n and status() == f"Copied {n} overlay image(s) to {folder['out']}"
    with heavy_calls(stall="AppContext.export_csv_files") as calls, gap_meter(qtbot) as g:
        page.export_csv()
        assert not out_csv.exists(), "the CSV export runs on a pool thread: no file before the action returns"
        qtbot.waitUntil(lambda: status().startswith("Exported"), timeout=60000)
    assert_off_ui_thread(calls, "AppContext.checks_for_many", "AppContext.export_csv_files")
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

    real, clicked = trained_ctx.defects_for, threading.Event()
    # A database that answers only once Cancel is clicked, so the export stops after its first record on any machine.
    # A 20 ms answer per record raced Cancel, shown 0.4 s in: when the click landed after the export's check for it
    # before the last record, the export wrote both files and said so, and the stop awaited below never came (Windows CI
    # on #258, #266, #269). The wait outlasts the helper's 60 s, so the answer comes only after a click or a failure.
    monkeypatch.setattr(trained_ctx, "defects_for", lambda iid: (clicked.wait(120), real(iid))[1])
    out_csv = tmp_path / "out2" / "inspections.csv"
    try:
        page.export_csv()
        _cancel_when_started(qtbot, page.busy, lambda: True)
    finally:
        clicked.set()  # the pool thread never waits past the test
    qtbot.waitUntil(lambda: status().startswith("Export CSV stopped"), timeout=60000)
    assert not out_csv.exists() and not out_csv.with_name("inspections_checks.csv").exists()
    assert status() == "Export CSV stopped: no file was written."
    for d in ("out", "out2"):
        shutil.rmtree(tmp_path / d)  # up to 2 GB of copies: free the disk now, not when pytest prunes old runs


def test_req_set_021_training_add_samples_does_not_freeze(
    qtbot: QtBot, trained_ctx: AppContext, board_5mp: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """#194: Add OK Images… and Add NG Images… copy the picked files on a pool thread under the dataset's busy overlay
    once Import is pressed on the sheet; Cancel keeps the samples already added and says how many."""
    n = _copies_for_a_stall(board_5mp, tmp_path, checked=True)
    picked = {"ok": [str(p) for p in distinct_copies(board_5mp, tmp_path / "ok", n)]}  # each imported once (Q31)
    monkeypatch.setattr(QFileDialog, "getOpenFileNames", staticmethod(lambda *a, **k: (picked["ok"], "")))
    win = _window(qtbot, trained_ctx)
    page = win.pages["Training"]
    win.navigate("Training")
    before = page.samples.rowCount()
    with heavy_calls(stall="AppContext.import_samples") as calls, gap_meter(qtbot) as g:
        page.add_ok()
        page.sheet.btn_import.click()
        assert page.samples.rowCount() == before, "the copies run on a pool thread: the table waits for the result"
        qtbot.waitUntil(lambda: page.samples.rowCount() == before + n, timeout=120000)
    assert_off_ui_thread(calls, "AppContext.import_samples")
    assert g["longest_s"] < BUDGET_S, g
    assert len(trained_ctx.samples(BOARD)) == before + n
    # The job ends just after its result shows, and Add NG Images… is off until then: pressed sooner (the pool thread
    # waiting for the GIL between the two), the page starts no second import and the Cancel below never shows
    qtbot.waitUntil(page.btn_ng.isEnabled, timeout=60000)

    page.busy.SHOW_AFTER_S, page.busy.DETAIL_AFTER_S = 0.1, 0.3  # the 1 s and 10 s of the product, shortened
    ng_dir = trained_ctx.settings.images_dir / BOARD / "NG"
    files_before = len(list(ng_dir.glob("board_5mp_*.png")))
    status = win.statusBar().currentMessage
    picked["ok"] = [str(p) for p in distinct_copies(board_5mp, tmp_path / "ng", n)]
    page.add_ng()
    page.sheet.type_box.setCurrentIndex(0)
    page.sheet.type_box.activated.emit(0)  # one of the 33 types for all the NG files
    page.sheet.btn_import.click()
    _cancel_when_started(qtbot, page.busy, lambda: len(list(ng_dir.glob("board_5mp_*.png"))) > files_before)
    qtbot.waitUntil(lambda: status().startswith("Import cancelled"), timeout=60000)
    added = len(trained_ctx.samples(BOARD)) - before - n
    stopped = f"Import cancelled: 0 OK and {added} NG images imported into {BOARD} before it stopped"
    assert 0 < added < n and status() == stopped, status()
    assert len(list(ng_dir.glob("board_5mp_*.png"))) - files_before == added
    assert page.samples.rowCount() == before + n + added, "the table shows the samples kept"
    entries = trained_ctx.audit_entries(action="sample.import")[: added + 1]  # one a file (REQ-TRN-001, S31)
    assert [e["after"]["label"] for e in entries] == ["NG"] * added + ["OK"]
    for copy in trained_ctx.settings.images_dir.glob(f"{BOARD}/*/board_5mp_*.png"):
        copy.unlink()  # up to 2 GB of copies: free the disk now, not when pytest prunes old runs
