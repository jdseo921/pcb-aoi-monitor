"""Retention on a timer (REQ-LOG-010; ADR 0024 D1, D20, D21), on a synthetic 30-day workspace: records judged OK and
NG on each of the last 30 days, a log file per day and one archived 95 days ago, 5 migration backups, validation runs
old and new, and files no record names. One sweep shrinks it to the policy; the audit shows what went."""

from __future__ import annotations

import gzip
import os
import sqlite3
import time
from collections.abc import Callable, Iterator
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pytest
from PySide6.QtWidgets import QMessageBox
from pytestqt.qtbot import QtBot

from aoi.config import Settings
from aoi.core import retention
from aoi.core.imaging import preview_path
from aoi.core.services import AppContext
from tests.conftest import TrainedModel, engineer, log_rows, restored
from tests.test_evidence_policy import ok_board
from tests.test_req_done_in_v01 import BOARD, _window

DAYS = 30
OLD = time.time() - 2 * retention.ORPHAN_AGE_S  # a file's time old enough to be an orphan


@pytest.fixture
def ctx(tmp_path: Path, tiny_model: TrainedModel) -> Iterator[AppContext]:
    opened = engineer(AppContext(Settings(workspace=str(restored(tiny_model, tmp_path / "ws")), device="cpu")))
    swept(opened)  # its sweep at start, on its timer's thread, is over: the next is an hour away
    yield opened
    opened.close()


def swept(ctx: AppContext, until: Callable[[], bool] = lambda: True) -> None:
    deadline = time.monotonic() + 30
    while (ctx.last_sweep is None or not until()) and time.monotonic() < deadline:
        time.sleep(0.05)


def ago(days: int) -> str:
    return (datetime.now(UTC) - timedelta(days=days, hours=1)).isoformat(timespec="seconds")  # past a cutoff of `days`


def day(days: int) -> date:
    return (datetime.now(UTC) - timedelta(days=days)).date()  # as a log file or a backup is named by


def thirty_days(ctx: AppContext, synthetic_dataset: Path, ng_board: Path) -> dict[str, Path]:
    """The workspace of a station that ran DAYS days: what each sweep must keep or remove, by name."""
    root, results, insp = ctx.settings.root, ctx.settings.results_dir, ctx.inspector(BOARD)
    for n in range(0, DAYS, 3):  # an OK and an NG board every third day, saved as today's and dated back
        ctx.log_result(BOARD, *ok_board(ctx, insp, synthetic_dataset), insp)
        ctx.log_result(BOARD, str(ng_board), insp.inspect(ctx.load_image(str(ng_board))), insp)
        with sqlite3.connect(ctx.settings.db_path) as db:  # the two just saved, the newest
            db.execute("UPDATE inspections SET time=? WHERE id > (SELECT max(id) - 2 FROM inspections)", [ago(n)])
    for n in range(1, DAYS + 1):
        (root / "logs" / f"aoi-{day(n):%Y-%m-%d}.jsonl").write_text('{"event": "app.start"}\n', encoding="utf-8")
    (root / "logs" / retention.ARCHIVE).mkdir(exist_ok=True)  # made by the sweep at start
    gone_log = root / "logs" / retention.ARCHIVE / f"aoi-{day(95):%Y-%m-%d}.jsonl.gz"
    gone_log.write_bytes(gzip.compress(b"{}\n"))
    for n in range(5):  # oldest first by the time in the name, whatever the versions say
        (root / f"aoi.sqlite.bak-{n:04d}-to-{n + 1:04d}-{day(50 - n):%Y%m%d}T000000Z").write_bytes(b"copy")
    with sqlite3.connect(ctx.settings.db_path) as db:
        runs = [(ago(100), "old-run"), (ago(5), "new-run")]
        db.executemany("INSERT INTO test_runs(time, uuid) VALUES(?, ?)", runs)
    places = {name: results / "test_runs" / name / "0001.png" for name in ("old-run", "new-run", "no-run")}
    strays = results / "2026-10-01"  # an OK board's files no record names, and an NG board's (a restored database)
    places |= {"stray": strays / "b_1_OK.jpg", "young stray": strays / "b_2_OK.jpg", "NG stray": strays / "b_3_NG.png"}
    for name, p in places.items():
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(b"png")
        if name != "young stray":
            os.utime(p.parent if "run" in name else p, (OLD, OLD))
    places["archived log"] = gone_log
    return places


def test_req_log_010_one_sweep_shrinks_a_30_day_workspace_to_the_policy_and_the_audit_shows_what_went(
    ctx: AppContext, synthetic_dataset: Path, ng_board: Path
) -> None:
    places = thirty_days(ctx, synthetic_dataset, ng_board)
    logs, root, results = ctx.settings.root / "logs", ctx.settings.root, ctx.settings.results_dir
    first = ctx.sweep_retention()  # no Admin has confirmed the policy: only OK maps go, logs are packed
    assert first["ok_maps"] == 7  # the OK boards of days 9 to 27, past map_retention_days_ok (7)
    assert first["logs_gzipped"] == DAYS - retention.LOG_GZIP_DAYS + 1 and first["logs_archived"] == 1
    assert first["logs_deleted"] == first["backups"] == first["test_runs"] == first["orphans"] == 0
    assert all(p.exists() for p in places.values()) and len(list(root.glob("aoi.sqlite.bak-*"))) == 5
    assert min(p.name for p in logs.glob("aoi-*.jsonl")) == f"aoi-{day(6):%Y-%m-%d}.jsonl"  # 7 days old: gzipped
    assert gzip.decompress((logs / f"aoi-{day(10):%Y-%m-%d}.jsonl.gz").read_bytes()) == b'{"event": "app.start"}\n'

    for p in results.rglob("*"):  # every record's files as old as the strays: only what no record names may go
        if p.name != "b_2_OK.jpg":
            os.utime(p, (OLD, OLD))
    ctx.set_user("admin")
    ctx.confirm_retention()
    second = ctx.sweep_retention()
    went = {"logs_deleted": 1, "backups": 2, "test_runs": 2, "orphans": 1}
    assert second == dict.fromkeys(retention.COUNTS, 0) | went
    assert {name for name, p in places.items() if p.exists()} == {"new-run", "young stray", "NG stray"}
    assert sorted(p.name[15:19] for p in root.glob("aoi.sqlite.bak-*")) == ["0002", "0003", "0004"]  # the newest 3
    rows = ctx.inspections(board_model=BOARD, include_archived=True)
    named = [root / r[k] for r in rows for k in ("overlay_path", "diff_map_path", "ai_map_path") if r[k]]
    assert all(p.is_file() for p in named + [preview_path(p) for p in named if p.suffix == ".jpg"])  # all it names
    confirmed = ctx.retention_confirmed()
    assert confirmed is not None and confirmed["role"] == "Admin"
    sweeps = ctx.audit_entries(action="retention.sweep")  # newest first
    assert [e["after"] for e in sweeps] == [second, first] and sweeps[0]["reason"].endswith(confirmed["uuid"])
    assert sweeps[1]["reason"] is None and sweeps[0]["user_uuid"] is None  # a system action
    assert not any(ctx.sweep_retention().values()) and len(ctx.audit_entries(action="retention.sweep")) == 2


def test_req_log_010_the_context_sweeps_at_start_and_on_its_timer_until_it_closes(
    tmp_path: Path, tiny_model: TrainedModel, monkeypatch: pytest.MonkeyPatch
) -> None:
    ws = restored(tiny_model, tmp_path / "ws")
    old = ws / "logs" / f"aoi-{day(10):%Y-%m-%d}.jsonl"
    old.write_text("{}\n", encoding="utf-8")
    monkeypatch.setattr(retention, "SWEEP_EVERY_S", 0.05)
    ctx = AppContext(Settings(workspace=str(ws), device="cpu"))
    try:
        swept(ctx, lambda: not old.exists())
        assert ctx.last_sweep is not None and ctx.last_sweep["logs_gzipped"] == 1 and not old.exists()  # at start
        late = ws / "logs" / f"aoi-{day(11):%Y-%m-%d}.jsonl"
        late.write_text("{}\n", encoding="utf-8")
        swept(ctx, lambda: not late.exists())  # the timer's next sweep packs it
        assert not late.exists() and late.with_name(late.name + ".gz").is_file()
    finally:
        ctx.close()
    assert not ctx._retention.is_alive()  # the timer stops with the context
    assert sum(r["event"] == "retention.swept" for r in log_rows(ws / "logs")) >= 2


def test_req_log_010_settings_shows_the_last_sweep_and_an_admin_confirms_the_policy(
    qtbot: QtBot, ctx: AppContext, monkeypatch: pytest.MonkeyPatch
) -> None:
    ctx.set_user("admin")
    win = _window(qtbot, ctx, "Admin")
    page = win.pages["Settings"]
    win.navigate("Settings")
    assert page.sweep.text().startswith("Last retention sweep: ") and "Policy not confirmed" in page.sweep.text()
    monkeypatch.setattr(QMessageBox, "question", staticmethod(lambda *a, **k: QMessageBox.StandardButton.No))
    page.confirm_retention()
    assert ctx.retention_confirmed() is None
    monkeypatch.setattr(QMessageBox, "question", staticmethod(lambda *a, **k: QMessageBox.StandardButton.Yes))
    page.confirm_retention()
    assert ctx.retention_confirmed() is not None and "Policy confirmed" in page.sweep.text()
