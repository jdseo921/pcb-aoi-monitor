"""Numbered schema migrations (REQ-SET-016, ADR 0004).

The database is created and changed only by the SQL files in ``aoi/data/migrations/``, named
``NNNN_name.sql`` and applied in order at start-up. Each applied file is recorded in ``schema_version``
with its SHA-256, so an edited migration, a database written by a newer build and a v0.1 workspace are
refused with a plain message instead of being changed in place.
"""

from __future__ import annotations

import hashlib
import re
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from .errors import WorkspaceError

MIGRATIONS_DIR = Path(__file__).resolve().parent / "migrations"
FILE_NAME = re.compile(r"^(\d{4})_([a-z0-9_]+)\.sql$")
OWN_TRANSACTION = re.compile(r"^\s*(BEGIN|COMMIT|ROLLBACK|END)\b", re.IGNORECASE | re.MULTILINE)
SCHEMA_VERSION_TABLE = (
    "CREATE TABLE IF NOT EXISTS schema_version ("
    " number INTEGER PRIMARY KEY, name TEXT NOT NULL, applied_at TEXT NOT NULL, checksum TEXT NOT NULL)"
)


class MigrationError(WorkspaceError):
    """The database cannot be brought to this build's schema; nothing was changed."""


@dataclass(frozen=True)
class Migration:
    number: int
    name: str
    sql: str
    checksum: str

    @property
    def file(self) -> str:
        return f"{self.number:04d}_{self.name}.sql"


def checksum(sql: str) -> str:
    """SHA-256 of the text with LF line endings, so a Windows checkout records the same value as Linux."""
    return hashlib.sha256(sql.replace("\r\n", "\n").encode("utf-8")).hexdigest()


def utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def load_migrations(folder: Path = MIGRATIONS_DIR) -> list[Migration]:
    """The migration files in order. Numbers run 1, 2, 3 ... without gaps, and no file manages a transaction."""
    found: list[Migration] = []
    for path in sorted(folder.glob("*.sql")):
        m = FILE_NAME.match(path.name)
        if not m:
            raise MigrationError("AOI-SET-006", problem=f"file name is not NNNN_name.sql: {path.name}")
        sql = path.read_text(encoding="utf-8")
        if OWN_TRANSACTION.search(sql):
            raise MigrationError(
                "AOI-SET-006", problem=f"{path.name} manages its own transaction; the runner does that"
            )
        found.append(Migration(int(m.group(1)), m.group(2), sql, checksum(sql)))
    for expected, mig in enumerate(found, 1):
        if mig.number != expected:
            raise MigrationError("AOI-SET-006", problem=f"numbers must run 1, 2, 3 ... without gaps: found {mig.file}")
    return found


def recorded(conn: sqlite3.Connection) -> dict[int, tuple[str, str]]:
    """What the database records as applied: number -> (name, checksum)."""
    rows = conn.execute("SELECT number, name, checksum FROM schema_version ORDER BY number").fetchall()
    return {int(r[0]): (str(r[1]), str(r[2])) for r in rows}


def migrate(conn: sqlite3.Connection, migrations: list[Migration] | None = None) -> list[Migration]:
    """Bring the database to this build's schema and return the migrations applied now.

    Each pending migration runs in its own transaction, so a failure leaves no trace of it. Refused, with
    nothing changed: a database with tables but no ``schema_version`` (a v0.1 workspace), a recorded
    migration whose checksum differs from the file (an edited migration) and a recorded number this build
    does not ship (a newer build wrote the database).
    """
    files = load_migrations() if migrations is None else migrations
    tables = {str(r[0]) for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    if tables and "schema_version" not in tables:
        raise MigrationError("AOI-SET-001")
    conn.execute(SCHEMA_VERSION_TABLE)
    conn.commit()
    by_number = {m.number: m for m in files}
    for number, (name, digest) in recorded(conn).items():
        known = by_number.get(number)
        if known is None:
            raise MigrationError("AOI-SET-002", migration=f"{number:04d}_{name}")
        if known.checksum != digest:
            raise MigrationError("AOI-SET-003", file=known.file)
    done = recorded(conn)
    applied: list[Migration] = []
    for m in files:
        if m.number in done:
            continue
        try:
            conn.executescript("BEGIN;\n" + m.sql)  # leaves the transaction open for the record below
            conn.execute(
                "INSERT INTO schema_version(number, name, applied_at, checksum) VALUES (?, ?, ?, ?)",
                (m.number, m.name, utc_now(), m.checksum),
            )
            conn.commit()
        except sqlite3.Error as e:
            conn.rollback()
            raise MigrationError("AOI-SET-004", file=m.file, error=str(e)) from e
        applied.append(m)
    return applied
