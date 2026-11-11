"""#460 and #461: a customer's own photos are lit, placed and sized unlike the Golden board, and their good boards
differ from one another. A photo is brought to the Golden board's lighting and frame before either check reads it, a
photo much larger or smaller is matched at the Golden board's scale, and the comparison counts a pixel's difference
only by what exceeds the difference good boards showed there, which training measures and the Golden board's file
carries. The boards here are drawings (tools/varied_boards.py): they show that the steps work, never an accuracy."""

from __future__ import annotations

import json
import random
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import cv2
import numpy as np
import pytest

from aoi.config import Settings
from aoi.core import golden
from aoi.core.compare import ai_mask, compare, lab_difference, region_level, regions_from_mask
from aoi.core.imaging import (
    COVERAGE_WARN,
    LIGHT_WARN,
    align_to_reference,
    conform,
    frame_mask,
    load_image,
    load_image_bytes,
    match_light,
    outside_frame,
    registration,
    save_image,
)
from aoi.core.inspector import Inspector
from aoi.core.recipe import Recipe
from aoi.core.services import SSIM_MARGIN, AppContext
from aoi.data import credentials
from tests.conftest import engineer
from tools.make_synthetic_dataset import H, W, draw_board
from tools.trainable import trainable
from tools.varied_boards import varied_board, write_boards

BM = "VARIED-A1"


def board(seed: int = 5, defect: str | None = None) -> np.ndarray:
    return draw_board(random.Random(seed), defect)


def lit(img: np.ndarray, gain: Any = 1.0, offset: float = 0.0) -> np.ndarray:
    return np.clip(img.astype(np.float32) * gain + offset, 0, 255).astype(np.uint8)


def apart(a: np.ndarray, b: np.ndarray) -> float:
    """The mean difference of two images in grey levels."""
    return float(np.abs(a.astype(np.float32) - b.astype(np.float32)).mean())


# --- lighting ---------------------------------------------------------------------------------------------------------
@pytest.mark.parametrize("gain", [0.7, 0.85, 1.15, 1.3])
def test_460_a_photo_lit_brighter_or_darker_is_judged_as_the_golden_board_is_lit(gain: float) -> None:
    ref = board()
    out, info = match_light(lit(ref, gain), ref)
    assert info["light_matched"] and info["light_gain"] == pytest.approx(gain, abs=0.03)
    assert info["light_change"] == pytest.approx(abs(gain - 1), abs=0.03) and info["light_tilt"] < 0.03
    assert apart(out, ref) < 2.0 < apart(lit(ref, gain), ref)


def test_460_a_colour_cast_and_a_raised_black_level_are_taken_out() -> None:
    ref = board()
    warm = lit(ref, np.array([0.9, 1.0, 1.12], np.float32), 10.0)  # less blue, more red, and 10 grey levels of haze
    out, info = match_light(warm, ref)
    assert info["light_matched"] and apart(out, ref) < 2.0 < apart(warm, ref)


def test_460_light_from_one_side_is_measured_as_a_tilt_and_taken_out() -> None:
    ref = board()
    side = np.linspace(0.85, 1.15, W, dtype=np.float32)[None, :, None]
    out, info = match_light(lit(ref, side), ref)
    assert info["light_tilt"] == pytest.approx(0.30, abs=0.04) and info["light_gain"] == pytest.approx(1.0, abs=0.03)
    assert info["light_change"] == pytest.approx(0.15, abs=0.04)  # the furthest it is from the Golden board's anywhere
    assert apart(out, ref) < 3.5 < apart(lit(ref, side), ref)


def test_460_a_photo_lit_as_the_golden_board_keeps_every_pixel() -> None:
    ref = board()
    noise = np.random.default_rng(1).normal(0, 2, ref.shape)
    photo = np.clip(ref + noise, 0, 255).astype(np.uint8)
    out, info = match_light(photo, ref)
    assert out is photo and not info["light_matched"]  # a station with steady light is judged as before #460
    assert info["light_change"] < 0.02


def test_460_a_defect_does_not_pull_the_lighting_and_is_still_there_after_it() -> None:
    ref, faulty = board(), board(defect="Missing Component")
    where = np.abs(faulty.astype(int) - ref.astype(int)).max(axis=2) > 40
    assert where.sum() > 200, "the drawn defect is too small to test with"
    out, info = match_light(lit(faulty, 1.2), ref)
    assert info["light_gain"] == pytest.approx(1.2, abs=0.03)
    assert apart(out[~where], ref[~where]) < 2.0  # the board around it is as the Golden board
    assert apart(out[where], faulty[where]) < 6.0 < apart(out[where], ref[where])  # and the defect as photographed


@pytest.mark.parametrize("photo", [np.zeros((H, W, 3), np.uint8), np.full((H, W, 3), 255, np.uint8)])
def test_460_a_photo_with_nothing_to_measure_is_left_as_it_is(photo: np.ndarray) -> None:
    out, info = match_light(photo, board())
    assert out is photo and not info["light_matched"] and info["light_gain"] == 1.0


def test_460_the_correction_is_held_within_its_limits() -> None:
    ref = board()
    out, info = match_light(lit(ref, 0.3), ref)  # a photo taken nearly in the dark
    assert info["light_change"] > LIGHT_WARN  # said, and the inspection warns (below)
    assert int(out.max()) <= 255 and out.dtype == np.uint8 and out.mean() < ref.mean()  # not blown up to match


# --- the frame --------------------------------------------------------------------------------------------------------
def test_460_frame_mask_is_none_for_a_photo_that_shows_the_whole_frame() -> None:
    assert frame_mask((H, W, 3), None, (W, H)) is None  # a plain resize
    assert frame_mask((H, W, 3), np.eye(3), (W, H)) is None
    nudge = np.array([[1, 0, 0.6], [0, 1, -0.4], [0, 0, 1]], np.float64)  # under a pixel: the registration's own error
    assert frame_mask((H, W, 3), nudge, (W, H)) is None


def test_460_frame_mask_marks_what_a_shifted_photo_does_not_show() -> None:
    shift = np.array([[1, 0, 64], [0, 1, 0], [0, 0, 1]], np.float64)  # the photo sits 64 px to the right
    mask = frame_mask((H, W, 3), shift, (W, H))
    assert mask is not None and mask.shape == (H, W)
    assert not mask[:, :62].any() and (mask[:, 66:] == 255).all()
    assert frame_mask((H, W, 3), np.full((3, 3), np.nan), (W, H)) is None  # a registration that gave no finite answer


def test_460_conform_holds_the_golden_boards_pixels_where_the_photo_showed_none() -> None:
    ref = board()
    shift = np.array([[1, 0, 64], [0, 1, 0], [0, 0, 1]], np.float64)
    photo = lit(cv2.warpPerspective(ref, np.linalg.inv(shift), (W, H)), 1.2)  # the board 64 px out of view, brighter
    warped = cv2.warpPerspective(photo, shift, (W, H))  # registered: black where the photo showed no board
    assert not warped[:, :60].any()
    out, info = conform(warped, ref, shift, photo.shape)
    assert info["coverage_pct"] == pytest.approx(90.0, abs=0.5) and info["light_matched"]
    assert (out[:, :60] == ref[:, :60]).all()  # not the warp's black border, which both checks would read as a defect
    assert apart(out[:, 70:], ref[:, 70:]) < 2.0  # and the board it did show, lit as the Golden board
    assert info["frame"] is not None and not info["frame"][:, :60].any()
    whole, seen = conform(ref.copy(), ref, np.eye(3), ref.shape)
    assert seen["coverage_pct"] == 100.0 and seen["frame"] is None and (whole == ref).all()


def test_460_outside_frame_takes_a_margin_inside_the_photos_edge() -> None:
    valid = np.zeros((100, 200), np.uint8)
    valid[:, 50:] = 255
    out = outside_frame(valid, 8)
    assert (out[:, :58] == 255).all() and not out[:, 58:192].any()


def test_460_align_reports_what_the_photo_showed_and_how_it_was_lit() -> None:
    ref = board()
    m = cv2.getRotationMatrix2D((W / 2, H / 2), 3.0, 1.0)
    m[:, 2] += (30, -12)
    photo = lit(cv2.warpAffine(ref, m, (W, H)), 1.15)  # turned, shifted and brighter; black where no board was
    aligned, info = align_to_reference(photo, ref)
    assert info["inliers"] >= 12 and info["light_gain"] == pytest.approx(1.15, abs=0.04)
    assert 85.0 < info["coverage_pct"] < 99.0
    result = compare(photo, ref, aligned=aligned, align_info=info)
    assert result.metrics["compare_regions"] == 0, "the warp's border or the lighting was read as a defect"
    assert result.metrics["coverage_pct"] == info["coverage_pct"] and "frame" not in result.metrics


# --- a photo of another size ------------------------------------------------------------------------------------------
@pytest.mark.parametrize("factor", [0.4, 2.5, 4.0])
def test_460_a_photo_much_larger_or_smaller_than_the_golden_board_is_matched_at_its_scale(factor: float) -> None:
    ref = board()
    size = (round(W * factor), round(H * factor))
    photo = cv2.resize(ref, size, interpolation=cv2.INTER_AREA if factor < 1 else cv2.INTER_CUBIC)
    homography, info = registration(photo, ref)
    assert homography is not None and info["inliers"] >= 12
    corner = cv2.perspectiveTransform(np.array([[[size[0], size[1]]]], np.float64), homography).ravel()
    assert corner == pytest.approx([W, H], abs=3.0)  # the photo's far corner lands on the Golden board's
    aligned, seen = align_to_reference(photo, ref)
    assert aligned.shape == ref.shape and apart(aligned, ref) < (9.0 if factor < 1 else 4.0)
    if factor > 1:  # nothing was lost: no difference region on the very board
        assert compare(photo, ref, aligned=aligned, align_info=seen).metrics["compare_regions"] == 0


def test_460_a_photo_near_the_golden_boards_size_is_registered_as_before() -> None:
    ref = board()
    photo = cv2.resize(ref, (round(W * 1.2), round(H * 1.2)), interpolation=cv2.INTER_CUBIC)
    homography, info = registration(photo, ref)
    assert homography is not None and info["inliers"] >= 12


# --- the tolerance good boards teach (#461) ---------------------------------------------------------------------------
def test_461_spread_is_the_mean_and_three_deviations_of_what_good_boards_showed() -> None:
    spread = golden.Spread((4, 6))
    for value in (0, 10, 20):
        d = np.zeros((4, 6), np.uint8)
        d[2, 3] = value  # one pixel that differs from board to board: mean 10, deviation 8.165
        spread.add(d)
    tol = spread.tolerance()
    assert spread.count == 3 and tol.dtype == np.uint8 and tol.shape == (4, 6)
    assert tol[2, 3] == 35 and tol[1, 2] == 35 and tol[3, 4] == 35  # ceil(10 + 3 x 8.165), spread a pixel each way
    assert tol[0, 0] == 0 and tol[2, 5] == 0  # a place that never differs keeps its full sensitivity
    assert not golden.Spread((2, 2)).tolerance().any()  # no board added: no tolerance


def test_461_what_two_good_boards_showed_is_tolerated_and_what_one_showed_is_not() -> None:
    spread = golden.Spread((1, 3))
    for board_no in range(30):  # a date code's stroke: on 2 boards of 30 at one pixel, on 1 of 30 at another
        d = np.zeros((1, 3), np.uint8)
        d[0, 0] = 120 if board_no in (3, 17) else 0
        d[0, 2] = 120 if board_no == 9 else 0
        spread.add(d)
    one, two = golden.Spread((1, 1)), golden.Spread((1, 1))
    for board_no in range(30):
        one.add(np.full((1, 1), 120 if board_no == 9 else 0, np.uint8))
        two.add(np.full((1, 1), 120 if board_no in (3, 17) else 0, np.uint8))
    assert int(two.tolerance()[0, 0]) == 120  # seen twice on good boards: a third board like them is passed over
    assert int(one.tolerance()[0, 0]) < 120 * 0.6  # one board labelled good by mistake does not blind the place
    assert int(spread.tolerance()[0, 0]) == 120  # and each pixel keeps its own


def test_461_the_golden_boards_file_carries_its_tolerance(tmp_path: Path) -> None:
    ref = board()
    path = tmp_path / "golden.png"
    save_image(path, ref)
    plain = path.read_bytes()
    assert golden.extract(plain, (H, W)) is None  # a Golden board from before #461, or a sample set as the reference
    tol = np.random.default_rng(3).integers(0, 40, (H, W), dtype=np.uint8)
    learned = {"images": 31, "sigmas": 3.0, "ssim_low": 0.71}
    path.write_bytes(golden.embed(plain, tol, learned))
    image, data = load_image_bytes(path)
    assert (image == ref).all() and (load_image(path) == ref).all()  # every reader shows the same picture
    found = golden.extract(data, (H, W))
    assert found is not None and (found[0] == tol).all()
    assert found[1] == {"format": 1, "shape": [H, W], **learned}
    again = golden.embed(data, tol // 2, learned)  # embedded again: one chunk, the new one
    assert (
        again.count(golden.TOLERANCE_CHUNK) == 1
        and (golden.extract(again, (H, W)) or [None])[0][5, 5] == tol[5, 5] // 2
    )
    assert golden.extract(data, (H, W + 1)) is None  # not for an image of this shape
    at = data.index(golden.TOLERANCE_CHUNK) + 40
    damaged = data[:at] + bytes([data[at] ^ 0xFF]) + data[at + 1 :]
    assert golden.extract(damaged, (H, W)) is None  # a damaged chunk is not used: compared without
    with pytest.raises(ValueError, match="not a PNG"):
        golden.embed(b"JFIF", tol, learned)


def test_461_a_difference_good_boards_also_showed_is_passed_over_and_any_other_counts_in_full() -> None:
    ref = board()
    photo = ref.copy()
    cv2.rectangle(photo, (100, 100), (130, 120), (60, 60, 60), -1)  # a date code that changes from board to board
    cv2.rectangle(photo, (400, 300), (430, 330), (40, 40, 220), -1)  # and a real defect
    info = {"method": "resize", "inliers": 0}
    plain = compare(photo, ref, aligned=photo, align_info=info)
    assert plain.metrics["compare_regions"] == 2 and plain.metrics["tolerance"] is False
    raw = lab_difference(photo, ref)
    tol = np.full((H, W), 12, np.uint8)  # the camera's noise, everywhere
    tol[90:130, 90:140] = int(raw[100:120, 100:130].max())  # and what good boards showed at the date code
    judged = compare(photo, ref, aligned=photo, align_info=info, tolerance=tol)
    assert judged.metrics["compare_regions"] == 1 and judged.metrics["tolerance"] is True
    (region,) = judged.regions
    (same,) = [r for r in plain.regions if abs(r.x - region.x) < 5]
    assert 395 <= region.x <= 405 and 295 <= region.y <= 305
    assert (region.area, region.peak) == (same.area, same.peak), "the defect lost sensitivity to the tolerance"
    assert judged.metrics["max_diff"] == plain.metrics["max_diff"]  # the map keeps the comparison's own scale
    assert judged.metrics["changed_pct"] < plain.metrics["changed_pct"]
    faint = ref.copy()
    cv2.rectangle(faint, (400, 300), (430, 330), tuple(int(v) for v in ref[315, 415] + 40), -1)  # a faint stain
    before = compare(faint, ref, 25, 40, faint, info)
    after = compare(faint, ref, 25, 40, faint, info, tol)
    assert before.metrics["compare_regions"] == after.metrics["compare_regions"] == 1  # above the noise: still found


def test_460_nothing_is_counted_at_the_edge_of_what_the_photo_showed() -> None:
    ref = board()
    shift = np.array([[1, 0, 40], [0, 1, 0], [0, 0, 1]], np.float64)
    photo = cv2.warpPerspective(ref, np.linalg.inv(shift), (W, H))
    warped = cv2.warpPerspective(photo, shift, (W, H))
    aligned, seen = conform(warped, ref, shift, photo.shape)
    aligned[:, 40:46] = 255  # the worst a seam could leave: a bright line where the photo's own pixels begin
    info = {"method": "orb-homography", "inliers": 99} | seen
    assert compare(photo, ref, aligned=aligned, align_info=info).metrics["compare_regions"] == 0
    info["frame"] = None  # the same pixels on a photo that showed the whole frame are a difference like any other
    assert compare(photo, ref, aligned=aligned, align_info=info).metrics["compare_regions"] == 1


def test_460_a_value_the_camera_clipped_is_not_read_as_a_difference() -> None:
    ref = board()
    cv2.rectangle(ref, (300, 200), (360, 240), (245, 245, 245), -1)  # a white connector body
    photo = lit(ref, 1.15)  # 15 % brighter: the connector reads 255, and so would anything brighter still
    assert (photo[210:230, 310:350] == 255).all()
    out, info = match_light(photo, ref)
    assert info["light_matched"] and (out[210:230, 310:350] == ref[210:230, 310:350]).all()
    info = {"method": "resize", "inliers": 0} | info
    assert compare(photo, ref, aligned=out, align_info=info).metrics["compare_regions"] == 0
    dark = ref.copy()
    cv2.rectangle(dark, (100, 300), (140, 330), (5, 5, 5), -1)  # the Golden board is dark here
    glare = lit(dark, 1.15)
    cv2.rectangle(glare, (100, 300), (140, 330), (255, 255, 255), -1)  # and the photo burnt out: a real difference
    out, _ = match_light(glare, dark)
    assert out[315, 120].min() > 200  # kept: brighter than the Golden board, on the side the clipping did not hide


# --- AI regions are judged against what good boards showed (#460) -----------------------------------------------------
def test_460_region_level_is_the_level_at_which_a_map_first_holds_a_region() -> None:
    amap = np.zeros((120, 160), np.float32)
    amap[10:20, 10:20] = 9.0  # 100 px at 9
    amap[60:63, 60:63] = 30.0  # 9 px at 30: too small to be a region
    level = region_level(amap, 40)
    assert level == pytest.approx(9.0, abs=0.01) and level <= 9.0
    assert regions_from_mask(ai_mask(amap, level), amap, 40, "ai") and not regions_from_mask(
        ai_mask(amap, level + 0.01), amap, 40, "ai"
    )
    assert region_level(np.zeros((50, 50), np.float32), 40) == 0.0
    assert region_level(amap, 100 * 100) == 0.0  # no region that large at any level above 0


def test_460_the_pixel_threshold_lies_above_the_region_level_of_the_good_boards_held_out(tiny_model: Any) -> None:
    meta = tiny_model.model.meta
    levels = meta["ok_region_levels"]
    assert len(levels) == len(meta["ok_scores"]) - meta["n_ng"] or len(levels) == meta["n_ok_val"] or levels
    assert meta["pixel_threshold"] >= max(levels) * 1.05 - 1e-6  # no held-out good board shows an AI region
    assert meta["pixel_threshold"] >= meta["image_threshold"] * 0.6 - 1e-6  # and never under what it was


# --- the two checks a result states ----------------------------------------------------------------------------------
def inspector_of(tiny_model: Any, **more: Any) -> Inspector:
    return Inspector(Recipe(board_model=tiny_model.board_model), tiny_model.model, tiny_model.reference, **more)


def checks(result: Any) -> dict[str, Any]:
    return {c.name: c for c in result.checks}


def test_460_a_result_keeps_the_lighting_and_the_frame_and_states_them_only_when_someone_must_act(
    tiny_model: Any,
) -> None:
    insp = inspector_of(tiny_model)
    brighter = insp.inspect(lit(tiny_model.reference, 1.2))
    assert brighter.compare is not None
    m = brighter.compare.metrics
    assert m["light_gain"] == pytest.approx(1.2, abs=0.03) and m["light_change"] == pytest.approx(0.2, abs=0.03)
    assert m["coverage_pct"] == 100.0 and m["tolerance"] is False
    assert "Lighting change %" not in checks(brighter) and "Board in frame %" not in checks(brighter)
    assert checks(brighter)["Difference regions"].value == 0 and checks(brighter)["SSIM similarity"].verdict == "OK"


def test_460_lighting_too_far_from_the_golden_boards_makes_the_board_warn(tiny_model: Any) -> None:
    result = inspector_of(tiny_model).inspect(lit(tiny_model.reference, 0.55))
    light = checks(result)["Lighting change %"]
    assert light.verdict == "WARN" and light.value < -35.0 and light.threshold == 35.0 and result.verdict != "OK"


def test_460_a_board_partly_out_of_frame_makes_the_board_warn_not_ng(tiny_model: Any) -> None:
    ref = tiny_model.reference
    h, w = ref.shape[:2]
    shifted = cv2.warpAffine(ref, np.array([[1, 0, 0.08 * w], [0, 1, 0]], np.float32), (w, h))
    result = inspector_of(tiny_model).inspect(shifted)
    frame = checks(result)["Board in frame %"]
    assert frame.verdict == "WARN" and frame.value == pytest.approx(92.0, abs=1.0) and frame.threshold == COVERAGE_WARN
    assert result.verdict == "WARN", "what was not photographed was not inspected: a person looks, no defect is claimed"
    assert checks(result)["Difference regions"].value == 0


def test_460_a_stored_result_from_before_is_not_judged_on_what_it_never_measured(tiny_model: Any) -> None:
    insp = inspector_of(tiny_model)
    result = insp.inspect(tiny_model.reference)
    assert result.compare is not None
    for key in ("light_gain", "light_tilt", "light_change", "coverage_pct", "tolerance"):
        result.compare.metrics.pop(key)
    insp.judge(result, None)
    names = [c.name for c in result.checks]
    assert "SSIM similarity" in names and "Lighting change %" not in names and "Board in frame %" not in names


# --- training measures it, and Inspection uses it ---------------------------------------------------------------------
@pytest.fixture(scope="module")
def varied(tmp_path_factory: pytest.TempPathFactory) -> Iterator[AppContext]:
    """VARIED-A1 trained on 24 good boards that differ as photographed boards do, and one of each defect type."""
    root = tmp_path_factory.mktemp("varied")
    paths = write_boards(root / "boards", ok=24, ng=1, seed=11)
    ctx = engineer(
        AppContext(Settings(workspace=str(root / "workspace"), device="cpu"), credentials.MemoryCredentials())
    )
    ctx.import_samples(BM, [str(p) for p in paths if p.parent.name == "ok"], "OK")
    for p in paths:
        if p.parent.name != "ok":
            ctx.import_samples(BM, [str(p)], "NG", p.parent.name)
    meta = ctx.train(trainable(ctx, BM), epochs=1, image_size=32)
    assert meta["activated"]
    yield ctx
    ctx.close()


def registered(ctx: AppContext) -> dict[str, Any]:
    """What the registry holds of the active AI model version."""
    active = ctx.active_model(BM)
    assert active is not None
    found: dict[str, Any] = json.loads(active["metrics"])
    return found


def test_461_training_measures_how_good_boards_differ_and_the_file_carries_it(varied: AppContext) -> None:
    file = varied.db.reference(BM)
    assert file is not None
    image, data = load_image_bytes(file, read=varied._plain_bytes)
    found = golden.extract(data, image.shape[:2])
    assert found is not None
    tol, learned = found
    assert learned["images"] == 24 and learned["sigmas"] == golden.TOLERANCE_SIGMAS and 0.3 < learned["ssim_low"] < 1
    assert 0 < np.count_nonzero(tol > 20) < 0.25 * tol.size  # where boards differ, and not everywhere
    insp = varied.inspector(BM)
    assert insp.tolerance is not None and (insp.tolerance == tol).all()
    # the version's record names what its Golden board learned
    assert registered(varied)["golden_learned"] == {k: v for k, v in learned.items() if k not in ("format", "shape")}


def found_by_comparison(insp: Inspector, photo: np.ndarray, tolerance: np.ndarray | None) -> int:
    aligned, info = align_to_reference(photo, insp.reference)
    r = insp.recipe
    return len(compare(photo, insp.reference, r.diff_threshold, r.min_defect_area, aligned, info, tolerance).regions)


def test_460_good_boards_it_has_not_seen_show_the_comparison_no_difference_region(varied: AppContext) -> None:
    """Twelve good boards that differ as photographed boards do, each turned, shifted and lit its own way: before #460
    the warp's border, the lighting, a homography's play at the corners and clipped highlights each made regions."""
    insp = varied.inspector(BM)
    rng = random.Random(99)
    flagged = sum(found_by_comparison(insp, varied_board(rng), insp.tolerance) > 0 for _ in range(12))
    assert flagged == 0


@pytest.mark.parametrize("defect", ["Missing Component", "Misalignment", "Polarity Error", "Contamination", "Scratch"])
def test_461_the_tolerance_costs_the_comparison_no_defect(varied: AppContext, defect: str) -> None:
    insp = varied.inspector(BM)
    rng = random.Random(7)
    boards = [varied_board(rng, defect) for _ in range(3)]
    without = [found_by_comparison(insp, b, None) > 0 for b in boards]
    assert [found_by_comparison(insp, b, insp.tolerance) > 0 for b in boards] == without
    assert sum(without) >= 2, "the drawn defect is too faint to test with"


def test_460_a_first_models_untouched_recipe_takes_its_similarity_from_the_good_boards(varied: AppContext) -> None:
    """Photographed good boards score a similarity well under the default threshold (0.47 at the median on the VisA
    boards of the 2026-11-05 record): with the default, every one is NG until someone finds the Recipe Editor."""
    default = Recipe(board_model=BM)
    assert varied.recipe(BM)[1].to_dict() == default.to_dict()  # these drawn boards score above it: nothing learned
    assert registered(varied)["golden_learned"]["ssim_low"] - SSIM_MARGIN >= default.ssim_min
    varied._learn_similarity(BM, "v1.0", {"images": 24, "ssim_low": 0.7134})
    recipe = varied.recipe(BM)[1]
    assert recipe.ssim_min == pytest.approx(round(0.7134 - SSIM_MARGIN, 2))
    assert {k: v for k, v in recipe.to_dict().items() if k != "ssim_min"} == {
        k: v for k, v in default.to_dict().items() if k != "ssim_min"
    }
    (saved,) = varied.audit_entries(action="recipe.save")
    assert "Similarity threshold set from the 24 OK images AI model v1.0 was trained on" in saved["reason"]
    assert "0.71" in saved["reason"] and "0.80" in saved["reason"]


def test_460_a_recipe_someone_saved_is_never_touched(varied: AppContext) -> None:
    before = varied.recipe(BM)[1]
    before.ssim_min = 0.9
    varied.save_recipe(before, "Tightened by hand.")
    varied._learn_similarity(BM, "v9.9", {"images": 24, "ssim_low": 0.5})
    assert varied.recipe(BM)[1].ssim_min == 0.9


def test_461_a_golden_board_without_a_tolerance_is_compared_as_before(varied: AppContext, tmp_path: Path) -> None:
    file = varied.db.reference(BM)
    assert file is not None
    image, _ = load_image_bytes(file, read=varied._plain_bytes)
    assert golden.extract(cv2.imencode(".png", image)[1].tobytes(), image.shape[:2]) is None
    bare = Inspector(Recipe(board_model=BM), varied.inspector(BM).model, image)
    assert bare.tolerance is None and bare.inspect(image).compare.metrics["tolerance"] is False  # type: ignore[union-attr]
