"""Accounts with passwords (REQ-USR-002, REQ-USR-007; ADR 0002, ADR 0024 D3): Argon2id hashes of NFKC text, the rules
for a new password and a PIN, and the migration that puts the seeded Engineer and Admin in set-up."""

from __future__ import annotations

import sqlite3
import unicodedata
from pathlib import Path

from argon2 import PasswordHasher

from aoi.config import APP_NAME
from aoi.core import passwords
from aoi.data.db import Database

KOREAN = "부산 바다 위를 나는 일곱 마리 올빼미"  # 21 characters, typed composed (NFC)


def test_req_usr_002_a_secret_is_an_argon2id_hash_of_its_nfkc_text() -> None:
    """The same Korean passphrase typed as composed or decomposed jamo is one secret; the hash is Argon2id with its
    parameters in the string, never the text; one made with weaker parameters is stale."""
    stored = passwords.hash_secret(KOREAN)
    assert stored.startswith("$argon2id$v=19$m=65536,t=3,p=4$") and KOREAN not in stored
    assert passwords.verify(stored, unicodedata.normalize("NFD", KOREAN))
    assert not passwords.verify(stored, KOREAN[:-1]) and not passwords.verify(None, KOREAN)
    assert not passwords.verify("not a hash", KOREAN) and not passwords.stale(stored)
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
