"""REQ-SET-020 (stage S55): pages open within 300 ms on a workspace with 100,000 inspection records. Logs & Export
reads its records on the pool thread once shown, so the switch to it never waits for them."""

from __future__ import annotations

import threading
from typing import Any

import pytest
from pytestqt.qtbot import QtBot

from aoi.core.services import AppContext
from aoi.ui.main_window import MainWindow
from aoi.ui.pages.logs import LogsPage
from tests.conftest import listed
from tests.test_ui_offscreen import _record


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
