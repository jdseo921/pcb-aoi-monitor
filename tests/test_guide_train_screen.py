"""REQ-TRN-021 for B5 of the 2026-10 business-readiness brief (D4; docs/sketches/first-run-guide.md, Q72 to Q74): the
first-run guide's screen 3 on Home, for a board model whose images are in and boxed until its first board is inspected.
It says what is ready and what Train does, asks the board revision, and Train (Enter) runs the five parts as the
context's one training run, with one line and Cancel; then it shows what Train made, read again after a restart, and
hands over to Inspection, Logs & Export and Training. Results on synthetic boards prove the code path only; none is
quoted as accuracy."""

from __future__ import annotations

from pathlib import Path
from typing import Any, cast

import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QFileDialog
from pytestqt.qtbot import QtBot

from aoi.core.jobs import Job
from aoi.core.services import AppContext
from aoi.errors import AoiError
from aoi.ui.main_window import HomePage, MainWindow
from aoi.ui.pages.guide import FirstRunGuide
from aoi.ui.pages.guide_train import GuideTrain
from aoi.ui.pages.inspection import InspectionPage
from aoi.ui.pages.logs import LogsPage
from aoi.ui.pages.training import TrainingPage
from tests.test_first_board_model_store import shell
from tests.test_trial_versions import ONE, one_person

TRAINED = "✓ 1 Board model  ───  ✓ 2 Images  ───  ✓ 3 Train"


def ready(ctx: AppContext, folder: Path) -> None:
    """ONE-1's 80 OK and 20 NG images of the Top view, each NG one boxed, in Acme's store (`one_person`), the run kept
    short and the shift check asked for every 12 hours."""
    one_person(ctx, folder)
    ctx.set_user("engineer")
    ctx.settings.default_epochs, ctx.settings.image_size, ctx.settings.shift_check_hours = 1, 32, 12


def home(qtbot: QtBot, ctx: AppContext, role: str = "engineer") -> tuple[MainWindow, FirstRunGuide, GuideTrain]:
    win = shell(qtbot, ctx, role)
    win.select_board_model(ONE)
    win.navigate("Home")
    guide = cast(HomePage, win.pages["Home"]).guide
    return win, guide, guide.train_step


def trained(qtbot: QtBot, screen: GuideTrain) -> None:
    """Train pressed, and its end waited for."""
    screen.btn_train.click()
    qtbot.waitUntil(lambda: screen.worker is None and not screen.ctx.guide_running(ONE), timeout=180000)


def test_req_trn_021_screen_3_trains_and_shows_what_it_made(qtbot: QtBot, ctx: AppContext, tmp_path: Path) -> None:
    """With the images in and boxed, screen 3 shows itself with Train focused and says what is ready and what Train
    does, with the images it keeps apart and trains on. Enter runs Train, its line saying the part, the percent and the
    time left; then the screen says which AI model judges the board model's boards, the images it was trained on and
    kept apart, its missed defects and false calls counts first, the Trial line and the shift check, and step 3 is
    done. The board revision typed is the one Train froze."""
    ready(ctx, tmp_path / "boards")
    win, guide, screen = home(qtbot, ctx)
    assert guide.isVisible() and screen.isVisible() and screen.before.isVisible() and not screen.result.isVisible()
    assert guide.steps.text() == "✓ 1 Board model  ───  ✓ 2 Images  ───  ● 3 Train"
    assert screen.ready.text() == "80 OK and 20 NG images of the Top view are ready, every defect boxed."
    assert screen.plan.text().startswith(
        "Train keeps 50 OK and 6 NG images apart, trains the AI model on the other 30 OK and 14 NG as a Trial, since"
        " one person labelled them, makes it the AI model that judges ONE-1's boards, tests it on the images kept"
        " apart and runs the first shift check."
    )
    assert screen.revision.text() == "R1" and win.focusWidget() is screen.btn_train
    screen.revision.setText("R2")
    lines: list[str] = []
    win.activateWindow()
    qtbot.waitUntil(lambda: QApplication.activeWindow() is win)
    qtbot.keyClick(screen.btn_train, Qt.Key.Key_Return)
    assert screen.worker is not None and screen.run_row.isVisible() and not screen.btn_train.isEnabled()
    screen.worker.signals.progress.connect(lambda _v: lines.append(screen.run_line.text()))
    qtbot.waitUntil(lambda: screen.worker is None, timeout=180000)
    assert any(line.startswith("Training the AI model: round 1 of 1 · ") for line in lines), lines
    assert all(" % · " in line for line in lines)
    assert screen.result.isVisible() and not screen.before.isVisible() and guide.steps.text() == TRAINED
    assert screen.done_line.text() == "✓ AI model v1.0 (Trial) judges ONE-1's boards."
    assert screen.trained_line.text() == "Trained on 30 OK and 14 NG images. On the 50 OK and 6 NG images kept apart:"
    assert screen.missed.text().startswith("Missed defects  ") and " of 6, 95 % upper bound " in screen.missed.text()
    assert (
        screen.false_calls.text().startswith("False calls  ")
        and " of 50, 95 % upper bound " in screen.false_calls.text()
    )
    assert not screen.untested.isVisible()
    shift = screen.shift_line.text()
    assert shift.startswith("✓ Shift check: every verdict right · boards may be inspected until ") or shift.startswith(
        "Shift check of ONE-1: "
    ), shift
    assert screen.shift_next.isVisible() == shift.startswith("Shift check of ONE-1: ")
    assert [v["revision"] for v in ctx.db.datasets(ONE)] == ["R2"]
    assert "Enter   Inspect a Board…" in win.keys_text()


def test_req_trn_021_what_train_made_after_a_restart_and_the_handover(
    qtbot: QtBot, ctx: AppContext, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Train's result is read again from the workspace, as after a restart. Open Logs & Export › shows the board model's
    history and Start the Checks › Training's What is missing with Validated picked. Inspect a Board… opens Load
    Images… on the folder above screen 2's, in the view Train trained on, and inspects the board picked at once; then
    Home shows its cards. A test or a shift check that did not run is said."""
    ready(ctx, tmp_path / "boards")
    ctx.guide_train(ONE, "Top", "R1")
    win, guide, screen = home(qtbot, ctx)
    assert screen.result.isVisible() and guide.steps.text() == TRAINED and win.focusWidget() is screen.btn_inspect
    screen.btn_logs.click()
    logs = cast(LogsPage, win.pages["Logs & Export"])
    assert win.stack.currentWidget() is logs and logs.model.currentData() == ONE
    win.navigate("Home")
    screen.btn_checks.click()
    training = cast(TrainingPage, win.pages["Training"])
    assert win.stack.currentWidget() is training and training.tabs.currentIndex() == 2
    assert training.missing_list.validated.isChecked() and not training.missing_list.missing.trial  # type: ignore[union-attr]
    ctx.db.execute("DELETE FROM test_runs")
    ctx.db.execute("DELETE FROM shift_checks")
    win.navigate("Home")
    assert screen.untested.text() == "Not tested yet on the 50 OK and 6 NG images kept apart: AI Model Test tests it."
    assert screen.untested.isVisible() and not screen.missed.isVisible()
    assert screen.shift_line.text() == (
        "No shift check counts now: Inspection asks for Shift Check (F7) before the first board."
    )
    ctx.settings.shift_check_hours = 0  # off: the first board needs none
    guide.images.folder = str(tmp_path / "boards" / "TBOX")  # screen 2's folder in this session
    asked: list[str] = []
    board = sorted((tmp_path / "boards").glob("*.png"))[0]

    def picked(parent: Any, title: str, folder: str, kinds: str) -> tuple[list[str], str]:
        asked.append(folder)
        return [str(board)], kinds

    monkeypatch.setattr(QFileDialog, "getOpenFileNames", staticmethod(picked))
    cast(HomePage, win.pages["Home"]).on_show()  # Home read again, as a page shown again reads it
    assert screen.shift_line.isHidden()
    win.activateWindow()
    qtbot.waitUntil(lambda: QApplication.activeWindow() is win)
    qtbot.keyClick(screen.btn_inspect, Qt.Key.Key_Return)
    inspection = cast(InspectionPage, win.pages["Inspection"])
    assert win.stack.currentWidget() is inspection and asked == [str(tmp_path / "boards")]
    assert inspection.view_combo.currentData() == "Top"
    qtbot.waitUntil(lambda: ctx.db.inspection_counts(ONE)[0] == 1, timeout=60000)
    win.navigate("Home")
    assert not guide.isVisible() and cast(HomePage, win.pages["Home"]).cards.isVisible()


def test_req_trn_021_train_says_why_it_is_off_and_what_stopped_it(
    qtbot: QtBot, ctx: AppContext, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, dialogs: list[Any]
) -> None:
    """Train is off, and a press or Enter says why, for a board revision it cannot take and while another training
    runs. A refusal, as the press is made or in the run, is said under Train with its code, with no dialog. Cancel
    stops Train and says the parts done are kept."""
    ready(ctx, tmp_path / "boards")
    win, guide, screen = home(qtbot, ctx)
    screen.revision.setText("R-1")
    assert screen.revision_line.isVisible() and not screen.btn_train.isEnabled()
    for press in (lambda: qtbot.mouseClick(screen.btn_train, Qt.MouseButton.LeftButton), screen.train):
        win.statusBar().clearMessage()
        press()
        assert win.statusBar().currentMessage() == "Type the board revision: 1 to 16 letters and digits, such as R1."
    screen.revision.setText("R1")
    other: Job[Any] = Job("training", lambda: None)
    ctx.training = other  # another training run, not yet ended
    screen.refresh()
    assert not screen.btn_train.isEnabled() and not screen.revision.isEnabled()
    win.statusBar().clearMessage()
    qtbot.mouseClick(screen.btn_train, Qt.MouseButton.LeftButton)
    assert win.statusBar().currentMessage() == "Wait for the training under way to end, then press Train again."
    ctx.training = None
    screen.refresh()

    def refused(*args: Any, **kw: Any) -> Any:
        raise AoiError("AOI-TRN-047")

    monkeypatch.setattr(ctx, "start_guide_train", refused)
    screen.btn_train.click()
    assert screen.said.isVisible() and screen.said.text().startswith("AOI-TRN-047 ")
    monkeypatch.undo()

    def not_trained(*args: Any, **kw: Any) -> Any:
        raise AoiError("AOI-TRN-045", name="v1.0", reason="too few OK images")

    monkeypatch.setattr(ctx, "guide_train", not_trained)
    trained(qtbot, screen)
    assert screen.said.text().startswith("AOI-TRN-045 ") and screen.before.isVisible() and dialogs == []
    monkeypatch.undo()
    screen.btn_train.click()
    screen.cancel()
    qtbot.waitUntil(lambda: screen.worker is None, timeout=180000)
    assert screen.said.text() == (
        "Train was cancelled. What it had done is kept, and the next Train goes on from there."
    )
    assert screen.before.isVisible() and screen.btn_train.isEnabled() and ctx.active_model(ONE) is None
