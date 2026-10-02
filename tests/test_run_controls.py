"""REQ-INSP-005 on the Inspection page (stage S24a; the 100 ms budgets are measured in S24b).

Start, Stop, Next Board and Save Result are actions that a key and a button share. The keys are the sketch's
(docs/sketches/inspection-run-controls.md, PR #79): F5, F6, F8, F9, Ctrl+O, Ctrl+Shift+O and Alt+V, wherever the focus
is on the page and only while the page is shown. #120: one board is inspected at a time per page.
"""

from __future__ import annotations

import threading
from pathlib import Path
from time import perf_counter

import numpy as np
import pytest
from PySide6.QtCore import Qt
from PySide6.QtGui import QAction, QKeySequence
from PySide6.QtWidgets import QApplication, QFileDialog
from pytestqt.qtbot import QtBot

from aoi.core.imaging import list_images
from aoi.core.inspector import InspectionResult, Inspector
from aoi.core.services import AppContext
from aoi.ui import theme
from aoi.ui.main_window import MainWindow
from aoi.ui.pages.inspection import InspectionPage
from tests.test_req_done_in_v01 import _window

MIN_W, MIN_H = 120, theme.RUN_CONTROL_H  # the plan's 120 px wide; the sketch's T+, 56 px tall


class HeldEngine:
    """`Inspector.inspect` under the test's control: it waits for `release()` before it runs, so the page can be seen
    while a board is being inspected for as long as the test needs, and the times each inspection started and returned
    are recorded on the pool thread."""

    def __init__(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self.gate = threading.Event()
        self.started: list[float] = []
        self.done: list[float] = []
        real = Inspector.inspect

        def inspect(engine: Inspector, image: np.ndarray) -> InspectionResult:
            self.started.append(perf_counter())
            assert self.gate.wait(30), "the test did not release the board"
            res = real(engine, image)
            self.done.append(perf_counter())
            return res

        monkeypatch.setattr(Inspector, "inspect", inspect)

    def hold(self) -> None:
        self.gate.clear()

    def release(self) -> None:
        self.gate.set()


@pytest.fixture
def engine(monkeypatch: pytest.MonkeyPatch) -> HeldEngine:
    return HeldEngine(monkeypatch)


def inspection(qtbot: QtBot, ctx: AppContext) -> tuple[MainWindow, InspectionPage]:
    win = _window(qtbot, ctx, "Operator")
    page = win.pages["Inspection"]
    win.navigate("Inspection")
    QApplication.processEvents()  # lay the page out, so the buttons have their size
    page.table.setFocus()  # the focus is on the defect list: a key still reaches the page's actions
    return win, page


def press(qtbot: QtBot, win: MainWindow, action: QAction) -> None:
    """Press the key the action's button shows, as the operator reads it: F8 for Next Board."""
    combo = action.shortcut()[0]
    qtbot.keyClick(win, combo.key(), combo.keyboardModifiers())


def test_req_insp_005_keys_and_buttons_do_the_same(
    qtbot: QtBot,
    trained_ctx: AppContext,
    ng_board: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    engine: HeldEngine,
) -> None:
    """Each run control is one action behind a 120 × 56 px button labelled with its key and the key itself (the
    sketch's table): F8 and the Next Board button each inspect one board, F5 runs the queue, F6 stops it after the board
    in hand, F9 saves the result; Ctrl+O and Ctrl+Shift+O load, Alt+V cycles the view. A key works with the focus
    anywhere on the page and does nothing from another page."""
    engine.release()
    win, page = inspection(qtbot, trained_ctx)
    controls = {page.act_start: page.btn_start, page.act_stop: page.btn_stop, page.act_next: page.btn_next}
    controls[page.act_save] = page.btn_save
    for act, b in controls.items():
        key = act.shortcut().toString(QKeySequence.SequenceFormat.NativeText)
        assert b.text() == f"{act.text()}  {key}" and b.isEnabled() == act.isEnabled(), b.text()
        assert b.width() >= MIN_W and b.height() >= MIN_H, (b.text(), b.width(), b.height())
    assert [a.shortcut().toString() for a in controls] == ["F5", "F6", "F8", "F9"]
    assert page.act_load.shortcut() == QKeySequence(QKeySequence.StandardKey.Open)  # Ctrl+O on Windows and Linux
    native = page.act_load.shortcut().toString(QKeySequence.SequenceFormat.NativeText)
    assert page.btn_load.text() == "Load Images…" and page.btn_load.toolTip() == native, "the key is the tooltip"
    assert page.btn_load.height() >= theme.TARGET_H and page.view_combo.height() >= theme.TARGET_H
    assert not page.act_next.isEnabled() and not page.act_save.isEnabled(), "nothing queued, nothing to save"

    folder = ng_board.parent
    monkeypatch.setattr(QFileDialog, "getOpenFileNames", staticmethod(lambda *a, **k: ([str(ng_board)], "")))
    monkeypatch.setattr(QFileDialog, "getExistingDirectory", staticmethod(lambda *a, **k: str(folder)))
    press(qtbot, win, page.act_load)
    assert page.queue == [ng_board]
    press(qtbot, win, page.act_folder)
    assert page.queue == list_images(folder) and len(page.queue) > 1
    press(qtbot, win, page.act_view)
    assert page.view_combo.currentData() == "Side"
    press(qtbot, win, page.act_view)
    press(qtbot, win, page.act_view)
    assert page.view_combo.currentData() == "Top"

    win.navigate("Home")
    press(qtbot, win, page.act_next)
    assert page.worker is None and page.queue_pos == -1, "F8 on another page does nothing"
    win.navigate("Inspection")
    page._set_queue([ng_board, ng_board, ng_board])
    press(qtbot, win, page.act_next)
    assert page.worker is not None and page.queue_pos == 0, "F8 inspects the next board"
    qtbot.waitUntil(lambda: page.worker is None, timeout=30000)
    assert page.last is not None and page.last_path == ng_board and len(engine.done) == 1
    qtbot.mouseClick(page.btn_next, Qt.MouseButton.LeftButton)
    assert page.worker is not None and page.queue_pos == 1, "the button inspects the next board"
    qtbot.waitUntil(lambda: page.worker is None, timeout=30000)
    assert len(engine.done) == 2

    by_key, by_button = tmp_path / "by_key.png", tmp_path / "by_button.png"
    monkeypatch.setattr(QFileDialog, "getSaveFileName", staticmethod(lambda *a, **k: (str(by_key), "PNG (*.png)")))
    press(qtbot, win, page.act_save)
    assert by_key.exists() and win.statusBar().currentMessage() == "Saved by_key.png"
    monkeypatch.setattr(QFileDialog, "getSaveFileName", staticmethod(lambda *a, **k: (str(by_button), "PNG (*.png)")))
    qtbot.mouseClick(page.btn_save, Qt.MouseButton.LeftButton)
    assert by_button.exists()

    page._set_queue([ng_board, ng_board, ng_board])
    press(qtbot, win, page.act_start)
    assert page.running and page.act_stop.isEnabled() and not page.act_start.isEnabled(), "F5 runs the queue"
    qtbot.waitUntil(lambda: not page.running, timeout=60000)
    assert page.queue_pos == 2 and len(engine.done) == 5 and win.statusBar().currentMessage() == "End of queue"

    engine.hold()
    page._set_queue([ng_board, ng_board, ng_board])
    qtbot.mouseClick(page.btn_start, Qt.MouseButton.LeftButton)
    assert page.running and page.worker is not None, "the button runs the queue"
    press(qtbot, win, page.act_stop)
    assert not page.running and not page.act_stop.isEnabled(), "F6 stops the run"
    engine.release()
    qtbot.waitUntil(lambda: page.worker is None, timeout=30000)
    assert page.worker is None and page.queue_pos == 0 and len(engine.done) == 6, "the board in hand finished; no more"
    assert page.act_start.isEnabled() and page.act_next.isEnabled()


def test_issue_120_start_waits_while_a_board_is_inspected(
    qtbot: QtBot, trained_ctx: AppContext, ng_board: Path, engine: HeldEngine
) -> None:
    """While a board is being inspected, Start and Next Board are disabled and their keys and buttons do nothing, so one
    inspection runs at a time per page and every board is inspected once (#120); once the board is done, they act
    again."""
    win, page = inspection(qtbot, trained_ctx)
    page._set_queue([ng_board, ng_board, ng_board])
    press(qtbot, win, page.act_next)
    w = page.worker
    assert w is not None and not page.act_start.isEnabled() and not page.act_next.isEnabled()
    qtbot.waitUntil(lambda: len(engine.started) == 1, timeout=10000)
    for act in (page.act_start, page.act_next):
        press(qtbot, win, act)
        act.trigger()
    qtbot.mouseClick(page.btn_start, Qt.MouseButton.LeftButton)
    qtbot.mouseClick(page.btn_next, Qt.MouseButton.LeftButton)
    assert page.worker is w and page.queue_pos == 0 and not page.running and len(engine.started) == 1
    engine.release()
    qtbot.waitUntil(lambda: page.worker is None, timeout=30000)
    assert page.queue_pos == 0 and len(engine.started) == 1 and page.last_path == ng_board
    assert page.act_start.isEnabled() and page.act_next.isEnabled()
    press(qtbot, win, page.act_next)
    assert page.worker is not None and page.queue_pos == 1
    qtbot.waitUntil(lambda: page.worker is None, timeout=30000)
    assert len(engine.done) == 2
