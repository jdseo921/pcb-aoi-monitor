"""REQ-SET-020 (stage S55): the app is usable within 5 s of starting and switches pages within 300 ms, on a workspace
with 50 board models and 100,000 inspection records, written once for the module by tools/seed_workspace.py.

The start-up is timed from before a process of its own starts (tests/startup_worker.py runs main.main() in it) to the
window shown, exposed and painted, three times. A page switch is MainWindow.navigate from the page before to the new
page painted, for every sidebar page in turn as the Admin, who may open them all, in two rounds; the first opening of
each page after the start counts as any other. Logs & Export lists its records on the pool thread once shown (S55):
before the next switch the test waits until the rows are shown, and prints how long that took, since filling the table
runs on the UI thread and would land in the switch after it.

The budgets are the reference PC's (Engineering standard, performance budgets) and are asserted as written on every
machine, a CI runner included; the times measured are printed with each test's output (pytest -s shows them)."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import time
from pathlib import Path
from time import perf_counter
from typing import Any

import pytest
from PySide6.QtCore import QEvent, QObject
from PySide6.QtWidgets import QApplication, QWidget
from pytestqt.qtbot import QtBot

from aoi.config import Settings
from aoi.core.services import AppContext
from aoi.ui.main_window import MainWindow
from aoi.ui.pages.logs import LogsPage
from tests.conftest import listed
from tests.test_ui_offscreen import _record
from tools.seed_workspace import seed

ROOT = Path(__file__).resolve().parents[1]
START_BUDGET_S, SWITCH_BUDGET_S = 5.0, 0.3
STARTS, ROUNDS = 3, 2


@pytest.fixture(scope="module")
def seeded(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """A workspace with 50 board models and 100,000 records (about 15 s and 470 MB on disk)."""
    root = tmp_path_factory.mktemp("seeded") / "workspace"
    s = seed(root)
    assert (len(s.board_models), s.records) == (50, 100_000)
    return root


class Painted(QObject):
    """Notes when `widget` is next painted."""

    def __init__(self, widget: QWidget) -> None:
        super().__init__(widget)
        self.painted = False
        widget.installEventFilter(self)

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:  # noqa: N802 (Qt's name)
        if event.type() == QEvent.Type.Paint:
            self.painted = True
        return False


def test_req_set_020_starts_usable_within_5_s(seeded: Path, tmp_path: Path) -> None:
    """Each of three starts of main.main() on the seeded workspace, as settings.json names it, shows its window, on
    Home as a first start opens, within 5 s of the process being started."""
    settings = tmp_path / "default_workspace"
    settings.mkdir()
    (settings / "settings.json").write_text(json.dumps({"workspace": str(seeded)}), encoding="utf-8")
    starts = []
    for _ in range(STARTS):
        env = {**os.environ, "AOI_WORKSPACE": str(settings), "AOI_STARTUP_LAUNCHED": repr(time.time())}
        cmd = [sys.executable, "-m", "tests.startup_worker"]
        done = subprocess.run(cmd, cwd=ROOT, env=env, capture_output=True, text=True, timeout=120)
        assert done.returncode == 0, done.stderr
        start = json.loads(done.stdout.strip().splitlines()[-1])
        assert start["exposed"], "the window was never exposed"
        starts.append(start)
    shown = [{k: round(v, 2) if isinstance(v, float) else v for k, v in s.items()} for s in starts]
    print("\nREQ-SET-020 start-up, seconds:", *map(json.dumps, shown))
    slowest = max(s["usable"] for s in starts)
    assert slowest <= START_BUDGET_S, f"usable after {slowest:.2f} s of the {START_BUDGET_S} s budget: {starts}"


@pytest.mark.usefixtures("settled_collector")  # the budget is the switch's, not a collector pass over earlier tests'
def test_req_set_020_switches_every_page_within_300_ms(qtbot: QtBot, seeded: Path) -> None:
    """Every sidebar page opens, painted, within 300 ms of navigate, in each of two rounds as the Admin."""
    ctx = AppContext(Settings(workspace=str(seeded), device="cpu"))
    win = MainWindow(ctx)
    qtbot.addWidget(win)
    win.resize(1600, 900)
    win.show()
    qtbot.waitExposed(win)
    win.set_user("admin")
    assert win.board_model, "the seeded workspace's board models are missing"
    titles = list(win.pages)
    switches: dict[str, list[float]] = {t: [] for t in titles}
    listing: list[float] = []
    for _ in range(ROUNDS):
        for title in titles[1:] + titles[:1]:  # from Home, where the window opens, round to Home
            page = win.pages[title]
            watch = Painted(page)
            t0 = perf_counter()
            assert win.navigate(title), title
            while not watch.painted and perf_counter() - t0 < 10:
                QApplication.processEvents()
            switches[title].append(perf_counter() - t0)
            watch.deleteLater()
            if getattr(page, "listing", None) is not None:
                listed(qtbot, page)
                listing.append(perf_counter() - t0)
    print("\nREQ-SET-020 page switches, ms:", {t: [round(s * 1000) for s in v] for t, v in switches.items()})
    print("Logs & Export, records shown after (ms):", [round(s * 1000) for s in listing])
    slow = {t: round(max(v) * 1000) for t, v in switches.items() if max(v) > SWITCH_BUDGET_S}
    assert not slow, f"over the {SWITCH_BUDGET_S * 1000:.0f} ms budget (ms): {slow}"
    assert len(listing) == ROUNDS and len(win.pages["Logs & Export"].rows) > 0


def test_req_set_020_logs_lists_its_records_on_the_pool(
    qtbot: QtBot, ctx: AppContext, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Showing Logs & Export reads its records on the pool thread (at 100,000 records the read on the UI thread held
    the switch for 6.5 s): the page is up before they arrive, and the exports wait for them. Rows that arrive after
    another page is shown, or after Filter listed newer ones, are dropped; Filter itself lists at once."""
    gate, pool_calls = threading.Event(), []

    def inspections(*args: Any, **kwargs: Any) -> list[dict[str, Any]]:
        if threading.current_thread() is threading.main_thread():  # Filter: three records, at once
            return [_record(i) for i in (1, 2, 3)]
        pool_calls.append(args)
        assert gate.wait(30), "the test never let the listing finish"
        return [_record(9)]

    monkeypatch.setattr(ctx, "inspections", inspections)
    win = MainWindow(ctx)  # the Engineer, who may export
    qtbot.addWidget(win)
    logs = win.pages["Logs & Export"]
    assert isinstance(logs, LogsPage)
    assert win.navigate("Logs & Export")  # returns with the read still held at the gate
    qtbot.waitUntil(lambda: len(pool_calls) == 1)
    assert logs.listing is not None and not logs.btn_csv.isEnabled() and not logs.btn_img.isEnabled()
    assert win.navigate("Home")
    gate.set()
    qtbot.waitUntil(lambda: logs.listing is None)
    assert logs.rows == [] and logs.table.rowCount() == 0, "rows filled in under another page"
    gate.clear()
    assert win.navigate("Logs & Export")
    qtbot.waitUntil(lambda: len(pool_calls) == 2)
    dropped = logs.listing
    assert dropped is not None
    logs.refresh()  # Filter, while the listing waits
    assert [r["id"] for r in logs.rows] == [1, 2, 3] and logs.listing is None and logs.btn_csv.isEnabled()
    gate.set()
    qtbot.waitUntil(lambda: dropped.job.done)
    qtbot.wait(50)  # its signals, sent before it was done, delivered
    assert [r["id"] for r in logs.rows] == [1, 2, 3], "an older listing replaced Filter's rows"
    assert win.navigate("Home") and win.navigate("Logs & Export")
    listed(qtbot, logs)
    assert [r["id"] for r in logs.rows] == [9] and logs.table.rowCount() == 1 and logs.btn_csv.isEnabled()
