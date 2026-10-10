"""The demo workspace from the app (REQ-SET-007, REQ-SET-009; S53): Settings › Demo loads it in one click, plays its
scripted run at the set pace, resets it and leaves it, and the production workspace's files stay as they were; `main.py
--demo` starts in it. The demo's boards are synthetic: these tests prove the path, never accuracy."""

from __future__ import annotations

import hashlib
import json
import time
from collections.abc import Iterator
from pathlib import Path

import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QMessageBox, QPushButton
from pytestqt.qtbot import QtBot

from aoi import config
from aoi.config import Settings
from aoi.core import demo
from aoi.errors import AoiError
from aoi.ui import theme
from aoi.ui.demo_workspace import open_demo
from aoi.ui.errors import open_workspace
from aoi.ui.main_window import MainWindow, build_window
from aoi.ui.pages.inspection import InspectionPage

VERDICTS = ["OK"] * 3 + ["NG"] + ["OK"] * 6  # the bundle's boards in run order


def hashes(folder: Path) -> dict[str, str]:
    return {p.relative_to(folder).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(folder.rglob("*")) if p.is_file()}  # fmt: skip


@pytest.fixture
def bundle(demo_bundle: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("AOI_DEMO_BUNDLE", str(demo_bundle))
    return demo_bundle


@pytest.fixture(autouse=True)
def _windows_closed(qapp: QApplication) -> Iterator[None]:
    """Every main window a test opened, the ones a switch opened included, is closed after it, passed or failed."""
    yield
    for w in QApplication.topLevelWidgets():
        if isinstance(w, MainWindow):
            w.close()
            w.ctx.close()
            w.deleteLater()


def shown_window() -> MainWindow:
    """The one main window shown now: after a switch, the new one."""
    (win,) = [w for w in QApplication.topLevelWidgets() if isinstance(w, MainWindow) and w.isVisible()]
    return win


def station(qtbot: QtBot) -> MainWindow:
    """The app as it starts on the station's own workspace, signed in as the Admin, on Settings."""
    ctx = open_workspace()
    assert ctx is not None
    win = build_window(ctx)
    assert win is not None
    win.show()
    qtbot.waitExposed(win)
    win.set_user("admin")
    assert win.navigate("Settings")
    return win


def click(qtbot: QtBot, button: object) -> MainWindow:
    """Click `button` as a user does and return the window shown after it."""
    qtbot.mouseClick(button, Qt.MouseButton.LeftButton)  # type: ignore[arg-type]
    win = shown_window()
    qtbot.waitExposed(win)
    return win


def records(win: MainWindow) -> list[str]:
    return [str(r["result"]) for r in win.ctx.db.query("SELECT result FROM inspections ORDER BY id")]


def play_to_pause(qtbot: QtBot, win: MainWindow) -> InspectionPage:
    """Play Scripted Run › on Settings, then wait for the run to pause at its NG board."""
    win.navigate("Settings")
    qtbot.mouseClick(win.pages["Settings"].demo.btn_play, Qt.MouseButton.LeftButton)  # type: ignore[attr-defined]
    page = win.pages["Inspection"]
    assert isinstance(page, InspectionPage) and win.stack.currentWidget() is page and page.running
    qtbot.waitUntil(lambda: not page.running and page.worker is None, timeout=60000)
    return page


def test_req_set_007_settings_loads_plays_resets_and_leaves_with_production_untouched(
    qtbot: QtBot, bundle: Path, tmp_path: Path
) -> None:
    win = station(qtbot)
    production = win.ctx.settings.root
    panel = win.pages["Settings"].demo  # type: ignore[attr-defined]
    assert panel.state.text() == "Demo workspace: not loaded."
    assert not win.demo_badge.isVisible()

    win = click(qtbot, panel.btn_load)  # one click
    before = hashes(production)  # the station's session closed at the switch: what it left is production's data
    assert win.in_demo and win.demo_badge.isVisible() and win.windowTitle().endswith("· Demo")
    assert win.ctx.settings.root == demo.demo_folder(production) and win.ctx.role == "Admin"
    assert win.board_model == "DEMO-TBOX-A1" and win.stack.currentWidget() is win.pages["Settings"]
    assert config.default_workspace() == win.ctx.settings.root  # the demo's settings.json, never the station's
    queued = win.pages["Inspection"]
    assert isinstance(queued, InspectionPage) and [p.name for p in queued.queue] == [
        f"board_{i:02d}.png" for i in range(1, 11)
    ]

    win.pages["Settings"].demo.pace.setValue(1)  # type: ignore[attr-defined]
    page = play_to_pause(qtbot, win)
    assert page.queue_pos == 3 and page.last is not None and page.last.verdict == "NG"
    assert "Paused at the NG board board_04.png" in page.summary.text()
    qtbot.mouseClick(page.btn_start, Qt.MouseButton.LeftButton)  # Start goes on with the run
    qtbot.waitUntil(lambda: not page.running and page.worker is None and page.queue_pos == 9, timeout=60000)
    assert records(win) == VERDICTS

    win.navigate("Settings")
    win = click(qtbot, win.pages["Settings"].demo.btn_reset)  # type: ignore[attr-defined]
    assert win.in_demo and records(win) == [] and win.stack.currentWidget() is win.pages["Settings"]
    (entry,) = win.ctx.audit_entries(action="demo.reset")
    assert entry["after"]["seconds"] < 10 and entry["role"] == "Admin"
    assert win.ctx.settings.demo_pace_s == 1  # the demo's own settings stay through a reset
    assert hashes(production) == before

    win = click(qtbot, win.pages["Settings"].demo.btn_leave)  # type: ignore[attr-defined]
    assert not win.in_demo and win.ctx.settings.root == production and not win.demo_badge.isVisible()
    assert win.pages["Settings"].demo.state.text() == "Demo workspace: loaded, not open."  # type: ignore[attr-defined]
    assert config.default_workspace() == production
    win.close()


def test_req_set_009_pace(qtbot: QtBot, bundle: Path) -> None:
    win = click(qtbot, station(qtbot).pages["Settings"].demo.btn_load)  # type: ignore[attr-defined]
    slider = win.pages["Settings"].demo.pace  # type: ignore[attr-defined]
    assert (slider.minimum(), slider.maximum(), slider.value()) == (1, 10, 3)  # 1 to 10 s per board, default 3 s
    assert slider.height() >= theme.TARGET_H  # an operator target, the sketch's size T
    slider.setValue(2)
    assert json.loads((win.ctx.settings.root / "settings.json").read_text())["demo_pace_s"] == 2
    page = win.pages["Inspection"]
    assert isinstance(page, InspectionPage)
    starts: list[float] = []
    real = page.next_board

    def timed() -> None:
        starts.append(time.monotonic())
        real()

    page.next_board = timed  # type: ignore[method-assign]
    play_to_pause(qtbot, win)
    gaps = [b - a for a, b in zip(starts, starts[1:], strict=False)]
    assert len(starts) == 4 and min(gaps) >= 2 - 0.05, gaps  # each board 2 s after the one before
    assert records(win) == VERDICTS[:4]  # through the normal path: each board inspected and saved
    with pytest.raises(AoiError) as e:
        Settings.check("demo_pace_s", 11)
    assert e.value.code == "AOI-SET-008"
    win.close()


def test_req_set_009_a_queue_the_user_loads_plays_without_pace(qtbot: QtBot, bundle: Path) -> None:
    win = click(qtbot, station(qtbot).pages["Settings"].demo.btn_load)  # type: ignore[attr-defined]
    page = win.pages["Inspection"]
    assert isinstance(page, InspectionPage) and page.pace_s == 3
    win.navigate("Inspection")
    page._set_queue(sorted((win.ctx.settings.root / demo.BOARDS).glob("board_0[1-5].png")))
    assert page.pace_s is None
    started = time.monotonic()
    qtbot.mouseClick(page.btn_start, Qt.MouseButton.LeftButton)
    qtbot.waitUntil(lambda: not page.running and page.worker is None and page.queue_pos == 4, timeout=60000)
    assert time.monotonic() - started < 4 * 3  # no pace between the boards, and no pause at the NG one
    assert records(win)[3] == "NG"
    win.close()


def test_req_set_007_main_demo_starts_in_the_demo_workspace(bundle: Path, tmp_path: Path) -> None:
    station_folder = config.default_workspace()
    ctx = open_demo()
    assert ctx is not None
    try:
        assert ctx.settings.root == demo.demo_folder(station_folder) and demo.is_demo(ctx.settings.root)
        assert ctx.settings.last_page == "Inspection"
        assert not (station_folder / "settings.json").exists()  # the station's settings.json is not written
    finally:
        ctx.close()
    config.use_workspace(None)
    again = open_demo()  # after a crash: the demo as it was, not loaded again
    assert again is not None
    again.close()


def test_req_set_007_a_missing_bundle_is_refused_with_its_code(
    qtbot: QtBot, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, dialogs: list[tuple[str, str]]
) -> None:
    monkeypatch.setenv("AOI_DEMO_BUNDLE", str(tmp_path / "no-bundle"))
    win = station(qtbot)
    qtbot.mouseClick(win.pages["Settings"].demo.btn_load, Qt.MouseButton.LeftButton)  # type: ignore[attr-defined]
    assert shown_window() is win and not win.in_demo
    assert [t for t, _ in dialogs] and dialogs[-1][0].startswith("AOI-SET-015")
    assert not demo.demo_folder(win.ctx.settings.root).exists()
    win.close()


def test_req_set_007_reset_asks_first_and_no_keeps_the_demo(
    qtbot: QtBot, bundle: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    win = click(qtbot, station(qtbot).pages["Settings"].demo.btn_load)  # type: ignore[attr-defined]
    play_to_pause(qtbot, win)
    asked: list[str] = []

    def no(parent: object, title: str, text: str, *rest: object) -> QMessageBox.StandardButton:
        asked.append(text)
        return QMessageBox.StandardButton.No

    monkeypatch.setattr(QMessageBox, "question", staticmethod(no))
    win.navigate("Settings")
    reset = win.pages["Settings"].demo.btn_reset  # type: ignore[attr-defined]
    assert reset.objectName() == "danger" and not reset.autoDefault()  # red, never the default
    qtbot.mouseClick(reset, Qt.MouseButton.LeftButton)
    assert shown_window() is win and len(records(win)) == 4
    assert "Every result, record, alarm and log of the demo" in asked[0]
    win.close()


def test_req_set_007_the_demo_panel_keeps_its_buttons_whole_in_the_narrowest_window(qtbot: QtBot, bundle: Path) -> None:
    win = click(qtbot, station(qtbot).pages["Settings"].demo.btn_load)  # type: ignore[attr-defined]
    win.showNormal()
    win.resize(win.minimumSizeHint().width(), 1080)  # as narrow as the window goes: a presenter's smaller screen
    qtbot.waitUntil(lambda: win.width() == win.minimumSizeHint().width())
    panel = win.pages["Settings"].demo  # type: ignore[attr-defined]
    cut = [(b.text(), b.width(), b.sizeHint().width()) for b in panel.findChildren(QPushButton)
           if b.width() < b.sizeHint().width()]  # fmt: skip
    assert cut == []  # each label shown in full
    assert panel.btn_reset.y() > panel.btn_play.y()  # the red button on a row of its own, last
    win.close()
