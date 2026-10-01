"""Local SQLite store (spec 6: "Local SQLite or PostgreSQL database").

All SQL lives here so the rest of the app talks to plain Python methods, and a
PostgreSQL backend can be swapped in for Stage 4 / multi-station use.
"""

from __future__ import annotations

import json
import sqlite3
import threading
from collections.abc import Iterable
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY, name TEXT UNIQUE NOT NULL,
    role TEXT NOT NULL CHECK(role IN ('Operator','Engineer','Admin'))
);
CREATE TABLE IF NOT EXISTS board_models (
    id INTEGER PRIMARY KEY, name TEXT UNIQUE NOT NULL,
    reference_image TEXT,               -- golden sample used by Compare
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS samples (     -- uploaded training / validation images
    id INTEGER PRIMARY KEY,
    board_model TEXT NOT NULL,
    path TEXT NOT NULL,
    label TEXT NOT NULL CHECK(label IN ('OK','NG')),
    defect_type TEXT,                    -- from aoi.defects when label = NG
    side TEXT DEFAULT 'Top',             -- Top | Side | Bottom
    added_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS models (      -- trained model registry (version control)
    id INTEGER PRIMARY KEY,
    board_model TEXT NOT NULL,
    version TEXT NOT NULL,
    path TEXT NOT NULL,
    created_at TEXT NOT NULL,
    metrics TEXT,                        -- JSON: loss, calibrated thresholds, val scores
    active INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS recipes (
    id INTEGER PRIMARY KEY,
    board_model TEXT NOT NULL,
    revision INTEGER NOT NULL,
    body TEXT NOT NULL,                  -- JSON (aoi.core.recipe.Recipe)
    user TEXT, created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS inspections (
    id INTEGER PRIMARY KEY,
    time TEXT NOT NULL,
    board_model TEXT, model_version TEXT, recipe_rev INTEGER,
    image_path TEXT, overlay_path TEXT,
    result TEXT NOT NULL,                -- OK | NG | WARN
    score REAL, metrics TEXT, operator TEXT,
    archived INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS defects (
    id INTEGER PRIMARY KEY,
    inspection_id INTEGER NOT NULL REFERENCES inspections(id) ON DELETE CASCADE,
    no INTEGER, type TEXT, score REAL, side TEXT,
    x INTEGER, y INTEGER, w INTEGER, h INTEGER
);
CREATE TABLE IF NOT EXISTS test_runs (   -- AI Model Test screen history
    id INTEGER PRIMARY KEY, time TEXT NOT NULL, board_model TEXT,
    model_version TEXT, folder TEXT, metrics TEXT, results TEXT
);
CREATE TABLE IF NOT EXISTS alarms (
    id INTEGER PRIMARY KEY, time TEXT NOT NULL, level TEXT, message TEXT
);
"""


def now() -> str:
    return datetime.now().isoformat(timespec="seconds")


class Database:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(self.path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA foreign_keys = ON")
        self._conn.executescript(SCHEMA)
        if not self.query("SELECT 1 FROM users LIMIT 1"):
            for n, r in (("operator", "Operator"), ("engineer", "Engineer"), ("admin", "Admin")):
                self.execute("INSERT INTO users(name, role) VALUES(?,?)", (n, r))

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

    # --- board models ------------------------------------------------------
    def board_models(self) -> list[str]:
        return [r["name"] for r in self.query("SELECT name FROM board_models ORDER BY name")]

    def ensure_board_model(self, name: str) -> None:
        self.execute("INSERT OR IGNORE INTO board_models(name, created_at) VALUES(?,?)", (name, now()))

    def set_reference(self, board_model: str, path: str) -> None:
        self.ensure_board_model(board_model)
        self.execute("UPDATE board_models SET reference_image=? WHERE name=?", (path, board_model))

    def reference(self, board_model: str) -> str | None:
        r = self.query("SELECT reference_image FROM board_models WHERE name=?", (board_model,))
        return r[0]["reference_image"] if r else None

    # --- samples -----------------------------------------------------------
    def add_sample(
        self, board_model: str, path: str, label: str, defect_type: str | None = None, side: str = "Top"
    ) -> int:
        self.ensure_board_model(board_model)
        return self._insert(
            "INSERT INTO samples(board_model, path, label, defect_type, side, added_at) VALUES(?,?,?,?,?,?)",
            (board_model, path, label, defect_type, side, now()),
        )

    def samples(self, board_model: str, label: str | None = None) -> list[dict[str, Any]]:
        if label:
            return self.query("SELECT * FROM samples WHERE board_model=? AND label=? ORDER BY id", (board_model, label))
        return self.query("SELECT * FROM samples WHERE board_model=? ORDER BY id", (board_model,))

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
            "INSERT INTO models(board_model, version, path, created_at, metrics, active) VALUES(?,?,?,?,?,?)",
            (board_model, version, path, now(), json.dumps(metrics), int(activate)),
        )

    def models(self, board_model: str) -> list[dict[str, Any]]:
        return self.query("SELECT * FROM models WHERE board_model=? ORDER BY id DESC", (board_model,))

    def active_model(self, board_model: str) -> dict[str, Any] | None:
        r = self.query("SELECT * FROM models WHERE board_model=? AND active=1", (board_model,))
        return r[0] if r else None

    def activate_model(self, model_id: int) -> None:
        bm = self.query("SELECT board_model FROM models WHERE id=?", (model_id,))[0]["board_model"]
        self.execute("UPDATE models SET active=0 WHERE board_model=?", (bm,))
        self.execute("UPDATE models SET active=1 WHERE id=?", (model_id,))

    def next_model_version(self, board_model: str) -> str:
        n = len(self.models(board_model)) + 1
        return f"v1.{n - 1}" if n > 1 else "v1.0"

    # --- recipes -----------------------------------------------------------
    def save_recipe(self, board_model: str, body: dict[str, Any], user: str) -> int:
        rev = (self.query("SELECT MAX(revision) m FROM recipes WHERE board_model=?", (board_model,))[0]["m"] or 0) + 1
        self.execute(
            "INSERT INTO recipes(board_model, revision, body, user, created_at) VALUES(?,?,?,?,?)",
            (board_model, rev, json.dumps(body), user, now()),
        )
        return rev

    def latest_recipe(self, board_model: str) -> tuple[int, dict[str, Any]] | None:
        r = self.query(
            "SELECT revision, body FROM recipes WHERE board_model=? ORDER BY revision DESC LIMIT 1", (board_model,)
        )
        return (r[0]["revision"], json.loads(r[0]["body"])) if r else None

    def recipe_history(self, board_model: str) -> list[dict[str, Any]]:
        return self.query(
            "SELECT revision, user, created_at FROM recipes WHERE board_model=? ORDER BY revision DESC", (board_model,)
        )

    # --- inspections -------------------------------------------------------
    def add_inspection(self, rec: dict[str, Any], defects: list[dict[str, Any]]) -> int:
        iid = self._insert(
            "INSERT INTO inspections(time, board_model, model_version, recipe_rev, image_path, overlay_path,"
            " result, score, metrics, operator) VALUES(?,?,?,?,?,?,?,?,?,?)",
            (
                now(),
                rec.get("board_model"),
                rec.get("model_version"),
                rec.get("recipe_rev"),
                rec.get("image_path"),
                rec.get("overlay_path"),
                rec["result"],
                rec.get("score"),
                json.dumps(rec.get("metrics", {})),
                rec.get("operator"),
            ),
        )
        for d in defects:
            self.execute(
                "INSERT INTO defects(inspection_id, no, type, score, side, x, y, w, h) VALUES(?,?,?,?,?,?,?,?,?)",
                (iid, d["no"], d["type"], d["score"], d.get("side", "Top"), d["x"], d["y"], d["w"], d["h"]),
            )
        return iid

    def inspections(
        self,
        date_from: str | None = None,
        date_to: str | None = None,
        board_model: str | None = None,
        operator: str | None = None,
        include_archived: bool = False,
    ) -> list[dict[str, Any]]:
        sql = (
            "SELECT i.*, (SELECT COUNT(*) FROM defects d WHERE d.inspection_id=i.id) AS defect_count "
            "FROM inspections i WHERE 1=1"
        )
        p: list[Any] = []
        if not include_archived:
            sql += " AND archived=0"
        if date_from:
            sql += " AND time >= ?"
            p.append(date_from)
        if date_to:
            sql += " AND time <= ?"
            p.append(date_to + "T23:59:59")
        if board_model:
            sql += " AND board_model = ?"
            p.append(board_model)
        if operator:
            sql += " AND operator = ?"
            p.append(operator)
        return self.query(sql + " ORDER BY id DESC", p)

    def defects_for(self, inspection_id: int) -> list[dict[str, Any]]:
        return self.query("SELECT * FROM defects WHERE inspection_id=? ORDER BY no", (inspection_id,))

    def archive_old(self, days: int) -> int:
        cutoff = (datetime.now() - timedelta(days=days)).isoformat(timespec="seconds")
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
            (now(), board_model, model_version, folder, json.dumps(metrics), json.dumps(results)),
        )

    def alarm(self, level: str, message: str) -> None:
        self.execute("INSERT INTO alarms(time, level, message) VALUES(?,?,?)", (now(), level, message))

    def users(self) -> list[dict[str, Any]]:
        return self.query("SELECT * FROM users ORDER BY id")

    def add_user(self, name: str, role: str) -> None:
        self.execute("INSERT OR REPLACE INTO users(name, role) VALUES(?,?)", (name, role))
