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
from tests.conftest import PASSPHRASE, handed_over

WRONG = "not the passphrase, but long"
KIM = "a second Admin chose this one"


def _refused(ctx: AppContext, password: str | None = WRONG) -> str:
    with pytest.raises(AoiError) as e:
        ctx.sign_in("engineer", password=password)
    return e.value.code


def test_req_usr_004_five_wrong_passwords_lock_the_account_for_five_minutes(ctx: AppContext) -> None:
    """The 5th wrong password in a row locks it (AOI-USR-006), audited user.lock with its end; while locked even the
    right password is not checked; once the lock ends the right one signs in and the count starts again. A right
    password between wrong ones starts the count again, and a start's refusal is no guess."""
    handed_over(ctx)
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
    assert row["locked_minutes"] == 5 and row["failed_attempts"] == 5
    assert _refused(ctx, PASSPHRASE) == "AOI-USR-006" and ctx.user == "operator"  # on record, no guess counted
    assert ctx.audit_entries(action="user.sign_in_failed")[0]["after"]["locked"] is True
    assert next(u for u in ctx.users() if u["name"] == "engineer")["failed_attempts"] == 5
    ctx.sign_in("operator")  # a lock never stops the Operator view
    ctx.db.execute("UPDATE users SET locked_until='2026-01-01T00:00:00+00:00' WHERE name='engineer'")  # it ended
    ctx.sign_in("engineer", password=PASSPHRASE)
    assert ctx.user == "engineer" and next(u for u in ctx.users() if u["name"] == "engineer")["locked_until"] is None


def test_req_usr_004_the_100th_wrong_password_or_an_unreadable_lock_waits_for_an_admin(ctx: AppContext) -> None:
    """A timed lock does not reset the count, so a guesser gets no endless rounds: the 100th wrong password since the
    last right one locks until an Admin unlocks (AOI-USR-007), and so does a lock time that cannot be read."""
    handed_over(ctx)
    ctx.sign_in("engineer", password=PASSPHRASE)
    ctx.set_user("operator")
    ctx.db.execute("UPDATE users SET failed_attempts=98 WHERE name='engineer'")
    assert [_refused(ctx), _refused(ctx), _refused(ctx, PASSPHRASE)] == ["AOI-USR-004", "AOI-USR-007", "AOI-USR-007"]
    ctx.db.execute("UPDATE users SET locked_until='not a time' WHERE name='engineer'")
    assert _refused(ctx, PASSPHRASE) == "AOI-USR-007"
    ctx.db.execute("UPDATE users SET locked_until='2026-01-01T00:00:00' WHERE name='engineer'")  # no offset: UTC
    ctx.sign_in("engineer", password=PASSPHRASE)
    assert next(u for u in ctx.users() if u["name"] == "engineer")["failed_attempts"] == 0


def test_req_usr_004_wrong_passwords_never_leave_the_station_without_an_admin(ctx: AppContext) -> None:
    """Anyone at Switch User may type 100 wrong passwords for an Admin, which locks them until an Admin unlocks
    (AOI-USR-007). No change then leaves the station with only Admins locked so (AOI-USR-013); and every Admin, the
    one handed over too, has their own recovery code, which signs them in again when no Admin is left to unlock them
    (senior review 2026-11-06, SEC-2)."""
    ctx.set_user("operator")
    ctx.sign_in("admin", password=PASSPHRASE)  # the station's first Admin
    assert ctx.take_recovery_code() is not None
    ctx.add_user("kim", "Admin")
    ctx.sign_in("kim", password=KIM)  # handed over by the first Admin
    code = ctx.take_recovery_code()
    assert code is not None
    ctx.set_user("operator")
    ctx.db.execute("UPDATE users SET failed_attempts=99 WHERE name='admin'")  # 99 guesses typed before
    with pytest.raises(AoiError, match="AOI-USR-007"):
        ctx.sign_in("admin", password=WRONG)
    ctx.sign_in("kim", password=KIM)
    with pytest.raises(AoiError, match="AOI-USR-013"):
        ctx.add_user("kim", "Engineer")  # kim is the one Admin who can sign in
    ctx.set_user("operator")
    ctx.db.execute("UPDATE users SET failed_attempts=99 WHERE name='kim'")
    with pytest.raises(AoiError, match="AOI-USR-007"):
        ctx.sign_in("kim", password=WRONG)
    with pytest.raises(AoiError, match="AOI-USR-007"):
        ctx.sign_in("kim", password=KIM)  # the right password waits for an Admin, and none can sign in
    ctx.recover("kim", code, "kim's new passphrase after the lock")
    assert ctx.user == "kim" and ctx.role == "Admin" and ctx.take_recovery_code() not in (None, code)
    ctx.unlock_user("admin")
    ctx.sign_in("admin", password=PASSPHRASE)


def test_req_usr_004_an_admin_counts_once_they_have_their_recovery_code(ctx: AppContext) -> None:
    """The review's case: an Engineer moved to the Admin role keeps their password, so had no code; the first Admin
    could then step down, and anyone at Switch User could lock the only Admin until an Admin unlocks them, for good.
    Every Admin gets their code at their next sign-in, and counts as an Admin who can sign in only then (AOI-USR-013);
    one under a timed lock counts (senior review 2026-11-06, SEC-2)."""
    handed_over(ctx)
    ctx.set_user("operator")
    ctx.sign_in("admin", password=PASSPHRASE)
    assert ctx.take_recovery_code() is not None
    ctx.add_user("engineer", "Admin")
    with pytest.raises(AoiError, match="AOI-USR-013") as refused:
        ctx.add_user("admin", "Engineer")  # the engineer has no code yet
    assert "have them sign in once" in str(refused.value)
    ctx.sign_in("engineer", password=PASSPHRASE)
    code = ctx.take_recovery_code()
    assert code is not None
    for _ in range(ctx.settings.lock_after):  # a timed lock: still an Admin who can sign in
        with pytest.raises(AoiError, match="AOI-USR-00[46]"):
            ctx.sign_in("engineer", password=WRONG)
    ctx.sign_in("admin", password=PASSPHRASE)
    ctx.add_user("admin", "Engineer")
    ctx.db.execute("UPDATE users SET failed_attempts=99, locked_until=NULL WHERE name='engineer'")  # the lock over
    with pytest.raises(AoiError, match="AOI-USR-007"):
        ctx.sign_in("engineer", password=WRONG)
    ctx.recover("engineer", code, "the engineer's new passphrase")  # the only Admin, back with their own code
    assert ctx.user == "engineer" and ctx.take_recovery_code() not in (None, code)
    ctx.add_user("admin", "Admin")  # moved back: the code went with the role, so none until they sign in
    with pytest.raises(AoiError, match="AOI-USR-013"):
        ctx.add_user("engineer", "Engineer")
    ctx.sign_in("admin", password=PASSPHRASE)
    assert ctx.take_recovery_code() is not None
    ctx.add_user("engineer", "Engineer")


def test_req_usr_004_the_only_admin_locked_while_signed_in_still_manages_other_users(ctx: AppContext) -> None:
    """The review's case: the only Admin, locked until an Admin unlocks them by wrong passwords typed at Switch User
    while they stay signed in, was refused every change to an Engineer or an Operator (AOI-USR-013). Only a change to
    one who is an Admin is checked for Admins: a promotion takes none away, and a reset is judged with the lock it
    clears, so another Admin locked so may be reset to choose a new password (the second review's cases)."""
    handed_over(ctx)
    ctx.set_user("operator")
    ctx.sign_in("admin", password=PASSPHRASE)
    ctx.add_user("kim", "Admin")
    ctx.sign_in("kim", password=KIM)
    assert ctx.take_recovery_code() is not None
    ctx.set_user("operator")
    ctx.db.execute("UPDATE users SET failed_attempts=99 WHERE name='kim'")
    with pytest.raises(AoiError, match="AOI-USR-007"):
        ctx.sign_in("kim", password=WRONG)
    ctx.sign_in("admin", password=PASSPHRASE)
    ctx.db.execute("UPDATE users SET failed_attempts=99 WHERE name='admin'")
    with pytest.raises(AoiError, match="AOI-USR-007"):
        ctx.sign_in("admin", password=WRONG)
    assert ctx.user == "admin"
    ctx.reset_secret("engineer")
    ctx.set_user_enabled("engineer", False)
    ctx.add_user("engineer", "Operator")
    ctx.add_user("engineer", "Admin")
    ctx.reset_secret("kim")
    assert next(u for u in ctx.users() if u["name"] == "kim")["status"] == "setup"


def test_req_usr_004_an_admin_unlocks_and_only_an_admin(ctx: AppContext) -> None:
    handed_over(ctx)
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
    handed_over(ctx)
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
