"""The presenter theme's full screen on a laptop with a projector beside it (#104, ADR 0019 decision 4), in a process
of its own whose offscreen Qt has two screens (tests/two_screens_worker.py)."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
SCREENS = {
    "synchronousWindowSystemEvents": False,
    "windowFrameMargins": False,
    "screens": [
        {"name": "laptop", "x": 0, "y": 0, "width": 1920, "height": 1080, "logicalDpi": 96, "logicalBaseDpi": 96},
        {"name": "projector", "x": 1920, "y": 0, "width": 1366, "height": 768, "logicalDpi": 96, "logicalBaseDpi": 96},
    ],
}


def test_req_set_008_the_presenter_theme_fills_the_projector_and_a_workspace_switch_stays_on_it(tmp_path: Path) -> None:
    """With Windows' Extend, the projector a screen of its own beside the laptop's: the window the presenter put on the
    projector fills it, 1366 x 768 at the projector's place, in the presenter theme's sizes for it (16 pt), and the
    window a workspace switch builds in its place (Load Demo, Reset Demo, Leave Demo Workspace) fills the projector
    too. A window a switch built opened on the laptop's screen, full screen there with no title bar to drag it back
    by (review of the full-screen change). The geometry read is the window's own, as the system placed it, not only
    its full-screen flag."""
    (tmp_path / "screens.json").write_text(json.dumps(SCREENS), encoding="utf-8")
    station = tmp_path / "AOI_Workspace"
    station.mkdir()
    env = {**os.environ, "AOI_WORKSPACE": str(station), "AOI_MEMORY_KEYS": "1"}
    env |= {"PYTHONPATH": os.pathsep.join([str(ROOT), env.get("PYTHONPATH", "")]).rstrip(os.pathsep)}
    # a path with no drive letter, as the platform's arguments are split at each colon
    env["QT_QPA_PLATFORM"] = "offscreen:configfile=screens.json"
    cmd = [sys.executable, "-m", "tests.two_screens_worker"]
    done = subprocess.run(cmd, cwd=tmp_path, env=env, capture_output=True, text=True, timeout=180)
    assert done.returncode == 0, done.stderr
    shown: list[dict[str, Any]] = [json.loads(line) for line in done.stdout.splitlines() if line.startswith("{")]
    projector = {"screen": "projector", "geometry": [1920, 0, 1366, 768], "full_screen": True, "small": True}
    assert shown == [projector | {"dialogs": []}, projector | {"dialogs": []}], (shown, done.stderr)
