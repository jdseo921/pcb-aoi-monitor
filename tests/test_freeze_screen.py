"""REQ-TRN-005 on screen (Datasets stage 4 of 4): Training › Datasets' Working set panel. Results on synthetic boards
prove a code path; they are never quoted as accuracy."""

from __future__ import annotations

from pathlib import Path
from typing import cast

from PySide6.QtWidgets import QApplication
from pytestqt.qtbot import QtBot

from aoi.core.services import AppContext
from aoi.ui.main_window import MainWindow
from aoi.ui.pages.training import TrainingPage
from tests.test_datasets import ready
from tests.test_labeller_agreement import CAL


def _datasets(qtbot: QtBot, ctx: AppContext) -> TrainingPage:
    """Training › Datasets for CAL-1 as the engineer, at 1600 x 900."""
    win = MainWindow(ctx)
    qtbot.addWidget(win)
    win.resize(1600, 900)
    win.show()
    qtbot.waitExposed(win)
    win.activateWindow()
    win.set_user("engineer")
    win._on_board_model(CAL)
    win.navigate("Training")
    page = cast(TrainingPage, win.pages["Training"])
    page.tabs.setCurrentIndex(1)
    qtbot.waitUntil(lambda: QApplication.activeWindow() is win, timeout=5000)
    return page


def test_req_trn_005_working_set_panel(qtbot: QtBot, ctx: AppContext, tmp_path: Path) -> None:
    """The working set counts each view's labels and checks, with ✓ once the view is ready, names the customer whose
    dataset store holds the board model and ticks Their own AI models. A board model with no image labelled OK or NG
    says so, with no customer, and Open Samples › shows the Samples tab; with no board model the panel is blank."""
    ready(ctx, tmp_path / "boards")
    page = _datasets(qtbot, ctx)
    panel = page.working
    assert panel.counts.text() == "Top: 80 OK · 20 NG · 0 UNSURE · 20 of 20 NG checked · 8 of 8 OK checked (10 %) ✓"
    assert panel.customer.text() == "Acme" and [b.isChecked() for b in panel.uses.values()] == [True, False, False]
    assert [b.text() for b in panel.uses.values()] == ["Their own AI models", "Shared improvement", "Demos"]
    assert not panel.btn_samples.isVisibleTo(panel)
    ctx.ensure_board_model("NO-SAMPLES")
    page.shell._reload_board_models("NO-SAMPLES")
    assert panel.counts.text() == "No samples labelled OK or NG yet. Add OK boards on the Samples tab."
    assert panel.customer.text() == "in no customer's dataset store yet" and panel.btn_samples.isVisible()
    panel.btn_samples.click()
    assert page.tabs.currentIndex() == 0
    page.shell._on_board_model("")
    assert panel.counts.text() == "" and not panel.btn_samples.isVisibleTo(panel)
