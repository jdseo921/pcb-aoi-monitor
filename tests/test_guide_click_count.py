"""REQ-TRN-021 for B5 of the 2026-10 business-readiness brief (docs/sketches/first-run-guide.md, "Click count"): one
person goes from an empty workspace to the first verdict in at most 25 actions on at most 4 screens. An action is a
click or tap, a drag, a key press that is not typing, or one field typed; a screen is a page or a guide screen that
replaces the one before, and a system dialog is not one (Q64). As the sketch assumes: the key's USB drive is plugged in
for screen 1 and the images' for screen 2, holding TBOX-A1/ok, TBOX-A1/ng/<defect type> and, beside that folder, the
image of the board to inspect; each NG image shows one defect, and no image is refused. A dialog that does not open on
the right USB drive costs one action more (Q68). The boards are synthetic: the test counts actions, never accuracy."""

from __future__ import annotations

import random
from pathlib import Path
from typing import Any, cast

import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QFileDialog
from pytestqt.qtbot import QtBot

from aoi.core.imaging import save_image
from aoi.core.services import AppContext
from aoi.ui import theme
from aoi.ui.main_window import HomePage, MainWindow
from aoi.ui.pages.base import Page
from aoi.ui.pages.inspection import InspectionPage
from tests.test_guide_images import BM, drawn
from tests.test_usb_drives import plugged
from tools.make_synthetic_dataset import capture, draw_board

DEFECT = "Missing Component"
SKETCH = [  # the sketch's table, in its words
    "Type the board model name",
    "Tab to Customer",
    "Type the customer",
    "Create (Enter)",
    "Save to File…",
    "Save",
    "I Have Saved the Key",
    "Pick Folder…",
    "Click TBOX-A1 in the folder dialog",
    "Select Folder",
    *["One drag on an NG image"] * 10,
    "Train",
    "Inspect a Board…",
    "Click the board's image in the file dialog",
    "Open",
]
FIND_THE_DRIVE = "Find the USB drive in the dialog"  # Q68 not taken: one action more for each dialog


def on_a_drive(drive: Path, ok: int, ng: int) -> tuple[Path, Path]:
    """On `drive`, TBOX-A1/ok with `ok` synthetic boards as a fixture takes them (tools/make_synthetic_dataset.py),
    TBOX-A1/ng/<DEFECT> with `ng` boards each missing a part, and beside TBOX-A1 one more good board, to inspect: the
    folder and that board."""
    rng = random.Random(7)
    folder = drive / BM
    for place, n, defect in ((folder / "ok", ok, None), (folder / "ng" / DEFECT, ng, DEFECT)):
        place.mkdir(parents=True)
        for i in range(n):
            save_image(place / f"{i:03d}.png", capture(draw_board(rng, defect), rng))
    save_image(drive / "board.png", capture(draw_board(rng), rng))
    return folder, drive / "board.png"


class Count:
    """Each action, named as the sketch's table names it, and each screen an action was taken on, in order."""

    def __init__(self, win: MainWindow) -> None:
        self.win = win
        self.actions: list[str] = []
        self.screens: list[str] = []

    def __call__(self, action: str) -> None:
        self.actions.append(action)
        self.look()

    def look(self) -> None:
        """The screen shown now noted, unless it is the one before: a guide screen by its number, else the page."""
        page = cast(Page, self.win.stack.currentWidget())
        guide = cast(HomePage, self.win.pages["Home"]).guide
        here = f"Guide screen {guide.shown}" if page is self.win.pages["Home"] and guide.isVisible() else page.title
        if not self.screens or self.screens[-1] != here:
            self.screens.append(here)


@pytest.mark.parametrize("ok", [90, 70], ids=["90 OK", "70 OK"])
def test_req_trn_021_from_an_empty_workspace_to_the_first_verdict_in_24_actions_on_4_screens(
    qtbot: QtBot, ctx: AppContext, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, dialogs: list[Any], ok: int
) -> None:
    """The sketch's 24 actions on 4 screens, with 90 or 70 OK and 10 NG images: the board model named and made, the key
    saved on the key's USB drive, the images' folder picked on theirs, a box dragged on each NG image, Train, and the
    board inspected from beside the folder, with the shift check on, as a station has it (Q72). Each dialog opens on
    the USB drive plugged in last, or the action it costs is counted."""
    key_drive, image_drive = tmp_path / "KEY", tmp_path / "IMAGES"
    key_drive.mkdir()
    folder, board = on_a_drive(image_drive, ok, 10)
    ctx.settings.default_epochs, ctx.settings.image_size, ctx.settings.shift_check_hours = 1, 32, 12  # a short run
    usb = plugged(monkeypatch, key_drive)
    win = MainWindow(ctx)  # a first start: the first Admin, at Home
    qtbot.addWidget(win)
    win.resize(1600, 900)
    win.show()
    qtbot.waitExposed(win)
    win.activateWindow()
    qtbot.waitUntil(lambda: QApplication.activeWindow() is win)
    home = cast(HomePage, win.pages["Home"])
    guide, inspection = home.guide, cast(InspectionPage, win.pages["Inspection"])
    count = Count(win)

    def saved(parent: object, title: str, path: str, kinds: str) -> tuple[str, str]:
        if Path(path).parent != key_drive:
            count(FIND_THE_DRIVE)
        count("Save")  # the file named already
        return str(key_drive / Path(path).name), kinds

    def picked(parent: object, title: str, start: str = "") -> str:
        if start != str(image_drive):
            count(FIND_THE_DRIVE)
        count("Click TBOX-A1 in the folder dialog")
        count("Select Folder")
        return str(folder)

    def opened(parent: object, title: str, start: str, kinds: str) -> tuple[list[str], str]:
        if start != str(image_drive):
            count(FIND_THE_DRIVE)
        count("Click the board's image in the file dialog")
        count("Open")
        return [str(board)], kinds

    monkeypatch.setattr(QFileDialog, "getSaveFileName", staticmethod(saved))
    monkeypatch.setattr(QFileDialog, "getExistingDirectory", staticmethod(picked))
    monkeypatch.setattr(QFileDialog, "getOpenFileNames", staticmethod(opened))

    assert win.focusWidget() is guide.name  # screen 1 opens on the name
    count("Type the board model name")
    qtbot.keyClicks(guide.name, BM)
    count("Tab to Customer")
    qtbot.keyClick(guide.name, Qt.Key.Key_Tab)
    assert win.focusWidget() is guide.customer
    count("Type the customer")
    qtbot.keyClicks(guide.customer, "Acme")
    count("Create (Enter)")
    qtbot.keyClick(guide.customer, Qt.Key.Key_Return)
    count("Save to File…")
    qtbot.mouseClick(guide.recovery.btn_save, Qt.MouseButton.LeftButton)
    count("I Have Saved the Key")
    qtbot.mouseClick(guide.btn_kept, Qt.MouseButton.LeftButton)

    usb.append(image_drive)  # the images' USB drive plugged in, which is no action
    images = guide.images
    count("Pick Folder…")
    qtbot.mouseClick(images.btn_pick, Qt.MouseButton.LeftButton)
    qtbot.waitUntil(lambda: images.copying is None, timeout=60000)
    for _ in range(10):
        count("One drag on an NG image")
        drawn(qtbot, images)

    screen = guide.train_step
    qtbot.waitUntil(lambda: guide.shown == 3 and screen.btn_train.isEnabled())  # screen 3 shows itself (Q69)
    count("Train")
    qtbot.mouseClick(screen.btn_train, Qt.MouseButton.LeftButton)
    qtbot.waitUntil(lambda: screen.worker is None and not ctx.guide_running(BM), timeout=300000)
    count("Inspect a Board…")
    qtbot.mouseClick(screen.btn_inspect, Qt.MouseButton.LeftButton)
    qtbot.waitUntil(lambda: ctx.db.inspection_counts(BM)[0] == 1 and inspection.last is not None, timeout=60000)
    count.look()

    assert count.actions == SKETCH and len(count.actions) == 24  # against 25
    assert count.screens == ["Guide screen 1", "Guide screen 2", "Guide screen 3", "Inspection"]  # against 4
    assert inspection.verdict.text() == theme.verdict_label(inspection.last.verdict) and dialogs == []
