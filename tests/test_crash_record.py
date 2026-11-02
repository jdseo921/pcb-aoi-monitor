"""The crash record (REQ-SET-026): faulthandler writes a native crash's stacks to logs/crash.log, the next start keeps
it as crash-<time>.log and logs it, and every error dialog's Details names the version, build and commit."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from pytestqt.qtbot import QtBot

from aoi import config, logging_setup
from aoi.config import APP_LABEL, BUILD_LINE, Settings, build_commit
from aoi.core.services import AppContext, ErrorReport
from aoi.ui.errors import ErrorBox
from tests.conftest import TrainedModel, log_rows, restored

ROOT = Path(__file__).resolve().parents[1]
CRASH = "import faulthandler, sys; from pathlib import Path; from aoi import logging_setup as s; "


def run(code: str, logs: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run([sys.executable, "-c", CRASH + code, str(logs)], cwd=ROOT, capture_output=True, text=True)


def test_req_set_026_a_forced_access_violation_leaves_its_stacks_in_logs_and_the_next_start_keeps_them(
    tmp_path: Path,
) -> None:
    logs = tmp_path / "logs"
    died = run("s.crash_record(Path(sys.argv[1])); faulthandler._sigsegv()", logs)
    assert died.returncode != 0  # the process died of the fault
    record = (logs / logging_setup.CRASH).read_text(encoding="utf-8")
    assert "Fatal Python error" in record and ("Current thread" in record or "Thread 0x" in record)
    started = run("print(s.crash_record(Path(sys.argv[1])).name)", logs)  # the next start
    kept = logs / started.stdout.strip()
    assert kept.name.startswith("crash-") and kept.read_text(encoding="utf-8") == record
    assert (logs / logging_setup.CRASH).read_text(encoding="utf-8") == ""  # a new one, empty while nothing crashes
    assert run("print(s.crash_record(Path(sys.argv[1])))", logs).stdout.strip() == "None"


def test_req_set_026_every_error_dialogs_details_name_the_version_build_and_commit(
    qtbot: QtBot, tmp_path: Path
) -> None:
    box = ErrorBox(None, ErrorReport("AOI-SET-007", "Unexpected error", "What happened", "What to do", "ValueError: x"))
    qtbot.addWidget(box)
    assert box.detailedText() == f"ValueError: x\n\n{BUILD_LINE}" and APP_LABEL in BUILD_LINE
    bare = ErrorBox(None, ErrorReport("AOI-SET-007", "Unexpected error", "What happened", "What to do"))
    qtbot.addWidget(bare)
    assert bare.detailedText() == BUILD_LINE == f"{config.APP_NAME} {APP_LABEL}, commit none (from source)"
    (tmp_path / "COMMIT").write_text("0123456789ab\n", encoding="ascii")  # as installer/aoi.spec writes it
    assert build_commit(tmp_path) == "0123456789ab" and build_commit(tmp_path / "none") is None


def test_req_set_026_each_workspace_holds_its_own_crash_record_only_while_open(
    tmp_path: Path, tiny_model: TrainedModel
) -> None:
    """The context points faulthandler at its own logs/ and lets go on close, so Windows can move or delete the folder
    (Reset Demo deletes the demo's logs/); a record a crash left is logged at the next open."""
    ws = restored(tiny_model, tmp_path / "ws")
    (ws / "logs" / logging_setup.CRASH).write_text("Fatal Python error: Segmentation fault\n", encoding="utf-8")
    ctx = AppContext(Settings(workspace=str(ws), device="cpu"))
    try:
        held = logging_setup._crash_file
        assert held is not None and Path(held.name) == ws / "logs" / logging_setup.CRASH
        kept = [r["record"] for r in log_rows(ws / "logs") if r["event"] == "app.crashed"]
        assert kept and kept[-1].startswith("crash-") and (ws / "logs" / kept[-1]).is_file()
    finally:
        ctx.close()
    assert logging_setup._crash_file is None and held.closed
