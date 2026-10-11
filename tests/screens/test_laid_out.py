"""A list whose size Qt adjusts to its contents keeps the width its layout gives it, so a page is drawn alike however
soon after it is shown it is grabbed (REQ-SET-004)."""

from __future__ import annotations

from pathlib import Path
from typing import cast

from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from aoi.core.services import AppContext
from aoi.ui.main_window import MainWindow
from aoi.ui.pages.logs import LogsPage
from tools import render_screens


def test_req_set_004_logs_name_filters_keep_their_place_when_qt_resizes_them(
    screens: tuple[AppContext, Path], qapp: QApplication
) -> None:
    """Logs fills its Board model and Operator lists each time it is shown, and 20 ms later Qt resizes each list to its
    size hint (QWidget.adjustSize), outside the layout. The Board model list was then drawn at 80 px in its 109 px place
    until the page was laid out again, so logs-export-admin.png showed either width and failed now and then (#386's
    CI). That resize now keeps the width the layout gave."""
    ctx, dataset = screens
    with render_screens.pinned_rendering(qapp, render_screens.TEST_FONT):
        win = MainWindow(ctx)
        win.resize(1920, 1080)
        win.show()
        try:
            win.set_user("admin")
            assert win.navigate("Logs & Export")
            render_screens.prepare(win, "Logs & Export", dataset)
            QTest.qWait(100)
            page = cast(LogsPage, win.pages["Logs & Export"])
            for names in (page.model, page.operator):
                page.layout().invalidate()
                page.layout().activate()  # the place the layout gives the list
                placed = names.geometry()
                names.adjustSize()  # what Qt does 20 ms after the list's names change
                assert names.geometry() == placed
        finally:
            win.close()
