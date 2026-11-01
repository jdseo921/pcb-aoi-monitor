"""The heartbeat, alerts.jsonl and the clean-exit marker (REQ-SET-024; docs/operations/metrics.md)."""

from __future__ import annotations

import json
import time
from collections.abc import Iterator
from pathlib import Path

import pytest

from aoi.config import APP_LABEL, Settings
from aoi.core import heartbeat
from aoi.core.services import FALSE_CALL, AppContext
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
