"""The disk guard (REQ-LOG-006): the workspace drive's free space is measured at start and before each save; it alarms
at 80 % used, and at 95 % an OK board keeps its record but not its overlay and maps.

The drive is a bounded temporary filesystem filled with a real file to each threshold: a tmpfs of CAPACITY bytes where
the test may mount one (root on Linux), else a folder whose files count against CAPACITY.
"""

from __future__ import annotations

import contextlib
import csv
import os
import sqlite3
import subprocess
import sys
from collections.abc import Iterator
from pathlib import Path
from unittest import mock

import pytest
from PySide6.QtWidgets import QFileDialog, QMessageBox
from pytestqt.qtbot import QtBot

from aoi.config import Settings
from aoi.core import disk
from aoi.core.imaging import list_images
from aoi.core.inspector import InspectionResult, Inspector
from aoi.core.services import AppContext
from aoi.data.db import Database
from aoi.ui import theme
from tests.conftest import TrainedModel, engineer, listed, log_rows, restored
from tests.test_req_done_in_v01 import BOARD, _window

CAPACITY = 128 * 2**20
SYSTEM_USAGE = disk.usage  # the system's own count, before conftest pins every test's drive


@pytest.fixture
def drive(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    root = tmp_path / "drive"
    root.mkdir()
    mount = ["mount", "-t", "tmpfs", "-o", f"size={CAPACITY}", "tmpfs", str(root)]
    mounted = sys.platform == "linux" and os.geteuid() == 0 and subprocess.run(mount, check=False).returncode == 0
    total = lambda: sum(p.stat().st_size for p in root.rglob("*") if p.is_file())  # noqa: E731  (files, not mounted)
    counted = lambda f: disk.Usage(CAPACITY, total(), CAPACITY - total())  # noqa: E731
    monkeypatch.setattr(disk, "usage", SYSTEM_USAGE if mounted else counted)
    yield root
    if mounted:
        subprocess.run(["umount", "-l", str(root)], check=True)


@pytest.fixture
def ctx(drive: Path, tiny_model: TrainedModel) -> Iterator[AppContext]:
    ws = restored(tiny_model, drive / "workspace")
    opened = engineer(AppContext(Settings(workspace=str(ws), device="cpu")))
    yield opened
    opened.close()


def fill(drive: Path, share: float) -> None:
    """Write zeros to drive/filler.bin until `share` of the drive is in use (tmpfs keeps written zeros in memory)."""
    found = disk.usage(drive)
    need = int(share * found.total) - (found.total - found.free)
    assert need >= 0, f"the drive is already {1 - found.free / found.total:.0%} used"
    with (drive / "filler.bin").open("ab") as f:
        while need > 0:
            f.write(bytes(min(need, 2**20)))
            need -= 2**20


def ok_board(ctx: AppContext, insp: Inspector, dataset: Path) -> tuple[str, InspectionResult]:
    judged = ((str(p), insp.inspect(ctx.load_image(str(p)))) for p in list_images(dataset / "test" / "ok"))
    return next((p, r) for p, r in judged if r.verdict == "OK")


def disk_alarms(ctx: AppContext) -> list[tuple[str, str]]:
    return [(a["level"], a["code"]) for a in reversed(ctx.alarms()) if a["code"] in ("AOI-LOG-005", "AOI-LOG-006")]


def test_req_log_006_alarms_once_as_the_drive_crosses_80_and_95_percent(ctx: AppContext, drive: Path) -> None:
    assert ctx.check_disk() is not None and disk_alarms(ctx) == []  # a workspace on an empty drive
    fill(drive, 0.81)
    space = ctx.check_disk()
    assert space is not None and space.level == disk.LOW_LEVEL and 80 <= space.percent < 95
    ctx.check_disk()  # still above 80 %: alarmed once
    assert disk_alarms(ctx) == [("WARN", "AOI-LOG-005")]
    fill(drive, 0.96)
    ctx.check_disk()
    assert disk_alarms(ctx) == [("WARN", "AOI-LOG-005"), ("ERROR", "AOI-LOG-006")]
    (drive / "filler.bin").unlink()  # freed: the next crossing alarms again
    assert ctx.check_disk().level == disk.OK  # type: ignore[union-attr]
    fill(drive, 0.81)
    ctx.check_disk()
    assert disk_alarms(ctx)[-1] == ("WARN", "AOI-LOG-005") and len(disk_alarms(ctx)) == 3
    alarm = next(a for a in ctx.alarms() if a["code"] == "AOI-LOG-006")
    assert "% full" in alarm["message"] and "GB free" in alarm["message"]


def test_req_log_006_at_95_percent_an_ok_board_keeps_its_record_but_not_its_overlay_and_maps(
    ctx: AppContext, drive: Path, ng_board: Path, synthetic_dataset: Path
) -> None:
    """NG and WARN evidence is always saved."""
    insp = ctx.inspector(BOARD)
    path, ok = ok_board(ctx, insp, synthetic_dataset)
    fill(drive, 0.96)
    ctx.log_result(BOARD, path, ok, insp)  # measured before the save: alarms AOI-LOG-006
    ng = insp.inspect(ctx.load_image(str(ng_board)))
    ctx.log_result(BOARD, str(ng_board), ng, insp)
    ng_row, ok_row = ctx.inspections(board_model=BOARD)  # newest first
    assert ok_row["result"] == "OK" and not (ok_row["overlay_path"] or ok_row["diff_map_path"] or ok_row["ai_map_path"])
    stored = ctx.inspection_result(ok_row["id"])
    assert stored is not None and stored.notes[-1] == disk.SKIPPED_NOTE and stored.verdict == "OK"
    assert disk.SKIPPED_NOTE not in ok.notes  # the result the Inspection page shows is not changed on the pool thread
    assert ng_row["result"] == "NG" and Path(ng_row["overlay_path"]).is_file()
    assert Path(ng_row["diff_map_path"]).is_file() and Path(ng_row["ai_map_path"]).is_file()
    assert [p.name for p in ctx.settings.results_dir.rglob("*_OK*")] == []
    assert disk_alarms(ctx) == [("ERROR", "AOI-LOG-006")]


def test_req_log_006_a_start_on_a_drive_too_full_to_archive_opens_and_alarms(
    drive: Path, tiny_model: TrainedModel, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The start-up archive step refused the workspace with AOI-SET-011 on SQLITE_FULL (diagnosis, day 31); now it
    waits for the next start, and the app opens with the drive's alarm. Any other refusal still refuses."""
    ws = restored(tiny_model, drive / "workspace")
    fill(drive, 0.96)

    def full(self: Database, days: int) -> int:
        raise sqlite3.OperationalError("database or disk is full")

    monkeypatch.setattr(Database, "archive_old", full)
    ctx = AppContext(Settings(workspace=str(ws), device="cpu"))
    try:
        assert disk_alarms(ctx) == [("ERROR", "AOI-LOG-006")]
        assert "retention.not_archived" in [r["event"] for r in log_rows(ctx.settings.root / "logs")]
    finally:
        ctx.close()

    def damaged(self: Database, days: int) -> int:
        raise sqlite3.DatabaseError("database disk image is malformed")

    monkeypatch.setattr(Database, "archive_old", damaged)
    with pytest.raises(Exception, match="AOI-SET-011"):
        AppContext(Settings(workspace=str(ws), device="cpu"))


def test_req_log_006_a_drive_the_system_cannot_measure_stops_no_save(
    ctx: AppContext, ng_board: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(disk, "usage", mock.Mock(side_effect=OSError("drive gone")))
    insp = ctx.inspector(BOARD)
    ctx.log_result(BOARD, str(ng_board), insp.inspect(ctx.load_image(str(ng_board))), insp)
    assert ctx.disk is None and Path(ctx.inspections()[0]["overlay_path"]).is_file() and disk_alarms(ctx) == []


def test_req_log_006_a_start_on_a_drive_with_no_byte_free_opens(
    drive: Path, tiny_model: TrainedModel, synthetic_dataset: Path
) -> None:
    """The diagnosis's day 31 on a real filesystem: every start-up write meets a full drive, an OK record and its maps
    past their retention among them; the app opens, and alarms AOI-LOG-006 if the alarm fits."""
    if not os.path.ismount(drive):
        pytest.skip("needs a tmpfs the test may mount (root on Linux); CI's runner fakes SQLITE_FULL above")
    ws = restored(tiny_model, drive / "workspace")
    ctx = engineer(AppContext(Settings(workspace=str(ws), device="cpu")))
    insp = ctx.inspector(BOARD)
    ctx.log_result(BOARD, *ok_board(ctx, insp, synthetic_dataset), insp)
    ctx.close()
    with sqlite3.connect(ws / "aoi.sqlite") as db:  # the record and its maps past retention
        db.execute("UPDATE inspections SET time='2000-01-01T00:00:00+00:00'")
    with (drive / "filler.bin").open("ab", buffering=0) as f, contextlib.suppress(OSError):
        while True:
            f.write(bytes(2**16))
    assert disk.usage(drive).free < 2**16
    ctx = AppContext(Settings(workspace=str(ws), device="cpu"))
    try:
        assert ctx.disk is not None and ctx.disk.level == disk.FULL_LEVEL
    finally:
        ctx.close()


def test_req_log_006_the_status_bar_shows_the_free_space_on_amber_from_80_percent(
    qtbot: QtBot, ctx: AppContext, drive: Path
) -> None:
    win = _window(qtbot, ctx, "Operator")
    assert win.drive.text().startswith("Drive: ") and win.drive.styleSheet() == theme.drive_style(disk.OK)
    fill(drive, 0.81)
    win.show_drive()  # what the timer does each minute
    assert win.drive.styleSheet() == theme.drive_style(disk.LOW_LEVEL) and theme.WARN_COLOR in win.drive.styleSheet()
    fill(drive, 0.96)
    win.show_drive()
    space = ctx.disk
    assert space is not None and theme.NG_COLOR in win.drive.styleSheet()
    assert win.drive.text() == f"Drive: {space.free_gb} GB free · {space.percent} % used"


def test_req_log_006_the_csv_export_names_the_evidence_each_record_kept(
    qtbot: QtBot,
    ctx: AppContext,
    drive: Path,
    ng_board: Path,
    synthetic_dataset: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    insp = ctx.inspector(BOARD)
    path, ok = ok_board(ctx, insp, synthetic_dataset)
    fill(drive, 0.96)
    ctx.log_result(BOARD, path, ok, insp)
    ctx.log_result(BOARD, str(ng_board), insp.inspect(ctx.load_image(str(ng_board))), insp)
    win = _window(qtbot, ctx, "Admin")  # only an Admin exports (Q58)
    logs = win.pages["Logs & Export"]
    win.navigate("Logs & Export")
    listed(qtbot, logs)
    out = tmp_path / "inspections.csv"
    monkeypatch.setattr(QFileDialog, "getSaveFileName", staticmethod(lambda *a, **k: (str(out), "CSV (*.csv)")))
    monkeypatch.setattr(QMessageBox, "question", staticmethod(lambda *a, **k: QMessageBox.StandardButton.Yes))
    logs.export_csv()
    qtbot.waitUntil(lambda: win.statusBar().currentMessage().startswith("Exported"), timeout=30000)
    with out.open(encoding="utf-8-sig", newline="") as f:
        exported = {r["result"]: r for r in csv.DictReader(f)}
    assert list(exported["OK"])[-1] == "evidence"  # last, so the columns before it keep their places
    assert exported["OK"]["evidence"] == "none: drive full" and exported["NG"]["evidence"] == "overlay+maps"
    (ng,) = [r for r in ctx.inspections() if r["result"] == "NG"]
    Path(ng["overlay_path"]).unlink()  # gone by hand: no longer kept
    assert disk.evidence(ng, []) == "maps"
