"""REQ-TRN-021 for B5 of the 2026-10 business-readiness brief (D4; docs/sketches/first-run-guide.md, Q69 to Q71): the
first-run guide's screen 2 on Home, for a board model in a customer's store until its images are in and boxed. Pick
Folder… copies the folder's ok/ and ng/<defect type>/ images in the view picked as soon as the folder is picked,
counts them against What is missing's first three lines and names the images not taken; images straight in ng/ wait
for their type. The box area is always drawing: each box is stored with its folder's type and the next NG image with
no box opens; Undo takes the last box away again. A refusal is said under the control that raised it, with no
dialog."""

from __future__ import annotations

from pathlib import Path
from typing import Any, cast

import numpy as np
import pytest
from PySide6.QtCore import QRectF, Qt
from PySide6.QtWidgets import QApplication, QFileDialog
from pytestqt.qtbot import QtBot

from aoi.core.imaging import save_image
from aoi.core.services import AppContext
from aoi.ui.main_window import HomePage, MainWindow
from aoi.ui.pages.guide import FirstRunGuide
from aoi.ui.pages.guide_images import GuideImages
from tests.test_dataset_stores import as_admin
from tests.test_first_board_model_store import shell

BM = "TBOX-A1"


def boards(folder: Path, ok: int, ng: dict[str, int], seed: int = 3) -> Path:
    """`folder` holding `ok` OK images in ok/ and, for each name in `ng`, that many NG images in ng/<name>/ (ng/ itself
    for ""), each 32 x 32 px and different."""
    rng = np.random.default_rng(seed)
    places = [(folder / "ok", ok)] + [(folder / "ng" / name if name else folder / "ng", n) for name, n in ng.items()]
    for place, n in places:
        place.mkdir(parents=True, exist_ok=True)
        for i in range(n):
            save_image(
                place / f"{place.name.replace(' ', '_')}_{i:02d}.png", rng.integers(0, 256, (32, 32, 3), np.uint8)
            )
    return folder


def home(qtbot: QtBot, ctx: AppContext, role: str = "admin") -> tuple[MainWindow, FirstRunGuide, GuideImages]:
    """TBOX-A1 made in Acme's store, Home shown for `role`."""
    as_admin(ctx, ctx.create_customer_board_model, BM, "Acme")
    win = shell(qtbot, ctx, role)
    win.select_board_model(BM)
    win.navigate("Home")
    guide = cast(HomePage, win.pages["Home"]).guide
    return win, guide, guide.images


def picked(qtbot: QtBot, monkeypatch: pytest.MonkeyPatch, images: GuideImages, folder: Path) -> None:
    """Pick Folder… with `folder` picked, and the copy waited for."""
    monkeypatch.setattr(QFileDialog, "getExistingDirectory", staticmethod(lambda *a: str(folder)))
    images.btn_pick.click()
    qtbot.waitUntil(lambda: images.copying is None, timeout=20000)


def lines(images: GuideImages) -> list[str]:
    return [line.text() for line in images.need_lines.values()]


def drawn(qtbot: QtBot, images: GuideImages) -> None:
    """A box dragged across the NG image shown, once it is read: the view's own signal for a drag in Draw mode."""
    qtbot.waitUntil(lambda: images.reading is None and images.editor._pix is not None)
    images.editor.roiDrawn.emit(QRectF(4, 4, 12, 10))


def test_req_trn_021_a_board_model_in_a_store_opens_on_screen_2(
    qtbot: QtBot, ctx: AppContext, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, dialogs: list[Any]
) -> None:
    """Screen 2 before any image says what a board model needs and how the folder is laid out. Pick Folder… copies
    75 OK and 3 NG images in the view picked, as soon as the folder is picked; a file in neither ok nor ng is not
    taken, and Show Why says why with its code. Then the box area opens on the first NG image."""
    win, guide, images = home(qtbot, ctx)
    assert guide.isVisible() and images.isVisible() and not guide.form.isVisible()
    assert guide.heading.text() == "Set up TBOX-A1"
    assert guide.steps.text() == "✓ 1 Board model  ───  ● 2 Images  ───  ○ 3 Train"
    assert images.first.isVisible() and images.none.text() == "No images of TBOX-A1 yet"
    assert lines(images) == [
        "○ OK images: 0 of 70",
        "○ NG images: 0 of 1",
        "○ NG images with every defect boxed: 0 of 1",
    ]
    folder = boards(tmp_path / "TBOX-A1", 75, {"Missing Component": 3})
    save_image(folder / "stray.png", np.zeros((32, 32, 3), np.uint8))
    images.view_buttons["Side"].click()
    picked(qtbot, monkeypatch, images, folder)
    assert lines(images) == [
        "✓ OK images: 75 of 70",
        "✓ NG images: 3 of 1",
        "○ NG images with every defect boxed: 0 of 3",
    ]
    assert {s["side"] for s in ctx.samples(BM)} == {"Side"} and images.view_buttons["Side"].isChecked()
    assert {s["defect_type"] for s in ctx.samples(BM, "NG")} == {"Missing Component"}
    assert images.from_line.text() == f"From {folder}, Side view. Not taken: 1."
    images.btn_why.click()
    assert images.why.isVisible() and images.why.text().startswith("stray.png: AOI-TRN-016 ")
    assert not images.first.isVisible() and images.boxes.isVisible() and dialogs == []
    qtbot.waitUntil(lambda: images.editor._pix is not None)
    assert images.where.text().startswith("Image 1 of 3 · Missing_Component_00")  # the copy's name, as Training's
    assert images.kind.text() == "Missing Component (its folder)"


def test_req_trn_021_one_box_on_each_ng_image_ends_screen_2(
    qtbot: QtBot, ctx: AppContext, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Each box is stored as drawn, with its folder's type, and the next NG image with no box opens; Undo takes the
    last box away again and shows its image; ← Back opens the one before. With a box on every NG image, screen 2 is
    done and Home goes on."""
    win, guide, images = home(qtbot, ctx)
    picked(qtbot, monkeypatch, images, boards(tmp_path / "TBOX-A1", 70, {"Solder Bridge": 2, "Missing Component": 1}))
    ng = images.ng
    drawn(qtbot, images)
    assert [(b["dct_type"], b["w"], b["h"]) for b in ctx.boxes(ng[0]["uuid"])] == [("Missing Component", 12, 10)]
    assert images.at == 1 and lines(images)[2] == "○ NG images with every defect boxed: 1 of 3"
    images.btn_undo.click()
    assert ctx.boxes(ng[0]["uuid"]) == [] and images.at == 0
    drawn(qtbot, images)
    drawn(qtbot, images)
    assert images.at == 2
    images.btn_back.click()
    assert images.at == 1
    images.open_image(2)
    drawn(qtbot, images)
    assert all(ctx.boxes(s["uuid"]) for s in ng) and ctx.guide_step(BM) == 3
    assert not guide.isVisible() and cast(HomePage, win.pages["Home"]).cards.isVisible()


def test_req_trn_021_images_straight_in_ng_wait_for_their_type(
    qtbot: QtBot, ctx: AppContext, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Images straight in ng/ show the type list, and nothing is copied until a type is picked; then the copy starts
    and they take it (Q71)."""
    win, guide, images = home(qtbot, ctx)
    monkeypatch.setattr(QFileDialog, "getExistingDirectory", staticmethod(lambda *a: str(tmp_path / "TBOX-A1")))
    boards(tmp_path / "TBOX-A1", 70, {"": 2})
    images.btn_pick.click()
    assert images.typing.isVisible() and images.copying is None and ctx.samples(BM) == []
    images.ng_type.activated.emit(images.ng_type.findText("Tombstone"))
    qtbot.waitUntil(lambda: images.copying is None and bool(ctx.samples(BM)), timeout=20000)
    assert not images.typing.isVisible()
    assert [s["defect_type"] for s in ctx.samples(BM, "NG")] == ["Tombstone", "Tombstone"]


def test_req_trn_021_a_folder_with_no_ok_or_ng_and_a_copy_stopped(
    qtbot: QtBot, ctx: AppContext, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, dialogs: list[Any]
) -> None:
    """A folder with no image in ok or ng copies nothing and says how to lay it out; a copy stopped part way, as
    Cancel stops it, keeps the images before and says where it stopped. No dialog."""
    win, guide, images = home(qtbot, ctx)
    loose = tmp_path / "loose"
    loose.mkdir()
    save_image(loose / "a.png", np.zeros((32, 32, 3), np.uint8))
    picked(qtbot, monkeypatch, images, loose)
    assert images.picked.isVisible() and images.picked.text().startswith(f"No images in ok or ng folders in {loose}.")
    assert ctx.samples(BM) == []
    real = ctx.import_files

    def stops_after_two(board_model: str, files: list[Any], progress: Any = None, should_stop: Any = None) -> Any:
        done: list[int] = []
        return real(board_model, files, lambda n, total: done.append(n), lambda: len(done) >= 2)

    monkeypatch.setattr(ctx, "import_files", stops_after_two)
    picked(qtbot, monkeypatch, images, boards(tmp_path / "TBOX-A1", 4, {}))
    assert len(ctx.samples(BM)) == 2
    assert images.picked.text() == "Copying stopped at image 3 of 4; the ones before it are kept." and dialogs == []


def test_req_trn_021_screen_2_for_each_role(qtbot: QtBot, ctx: AppContext, tmp_path: Path) -> None:
    """An Engineer gets screen 2 as the Admin does; an Operator, who sets nothing up, gets Home's empty state saying
    the board model is still being set up. A board model in no customer's store gets Home's cards."""
    win, guide, images = home(qtbot, ctx, "engineer")
    assert images.isVisible() and images.btn_pick.isEnabled()
    win.set_user("operator")
    home_page = cast(HomePage, win.pages["Home"])
    assert not guide.isVisible() and home_page.empty.heading.text() == "TBOX-A1 is still being set up"
    assert not home_page.cards.isVisible()
    win.set_user("engineer")
    ctx.ensure_board_model("PLAIN-1")
    win.select_board_model("PLAIN-1")
    assert ctx.guide_step("PLAIN-1") is None and not guide.isVisible() and home_page.cards.isVisible()


def test_req_trn_021_screen_2_says_why_and_takes_its_keys(
    qtbot: QtBot, ctx: AppContext, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A press on an off control of screen 2 says why on the status bar: ← Back on the first NG image, Undo with no box
    drawn, Pick Folder… while a copy runs. F1 lists screen 2's keys, and PgUp and Ctrl+Z do what their buttons do."""
    win, guide, images = home(qtbot, ctx)
    picked(qtbot, monkeypatch, images, boards(tmp_path / "TBOX-A1", 70, {"Solder Bridge": 2}))
    qtbot.waitUntil(lambda: images.reading is None)
    for control, said in (
        (images.btn_back, "This is the first NG image."),
        (images.btn_undo, "No box drawn on this screen to undo."),
    ):
        win.statusBar().clearMessage()
        qtbot.mouseClick(control, Qt.MouseButton.LeftButton)
        assert not control.isEnabled() and win.statusBar().currentMessage() == said
    keys = win.keys_text()
    for line in ("Ctrl+O   Pick Folder…", "PgUp   ← Back", "Ctrl+Z   Undo", "+   Zoom In", "-   Zoom Out", "0   Fit"):
        assert line in keys, line
    win.activateWindow()
    qtbot.waitUntil(lambda: QApplication.activeWindow() is win)
    drawn(qtbot, images)
    assert images.at == 1 and images.btn_back.isEnabled() and images.btn_undo.isEnabled()
    qtbot.keyClick(images.boxes, Qt.Key.Key_PageUp)
    assert images.at == 0
    qtbot.keyClick(images.boxes, Qt.Key.Key_Z, Qt.KeyboardModifier.ControlModifier)
    assert ctx.boxes(images.ng[0]["uuid"]) == [] and not images.btn_undo.isEnabled()
    images.copying = cast(Any, object())  # a copy running, as far as the screen goes: its Worker is not needed here
    images._gate()
    win.statusBar().clearMessage()
    qtbot.mouseClick(images.btn_pick, Qt.MouseButton.LeftButton)
    assert win.statusBar().currentMessage() == "A copy is running: Cancel (Esc) stops it."
    images.copying = None
