"""Accounts with passwords (REQ-USR-002, REQ-USR-007; ADR 0002, ADR 0024 D3): Argon2id hashes of NFKC text, the rules
for a new password and a PIN, the migration that puts the seeded Engineer and Admin in set-up, their first sign-in
choosing a password, a wrong one refused and audited, a start that never signs in a passworded account, the sign-in
dialog, and no password or hash in the logs, the audit or the support bundle."""

from __future__ import annotations

import json
import sqlite3
import unicodedata
import zipfile
from pathlib import Path

import pytest
from argon2 import PasswordHasher
from pytestqt.qtbot import QtBot

from aoi.config import APP_NAME
from aoi.core import passwords
from aoi.core.services import AppContext
from aoi.data.db import Database
from aoi.errors import AoiError
from aoi.ui.main_window import MainWindow
from aoi.ui.sign_in_dialog import SignInDialog
from tests.conftest import PASSPHRASE

KOREAN = "부산 바다 위를 나는 일곱 마리 올빼미"  # 21 characters, typed composed (NFC)


def test_req_usr_002_a_secret_is_an_argon2id_hash_of_its_nfkc_text() -> None:
    """The same Korean passphrase typed as composed or decomposed jamo is one secret; the hash is Argon2id with its
    parameters in the string, never the text; one made with weaker parameters is stale."""
    stored = passwords.hash_secret(KOREAN)
    assert stored.startswith("$argon2id$v=19$m=65536,t=3,p=4$") and KOREAN not in stored
    assert passwords.verify(stored, unicodedata.normalize("NFD", KOREAN))
    assert not passwords.verify(stored, KOREAN[:-1]) and not passwords.verify(None, KOREAN)
    assert not passwords.verify("not a hash", KOREAN) and not passwords.stale(stored) and passwords.stale("not a hash")
    weak = PasswordHasher(time_cost=1, memory_cost=8192, parallelism=1).hash(KOREAN)
    assert passwords.verify(weak, KOREAN) and passwords.stale(weak)
    assert passwords.hash_secret(KOREAN) != stored  # a new salt each time


def test_req_usr_002_a_new_password_is_15_to_64_characters_and_no_name() -> None:
    names = ["engineer", "Hanwha Precision"]
    assert passwords.refusal("seven tired owls over Busan", names) is None and passwords.refusal(KOREAN, names) is None
    assert passwords.refusal("x" * 14, names) == passwords.TOO_SHORT.fill(length=15)
    assert passwords.refusal("x" * 65, names) == passwords.TOO_LONG.fill(length=64)
    assert passwords.refusal("hanwha precision", names) == passwords.A_NAME
    assert passwords.refusal(APP_NAME.upper(), []) in (passwords.A_NAME, passwords.TOO_SHORT.fill(length=15))
    assert passwords.refusal("a" * 15, names) is None  # no composition rule (NIST SP 800-63B-4)
    assert [passwords.pin_refusal(p) for p in ("1234", "123456")] == [None, None]
    assert {passwords.pin_refusal(p) for p in ("123", "1234567", "12a4", "١٢٣٤")} == {passwords.NOT_A_PIN}


def test_req_usr_002_the_migration_puts_the_seeded_engineer_and_admin_in_set_up(tmp_path: Path) -> None:
    """Migration 0029 on a v0.3 users table: the Engineer and Admin wait in set-up for a password, the Operator is
    active, and no one has a hash; users() never returns the hash column."""
    db = sqlite3.connect(tmp_path / "old.sqlite")
    db.execute("CREATE TABLE users(id INTEGER PRIMARY KEY, uuid TEXT, name TEXT UNIQUE, role TEXT)")
    db.executemany(
        "INSERT INTO users(uuid, name, role) VALUES(?,?,?)",
        [("u1", "operator", "Operator"), ("u2", "engineer", "Engineer"), ("u3", "admin", "Admin")],
    )
    migration = Path(__file__).parents[1] / "aoi" / "data" / "migrations" / "0029_user_secrets.sql"
    db.executescript(migration.read_text(encoding="utf-8"))
    got = db.execute("SELECT name, status, secret_hash, failed_attempts, locked_until FROM users ORDER BY id")
    assert got.fetchall() == [
        ("operator", "active", None, 0, None),
        ("engineer", "setup", None, 0, None),
        ("admin", "setup", None, 0, None),
    ]
    db.close()


def test_req_usr_007_users_never_carry_the_hash(tmp_path: Path) -> None:
    """The users the database lists hold UUID, name, role, status, failed attempts and lock time, never the hash, which
    only user_secret reads; a hash set makes a set-up Engineer active, and a move to Operator and back drops it."""
    db = Database(tmp_path / "aoi.sqlite")
    try:
        assert [(u["name"], u["status"]) for u in db.users()] == [
            ("operator", "active"),
            ("engineer", "setup"),
            ("admin", "setup"),
        ]
        assert all(
            set(u) == {"id", "uuid", "name", "role", "status", "failed_attempts", "locked_until"} for u in db.users()
        )
        uuid = str(db.user_uuid("engineer"))
        db.set_user_secret(uuid, passwords.hash_secret(KOREAN))
        assert passwords.verify(db.user_secret(uuid), KOREAN)
        assert next(u for u in db.users() if u["name"] == "engineer")["status"] == "active"
        db.add_user("engineer", "Operator")
        db.add_user("engineer", "Engineer")
        assert db.user_secret(uuid) is None
        assert next(u for u in db.users() if u["name"] == "engineer")["status"] == "setup"
    finally:
        db.close()


def test_req_usr_007_a_hash_set_or_dropped_moves_the_status(tmp_path: Path) -> None:
    """A hash set clears failed attempts and the lock; a hash dropped (a reset) puts an Engineer back in set-up, never
    active with no password; a disabled user stays disabled either way."""
    db = Database(tmp_path / "aoi.sqlite")
    try:
        uuid = str(db.user_uuid("admin"))
        db.execute("UPDATE users SET failed_attempts=3, locked_until='2026-11-02T10:00:00+00:00' WHERE uuid=?", (uuid,))
        db.set_user_secret(uuid, passwords.hash_secret(KOREAN))
        row = next(u for u in db.users() if u["uuid"] == uuid)
        assert (row["status"], row["failed_attempts"], row["locked_until"]) == ("active", 0, None)
        db.set_user_secret(uuid, None)
        assert next(u for u in db.users() if u["uuid"] == uuid)["status"] == "setup"
        db.execute("UPDATE users SET status='disabled' WHERE uuid=?", (uuid,))
        db.set_user_secret(uuid, passwords.hash_secret(KOREAN))
        assert next(u for u in db.users() if u["uuid"] == uuid)["status"] == "disabled"
    finally:
        db.close()


def test_req_usr_006_a_role_change_that_drops_the_password_says_so(ctx: AppContext) -> None:
    """user.change records the status before and after: a move to Operator and back starts set-up again."""
    uuid = str(ctx.db.user_uuid("engineer"))
    ctx.db.set_user_secret(uuid, passwords.hash_secret(KOREAN))
    ctx.set_user("admin")
    ctx.add_user("engineer", "Operator")
    ctx.add_user("engineer", "Engineer")
    changes = [(e["before"], e["after"]) for e in ctx.audit_entries(action="user.change")]  # newest first
    assert changes == [
        ({"role": "Operator", "status": "active"}, {"name": "engineer", "role": "Engineer", "status": "setup"}),
        ({"role": "Engineer", "status": "active"}, {"name": "engineer", "role": "Operator", "status": "active"}),
    ]
    assert ctx.db.user_secret(uuid) is None


def test_req_usr_002_a_first_sign_in_chooses_the_password_and_later_ones_need_it(ctx: AppContext) -> None:
    """In set-up, a password that breaks a rule is refused (AOI-USR-005) and nothing is stored; one that keeps them is
    hashed and audited as user.password_set, naming the person and not the secret. After, a missing or wrong password
    is refused (AOI-USR-004) and audited as user.sign_in_failed; the right one signs them in."""
    uuid = ctx.db.user_uuid("engineer")
    assert uuid is not None
    ctx.set_user("operator")
    with pytest.raises(AoiError) as refused:
        ctx.sign_in("engineer", password="short")
    assert refused.value.code == "AOI-USR-005" and ctx.db.user_secret(uuid) is None and ctx.user == "operator"
    ctx.sign_in("engineer", password=PASSPHRASE)
    assert ctx.user == "engineer" and passwords.verify(ctx.db.user_secret(uuid), PASSPHRASE)
    (chose,) = ctx.audit_entries(action="user.password_set")
    assert (chose["object_uuid"], chose["after"]) == (uuid, {"user": "engineer"})
    ctx.sign_in("operator")
    for wrong in (None, "seven tired owls over Seoul"):
        with pytest.raises(AoiError) as refused:
            ctx.sign_in("engineer", password=wrong)
        assert refused.value.code == "AOI-USR-004" and ctx.user == "operator"
    failed = ctx.audit_entries(action="user.sign_in_failed")
    assert [(e["object_uuid"], e["after"]) for e in failed] == [(uuid, {"user": "engineer", "start": False})] * 2
    ctx.sign_in("engineer", password=PASSPHRASE)
    assert ctx.user == "engineer"


def test_req_usr_002_a_stale_hash_is_made_again_and_no_start_signs_them_in(ctx: AppContext) -> None:
    uuid = str(ctx.db.user_uuid("admin"))
    ctx.db.set_user_secret(uuid, PasswordHasher(time_cost=1, memory_cost=8192, parallelism=1).hash(PASSPHRASE))
    ctx.sign_in("admin", password=PASSPHRASE)
    stored = ctx.db.user_secret(uuid)
    assert stored is not None and not passwords.stale(stored) and passwords.verify(stored, PASSPHRASE)
    assert ctx.start_user(setting_up=True) == "operator"  # not the first Admin: they have a password
    with pytest.raises(AoiError, match="AOI-USR-004"):
        ctx.sign_in("admin", start=True)


def test_req_usr_002_the_dialog_asks_each_role_for_what_it_needs(
    qtbot: QtBot, ctx: AppContext, dialogs: list[tuple[str, str]]
) -> None:
    """An Operator: no field. An Engineer in set-up: the password twice, Sign In only once they agree. With a password:
    one field; a wrong one shows AOI-USR-004, keeps the dialog open and clears what was typed."""
    ctx.ensure_board_model("B")
    win = MainWindow(ctx)
    qtbot.addWidget(win)
    box = SignInDialog(win)
    qtbot.addWidget(box)
    box.show()

    def pick(name: str) -> None:
        box.user.setCurrentIndex(next(i for i, u in enumerate(box.users) if u["name"] == name))

    pick("operator")
    assert not box.password.isVisible() and not box.again.isVisible() and box.btn_sign_in.isEnabled()
    pick("engineer")
    assert box.password.isVisible() and box.again.isVisible() and not box.btn_sign_in.isEnabled()
    box.password.setText(PASSPHRASE)
    box.again.setText(PASSPHRASE + " ")
    assert not box.btn_sign_in.isEnabled()
    box.again.setText(PASSPHRASE)
    assert box.btn_sign_in.isEnabled()
    box.sign_in()
    assert box.signed_in == "engineer" and ctx.user == "engineer" and box.password.text() == ""

    again = SignInDialog(win)
    qtbot.addWidget(again)
    again.show()
    assert again.password.isVisible() and not again.again.isVisible()  # engineer, signed in now, has a password
    again.password.setText("not the passphrase at all")
    again.sign_in()
    assert again.signed_in is None and again.password.text() == "" and not again.result()
    assert [t for t, _ in dialogs] and dialogs[-1][0].startswith("AOI-USR-004")
    win.close()


def test_req_usr_007_no_password_or_hash_in_logs_audit_or_support_bundle(ctx: AppContext, tmp_path: Path) -> None:
    """After a password is chosen, refused, typed wrong and typed right, neither the passphrase (as typed or NFKC) nor
    its hash, nor any Argon2 string, is in the audit entries or any file of the support bundle, logs included.
    The database (and its backups) holds the hash, as it must; the bundle has no copy of the users table."""
    secret = KOREAN
    with pytest.raises(AoiError):
        ctx.sign_in("admin", password=secret[:10])  # refused, too short
    ctx.sign_in("admin", password=secret)
    with pytest.raises(AoiError):
        ctx.sign_in("admin", password=secret + "!")
    ctx.sign_in("admin", password=unicodedata.normalize("NFD", secret))
    stored = ctx.db.user_secret(str(ctx.db.user_uuid("admin")))
    assert stored is not None
    bundle = tmp_path / "support.zip"
    ctx.support_bundle(bundle)
    with zipfile.ZipFile(bundle) as z:
        held = [(f"bundle:{n}", z.read(n)) for n in z.namelist()]
    audit = [("audit", json.dumps(ctx.audit_entries(), ensure_ascii=False).encode("utf-8"))]
    looked = held + audit  # the bundle holds the logs
    assert len(held) > 3 and any(n.startswith("bundle:logs/") for n, _ in held)
    needles = {secret, unicodedata.normalize("NFD", secret), secret[:10], stored, stored.split("$")[-1], "$argon2"}
    found = [(name, n) for name, data in looked for n in needles if n.encode("utf-8") in data]
    assert found == []
