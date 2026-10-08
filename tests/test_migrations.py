"""REQ-SET-016: the database is created and changed only through numbered migrations (ADR 0004), backed up before
they run, and a workspace the app refuses can be swapped for another at start-up; REQ-INSP-010 for the view column
migration 0005 adds; REQ-INSP-012 for the evidence columns and the checks table of migration 0006."""

from __future__ import annotations

import builtins
import functools
import json
import logging
import re
import shutil
import sqlite3
import threading
from contextlib import closing
from dataclasses import replace
from pathlib import Path

import pytest
from PySide6.QtWidgets import QFileDialog, QWidget

from aoi import logging_setup
from aoi.config import Settings, default_workspace
from aoi.core.services import AppContext
from aoi.data import migrate as mg
from aoi.data.db import Database
from aoi.data.errors import WorkspaceError
from aoi.errors import AoiError
from aoi.ui import errors as ui_errors

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


def test_req_set_016_backup_before_migrating(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Engineering, "Upgrade and rollback": a database at an older schema version is copied whole beside itself before
    the pending migrations run, and putting the copy back is the rollback; a brand-new database and one with nothing
    pending get no copy; a copy that fails stops the start with AOI-SET-009, leaving the database as it was and no
    half copy behind."""
    path = tmp_path / "aoi.sqlite"
    files = mg.load_migrations()
    with closing(sqlite3.connect(path)) as old:
        mg.migrate(old, files[:4])
        old.execute("INSERT INTO inspections(uuid, time, result) VALUES('old', '2026-09-30T01:00:00+00:00', 'NG')")
        old.commit()
    Database(path).close()
    Database(path).close()  # nothing pending at the second start: no second copy
    (backup,) = [p for p in tmp_path.iterdir() if p.name != "aoi.sqlite"]
    assert re.fullmatch(rf"aoi\.sqlite\.bak-0004-to-{len(files):04d}-\d{{8}}T\d{{6}}Z", backup.name)  # UTC, no colon
    with closing(sqlite3.connect(backup)) as copy:
        assert copy.execute("SELECT MAX(number) FROM schema_version").fetchone() == (4,)
        assert copy.execute("SELECT uuid, result FROM inspections").fetchall() == [("old", "NG")]
    with closing(sqlite3.connect(path)) as live:
        assert live.execute("SELECT MAX(number) FROM schema_version").fetchone() == (len(files),)
    assert sorted(p.name for p in tmp_path.iterdir()) == ["aoi.sqlite", backup.name]
    shutil.copyfile(backup, path)  # the rollback, as docs/manual/engineer.md gives it: the build upgraded from opens it
    with closing(sqlite3.connect(path)) as rolled_back:
        assert mg.migrate(rolled_back, files[:4]) == []
        assert rolled_back.execute("SELECT uuid, result FROM inspections").fetchall() == [("old", "NG")]
    Database(tmp_path / "new" / "aoi.sqlite").close()
    assert [p.name for p in (tmp_path / "new").iterdir()] == ["aoi.sqlite"]

    def disk_full(conn: sqlite3.Connection, target: Path) -> None:
        target.write_bytes(b"half a copy")
        raise sqlite3.OperationalError("database or disk is full")

    path = tmp_path / "full" / "aoi.sqlite"
    path.parent.mkdir()
    with closing(sqlite3.connect(path)) as old:
        mg.migrate(old, files[:4])
    monkeypatch.setattr(mg, "copy_database", disk_full)
    with pytest.raises(mg.MigrationError) as refused:
        Database(path)
    assert refused.value.code == "AOI-SET-009" and "database or disk is full" in refused.value.what
    with closing(sqlite3.connect(path)) as live:
        assert live.execute("SELECT MAX(number) FROM schema_version").fetchone() == (4,)
    assert [p.name for p in path.parent.iterdir()] == ["aoi.sqlite"]


def test_req_set_016_refused_workspace_offers_another(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, dialogs: list[tuple[str, str]]
) -> None:
    """A workspace the app cannot open is refused at start-up, before any window and so before the Settings page: its
    coded message says to choose another folder in the window that opens next, and a folder picker does open. The folder
    chosen is saved to settings.json as the Settings page saves it, and opened; Cancel closes the app as before, and an
    error another folder cannot fix (a wrong setting) opens no picker."""
    v01 = tmp_path / "v01"
    v01.mkdir()
    with closing(sqlite3.connect(v01 / "aoi.sqlite")) as c:
        c.execute("CREATE TABLE users (id INTEGER PRIMARY KEY, name TEXT UNIQUE NOT NULL, role TEXT NOT NULL)")
    Settings(workspace=str(v01), device="cpu").save()
    answers, asked = iter(["", str(tmp_path / "new")]), list[tuple[str, str]]()

    def pick(parent: QWidget | None, title: str, folder: str) -> str:
        asked.append((title, folder))
        return next(answers)

    monkeypatch.setattr(QFileDialog, "getExistingDirectory", staticmethod(pick))
    assert ui_errors.open_workspace() is None  # Cancel: the app closes, settings.json unchanged
    assert Settings.load().workspace == str(v01)
    handlers = logging.getLogger(logging_setup.LOGGER).handlers
    assert not [h for h in handlers if isinstance(h, logging_setup.JsonLinesHandler)]  # no file of it is held open
    ctx = ui_errors.open_workspace()
    assert ctx is not None and ctx.settings.root == tmp_path / "new" and ctx.db.board_models() == []
    ctx.close()
    assert Settings.load().workspace == str(tmp_path / "new") and Settings.load().device == "cpu"
    assert asked == [("Choose another workspace folder", str(v01))] * 2
    assert [title for title, _ in dialogs] == ["AOI-SET-001 Workspace from version 0.1"] * 2
    assert "in the window that opens next" in dialogs[0][1] and "Settings" not in dialogs[0][1]
    assert table_names(v01 / "aoi.sqlite") == {"users"}  # the 0.1 workspace is left as it was
    (default_workspace() / "settings.json").write_text('{"max_image_megabytes": 0}', encoding="utf-8")
    assert ui_errors.open_workspace() is None and len(asked) == 2
    assert dialogs[-1][0] == "AOI-SET-008 Setting invalid"


def test_req_set_019_a_settings_file_that_cannot_be_read_is_refused_with_a_code(
    dialogs: list[tuple[str, str]], capsys: pytest.CaptureFixture[str]
) -> None:
    """A settings.json that is not JSON, not UTF-8 text or not a JSON object is refused at start-up with AOI-SET-010,
    naming the file and what is wrong, in the coded dialog and with no Python traceback; the app closes."""
    f = default_workspace() / "settings.json"
    f.parent.mkdir(parents=True, exist_ok=True)
    cases = (
        (b'{"device": "cpu",}', "it is not valid JSON (line 1, column 18: "),
        (b"\xff\xfe{}", "it is not UTF-8 text"),
        (b'["cpu"]', "it does not hold a JSON object of settings"),
    )
    for content, reason in cases:
        f.write_bytes(content)
        with pytest.raises(AoiError) as refused:
            Settings.load()
        assert refused.value.code == "AOI-SET-010" and str(f) in refused.value.what and reason in refused.value.what
        assert ui_errors.open_workspace() is None
        assert dialogs[-1] == (
            "AOI-SET-010 Settings file cannot be read",
            f"{refused.value.what}\n\n{refused.value.action}",
        )
    assert len(dialogs) == 3 and "Traceback" not in capsys.readouterr().err


def test_req_set_019_a_workspace_that_cannot_be_opened_offers_another(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, dialogs: list[tuple[str, str]]
) -> None:
    """A workspace whose aoi.sqlite is not a database, or whose folder cannot be created (a file stands where a folder
    must go, as on a drive letter with no drive behind it), is refused with AOI-SET-011 naming the folder, and the
    folder picker follows, as for the other refusals another folder cures. The damaged file is left as it was."""
    damaged = tmp_path / "damaged"
    damaged.mkdir()
    (damaged / "aoi.sqlite").write_bytes(b"not a database " * 300)
    blocked = tmp_path / "blocked"
    blocked.write_text("a file, not a folder", encoding="utf-8")
    answers = iter(["", "", str(tmp_path / "new")])
    monkeypatch.setattr(QFileDialog, "getExistingDirectory", staticmethod(lambda *_: next(answers)))
    for workspace in (damaged, blocked / "workspace"):
        Settings(workspace=str(workspace), device="cpu").save()
        with pytest.raises(WorkspaceError) as refused:
            AppContext(Settings.load())
        assert refused.value.code == "AOI-SET-011" and str(workspace) in refused.value.what
        assert ui_errors.open_workspace() is None  # Cancel in the picker closes the app
        assert dialogs[-1][0] == "AOI-SET-011 Workspace cannot be opened"
        assert "in the window that opens next" in dialogs[-1][1]
    ctx = ui_errors.open_workspace()  # the blocked workspace again; this time another folder is chosen
    assert ctx is not None and ctx.settings.root == tmp_path / "new"
    ctx.close()
    assert (damaged / "aoi.sqlite").read_bytes() == b"not a database " * 300
    assert [p.name for p in damaged.iterdir() if p.name.startswith("aoi.sqlite")] == ["aoi.sqlite"]


def test_req_set_019_an_unexpected_error_at_start_up_shows_a_code_and_logs_its_trace(
    monkeypatch: pytest.MonkeyPatch, dialogs: list[tuple[str, str]], capsys: pytest.CaptureFixture[str]
) -> None:
    """An error at start-up that no refusal names shows AOI-SET-007 with the exception's type and no trace; the trace
    goes to the log in the default workspace (stack traces go only to the log), and the log file is closed again."""

    def broken(settings: Settings) -> AppContext:
        raise RuntimeError("the disk controller stopped answering")

    monkeypatch.setattr(ui_errors, "AppContext", broken)
    assert ui_errors.open_workspace() is None
    (title, text) = dialogs[-1]
    assert title == "AOI-SET-007 Unexpected error" and "(RuntimeError)" in text and "(start-up)" in text
    assert "Traceback" not in text and "disk controller" not in text
    lines = [json.loads(line) for f in (default_workspace() / "logs").glob("aoi-*.jsonl") for line in f.open()]
    (failed,) = [line for line in lines if line["event"] == "app.start_failed"]
    assert "RuntimeError: the disk controller stopped answering" in failed["trace"]
    handlers = logging.getLogger(logging_setup.LOGGER).handlers
    assert not [h for h in handlers if isinstance(h, logging_setup.JsonLinesHandler)]
    assert "Traceback" not in capsys.readouterr().err


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


def test_req_insp_012_rows_from_before_the_map_columns_keep_none(tmp_path: Path) -> None:
    """Migration 0007: a record from before it names no maps; new paths are stored relative and come back absolute."""
    path = tmp_path / "aoi.sqlite"
    files = mg.load_migrations()
    old = sqlite3.connect(path)
    assert [m.number for m in mg.migrate(old, files[:6])] == list(range(1, 7))
    old.execute("INSERT INTO inspections(uuid, time, result) VALUES('old', '2026-09-30T01:00:00+00:00', 'OK')")
    old.commit()
    old.close()
    db = Database(path, tmp_path)
    (before,) = db.inspections(include_archived=True)
    assert (before["diff_map_path"], before["ai_map_path"]) == (None, None)
    assert db.map_paths(before["id"]) == (None, None) and db.ok_maps_older_than(0) == []
    diff, ai = tmp_path / "results" / "a_diff.png", tmp_path / "results" / "a_ai.png"
    iid = db.add_inspection({"result": "NG", "diff_map_path": str(diff), "ai_map_path": str(ai)}, [], None)
    stored = db.query("SELECT diff_map_path, ai_map_path FROM inspections WHERE id=?", (iid,))[0]
    assert stored == {"diff_map_path": "results/a_diff.png", "ai_map_path": "results/a_ai.png"}
    assert db.map_paths(iid) == (str(diff), str(ai)) and db.map_paths(iid + 1) == (None, None)
    db.close()


def test_req_cmp_003_rows_from_before_0008_name_no_golden_board(tmp_path: Path) -> None:
    """Migration 0008: a record from before it names no golden board; a new one stores the file relative to the
    workspace with the SHA-256 of its bytes, and reads them back with the path absolute."""
    path = tmp_path / "aoi.sqlite"
    old = sqlite3.connect(path)
    assert [m.number for m in mg.migrate(old, mg.load_migrations()[:7])] == list(range(1, 8))
    old.execute("INSERT INTO inspections(uuid, time, result) VALUES('old', '2026-10-01T01:00:00+00:00', 'OK')")
    old.commit()
    old.close()
    db = Database(path, tmp_path)
    before = db.inspection(db.inspections(include_archived=True)[0]["id"])
    assert before is not None and (before["reference_path"], before["reference_sha256"]) == (None, None)
    golden, sha = tmp_path / "models" / "B" / "B_v1_golden.png", "0f" * 32
    iid = db.add_inspection({"result": "NG", "reference_path": str(golden), "reference_sha256": sha}, [], None)
    stored = db.query("SELECT reference_path, reference_sha256 FROM inspections WHERE id=?", (iid,))[0]
    assert stored == {"reference_path": "models/B/B_v1_golden.png", "reference_sha256": sha}
    new = db.inspection(iid)
    assert new is not None and (new["reference_path"], new["reference_sha256"]) == (str(golden), sha)
    db.close()


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


def test_req_trn_010_switching_the_active_model_is_one_transaction(tmp_path: Path) -> None:
    """#171: registering an active version and activating one each switch in one transaction: a reader on another
    thread never finds no active AI model, and a failure halfway (a trigger refusing the new active row, as a power cut
    between two commits would) keeps the version that was active."""
    db = Database(tmp_path / "aoi.sqlite")
    first, second = (db.register_model("B", v, f"{v}.pt", {}) for v in ("v1.0", "v1.1"))
    seen: list[dict[str, object] | None] = []
    stop = threading.Event()
    reader = threading.Thread(target=lambda: [seen.append(db.active_model("B")) for _ in iter(stop.is_set, True)])
    reader.start()
    for i in range(60):
        db.activate_model(first if i % 2 else second)
    for i in range(30):
        db.register_model("B", f"v2.{i}", f"{i}.pt", {})
    stop.set()
    reader.join()
    assert seen and None not in seen, f"{seen.count(None)} of {len(seen)} reads found no active AI model"
    db.activate_model(first)
    db._conn.executescript(
        "CREATE TEMP TRIGGER u BEFORE UPDATE OF active ON models WHEN NEW.active BEGIN SELECT RAISE(ABORT, 'x'); END;"
        "CREATE TEMP TRIGGER i BEFORE INSERT ON models WHEN NEW.active BEGIN SELECT RAISE(ABORT, 'x'); END;"
    )
    for switch in (lambda: db.activate_model(second), lambda: db.register_model("B", "v3.0", "c.pt", {})):
        with pytest.raises(sqlite3.IntegrityError):
            switch()
        active = db.active_model("B")
        assert active is not None and active["id"] == first and not db._conn.in_transaction
    db.close()


def test_req_set_019_a_database_in_use_at_start_up_offers_the_folder_again(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, dialogs: list[tuple[str, str]]
) -> None:
    """#171: another program holding the workspace database's write lock at start-up (a second copy of the app, a
    database tool) is refused with AOI-SET-012, the database and the log closed first, not shown as AOI-SET-007; the
    folder picker follows, and the same folder opens once the other program lets go."""
    ws = tmp_path / "ws"
    AppContext(Settings(workspace=str(ws), device="cpu")).close()
    Settings(workspace=str(ws), device="cpu").save()
    monkeypatch.setattr(sqlite3, "connect", functools.partial(sqlite3.connect, timeout=0.2))  # not SQLite's 5 s wait
    other = sqlite3.connect(ws / "aoi.sqlite", isolation_level=None)
    other.execute("BEGIN IMMEDIATE")
    closed, close, at_picker = list[Path](), Database.close, list[object]()
    monkeypatch.setattr(Database, "close", lambda db: (closed.append(db.path), close(db))[1])

    def pick(*_: object) -> str:  # what is still open when the picker shows; then the other program lets go
        log = logging.getLogger(logging_setup.LOGGER)
        at_picker.extend([*closed, *(h for h in log.handlers if isinstance(h, logging_setup.JsonLinesHandler))])
        other.rollback()
        return str(ws)

    monkeypatch.setattr(QFileDialog, "getExistingDirectory", staticmethod(pick))
    ctx = ui_errors.open_workspace()
    assert ctx is not None and ctx.settings.root == ws and at_picker == [ws / "aoi.sqlite"]  # closed, no log open
    ctx.close()
    other.close()
    assert [title for title, _ in dialogs] == ["AOI-SET-012 Workspace in use"]
    assert str(ws / "aoi.sqlite") in dialogs[0][1] and "database is locked" in dialogs[0][1]


def test_req_set_016_a_picked_folder_opens_when_settings_json_cannot_be_written(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, dialogs: list[tuple[str, str]]
) -> None:
    """#171: when the default workspace folder, which holds settings.json, cannot be reached (AOI_WORKSPACE on a drive
    that is not connected), the folder picked after AOI-SET-011 is opened all the same: settings.json is written only
    once the folder opened, and a settings.json that cannot be written is logged, not a start-up failure."""
    (tmp_path / "blocker").write_text("a file where the drive's folder would be", encoding="utf-8")
    monkeypatch.setenv("AOI_WORKSPACE", str(tmp_path / "blocker" / "AOI"))
    local = tmp_path / "local"
    monkeypatch.setattr(QFileDialog, "getExistingDirectory", staticmethod(lambda *_: str(local)))
    ctx = ui_errors.open_workspace()
    assert ctx is not None and ctx.settings.root == local and (local / "aoi.sqlite").exists()
    ctx.close()
    assert [title for title, _ in dialogs] == ["AOI-SET-011 Workspace cannot be opened"]
    lines = [json.loads(line) for f in (local / "logs").glob("aoi-*.jsonl") for line in f.open(encoding="utf-8")]
    (failed,) = [line for line in lines if line["event"] == "settings.save_failed"]
    raised = failed["trace"].rstrip().splitlines()[-1].split(":", 1)[0]  # NotADirectoryError; Windows: FileExistsError
    assert (failed["level"], failed["workspace"]) == ("WARNING", str(local))
    assert issubclass(getattr(builtins, raised), OSError), failed["trace"]
