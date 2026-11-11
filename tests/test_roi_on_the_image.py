"""REQ-RCP-002, REQ-RCP-005 (senior review 2026-11-06, ENG-2, ENG-3): an enabled ROI not wholly on the image gives
the board no verdict (AOI-INSP-021); Save Recipe and Calibrate Scale… refuse one off the Golden board (AOI-RCP-014,
-015); with the AI check off, which judges ROIs, no check is covered by an ROI and each board says no ROI was judged."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import cv2
import pytest
from pytestqt.qtbot import QtBot

from aoi.core import checklist
from aoi.core.checklist import NOT_COVERED, ROI
from aoi.core.explain import NOTES, explain
from aoi.core.imaging import list_images
from aoi.core.inspector import ROIS_NOT_JUDGED_NOTE, re_grade
from aoi.core.recipe import ROI as Roi
from aoi.core.recipe import Recipe
from aoi.core.services import AppContext
from aoi.errors import AoiError
from tests.test_req_done_in_v01 import BOARD, _window


def _ok_board(dataset: Path) -> str:
    return str(sorted(list_images(dataset / "test" / "ok"))[0])


@pytest.mark.parametrize(
    "roi",
    [
        Roi("P2", "Polarity", 620, 460, 60, 60),  # past the right and the bottom edge of the 640 x 480 Golden board
        Roi("P3", "Polarity", 700, 10, 50, 50),  # wholly off it
        Roi("P4", "Polarity", -10, 10, 50, 50),  # past the left edge
        Roi("P5", "Polarity", 100, 100, 0, 0),  # of no size
    ],
)
def test_req_rcp_002_an_roi_not_wholly_on_the_image_gives_the_board_no_verdict(
    trained_ctx: AppContext, synthetic_dataset: Path, roi: Roi
) -> None:
    """Before, the part on the image was judged and an ROI with none on it was skipped, so the board could be OK with
    the place the recipe names never looked at; now the board is refused, naming the ROI, its box and the image's size.
    An ROI turned off is not judged, wherever it lies, and one reaching the edge exactly is judged."""
    rcp = trained_ctx.recipe(BOARD)[1]
    img = trained_ctx.load_image(_ok_board(synthetic_dataset))
    with pytest.raises(AoiError) as refused:
        trained_ctx.inspector(BOARD, recipe=replace(rcp, rois=[roi])).inspect(img)
    assert refused.value.code == "AOI-INSP-021"
    assert f"ROI {roi.name} " in refused.value.what and "640 × 480 px" in refused.value.what
    assert f"{roi.x}, {roi.y}, {roi.w} × {roi.h} px" in refused.value.what
    edge = Roi("P1", "Polarity", 580, 420, 60, 60)
    res = trained_ctx.inspector(BOARD, recipe=replace(rcp, rois=[edge, replace(roi, enabled=False)])).inspect(img)
    assert [c.region for c in res.checks if c.source == "ROI"] == ["P1 @ 580,420 60x60"]


def test_req_rcp_002_a_scale_that_moves_an_roi_off_the_golden_board_refuses_the_board(
    trained_ctx: AppContext, synthetic_dataset: Path
) -> None:
    """The review's case: an ROI in mm, NG at 10 px/mm, was past the Golden board at 20 px/mm and the board OK. Such
    a scale is now refused as it is set (the next test); one stored before gives no verdict, and nothing is stored."""
    ok_board, rcp = _ok_board(synthetic_dataset), trained_ctx.recipe(BOARD)[1]
    trained_ctx.set_scale(BOARD, 100, 10)
    strict = Roi("P1", "Presence", 500, 300, 60, 60, ai_score=0.001)  # an AI score any board reaches: NG
    trained_ctx.save_recipe(replace(rcp, rois=[strict]).in_mm(trained_ctx.scale(BOARD)), "review case")
    assert trained_ctx.inspect_file(BOARD, ok_board, save=False).verdict == "NG"
    trained_ctx.db.set_scale(BOARD, 20.0)  # as stored before: the ROI now at 1000, 600, past the 640 x 480 board
    before = len(trained_ctx.inspections(board_model=BOARD))
    with pytest.raises(AoiError, match="AOI-INSP-021"):
        trained_ctx.inspect_file(BOARD, ok_board, save=True)
    assert len(trained_ctx.inspections(board_model=BOARD)) == before


def test_req_rcp_002_a_scale_that_moves_an_roi_off_is_refused_and_a_camera_change_sets_its_golden_board_first(
    trained_ctx: AppContext, synthetic_dataset: Path, tmp_path: Path
) -> None:
    """Review of the fix: a recalibration 0.1 % off put an ROI drawn to the board's edge 1 px past it, and the line
    stopped at the next board with no word. Now it is refused (AOI-RCP-015), naming the ROI, its box and the Golden
    board, nothing changed; one turned off, or in px, lets it through. Set Reference checks none, so a camera with fewer
    pixels takes the manual's order: its Golden board, then the scale calibrated on it (REQ-RCP-006, reviews)."""
    rcp = trained_ctx.recipe(BOARD)[1]
    trained_ctx.set_scale(BOARD, 100, 10)
    edge = Roi("P1", "Presence", 580, 420, 60, 60, mm=[58.0, 42.0, 6.0, 6.0])  # to the corner, as a drag stops there
    trained_ctx.save_recipe(replace(rcp, rois=[edge, Roi("P2", "Polarity", 500, 300, 60, 60)]), "at the edge")
    with pytest.raises(AoiError) as refused:
        trained_ctx.set_scale(BOARD, 100.1, 10)
    assert refused.value.code == "AOI-RCP-015" and "581, 420, 60 × 60 px" in refused.value.what
    assert "640 × 480 px" in refused.value.what and trained_ctx.scale(BOARD) == 10.0
    small = tmp_path / "small.png"  # the board as a camera of half the resolution sees it
    cv2.imwrite(str(small), cv2.resize(cv2.imread(_ok_board(synthetic_dataset)), (320, 240)))
    trained_ctx.import_samples(BOARD, [str(small)], "OK")
    sample = next(x for x in trained_ctx.samples(BOARD, "OK") if Path(x["path"]).stem.startswith("small"))
    trained_ctx.set_reference(BOARD, sample["id"])
    assert trained_ctx.reference_image(BOARD) == sample["path"]
    with pytest.raises(AoiError) as refused:
        trained_ctx.set_scale(BOARD, 100, 10)  # the old scale, against the new Golden board
    assert refused.value.code == "AOI-RCP-015" and "320 × 240 px" in refused.value.what
    assert trained_ctx.set_scale(BOARD, 50, 10) == pytest.approx(5.0)  # P1 at 290, 210, 30 × 30 px; P2 in px, not moved
    trained_ctx.save_recipe(replace(rcp, rois=[replace(edge, enabled=False)]), "turned off")
    assert trained_ctx.set_scale(BOARD, 50.1, 10) == pytest.approx(5.01)


def test_req_rcp_002_save_recipe_checks_no_roi_without_a_golden_board_size(trained_ctx: AppContext) -> None:
    """Review of the fix: a Golden board whose header gave no size made every ROI "off a 0 × 0 px board". With no
    Golden board, or one whose size cannot be read, Save Recipe checks no ROI, as inspecting then refuses every board
    itself (AOI-INSP-009)."""
    off = Roi("P2", "Polarity", 620, 460, 60, 60)
    trained_ctx.ensure_board_model("NOGB")
    rev = trained_ctx.save_recipe(Recipe(board_model="NOGB", rois=[off]), "no Golden board")
    assert trained_ctx.recipe("NOGB")[0] == rev
    golden = Path(str(trained_ctx.reference_image(BOARD)))
    golden.write_bytes(golden.read_bytes()[:20])  # the PNG signature and part of its first chunk: no size
    rev, rcp = trained_ctx.recipe(BOARD)
    assert trained_ctx.save_recipe(replace(rcp, rois=[off]), "its size not read") == rev + 1


def test_req_rcp_002_save_recipe_refuses_an_roi_past_the_golden_board(trained_ctx: AppContext) -> None:
    """In px, and in mm at the board model's scale: nothing is stored, and the message names the box as the engine
    would apply it. One on the Golden board, and one past it that is turned off, are saved."""
    rev, rcp = trained_ctx.recipe(BOARD)
    for rois, scale in (([Roi("P2", "Polarity", 620, 460, 60, 60)], None), ([Roi("P3", "Presence", 0, 0, 10, 10)], 1)):
        if scale:
            trained_ctx.set_scale(BOARD, 100, 10)  # 10 px/mm: the ROI's 10 mm become 100 px
            rois = [replace(rois[0], mm=[60.0, 45.0, 10.0, 10.0])]  # 600, 450, 100 × 100 px
        with pytest.raises(AoiError) as refused:
            trained_ctx.save_recipe(replace(rcp, rois=rois), "off the board")
        assert refused.value.code == "AOI-RCP-014" and f"ROI {rois[0].name} " in refused.value.what
        assert trained_ctx.recipe(BOARD)[0] == rev, "nothing stored"
    assert "600, 450, 100 × 100 px" in refused.value.what and "640 × 480 px" in refused.value.what
    on, off = Roi("P1", "Presence", 0, 0, 640, 480), Roi("P2", "Polarity", 620, 460, 60, 60, enabled=False)
    assert trained_ctx.save_recipe(replace(rcp, rois=[on, off]), "on the board") == rev + 1


def test_req_rcp_005_rois_with_the_ai_check_off_cover_nothing_and_each_board_says_so(
    trained_ctx: AppContext, synthetic_dataset: Path
) -> None:
    """Before, the AOI checks tab marked Missing Component covered by an ROI the engine never judged with the AI check
    off, and the board's explanation did not say so. Now the check is not covered, so saving asks for a reason, and
    the result notes that no ROI was judged, once, also when judged again."""
    rcp = trained_ctx.recipe(BOARD)[1]
    img = trained_ctx.load_image(_ok_board(synthetic_dataset))
    presence = Roi("P1", "Presence", 500, 300, 60, 60)
    for use_ai, how in ((True, ROI), (False, NOT_COVERED)):
        r = replace(rcp, rois=[presence], use_ai=use_ai)
        (cover,) = [c for c in checklist.coverage(r) if c.check == "Missing Component"]
        assert cover.how == how and ("Missing Component" in checklist.uncovered(r)) is (not use_ai)
        res = trained_ctx.inspector(BOARD, recipe=r).inspect(img)
        assert (ROIS_NOT_JUDGED_NOTE in res.notes) is (not use_ai)
        assert any(c.source == "ROI" for c in res.checks) is use_ai
    assert NOTES[ROIS_NOT_JUDGED_NOTE] in [s.template for s in explain(res)]
    assert re_grade(res, r, None).notes.count(ROIS_NOT_JUDGED_NOTE) == 1


def test_req_rcp_002_compare_says_an_roi_off_the_image_on_its_pane(
    qtbot: QtBot, trained_ctx: AppContext, synthetic_dataset: Path, tmp_path: Path, dialogs: list[tuple[str, str]]
) -> None:
    """Compare judging its test board on its own (quiet, as after a header change) against a smaller Golden board (a
    camera change, its scale not calibrated yet) says AOI-INSP-021 on its pane, as AOI-INSP-010 (#247): no dialog."""
    rcp = trained_ctx.recipe(BOARD)[1]
    trained_ctx.save_recipe(replace(rcp, rois=[Roi("P1", "Presence", 580, 420, 60, 60)]), "at the edge")
    small = tmp_path / "small.png"
    cv2.imwrite(str(small), cv2.resize(cv2.imread(_ok_board(synthetic_dataset)), (320, 240)))
    trained_ctx.import_samples(BOARD, [str(small)], "OK")
    win = _window(qtbot, trained_ctx)
    compare = win.pages["Compare"]
    win.navigate("Compare")
    compare.set_test(str(small))
    qtbot.waitUntil(lambda: compare.res is not None and compare._bg is None, timeout=60000)
    sample = next(x for x in trained_ctx.samples(BOARD, "OK") if Path(x["path"]).stem.startswith("small"))
    trained_ctx.set_reference(BOARD, sample["id"])
    compare._start(quiet=True)
    qtbot.waitUntil(lambda: compare._bg is None and compare.test_empty.isVisible(), timeout=60000)
    assert dialogs == [] and compare.res is None
    assert compare.test_empty.sentence.text().startswith("AOI-INSP-021 "), compare.test_empty.sentence.text()
