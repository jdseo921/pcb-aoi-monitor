"""REQ-TRN-005 on screen (Datasets stage 4 of 4): Training › Datasets' Working set panel and its Freeze sheet, which
shows what a freeze of the working set needs, line by line. Results on synthetic boards prove a code path; they are
never quoted as accuracy."""

from __future__ import annotations

from pathlib import Path
from typing import cast

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication
from pytestqt.qtbot import QtBot

from aoi.core.services import AppContext
from aoi.ui.main_window import MainWindow
from aoi.ui.pages.training import TrainingPage
from tests.test_datasets import agree, ready
from tests.test_labeller_agreement import CAL, calibration_workspace
from tools.trainable import trainable


def _datasets(qtbot: QtBot, ctx: AppContext) -> TrainingPage:
    """Training › Datasets for CAL-1 as the engineer, at 1600 x 900, the window active so a sheet takes the focus."""
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


def _lines(page: TrainingPage) -> list[str]:
    return [line.text() for line in page.working.sheet.lines]


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


def test_req_trn_005_freeze_sheet(qtbot: QtBot, ctx: AppContext, tmp_path: Path) -> None:
    """Ctrl+F shows the Freeze sheet in place of the labeller agreement, the window kept at 1600 x 900, the focus on
    the board revision; the name follows the revision typed, and each line says ✓ or what to do. Esc closes it; once
    the agreement check reaches its targets, its line says ✓."""
    samples, cal = ready(ctx, tmp_path / "boards")
    page = _datasets(qtbot, ctx)
    panel = page.working
    qtbot.keyClick(page.datasets_tab, Qt.Key.Key_F, Qt.KeyboardModifier.ControlModifier)
    sheet = panel.sheet
    assert sheet.isVisible() and not page.agreement.isVisible() and not panel.btn_freeze.isEnabled()
    assert (page.shell.width(), page.shell.height()) == (1600, 900) and sheet.revision.hasFocus()
    assert sheet.name_line.text() == "Name: type the board revision, 1 to 16 letters and digits, such as R3"
    assert not sheet.refused.isVisible()  # the name line says it: no second line for the same refusal
    qtbot.keyClicks(sheet.revision, "R3")
    assert sheet.name_line.text() == "Name DS-CAL1-R3-TOP-v1"
    assert _lines(page) == [
        "✓ Every NG label checked by a second user",
        "✓ 8 of 8 OK labels checked (10 % of 80)",
        "✓ Customer Acme, whose dataset store holds it",
        "✗ No agreement check of this view reached its targets: run one under Labeller agreement",
    ]
    assert sheet.files_line.text() == "100 files · a SHA-256 manifest is written · the version never changes afterwards"
    qtbot.keyClick(sheet.revision, Qt.Key.Key_Escape)
    assert not sheet.isVisible() and page.agreement.isVisible() and panel.btn_freeze.isEnabled()
    agree(ctx, cal, samples)
    page.refresh()
    panel.btn_freeze.click()
    qtbot.keyClicks(sheet.revision, "R3")
    assert _lines(page)[3] == "✓ Agreement check reached its targets" and not sheet.refused.isVisible()


def test_req_trn_005_freeze_sheet_names_each_fix(qtbot: QtBot, ctx: AppContext, tmp_path: Path) -> None:
    """Each line of the Freeze sheet names its fix: NG labels not checked, OK labels to draw and check, no dataset
    store. With every line ✓, a refusal no line names, another board model's versions under the same name, shows as
    its coded line, and Freeze stays off. A sign-in or another board model closes the sheet."""
    calibration_workspace(ctx, tmp_path / "boards")
    ctx.set_user("engineer")
    page = _datasets(qtbot, ctx)
    panel = page.working
    assert panel.counts.text() == "Top: 80 OK · 20 NG · 0 UNSURE · 0 of 20 NG checked · 0 of 8 OK checked (10 %)"
    panel.btn_freeze.click()
    qtbot.keyClicks(panel.sheet.revision, "R3")
    assert _lines(page)[:3] == [
        "✗ 20 of 20 NG labels not checked: check them on the Samples tab",
        "✗ 0 of 8 OK labels checked (10 % of 80): draw and check them on the Samples tab",
        "✗ In no customer's dataset store: an Admin moves it in on Settings",
    ]
    page.shell.set_user("admin")
    assert not panel.sheet.isVisible() and page.agreement.isVisible()
    page.shell.set_user("engineer")
    panel.btn_freeze.click()
    page.shell._on_board_model("")
    assert not panel.sheet.isVisible() and panel.counts.text() == "" and not panel.btn_freeze.isEnabled()


def test_req_trn_005_freeze_sheet_shows_a_refusal_no_line_names(qtbot: QtBot, ctx: AppContext, tmp_path: Path) -> None:
    """Every line ✓, but another board model, CAL1, has frozen versions under the name CAL-1's would take: the sheet
    shows AOI-TRN-040 as its coded line and Freeze stays off."""
    samples, cal = ready(ctx, tmp_path / "boards")
    agree(ctx, cal, samples)
    trainable(ctx, "CAL1", stored=False)
    page = _datasets(qtbot, ctx)
    page.working.btn_freeze.click()
    qtbot.keyClicks(page.working.sheet.revision, "R3")
    assert all(line.startswith("✓") for line in _lines(page))
    sheet = page.working.sheet
    assert sheet.refused.isVisible() and sheet.refused.text().startswith("AOI-TRN-040 ")
