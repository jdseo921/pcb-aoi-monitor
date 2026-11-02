"""The Operator's optional PIN (REQ-USR-003) and the idle end of an Engineer's or Admin's session (REQ-USR-004), as
ADR 0002 decisions 1 and 4 have them."""

from __future__ import annotations

import time
from typing import Any, cast

import pytest
from pytestqt.qtbot import QtBot

from aoi.config import Settings
from aoi.core import passwords
from aoi.core.services import AppContext
from aoi.errors import AoiError
from aoi.ui.main_window import MainWindow
from aoi.ui.sign_in_dialog import SignInDialog
from tests.conftest import PASSPHRASE


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


def test_req_usr_004_an_idle_engineer_goes_back_to_the_shifts_operator_never_mid_inspection(
    qtbot: QtBot, ctx: AppContext
) -> None:
    """After idle_minutes without input an Engineer's session ends, back to the Operator signed in last, audited
    user.idle_end; input in time, an Operator, or a run under way on Inspection keep the session."""
    ctx.ensure_board_model("B")
    ctx.set_user("admin")
    ctx.add_user("kim", "Operator")
    win = MainWindow(ctx)
    qtbot.addWidget(win)
    ctx.sign_in("kim")
    ctx.sign_in("engineer", password=PASSPHRASE)
    win.set_user("engineer")
    win.input.last = time.monotonic() - 14 * 60
    assert not win.check_idle() and ctx.user == "engineer"
    win.input.last = time.monotonic() - 15 * 60
    inspection = cast(Any, win.pages["Inspection"])
    inspection.running = True
    assert not win.check_idle() and ctx.user == "engineer"
    inspection.running = False
    assert win.check_idle() and ctx.user == "kim" and win.user_label.text() == "kim  ·  Operator"
    (ended,) = ctx.audit_entries(action="user.idle_end")
    assert ended["before"] == {"user": "engineer", "role": "Engineer"} and ended["after"]["user"] == "kim"
    assert "ended after 15 minutes without input" in win.statusBar().currentMessage()
    assert not win.check_idle()  # an Operator's view never ends
    win.close()


def test_req_usr_004_the_idle_time_keeps_to_its_range() -> None:
    Settings.check("idle_minutes", 1)
    Settings.check("idle_minutes", 120)
    for bad in (0, 121):
        with pytest.raises(AoiError, match="AOI-SET-008"):
            Settings.check("idle_minutes", bad)
