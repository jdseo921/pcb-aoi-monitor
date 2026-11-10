"""The heartbeat, alerts.jsonl and the clean-exit marker (REQ-SET-024; docs/operations/metrics.md)."""

from __future__ import annotations

import functools
import json
import sqlite3
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from aoi.config import APP_LABEL, Settings
from aoi.core import heartbeat
from aoi.core.services import FALSE_CALL, AppContext
from aoi.data.errors import WorkspaceError
from tests.conftest import TrainedModel, engineer, log_rows, restored
from tests.run_pinned import PINNED_DRIVE
from tests.test_evidence_policy import saved


@pytest.fixture
def ctx(tmp_path: Path, tiny_model: TrainedModel) -> Iterator[AppContext]:
    opened = engineer(AppContext(Settings(workspace=str(restored(tiny_model, tmp_path / "ws")), device="cpu")))
    yield opened
    opened.close()


def test_req_set_024_the_heartbeat_counts_the_last_hours_boards_and_names_the_last(
    ctx: AppContext, synthetic_dataset: Path, ng_board: Path
) -> None:
    deadline = time.monotonic() + 30
    while not (ctx.settings.root / heartbeat.HEARTBEAT).exists():  # the start's beat, then none for BEAT_EVERY_S
        assert time.monotonic() < deadline
        time.sleep(0.05)
    ok, ng = saved(ctx, synthetic_dataset, ng_board)
    ctx.review_result(int(str(ng["id"])), FALSE_CALL, "a speck of dust")
    beat = ctx.heartbeat()
    assert json.loads((ctx.settings.root / heartbeat.HEARTBEAT).read_text(encoding="utf-8")) == beat  # as written
    assert beat["pid"] > 0 and beat["app_version"] == APP_LABEL and beat["uptime_s"] >= 0
    hour = beat["last_hour"]
    assert hour["boards"] == 2 and hour["ng"] == 1 and hour["false_calls"] == 1
    assert hour["verdict_ms_p95"] >= hour["verdict_ms_mean"] > 0
    assert (
        beat["last_inspection"]["board_model"] == "TINY" and beat["last_inspection"]["ai_model"] == ng["model_version"]
    )
    assert beat["last_inspection"]["recipe_rev"] == ng["recipe_rev"]
    assert beat["free_bytes"] == PINNED_DRIVE.free and beat["wal_bytes"] >= 0
    pulse = heartbeat.Pulse()  # an hour later the boards no longer count
    pulse.add("NG", 10.0, {}, now=time.time() - heartbeat.HOUR_S - 1)
    assert pulse.hour(time.time()) == {"boards": 0, "ng": 0, "verdict_ms_mean": None, "verdict_ms_p95": None}


def test_req_set_024_the_heartbeat_is_rewritten_on_the_contexts_timer(
    tmp_path: Path, tiny_model: TrainedModel, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(heartbeat, "BEAT_EVERY_S", 0.05)
    ctx = AppContext(Settings(workspace=str(restored(tiny_model, tmp_path / "ws")), device="cpu"))
    beat = ctx.settings.root / heartbeat.HEARTBEAT
    try:
        deadline = time.monotonic() + 30
        for n in range(2):  # the start's beat; then, deleted, the next beat writes it again
            while not beat.exists():
                assert time.monotonic() < deadline, "no beat"
                time.sleep(0.05)
            if n == 0:
                beat.unlink()
        assert json.loads(beat.read_text(encoding="utf-8"))["pid"] > 0
    finally:
        ctx.close()
    assert not ctx._beating.is_alive()


def test_req_set_024_a_clean_close_is_logged_and_a_start_after_a_kill_says_so(
    tmp_path: Path, tiny_model: TrainedModel
) -> None:
    ws = restored(tiny_model, tmp_path / "ws")
    (ws / heartbeat.RUNNING).unlink(missing_ok=True)  # copied from the session's workspace, which is still open
    ctx = AppContext(Settings(workspace=str(ws), device="cpu"))
    marker = (ws / heartbeat.RUNNING).read_text(encoding="utf-8")  # while it runs
    ctx.close()
    assert not (ws / heartbeat.RUNNING).exists() and "app.close" in [r["event"] for r in log_rows(ws / "logs")]
    AppContext(Settings(workspace=str(ws), device="cpu")).close()
    assert "app.not_closed_cleanly" not in [r["event"] for r in log_rows(ws / "logs")]
    (ws / heartbeat.RUNNING).write_text(marker, encoding="utf-8")  # what a kill, a crash or a power cut leaves
    AppContext(Settings(workspace=str(ws), device="cpu")).close()
    assert [r["event"] for r in log_rows(ws / "logs")].count("app.not_closed_cleanly") == 1


def test_req_set_024_every_alarm_is_appended_to_alerts_jsonl(
    ctx: AppContext, synthetic_dataset: Path, ng_board: Path
) -> None:
    ctx.alarm("WARN", "Drive nearly full", "AOI-LOG-005")
    saved(ctx, synthetic_dataset, ng_board)  # an NG board's alarm, stored with its record
    lines = (ctx.settings.root / "logs" / heartbeat.ALERTS).read_text(encoding="utf-8").splitlines()
    alerts = [json.loads(line) for line in lines]
    assert [(a["level"], a["code"]) for a in alerts][0] == ("WARN", "AOI-LOG-005") and alerts[0]["text"]
    assert alerts[-1]["level"] == "NG" and all(a["time"].endswith("+00:00") for a in alerts)


def test_req_set_024_every_alarm_reaches_the_log_and_alerts_jsonl_once_a_failed_shift_checks_too(
    ctx: AppContext, synthetic_dataset: Path, ng_board: Path
) -> None:
    """A failed shift check stored its NG alarm AOI-INSP-016 in the database alone, so `logs/alerts.jsonl` and the log
    never had it, unlike every other alarm (review finding DAT-2). Each alarm now writes one line to each, whichever
    way it is stored: raised by `alarm`, an NG board's stored with its record, a failed shift check's with the check.
    Lines the copied workspace held are left out, and so are alarms the app raises meanwhile (a drive filling, say):
    this test's are told by their code, `alarm`'s by its text."""
    logs, raised = ctx.settings.root / "logs", "Raised by this test"

    def ours(rows: list[dict[str, Any]], level: str) -> list[tuple[str, str | None]]:
        """The lines of this test's alarms, as (level, code)."""
        codes = ("AOI-INSP-003", "AOI-INSP-016")
        return [(r[level], r["code"]) for r in rows if r["code"] in codes or r["text"] == raised]

    def written() -> tuple[list[tuple[str, str | None]], list[tuple[str, str | None]]]:
        """Each line of `alerts.jsonl`, and each `alarm` line of the log, of this test's alarms."""
        alerts = logs / heartbeat.ALERTS
        lines = alerts.read_text(encoding="utf-8").splitlines() if alerts.exists() else []
        logged = [r for r in log_rows(logs) if r["event"] == "alarm"]
        return ours([json.loads(line) for line in lines], "level"), ours(logged, "alarm_level")

    before = written()
    ctx.alarm("WARN", raised, "AOI-LOG-005")
    saved(ctx, synthetic_dataset, ng_board)  # an NG board's alarm AOI-INSP-003, stored with its record
    ok_master = ctx.master_samples("TINY")[0]
    ctx.update_sample(int(ok_master["id"]), "NG", "Solder Bridge")  # the known-OK board is now expected NG
    assert not ctx.run_shift_check("TINY")["check"]["passed"]
    assert ctx.alarms()[0]["code"] == "AOI-INSP-016"  # the alarm list, as before
    each = [("WARN", "AOI-LOG-005"), ("NG", "AOI-INSP-003"), ("NG", "AOI-INSP-016")]
    alerted, logged = (after[len(old) :] for after, old in zip(written(), before, strict=True))
    assert alerted == each, "alerts.jsonl"
    assert logged == each, "the log"


@pytest.mark.parametrize("refused_in", ["_archive_old", "_ensure_recipe"])
def test_req_set_024_a_refused_start_leaves_the_marker_as_it_found_it(
    tmp_path: Path, tiny_model: TrainedModel, monkeypatch: pytest.MonkeyPatch, refused_in: str
) -> None:
    """A start refused once its database was open (another program holding the database's lock, AOI-SET-012) deleted
    the marker a killed run had left, so the next start no longer said that run had not closed cleanly (review
    finding DAT-3). A refused start now leaves the marker as it found it, whichever start-up step meets the lock: the
    first that writes (`_archive_old`) or the last before the marker is written (`_ensure_recipe`). None stays none,
    and the next good start says so of the killed run."""
    ws = restored(tiny_model, tmp_path / "ws")
    (ws / heartbeat.RUNNING).unlink(missing_ok=True)  # copied from the session's workspace, which is still open
    monkeypatch.setattr(sqlite3, "connect", functools.partial(sqlite3.connect, timeout=0.2))  # not SQLite's 5 s wait
    killed = '{"pid": 1, "time": "2026-11-01T00:00:00+00:00"}\n'  # what a kill, a crash or a power cut leaves
    step = getattr(AppContext, refused_in)
    for found in (None, killed):
        if found is not None:
            (ws / heartbeat.RUNNING).write_text(found, encoding="utf-8")
        other = sqlite3.connect(ws / "aoi.sqlite", isolation_level=None)

        def locked(self: AppContext, *args: object, held: sqlite3.Connection = other) -> None:
            """The step, run once another program takes the database's lock: before the first, as if from the start."""
            held.execute("BEGIN IMMEDIATE")
            step(self, *args)

        try:
            with monkeypatch.context() as m, pytest.raises(WorkspaceError) as refused:
                m.setattr(AppContext, refused_in, locked)
                AppContext(Settings(workspace=str(ws), device="cpu"))
        finally:
            other.close()
        assert refused.value.code == "AOI-SET-012"
        marker = ws / heartbeat.RUNNING
        assert (marker.read_text(encoding="utf-8") if marker.exists() else None) == found, "the marker as found"
    AppContext(Settings(workspace=str(ws), device="cpu")).close()
    assert [r["event"] for r in log_rows(ws / "logs")].count("app.not_closed_cleanly") == 1
