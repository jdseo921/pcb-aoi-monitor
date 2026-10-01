"""The Qt shell opens offscreen (stage S05): page tests can run in CI on Windows and Linux.

pytest-qt supplies `qtbot`; conftest.py sets QT_QPA_PLATFORM=offscreen before Qt is imported.
"""

from __future__ import annotations

from pytestqt.qtbot import QtBot

from aoi.core.services import AppContext
from aoi.ui.main_window import MainWindow

PAGES = [
    "Home",
    "Inspection",
    "Compare",
    "Training",
    "AI Model Test",
    "Recipe Editor",
    "3D Profile",
    "Logs & Export",
    "Settings",
]


def test_main_window_shows_every_page_offscreen(qtbot: QtBot, ctx: AppContext) -> None:
    win = MainWindow(ctx)
    qtbot.addWidget(win)
    win.show()
    assert list(win.pages) == PAGES
    assert win.ctx.role == "Admin", "an empty workspace opens as Admin so the first user can set up"
    for title in PAGES:
        win.navigate(title)
        assert win.stack.currentWidget() is win.pages[title], title


def test_operator_cannot_open_an_admin_page(qtbot: QtBot, ctx: AppContext) -> None:
    win = MainWindow(ctx)
    qtbot.addWidget(win)
    win.set_role("Operator", "operator")
    win.navigate("Settings")
    assert win.stack.currentWidget() is win.pages["Home"]
    assert win.statusBar().currentMessage() == "Settings needs the Admin role"
