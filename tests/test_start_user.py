"""A1 (REQ-USR-003, REQ-SET-007): who a start signs in. The demo workspace, opened by `main.py --demo` or the
installer's Demo shortcut, signs in its first Admin at Home, as the demo scripts begin; a station signs in the user who
signed in on it last with Switch User, which is audited, or `operator` while no one has; a station with no board model
yet signs in its first Admin, to set it up. The demo's boards are synthetic: these tests prove the path, never accuracy.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

import pytest
from PySide6.QtWidgets import QInputDialog
from pytestqt.qtbot import QtBot

from aoi.config import Settings
from aoi.core import demo
from aoi.core.services import AppContext
from aoi.data import credentials
from aoi.errors import AoiError
from aoi.ui.main_window import MainWindow
from tests.budgets import LONG_TRIES, judged

ROOT = Path(__file__).resolve().parents[1]
START_BUDGET_S = 5.0  # REQ-SET-020: usable within 5 s of starting


def _reopened(ctx: AppContext) -> AppContext:
    """The station started again: its workspace closed and opened anew."""
    ctx.close()
    return AppContext(Settings(workspace=ctx.settings.workspace, device="cpu"), ctx.credentials)


def test_req_usr_003_a_start_signs_in_who_signed_in_last_on_the_station(ctx: AppContext) -> None:
    """No one has signed in yet: a start signs in operator. Switch User's sign-in is audited with the user before, and
    the next start signs that user in again; the demo and a station being set up still start with the first Admin."""
    ctx.ensure_board_model("B")  # set up: no longer the first start's Admin
    ctx.set_user("operator")
    assert ctx.start_user() == "operator" and ctx.db.last_sign_in() is None
    ctx.sign_in("engineer")
    assert ctx.user == "engineer"
    (entry,) = ctx.audit_entries(action="user.sign_in")
    assert (entry["object_type"], entry["object_uuid"]) == ("user", ctx.db.user_uuid("engineer"))
    assert (entry["user_uuid"], entry["role"]) == (ctx.db.user_uuid("engineer"), "Engineer")  # who signed in
    assert entry["before"] == {"user": "operator", "role": "Operator"}
    assert entry["after"] == {"user": "engineer", "role": "Engineer"}

    again = _reopened(ctx)
    try:
        assert again.user == "engineer" and again.start_user() == "engineer"
        assert again.start_user(demo=True) == again.start_user(setting_up=True) == "admin"
    finally:
        again.close()


def test_req_usr_003_a_sign_in_refused_or_not_audited_leaves_the_user_before(
    ctx: AppContext, monkeypatch: pytest.MonkeyPatch
) -> None:
    """AOI-USR-003 refuses a name the users table does not hold; a sign-in whose audit entry cannot be written leaves
    the user before signed in, and the next start does not take it for the last."""
    ctx.set_user("operator")
    with pytest.raises(AoiError) as refused:
        ctx.sign_in("nobody")
    assert refused.value.code == "AOI-USR-003" and ctx.user == "operator"

    def full(*args: Any) -> str:
        raise OSError("the drive is full")

    monkeypatch.setattr(ctx.db, "add_audit", full)
    with pytest.raises(OSError):
        ctx.sign_in("admin")
    assert ctx.user == "operator" and ctx.db.last_sign_in() is None


def test_req_usr_003_switch_user_signs_in_and_the_next_start_keeps_them(
    qtbot: QtBot, ctx: AppContext, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The header's Switch User signs the user in through AppContext.sign_in; the window of the next start opens
    with them, where it opened with operator before anyone had signed in."""
    ctx.ensure_board_model("B")
    workspace = ctx.settings.workspace
    win = MainWindow(ctx)
    qtbot.addWidget(win)
    assert ctx.user == "operator"
    monkeypatch.setattr(QInputDialog, "getItem", staticmethod(lambda *args: ("engineer (Engineer)", True)))
    win.switch_user()
    assert ctx.user == "engineer" and win.user_label.text() == "engineer  ·  Engineer"
    assert [e["after"]["user"] for e in ctx.audit_entries(action="user.sign_in")] == ["engineer"]
    win.close()  # closes the workspace, as quitting the app does

    again = MainWindow(AppContext(Settings(workspace=workspace, device="cpu")))
    qtbot.addWidget(again)
    try:
        assert again.ctx.user == "engineer" and again.user_label.text() == "engineer  ·  Engineer"
    finally:
        again.close()


def test_req_set_007_the_demo_window_opens_as_its_first_admin_at_home(
    qtbot: QtBot, demo_bundle: Path, tmp_path: Path, keys: credentials.MemoryCredentials
) -> None:
    """Whoever signed in last in the demo workspace, and whatever page it showed last, its window opens at Home with
    its first Admin, as the demo scripts' preparation has it (docs/demo/stage1-5min.md)."""
    folder = tmp_path / "AOI_Workspace-Demo"
    demo.load(demo_bundle, folder, {"device": "cpu", "last_page": "Logs & Export"}, keys)
    ctx = AppContext(Settings(workspace=str(folder), device="cpu", last_page="Logs & Export"), keys)
    ctx.sign_in("operator")
    win = MainWindow(ctx)
    qtbot.addWidget(win)
    try:
        assert win.in_demo and (ctx.user, ctx.role) == ("admin", "Admin")
        assert win.stack.currentWidget() is win.pages["Home"]
    finally:
        win.close()


def test_req_set_007_main_demo_starts_as_the_first_admin_at_home_in_its_theme_within_5_s(
    demo_bundle: Path, tmp_path: Path
) -> None:
    """`main.py --demo` (the installer's Demo shortcut), each start in a process of its own through main.main()
    (tests/startup_worker.py): the first loads the demo beside the station's workspace, and is not timed; the presenter
    then turns the presenter theme on and signs in as the Operator, as the 45-minute script does, and quits. Each start
    after opens the demo as its first Admin, at Home, in the presenter theme, usable within REQ-SET-020's 5 s of the
    process starting, judged as tests/budgets.py judges a start."""
    station = tmp_path / "AOI_Workspace"
    station.mkdir()
    env = {**os.environ, "AOI_WORKSPACE": str(station), "AOI_DEMO_BUNDLE": str(demo_bundle), "AOI_MEMORY_KEYS": "1"}

    def start() -> dict[str, Any]:
        launched = {"AOI_STARTUP_LAUNCHED": repr(time.time())}
        cmd = [sys.executable, "-m", "tests.startup_worker", "--demo"]
        done = subprocess.run(cmd, cwd=ROOT, env=env | launched, capture_output=True, text=True, timeout=180)
        assert done.returncode == 0, done.stderr
        opened: dict[str, Any] = json.loads(done.stdout.strip().splitlines()[-1])
        assert opened["exposed"] and opened["demo"], opened
        return opened

    first = start()
    assert (first["user"], first["role"], first["page"], first["presenter"]) == ("admin", "Admin", "Home", False)
    folder = demo.demo_folder(station)
    settings = json.loads((folder / "settings.json").read_text(encoding="utf-8"))
    (folder / "settings.json").write_text(json.dumps(settings | {"presenter_theme": True}), encoding="utf-8")
    ctx = AppContext(Settings(workspace=str(folder), device="cpu"), credentials.MemoryCredentials())
    ctx.sign_in("operator")
    ctx.close()

    starts = [start() for _ in range(LONG_TRIES)]
    print("\nmain.py --demo, seconds to usable:", [round(s["usable"], 2) for s in starts])
    for s in starts:
        assert (s["user"], s["role"], s["page"], s["presenter"]) == ("admin", "Admin", "Home", True), s
    usable = judged([s["usable"] for s in starts])
    assert usable <= START_BUDGET_S, f"usable after {usable:.2f} s of the {START_BUDGET_S} s budget: {starts}"
