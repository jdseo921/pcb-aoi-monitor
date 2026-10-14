"""REQ-TRN-021 for B5 of the 2026-10 business-readiness brief (D4; docs/sketches/first-run-guide.md, Q69 to Q71): the
first-run guide's screen 2 on Home, for a board model in a customer's store until its images are in and boxed. Pick
Folder… copies the folder's ok/ and ng/<defect type>/ images in the view picked as soon as the folder is picked,
counts them against What is missing's first three lines and names the images not taken; images straight in ng/ wait
for their type. The box area is always drawing: each box is stored with its folder's type and the next NG image with
no box opens; Undo takes the last box away again. A refusal is said under the control that raised it, with no
dialog."""

from __future__ import annotations

import dataclasses
import threading
from pathlib import Path
from typing import Any, cast

import numpy as np
import pytest
from PySide6.QtCore import QPoint, QPointF, QRectF, Qt
from PySide6.QtWidgets import QApplication, QFileDialog
from pytestqt.qtbot import QtBot

from aoi.core.imaging import save_image
from aoi.core.labels import DefectBox
from aoi.core.services import AppContext
from aoi.errors import AoiError
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
    done and screen 3 shows, with Train focused."""
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
    assert guide.isVisible() and not images.isVisible() and guide.train_step.isVisible()
    assert guide.steps.text() == "✓ 1 Board model  ───  ✓ 2 Images  ───  ● 3 Train"
    assert win.focusWidget() is guide.train_step.btn_train


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


def held_copy(ctx: AppContext, monkeypatch: pytest.MonkeyPatch, at: int) -> threading.Event:
    """A copy that waits in its image `at` (from 1) until the event returned is set, as a slow USB drive would."""
    real, go, seen = ctx.import_samples, threading.Event(), []

    def slow(*args: Any, **kw: Any) -> Any:
        seen.append(1)
        if len(seen) == at:
            go.wait(20)
        return real(*args, **kw)

    monkeypatch.setattr(ctx, "import_samples", slow)
    return go


def test_req_trn_021_screen_2_starts_afresh_for_another_board_model_or_user(
    qtbot: QtBot, ctx: AppContext, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A type still asked for goes with another board model, another folder picked and a sign-in, so no image is copied
    into a board model or as a folder not shown; the view pressed stays through the copy and a box; a sign-in leaves
    nothing of the user before: the line of their copy, or a box Undo would take away."""
    win, guide, images = home(qtbot, ctx)
    as_admin(ctx, ctx.create_customer_board_model, "TBOX-B1", "Acme")
    plain = boards(tmp_path / "plain", 70, {"": 2})
    monkeypatch.setattr(QFileDialog, "getExistingDirectory", staticmethod(lambda *a: str(plain)))
    images.btn_pick.click()
    assert images.typing.isVisible() and images.waiting
    win.select_board_model("TBOX-B1")
    assert images.board_model == "TBOX-B1" and not images.typing.isVisible() and images.waiting == []
    images.ng_type.activated.emit(images.ng_type.findText("Tombstone"))
    win.select_board_model(BM)
    assert images.copying is None and ctx.samples(BM) == [] and ctx.samples("TBOX-B1") == []
    images.btn_pick.click()  # the type asked again, then another folder picked
    assert images.typing.isVisible()
    images.view_buttons["Side"].click()
    picked(qtbot, monkeypatch, images, boards(tmp_path / "TBOX-A1", 70, {"Solder Bridge": 2}))
    assert not images.typing.isVisible() and images.waiting == []
    images.ng_type.activated.emit(images.ng_type.findText("Tombstone"))
    assert images.copying is None and len(ctx.samples(BM)) == 72
    assert {s["side"] for s in ctx.samples(BM)} == {"Side"}
    drawn(qtbot, images)
    assert images.view_buttons["Side"].isChecked() and images.undo and images.from_line.isVisible()
    win.set_user("engineer")
    win.navigate("Home")
    assert not images.from_line.isVisible() and images.undo == [] and not images.btn_undo.isEnabled()
    assert images.boxes.isVisible() and images.at == 1  # the first NG image with no box


def test_req_trn_021_a_copy_keeps_its_board_model_and_cancel_keeps_what_went_in(
    qtbot: QtBot, ctx: AppContext, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The copy's line says the image it is at, the percent and the time left, and names its board model while another
    is shown, where Pick Folder… says why it is off; what it did is said on its own board model's screen only, and the
    status bar says it ended. Cancel, pressed, stops it after the image in hand and keeps the images before."""
    win, guide, images = home(qtbot, ctx)
    as_admin(ctx, ctx.create_customer_board_model, "TBOX-B1", "Acme")
    go = held_copy(ctx, monkeypatch, 2)
    monkeypatch.setattr(QFileDialog, "getExistingDirectory", staticmethod(lambda *a: str(tmp_path / "TBOX-A1")))
    boards(tmp_path / "TBOX-A1", 4, {})
    images.btn_pick.click()
    qtbot.waitUntil(lambda: images.copy_line.text().startswith("Copying image 1 of 4 · 25 % · "))
    win.select_board_model("TBOX-B1")
    assert images.copy_row.isVisible() and images.copy_for == BM
    win.statusBar().clearMessage()
    qtbot.mouseClick(images.btn_pick, Qt.MouseButton.LeftButton)
    assert win.statusBar().currentMessage() == "A copy into TBOX-A1 is running: Cancel (Esc) stops it."
    go.set()
    qtbot.waitUntil(lambda: images.copying is None, timeout=20000)
    assert win.statusBar().currentMessage() == "The copy into TBOX-A1 ended: 4 copied, 0 not taken."
    assert not images.from_line.isVisible() and not images.picked.isVisible() and len(ctx.samples(BM)) == 4
    go = held_copy(ctx, monkeypatch, 2)
    boards(tmp_path / "TBOX-B1", 4, {}, seed=5)
    picked_now = str(tmp_path / "TBOX-B1")
    monkeypatch.setattr(QFileDialog, "getExistingDirectory", staticmethod(lambda *a: picked_now))
    images.btn_pick.click()
    qtbot.waitUntil(lambda: images.copy_line.text().startswith("Copying image 1 of 4"))
    qtbot.mouseClick(images.btn_cancel, Qt.MouseButton.LeftButton)
    go.set()
    qtbot.waitUntil(lambda: images.copying is None, timeout=20000)
    assert len(ctx.samples("TBOX-B1")) == 2
    assert images.picked.text() == "Copying stopped at image 3 of 4; the ones before it are kept."
    assert images.from_line.text() == f"From {picked_now}, Top view. Not taken: 0."


def test_req_trn_021_a_copy_stopped_by_an_error_and_images_already_in(
    qtbot: QtBot, ctx: AppContext, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, dialogs: list[Any]
) -> None:
    """An error the copy cannot pass stops it at that image: the line says where, names the image and gives the code,
    with no dialog. The folder picked again counts the images already in apart from those not taken."""
    win, guide, images = home(qtbot, ctx)
    real, seen = ctx.import_samples, []

    def third_fails(*args: Any, **kw: Any) -> Any:
        seen.append(1)
        if len(seen) == 3:
            raise OSError("the drive went away")
        return real(*args, **kw)

    monkeypatch.setattr(ctx, "import_samples", third_fails)
    folder = boards(tmp_path / "TBOX-A1", 4, {})
    picked(qtbot, monkeypatch, images, folder)
    assert len(ctx.samples(BM)) == 2 and dialogs == []
    said = images.picked.text()
    assert said.startswith("Copying stopped at image 3 of 4; the ones before it are kept. ok_02.png: AOI-"), said
    monkeypatch.setattr(ctx, "import_samples", real)
    picked(qtbot, monkeypatch, images, folder)
    assert images.from_line.text() == f"From {folder}, Top view. Not taken: 0. Already in: 2."
    images.btn_why.click()
    assert images.why.text().count("AOI-TRN-015") == 2


def test_req_trn_021_the_type_list_copies_only_on_a_pick(
    qtbot: QtBot, ctx: AppContext, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """On the closed type list, the arrows, a letter and the wheel pick nothing and copy nothing; Enter opens the list,
    and Enter there picks the type and starts the copy (Q71)."""
    win, guide, images = home(qtbot, ctx)
    monkeypatch.setattr(QFileDialog, "getExistingDirectory", staticmethod(lambda *a: str(tmp_path / "TBOX-A1")))
    boards(tmp_path / "TBOX-A1", 70, {"": 2})
    images.btn_pick.click()
    box = images.ng_type
    for key in (Qt.Key.Key_Down, Qt.Key.Key_Up, Qt.Key.Key_End, Qt.Key.Key_S):
        qtbot.keyClick(box, key)
    qtbot.wait(50)
    assert box.currentIndex() == -1 and images.copying is None and ctx.samples(BM) == []
    qtbot.keyClick(box, Qt.Key.Key_Return)
    popup = box.view()
    qtbot.waitUntil(popup.isVisible)
    popup.setCurrentIndex(box.model().index(box.findText("Tombstone"), 0))
    qtbot.keyClick(popup, Qt.Key.Key_Return)
    qtbot.waitUntil(lambda: images.copying is None and bool(ctx.samples(BM)), timeout=20000)
    assert [s["defect_type"] for s in ctx.samples(BM, "NG")] == ["Tombstone", "Tombstone"]


def test_req_trn_021_a_box_goes_on_the_image_shown(
    qtbot: QtBot, ctx: AppContext, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The box area always draws, and a drag on a box moves it, with no next image. When the NG images change under the
    screen, as when one is labelled OK on Training, the image shown keeps its boxes' sample, or the first NG image with
    no box opens; a box drawn goes on the image shown, never on the one now at its place in the list."""
    win, guide, images = home(qtbot, ctx)
    picked(qtbot, monkeypatch, images, boards(tmp_path / "TBOX-A1", 70, {"Solder Bridge": 3}))
    ng = [s["uuid"] for s in images.ng]
    qtbot.waitUntil(lambda: images.loaded is not None)
    assert images.editor._draw_mode and images.editor.moves_while_drawing
    drawn(qtbot, images)
    images.back()
    qtbot.waitUntil(lambda: images.loaded is not None and images.at == 0)
    view = images.editor
    inside = view.mapFromScene(QPointF(10, 9))
    qtbot.mousePress(view.viewport(), Qt.MouseButton.LeftButton, pos=inside)
    qtbot.mouseMove(view.viewport(), inside + QPoint(65, 65))  # 5 px of the image, at 13 times
    qtbot.mouseRelease(view.viewport(), Qt.MouseButton.LeftButton, pos=inside + QPoint(65, 65))
    moved = ctx.boxes(ng[0])
    assert len(moved) == 1 and (moved[0]["x"], moved[0]["y"]) != (4, 4) and images.at == 0
    images.open_image(1)
    qtbot.waitUntil(lambda: images.loaded is not None and images.at == 1)
    as_admin(ctx, ctx.set_label, ng[0], "OK")  # one before the image shown leaves the list: it is first now
    cast(HomePage, win.pages["Home"]).on_show()
    assert images.at == 0 and images.open_uuid == ng[1] and images.where.text().startswith("Image 1 of 2 · ")
    drawn(qtbot, images)
    assert len(ctx.boxes(ng[1])) == 1 and ctx.boxes(ng[2]) == []


def test_req_trn_021_an_image_that_cannot_be_read_and_a_box_refused(
    qtbot: QtBot, ctx: AppContext, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, dialogs: list[Any]
) -> None:
    """An NG image that cannot be read is skipped and named under the box area with its code, and the next NG image
    with no box opens; ← Back skips it too. A box the workspace refuses is said under the box area with its code,
    and the image keeps the boxes it had. No dialog."""
    win, guide, images = home(qtbot, ctx)
    picked(qtbot, monkeypatch, images, boards(tmp_path / "TBOX-A1", 70, {"Solder Bridge": 3}))
    ng = list(images.ng)
    Path(ng[1]["path"]).unlink()
    drawn(qtbot, images)
    qtbot.waitUntil(lambda: images.at == 2 and images.reading is None)
    assert images.skipped.isVisible() and images.skipped.text().startswith("Skipped, as they cannot be read:\n")
    assert f"{Path(ng[1]['path']).name}: AOI-" in images.skipped.text()
    images.back()
    qtbot.waitUntil(lambda: images.at == 0 and images.reading is None)

    def refused(sample: str, boxes: list[DefectBox]) -> None:
        raise AoiError("AOI-TRN-032", sample=sample)

    images.open_image(2)
    qtbot.waitUntil(lambda: images.loaded is not None and images.at == 2)
    monkeypatch.setattr(ctx, "set_boxes", refused)
    drawn(qtbot, images)
    assert images.box_refused.isVisible() and images.box_refused.text().startswith("AOI-TRN-032 ")
    assert images.editor.boxes == [] and images.at == 2 and dialogs == []


def test_req_trn_021_screen_2_keys_say_why_they_do_nothing(
    qtbot: QtBot, ctx: AppContext, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """PgUp on the first NG image, Ctrl+Z with no box drawn, and Ctrl+O or a view pressed while a copy runs say why
    on the status bar, as their buttons do."""
    win, guide, images = home(qtbot, ctx)
    picked(qtbot, monkeypatch, images, boards(tmp_path / "TBOX-A1", 70, {"Solder Bridge": 2}))
    qtbot.waitUntil(lambda: images.loaded is not None)
    win.activateWindow()
    qtbot.waitUntil(lambda: QApplication.activeWindow() is win)
    for key, mods, said in (
        (Qt.Key.Key_PageUp, Qt.KeyboardModifier.NoModifier, "This is the first NG image."),
        (Qt.Key.Key_Z, Qt.KeyboardModifier.ControlModifier, "No box drawn on this screen to undo."),
    ):
        win.statusBar().clearMessage()
        qtbot.keyClick(images.boxes, key, mods)
        assert win.statusBar().currentMessage() == said
    go = held_copy(ctx, monkeypatch, 1)
    more = boards(tmp_path / "more", 2, {}, seed=9)
    monkeypatch.setattr(QFileDialog, "getExistingDirectory", staticmethod(lambda *a: str(more)))
    images.btn_pick.click()
    qtbot.waitUntil(images.copy_row.isVisible)
    for press in (
        lambda: qtbot.keyClick(images, Qt.Key.Key_O, Qt.KeyboardModifier.ControlModifier),
        lambda: qtbot.mouseClick(images.view_buttons["Side"], Qt.MouseButton.LeftButton),
    ):
        win.statusBar().clearMessage()
        press()
        assert win.statusBar().currentMessage() == "A copy is running: Cancel (Esc) stops it."
    assert images.view_buttons["Top"].isChecked()
    go.set()
    qtbot.waitUntil(lambda: images.copying is None, timeout=20000)


def test_req_trn_021_the_screen_for_each_board_model(ctx: AppContext, monkeypatch: pytest.MonkeyPatch) -> None:
    """`guide_step`: 1 with no board model; None for one in no store, a shredded store's, one with a board inspected
    and one a Validated AI model judges; 2 until one view holds what a Trial AI model needs, every NG image boxed."""
    assert ctx.guide_step(None) == 1
    ctx.ensure_board_model("PLAIN-1")
    assert ctx.guide_step("PLAIN-1") is None
    as_admin(ctx, ctx.create_customer_board_model, BM, "Acme")
    assert ctx.guide_step(BM) == 2
    real_counts = ctx.db.inspection_counts
    monkeypatch.setattr(ctx.db, "inspection_counts", lambda bm: (1, 0) if bm == BM else real_counts(bm))
    assert ctx.guide_step(BM) is None
    monkeypatch.setattr(ctx.db, "inspection_counts", real_counts)
    monkeypatch.setattr(ctx, "validated_live", lambda bm: {"version": "v1.0"})
    assert ctx.guide_step(BM) is None
    monkeypatch.undo()
    made = as_admin(ctx, ctx.create_customer_board_model, "TBOX-C1", "Cedar")
    as_admin(ctx, ctx.shred_store, made["store"]["uuid"])
    assert ctx.guide_step("TBOX-C1") is None


def test_req_trn_021_an_operator_gets_the_cards_once_an_ai_model_judges(
    qtbot: QtBot, ctx: AppContext, monkeypatch: pytest.MonkeyPatch
) -> None:
    """While the guide sets a board model up and no AI model judges its boards, an Operator's Home says it is still
    being set up; once one does, before its first board, the Operator gets the cards, Inspection's among them."""
    win, guide, images = home(qtbot, ctx, "operator")
    page = cast(HomePage, win.pages["Home"])
    assert page.empty.isVisible() and not page.cards.isVisible()
    real = ctx.board_status
    monkeypatch.setattr(ctx, "board_status", lambda bm: dataclasses.replace(real(bm), model_version="v1.0"))
    page.on_show()
    assert page.cards.isVisible() and not page.empty.isVisible() and not guide.isVisible()
