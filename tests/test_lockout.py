"""Lockout (REQ-USR-004; ADR 0002, decision 4): wrong passwords in a row lock an Engineer's or Admin's account for a
while, audited, and an Admin may unlock it sooner on Settings; a start is never a guess."""

from __future__ import annotations

from typing import Any, cast

import pytest
from PySide6.QtWidgets import QInputDialog
from pytestqt.qtbot import QtBot

from aoi.config import Settings
from aoi.core.services import AppContext
from aoi.errors import AoiError
from aoi.ui.main_window import MainWindow
from tests.conftest import PASSPHRASE

WRONG = "not the passphrase, but long"


def _refused(ctx: AppContext, password: str | None = WRONG) -> str:
    with pytest.raises(AoiError) as e:
        ctx.sign_in("engineer", password=password)
    return e.value.code


def test_req_usr_004_five_wrong_passwords_lock_the_account_for_five_minutes(ctx: AppContext) -> None:
    """The 5th wrong password in a row locks it (AOI-USR-006), audited user.lock with its end; while locked even the
    right password is not checked; once the lock ends the right one signs in and the count starts again. A right
    password between wrong ones starts the count again, and a start's refusal is no guess."""
    ctx.sign_in("engineer", password=PASSPHRASE)
    ctx.set_user("operator")
    assert [_refused(ctx) for _ in range(4)] == ["AOI-USR-004"] * 4
    ctx.sign_in("engineer", password=PASSPHRASE)
    ctx.set_user("operator")
    for _ in range(3):
        with pytest.raises(AoiError):
            ctx.sign_in("engineer", start=True)
    assert [_refused(ctx) for _ in range(5)] == ["AOI-USR-004"] * 4 + ["AOI-USR-006"]
    (lock,) = ctx.audit_entries(action="user.lock")
    assert lock["after"]["user"] == "engineer" and lock["object_uuid"] == ctx.db.user_uuid("engineer")
    row = next(u for u in ctx.users() if u["name"] == "engineer")
    assert row["locked_minutes"] == 5 and row["failed_attempts"] == 0
    assert _refused(ctx, PASSPHRASE) == "AOI-USR-006" and ctx.user == "operator"
    ctx.db.execute("UPDATE users SET locked_until='2026-01-01T00:00:00+00:00' WHERE name='engineer'")  # it ended
    ctx.sign_in("engineer", password=PASSPHRASE)
    assert ctx.user == "engineer" and next(u for u in ctx.users() if u["name"] == "engineer")["locked_until"] is None


def test_req_usr_004_an_admin_unlocks_and_only_an_admin(ctx: AppContext) -> None:
    ctx.sign_in("engineer", password=PASSPHRASE)
    ctx.set_user("operator")
    for _ in range(5):
        _refused(ctx)
    with pytest.raises(AoiError, match="AOI-USR-001"):
        ctx.unlock_user("engineer")
    ctx.set_user("admin")
    ctx.unlock_user("engineer")
    (entry,) = ctx.audit_entries(action="user.unlock")
    assert entry["before"]["locked_until"] is not None and entry["after"] == {"user": "engineer"}
    ctx.sign_in("engineer", password=PASSPHRASE)
    assert ctx.user == "engineer"


def test_req_usr_004_the_lock_settings_keep_to_their_ranges() -> None:
    for name, good, bad in (("lock_after", (3, 20), (2, 21)), ("lock_minutes", (1, 60), (0, 61))):
        for value in good:
            Settings.check(name, value)
        for value in bad:
            with pytest.raises(AoiError, match="AOI-SET-008"):
                Settings.check(name, value)


def test_req_usr_004_settings_shows_the_lock_and_unlocks_it(
    qtbot: QtBot, ctx: AppContext, monkeypatch: pytest.MonkeyPatch
) -> None:
    ctx.ensure_board_model("B")
    ctx.sign_in("engineer", password=PASSPHRASE)
    ctx.set_user("operator")
    for _ in range(5):
        _refused(ctx)
    win = MainWindow(ctx)
    qtbot.addWidget(win)
    win.set_user("admin")  # in set-up: no password to type here
    page = cast(Any, win.pages["Settings"])
    assert win.navigate("Settings")
    cells = [[page.users.item(r, c).text() for c in range(3)] for r in range(page.users.rowCount())]
    assert cells == [
        ["operator", "Operator", "Active"],
        ["engineer", "Engineer", "Locked, 5 min"],
        ["admin", "Admin", "No password yet"],
    ]
    assert page.btn_unlock.isEnabled()
    pick = staticmethod(lambda _p, _t, _l, items, *_a: (items[0], True))
    monkeypatch.setattr(QInputDialog, "getItem", pick)
    page.btn_unlock.click()
    assert page.users.item(1, 2).text() == "Active" and not page.btn_unlock.isEnabled()
    win.close()
