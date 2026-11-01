"""The start-up self-check (REQ-SET-024): one coded alarm per failure, AOI-SET-020 to -023, each in alerts.jsonl too."""

from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path

import pytest

from aoi.config import Settings
from aoi.core import heartbeat
from aoi.core.services import AppContext
from aoi.data import atomic, credentials
from aoi.data.db import Database
from tests.conftest import TrainedModel, engineer, log_rows, restored
from tests.test_evidence_policy import saved

CODES = ("AOI-SET-020", "AOI-SET-021", "AOI-SET-022", "AOI-SET-023")


def done(ws: Path) -> int:
    return [r["event"] for r in log_rows(ws / "logs")].count("self_check.done")


def started(ctx: AppContext, before: int) -> None:
    """Wait for the start's own check, on the heartbeat's thread, to end: `before` were logged before it."""
    deadline = time.monotonic() + 30
    while done(ctx.settings.root) <= before:
        assert time.monotonic() < deadline
        time.sleep(0.05)


def checks(ctx: AppContext) -> list[tuple[str, str]]:
    return [(a["level"], a["code"]) for a in reversed(ctx.alarms()) if a["code"] in CODES]


def test_req_set_024_a_whole_workspace_passes_the_self_check_with_no_alarm(
    tmp_path: Path, tiny_model: TrainedModel
) -> None:
    ws = restored(tiny_model, tmp_path / "ws")
    before, ctx = done(ws), AppContext(Settings(workspace=str(ws), device="cpu"))
    try:
        started(ctx, before)
        found = ctx.self_check()
        assert found["database_problems"] == found["missing_files"] == found["temp_files_left"] == 0
        assert found["stores_without_key"] == [] and found["free_bytes"] > 0 and checks(ctx) == []
    finally:
        ctx.close()


def test_req_set_024_each_failure_of_the_self_check_is_one_coded_alarm(
    tmp_path: Path,
    tiny_model: TrainedModel,
    synthetic_dataset: Path,
    ng_board: Path,
    keys: credentials.MemoryCredentials,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ws = restored(tiny_model, tmp_path / "ws")
    ctx = engineer(AppContext(Settings(workspace=str(ws), device="cpu")))
    _, ng = saved(ctx, synthetic_dataset, ng_board)
    for store in ctx.stores():  # a station that never got the store's key
        keys.delete(credentials.STORE_PREFIX + store["uuid"])
    ctx.close()
    Path(str(ng["overlay_path"])).unlink()  # deleted by hand
    monkeypatch.setattr(Database, "quick_check", lambda self: ["row 7 missing from index sample_hash"])
    left = (ws / "held.tmp", "held open by another program")
    monkeypatch.setattr(atomic, "sweep_temp_files", lambda folder: (0, [left, left]))
    before, ctx = done(ws), AppContext(Settings(workspace=str(ws), device="cpu"))
    try:
        started(ctx, before)
        assert checks(ctx) == [("ERROR", CODES[0]), ("ERROR", CODES[1]), ("WARN", CODES[2]), ("WARN", CODES[3])]
        found = ctx.self_check()  # again: what it found, and the same alarms
        assert found["database_problems"] == 1 and found["missing_files"] == 1 and found["temp_files_left"] == 2
        assert len(found["stores_without_key"]) == 1
        alerts = (ws / "logs" / heartbeat.ALERTS).read_text(encoding="utf-8").splitlines()
        assert [json.loads(a)["code"] for a in alerts][-8:] == list(CODES) * 2
        assert "1 overlay or map files" in next(a["message"] for a in ctx.alarms() if a["code"] == "AOI-SET-022")
    finally:
        ctx.close()


def test_req_set_024_a_check_that_fails_is_logged_and_the_others_still_run(
    tmp_path: Path, tiny_model: TrainedModel, monkeypatch: pytest.MonkeyPatch
) -> None:
    ws = restored(tiny_model, tmp_path / "ws")

    def busy(self: Database) -> list[str]:
        raise sqlite3.OperationalError("database is locked")

    monkeypatch.setattr(Database, "quick_check", busy)
    before, ctx = done(ws), AppContext(Settings(workspace=str(ws), device="cpu"))
    try:
        started(ctx, before)
        found = ctx.self_check()
        assert found["failed"] == ["database"] and found["missing_files"] == 0 and found["free_bytes"] > 0
        assert "self_check.step_failed" in [r["event"] for r in log_rows(ws / "logs")]
    finally:
        ctx.close()
