"""REQ-INSP-008, crash-safety part (S11): no finished result is lost and nothing is left half-written.

A process kill is not a power cut: the operating system still flushes what the process handed it, and the
disk's own cache is not involved. The full test on the reference PC, with the power pulled, is part of S55.
"""

from __future__ import annotations

import random
import shutil
import subprocess
import sys
import time
from pathlib import Path

import pytest

from aoi.config import Settings
from aoi.core.imaging import IMAGE_EXTS, load_image
from aoi.core.services import AppContext
from aoi.data import atomic
from aoi.data.db import Database
from tests.conftest import TrainedModel

ROOT = Path(__file__).resolve().parents[1]
KILLS = 20
SEED = 2026


def test_req_insp_008_writes_are_atomic(tmp_path: Path) -> None:
    target = tmp_path / "board.png"
    atomic.write_bytes(target, b"old")

    def half(f: object) -> None:
        f.write(b"new but")  # type: ignore[attr-defined]
        raise OSError("disk full")

    with pytest.raises(OSError, match="disk full"):
        atomic.write_with(target, half)
    assert target.read_bytes() == b"old"  # the old file is untouched ...
    assert [p.name for p in tmp_path.iterdir()] == ["board.png"]  # ... and no temporary file remains
    atomic.write_text(target, "new")
    assert target.read_text(encoding="utf-8") == "new"
    atomic.copy_file(target, tmp_path / "sub" / "copy.png")
    assert (tmp_path / "sub" / "copy.png").read_bytes() == b"new"
    (tmp_path / "sub" / ".left.deadbeef.tmp").write_bytes(b"x")
    assert atomic.sweep_temp_files(tmp_path) == 1 and not (tmp_path / "sub" / ".left.deadbeef.tmp").exists()


def test_req_insp_008_no_finished_result_lost(tmp_path: Path, tiny_model: TrainedModel) -> None:
    ws = tmp_path / "station"
    shutil.copytree(tiny_model.ctx.settings.root, ws)
    rng = random.Random(SEED)
    finished = 0
    for _ in range(KILLS):
        proc = subprocess.Popen(
            [sys.executable, "-m", "tests.power_cut_worker", str(ws)],
            cwd=ROOT,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        assert proc.stdout is not None
        assert proc.stdout.readline().strip() == "ready", proc.stderr.read() if proc.stderr else ""
        time.sleep(rng.uniform(0.2, 1.5))  # somewhere inside an inspection, a save, or between boards
        proc.kill()
        proc.wait()

        db = Database(ws / "aoi.sqlite", ws)  # reopens cleanly: WAL recovery, migrations consistent
        rows = db.inspections(include_archived=True)
        for r in rows:
            overlay = Path(r["overlay_path"])
            assert overlay.exists(), r
            load_image(overlay)  # decodes, so the whole file is there
            assert r["defect_count"] == len(db.defects_for(r["id"]))
            assert db.checks_for(r["id"]) and db.inspection_result(r["id"]), "a row without its checks or result"
        db.close()
        for p in (ws / "results").rglob("*"):
            if p.is_file() and not p.name.endswith(atomic.TEMP_SUFFIX):  # a temp file: an interrupted write
                assert p.suffix in IMAGE_EXTS, f"left half-written: {p}"
                load_image(p)
        assert len(rows) >= finished  # nothing recorded earlier disappeared
        finished = len(rows)
    assert finished >= KILLS, f"only {finished} inspections finished over {KILLS} runs"
    ctx = AppContext(Settings(workspace=str(ws), device="cpu"))  # the next start sweeps the temp files away
    assert not list(ws.rglob(f".*{atomic.TEMP_SUFFIX}")) and ctx.load_model("TINY") is not None
