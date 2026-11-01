"""The station's heartbeat (REQ-SET-024; docs/operations/metrics.md): `heartbeat.json` in the workspace, rewritten whole
every BEAT_EVERY_S by a thread the context owns, `logs/alerts.jsonl` with one line per alarm for the company's tools to
tail, and the marker that tells the next start whether this run closed cleanly. No Qt here.
"""

from __future__ import annotations

import json
import math
import os
import threading
import time
from collections import deque
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from ..data import atomic

BEAT_EVERY_S = 60
HOUR_S = 3600
HEARTBEAT = "heartbeat.json"  # in the workspace folder
ALERTS = "alerts.jsonl"  # in logs/
RUNNING = "aoi.running"  # in the workspace folder while the app runs; a start that finds it follows a run not closed


class Pulse:
    """The boards this run saved in the last hour, and the board model, AI model and recipe revision of the last."""

    def __init__(self) -> None:
        self._boards: deque[tuple[float, str, float]] = deque()  # (time.time(), verdict, ms to a verdict)
        self._lock = threading.Lock()  # boards are saved on the pool thread, the beat reads on its own
        self.last: dict[str, Any] = {}

    def add(self, verdict: str, ms: float, last: dict[str, Any], now: float | None = None) -> None:
        with self._lock:
            self._boards.append((time.time() if now is None else now, verdict, ms))
            self.last = {"time": datetime.now(UTC).isoformat(timespec="seconds")} | last

    def hour(self, now: float) -> dict[str, Any]:
        """The last hour's boards, NG boards, and mean and p95 time to a verdict in ms (None with no board)."""
        with self._lock:
            while self._boards and self._boards[0][0] < now - HOUR_S:
                self._boards.popleft()
            boards = list(self._boards)
        ms = sorted(b[2] for b in boards)
        p95 = round(ms[max(0, math.ceil(0.95 * len(ms)) - 1)], 1) if ms else None
        mean = round(sum(ms) / len(ms), 1) if ms else None
        return {
            "boards": len(boards),
            "ng": sum(b[1] == "NG" for b in boards),
            "verdict_ms_mean": mean,
            "verdict_ms_p95": p95,
        }


def write(root: Path, fields: dict[str, Any]) -> None:
    """Rewrite heartbeat.json whole (a cut leaves the last beat), so a reader never sees half a beat. Windows refuses
    the rename while a reader holds the file open (a monitoring tool, the support bundle): tried again, briefly."""
    for wait in (0.1, 0.5, None):
        try:
            atomic.write_text(root / HEARTBEAT, json.dumps(fields, indent=1, default=str) + "\n")
            return
        except PermissionError:
            if wait is None:
                raise
            time.sleep(wait)


def alert(logs: Path, fields: dict[str, Any]) -> None:
    """Append one alarm to logs/alerts.jsonl, one JSON object a line."""
    logs.mkdir(parents=True, exist_ok=True)
    with open(logs / ALERTS, "a", encoding="utf-8") as f:
        f.write(json.dumps(fields, ensure_ascii=False, default=str) + "\n")


def started(root: Path) -> bool:
    """Write the running marker; True when the run before left one, which a clean close removes (a kill does not)."""
    marker = root / RUNNING
    unclean = marker.exists()
    atomic.write_text(marker, json.dumps({"pid": os.getpid(), "time": datetime.now(UTC).isoformat()}) + "\n")
    return unclean


def closed(root: Path) -> None:
    (root / RUNNING).unlink(missing_ok=True)
