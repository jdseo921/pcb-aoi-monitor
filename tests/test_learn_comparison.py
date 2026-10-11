"""REQ-RCP-007 and REQ-TRN-018 (ADR 0017): fine alignment refines ORB's homography to a fraction of a pixel when the
recipe asks, and Learn From Labelled Boards chooses the comparison's Pixel difference, Minimum defect area and fine
alignment from a board model's labelled boards, counting the choice and the recipe's own on boards held out of
choosing. The boards here are drawings: what they show is that the steps work, never an accuracy."""

from __future__ import annotations

import functools
import itertools
import math
import uuid
from pathlib import Path
from unittest import mock

import cv2
import numpy as np
import pytest
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QLabel, QMessageBox, QVBoxLayout, QWidget
from pytestqt.qtbot import QtBot

from aoi.core import stats, tuning
from aoi.core.imaging import refine, registration, save_image
from aoi.core.inspector import Inspector
from aoi.core.jobs import JobCancelled
from aoi.core.labels import DefectBox
from aoi.core.recipe import Recipe
from aoi.core.services import AppContext
from aoi.errors import AoiError
from aoi.ui.main_window import MainWindow
from aoi.ui.pages.recipe_editor import RecipeEditorPage
from aoi.ui.pages.recipe_learn import LearnSheet

BOARD = "LEARN-01"
DEFECT = (300, 200, 14, 10)  # x, y, w, h of the copper speck drawn on each NG board, before it is moved


def _moved(golden: np.ndarray, dx: float, dy: float, degrees: float) -> np.ndarray:
    """The Golden board placed off by a fraction of a pixel and turned a little, as a board on the line lies."""
    h, w = golden.shape[:2]
    m = cv2.getRotationMatrix2D((w / 2, h / 2), degrees, 1.0)
    m[:, 2] += (dx, dy)
    return cv2.warpAffine(golden, m, (w, h), flags=cv2.INTER_CUBIC, borderMode=cv2.BORDER_REPLICATE)


def _board(golden: np.ndarray, i: int, ng: bool) -> tuple[np.ndarray, list[tuple[int, int, int, int]]]:
    """Board i: the Golden board moved by its own sub-pixel offset, with sensor noise; an NG board also has a copper
    speck at DEFECT, its box given in the board's own pixels."""
    rng = np.random.default_rng(i)
    board = golden.copy()
    boxes = []
    if ng:
        x, y, w, h = DEFECT
        x, y = x + 40 * (i % 5), y + 30 * (i % 4)
        cv2.rectangle(board, (x, y), (x + w - 1, y + h - 1), (60, 140, 200), -1)
        boxes.append((x, y, w, h))
    board = _moved(board, 0.3 + 0.1 * (i % 4), -0.4 + 0.1 * (i % 3), 0.15)
    noisy = board.astype(np.float32) + rng.normal(0, 2, board.shape)
    return np.clip(noisy, 0, 255).astype(np.uint8), boxes


@pytest.fixture
def golden(synthetic_dataset: Path) -> np.ndarray:
    img = cv2.imread(str(synthetic_dataset / "golden.png"))
    assert img is not None
    return img


def _residual(h_found: np.ndarray, h_true: np.ndarray, shape: tuple[int, ...]) -> float:
    """The largest distance, in px, between where two homographies put a grid of the board's points."""
    ys, xs = np.mgrid[0 : shape[0] : 40, 0 : shape[1] : 40]
    pts = np.stack([xs.ravel(), ys.ravel()], axis=1).astype(np.float64).reshape(-1, 1, 2)
    return float(
        np.linalg.norm(cv2.perspectiveTransform(pts, h_found) - cv2.perspectiveTransform(pts, h_true), axis=2).max()
    )


def test_req_rcp_007_fine_alignment_places_a_board_closer_than_orb(golden: np.ndarray) -> None:
    """A board moved by 0.45 px and turned 0.15 degrees: ORB places it within a pixel or so, the refinement within a
    tenth of one; a picture with nothing to match is left to ORB."""
    h, w = golden.shape[:2]
    board = _moved(golden, 0.45, -0.35, 0.15)
    m = cv2.getRotationMatrix2D((w / 2, h / 2), 0.15, 1.0)
    m[:, 2] += (0.45, -0.35)
    truth = np.linalg.inv(np.vstack([m, [0, 0, 1]]))  # the board's pixels back onto the Golden board's
    orb, info = registration(board, golden)
    assert orb is not None and info["method"] == "orb-homography"
    fine, info = registration(board, golden, fine=True)
    assert fine is not None and info["method"] == "orb-homography+fine"
    before, after = _residual(orb, truth, golden.shape), _residual(fine, truth, golden.shape)
    assert after < 0.1 < before, (before, after)
    flat = np.full_like(golden, 128)
    assert refine(flat, flat, np.eye(3)) is None


def test_req_rcp_007_off_by_default_stored_only_when_on_and_judging_closer(golden: np.ndarray) -> None:
    """A recipe stores fine alignment only when it is on, so every recipe saved before reads and judges as it did;
    on, the Inspector names it as the alignment method and the board differs less from the Golden board."""
    assert "fine_alignment" not in Recipe(board_model=BOARD).to_dict()
    on = Recipe(board_model=BOARD, use_ai=False, fine_alignment=True)
    assert on.to_dict()["fine_alignment"] is True and Recipe.from_dict(on.to_dict()) == on
    board, _ = _board(golden, 1, ng=False)
    off = Inspector(Recipe(board_model=BOARD, use_ai=False), reference=golden).inspect(board)
    fine = Inspector(on, reference=golden).inspect(board)
    assert off.compare is not None and fine.compare is not None
    assert (off.compare.metrics["alignment_method"], fine.compare.metrics["alignment_method"]) == (
        "orb-homography",
        "orb-homography+fine",
    )
    assert fine.compare.metrics["mean_abs_diff"] < off.compare.metrics["mean_abs_diff"]


def test_req_trn_018_boxes_follow_the_board_onto_the_golden_board() -> None:
    shift = np.array([[1, 0, 10.5], [0, 1, -5.2], [0, 0, 1]], dtype=np.float64)
    assert tuning.map_boxes([(20, 30, 10, 8)], shift, (640, 480), (640, 480)) == [(30, 24, 11, 9)]
    assert tuning.map_boxes([(20, 30, 10, 8)], None, (1280, 960), (640, 480)) == [(10, 15, 5, 4)]  # a plain resize
    assert tuning.map_boxes([(700, 30, 10, 8), (630, 470, 20, 20)], None, (640, 480), (640, 480)) == [
        (630, 470, 10, 10)
    ]


def test_req_trn_018_fine_alignment_is_chosen_only_for_fewer_false_calls() -> None:
    c = tuning.Counts
    same = {(30, 5): c(defects=10, found=10, windows=20, false_windows=2)}
    assert tuning.choose_setting({False: same, True: same}) == (False, 30, 5)  # no better: off, which is faster
    better = {(30, 5): c(defects=10, found=10, windows=20, false_windows=1)}
    assert tuning.choose_setting({False: same, True: better}) == (True, 30, 5)
    missing = {(30, 5): c(defects=10, found=8, windows=20, false_windows=0)}
    assert tuning.choose_setting({False: same, True: missing}) == (False, 30, 5)  # 2 of 10 missed is over 1 %
    with pytest.raises(ValueError):
        tuning.choose_setting({False: {}, True: {}})


def test_req_trn_018_of_settings_that_tie_the_one_deepest_among_them_is_chosen() -> None:
    """On a few boards, every pair from 20 to 40 finds each defect with no false call, 10 makes false calls and 50
    misses: the highest pair that ties, (40, 20), is a step from missing; the middle one, (30, 10), is chosen."""
    c = tuning.Counts
    table = {}
    for t in (10, 20, 30, 40, 50):
        for a in (5, 10, 20):
            found, false = (8, 0) if t < 50 else (6, 0)
            table[t, a] = c(defects=8, found=found, windows=30, false_windows=3 if t == 10 else false)
    assert tuning.choose(table) == (30, 10)
    assert tuning.choose_setting({False: table, True: table}) == (False, 30, 10)


def _labelled(ctx: AppContext, golden: np.ndarray, folder: Path, ok: int, ng: int) -> None:
    """The board model with the Golden board, then `ok` OK boards and `ng` NG boards each with its speck boxed. Their
    UUIDs are counted, 1, 2, 3…, not drawn: the held-out third is drawn with the seed from the boards in their UUIDs'
    order, so random UUIDs held out other boards on each run, and the learned Pixel difference came out 35 on one run
    and 40 on the next (#389)."""
    counted = (uuid.UUID(int=n, version=4) for n in itertools.count(1))
    with mock.patch("uuid.uuid4", side_effect=counted):
        _write_labelled(ctx, golden, folder, ok, ng)


def _write_labelled(ctx: AppContext, golden: np.ndarray, folder: Path, ok: int, ng: int) -> None:
    folder.mkdir()
    save_image(folder / "golden.png", golden)
    ctx.import_samples(BOARD, [str(folder / "golden.png")], "OK")
    oks = []
    for i in range(ok):
        save_image(folder / f"ok_{i}.png", _board(golden, i, ng=False)[0])
        oks.append(str(folder / f"ok_{i}.png"))
    ctx.import_samples(BOARD, oks, "OK")
    for i in range(ng):
        img, boxes = _board(golden, 100 + i, ng=True)
        save_image(folder / f"ng_{i}.png", img)
        uids: list[str] = []
        ctx.import_samples(BOARD, [str(folder / f"ng_{i}.png")], "NG", "Spurious Copper", added=uids)
        ctx.set_boxes(uids[0], [DefectBox(x, y, w, h, "Spurious Copper") for x, y, w, h in boxes])


def test_req_trn_018_learns_from_labelled_boards_and_counts_on_boards_held_out(
    ctx: AppContext, golden: np.ndarray, tmp_path: Path
) -> None:
    """Six OK and six NG boards: a third of each drawn with the seed is held out; the setting chosen on the others
    finds every speck there and is counted beside the recipe's own on the held-out boards, with 95 % upper bounds.
    Nothing is written: the recipe stays at its revision."""
    _labelled(ctx, golden, tmp_path / "boards", ok=6, ng=6)
    seen: list[tuple[int, int]] = []
    found = ctx.learn_comparison(BOARD, progress=lambda n, of: seen.append((n, of)), seed=11)
    assert seen[-1] == (12, 12) and len(seen) == 12
    assert found["counted_on"] == {"ok": 2, "ng": 2, "boxes": 2, "by": "seed", "seed": 11}
    assert (found["chosen_on"]["ok"], found["chosen_on"]["ng"], found["chosen_on"]["boxes"]) == (4, 4, 4)
    assert found["current"] == {"fine_alignment": False, "diff_threshold": 45, "min_defect_area": 40}
    chosen = found["chosen"]
    assert set(chosen) == {"fine_alignment", "diff_threshold", "min_defect_area"}
    assert chosen["diff_threshold"] in tuning.THRESHOLDS and chosen["min_defect_area"] in tuning.AREAS
    assert found["chosen_on"]["rates"]["missed"]["n"] == 0
    held = found["held_out"]["chosen"]
    assert held["missed"]["of"] == 2 and held["false_calls"]["of"] == held["counts"]["windows"]
    assert held["missed"]["limit"] is not None and 0 < held["missed"]["limit"] <= 1
    assert found["held_out"]["current"]["missed"]["of"] == 2
    assert found["left_out"] == {"other_view": 0, "unsure": 0, "no_boxes": 0, "unreadable": 0, "why": None}
    assert ctx.recipe(BOARD)[0] == 1 and not ctx.audit_entries(action="recipe.save")
    again = ctx.learn_comparison(BOARD, seed=11)
    assert again["chosen"] == chosen and again["held_out"] == found["held_out"]  # one seed, one draw, one choice


def test_req_trn_018_counts_on_the_locked_validation_set_when_it_holds_enough(
    ctx: AppContext, golden: np.ndarray, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Boards whose SHA-256 a locked validation set holds are the ones counted on, whatever the seed."""
    _labelled(ctx, golden, tmp_path / "boards", ok=3, ng=4)
    ng = ctx.samples(BOARD, "NG")
    locked = {ng[0]["sha256"], ng[1]["sha256"]}
    monkeypatch.setattr(ctx.db, "split_sha256", lambda part: locked if part == "validation" else set())
    found = ctx.learn_comparison(BOARD, seed=3)
    assert found["counted_on"] == {"ok": 0, "ng": 2, "boxes": 2, "by": "validation", "seed": None}
    assert (found["chosen_on"]["ok"], found["chosen_on"]["ng"]) == (3, 2)


def test_req_trn_018_too_few_boards_no_golden_board_and_cancel(
    ctx: AppContext, golden: np.ndarray, tmp_path: Path
) -> None:
    """AOI-RCP-013 says why it cannot learn: no Golden board, or under three NG boards with boxes (an NG board with no
    box, or in another view, does not count); Cancel stops it with nothing written; an Operator may not run it."""
    with pytest.raises(AoiError) as e:
        ctx.learn_comparison("NO-SUCH-BOARD")
    assert e.value.code == "AOI-RCP-013" and "no Golden board" in str(e.value)
    _labelled(ctx, golden, tmp_path / "boards", ok=2, ng=2)
    save_image(tmp_path / "unboxed.png", _board(golden, 7, ng=True)[0])
    ctx.import_samples(BOARD, [str(tmp_path / "unboxed.png")], "NG", "Spurious Copper")
    with pytest.raises(AoiError) as e:
        ctx.learn_comparison(BOARD)
    assert e.value.code == "AOI-RCP-013" and "2 NG image(s) with defect boxes in the Top view" in str(e.value)
    img, boxes = _board(golden, 9, ng=True)
    save_image(tmp_path / "ng_more.png", img)
    uids: list[str] = []
    ctx.import_samples(BOARD, [str(tmp_path / "ng_more.png")], "NG", "Spurious Copper", added=uids)
    ctx.set_boxes(uids[0], [DefectBox(*boxes[0], "Spurious Copper")])
    found = ctx.learn_comparison(BOARD, seed=1)
    assert found["left_out"]["no_boxes"] == 1
    with pytest.raises(JobCancelled):
        ctx.learn_comparison(BOARD, should_stop=lambda: True)
    ctx.set_user("operator")
    with pytest.raises(AoiError) as e:
        ctx.learn_comparison(BOARD)
    assert e.value.code == "AOI-USR-001"
    assert math.isfinite(found["held_out"]["chosen"]["missed"]["limit"])


def _cut(sheet: LearnSheet) -> list[str]:
    """The sheet's wrapped lines shown with less height than their text needs at their width."""
    return [
        label.text()
        for label in sheet.findChildren(QLabel)
        if label.isVisible() and label.wordWrap() and label.heightForWidth(label.width()) > label.height()
    ]


def test_req_trn_018_the_learn_sheet_keeps_every_line_whole_in_a_narrow_column(qtbot: QtBot) -> None:
    """#389's Windows CI: the sheet's grid gave a count over its bound 73 px where its three lines needed 76, and cut
    the last. Each wrapped line now asks for the height its text needs at the width it has, so the column lays it out
    whole: in columns 260 to 400 px wide, where plain wrapped labels were cut in the test font, nothing is."""
    rates = {"missed": stats.rate(0, 2), "false_calls": stats.rate(0, 6), "ok_called_ng": stats.rate(0, 2)}
    found = {
        "chosen_on": {"ok": 4, "ng": 4, "boxes": 4},
        "counted_on": {"by": "split", "ok": 2, "ng": 2, "seed": 11},
        "current": {"diff_threshold": 45, "min_defect_area": 40, "fine_alignment": False},
        "chosen": {"diff_threshold": 35, "min_defect_area": 20, "fine_alignment": True},
        "held_out": {"current": rates, "chosen": rates},
        "left_out": {"no_boxes": 1, "other_view": 0, "unsure": 2, "unreadable": 0, "why": ""},
    }
    column = QWidget()
    qtbot.addWidget(column)
    sheet = LearnSheet(lambda _found: None)
    QVBoxLayout(column).addWidget(sheet, 1)  # as the Recipe Editor's column holds it, in the tabs' place
    sheet.show_found(found)
    column.show()
    cut = {}
    for width in range(260, 401, 20):
        column.resize(width, 900)
        qtbot.wait(20)
        cut[width] = _cut(sheet)
    assert cut == {width: [] for width in range(260, 401, 20)}
    assert sheet.text_at(4, 2) == "0 of 2\n95 % upper bound 77.6 %"


def test_req_trn_018_learn_on_the_recipe_editor_sets_the_fields_and_save_keeps_the_evidence(
    qtbot: QtBot, ctx: AppContext, golden: np.ndarray, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Ctrl+L runs the learning off the UI thread and shows its sheet under the tabs: where it chose and counted, the
    recipe's setting beside the learned one, counts over their bounds, every line whole at 1600 x 900. Use Learned
    Values sets the fields and nothing else; Save Recipe lists the changes and offers the evidence as the reason, which
    the audit entry keeps. Fine alignment is a tick on Thresholds, stored and listed as on or off."""
    monkeypatch.setattr(QMessageBox, "information", staticmethod(lambda *_: QMessageBox.StandardButton.Ok))
    _labelled(ctx, golden, tmp_path / "boards", ok=6, ng=6)
    monkeypatch.setattr(ctx, "learn_comparison", functools.partial(ctx.learn_comparison, seed=11))
    win = MainWindow(ctx)
    qtbot.addWidget(win)
    win.resize(1600, 900)
    win.show()
    win.set_user("engineer")
    win._on_board_model(BOARD)
    win.navigate("Recipe Editor")
    page = win.pages["Recipe Editor"]
    assert isinstance(page, RecipeEditorPage)
    rev = page.rev
    qtbot.waitUntil(win.isActiveWindow, timeout=5000)
    QTest.keyClick(page.view, Qt.Key.Key_L, Qt.KeyboardModifier.ControlModifier)
    sheet = page.learn_sheet
    qtbot.waitUntil(sheet.isVisible, timeout=60000)
    assert sheet.what.text() == (
        "Chosen on 8 board(s): 4 OK and 4 NG with 4 defect box(es). Counted on 4 other board(s), a third held out"
        " with seed 11: 2 OK and 2 NG."
    )
    assert [sheet.text_at(r, 1) for r in (1, 2, 3)] == ["45", "40", "off"]
    assert [sheet.text_at(r, 2) for r in (1, 2, 3)] == ["40", "20", "off"]
    assert sheet.text_at(4, 2).split("\n") == ["0 of 2", "95 % upper bound 77.6 %"]
    assert sheet.text_at(5, 2).split("\n")[0] == "0 of 6" and sheet.left.isHidden()
    qtbot.waitUntil(lambda: not _cut(sheet), timeout=5000)  # a line's height follows its width in one more pass
    assert page.diff.value() == 45, "nothing changes before Use Learned Values"
    sheet.btn_use.click()
    assert sheet.isHidden() and (page.diff.value(), page.area.value(), page.fine.isChecked()) == (40, 20, False)
    page.ask_save()
    assert page.save_sheet.changes.text().split("\n") == [
        "Pixel difference: 45 → 40",
        "Minimum defect area (px): 40 → 20",
    ]
    reason = page.save_sheet.reason.text()
    assert reason.startswith("Learned from 8 labelled board(s); on 4 held out: missed defects 0 of 2, 95 % upper")
    page.save_sheet.btn_save.click()
    entry = ctx.audit_entries(action="recipe.save", object_uuid=ctx.recipe_history(BOARD)[0]["uuid"])[0]
    assert entry["reason"] == reason and entry["after"]["diff_threshold"] == 40 and page.rev == rev + 1
    page.fine.setChecked(True)
    page.ask_save()
    assert page.save_sheet.changes.text() == "Fine alignment: off → on" and not page.save_sheet.reason.text()
    page.save_sheet.reason.setText("fewer false calls on copper edges")  # the recipe leaves Stage 1 checks uncovered
    page.save_sheet.btn_save.click()
    assert ctx.recipe(BOARD)[1].fine_alignment is True
    assert ctx.inspector(BOARD).recipe.fine_alignment is True
