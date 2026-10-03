"""Numbered schema migrations (REQ-SET-016, ADR 0004).

The database is created and changed only by the SQL files in ``aoi/data/migrations/``, named
``NNNN_name.sql`` and applied in order at start-up. Each applied file is recorded in ``schema_version``
with its SHA-256, so an edited migration, a database written by a newer build and a v0.1 workspace are
refused with a plain message instead of being changed in place. A database that already has a schema is copied beside
itself before the pending files run (Engineering, "Upgrade and rollback"); putting that copy back is the rollback.
"""

from __future__ import annotations

import hashlib
import logging
import os
import re
import sqlite3
from contextlib import closing
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from ..errors import QT_TRANSLATE_NOOP
from .atomic import TEMP_SUFFIX
from .errors import WorkspaceError

log = logging.getLogger(__name__)
MIGRATIONS_DIR = Path(__file__).resolve().parent / "migrations"
FILE_NAME = re.compile(r"^(\d{4})_([a-z0-9_]+)\.sql$")
OWN_TRANSACTION = re.compile(r"^\s*(BEGIN|COMMIT|ROLLBACK|END)\b", re.IGNORECASE | re.MULTILINE)
SCHEMA_VERSION_TABLE = (
    "CREATE TABLE IF NOT EXISTS schema_version ("
    " number INTEGER PRIMARY KEY, name TEXT NOT NULL, applied_at TEXT NOT NULL, checksum TEXT NOT NULL)"
)


# What is wrong with the migration files (AOI-SET-006), as phrases a screen translates (#198)
BAD_NAME = QT_TRANSLATE_NOOP("Errors", "file name is not NNNN_name.sql: {file}")
OWN_COMMIT = QT_TRANSLATE_NOOP("Errors", "{file} manages its own transaction; the runner does that")
GAP = QT_TRANSLATE_NOOP("Errors", "numbers must run 1, 2, 3 ... without gaps: found {file}")


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
            raise MigrationError("AOI-SET-006", problem=BAD_NAME.fill(file=path.name))
        sql = path.read_text(encoding="utf-8")
        if OWN_TRANSACTION.search(sql):
            raise MigrationError("AOI-SET-006", problem=OWN_COMMIT.fill(file=path.name))
        found.append(Migration(int(m.group(1)), m.group(2), sql, checksum(sql)))
    for expected, mig in enumerate(found, 1):
        if mig.number != expected:
            raise MigrationError("AOI-SET-006", problem=GAP.fill(file=mig.file))
    return found


def recorded(conn: sqlite3.Connection) -> dict[int, tuple[str, str]]:
    """What the database records as applied: number -> (name, checksum)."""
    rows = conn.execute("SELECT number, name, checksum FROM schema_version ORDER BY number").fetchall()
    return {int(r[0]): (str(r[1]), str(r[2])) for r in rows}


def copy_database(conn: sqlite3.Connection, target: Path) -> None:
    """A consistent copy of the open database at `target`, through SQLite's online backup."""
    with closing(sqlite3.connect(target)) as copy:
        conn.backup(copy)


def backup(conn: sqlite3.Connection, old: int, new: int) -> Path:
    """Copy the database to ``<file>.bak-<old>-to-<new>-<UTC time>`` beside it before migrating it from schema version
    `old` to `new`, and return the copy's path. The copy is written under a temporary name and renamed once whole, so a
    crash leaves no half copy under the backup's name; a copy that fails is removed and raises AOI-SET-009."""
    db = Path(conn.execute("PRAGMA database_list").fetchone()[2])  # the main database's file
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")  # ISO 8601 basic: no colon, which Windows refuses in a name
    target = db.with_name(f"{db.name}.bak-{old:04d}-to-{new:04d}-{stamp}")
    tmp = target.with_name(f".{target.name}{TEMP_SUFFIX}")  # swept at the next start if a crash leaves it
    try:
        copy_database(conn, tmp)
        os.replace(tmp, target)
    except (sqlite3.Error, OSError) as e:
        for part in ("", "-journal", "-wal", "-shm"):  # the half copy and any side file SQLite left with it
            tmp.with_name(tmp.name + part).unlink(missing_ok=True)
        raise MigrationError("AOI-SET-009", file=target.name, error=str(e)) from e
    log.info("schema.backup", extra={"backup": target.name, "from_version": old, "to_version": new})
    return target


def migrate(conn: sqlite3.Connection, migrations: list[Migration] | None = None) -> list[Migration]:
    """Bring the database to this build's schema and return the migrations applied now.

    Each pending migration runs in its own transaction, so a failure leaves no trace of it. Refused, with
    nothing changed: a database with tables but no ``schema_version`` (a v0.1 workspace), a recorded
    migration whose checksum differs from the file (an edited migration) and a recorded number this build
    does not ship (a newer build wrote the database). A database with migrations applied and more pending is
    first copied by `backup`; a failed copy stops here, nothing migrated.
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
    pending = [m for m in files if m.number not in done]
    if done and pending:  # a brand-new database holds nothing to lose, and gets no copy
        backup(conn, max(done), pending[-1].number)
    applied: list[Migration] = []
    for m in pending:
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
        log.info("schema.migrated", extra={"migration": m.file, "checksum": m.checksum[:12]})
    return applied
