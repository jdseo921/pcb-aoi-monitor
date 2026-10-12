"""REQ-USR-003, REQ-SET-007: who a start signs in. The demo workspace, opened by `main.py --demo` or the
installer's Demo shortcut, signs in its first Admin, at Home after a normal close, as the demo scripts begin; a station
signs in the user who signed in on it last with Switch User, which is audited, or `operator` while no one has; a station
with no board model yet signs in its first Admin, to set it up. Each start's sign-in is audited too (user.start). The
demo's boards are synthetic: these tests prove the path, never accuracy.
"""

from __future__ import annotations

import json
import os
import sqlite3
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

import pytest
from PySide6.QtWidgets import QInputDialog
from pytestqt.qtbot import QtBot

from aoi import config
from aoi.config import Settings
from aoi.core import demo
from aoi.core.services import AppContext
from aoi.data import credentials
from aoi.errors import AoiError
from aoi.ui.demo_workspace import open_demo
from aoi.ui.errors import open_workspace
from aoi.ui.main_window import MainWindow, build_window
from tests.budgets import LONG_TRIES, judged

ROOT = Path(__file__).resolve().parents[1]
START_BUDGET_S = 5.0  # REQ-SET-020: usable within 5 s of starting
LOAD_BUDGET_S = 10.0  # REQ-SET-007: the demo loaded (or reset) within 10 s; the first --demo start loads it, then opens


def _reopened(ctx: AppContext) -> AppContext:
    """The station started again: its workspace closed and opened anew."""
    ctx.close()
    return AppContext(Settings(workspace=ctx.settings.workspace, device="cpu"), ctx.credentials)


def test_req_usr_003_a_start_signs_in_who_signed_in_last_on_the_station(ctx: AppContext) -> None:
    """No one has signed in yet: a start signs in operator. Switch User's sign-in is audited with the user before, and
    the next start signs that user in again; a start's own sign-in (user.start) is audited and changes no later start;
    a station being set up still starts with the first Admin."""
    ctx.ensure_board_model("B")  # set up: no longer the first start's Admin
    ctx.set_user("operator")
    assert ctx.start_user() == "operator" and ctx.last_signed_in() is None
    ctx.sign_in("engineer")
    assert ctx.user == "engineer" and ctx.last_signed_in() == "engineer"
    (entry,) = ctx.audit_entries(action="user.sign_in")
    assert (entry["object_type"], entry["object_uuid"]) == ("user", ctx.db.user_uuid("engineer"))
    assert (entry["user_uuid"], entry["role"]) == (ctx.db.user_uuid("engineer"), "Engineer")  # who signed in
    assert entry["before"] == {"user": "operator", "role": "Operator"}
    assert entry["after"] == {"user": "engineer", "role": "Engineer"}

    again = _reopened(ctx)
    try:
        assert again.user == "engineer" and again.start_user() == "engineer"
        again.sign_in("admin", start=True)  # as a start does: audited, but no sign-in of a person
        (started,) = again.audit_entries(action="user.start")
        assert (started["object_uuid"], started["before"]) == (again.db.user_uuid("admin"), None)
        assert started["after"] == {"user": "admin", "role": "Admin"}
        assert again.last_signed_in() == again.start_user() == "engineer"
        assert again.start_user(setting_up=True) == "admin"
    finally:
        again.close()


def test_req_usr_003_a_sign_in_refused_or_not_audited_leaves_the_user_before(
    ctx: AppContext, monkeypatch: pytest.MonkeyPatch
) -> None:
    """AOI-USR-003 refuses a name the users table does not hold; a sign-in whose audit entry cannot be written (the
    drive full) leaves the user before signed in, and the next start does not take it for the last."""
    ctx.set_user("operator")
    with pytest.raises(AoiError) as refused:
        ctx.sign_in("nobody")
    assert refused.value.code == "AOI-USR-003" and ctx.user == "operator"

    def full(*args: Any) -> str:
        raise sqlite3.OperationalError("database or disk is full")

    monkeypatch.setattr(ctx.db, "add_audit", full)
    for start in (False, True):
        with pytest.raises(sqlite3.OperationalError):
            ctx.sign_in("admin", start=start)
        assert ctx.user == "operator" and ctx.last_signed_in() is None


def test_req_usr_003_switch_user_signs_in_and_the_next_start_keeps_them(
    qtbot: QtBot, ctx: AppContext, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The window's start signs its user in (user.start); the header's Switch User signs a user in through
    AppContext.sign_in, and a sign-in that cannot be audited leaves the header as it was. The window of the next start
    opens with the user who signed in last, and its status line says so, where it opened with operator, and no such
    line, before anyone had signed in."""
    ctx.ensure_board_model("B")
    workspace = ctx.settings.workspace
    win = MainWindow(ctx)
    qtbot.addWidget(win)
    assert ctx.user == "operator" and "signed in last" not in win.statusBar().currentMessage()
    assert [e["after"]["user"] for e in ctx.audit_entries(action="user.start")] == ["operator"]
    pick = staticmethod(lambda *args: ("engineer (Engineer)", True))
    monkeypatch.setattr(QInputDialog, "getItem", pick)

    def full(*args: Any) -> str:
        raise sqlite3.OperationalError("database or disk is full")

    with monkeypatch.context() as m:
        m.setattr(ctx.db, "add_audit", full)
        with pytest.raises(sqlite3.OperationalError):  # shown by the window's error hook, as any unhandled error
            win.switch_user()
    assert ctx.user == "operator" and win.user_label.text() == "operator  ·  Operator"
    win.switch_user()
    assert ctx.user == "engineer" and win.user_label.text() == "engineer  ·  Engineer"
    assert [e["after"]["user"] for e in ctx.audit_entries(action="user.sign_in")] == ["engineer"]
    win.close()  # closes the workspace, as quitting the app does

    again = MainWindow(AppContext(Settings(workspace=workspace, device="cpu")))
    qtbot.addWidget(again)
    try:
        assert again.ctx.user == "engineer" and again.user_label.text() == "engineer  ·  Engineer"
        said = again.statusBar().currentMessage()
        assert said.startswith("Signed in as engineer (Engineer), who signed in last on this station."), said
    finally:
        again.close()


def test_req_set_007_the_demo_window_opens_as_its_first_admin_at_home(
    qtbot: QtBot, demo_bundle: Path, tmp_path: Path, keys: credentials.MemoryCredentials
) -> None:
    """Whoever signed in last in the demo workspace, its window opens with its first Admin, as the demo scripts'
    preparation has it (docs/demo/stage1-5min.md). After a crash it opens on the page it showed, so the presenter
    carries on (REQ-LOG-005); closed, it opens at Home next, where its scripts begin."""
    folder = tmp_path / "AOI_Workspace-Demo"
    demo.load(demo_bundle, folder, {"device": "cpu", "last_page": "Logs & Export"}, keys)  # as a crash on Logs left it
    config.use_workspace(folder)  # its own settings.json, as main.py --demo has it

    def opened() -> MainWindow:
        ctx = AppContext(Settings.load(), keys)
        ctx.sign_in("operator")  # the presenter signed in as the Operator, as the 45-minute script does
        win = MainWindow(ctx)
        qtbot.addWidget(win)
        assert win.in_demo and (ctx.user, ctx.role) == ("admin", "Admin")
        assert "signed in last" not in win.statusBar().currentMessage()
        return win

    win = opened()
    assert win.stack.currentWidget() is win.pages["Logs & Export"]
    win.close()
    assert json.loads((folder / "settings.json").read_text(encoding="utf-8"))["last_page"] == "Home"
    win = opened()
    try:
        assert win.stack.currentWidget() is win.pages["Home"]
    finally:
        win.close()


def test_req_usr_003_a_workspace_switch_signs_in_the_role_carried_once_and_never_as_the_last(
    qtbot: QtBot, demo_bundle: Path, keys: credentials.MemoryCredentials, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The demo opened with its Admin, then Leave Demo: the station's window opens with its first Admin, the role
    carried, audited once as user.start, with no line saying who signed in last; the station's next start still signs
    in the Engineer who signed in last with Switch User, not the Admin the demo signed in by itself."""
    monkeypatch.setenv("AOI_DEMO_BUNDLE", str(demo_bundle))
    ctx = open_workspace()
    assert ctx is not None
    ctx.set_user("engineer")
    ctx.ensure_board_model("B")  # set up
    ctx.sign_in("engineer")
    production = ctx.settings.root
    ctx.close()
    opened = open_demo()
    assert opened is not None
    win = build_window(opened)
    assert win is not None and win.in_demo and opened.role == "Admin"
    win.show()
    station = win.switch_workspace(None)  # Leave Demo
    assert station is not None and station.ctx.settings.root == production
    try:
        assert (station.ctx.user, station.ctx.role) == ("admin", "Admin")
        assert "signed in last" not in station.statusBar().currentMessage()
        started = [e["after"]["user"] for e in station.ctx.audit_entries(action="user.start")]
        assert started == ["admin"]  # one sign-in, as the window opened
        assert [e["after"]["user"] for e in station.ctx.audit_entries(action="user.sign_in")] == ["engineer"]
        assert station.ctx.last_signed_in() == station.ctx.start_user() == "engineer"
    finally:
        station.close()
    again = build_window(AppContext(Settings.load(), keys))
    assert again is not None
    try:
        assert again.ctx.user == "engineer" and "signed in last" in again.statusBar().currentMessage()
    finally:
        again.close()


def test_req_set_007_main_demo_starts_as_the_first_admin_at_home_in_its_theme_within_5_s(
    demo_bundle: Path, tmp_path: Path
) -> None:
    """`main.py --demo` (the installer's Demo shortcut), each start in a process of its own through main.main()
    (tests/startup_worker.py): the first loads the demo beside the station's workspace, once after an install, and is
    held to REQ-SET-007's 10 s for a load, one try as it happens once (about 4 s on a 4-core cloud VM); the presenter
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
    print("\nmain.py --demo, first start (the demo loaded), s:", round(first["usable"], 2))
    assert first["usable"] <= LOAD_BUDGET_S, f"the first start, loading the demo, took {first['usable']:.2f} s: {first}"
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
