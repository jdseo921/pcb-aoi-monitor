"""REQ-LOG-004, log part (S12b): a JSON-lines log with the required fields, daily files and no images or secrets."""

from __future__ import annotations

import json
import logging
import shutil
from datetime import UTC, datetime
from pathlib import Path

import numpy as np

from aoi import logging_setup
from aoi.config import APP_VERSION, Settings
from aoi.core.services import AppContext
from tests.conftest import TrainedModel, log_rows, restored

DAY_1 = datetime(2026, 10, 1, 5, 5, 0, tzinfo=UTC)
DAY_2 = datetime(2026, 10, 2, 0, 0, 1, tzinfo=UTC)


def lines(path: Path) -> list[dict[str, object]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def test_req_log_004_log_lines_are_json_with_fields(tmp_path: Path) -> None:
    log = logging_setup.setup(tmp_path, clock=lambda: DAY_1)
    log.info("unit.test", extra={"board_model": "TINY", "inspection_id": 7, "user_uuid": "0" * 36})
    try:
        raise ValueError("boom")
    except ValueError:
        log.error("unit.failed", exc_info=True)
    rows = lines(tmp_path / "logs" / "aoi-2026-10-01.jsonl")
    assert rows[0] == {
        "time": "2026-10-01T05:05:00.000+00:00",
        "level": "INFO",
        "module": "aoi",
        "event": "unit.test",
        "app_version": APP_VERSION,
        "board_model": "TINY",
        "inspection_id": 7,
        "user_uuid": "0" * 36,
    }
    assert rows[1]["level"] == "ERROR" and "ValueError: boom" in str(rows[1]["trace"])
    assert logging.getLogger("aoi.data.migrate").getEffectiveLevel() == logging.INFO  # children reach the same file


def test_req_log_004_rotates_daily(tmp_path: Path) -> None:
    today = [DAY_1]
    log = logging_setup.setup(tmp_path, clock=lambda: today[0])
    log.info("first")
    today[0] = DAY_2
    log.info("second")
    files = sorted(p.name for p in (tmp_path / "logs").iterdir())
    assert files == ["aoi-2026-10-01.jsonl", "aoi-2026-10-02.jsonl"]
    assert [r["event"] for r in lines(tmp_path / "logs" / files[0])] == ["first"]
    assert [r["event"] for r in lines(tmp_path / "logs" / files[1])] == ["second"]


def test_req_log_004_no_image_data_in_log(tmp_path: Path) -> None:
    log = logging_setup.setup(tmp_path, clock=lambda: DAY_1)
    image = np.full((4, 4, 3), 200, np.uint8)
    log.info(
        "scrubbed",
        extra={
            "image": image,
            "raw": b"\x89PNG secret bytes",
            "password": "hunter2",
            "nested": {"api_token": "abc", "count": 1, "pixels": image},
            "paths": ["a.png", b"\x00\x01"],
        },
    )
    text = (tmp_path / "logs" / "aoi-2026-10-01.jsonl").read_text(encoding="utf-8")
    assert "hunter2" not in text and "PNG" not in text and "abc" not in text and "200" not in text
    row = lines(tmp_path / "logs" / "aoi-2026-10-01.jsonl")[0]
    assert row["image"] == "<array (4, 4, 3) omitted>" and row["raw"] == "<17 bytes omitted>"
    assert row["nested"] == {"count": 1, "pixels": "<array (4, 4, 3) omitted>"} and "password" not in row
    assert row["paths"] == ["a.png", "<2 bytes omitted>"]


def test_req_log_004_app_events_reach_the_workspace_log(tmp_path: Path, tiny_model: TrainedModel) -> None:
    ws = tmp_path / "ws"
    restored(tiny_model, ws, shutil.ignore_patterns("logs"))
    ctx = AppContext(Settings(workspace=str(ws), device="cpu"))
    ctx.inspect_file("TINY", ctx.db.samples("TINY", "OK")[0]["path"])
    rows = log_rows(ws / "logs")
    events = [r["event"] for r in rows]
    assert events[0] == "app.start" and "inspection.saved" in events
    saved = next(r for r in rows if r["event"] == "inspection.saved")
    assert saved["board_model"] == "TINY" and saved["verdict"] in ("OK", "WARN", "NG") and saved["module"] == "aoi"
    assert "schema.migrated" in [r["event"] for r in log_rows(tiny_model.ctx.settings.root / "logs")]
