"""REQ-SET-017 (UUIDs and UTC times) and REQ-SET-001 (a workspace that moves): ADR 0004, stage S10."""

from __future__ import annotations

import csv
import html
import json
import re
import shutil
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import cast

import cv2
import numpy as np
import pytest
from PySide6.QtWidgets import QFileDialog, QMessageBox
from pytestqt.qtbot import QtBot

from aoi import times
from aoi.config import Settings
from aoi.core.anomaly import AnomalyModel
from aoi.core.recipe import Recipe
from aoi.core.services import AppContext
from aoi.data import db as dbmod
from aoi.data import migrate as mg
from aoi.data.db import Database
from aoi.ui.main_window import MainWindow
from aoi.ui.pages.settings import SettingsPage
from tests.conftest import TrainedModel, engineer
from tests.test_req_done_in_v01 import BOARD, _window

UUID4 = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$")
STORED_TIME = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\+00:00$")
RECORD_TABLES = ("users", "samples", "models", "recipes", "inspections", "test_runs", "alarms")
STORED_PATHS = (
    ("test_runs", "folder"),
    ("samples", "path"),
    ("models", "path"),
    ("inspections", "overlay_path"),
    ("inspections", "diff_map_path"),
    ("inspections", "ai_map_path"),
    ("inspections", "reference_path"),
    ("board_models", "reference_image"),
)


def filled_ctx(tmp_path: Path, tiny_model: TrainedModel, name: str = "ws") -> AppContext:
    """A private copy of the trained workspace with one inspection logged, one recipe saved, one alarm stored and one
    validation run on a folder inside the workspace (`validation/ok` and `validation/ng`, a sample copied into each)."""
    ws = tmp_path / name
    shutil.copytree(tiny_model.ctx.settings.root, ws)
    ctx = engineer(AppContext(Settings(workspace=str(ws), device="cpu")))
    ctx.inspect_file("TINY", ctx.db.samples("TINY", "NG")[0]["path"])
    ctx.save_recipe(Recipe(board_model="TINY"))
    ctx.alarm("WARN", "a stored alarm")
    for label in ("OK", "NG"):
        (ws / "validation" / label.lower()).mkdir(parents=True)
        shutil.copy(ctx.db.samples("TINY", label)[0]["path"], ws / "validation" / label.lower())
    ctx.batch_test("TINY", str(ws / "validation"))
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
        + (("test_runs", "time"), ("alarms", "time"))
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
    """A workspace moved to another folder, and named in settings.json as the Settings page saves it, opens everything
    at the next start: every image decodes, every result reads back with its maps and the golden board it was judged
    against, the AI model loads, and a validation run on a folder inside the workspace finds its folder and images."""
    old = filled_ctx(tmp_path, tiny_model, "old_place")
    old_root = old.settings.root
    for table, column in STORED_PATHS:
        for r in old.db.query(f"SELECT {column} p FROM {table}"):
            assert r["p"] and not Path(r["p"]).is_absolute(), (table, r["p"])
    for r in old.db.query("SELECT results FROM test_runs"):
        assert all(not Path(x["image"]).is_absolute() for x in json.loads(r["results"])), r
    old.close()  # the database and the log file; an open file keeps the folder from moving on Windows
    new_root = tmp_path / "new_place"
    shutil.move(str(old_root), str(new_root))
    old.settings.save_keys({"workspace": str(new_root)})  # what the Settings page's Save writes; read at the next start

    ctx = AppContext(Settings.load())  # what main.py does at start-up
    assert ctx.settings.root == new_root
    ref, active, run = ctx.db.reference("TINY"), ctx.db.active_model("TINY"), ctx.db.latest_test_run("TINY")
    assert ref and active and run
    records = ctx.db.inspections(include_archived=True)
    images = [s["path"] for s in ctx.db.samples("TINY")] + [ref] + [x["image"] for x in run["results"]]
    images += [r[k] for r in records for k in ("image_path", "overlay_path")]
    assert len(images) == len(tiny_model.ctx.db.samples("TINY")) + 1 + 2 + 2 * len(records) and records
    assert Path(run["folder"]) == new_root / "validation" and Path(run["folder"]).is_dir()
    for p in images:
        assert Path(p).is_relative_to(new_root), p
        ctx.load_image(p)  # decodes, or raises AoiError
    for r in records:
        res = ctx.inspection_result(r["id"], with_maps=True)
        assert res is not None and res.anomaly_map is not None and res.compare and res.compare.diff_map is not None
        assert ctx.judged_reference(r["id"])[1] == "same"
    assert ctx.load_model("TINY") is not None
    assert ctx.inspect_file("TINY", images[0]).verdict in ("OK", "WARN", "NG")
    stored = json.dumps(ctx.db.query("SELECT * FROM inspections") + ctx.db.query("SELECT * FROM test_runs"))
    assert str(old_root) not in stored and str(new_root) not in stored
    ctx.close()


def test_req_set_001_a_workspace_saved_on_settings_waits_for_the_restart(
    qtbot: QtBot, ctx: AppContext, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Saving another workspace on Settings writes it to settings.json only (#170): until the restart the app keeps its
    database, log and every folder on the open workspace, so a sample imported meanwhile lands there, stored relative
    to it, and nothing is written to the new folder; a later save of other settings keeps the new folder in the file.
    Before, the folders moved at once while the database stayed, and the sample was stored by its absolute path."""
    told: list[str] = []
    monkeypatch.setattr(QMessageBox, "information", staticmethod(lambda _p, _t, text: told.append(text)))
    win = MainWindow(ctx)  # an empty workspace opens as Admin
    qtbot.addWidget(win)
    page = cast(SettingsPage, win.pages["Settings"])
    old, new = ctx.settings.root, tmp_path / "new_place"
    page.ws.setText(str(new))
    page.save()
    assert ctx.settings.root == old and Settings.load().workspace == str(new)
    assert told == ["Saved. Restart the app to switch the workspace."]
    page.lang.setCurrentIndex(page.lang.findData("ko"))
    page.save()  # another setting, later
    assert (Settings.load().workspace, Settings.load().language) == (str(new), "ko")
    src = tmp_path / "board.png"
    cv2.imwrite(str(src), np.full((32, 32, 3), 128, np.uint8))
    ctx.ensure_board_model(BOARD)
    ctx.import_samples(BOARD, [str(src)], "OK")
    (row,) = ctx.db.query("SELECT path FROM samples")
    assert row["path"].startswith("images/") and (old / row["path"]).is_file() and not new.exists()


def test_req_set_017_migration_0009_gives_runs_and_alarms_a_uuid(tmp_path: Path) -> None:
    """Migration 0009 rebuilds test_runs and alarms with uuid NOT NULL and unique: a row from before it keeps its id and
    every value and gets a UUID4 of its own, and an insert without one is refused. A run stored before it, with absolute
    paths, reads back as written."""
    path = tmp_path / "aoi.sqlite"
    conn = sqlite3.connect(path)
    files = mg.load_migrations()
    assert [m.number for m in mg.migrate(conn, files[:8])] == list(range(1, 9))
    at, folder = "2026-10-01T00:00:00+00:00", tmp_path / "elsewhere"
    results = json.dumps([{"image": str(folder / "ok" / "a.png"), "gt": "OK"}])
    run = (at, "B", "v1.0", str(folder), '{"TP": 1}', results)
    conn.executemany(
        "INSERT INTO test_runs(time, board_model, model_version, folder, metrics, results) VALUES (?,?,?,?,?,?)",
        [run, run],
    )
    alarms = [(at, "NG", "a", "AOI-INSP-003"), (at, "WARN", "b", None)]
    conn.executemany("INSERT INTO alarms(time, level, message, code) VALUES (?,?,?,?)", alarms)
    conn.commit()
    assert [m.number for m in mg.migrate(conn, files)] == list(range(9, len(files) + 1))
    kept = {
        "test_runs": ("time, board_model, model_version, folder, metrics, results", [(1, *run), (2, *run)]),
        "alarms": ("time, level, message, code", [(1, *alarms[0]), (2, *alarms[1])]),
    }
    for table, (columns, before) in kept.items():
        rows = conn.execute(f"SELECT uuid, id, {columns} FROM {table} ORDER BY id").fetchall()
        assert [tuple(r[1:]) for r in rows] == before, table
        assert all(UUID4.match(r[0]) for r in rows) and len({r[0] for r in rows}) == 2, rows
        with pytest.raises(sqlite3.IntegrityError, match="NOT NULL"):
            conn.execute(f"INSERT INTO {table}(time) VALUES (?)", (at,))
        with pytest.raises(sqlite3.IntegrityError, match="UNIQUE"):
            conn.execute(f"INSERT INTO {table}(time, uuid) VALUES (?, ?)", (at, rows[0][0]))
    assert conn.execute("SELECT model_uuid FROM test_runs").fetchall() == [(None,), (None,)]
    conn.close()
    db = Database(path, tmp_path / "ws")
    old = db.latest_test_run("B")
    assert old and old["folder"] == str(folder) and old["results"][0]["image"] == str(folder / "ok" / "a.png")
    db.close()


def test_req_set_017_model_file_names_its_registry_record(tmp_path: Path, trained_ctx: AppContext) -> None:
    """Training writes the UUID of the AI model's registry row into the .pt file's metadata before saving it, so an
    exported model file names its record; the file still loads weights only, and the training audit entry names the
    same UUID."""
    active = trained_ctx.active_model("TINY")
    assert active is not None and UUID4.match(active["uuid"])
    out = trained_ctx.export_model(active["id"], tmp_path / "exported.pt")
    assert AnomalyModel.load(out).meta["uuid"] == AnomalyModel.load(active["path"]).meta["uuid"] == active["uuid"]
    assert trained_ctx.audit_entries(action="model.train")[0]["object_uuid"] == active["uuid"]


def test_req_set_017_validation_exports_name_the_run_and_the_ai_model(
    qtbot: QtBot, trained_ctx: AppContext, synthetic_dataset: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A validation run on AI Model Test is stored with a UUID and the UUID of the AI model it tested; its CSV export
    keeps its columns and gains the run's UUID, the AI model version and its UUID at the end, and the PDF report names
    the run and the AI model by UUID."""
    win = _window(qtbot, trained_ctx)
    page = win.pages["AI Model Test"]
    page.folder = str(synthetic_dataset / "test" / "ng")
    page.run()
    qtbot.waitUntil(lambda: bool(page.rows) and page.btn_run.isEnabled(), timeout=60000)
    run, active = trained_ctx.db.latest_test_run(BOARD), trained_ctx.active_model(BOARD)
    assert run and active and UUID4.match(run["uuid"]) and run["model_uuid"] == active["uuid"]
    assert trained_ctx.board_status(BOARD).last_test == run["metrics"] == page.metrics  # Home's card reads the run
    out = tmp_path / "model_test.csv"
    monkeypatch.setattr(QFileDialog, "getSaveFileName", staticmethod(lambda *a, **k: (str(out), "CSV (*.csv)")))
    page.export_csv()
    with out.open(encoding="utf-8-sig", newline="") as f:
        exported = list(csv.DictReader(f))
    assert len(exported) == len(run["results"]) > 0
    assert list(exported[0]) == [*run["results"][0], "run_uuid", "model_version", "model_uuid"]
    assert {(r["run_uuid"], r["model_version"], r["model_uuid"]) for r in exported} == {
        (run["uuid"], active["version"], active["uuid"])
    }
    report = page._report_html()
    assert f"Validation run UUID: {run['uuid']}" in report and f"AI model UUID: {active['uuid']}" in report


def test_model_test_report_names_the_folder_its_results_came_from(
    qtbot: QtBot, trained_ctx: AppContext, synthetic_dataset: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """#174: a folder picked after a run, to run next, leaves the report on the run whose results it holds: the report
    names the folder that run tested and stored, not the folder picked last."""
    win = _window(qtbot, trained_ctx)
    page = win.pages["AI Model Test"]
    tested, picked = synthetic_dataset / "test" / "ng", synthetic_dataset / "test" / "ok"
    page.folder = str(tested)
    page.run()
    qtbot.waitUntil(lambda: bool(page.rows) and page.btn_run.isEnabled(), timeout=60000)
    monkeypatch.setattr(QFileDialog, "getExistingDirectory", staticmethod(lambda *a, **k: str(picked)))
    page.pick()
    run = trained_ctx.db.latest_test_run(BOARD)
    assert run and Path(run["folder"]) == tested
    assert f"Validation folder: {html.escape(str(tested))}<br>" in page._report_html()


def test_req_insp_012_checks_of_many_records_come_in_chunks(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """`checks_for_many` reads the checks of an export in IN queries of IN_CHUNK ids: every record's checks come back,
    in order, however many chunks it takes; a record without checks maps to [] and a repeated id is read once."""
    db = Database(tmp_path / "aoi.sqlite")
    monkeypatch.setattr(dbmod, "IN_CHUNK", 2)
    check = {"name": "a", "value": 1.0, "threshold": 2.0, "rule": "r", "verdict": "OK", "source": "AI", "explain": ""}
    check["region"] = "Board"
    ids = [db.add_inspection({"result": "OK"}, [], [check, {**check, "name": f"b{i}"}]) for i in range(5)]
    ids.append(db.add_inspection({"result": "OK"}, [], None))
    got = db.checks_for_many([*ids, ids[0]])
    assert got == {i: db.checks_for(i) for i in ids} and got[ids[-1]] == []
    assert [c["metric"] for c in got[ids[2]]] == ["a", "b2"]
