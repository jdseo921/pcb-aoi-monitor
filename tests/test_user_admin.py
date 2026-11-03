"""User administration (REQ-USR-006; ADR 0002, decision 7): an Admin disables and enables users and resets a password or
PIN, each audited; a disabled user never signs in and keeps their name on past records; and an Engineer's or Admin's
first password is chosen only with an Admin signed in, or while no Admin has one; and no change leaves the station
with no Admin who can sign in, or no Operator for a start."""

from __future__ import annotations

import pytest

from aoi.core import passwords
from aoi.core.services import AppContext
from aoi.errors import AoiError
from tests.conftest import PASSPHRASE


def test_req_usr_006_a_first_password_is_chosen_only_with_an_admin_signed_in(ctx: AppContext) -> None:
    """While no Admin has a password anyone may choose one (a first run); once one has, an Engineer in set-up chooses
    theirs only while that Admin is signed in (AOI-USR-009 otherwise), as an Admin hands the account over."""
    ctx.set_user("operator")
    ctx.sign_in("admin", password=PASSPHRASE)  # no Admin had a password: the station's first
    ctx.sign_in("operator")
    with pytest.raises(AoiError, match="AOI-USR-009"):
        ctx.sign_in("engineer", password=PASSPHRASE)
    ctx.sign_in("admin", password=PASSPHRASE)
    ctx.sign_in("engineer", password=PASSPHRASE)  # handed over by the Admin signed in
    assert ctx.user == "engineer"


def test_req_usr_006_a_disabled_user_never_signs_in_and_the_last_admin_stays(ctx: AppContext) -> None:
    ctx.set_user("admin")
    ctx.set_user_enabled("engineer", False)
    with pytest.raises(AoiError, match="AOI-USR-010"):
        ctx.sign_in("engineer", password=PASSPHRASE)
    assert "engineer" not in {ctx.start_user(), ctx.start_user(setting_up=True)}
    with pytest.raises(AoiError, match="AOI-USR-013"):
        ctx.set_user_enabled("admin", False)  # the last Admin who can sign in
    ctx.add_user("kim", "Admin")
    with pytest.raises(AoiError, match="AOI-USR-011"):
        ctx.set_user_enabled("admin", False)  # not their own, signed in
    ctx.set_user_enabled("engineer", True)
    assert next(u for u in ctx.users() if u["name"] == "engineer")["status"] == "setup"  # no password: set-up again
    changes = [
        (e["action"], e["after"]["status"])
        for e in ctx.audit_entries()
        if e["action"] in ("user.disable", "user.enable")
    ]
    assert changes == [("user.enable", "setup"), ("user.disable", "disabled")]


def test_req_usr_006_an_admin_resets_a_password_or_pin(ctx: AppContext) -> None:
    ctx.sign_in("admin", password=PASSPHRASE)
    ctx.sign_in("engineer", password=PASSPHRASE)
    ctx.sign_in("admin", password=PASSPHRASE)
    uuid = str(ctx.db.user_uuid("engineer"))
    ctx.db.execute("UPDATE users SET failed_attempts=7, locked_until='2099-01-01T00:00:00+00:00' WHERE uuid=?", (uuid,))
    ctx.reset_secret("engineer")
    row = next(u for u in ctx.users() if u["uuid"] == uuid)
    assert (row["status"], row["failed_attempts"], row["locked_until"]) == ("setup", 0, None)
    assert ctx.db.user_secret(uuid) is None
    (reset,) = ctx.audit_entries(action="user.reset")
    assert reset["after"] == {"user": "engineer", "status": "setup"} and "$argon2" not in str(reset)
    ctx.sign_in("engineer", password="a brand new passphrase")  # with the Admin signed in
    assert passwords.verify(ctx.db.user_secret(uuid), "a brand new passphrase")


def test_req_usr_006_a_set_up_admin_neither_starts_nor_manages_once_an_admin_has_a_password(ctx: AppContext) -> None:
    """The review's take-over: an Admin added in set-up is never signed in at a start once an Admin has a password, and
    one signed in without a password manages no user (AOI-USR-012); no Admin resets their own account (AOI-USR-011)."""
    ctx.sign_in("admin", password=PASSPHRASE)
    ctx.add_user("kim", "Admin")
    assert ctx.startable() == {"operator"}
    assert ctx.start_user(setting_up=True) == "operator"
    with pytest.raises(AoiError, match="AOI-USR-011"):
        ctx.reset_secret("admin")
    ctx.set_user("kim")  # as a start once could
    for write in (
        lambda: ctx.reset_secret("admin"),
        lambda: ctx.set_user_enabled("admin", False),
        lambda: ctx.unlock_user("admin"),
        lambda: ctx.add_user("admin", "Engineer"),
    ):
        with pytest.raises(AoiError, match="AOI-USR-012"):
            write()
    assert next(u for u in ctx.users() if u["name"] == "admin")["status"] == "active"


def test_req_usr_006_the_station_keeps_an_admin_and_an_operator(ctx: AppContext) -> None:
    """No disable or role change leaves no Admin with a password (AOI-USR-013) or no enabled Operator (AOI-USR-014),
    so the app always opens; an Operator enabled again is active, and one whose PIN is reset chooses a new one."""
    ctx.sign_in("admin", password=PASSPHRASE)
    ctx.add_user("kim", "Admin")
    ctx.set_user_enabled("kim", False)
    with pytest.raises(AoiError, match="AOI-USR-013"):
        ctx.add_user("admin", "Engineer")  # kim, disabled, cannot sign in
    with pytest.raises(AoiError, match="AOI-USR-014"):
        ctx.set_user_enabled("operator", False)
    with pytest.raises(AoiError, match="AOI-USR-014"):
        ctx.add_user("operator", "Engineer")
    ctx.add_user("lee", "Operator")
    ctx.set_user_enabled("operator", False)
    ctx.set_user_enabled("operator", True)
    assert next(u for u in ctx.users() if u["name"] == "operator")["status"] == "active"
    ctx.settings.operator_pin = True
    ctx.sign_in("lee", password="1234")  # the first PIN
    ctx.sign_in("admin", password=PASSPHRASE)
    ctx.reset_secret("lee")
    ctx.sign_in("lee", password="5678")  # a new one, chosen at the next sign-in
    assert passwords.verify(ctx.db.user_secret(str(ctx.db.user_uuid("lee"))), "5678")
