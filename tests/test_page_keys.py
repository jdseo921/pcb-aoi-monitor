"""REQ-SET-004 and the Engineering standard's "Short paths" and "No dead ends": Ctrl+1 to Ctrl+9 open the sidebar's
pages from anywhere, F1 lists the keys of the page shown, and Home's cards never offer a page the role cannot open."""

from __future__ import annotations

import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QMessageBox
from pytestqt.qtbot import QtBot

from aoi.core.services import AppContext
from aoi.ui.main_window import MainWindow
from tests.test_req_done_in_v01 import _window


def focus(win: MainWindow) -> None:
    """The window active, with the focus in the sidebar, as when a user has clicked into it."""
    QApplication.processEvents()
    win.nav.setFocus()


def test_req_set_004_ctrl_and_a_number_opens_each_page_in_sidebar_order(qtbot: QtBot, trained_ctx: AppContext) -> None:
    """An Engineer presses Ctrl+2 and Ctrl+8 from Home: Inspection, then Logs & Export; the sidebar entry names its key
    in its tooltip. An Operator's Ctrl+4 (Training) changes nothing and the status bar names the roles it needs."""
    win = _window(qtbot, trained_ctx, "Engineer")
    titles = list(win.pages)
    assert win.page_keys == {t: f"Ctrl+{n}" for n, t in enumerate(titles, 1)}
    win.navigate("Home")
    focus(win)  # a key reaches the window's actions from wherever the focus is
    qtbot.keyClick(win.nav, Qt.Key.Key_2, Qt.KeyboardModifier.ControlModifier)
    assert win.stack.currentWidget() is win.pages["Inspection"]
    qtbot.keyClick(win.nav, Qt.Key.Key_8, Qt.KeyboardModifier.ControlModifier)
    assert win.stack.currentWidget() is win.pages[titles[7]] and titles[7] == "Logs & Export"
    assert win._items["Inspection"].toolTip().endswith("Ctrl+2")
    win.set_user("operator")
    win.navigate("Home")
    focus(win)
    qtbot.keyClick(win.nav, Qt.Key.Key_4, Qt.KeyboardModifier.ControlModifier)
    assert win.stack.currentWidget() is win.pages["Home"]
    assert "Training needs the Engineer / Admin role" in win.statusBar().currentMessage()


def test_req_set_004_f1_lists_the_page_keys_and_the_pages_the_role_opens(
    qtbot: QtBot, trained_ctx: AppContext, monkeypatch: pytest.MonkeyPatch
) -> None:
    win = _window(qtbot, trained_ctx, "Operator")
    win.navigate("Inspection")
    focus(win)
    shown: list[str] = []
    monkeypatch.setattr(QMessageBox, "information", staticmethod(lambda _p, _t, text, *a, **k: shown.append(text)))
    qtbot.keyClick(win.nav, Qt.Key.Key_F1)
    (text,) = shown
    lines = text.splitlines()
    assert lines[0] == "On Inspection:"
    assert "F5   Start" in lines and "F8   Next Board" in lines and "Ctrl+O   Load Images…" in lines
    assert "Ctrl+2   Inspection" in lines and "Ctrl+8   Logs & Export" in lines
    assert not any("Training" in line for line in lines)  # an Operator is not offered an Engineer's page


def test_req_set_004_home_offers_no_card_the_role_cannot_open(qtbot: QtBot, trained_ctx: AppContext) -> None:
    """An Operator's Home greys the cards for Engineer pages and says which roles open them; the Inspect and Export
    cards open their pages. An Engineer gets every card's link back."""
    win = _window(qtbot, trained_ctx, "Operator")
    win.navigate("Home")
    home = win.pages["Home"]
    links = {target: go for go, target in home.links}
    assert not links["Training"].isEnabled() and links["Training"].text() == "For Engineer / Admin"
    assert links["Training"].toolTip() == "Training needs the Engineer / Admin role"
    assert not links["Recipe Editor"].isEnabled() and not links["AI Model Test"].isEnabled()
    assert links["Inspection"].isEnabled() and links["Inspection"].text() == "Open Inspection ›"
    assert links["Logs & Export"].isEnabled()
    links["Inspection"].click()
    assert win.stack.currentWidget() is win.pages["Inspection"]
    win.set_user("engineer")
    win.navigate("Home")
    assert all(go.isEnabled() for go, _ in home.links)
    assert links["Training"].text() == "Open Training ›"
