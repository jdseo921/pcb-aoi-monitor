"""A screenshot waits for the page to finish laying out, so a page is drawn alike however busy the machine that grabs
it (REQ-SET-004). In a module of its own, so its workspace's window shows Logs & Export for the first time, with its
name lists empty until then, as `render_pages` shows it."""

from __future__ import annotations

import time
from pathlib import Path
from typing import cast
from unittest import mock

from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from aoi.core.services import AppContext
from aoi.ui.main_window import MainWindow
from aoi.ui.pages.logs import LogsPage
from tools import render_screens


def test_req_set_004_a_screenshot_waits_for_the_page_to_finish_laying_out(
    screens: tuple[AppContext, Path], qapp: QApplication
) -> None:
    """Shown the first time, Logs fills its name lists; Qt resizes each to its names 20 ms later, and the filter row
    lays itself out over the passes of the event loop after. On a busy machine the resize came first, and a screenshot
    one pass after `prepare` showed the Operator list 7 px wider than its place, its arrow cut off (#396's CI). Here the
    machine is busy for 50 ms; `settle` then handles events until each list is in its place, so laying the page out
    again moves nothing. With one pass in place of `settle`, the Operator list ends at 206 in its 200 px place."""
    ctx, dataset = screens
    with render_screens.pinned_rendering(qapp, render_screens.TEST_FONT):
        win = MainWindow(ctx)
        win.resize(1920, 1080)
        win.show()
        QTest.qWaitForWindowExposed(win)
        try:
            win.set_user("operator")
            for title, page in win.pages.items():  # the Operator's pages before Logs, grabbed as render_pages did
                if title == "Logs & Export":
                    break
                if "Operator" in page.roles:
                    assert win.navigate(title), title
                    render_screens.prepare(win, title, dataset)
                    QApplication.processEvents()
                    win.grab()
            logs = cast(LogsPage, win.pages["Logs & Export"])
            lists = (logs.model, logs.operator)
            assert logs.operator.count() == 0  # laid out with its lists empty: never shown yet
            assert win.navigate("Logs & Export")
            render_screens.prepare(win, "Logs & Export", dataset)
            time.sleep(0.05)  # busy past Qt's resize of the lists, with the filter row not laid out yet
            render_screens.settle()
            placed = [names.geometry() for names in lists]
            for names in lists:
                place = names.parentWidget()
                assert place is not None and names.geometry().right() < place.width(), "cut off by its place"
            logs.layout().invalidate()
            logs.layout().activate()
            assert [names.geometry() for names in lists] == placed
        finally:
            with mock.patch.object(ctx, "close"):  # the fixture closes the workspace
                win.close()
