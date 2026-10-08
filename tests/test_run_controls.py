"""REQ-INSP-005 and the 100 ms of REQ-INSP-002 on the Inspection page (stage S24).

Start, Stop, Next Board and Save Image… are actions that a key and a button share, each answers within 100 ms, and the
verdict is painted within 100 ms of the result. The keys are the sketch's (docs/sketches/inspection-run-controls.md,
PR #79): F5, F6, F8, F9, Ctrl+O, Ctrl+Shift+O and Alt+V, wherever the focus is on the page and only while the page is
shown. #120: one board is inspected at a time per page.
"""

from __future__ import annotations

import threading
from collections.abc import Iterator
from pathlib import Path
from time import perf_counter, sleep
from typing import Any

import numpy as np
import pytest
from PySide6.QtCore import QEvent, QObject, Qt
from PySide6.QtGui import QAction, QKeySequence
from PySide6.QtWidgets import QApplication, QFileDialog, QLabel
from pytestqt.qtbot import QtBot

from aoi.core.imaging import list_images
from aoi.core.inspector import InspectionResult, Inspector
from aoi.core.services import AppContext
from aoi.ui import theme
from aoi.ui.main_window import MainWindow
from aoi.ui.pages.inspection import InspectionPage
from aoi.ui.widgets.image_view import ImageView
from tests.test_req_done_in_v01 import _window

BUDGET_S = 0.1  # REQ-INSP-005: a response within 100 ms; REQ-INSP-002: the verdict within 100 ms of the result
MIN_W, MIN_H = 120, theme.RUN_CONTROL_H  # the plan's 120 px wide; the sketch's T+, 56 px tall


class HeldEngine:
    """`AppContext.inspector` and `Inspector.inspect` under the test's control: each waits for `release()` before it
    runs, so the page can be seen while an engine is built or a board is inspected for as long as the test needs, and
    the times are recorded on the pool thread. A build on the window's thread hangs the test instead of slowing it.
    Installed by the `engine` fixture once the window is up, so what it holds and counts is the test's own work."""

    def __init__(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self.gate = threading.Event()
        self.builds: list[float] = []
        self.started: list[float] = []
        self.done: list[float] = []
        real_build, real = AppContext.inspector, Inspector.inspect

        def build(ctx: AppContext, *args: Any, **kwargs: Any) -> Inspector:
            self.builds.append(perf_counter())
            assert self.gate.wait(30), "the test did not release the engine build"
            return real_build(ctx, *args, **kwargs)

        def inspect(engine: Inspector, image: np.ndarray) -> InspectionResult:
            self.started.append(perf_counter())
            assert self.gate.wait(30), "the test did not release the board"
            res = real(engine, image)
            self.done.append(perf_counter())
            return res

        monkeypatch.setattr(AppContext, "inspector", build)
        monkeypatch.setattr(Inspector, "inspect", inspect)

    def hold(self) -> None:
        self.gate.clear()

    def release(self) -> None:
        self.gate.set()


class PaintWatch(QObject):
    """Records (time, text) each time `label` is painted: what the operator saw, and when."""

    def __init__(self, label: QLabel) -> None:
        super().__init__(label)
        self.label = label
        self.paints: list[tuple[float, str]] = []
        label.installEventFilter(self)

    def eventFilter(self, obj: QObject, event: QEvent) -> bool:
        if event.type() == QEvent.Type.Paint:
            self.paints.append((perf_counter(), self.label.text()))
        return False

    def first(self, text: str) -> float:
        """When `text` was first painted."""
        return next(t for t, painted in self.paints if painted == text)


@pytest.fixture
def inspection(qtbot: QtBot, trained_ctx: AppContext) -> tuple[MainWindow, InspectionPage]:
    """The window on the Inspection page as the Operator, the focus on the defect list, and the start-up work on the
    pool (the Compare page loads the golden board) done."""
    win = _window(qtbot, trained_ctx, "Operator")
    page = win.pages["Inspection"]
    win.navigate("Inspection")
    QApplication.processEvents()  # lay the page out, so the buttons have their size
    page.table.setFocus()  # the focus is on the defect list: a key still reaches the page's actions
    qtbot.waitUntil(trained_ctx.jobs.idle, timeout=10000)
    return win, page


@pytest.fixture
def engine(inspection: tuple[MainWindow, InspectionPage], monkeypatch: pytest.MonkeyPatch) -> Iterator[HeldEngine]:
    """Installed once the window is up and idle, so the builds and inspections it holds and counts are the test's."""
    held = HeldEngine(monkeypatch)
    yield held
    held.release()  # a test that failed while holding leaves no pool thread waiting 30 s into the next test


def press(qtbot: QtBot, win: MainWindow, action: QAction) -> None:
    """Press the key the action's button shows, as the operator reads it: F8 for Next Board."""
    combo = action.shortcut()[0]
    qtbot.keyClick(win, combo.key(), combo.keyboardModifiers())


def test_req_insp_005_keys_and_buttons_do_the_same(
    qtbot: QtBot,
    inspection: tuple[MainWindow, InspectionPage],
    ng_board: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    engine: HeldEngine,
) -> None:
    """Each run control is one action behind a 120 × 56 px button labelled with its key and the key itself (the
    sketch's table): F8 and the Next Board button each inspect one board, F5 runs the queue, F6 stops it after the board
    in hand, F9 saves the picture; Ctrl+O and Ctrl+Shift+O load, Alt+V cycles the view. A key works with the focus
    anywhere on the page and does nothing from another page."""
    engine.release()
    win, page = inspection
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
    assert page.view_combo.currentData() == "Side" and win.statusBar().currentMessage() == "View: Side"
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
    assert win.statusBar().currentMessage() == "Stopping after this board…"
    engine.release()
    qtbot.waitUntil(lambda: page.worker is None, timeout=30000)
    assert page.worker is None and page.queue_pos == 0 and len(engine.done) == 6, "the board in hand finished; no more"
    assert page.act_start.isEnabled() and page.act_next.isEnabled()


def test_req_insp_005_feedback_within_100_ms(
    qtbot: QtBot, inspection: tuple[MainWindow, InspectionPage], ng_board: Path, engine: HeldEngine
) -> None:
    """Next Board, Start and Stop answer within 100 ms and before any result: the banner is painted grey with
    "Inspecting…" within the key press itself, the controls that cannot act go grey with their keys, and the status bar
    names the board and its place in the queue; Stop says it waits for the board in hand. The engine is held, build
    and inspection alike, so the response cannot be the result, and a first-board engine build on the window's thread
    would hang the press rather than slow it."""
    win, page = inspection
    watch = PaintWatch(page.verdict)
    page._set_queue([ng_board, ng_board])
    t0 = perf_counter()
    press(qtbot, win, page.act_next)
    took = perf_counter() - t0
    assert took < BUDGET_S, f"F8 returned after {took * 1000:.0f} ms"
    assert page.last is None and page.worker is not None and page.inspector is None, "no result, no engine yet"
    assert page.verdict.text() == "Inspecting…" and theme.INFO_COLOR in page.verdict.styleSheet()
    painted = watch.first("Inspecting…") - t0
    print(f"F8: returned after {took * 1000:.1f} ms, busy banner painted after {painted * 1000:.1f} ms")
    assert painted < BUDGET_S, "the busy banner was not painted within the key press"
    assert not page.act_next.isEnabled() and not page.btn_next.isEnabled() and not page.btn_start.isEnabled()
    assert page.summary.text() == f"Inspecting {ng_board.name}…"
    assert win.statusBar().currentMessage() == f"Inspecting {ng_board.name} (1 of 2)…"
    qtbot.waitUntil(lambda: len(engine.builds) == 1, timeout=10000)  # the build is on the pool thread, after the press
    engine.release()
    qtbot.waitUntil(lambda: page.worker is None, timeout=60000)
    assert page.last is not None and page.inspector is not None

    engine.hold()
    t0 = perf_counter()
    press(qtbot, win, page.act_start)
    took = perf_counter() - t0
    print(f"F5: returned after {took * 1000:.1f} ms")
    assert took < BUDGET_S, f"F5 returned after {took * 1000:.0f} ms"
    assert page.running and page.act_stop.isEnabled() and not page.act_start.isEnabled() and page.worker is not None
    assert page.verdict.text() == "Inspecting…" and watch.paints[-1][1] == "Inspecting…"
    assert win.statusBar().currentMessage() == f"Inspecting {ng_board.name} (2 of 2)…"
    t0 = perf_counter()
    press(qtbot, win, page.act_stop)
    took = perf_counter() - t0
    print(f"F6: returned after {took * 1000:.1f} ms")
    assert took < BUDGET_S, f"F6 returned after {took * 1000:.0f} ms"
    assert not page.running and not page.act_stop.isEnabled() and not page.btn_stop.isEnabled()
    assert win.statusBar().currentMessage() == "Stopping after this board…"
    engine.release()
    qtbot.waitUntil(lambda: page.worker is None, timeout=60000)
    assert page.queue_pos == 1 and page.verdict.text() == theme.verdict_label(page.last.verdict)


def test_req_insp_002_verdict_shown_within_100_ms_of_result(
    qtbot: QtBot,
    inspection: tuple[MainWindow, InspectionPage],
    ng_board: Path,
    engine: HeldEngine,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The verdict banner, colour and word, is painted within 100 ms of the engine's result and before the image and
    the defect table are built from it: here the image takes 150 ms to build, as a large board on a slow station might,
    and the verdict is on screen before that starts."""
    engine.release()
    win, page = inspection
    watch = PaintWatch(page.verdict)
    image_built: list[float] = []
    real = ImageView.set_image

    def slow(view: ImageView, img: np.ndarray, keep_view: bool = False) -> None:
        if view is page.view:  # the other pages' views keep their speed
            image_built.append(perf_counter())
            sleep(0.15)
        real(view, img, keep_view=keep_view)

    monkeypatch.setattr(ImageView, "set_image", slow)
    page._set_queue([ng_board])
    press(qtbot, win, page.act_next)
    qtbot.waitUntil(lambda: page.worker is None, timeout=60000)
    res = page.last
    assert res is not None and res.verdict == "NG" and page.view._pix is not None and len(image_built) == 1
    (done,) = engine.done
    shown = watch.first(theme.verdict_label(res.verdict))
    after, before = (shown - done) * 1000, (image_built[0] - shown) * 1000
    print(f"verdict painted {after:.1f} ms after the result, {before:.1f} ms before the image")
    assert shown - done < BUDGET_S, f"the verdict was painted {(shown - done) * 1000:.0f} ms after the result"
    assert shown < image_built[0], "the verdict is painted before the image is built"
    assert theme.NG_COLOR in page.verdict.styleSheet() and page.verdict.text() == "✗ NG"


def test_issue_120_start_waits_while_a_board_is_inspected(
    qtbot: QtBot, inspection: tuple[MainWindow, InspectionPage], ng_board: Path, engine: HeldEngine
) -> None:
    """While a board is being inspected, Start and Next Board are disabled and their keys and buttons do nothing, so one
    inspection runs at a time per page and every board is inspected once (#120); once the board is done, they act
    again."""
    win, page = inspection
    page._set_queue([ng_board, ng_board, ng_board])
    press(qtbot, win, page.act_next)
    w = page.worker
    assert w is not None and not page.act_start.isEnabled() and not page.act_next.isEnabled()
    qtbot.waitUntil(lambda: len(engine.builds) == 1, timeout=10000)  # the first board builds the engine, on the pool
    for act in (page.act_start, page.act_next):
        press(qtbot, win, act)
        act.trigger()
    qtbot.mouseClick(page.btn_start, Qt.MouseButton.LeftButton)
    qtbot.mouseClick(page.btn_next, Qt.MouseButton.LeftButton)
    assert page.worker is w and page.queue_pos == 0 and not page.running and len(engine.builds) == 1
    engine.release()
    qtbot.waitUntil(lambda: page.worker is None, timeout=30000)
    assert page.queue_pos == 0 and len(engine.started) == 1 and page.last_path == ng_board
    assert page.act_start.isEnabled() and page.act_next.isEnabled()
    press(qtbot, win, page.act_next)
    assert page.worker is not None and page.queue_pos == 1
    qtbot.waitUntil(lambda: page.worker is None, timeout=30000)
    assert len(engine.done) == 2


def test_req_insp_005_an_engine_built_for_the_state_before_is_dropped(
    qtbot: QtBot, inspection: tuple[MainWindow, InspectionPage], ng_board: Path, engine: HeldEngine
) -> None:
    """A page revisit, or a board model change, while the first board builds its engine drops that engine when it
    arrives, so the next board is inspected with the current model, recipe and golden board and not with those of the
    state before (the S24 review's finding B2)."""
    win, page = inspection
    page._set_queue([ng_board, ng_board])
    press(qtbot, win, page.act_next)
    qtbot.waitUntil(lambda: len(engine.builds) == 1, timeout=10000)
    win.navigate("Home")  # the operator looks elsewhere and comes back while the engine is being built
    win.navigate("Inspection")
    engine.release()
    qtbot.waitUntil(lambda: page.worker is None, timeout=30000)
    assert page.last is not None and page.inspector is None, "the engine built before the revisit is not kept"
    press(qtbot, win, page.act_next)
    qtbot.waitUntil(lambda: page.worker is None, timeout=30000)
    assert len(engine.builds) == 2 and page.inspector is not None, "the next board built the engine again"
