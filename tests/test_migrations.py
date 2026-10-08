"""REQ-SET-016: the database is created and changed only through numbered migrations (ADR 0004); REQ-INSP-010 for the
view column migration 0005 adds; REQ-INSP-012 for the evidence columns and the checks table of migration 0006."""

from __future__ import annotations

import sqlite3
from dataclasses import replace
from pathlib import Path

import pytest

from aoi.data import migrate as mg
from aoi.data.db import Database

V01_TABLES = {"users", "board_models", "samples", "models", "recipes", "inspections", "defects", "test_runs", "alarms"}


def table_names(path: Path) -> set[str]:
    with sqlite3.connect(path) as c:
        return {str(r[0]) for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'")}


def test_req_set_016_fresh_workspace_migrates(tmp_path: Path) -> None:
    db = Database(tmp_path / "aoi.sqlite")
    files = mg.load_migrations()
    rows = db.query("SELECT number, name, checksum, applied_at FROM schema_version ORDER BY number")
    assert [(r["number"], r["name"], r["checksum"]) for r in rows] == [(m.number, m.name, m.checksum) for m in files]
    assert rows[0]["applied_at"].endswith("+00:00")  # recorded in UTC with an offset
    assert V01_TABLES | {"schema_version"} <= table_names(db.path)
    assert mg.migrate(sqlite3.connect(db.path)) == []  # a second start applies nothing
    assert Database(db.path).query("SELECT COUNT(*) n FROM schema_version")[0]["n"] == len(files)


def test_req_set_016_checksum_change_refused(tmp_path: Path) -> None:
    db = Database(tmp_path / "aoi.sqlite")
    edited = [replace(m, sql=m.sql + "-- edited after shipping\n") for m in mg.load_migrations()]
    edited = [replace(m, checksum=mg.checksum(m.sql)) for m in edited]
    with pytest.raises(mg.MigrationError, match="0001_baseline.sql differs"):
        mg.migrate(sqlite3.connect(db.path), edited)


def test_req_set_016_newer_db_refused(tmp_path: Path) -> None:
    db = Database(tmp_path / "aoi.sqlite")
    db.execute(
        "INSERT INTO schema_version(number, name, applied_at, checksum) VALUES (?, ?, ?, ?)",
        (999, "from_a_newer_build", "2027-01-01T00:00:00+00:00", "0" * 64),
    )
    with pytest.raises(mg.MigrationError, match="newer build"):
        Database(db.path)


def test_req_set_016_wal_mode_on(tmp_path: Path) -> None:
    db = Database(tmp_path / "aoi.sqlite")
    assert db.query("PRAGMA journal_mode")[0]["journal_mode"] == "wal"
    assert db.query("PRAGMA synchronous")[0]["synchronous"] == 2  # FULL
    assert db.query("PRAGMA foreign_keys")[0]["foreign_keys"] == 1


def test_req_set_016_v01_workspace_refused(tmp_path: Path) -> None:
    path = tmp_path / "aoi.sqlite"
    with sqlite3.connect(path) as c:
        c.execute("CREATE TABLE users (id INTEGER PRIMARY KEY, name TEXT UNIQUE NOT NULL, role TEXT NOT NULL)")
    with pytest.raises(mg.MigrationError, match="0.1 and cannot be upgraded"):
        Database(path)
    assert table_names(path) == {"users"}  # nothing was added to the old workspace


def test_req_set_016_failed_migration_leaves_no_trace(tmp_path: Path) -> None:
    db = Database(tmp_path / "aoi.sqlite")
    files = mg.load_migrations()
    sql = "CREATE TABLE half_done (id INTEGER PRIMARY KEY);\nCREATE TABLE half_done (id INTEGER PRIMARY KEY);\n"
    bad = mg.Migration(len(files) + 1, "breaks_halfway", sql, mg.checksum(sql))
    with pytest.raises(mg.MigrationError, match="breaks_halfway.sql failed and was rolled back"):
        mg.migrate(sqlite3.connect(db.path), [*files, bad])
    assert "half_done" not in table_names(db.path)
    assert db.query("SELECT MAX(number) n FROM schema_version")[0]["n"] == len(files)


def test_req_set_016_migration_files_are_checked(tmp_path: Path) -> None:
    (tmp_path / "0001_first.sql").write_text("CREATE TABLE a (id INTEGER);\n", encoding="utf-8")
    (tmp_path / "0003_third.sql").write_text("CREATE TABLE c (id INTEGER);\n", encoding="utf-8")
    with pytest.raises(mg.MigrationError, match="without gaps"):
        mg.load_migrations(tmp_path)
    (tmp_path / "0003_third.sql").rename(tmp_path / "0002_second.sql")
    assert [m.file for m in mg.load_migrations(tmp_path)] == ["0001_first.sql", "0002_second.sql"]
    (tmp_path / "0002_second.sql").write_text("BEGIN;\nCREATE TABLE c (id INTEGER);\nCOMMIT;\n", encoding="utf-8")
    with pytest.raises(mg.MigrationError, match="manages its own transaction"):
        mg.load_migrations(tmp_path)
    (tmp_path / "0002_second.sql").rename(tmp_path / "second.sql")
    with pytest.raises(mg.MigrationError, match="NNNN_name.sql"):
        mg.load_migrations(tmp_path)
    assert mg.checksum("a\r\nb\n") == mg.checksum("a\nb\n")  # the same file checked out on Windows


def test_req_insp_010_rows_from_before_the_view_column_keep_no_view(tmp_path: Path) -> None:
    """Migration 0005 adds `inspections.view`: a record written before it stays without a view rather than being given
    one, and the column refuses a view outside Top, Side and Bottom."""
    path = tmp_path / "aoi.sqlite"
    files = mg.load_migrations()
    old = sqlite3.connect(path)
    assert [m.number for m in mg.migrate(old, files[:4])] == [1, 2, 3, 4]
    old.execute("INSERT INTO inspections(uuid, time, result) VALUES('old', '2026-09-30T01:00:00+00:00', 'OK')")
    old.commit()
    old.close()
    db = Database(path)
    applied = [r["number"] for r in db.query("SELECT number FROM schema_version ORDER BY number")]
    assert applied == list(range(1, len(files) + 1))  # the rest of the migrations, whatever their number
    db.add_inspection({"result": "NG", "view": "Bottom", "image_path": "x.png"}, [])
    assert [r["view"] for r in db.inspections(include_archived=True)] == ["Bottom", None]  # newest first
    with pytest.raises(sqlite3.IntegrityError, match="CHECK constraint failed"):  # SQLite 3.37 or later names it
        db.add_inspection({"result": "OK", "view": "Left"}, [])


def test_req_insp_012_rows_from_before_the_evidence_columns_keep_none(tmp_path: Path) -> None:
    """Migration 0006 adds `model_uuid`, `recipe_uuid` and `result_json` to inspections and the `checks` table: a record
    from before it has no checks and no stored result rather than invented ones; a new record's checks come back in
    order, and the record list leaves the stored result out (it is read one record at a time)."""
    path = tmp_path / "aoi.sqlite"
    files = mg.load_migrations()
    old = sqlite3.connect(path)
    assert [m.number for m in mg.migrate(old, files[:5])] == [1, 2, 3, 4, 5]
    old.execute("INSERT INTO inspections(uuid, time, result) VALUES('old', '2026-09-30T01:00:00+00:00', 'OK')")
    old.commit()
    old.close()
    db = Database(path)
    assert "checks" in table_names(path)
    (before,) = db.inspections(include_archived=True)
    assert (before["model_uuid"], before["recipe_uuid"]) == (None, None)
    assert db.checks_for(before["id"]) == [] and db.inspection_result(before["id"]) is None
    check = {"name": "AI anomaly score", "value": 1.5, "threshold": 1.0, "rule": "≥ thr → NG", "verdict": "NG"}
    check.update(source="AI", explain="", region="Board")
    roi = {**check, "name": "ROI R1 [Presence]", "region": "R1 @ 1,2 3x4", "verdict": "OK"}
    rec = {"result": "NG", "view": "Top", "model_uuid": "m-1", "recipe_uuid": "r-1", "result_json": {"verdict": "NG"}}
    iid = db.add_inspection(rec, [], [check, roi])
    stored = [(c["no"], c["metric"], c["region"], c["threshold"], c["result"]) for c in db.checks_for(iid)]
    assert stored == [(1, "AI anomaly score", "Board", 1.0, "NG"), (2, "ROI R1 [Presence]", "R1 @ 1,2 3x4", 1.0, "OK")]
    assert db.inspection_result(iid) == {"verdict": "NG"}
    new = next(r for r in db.inspections(include_archived=True) if r["id"] == iid)
    assert (new["model_uuid"], new["recipe_uuid"]) == ("m-1", "r-1") and "result_json" not in new


def test_req_insp_008_a_record_the_database_refuses_leaves_nothing_behind(tmp_path: Path) -> None:
    """The row, its defects and its checks commit together: a check the database refuses (a NULL value) after the
    inspection row is inserted rolls that row back, and a check dict without a field fails before anything is written;
    either way the connection is out of its transaction, so the next write cannot commit an orphan row."""
    db = Database(tmp_path / "aoi.sqlite")
    check = {"region": "Board", "name": "a", "source": "AI", "value": 1.0, "threshold": 2.0, "rule": "r"}
    check |= {"verdict": "OK", "explain": ""}
    with pytest.raises(sqlite3.IntegrityError):
        db.add_inspection({"result": "OK"}, [], [check, {**check, "value": None}])
    with pytest.raises(KeyError):
        db.add_inspection({"result": "OK"}, [], [{"name": "a"}])
    db.alarm("INFO", "the next write", "AOI-INSP-003")  # would commit a transaction left open
    assert db.inspections() == [] and not db._conn.in_transaction
    db.close()
