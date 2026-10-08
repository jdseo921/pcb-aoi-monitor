"""REQ-SET-017 (UUIDs and UTC times) and REQ-SET-001 (a workspace that moves): ADR 0004, stage S10."""

from __future__ import annotations

import json
import re
import shutil
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

import pytest

from aoi.config import Settings
from aoi.core.recipe import Recipe
from aoi.core.services import AppContext
from aoi.data import migrate as mg
from aoi.data import times
from tests.conftest import TrainedModel

UUID4 = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$")
STORED_TIME = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\+00:00$")
RECORD_TABLES = ("users", "samples", "models", "recipes", "inspections")
STORED_PATHS = (
    ("samples", "path"),
    ("models", "path"),
    ("inspections", "overlay_path"),
    ("board_models", "reference_image"),
)


def filled_ctx(tmp_path: Path, tiny_model: TrainedModel, name: str = "ws") -> AppContext:
    """A private copy of the trained workspace with one inspection logged and one recipe saved."""
    ws = tmp_path / name
    shutil.copytree(tiny_model.ctx.settings.root, ws)
    ctx = AppContext(Settings(workspace=str(ws), device="cpu"))
    ctx.inspect_file("TINY", ctx.db.samples("TINY", "NG")[0]["path"])
    ctx.save_recipe(Recipe(board_model="TINY"))
    return ctx


def test_req_set_017_records_have_uuid(tmp_path: Path, tiny_model: TrainedModel) -> None:
    ctx = filled_ctx(tmp_path, tiny_model)
    for table in RECORD_TABLES:
        ids = [r["uuid"] for r in ctx.db.query(f"SELECT uuid FROM {table}")]
        assert ids and all(UUID4.match(u) for u in ids), table
        assert len(set(ids)) == len(ids), table
    ctx.db.add_user("operator", "Engineer")  # a role change keeps the record, and so its UUID
    assert len({r["uuid"] for r in ctx.db.query("SELECT uuid FROM users")}) == 3


def test_req_set_017_migration_0002_backfills_existing_rows(tmp_path: Path) -> None:
    conn = sqlite3.connect(tmp_path / "v1.sqlite")
    files = mg.load_migrations()
    mg.migrate(conn, files[:1])
    conn.execute("INSERT INTO users(name, role) VALUES ('old', 'Operator')")
    conn.execute("INSERT INTO inspections(time, result) VALUES ('2026-10-01T00:00:00+00:00', 'OK')")
    conn.commit()
    mg.migrate(conn, files)
    filled = {t: conn.execute(f"SELECT uuid FROM {t}").fetchone()[0] for t in ("users", "inspections")}
    assert all(UUID4.match(u) for u in filled.values()), filled
    with pytest.raises(sqlite3.IntegrityError):  # the column is unique
        conn.execute("INSERT INTO users(uuid, name, role) VALUES (?, 'two', 'Operator')", (filled["users"],))


def test_req_set_017_times_are_utc_with_offset(tmp_path: Path, tiny_model: TrainedModel) -> None:
    ctx = filled_ctx(tmp_path, tiny_model)
    stored = [
        ctx.db.query(f"SELECT {column} t FROM {table} LIMIT 1")[0]["t"]
        for table, column in (("inspections", "time"), ("models", "created_at"), ("recipes", "created_at"))
    ] + [ctx.db.query("SELECT added_at t FROM samples LIMIT 1")[0]["t"]]
    assert all(STORED_TIME.match(t) for t in stored), stored
    t = stored[0]
    assert datetime.fromisoformat(t).tzinfo == UTC
    assert times.to_local(t) == datetime.fromisoformat(t).astimezone().strftime("%Y-%m-%d %H:%M:%S")
    assert times.to_local("2026-10-01T14:05:00") == "2026-10-01 14:05:00"  # v0.1 data, no offset: shown as written
    today = datetime.now().strftime("%Y-%m-%d")  # the Logs filter takes local calendar days
    assert len(ctx.db.inspections(today, today)) == 1
    assert ctx.db.inspections("2000-01-01", "2000-01-02") == []
    assert ctx.db.inspections(date_to="2000-01-02") == []


def test_req_set_001_moved_workspace_opens_everything(tmp_path: Path, tiny_model: TrainedModel) -> None:
    old = filled_ctx(tmp_path, tiny_model, "old_place")
    old_root = old.settings.root
    for table, column in STORED_PATHS:
        for r in old.db.query(f"SELECT {column} p FROM {table}"):
            assert r["p"] and not Path(r["p"]).is_absolute(), (table, r["p"])
    old.db.close()
    new_root = tmp_path / "new_place"
    shutil.move(str(old_root), str(new_root))

    ctx = AppContext(Settings(workspace=str(new_root), device="cpu"))
    opened = [Path(s["path"]) for s in ctx.db.samples("TINY")]
    ref = ctx.db.reference("TINY")
    active = ctx.db.active_model("TINY")
    assert ref and active
    opened += [Path(ref), Path(active["path"])]
    for r in ctx.db.inspections(include_archived=True):
        opened += [Path(r["overlay_path"]), Path(r["image_path"])]  # the inspected board was a sample
    assert len(opened) == len(tiny_model.ctx.db.samples("TINY")) + 4
    assert all(p.is_relative_to(new_root) and p.exists() for p in opened), opened
    assert ctx.load_model("TINY") is not None
    assert ctx.inspect_file("TINY", str(opened[0])).verdict in ("OK", "WARN", "NG")
    assert str(old_root) not in json.dumps(ctx.db.query("SELECT * FROM inspections"))
