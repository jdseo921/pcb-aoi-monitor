"""The Operator's optional PIN (REQ-USR-003) and the idle end of an Engineer's or Admin's session (REQ-USR-004), as
ADR 0002 decisions 1 and 4 have them."""

from __future__ import annotations

import time
from typing import Any, cast

import pytest
from PySide6.QtCore import Qt
from PySide6.QtGui import QInputMethodEvent, QKeySequence
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QDialog, QLineEdit, QMessageBox
from pytestqt.qtbot import QtBot

from aoi.config import Settings
from aoi.core import passwords
from aoi.core.services import AppContext
from aoi.errors import AoiError
from aoi.ui.main_window import MainWindow
from aoi.ui.sign_in_dialog import SignInDialog
from tests.conftest import PASSPHRASE, handed_over


def test_req_usr_003_a_station_may_ask_operators_for_a_pin(ctx: AppContext) -> None:
    """Off, an Operator picks their name. On, their first sign-in chooses 4 to 6 digits (AOI-USR-008 otherwise),
    audited user.pin_set; then a wrong PIN is refused (AOI-USR-004) and counts toward the lock as a password does. A
    start still signs the Operator in: the Operator view is never held."""
    ctx.set_user("admin")
    ctx.add_user("kim", "Operator")
    ctx.sign_in("kim")
    ctx.settings.operator_pin = True
    ctx.set_user("operator")
    with pytest.raises(AoiError, match="AOI-USR-008"):
        ctx.sign_in("kim", password="12a4")
    ctx.sign_in("kim", password="2468")
    (chose,) = ctx.audit_entries(action="user.pin_set")
    assert chose["after"] == {"user": "kim"} and passwords.verify(ctx.db.user_secret(chose["object_uuid"]), "2468")
    assert ctx.users_with_pins() == {"kim"}
    ctx.set_user("operator")
    with pytest.raises(AoiError, match="AOI-USR-004"):
        ctx.sign_in("kim", password="1357")
    for _ in range(3):
        with pytest.raises(AoiError):
            ctx.sign_in("kim", password="1357")
    with pytest.raises(AoiError, match="AOI-USR-006"):
        ctx.sign_in("kim", password="1357")
    ctx.sign_in("kim", start=True)
    assert ctx.user == "kim"


def test_req_usr_003_the_dialog_asks_an_operator_for_their_pin(qtbot: QtBot, ctx: AppContext) -> None:
    ctx.ensure_board_model("B")
    ctx.settings.operator_pin = True
    win = MainWindow(ctx)
    qtbot.addWidget(win)
    box = SignInDialog(win)
    box.show()
    box.user.setCurrentIndex(0)  # operator, no PIN yet
    assert box.password.isVisible() and box.again.isVisible() and box.password.placeholderText() == "New PIN"
    box.password.setText("2468")
    box.again.setText("2468")
    box.sign_in()
    assert box.signed_in == "operator" and ctx.users_with_pins() == {"operator"}
    again = SignInDialog(win)
    again.show()
    again.user.setCurrentIndex(0)
    assert again.password.isVisible() and not again.again.isVisible() and again.password.placeholderText() == "PIN"
    win.close()


def test_req_usr_004_an_idle_engineer_goes_back_to_the_shifts_operator(qtbot: QtBot, ctx: AppContext) -> None:
    """After idle_minutes without input an Engineer's session ends, back to the Operator signed in last, audited
    user.idle_end, a dialog left open closed first; input in time, or an Operator, keep it. A board being inspected no
    longer does: it is recorded under who started it (senior review 2026-11-06, SEC-4; `tests/test_acting_user.py`)."""
    ctx.ensure_board_model("B")
    ctx.set_user("admin")
    ctx.add_user("kim", "Operator")
    win = MainWindow(ctx)
    qtbot.addWidget(win)
    handed_over(ctx)
    ctx.sign_in("kim")
    ctx.sign_in("engineer", password=PASSPHRASE)
    win.set_user("engineer")
    win.input.last = time.monotonic() - 14 * 60
    assert not win.check_idle() and ctx.user == "engineer"
    QTest.keyClick(win, Qt.Key.Key_Shift)  # input: the idle time starts again
    assert time.monotonic() - win.input.last < 5
    win.input.last = time.monotonic() - 15 * 60
    box = QDialog(win)
    box.open()  # a dialog left open is closed first, as Cancel would
    assert QApplication.activeModalWidget() is box
    assert (
        win.check_idle() and not box.isVisible() and ctx.user == "kim" and win.user_label.text() == "kim  ·  Operator"
    )
    (ended,) = ctx.audit_entries(action="user.idle_end")
    assert ended["before"] == {"user": "engineer", "role": "Engineer"} and ended["after"]["user"] == "kim"
    assert "ended after 15 minutes without input" in win.statusBar().currentMessage()
    assert not win.check_idle()  # an Operator's view never ends
    second = MainWindow(ctx)
    qtbot.addWidget(second)
    watches = QApplication.instance().findChildren(type(win.input))  # one filter for the app, never one per window
    assert watches == [win.input] and second.input is win.input
    win.close()


def test_req_usr_004_a_key_that_fires_a_shortcut_starts_the_idle_time_again(
    qtbot: QtBot, ctx: AppContext, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A key that fires a shortcut (the window's F1, and a page's own: 3D Profile's Esc) reaches no widget as a key
    press, only its action: it is input all the same, so an Engineer working by keyboard keeps the session (senior
    review 2026-11-06, UI-2). So is Hangul typed through the input method, and a key no shortcut takes, as before.
    An action triggered from code, a click from code, time passing and a mouse moved without a press are no input:
    the session then ends as ever."""
    ctx.ensure_board_model("B")
    win = MainWindow(ctx)
    qtbot.addWidget(win)
    handed_over(ctx)
    ctx.sign_in("engineer", password=PASSPHRASE)
    win.set_user("engineer")
    win.show()
    win.activateWindow()  # a window's keys need it active, which the offscreen platform does not make it by itself
    qtbot.waitUntil(lambda: QApplication.activeWindow() is win)
    listed: list[str] = []
    monkeypatch.setattr(QMessageBox, "information", staticmethod(lambda _p, _t, text, *a, **k: listed.append(text)))
    for page in ("Home", "Inspection"):
        win.navigate(page)
        win.nav.setFocus()
        win.input.last = time.monotonic() - 15 * 60
        qtbot.keyClick(win.nav, Qt.Key.Key_F1)
        assert len(listed) == 1 and listed.pop().startswith(f"On {page}:")  # the shortcut fired, as its action
        assert time.monotonic() - win.input.last < 5
        assert not win.check_idle() and ctx.user == "engineer"
    profile = win.pages["3D Profile"]
    win.navigate("3D Profile")
    profile.setFocus()
    win.input.last = time.monotonic() - 15 * 60
    qtbot.keyClick(profile, Qt.Key.Key_Escape)  # the page's own action, Back to Home
    assert win.stack.currentWidget() is win.pages["Home"] and time.monotonic() - win.input.last < 5
    win.input.last = time.monotonic() - 15 * 60
    qtbot.keyClick(win.nav, Qt.Key.Key_Down)  # no shortcut: a key press, as before
    assert time.monotonic() - win.input.last < 5
    edit = QLineEdit(win)
    hangul = QInputMethodEvent("", [])
    hangul.setCommitString("한글")
    win.input.last = time.monotonic() - 15 * 60
    QApplication.sendEvent(edit, hangul)  # typed through the input method, as a Korean keyboard types
    assert edit.text() == "한글" and time.monotonic() - win.input.last < 5
    win.input.last = time.monotonic() - 15 * 60
    keys = next(a for a in win.actions() if a.shortcut() == QKeySequence(Qt.Key.Key_F1))
    keys.trigger()  # from code: no key was pressed
    cast(Any, win.pages["Home"]).btn_guide.click()
    QTest.mouseMove(win.nav)
    qtbot.wait(1100)
    assert len(listed) == 1 and win.check_idle() and ctx.role == "Operator"
    win.close()


def test_req_usr_004_an_idle_end_signs_in_only_an_operator(ctx: AppContext) -> None:
    """The shift's operator, else the first Operator; with no Operator at all the session stays, never an Admin."""
    ctx.set_user("engineer")
    assert ctx.end_idle() == "operator" and ctx.role == "Operator"  # no Operator signed in yet: the first
    ctx.db.execute("UPDATE users SET role='Engineer' WHERE name='operator'")
    ctx.set_user("engineer")
    assert ctx.end_idle() is None and ctx.user == "engineer"


def test_req_usr_004_the_idle_time_keeps_to_its_range() -> None:
    Settings.check("idle_minutes", 1)
    Settings.check("idle_minutes", 120)
    for bad in (0, 121):
        with pytest.raises(AoiError, match="AOI-SET-008"):
            Settings.check("idle_minutes", bad)
