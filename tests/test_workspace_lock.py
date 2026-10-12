"""One copy of the app per workspace, and a start-up sweep that never stops the start (#204, REQ-INSP-008,
REQ-SET-016, REQ-SET-019).

A second copy started on a workspace in use is refused with AOI-SET-019 before it deletes anything (and brings the
first to the front, tests/test_second_start.py), a copy killed mid-run leaves no lock behind, and a temporary file the
sweep cannot delete is logged and skipped.
"""

from __future__ import annotations

import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import BinaryIO

import pytest
from PySide6.QtWidgets import QFileDialog

from aoi.config import Settings
from aoi.core.services import AppContext
from aoi.data import atomic
from aoi.data.db import Database
from aoi.errors import AoiError
from aoi.ui import errors as ui_errors
from aoi.ui import front
from tests.conftest import log_rows

ROOT = Path(__file__).resolve().parents[1]
FIRST_COPY = """
import os
import sys
from aoi.config import Settings
from aoi.core.services import AppContext
AppContext(Settings(workspace=sys.argv[1], device="cpu"))
print("ready", os.getpid(), flush=True)  # its own process id: in a venv on Windows, Popen's is the launcher's
sys.stdin.read()
"""


def _second_copy(settings: Settings) -> AppContext:
    return AppContext(Settings(workspace=settings.workspace, device="cpu"))


def _log_rows(root: Path, event: str) -> list[dict[str, object]]:
    return [r for r in log_rows(root / "logs") if r["event"] == event]


def test_req_insp_008_a_second_copy_is_refused_and_deletes_no_file_the_first_is_writing(workspace: Settings) -> None:
    """The issue's reproduction: copy A writes a result file through the atomic writer; copy B, started on the same
    workspace meanwhile, is refused with AOI-SET-019, and A's temporary file survives, so A's write finishes."""
    first = AppContext(workspace)
    target = first.settings.results_dir / "2026-10-03" / "ng_001_x_NG.png"
    started, go, failed = threading.Event(), threading.Event(), list[BaseException]()

    def writer(f: BinaryIO) -> None:
        f.write(b"x" * 100)
        started.set()
        go.wait(30)

    def write() -> None:
        try:
            atomic.write_with(target, writer)
        except BaseException as e:
            failed.append(e)

    thread = threading.Thread(target=write)
    thread.start()
    assert started.wait(30)
    in_flight = [p.name for p in target.parent.iterdir()]
    try:
        with pytest.raises(AoiError) as refused:
            _second_copy(workspace)
        assert [p.name for p in target.parent.iterdir()] == in_flight  # nothing deleted
    finally:
        go.set()
        thread.join(30)
    assert refused.value.code == "AOI-SET-019" and "already open on this workspace" in refused.value.what
    assert failed == [] and target.read_bytes() == b"x" * 100  # A's write finished
    first.close()
    _second_copy(workspace).close()  # the same folder opens once the first copy has closed


def test_req_set_016_a_copy_killed_mid_run_leaves_no_lock(workspace: Settings) -> None:
    """Another process holding the workspace refuses this one; once that process is killed (a crash, a power cut), the
    workspace opens: the lock is the operating system's, not a file that outlives the process."""
    proc = subprocess.Popen(
        [sys.executable, "-c", FIRST_COPY, workspace.workspace],
        cwd=ROOT,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        text=True,
    )
    try:
        assert proc.stdout is not None and proc.stdout.readline().split()[0] == "ready"
        with pytest.raises(AoiError) as refused:
            _second_copy(workspace)
        assert refused.value.code == "AOI-SET-019"
    finally:
        proc.kill()
        proc.wait()
    deadline = time.monotonic() + 10  # Windows drops a killed process's locks soon after it ends, not always at once
    while True:
        try:
            _second_copy(workspace).close()
            break
        except AoiError as e:
            if e.code != "AOI-SET-019" or time.monotonic() > deadline:
                raise
            time.sleep(0.1)


def test_req_set_016_a_workspace_in_use_ends_the_second_start_and_opens_once_the_other_copy_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, dialogs: list[tuple[str, str]]
) -> None:
    """At start-up (open_workspace), a workspace another copy has open ends this start with AOI-SET-019, in one
    sentence where the other copy cannot be brought to the front (here, no system to do it), never the folder picker
    (A6 of the 2026-10 business-readiness brief, F12); the same folder opens once the other copy has closed."""
    ws = tmp_path / "ws"
    Settings(workspace=str(ws), device="cpu").save()
    first = AppContext(Settings.load())
    asked: list[object] = []
    monkeypatch.setattr(QFileDialog, "getExistingDirectory", staticmethod(lambda *a: asked.append(a) or ""))
    monkeypatch.setattr(front, "this_system", lambda: None)
    assert ui_errors.open_workspace() is None
    assert [title for title, _ in dialogs] == ["AOI-SET-019 App already open"] and asked == []
    first.close()
    ctx = ui_errors.open_workspace()
    assert ctx is not None and ctx.settings.root == ws and len(dialogs) == 1
    ctx.close()


def test_req_set_019_a_temp_file_that_cannot_be_deleted_never_stops_the_start(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, dialogs: list[tuple[str, str]]
) -> None:
    """A leftover temporary file that cannot be deleted (read-only, held open) is logged as sweep.skipped and the app
    starts; a crash's other leftovers go, and a file with another program's name is left alone."""
    ws = tmp_path / "ws"
    settings = Settings(workspace=str(ws), device="cpu")
    AppContext(settings).close()
    settings.save()
    day = ws / "results" / "2026-10-03"
    day.mkdir(parents=True)
    stuck, left = day / ".ok_001_abc_OK.png.deadbeef.tmp", day / ".ng_002_abc_NG.png.0123abcd.tmp"
    foreign = ws / ".editor-backup.tmp"  # another program's temporary file, not a name the app makes
    for p in (stuck, left, foreign):
        p.write_bytes(b"x")
    unlink = Path.unlink

    def refuse(p: Path, missing_ok: bool = False) -> None:
        if p == stuck:
            raise PermissionError(1, "Operation not permitted", str(p))
        unlink(p, missing_ok=missing_ok)

    monkeypatch.setattr(Path, "unlink", refuse)
    asked: list[object] = []
    monkeypatch.setattr(QFileDialog, "getExistingDirectory", staticmethod(lambda *a: asked.append(a) or ""))
    ctx = ui_errors.open_workspace()
    assert dialogs == [] and asked == [] and ctx is not None
    assert stuck.exists() and not left.exists() and foreign.exists()
    rows = _log_rows(ws, "sweep.skipped")
    assert [r["path"] for r in rows] == ["results/2026-10-03/.ok_001_abc_OK.png.deadbeef.tmp"]
    assert "Operation not permitted" in str(rows[0]["reason"])
    assert _log_rows(ws, "app.start")[-1]["swept"] == 1
    ctx.close()


def test_req_set_016_a_start_that_fails_after_the_database_opened_closes_it_and_lets_go(
    workspace: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A failure in the start-up sweep closes the database (and the log) like every other start-up failure, and the
    workspace opens at the next try."""
    AppContext(workspace).close()
    closed, close, sweep = list[Path](), Database.close, atomic.sweep_temp_files
    monkeypatch.setattr(Database, "close", lambda db: (closed.append(db.path), close(db))[1])

    def fail(folder: object) -> object:
        raise RuntimeError("the drive went away")

    monkeypatch.setattr(atomic, "sweep_temp_files", fail)
    with pytest.raises(RuntimeError, match="the drive went away"):
        _second_copy(workspace)
    assert closed == [workspace.db_path]
    monkeypatch.setattr(atomic, "sweep_temp_files", sweep)
    _second_copy(workspace).close()
