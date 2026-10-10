"""REQ-INSP-005 and the 100 ms of REQ-INSP-002 on the Inspection page (stage S24).

Start, Stop, Next Board and Save Image… are actions that a key and a button share, each answers within 100 ms, and the
verdict is painted within 100 ms of the result. The keys are the sketch's (docs/sketches/inspection-run-controls.md,
PR #79): F5, F6, F8, F9, Ctrl+O, Ctrl+Shift+O and Alt+V, wherever the focus is on the page and only while the page is
shown. #120: one board is inspected at a time per page.
"""

from __future__ import annotations

import copy
import threading
from collections.abc import Callable, Iterator
from pathlib import Path
from time import perf_counter, sleep
from typing import Any

import numpy as np
import pytest
from PySide6.QtCore import QEvent, QObject, Qt
from PySide6.QtGui import QAction, QKeySequence
from PySide6.QtWidgets import QApplication, QFileDialog, QLabel, QMessageBox
from pytestqt.qtbot import QtBot

from aoi.core.imaging import list_images
from aoi.core.inspector import AI_OFF_NOTE, InspectionResult, Inspector
from aoi.core.recipe import ROI
from aoi.core.services import AppContext
from aoi.ui import theme
from aoi.ui.main_window import MainWindow
from aoi.ui.pages.inspection import NO_VERDICT, InspectionPage
from aoi.ui.widgets.image_view import ImageView
from tests.conftest import TINY_EPOCHS, TINY_IMAGE_SIZE, activated, another_version
from tests.test_req_done_in_v01 import BOARD, _button, _window
from tools.trainable import trainable

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
    win.set_user("admin")  # only an Admin exports (Q58, #151)
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
    qtbot.waitUntil(lambda: page._bg is None, timeout=30000)  # the save runs on the pool (#241)
    assert by_key.exists() and win.statusBar().currentMessage() == "Saved by_key.png"
    monkeypatch.setattr(QFileDialog, "getSaveFileName", staticmethod(lambda *a, **k: (str(by_button), "PNG (*.png)")))
    qtbot.mouseClick(page.btn_save, Qt.MouseButton.LeftButton)
    qtbot.waitUntil(lambda: page._bg is None, timeout=30000)
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
    and the verdict is on screen before that starts and before the result's save, which takes 150 ms here too."""
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
    monkeypatch.setattr(AppContext, "log_result", lambda *a, _r=AppContext.log_result: (sleep(0.15), _r(*a))[1])
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
    assert len(engine.done) == 2 and len(engine.builds) == 1, "the kept engine, still current, is used again (#243)"


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


def test_req_insp_005_a_board_model_change_stops_the_run(
    qtbot: QtBot, trained_ctx: AppContext, synthetic_dataset: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """#172: the header's board model changed while a run is on: the board in hand is saved under the run's board
    model, no board of the queue starts under the new one, and the status bar and the alarm log say so with
    AOI-INSP-012; the board in hand is not the last inspected board of the new board model."""
    trained_ctx.ensure_board_model("ZZZ")
    win = _window(qtbot, trained_ctx, "Operator")
    page = win.pages["Inspection"]
    assert isinstance(page, InspectionPage)
    win.navigate("Inspection")
    qtbot.waitUntil(trained_ctx.jobs.idle, timeout=10000)
    gate, started, real = threading.Event(), [], Inspector.inspect

    def inspect(engine: Inspector, image: np.ndarray) -> InspectionResult:
        started.append(perf_counter())
        assert len(started) != 2 or gate.wait(30), "the test did not release the second board"
        return real(engine, image)

    monkeypatch.setattr(Inspector, "inspect", inspect)
    page._set_queue(list_images(synthetic_dataset / "test" / "ok")[:4])
    page.start_run()
    qtbot.waitUntil(lambda: len(started) == 2, timeout=60000)  # the second board is in hand
    win.bm_combo.setCurrentText("ZZZ")  # a pick, or the mouse wheel over the box
    assert not page.running and page.worker is not None and not page.act_stop.isEnabled()
    assert win.statusBar().currentMessage().startswith("Run stopped: the board model changed from TINY to ZZZ.")
    assert trained_ctx.alarms()[0]["code"] == "AOI-INSP-012" and "AOI-INSP-012" in page.alarms.item(0).text()
    gate.set()
    qtbot.waitUntil(lambda: page.worker is None and trained_ctx.jobs.idle(), timeout=60000)
    assert [r["board_model"] for r in trained_ctx.inspections()] == [BOARD, BOARD], "the board in hand kept TINY"
    assert len(started) == 2 and page.queue_pos == 1 and not page.running
    assert page.last is None and page.last_id is None and win.last_inspected is None, "not ZZZ's last board"
    assert "inspected under board model TINY" in win.statusBar().currentMessage()
    assert page.verdict.text() == NO_VERDICT and page.view._pix is None, "the board in hand is cleared too (#243)"
    assert not _button(page, "Compare with Golden board ›").isEnabled() and not page.act_save.isEnabled()
    page.running, page.run_board_model = True, BOARD  # a run of TINY, should one reach Next Board under ZZZ
    page.next_board()
    assert page.worker is None and not page.running and len(started) == 2, "no board of it starts under ZZZ"


def test_req_insp_005_run_controls_off_without_a_board_model(
    qtbot: QtBot, ctx: AppContext, ng_board: Path, monkeypatch: pytest.MonkeyPatch, dialogs: list[tuple[str, str]]
) -> None:
    """#244: with no board model and images queued, Start and Next Board (their buttons, F5 and F8) were on for every
    role and opened a "Board model" message with no code that told an Operator to create or select a board model in the
    top bar, which an Operator cannot do. They are grey now; they come on when an Engineer creates the first board model
    without leaving the page, and go grey again when the header empties."""
    asked: list[tuple[str, str]] = []

    def record(parent: object, title: str, text: str, *buttons: object) -> QMessageBox.StandardButton:
        asked.append((title, text))
        return QMessageBox.StandardButton.Ok

    monkeypatch.setattr(QMessageBox, "information", staticmethod(record))
    win = MainWindow(ctx)  # an empty workspace: no board model
    qtbot.addWidget(win)
    win.show()
    qtbot.waitExposed(win)
    win.set_user("operator")
    page = win.pages["Inspection"]
    assert isinstance(page, InspectionPage)
    win.navigate("Inspection")
    assert win.board_model is None and ctx.role == "Operator" and page.empty.isVisible()
    page._set_queue([ng_board])
    controls = (page.act_start, page.act_next, page.btn_start, page.btn_next)
    assert [c.isEnabled() for c in controls] == [False] * 4, "Start and Next Board, buttons and keys, are grey"
    page.act_start.trigger()  # F5's action
    page.btn_next.click()  # F8's button
    assert (asked, dialogs, page.running, page.worker) == ([], [], False, None)
    win.set_user("engineer")
    ctx.ensure_board_model(BOARD)
    win._reload_board_models(BOARD)  # what + New does after the name dialog
    assert win.board_model == BOARD and win.stack.currentWidget() is page and page.queue == [ng_board]
    assert [c.isEnabled() for c in controls] == [True] * 4, "on once a board model is chosen, on the same page"
    win._on_board_model("")  # the header emptied
    assert [c.isEnabled() for c in controls] == [False] * 4


@pytest.mark.parametrize("press", ["next_board", "start_run"])
def test_req_insp_009_a_board_judged_after_a_board_model_change_is_cleared_with_a_lasting_line(
    qtbot: QtBot, trained_ctx: AppContext, synthetic_dataset: Path, monkeypatch: pytest.MonkeyPatch, press: str
) -> None:
    """#243: an NG board whose result arrives after the header's board model changed, by Next Board or in a run, is
    saved under the board model it was inspected under and cleared from the page as the board shown at the change is:
    the banner is idle, the picture and the defect list are empty, Compare with Golden board › and Save Image… are off,
    and the line under the banner names the board, its verdict and its board model, and in a run how to carry on with
    the queue, still on screen after the status bar's 8 s. Before, the board was painted in full under the new header
    while Compare and its defect rows did nothing, and the only explanation left the status bar after 8 s."""
    trained_ctx.ensure_board_model("ZZZ")
    win = _window(qtbot, trained_ctx, "Operator")
    page = win.pages["Inspection"]
    assert isinstance(page, InspectionPage)
    win.navigate("Inspection")
    qtbot.waitUntil(trained_ctx.jobs.idle, timeout=10000)
    gate, started, real = threading.Event(), [], Inspector.inspect

    def inspect(engine: Inspector, image: np.ndarray) -> InspectionResult:
        started.append(perf_counter())
        assert gate.wait(30), "the test did not release the board"
        return real(engine, image)

    monkeypatch.setattr(Inspector, "inspect", inspect)
    page._set_queue(list_images(synthetic_dataset / "test" / "ng")[:2])
    getattr(page, press)()
    qtbot.waitUntil(lambda: len(started) == 1, timeout=60000)  # the first board is in hand
    win.bm_combo.setCurrentText("ZZZ")
    gate.set()
    qtbot.waitUntil(lambda: page.worker is None and trained_ctx.jobs.idle(), timeout=60000)
    (rec,) = trained_ctx.inspections()
    assert (rec["board_model"], rec["result"]) == (BOARD, "NG") and rec["defect_count"] > 0, "a row to check"
    note = (
        f"{Path(rec['image_path']).name} was inspected under board model {BOARD} and judged NG; the header now shows"
        f" ZZZ. Its record is on Logs & Export under {BOARD}."
    )
    if press == "start_run":  # the change stopped the run, and the "Run stopped" line is replaced: how to carry on
        note += " The run stopped; press Start to carry on with the queue under ZZZ."
    qtbot.wait(8500)  # past the status bar's 8 s default
    compare = _button(page, "Compare with Golden board ›")
    shown = (page.verdict.text(), page.view._pix is None, page.table.rowCount(), compare.isEnabled())
    assert shown == (NO_VERDICT, True, 0, False), "the TINY board is not left on screen under ZZZ"
    assert not page.act_save.isEnabled() and page.last is None and page.last_id is None and win.last_inspected is None
    assert page.summary.text() == note and win.statusBar().currentMessage() == note
    qtbot.mouseClick(compare, Qt.MouseButton.LeftButton)
    assert win.stack.currentWidget() is page and len(started) == 1 and not page.running


def test_req_insp_009_a_board_cleared_after_a_board_model_change_keeps_the_line_of_a_run_that_moved(
    qtbot: QtBot, trained_ctx: AppContext, synthetic_dataset: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """#243 review: the last board of a run, in hand at a board model change, is also the run's first board judged
    against a new Golden board: it is cleared with both lines under the banner, the board model change's (no step to
    carry on, no board is left) and then the AOI-INSP-013 line, which the alarm log keeps too."""
    trained_ctx.ensure_board_model("ZZZ")
    win = _window(qtbot, trained_ctx, "Engineer")  # an Engineer sets the Golden board with Set Reference on Training
    page = win.pages["Inspection"]
    assert isinstance(page, InspectionPage)
    win.navigate("Inspection")
    qtbot.waitUntil(trained_ctx.jobs.idle, timeout=10000)
    started: list[str | None] = []
    held, real = {1: threading.Event(), 2: threading.Event()}, Inspector.inspect

    def inspect(engine: Inspector, image: np.ndarray) -> InspectionResult:
        started.append(engine.reference_path)
        assert held[len(started)].wait(30), "the test did not release the board"
        return real(engine, image)

    monkeypatch.setattr(Inspector, "inspect", inspect)
    boards = list_images(synthetic_dataset / "test" / "ok")[:2]
    page._set_queue(boards)
    page.start_run()
    qtbot.waitUntil(lambda: len(started) == 1, timeout=60000)  # board 1 is in hand
    golden = trained_ctx.samples(BOARD, "OK")[-1]
    trained_ctx.set_reference(BOARD, golden["id"])  # board 2 is judged against it
    held[1].set()
    qtbot.waitUntil(lambda: len(started) == 2, timeout=60000)  # board 2 is in hand
    win.bm_combo.setCurrentText("ZZZ")
    held[2].set()
    qtbot.waitUntil(lambda: page.worker is None and trained_ctx.jobs.idle(), timeout=60000)
    rec = trained_ctx.inspections()[0]
    assert Path(rec["image_path"]).name == boards[1].name and started[1] != started[0]
    cleared = (
        f"{boards[1].name} was inspected under board model {BOARD} and judged {rec['result']}; the header now shows"
        f" ZZZ. Its record is on Logs & Export under {BOARD}."
    )
    moved = (
        f"The AI model, recipe, scale or Golden board changed during this run: {boards[1].name} was judged with AI"
        f" model v1.0, recipe revision 1, Golden board {Path(golden['path']).name} and no scale; each record names the"
        " recipe revision and Golden board that judged it and the AI model version active then."
    )
    assert page.summary.text() == f"{cleared}\n{moved}" and win.statusBar().currentMessage() == cleared
    codes = [a["code"] for a in trained_ctx.alarms()]
    assert codes.count("AOI-INSP-013") == 1 and codes.count("AOI-INSP-012") == 1


def test_req_trn_010_a_board_started_after_an_activation_is_judged_by_the_active_ai_model(
    qtbot: QtBot, trained_ctx: AppContext, synthetic_dataset: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """#243: an AI model trained or activated while Inspection stays shown judges every board that starts after it,
    against the Golden board then in use: Next Board and Start on the queue already loaded, Start on a new queue. The
    board in hand at that moment keeps the engine it started with; a run in progress moves at its next board, with a
    line under the banner, while the status bar keeps the next board's busy line, and a WARN alarm AOI-INSP-013 naming
    the AI model now judging. An engine that is still current is used again, not built for each board. Before, the page
    kept its first board's engine until a revisit or a board model change, so every later board was judged by v1.0 and
    its Golden board while v1.1 was active."""
    win = _window(qtbot, trained_ctx, "Engineer")  # an Engineer trains and activates; the page stays on Inspection
    page = win.pages["Inspection"]
    assert isinstance(page, InspectionPage)
    win.navigate("Inspection")
    qtbot.waitUntil(trained_ctx.jobs.idle, timeout=10000)
    started: list[str | None] = []
    held = {6: threading.Event(), 8: threading.Event()}  # boards 6 and 8 wait for the test
    real, build = Inspector.inspect, AppContext.inspector

    def inspect(engine: Inspector, image: np.ndarray) -> InspectionResult:
        started.append(engine.model_version)
        if (gate := held.get(len(started))) is not None:
            assert gate.wait(30), "the test did not release the board"
        return real(engine, image)

    built_for: list[int] = []  # the board each engine build was for

    def built(ctx: AppContext, *args: Any, **kwargs: Any) -> Inspector:
        built_for.append(len(started) + 1)
        return build(ctx, *args, **kwargs)

    monkeypatch.setattr(Inspector, "inspect", inspect)
    monkeypatch.setattr(AppContext, "inspector", built)

    def run(press: Callable[[], None]) -> None:
        press()
        qtbot.waitUntil(lambda: page.worker is None and not page.running and trained_ctx.jobs.idle(), timeout=60000)

    def activate(version: str) -> None:  # one click on Training's version list, as an Engineer rolls back
        trained_ctx.activate_model(next(m["id"] for m in trained_ctx.models(BOARD) if m["version"] == version))

    boards = list_images(synthetic_dataset / "test" / "ok")[:8]
    page._set_queue(boards[:3])
    run(page.next_board)  # board 1 builds the engine with v1.0, and the page keeps it
    version = trainable(trained_ctx, BOARD)
    activated(
        trained_ctx, trained_ctx.train(version, epochs=TINY_EPOCHS, image_size=TINY_IMAGE_SIZE)
    )  # v1.1 and its Golden board are active
    run(page.next_board)  # board 2: Next Board on the queue already loaded
    activate("v1.0")  # v1.0 with its own Golden board (an activation switches both, REQ-TRN-010, S42)
    run(page.start_run)  # board 3: Start on the queue already loaded
    activate("v1.1")
    page._set_queue(boards[3:5])
    run(page.start_run)  # boards 4 and 5: Start on a new queue
    page._set_queue(boards[5:])
    page.start_run()
    qtbot.waitUntil(lambda: len(started) == 6, timeout=60000)  # board 6 is in hand
    activate("v1.0")
    held[6].set()
    qtbot.waitUntil(lambda: len(started) == 8, timeout=60000)  # board 7 is judged, board 8 is in hand
    g10, g11 = f"{BOARD}_v1.0_golden.png", f"{BOARD}_v1.1_golden.png"
    note = (
        f"The AI model, recipe, scale or Golden board changed during this run: {boards[6].name} was judged with AI"
        f" model v1.0, recipe revision 1, Golden board {g10} and no scale; each record names the recipe revision and"
        " Golden board that judged it and the AI model version active then."
    )
    assert page.summary.text() == f"Inspecting {boards[7].name}…\n{note}", "the run says it moved to v1.0"
    assert win.statusBar().currentMessage() == f"Inspecting {boards[7].name} (3 of 3)…", "the busy line stays"
    held[8].set()
    qtbot.waitUntil(lambda: page.worker is None and not page.running and trained_ctx.jobs.idle(), timeout=60000)

    def golden(iid: int) -> str:
        rec = trained_ctx.inspection(iid)
        return Path(rec["reference_path"]).name if rec and rec["reference_path"] else "none"

    judged = [(Path(r["image_path"]).name, r["model_version"], golden(r["id"])) for r in trained_ctx.inspections()]
    by = [("v1.0", g10), ("v1.1", g11), ("v1.0", g10), ("v1.1", g11), ("v1.1", g11), ("v1.1", g11)] + [
        ("v1.0", g10)
    ] * 2  # each activation brings its version's own Golden board (REQ-TRN-010, S42)
    assert judged[::-1] == [(b.name, *v) for b, v in zip(boards, by, strict=True)], "board 6 was in hand at activation"
    assert built_for == [1, 2, 3, 4, 6, 7], "boards 5 and 8 use the kept engine, which is still current"
    codes = [a["code"] for a in trained_ctx.alarms()]
    assert codes.count("AOI-INSP-013") == 1 and codes[0] == "AOI-INSP-013", "only the run that moved is alarmed"
    assert page.alarms.item(0).text().endswith(f"[WARN]  AOI-INSP-013  {note}")


@pytest.mark.parametrize("change", ["activate_ai_on", "activate", "reference", "scale", "scale_px", "roi", "roi_off"])
def test_req_trn_010_a_run_with_the_ai_check_off_moves_only_with_its_recipe_scale_or_golden_board(
    qtbot: QtBot, trained_ctx: AppContext, synthetic_dataset: Path, monkeypatch: pytest.MonkeyPatch, change: str
) -> None:
    """#243 with #246 (stack review): with the AI check off in the recipe no AI model judges a board, so an AI model
    activated while board 1 of a run is in hand ("activate") changes nothing that judges board 2: no AOI-INSP-013 and
    no line under the banner, while board 2's record names the version now active (#246 option (b)) and both records
    carry AI_OFF_NOTE. A Golden board set meanwhile ("reference") still moves the run, and its line and alarm say that
    the AI check was off and name no AI model; so does a scale set meanwhile ("scale", S29) while the recipe holds its
    minimum defect size in mm, which the scale sizes, or only an ROI in mm ("roi", S29 review), but not while it holds
    it in px ("scale_px"), which no scale changes, nor a disabled ROI in mm ("roi_off"). With the AI check on
    ("activate_ai_on", the control) the activation moves
    the run and its line names the version now active. Before, the activation under an AI-off recipe stored
    AOI-INSP-013 saying that board 2 "was judged with AI model v1.1", under the note that no AI model judged it, and the
    Golden board's line said "AI model v1.0"."""
    ctx = trained_ctx
    v11 = another_version(ctx, BOARD, "v1.1")
    recipe = copy.deepcopy(ctx.recipe(BOARD)[1])
    recipe.use_ai = change == "activate_ai_on"
    recipe.min_defect_mm = 0.5 if change == "scale" else None  # 445 px of area at 47.6 px/mm; 40 px with no scale
    recipe.rois = [ROI("R1", mm=[0, 0, 1, 1], enabled=change == "roi")] if change.startswith("roi") else recipe.rois
    revision = ctx.save_recipe(recipe)
    win = _window(qtbot, ctx, "Engineer")
    page = win.pages["Inspection"]
    assert isinstance(page, InspectionPage)
    win.navigate("Inspection")
    qtbot.waitUntil(ctx.jobs.idle, timeout=10000)
    started: list[str | None] = []
    gate, real = threading.Event(), Inspector.inspect

    def inspect(engine: Inspector, image: np.ndarray) -> InspectionResult:
        started.append(engine.model_version)
        assert len(started) > 1 or gate.wait(30), "the test did not release the board"
        return real(engine, image)

    monkeypatch.setattr(Inspector, "inspect", inspect)
    boards = list_images(synthetic_dataset / "test" / "ok")[:2]
    page._set_queue(boards)
    page.start_run()
    qtbot.waitUntil(lambda: len(started) == 1, timeout=60000)  # board 1 is in hand
    if change == "reference":
        ok = next(s for s in ctx.samples(BOARD, "OK") if s["path"] != ctx.reference_image(BOARD))
        ctx.set_reference(BOARD, ok["id"])
    elif change.startswith(("scale", "roi")):
        ctx.set_scale(BOARD, 476, 10)
    else:
        ctx.activate_model(v11)
    golden = Path(ctx.reference_image(BOARD) or "").name
    gate.set()
    qtbot.waitUntil(lambda: page.worker is None and not page.running and ctx.jobs.idle(), timeout=60000)
    records = ctx.inspections()[::-1]
    stored = [ctx.inspection_result(r["id"]) for r in records]
    judged = [(Path(r["image_path"]).name, r["model_version"], r["recipe_rev"]) for r in records]
    notes = [s.notes if s is not None else None for s in stored]
    alarms = [a["message"] for a in ctx.alarms() if a["code"] == "AOI-INSP-013"]
    print(change, judged, notes, alarms, page.summary.text(), sep="\n")
    version = "v1.1" if change.startswith("activate") else "v1.0"  # board 2's record names the version active then
    assert judged == [(boards[0].name, "v1.0", revision), (boards[1].name, version, revision)] and started[1] == version
    if change in ("activate", "scale_px", "roi_off"):
        assert notes == [[AI_OFF_NOTE]] * 2 and alarms == [], "no AI model, nor the scale, judged either board"
        assert "changed during this run" not in page.summary.text()
        return
    if change == "activate_ai_on":
        assert len(alarms) == 1 and AI_OFF_NOTE not in notes[1]
        said = f"{boards[1].name} was judged with AI model v1.1, recipe revision {revision}, Golden board {golden}"
        moved = "The AI model, recipe, scale or Golden board changed during this run:"
        assert alarms[0].startswith(f"{moved} {said} and no scale;")
        return
    scale = "a scale of 47.60 px/mm" if change in ("scale", "roi") else "no scale"  # the board model's at board 2
    line = (
        f"The recipe, scale or Golden board changed during this run: {boards[1].name} was judged with the AI check off,"
        f" recipe revision {revision}, Golden board {golden} and {scale}; each record names the recipe revision and"
        " Golden board that judged it and the AI model version active then."
    )
    assert notes == [[AI_OFF_NOTE]] * 2 and alarms == [line] and page.summary.text().endswith(f"\n{line}")
    assert page.alarms.item(0).text().endswith(f"[WARN]  AOI-INSP-013  {line}")


def test_req_insp_006_a_board_model_with_no_ai_model_is_alarmed_once_per_page_visit(
    qtbot: QtBot, trained_ctx: AppContext, synthetic_dataset: Path
) -> None:
    """#243 review: on a board model with a Golden board and no AI model, AOI-TRN-003 is stored once per page visit, as
    before #243, and not again for the engine each new queue builds: Load Images… or Load Folder… on such a board model
    would otherwise add a WARN row each time and push real alarms out of the alarm log's ALARM_LIMIT rows."""
    trained_ctx.ensure_board_model("ZZZ")
    trained_ctx.set_reference("ZZZ", trained_ctx.samples(BOARD, "OK")[0]["id"])
    win = _window(qtbot, trained_ctx, "Operator")
    page = win.pages["Inspection"]
    assert isinstance(page, InspectionPage)
    win.navigate("Inspection")
    win.bm_combo.setCurrentText("ZZZ")
    qtbot.waitUntil(trained_ctx.jobs.idle, timeout=10000)
    oks = list_images(synthetic_dataset / "test" / "ok")

    def queue(*boards: Path) -> None:  # a new queue, each board by Next Board
        page._set_queue(list(boards))
        for _ in boards:
            page.next_board()
            qtbot.waitUntil(lambda: page.worker is None and trained_ctx.jobs.idle(), timeout=60000)

    def warned() -> int:
        return [a["code"] for a in trained_ctx.alarms()].count("AOI-TRN-003")

    queue(oks[0], oks[1])
    queue(oks[2])
    queue(oks[3])
    assert len(trained_ctx.inspections()) == 4 and warned() == 1, "one AOI-TRN-003 for three queues on one visit"
    win.navigate("Home")
    win.navigate("Inspection")
    queue(oks[4])
    assert warned() == 2, "a new visit says it once more"
