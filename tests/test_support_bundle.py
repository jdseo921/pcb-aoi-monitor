"""The support bundle (REQ-LOG-007): one zip, built by an Admin or from the command line, with the last 7 days of logs,
settings.json without secrets, the schema version, the heartbeat and its history, alerts, alarms and audit as CSV and
the PC's facts; no image unless asked, no user data REQ-USR-007 keeps out; audited."""

from __future__ import annotations

import csv
import io
import json
import zipfile
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from aoi.config import BUILD_LINE, Settings, default_workspace
from aoi.core import heartbeat, support
from aoi.core.services import AppContext
from aoi.errors import AoiError
from tests.conftest import TrainedModel, engineer, restored
from tests.test_evidence_policy import saved


def opened(path: Path) -> tuple[zipfile.ZipFile, dict[str, object]]:
    z = zipfile.ZipFile(path)
    return z, json.loads(z.read("manifest.json"))


def rows(z: zipfile.ZipFile, name: str) -> list[dict[str, str]]:
    return list(csv.DictReader(io.StringIO(z.read(name).decode("utf-8-sig"))))


def test_req_log_007_an_admins_bundle_holds_what_support_asks_first_and_no_secret_or_image(
    tmp_path: Path, tiny_model: TrainedModel, synthetic_dataset: Path, ng_board: Path
) -> None:
    ws = restored(tiny_model, tmp_path / "ws")
    station = default_workspace() / "settings.json"
    station.parent.mkdir(parents=True, exist_ok=True)
    station.write_text(json.dumps({"device": "cpu", "api_token": "t0p", "store_key": "k3y"}), encoding="utf-8")
    logs = ws / "logs"
    old = logs / f"aoi-{datetime.now(UTC) - timedelta(days=support.DAYS + 1):%Y-%m-%d}.jsonl"
    old.write_bytes(b'{"event": "app.start"}\n')  # older than the bundle's days
    ctx = engineer(AppContext(Settings(workspace=str(ws), device="cpu")))
    try:
        saved(ctx, synthetic_dataset, ng_board)
        ctx.alarm("WARN", "Drive nearly full", "AOI-LOG-005")
        ctx.heartbeat()
        with pytest.raises(AoiError):  # an Engineer may not
            ctx.support_bundle(tmp_path / "no.zip")
        ctx.set_user("admin")
        manifest = ctx.support_bundle(tmp_path / "out" / "support.zip")
        z, inside = opened(tmp_path / "out" / "support.zip")
        assert inside == json.loads(json.dumps(manifest, default=str))
        names = set(z.namelist())
        today = f"logs/aoi-{datetime.now(UTC):%Y-%m-%d}.jsonl"
        assert {today, f"logs/{heartbeat.ALERTS}", heartbeat.HEARTBEAT, "heartbeat-history.jsonl"} <= names
        assert {"settings.json", "schema_version.csv", "alarms.csv", "audit.csv"} <= names
        assert f"logs/{old.name}" not in names and not any(n.startswith("images/") for n in names)
        assert json.loads(z.read("settings.json")) == {"device": "cpu"}  # the token and the key stay out
        assert all(json.loads(line)["event"] == "heartbeat" for line in z.read("heartbeat-history.jsonl").splitlines())
        assert z.read("heartbeat-history.jsonl") and int(rows(z, "schema_version.csv")[-1]["number"]) > 0
        assert "Drive nearly full" in [r["message"] for r in rows(z, "alarms.csv")]
        facts = manifest["facts"]
        assert facts["app"] == BUILD_LINE and facts["torch"] and facts["free_bytes"] > 0 and facts["cpu_count"]
        assert manifest["missing"] == [] and not any("users" in n or n.endswith(".png") for n in names)
        entry = ctx.audit_entries(action="support.bundle")[0]
        assert (
            entry["after"]["file"] == "support.zip" and entry["after"]["images"] is False and entry["role"] == "Admin"
        )

        ctx.support_bundle(tmp_path / "with.zip", images=True)  # ticked: the newest records' overlays
        z, _ = opened(tmp_path / "with.zip")
        assert [n for n in z.namelist() if n.startswith("images/")]
    finally:
        ctx.close()


def test_req_log_007_the_command_line_writes_the_bundle_for_a_station_whose_window_will_not_open(
    tmp_path: Path, tiny_model: TrainedModel
) -> None:
    ws = restored(tiny_model, tmp_path / "ws")
    assert support.main([]) == 2 and support.main([str(tmp_path / "a.zip"), str(tmp_path / "none")]) == 2
    assert support.main([str(tmp_path / "cli.zip"), str(ws)]) == 0
    _, manifest = opened(tmp_path / "cli.zip")
    assert "audit.csv" in manifest["files"] and manifest["not_read"] == {}  # type: ignore[operator]
    ctx = AppContext(Settings(workspace=str(ws), device="cpu"))
    try:
        entry = ctx.audit_entries(action="support.bundle")[0]
        assert entry["reason"] == "command line" and entry["user_uuid"] is None
    finally:
        ctx.close()


def test_req_log_007_secret_looking_keys_stay_out_at_any_depth_and_every_path_reads(tmp_path: Path) -> None:
    entry = {"key_id": "k1", "store_key": "x", "rows": [{"pin_hash": "y", "name": "kim"}], "api_token": "z"}
    assert support._clean(entry) == {"key_id": "k1", "rows": [{"name": "kim"}]}

    class Posix:  # a path as Windows resolves it, on any system
        def __init__(self, text: str) -> None:
            self.text = text

        def resolve(self) -> Posix:
            return self

        def as_posix(self) -> str:
            return self.text

    for given, uri in (
        ("C:/AOI WS/aoi.sqlite", "file:/C:/AOI%20WS/aoi.sqlite?mode=ro"),  # SQLite drops the / before a drive
        ("//server/share/aoi.sqlite", "file:////server/share/aoi.sqlite?mode=ro"),  # file://server/… is refused
    ):
        assert support._uri(Posix(given)) == uri  # type: ignore[arg-type]
