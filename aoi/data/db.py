"""Local SQLite store (spec 6: "Local SQLite or PostgreSQL database").

All SQL lives here so the rest of the app talks to plain Python methods, and a
PostgreSQL backend can be swapped in for Stage 4 / multi-station use. The schema
is created and changed only by the numbered migrations in ``migrations/``
(REQ-SET-016, ADR 0004).
"""

from __future__ import annotations

import json
import sqlite3
import threading
import uuid
from collections.abc import Callable, Iterable, Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from ..errors import Phrase
from ..times import local_day_bounds_utc, now_utc
from .errors import WorkspaceError
from .migrate import migrate
from .paths import resolve, to_stored

IN_CHUNK = 500  # ids per IN (…) query, under SQLite's 999 bound variables on older builds
WAIT_MS = 5000  # how long a write waits for another program's lock on the database before SQLite refuses it
DbError = sqlite3.Error  # what a Database call raises when SQLite refuses it, for callers that do not import sqlite3


def new_uuid() -> str:
    return str(uuid.uuid4())


def _phrase_json(message: str) -> str | None:
    """An alarm message that is a phrase, as the JSON the alarm list shows it from in the UI language (#198)."""
    return json.dumps(message.to_json(), ensure_ascii=False) if isinstance(message, Phrase) else None


def is_busy(e: BaseException | None) -> bool:
    """SQLite's refusal while another program holds the lock a statement needs (SQLITE_BUSY, SQLITE_LOCKED)."""
    code = getattr(e, "sqlite_errorcode", 0) if isinstance(e, sqlite3.Error) else 0
    return (code & 0xFF) in (sqlite3.SQLITE_BUSY, sqlite3.SQLITE_LOCKED)


class Database:
    """One SQLite file per workspace. Paths inside the workspace are stored relative to it (REQ-SET-001), every
    time in UTC with an offset (REQ-SET-017), and records that can leave the station carry a UUID."""

    def __init__(self, path: Path, workspace: Path | None = None) -> None:
        self.path = Path(path)
        self.workspace = Path(workspace) if workspace else self.path.parent
        self._lock = threading.RLock()  # re-entrant: a statement inside `transaction()` takes it again
        self._tx_depth = 0  # >0 while a `transaction()` is open; only the thread holding the lock reads or sets it
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self._conn = sqlite3.connect(self.path, timeout=WAIT_MS / 1000, check_same_thread=False)
        except (OSError, sqlite3.Error) as e:  # a drive not connected, a folder that cannot be written (REQ-SET-019)
            raise WorkspaceError("AOI-SET-011", path=str(self.workspace), error=str(e)) from e
        self._conn.row_factory = sqlite3.Row
        try:
            # Write-ahead log with a full sync on every commit: a finished write survives a power cut (ADR 0004).
            mode = str(self._conn.execute("PRAGMA journal_mode = WAL").fetchone()[0])
            if mode.lower() != "wal":
                raise WorkspaceError("AOI-SET-005")
            self._conn.execute("PRAGMA synchronous = FULL")
            self._conn.execute("PRAGMA foreign_keys = ON")
            # REPLACE fires the delete triggers of the row it removes, so it cannot slip past audit_no_delete (#196).
            self._conn.execute("PRAGMA recursive_triggers = ON")
            migrate(self._conn)
        except sqlite3.Error as e:  # not a database, damaged, or in use: migrate's own errors carry codes
            self._conn.close()
            raise self.refusal(e) from e
        except BaseException:
            self._conn.close()  # a refused database is not held open while another workspace is chosen (REQ-SET-016)
            raise
        if not self.query("SELECT 1 FROM users LIMIT 1"):
            for n, r in (("operator", "Operator"), ("engineer", "Engineer"), ("admin", "Admin")):
                self.execute("INSERT INTO users(uuid, name, role) VALUES(?,?,?)", (new_uuid(), n, r))

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    def refusal(self, e: DbError) -> WorkspaceError:
        """The start-up refusal the folder picker follows (REQ-SET-016): AOI-SET-012 while another program holds the
        database's lock, else AOI-SET-011 with SQLite's reason (read-only, disk full, damaged)."""
        if is_busy(e):
            return WorkspaceError("AOI-SET-012", path=str(self.path), error=str(e))
        return WorkspaceError("AOI-SET-011", path=str(self.workspace), error=str(e))

    # --- primitives --------------------------------------------------------
    @contextmanager
    def transaction(self) -> Iterator[None]:
        """Every statement inside commits together at the end, or none does: an exception, or the process dying, rolls
        them all back (#178). A write and its audit entry go in one, so neither is ever stored without the other. The
        lock is held throughout, so no other thread's statement joins or commits it; keep file work outside. One opened
        inside another joins it."""
        with self._lock:
            if self._tx_depth:
                self._tx_depth += 1
                try:
                    yield
                finally:
                    self._tx_depth -= 1
                return
            self._conn.execute("BEGIN IMMEDIATE")  # the write lock now: a write inside never waits half-way
            self._tx_depth = 1
            try:
                yield
                self._conn.commit()
            except BaseException:
                self._conn.rollback()
                raise
            finally:
                self._tx_depth = 0

    def _commit(self) -> None:
        """Commit a statement's own transaction; inside `transaction()` the outermost one commits."""
        if not self._tx_depth:
            self._conn.commit()

    def _rollback(self) -> None:
        if not self._tx_depth:  # inside `transaction()` the exception rolls back the whole of it
            self._conn.rollback()

    def execute(self, sql: str, params: Iterable[Any] = (), wait_ms: int | None = None) -> int | None:
        """Run one statement and commit. Returns the new row id after an INSERT, otherwise None. A statement that fails
        is rolled back, so no transaction is left open to hold the write lock or join the next commit (#171).
        `wait_ms` waits that long for another program's lock instead of WAIT_MS (#195)."""
        with self._lock:
            if wait_ms is not None:
                self._conn.execute(f"PRAGMA busy_timeout = {int(wait_ms)}")
            try:
                cur = self._conn.execute(sql, tuple(params))
                self._commit()
            except BaseException:
                self._rollback()
                raise
            finally:
                if wait_ms is not None:
                    self._conn.execute(f"PRAGMA busy_timeout = {WAIT_MS}")
            return cur.lastrowid

    def _insert(self, sql: str, params: Iterable[Any] = ()) -> int:
        """Run one INSERT and return the new row's id."""
        rowid = self.execute(sql, params)
        if rowid is None:
            raise sqlite3.DatabaseError(f"INSERT returned no row id: {sql}")
        return rowid

    def query(self, sql: str, params: Iterable[Any] = ()) -> list[dict[str, Any]]:
        with self._lock:
            return [dict(r) for r in self._conn.execute(sql, tuple(params)).fetchall()]

    # --- paths (REQ-SET-001) -----------------------------------------------
    def resolve_path(self, stored: str) -> str:
        """A path as the database stores it, made absolute for this workspace."""
        return str(resolve(stored, self.workspace))

    def _stored(self, path: str) -> str:
        return to_stored(path, self.workspace)

    def _resolved(self, row: dict[str, Any], *keys: str) -> dict[str, Any]:
        for k in keys:
            if row.get(k):
                row[k] = self.resolve_path(row[k])
        return row

    # --- board models ------------------------------------------------------
    def board_models(self) -> list[str]:
        return [r["name"] for r in self.query("SELECT name FROM board_models ORDER BY name")]

    def ensure_board_model(self, name: str) -> None:
        self.execute("INSERT OR IGNORE INTO board_models(name, created_at) VALUES(?,?)", (name, now_utc()))

    def set_reference(self, board_model: str, path: str) -> None:
        self.ensure_board_model(board_model)
        self.execute("UPDATE board_models SET reference_image=? WHERE name=?", (self._stored(path), board_model))

    def reference(self, board_model: str) -> str | None:
        r = self.query("SELECT reference_image FROM board_models WHERE name=?", (board_model,))
        return self.resolve_path(r[0]["reference_image"]) if r and r[0]["reference_image"] else None

    # --- samples -----------------------------------------------------------
    def add_sample(
        self,
        board_model: str,
        path: str,
        label: str,
        defect_type: str | None = None,
        side: str = "Top",
        uid: str | None = None,
    ) -> int:
        """Add a sample; returns its id. `uid` is the UUID its file name already carries (#245); a new one when None."""
        self.ensure_board_model(board_model)
        return self._insert(
            "INSERT INTO samples(uuid, board_model, path, label, defect_type, side, added_at) VALUES(?,?,?,?,?,?,?)",
            (uid or new_uuid(), board_model, self._stored(path), label, defect_type, side, now_utc()),
        )

    def samples(self, board_model: str, label: str | None = None) -> list[dict[str, Any]]:
        if label:
            rows = self.query("SELECT * FROM samples WHERE board_model=? AND label=? ORDER BY id", (board_model, label))
        else:
            rows = self.query("SELECT * FROM samples WHERE board_model=? ORDER BY id", (board_model,))
        return [self._resolved(r, "path") for r in rows]

    def sample(self, sample_id: int) -> dict[str, Any]:
        """One sample by id, with its absolute path."""
        return self._resolved(self.query("SELECT * FROM samples WHERE id=?", (sample_id,))[0], "path")

    def update_sample(self, sample_id: int, label: str, defect_type: str | None) -> None:
        self.execute("UPDATE samples SET label=?, defect_type=? WHERE id=?", (label, defect_type, sample_id))

    def delete_sample(self, sample_id: int) -> None:
        self.execute("DELETE FROM samples WHERE id=?", (sample_id,))

    # --- model registry ----------------------------------------------------
    def register_model(
        self,
        board_model: str,
        version: str,
        path: str,
        metrics: dict[str, Any],
        activate: bool = True,
        uid: str | None = None,
    ) -> int:
        """Add a model version to the registry and return its id. `uid` is the UUID the model file's metadata already
        holds (training writes it there before the file is saved, REQ-SET-017); a new one when None."""
        uid = uid or new_uuid()
        row = (uid, board_model, version, self._stored(path), now_utc(), json.dumps(metrics), int(activate))
        with self._lock:  # one transaction: a reader sees the old active model or the new one, never none (#171)
            try:
                if activate:
                    self._conn.execute("UPDATE models SET active=0 WHERE board_model=?", (board_model,))
                cur = self._conn.execute(
                    "INSERT INTO models(uuid, board_model, version, path, created_at, metrics, active)"
                    " VALUES(?,?,?,?,?,?,?)",
                    row,
                )
                self._commit()
            except BaseException:  # the old version stays active unless the new one is in
                self._rollback()
                raise
        if cur.lastrowid is None:
            raise sqlite3.DatabaseError("INSERT INTO models returned no row id")
        return cur.lastrowid

    def models(self, board_model: str) -> list[dict[str, Any]]:
        rows = self.query("SELECT * FROM models WHERE board_model=? ORDER BY id DESC", (board_model,))
        return [self._resolved(r, "path") for r in rows]

    def model(self, model_id: int) -> dict[str, Any]:
        """One model version by id, with its absolute path."""
        return self._resolved(self.query("SELECT * FROM models WHERE id=?", (model_id,))[0], "path")

    def active_model(self, board_model: str) -> dict[str, Any] | None:
        r = self.query("SELECT * FROM models WHERE board_model=? AND active=1", (board_model,))
        return self._resolved(r[0], "path") if r else None

    def activate_model(self, model_id: int) -> None:
        """Make `model_id` its board model's one active version in a single statement: never none, or two (#171)."""
        self.execute(
            "UPDATE models SET active = (id = ?) WHERE board_model = (SELECT board_model FROM models WHERE id = ?)",
            (model_id, model_id),
        )

    def next_model_version(self, board_model: str, taken: Callable[[str], bool] = lambda version: False) -> str:
        """The first of v1.0, v1.1, ... from the count of registered versions that no version has and `taken` does not
        report in use, such as by files a run left unregistered: a file a result names is never written over (#178)."""
        names = {m["version"] for m in self.models(board_model)}
        n = len(names)
        while (version := f"v1.{n}") in names or taken(version):
            n += 1
        return version

    # --- recipes -----------------------------------------------------------
    def save_recipe(self, board_model: str, body: dict[str, Any], user: str) -> tuple[int, str]:
        """Store the next revision; returns (revision, uuid)."""
        rev = (self.query("SELECT MAX(revision) m FROM recipes WHERE board_model=?", (board_model,))[0]["m"] or 0) + 1
        uid = new_uuid()
        self.execute(
            "INSERT INTO recipes(uuid, board_model, revision, body, user, created_at) VALUES(?,?,?,?,?,?)",
            (uid, board_model, rev, json.dumps(body), user, now_utc()),
        )
        return rev, uid

    def latest_recipe(self, board_model: str) -> tuple[int, dict[str, Any], str] | None:
        """(revision, body, uuid) of the newest recipe revision, or None while none is stored."""
        r = self.query(
            "SELECT revision, body, uuid FROM recipes WHERE board_model=? ORDER BY revision DESC LIMIT 1",
            (board_model,),
        )
        return (r[0]["revision"], json.loads(r[0]["body"]), str(r[0]["uuid"])) if r else None

    def recipe_history(self, board_model: str) -> list[dict[str, Any]]:
        return self.query(
            "SELECT revision, uuid, user, created_at FROM recipes WHERE board_model=? ORDER BY revision DESC",
            (board_model,),
        )

    # --- inspections -------------------------------------------------------
    def add_inspection(
        self,
        rec: dict[str, Any],
        defects: list[dict[str, Any]],
        checks: list[dict[str, Any]] | None = None,
        alarm: tuple[str, str, str | None] | None = None,
        uid: str | None = None,
    ) -> int:
        """The inspection row, its defects, its checks and its alarm, given as (level, message, code), commit together:
        a crash or a refused write leaves all or none (REQ-INSP-008, REQ-INSP-006; #179). `uid` is the record's UUID,
        which the names of its overlay and maps already carry (#245); a new one when None.
        `rec["result_json"]` is the whole result as `InspectionResult.to_dict` gives it, `model_uuid` and `recipe_uuid`
        name the AI model version and recipe revision that decided it, `diff_map_path` and `ai_map_path` the map files
        beside the overlay, `reference_path` and `reference_sha256` the golden board file it was judged against and the
        SHA-256 of its bytes (every path is stored relative to the workspace), and each check is a dict with the fields
        of `Check` (name, value, threshold, rule, verdict, source, explain, region) (REQ-INSP-012)."""
        result_json = rec.get("result_json")
        row = (
            uid or new_uuid(),
            now_utc(),
            rec.get("board_model"),
            rec.get("model_version"),
            rec.get("model_uuid"),
            rec.get("recipe_rev"),
            rec.get("recipe_uuid"),
            self._stored(rec["image_path"]) if rec.get("image_path") else None,
            self._stored(rec["overlay_path"]) if rec.get("overlay_path") else None,
            self._stored(rec["diff_map_path"]) if rec.get("diff_map_path") else None,
            self._stored(rec["ai_map_path"]) if rec.get("ai_map_path") else None,
            self._stored(rec["reference_path"]) if rec.get("reference_path") else None,
            rec.get("reference_sha256"),
            rec.get("view"),
            rec["result"],
            rec.get("score"),
            json.dumps(rec.get("metrics", {}), allow_nan=False),
            None if result_json is None else json.dumps(result_json, allow_nan=False),
            rec.get("operator"),
        )  # every parameter is built before the transaction opens, so a bad value fails it before the first INSERT
        defect_rows = [
            (d["no"], d["type"], d["score"], d.get("side", "Top"), d["x"], d["y"], d["w"], d["h"]) for d in defects
        ]
        check_rows = [
            (n, c["region"], c["name"], c["source"], c["value"], c["threshold"], c["rule"], c["verdict"], c["explain"])
            for n, c in enumerate(checks or (), 1)
        ]
        with self._lock:
            try:
                cur = self._conn.execute(
                    "INSERT INTO inspections(uuid, time, board_model, model_version, model_uuid, recipe_rev,"
                    " recipe_uuid, image_path, overlay_path, diff_map_path, ai_map_path, reference_path,"
                    " reference_sha256, view, result, score, metrics, result_json, operator)"
                    " VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    row,
                )
                iid = cur.lastrowid
                if iid is None:
                    raise sqlite3.DatabaseError("INSERT INTO inspections returned no row id")
                self._conn.executemany(
                    "INSERT INTO defects(inspection_id, no, type, score, side, x, y, w, h) VALUES(?,?,?,?,?,?,?,?,?)",
                    [(iid, *d) for d in defect_rows],
                )
                self._conn.executemany(
                    "INSERT INTO checks(inspection_id, no, region, metric, source, value, threshold, rule, result,"
                    " explain) VALUES(?,?,?,?,?,?,?,?,?,?)",
                    [(iid, *c) for c in check_rows],
                )
                if alarm is not None:  # an NG board's alarm: never a record without it, nor it without the record
                    level, message, code = alarm
                    self._conn.execute(
                        "INSERT INTO alarms(uuid, time, level, code, message, phrase) VALUES(?,?,?,?,?,?)",
                        (new_uuid(), row[1], level, code, str(message), _phrase_json(message)),
                    )
                self._commit()
            except BaseException:  # a database error or anything else: the record is whole or absent
                self._rollback()
                raise
        return iid

    def inspections(
        self,
        date_from: str | None = None,
        date_to: str | None = None,
        board_model: str | None = None,
        operator: str | None = None,
        include_archived: bool = False,
    ) -> list[dict[str, Any]]:
        sql = (  # every column but result_json and the golden board's, which `inspection_result` and `inspection`
            # read for one record at a time
            "SELECT i.id, i.uuid, i.time, i.board_model, i.model_version, i.model_uuid, i.recipe_rev, i.recipe_uuid,"
            " i.image_path, i.overlay_path, i.diff_map_path, i.ai_map_path, i.view, i.result, i.score, i.metrics,"
            " i.operator, i.archived,"
            " (SELECT COUNT(*) FROM defects d WHERE d.inspection_id=i.id) AS defect_count FROM inspections i WHERE 1=1"
        )
        p: list[Any] = []
        if not include_archived:
            sql += " AND archived=0"
        start, end = local_day_bounds_utc(date_from, date_to)  # the filter takes local calendar days
        if start:
            sql += " AND time >= ?"
            p.append(start)
        if end:
            sql += " AND time < ?"
            p.append(end)
        if board_model:
            sql += " AND board_model = ?"
            p.append(board_model)
        if operator:
            sql += " AND operator = ?"
            p.append(operator)
        rows = self.query(sql + " ORDER BY id DESC", p)
        return [self._resolved(r, "image_path", "overlay_path", "diff_map_path", "ai_map_path") for r in rows]

    def defects_for(self, inspection_id: int) -> list[dict[str, Any]]:
        return self.query("SELECT * FROM defects WHERE inspection_id=? ORDER BY no", (inspection_id,))

    def checks_for(self, inspection_id: int) -> list[dict[str, Any]]:
        """The checks that decided one inspection, in order; [] for a record from before migration 0006."""
        return self.query(
            "SELECT no, region, metric, source, value, threshold, rule, result, explain FROM checks"
            " WHERE inspection_id=? ORDER BY no",
            (inspection_id,),
        )

    def checks_for_many(self, inspection_ids: Iterable[int]) -> dict[int, list[dict[str, Any]]]:
        """The checks of many inspections in one pass, {inspection_id: [checks in order]}, for an export; an id without
        checks (a record from before migration 0006) maps to []."""
        ids = list(dict.fromkeys(inspection_ids))  # each id once, in order
        out: dict[int, list[dict[str, Any]]] = {i: [] for i in ids}
        for start in range(0, len(ids), IN_CHUNK):
            chunk = ids[start : start + IN_CHUNK]
            rows = self.query(
                "SELECT inspection_id, no, region, metric, source, value, threshold, rule, result, explain FROM checks"
                f" WHERE inspection_id IN ({','.join('?' * len(chunk))}) ORDER BY inspection_id, no",
                chunk,
            )
            for r in rows:
                out[r.pop("inspection_id")].append(r)
        return out

    def inspection_result(self, inspection_id: int) -> dict[str, Any] | None:
        """The whole stored result of one inspection, as `InspectionResult.to_dict` wrote it; None for a record from
        before migration 0006 or an unknown id."""
        r = self.query("SELECT result_json FROM inspections WHERE id=?", (inspection_id,))
        return json.loads(r[0]["result_json"]) if r and r[0]["result_json"] else None

    def inspection(self, inspection_id: int) -> dict[str, Any] | None:
        """One inspection record by id with its paths absolute, or None for an unknown id (REQ-INSP-009)."""
        paths = ("image_path", "overlay_path", "diff_map_path", "ai_map_path", "reference_path")
        cols = "id, uuid, time, board_model, model_version, model_uuid, recipe_rev, recipe_uuid, view, result, score"
        sql = f"SELECT {cols}, reference_sha256, {', '.join(paths)} FROM inspections WHERE id=?"
        r = self.query(sql, (inspection_id,))
        return self._resolved(r[0], *paths) if r else None

    def inspection_id(self, uuid: str) -> int | None:
        """The id of the inspection record with this UUID, or None."""
        r = self.query("SELECT id FROM inspections WHERE uuid=?", (uuid,))
        return int(r[0]["id"]) if r else None

    def map_paths(self, inspection_id: int) -> tuple[str | None, str | None]:
        """The stored map files of one inspection, absolute; None where none was stored or the sweep deleted it."""
        rows = self.query("SELECT diff_map_path, ai_map_path FROM inspections WHERE id=?", (inspection_id,))
        row = self._resolved(rows[0], "diff_map_path", "ai_map_path") if rows else {}
        return row.get("diff_map_path"), row.get("ai_map_path")

    def ok_maps_older_than(self, days: int) -> list[dict[str, Any]]:
        """OK inspections older than `days` that still name a map file: id and the two paths, absolute."""
        cutoff = (datetime.now(UTC) - timedelta(days=days)).isoformat(timespec="seconds")
        rows = self.query(
            "SELECT id, diff_map_path, ai_map_path FROM inspections WHERE result='OK' AND time < ?"
            " AND (diff_map_path IS NOT NULL OR ai_map_path IS NOT NULL) ORDER BY id",
            (cutoff,),
        )
        return [self._resolved(r, "diff_map_path", "ai_map_path") for r in rows]

    def clear_map_paths(self, inspection_ids: list[int]) -> None:
        """Forget the map files of these inspections (deleted by the retention sweep), IN_CHUNK ids at a time."""
        for start in range(0, len(inspection_ids), IN_CHUNK):
            chunk = inspection_ids[start : start + IN_CHUNK]
            marks = ",".join("?" * len(chunk))
            self.execute(f"UPDATE inspections SET diff_map_path=NULL, ai_map_path=NULL WHERE id IN ({marks})", chunk)

    def archive_old(self, days: int) -> int:
        cutoff = (datetime.now(UTC) - timedelta(days=days)).isoformat(timespec="seconds")
        n: int = self.query("SELECT COUNT(*) c FROM inspections WHERE archived=0 AND time < ?", (cutoff,))[0]["c"]
        self.execute("UPDATE inspections SET archived=1 WHERE time < ?", (cutoff,))
        return n

    # --- test runs / alarms ------------------------------------------------
    def add_test_run(
        self,
        board_model: str,
        model_version: str,
        folder: str,
        metrics: dict[str, Any],
        results: list[dict[str, Any]],
        model_uuid: str | None = None,
    ) -> str:
        """Store one validation run of the AI Model Test screen, naming the AI model it tested by UUID, and return the
        run's UUID (REQ-SET-017). The folder and each result's "image" are stored relative to the workspace when inside
        it, else absolute: a folder on a USB drive or a share is not part of the workspace and does not move with it
        (REQ-SET-001)."""
        uid = new_uuid()
        stored = [{**r, "image": self._stored(str(Path(r["image"]).absolute()))} for r in results]
        row = (uid, now_utc(), board_model, model_version, model_uuid, self._stored(str(Path(folder).absolute())))
        self._insert(
            "INSERT INTO test_runs(uuid, time, board_model, model_version, model_uuid, folder, metrics, results)"
            " VALUES(?,?,?,?,?,?,?,?)",
            (*row, json.dumps(metrics), json.dumps(stored)),
        )
        return uid

    def latest_test_run(self, board_model: str) -> dict[str, Any] | None:
        """The newest validation run of a board model, with metrics and results decoded and the folder and each result's
        image absolute for this workspace; a run stored before migration 0009 holds absolute paths, read as written."""
        r = self.query("SELECT * FROM test_runs WHERE board_model=? ORDER BY id DESC LIMIT 1", (board_model,))
        if not r:
            return None
        run = self._resolved(r[0], "folder")
        run["metrics"] = json.loads(run["metrics"] or "{}")
        run["results"] = [self._resolved(x, "image") for x in json.loads(run["results"] or "[]")]
        return run

    def inspection_counts(self, board_model: str) -> tuple[int, int]:
        """(inspections, NG inspections) of a board model, archived ones included."""
        sql = "SELECT COUNT(*) n, COALESCE(SUM(result='NG'), 0) ng FROM inspections WHERE board_model=?"
        r = self.query(sql, (board_model,))[0]
        return int(r["n"]), int(r["ng"])

    def alarm(self, level: str, message: str, code: str | None = None, wait_ms: int | None = None) -> None:
        """Store an alarm: its message in English and, for a phrase, the phrase as JSON (migration 0011); `wait_ms` as
        `execute` takes it."""
        self.execute(
            "INSERT INTO alarms(uuid, time, level, code, message, phrase) VALUES(?,?,?,?,?,?)",
            (new_uuid(), now_utc(), level, code, str(message), _phrase_json(message)),
            wait_ms,
        )

    def alarms(self, limit: int = 1000) -> list[dict[str, Any]]:
        """The newest alarms first, at most `limit` of them (REQ-INSP-006)."""
        return self.query("SELECT * FROM alarms ORDER BY id DESC LIMIT ?", (int(limit),))

    def users(self) -> list[dict[str, Any]]:
        return self.query("SELECT * FROM users ORDER BY id")

    def user_uuid(self, name: str) -> str | None:
        r = self.query("SELECT uuid FROM users WHERE name=?", (name,))
        return str(r[0]["uuid"]) if r else None

    # --- audit trail (REQ-LOG-004): append only, enforced by triggers in migration 0003 ----
    def add_audit(
        self,
        user_uuid: str | None,
        role: str | None,
        action: str,
        object_type: str,
        object_uuid: str | None,
        before: dict[str, Any] | None,
        after: dict[str, Any] | None,
        reason: str | None = None,
    ) -> str:
        """Append one entry and return its UUID. There is no method to change or remove one."""
        uid = new_uuid()
        self.execute(
            "INSERT INTO audit(uuid, at_utc, user_uuid, role, action, object_type, object_uuid, before_json,"
            " after_json, reason) VALUES(?,?,?,?,?,?,?,?,?,?)",
            (
                uid,
                now_utc(),
                user_uuid,
                role,
                action,
                object_type,
                object_uuid,
                None if before is None else json.dumps(before, sort_keys=True),
                None if after is None else json.dumps(after, sort_keys=True),
                reason,
            ),
        )
        return uid

    def audit_entries(
        self,
        object_type: str | None = None,
        object_uuid: str | None = None,
        action: str | None = None,
        since: str | None = None,
        limit: int = 1000,
    ) -> list[dict[str, Any]]:
        """Entries newest first, each with the same fields: `before` and `after` decoded from JSON, or None when the
        entry has none, in place of the raw `before_json` and `after_json` columns."""
        sql, p = "SELECT * FROM audit WHERE 1=1", []
        for column, value in (("object_type", object_type), ("object_uuid", object_uuid), ("action", action)):
            if value is not None:
                sql += f" AND {column}=?"
                p.append(value)
        if since:
            sql += " AND at_utc >= ?"
            p.append(since)
        rows = self.query(sql + " ORDER BY id DESC LIMIT ?", [*p, int(limit)])
        for r in rows:
            raw_before, raw_after = r.pop("before_json"), r.pop("after_json")
            r["before"] = None if raw_before is None else json.loads(raw_before)
            r["after"] = None if raw_after is None else json.loads(raw_after)
        return rows

    def add_user(self, name: str, role: str) -> None:
        self.execute(
            "INSERT INTO users(uuid, name, role) VALUES(?,?,?) ON CONFLICT(name) DO UPDATE SET role=excluded.role",
            (new_uuid(), name, role),
        )
