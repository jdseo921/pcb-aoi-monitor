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
from collections.abc import Iterable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from ..times import local_day_bounds_utc, now_utc
from .errors import WorkspaceError
from .migrate import migrate
from .paths import resolve, to_stored


def new_uuid() -> str:
    return str(uuid.uuid4())


class Database:
    """One SQLite file per workspace. Paths inside the workspace are stored relative to it (REQ-SET-001), every
    time in UTC with an offset (REQ-SET-017), and records that can leave the station carry a UUID."""

    def __init__(self, path: Path, workspace: Path | None = None) -> None:
        self.path = Path(path)
        self.workspace = Path(workspace) if workspace else self.path.parent
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(self.path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        # Write-ahead log with a full sync on every commit: a finished write survives a power cut (ADR 0004).
        mode = str(self._conn.execute("PRAGMA journal_mode = WAL").fetchone()[0])
        if mode.lower() != "wal":
            raise WorkspaceError("AOI-SET-005")
        self._conn.execute("PRAGMA synchronous = FULL")
        self._conn.execute("PRAGMA foreign_keys = ON")
        migrate(self._conn)
        if not self.query("SELECT 1 FROM users LIMIT 1"):
            for n, r in (("operator", "Operator"), ("engineer", "Engineer"), ("admin", "Admin")):
                self.execute("INSERT INTO users(uuid, name, role) VALUES(?,?,?)", (new_uuid(), n, r))

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    # --- primitives --------------------------------------------------------
    def execute(self, sql: str, params: Iterable[Any] = ()) -> int | None:
        """Run one statement and commit. Returns the new row id after an INSERT, otherwise None."""
        with self._lock:
            cur = self._conn.execute(sql, tuple(params))
            self._conn.commit()
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
        self, board_model: str, path: str, label: str, defect_type: str | None = None, side: str = "Top"
    ) -> int:
        self.ensure_board_model(board_model)
        return self._insert(
            "INSERT INTO samples(uuid, board_model, path, label, defect_type, side, added_at) VALUES(?,?,?,?,?,?,?)",
            (new_uuid(), board_model, self._stored(path), label, defect_type, side, now_utc()),
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
        self, board_model: str, version: str, path: str, metrics: dict[str, Any], activate: bool = True
    ) -> int:
        if activate:
            self.execute("UPDATE models SET active=0 WHERE board_model=?", (board_model,))
        return self._insert(
            "INSERT INTO models(uuid, board_model, version, path, created_at, metrics, active) VALUES(?,?,?,?,?,?,?)",
            (new_uuid(), board_model, version, self._stored(path), now_utc(), json.dumps(metrics), int(activate)),
        )

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
        bm = self.query("SELECT board_model FROM models WHERE id=?", (model_id,))[0]["board_model"]
        self.execute("UPDATE models SET active=0 WHERE board_model=?", (bm,))
        self.execute("UPDATE models SET active=1 WHERE id=?", (model_id,))

    def next_model_version(self, board_model: str) -> str:
        n = len(self.models(board_model)) + 1
        return f"v1.{n - 1}" if n > 1 else "v1.0"

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
        self, rec: dict[str, Any], defects: list[dict[str, Any]], checks: list[dict[str, Any]] | None = None
    ) -> int:
        """The inspection row, its defects and its checks commit together: a crash leaves all or none (REQ-INSP-008).
        `rec["result_json"]` is the whole result as `InspectionResult.to_dict` gives it, `model_uuid` and `recipe_uuid`
        name the AI model version and recipe revision that decided it, and each check is a dict with the fields of
        `Check` (name, value, threshold, rule, verdict, source, explain, region) (REQ-INSP-012)."""
        result_json = rec.get("result_json")
        row = (
            new_uuid(),
            now_utc(),
            rec.get("board_model"),
            rec.get("model_version"),
            rec.get("model_uuid"),
            rec.get("recipe_rev"),
            rec.get("recipe_uuid"),
            self._stored(rec["image_path"]) if rec.get("image_path") else None,
            self._stored(rec["overlay_path"]) if rec.get("overlay_path") else None,
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
                    " recipe_uuid, image_path, overlay_path, view, result, score, metrics, result_json, operator)"
                    " VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
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
                self._conn.commit()
            except BaseException:  # a database error or anything else: the record is whole or absent
                self._conn.rollback()
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
        sql = (  # every column but result_json, which `inspection_result` reads for one record at a time
            "SELECT i.id, i.uuid, i.time, i.board_model, i.model_version, i.model_uuid, i.recipe_rev, i.recipe_uuid,"
            " i.image_path, i.overlay_path, i.view, i.result, i.score, i.metrics, i.operator, i.archived,"
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
        return [self._resolved(r, "image_path", "overlay_path") for r in self.query(sql + " ORDER BY id DESC", p)]

    def defects_for(self, inspection_id: int) -> list[dict[str, Any]]:
        return self.query("SELECT * FROM defects WHERE inspection_id=? ORDER BY no", (inspection_id,))

    def checks_for(self, inspection_id: int) -> list[dict[str, Any]]:
        """The checks that decided one inspection, in order; [] for a record from before migration 0006."""
        return self.query(
            "SELECT no, region, metric, source, value, threshold, rule, result, explain FROM checks"
            " WHERE inspection_id=? ORDER BY no",
            (inspection_id,),
        )

    def inspection_result(self, inspection_id: int) -> dict[str, Any] | None:
        """The whole stored result of one inspection, as `InspectionResult.to_dict` wrote it; None for a record from
        before migration 0006 or an unknown id."""
        r = self.query("SELECT result_json FROM inspections WHERE id=?", (inspection_id,))
        return json.loads(r[0]["result_json"]) if r and r[0]["result_json"] else None

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
    ) -> int:
        return self._insert(
            "INSERT INTO test_runs(time, board_model, model_version, folder, metrics, results) VALUES(?,?,?,?,?,?)",
            (now_utc(), board_model, model_version, folder, json.dumps(metrics), json.dumps(results)),
        )

    def latest_test_run(self, board_model: str) -> dict[str, Any] | None:
        r = self.query("SELECT * FROM test_runs WHERE board_model=? ORDER BY id DESC LIMIT 1", (board_model,))
        return r[0] if r else None

    def inspection_counts(self, board_model: str) -> tuple[int, int]:
        """(inspections, NG inspections) of a board model, archived ones included."""
        sql = "SELECT COUNT(*) n, COALESCE(SUM(result='NG'), 0) ng FROM inspections WHERE board_model=?"
        r = self.query(sql, (board_model,))[0]
        return int(r["n"]), int(r["ng"])

    def alarm(self, level: str, message: str, code: str | None = None) -> None:
        self.execute(
            "INSERT INTO alarms(time, level, code, message) VALUES(?,?,?,?)", (now_utc(), level, code, message)
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
        """Entries newest first, with before and after decoded from JSON."""
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
            r["before"] = json.loads(r.pop("before_json")) if r["before_json"] else None
            r["after"] = json.loads(r.pop("after_json")) if r["after_json"] else None
        return rows

    def add_user(self, name: str, role: str) -> None:
        self.execute(
            "INSERT INTO users(uuid, name, role) VALUES(?,?,?) ON CONFLICT(name) DO UPDATE SET role=excluded.role",
            (new_uuid(), name, role),
        )
