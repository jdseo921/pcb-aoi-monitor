"""REQ-RCP-006 (S29): a recipe whose minimum defect size is in mm, applied at the board model's scale, judges the
synthetic regression set at 1x and at 2x. It is never accuracy: the boards are drawings (README.md)."""

from __future__ import annotations

import cv2
import numpy as np
import pytest

from aoi.core.inspector import Inspector, re_grade
from aoi.core.recipe import Recipe, disc_width
from tests.regression import make_regression_set as rs
from tests.regression.test_regression_verdicts import BOARDS, regression_set  # noqa: F401  # the fixture

SCALE = 640 / 150  # px per mm of the set's 640 x 480 boards, taken as 150 mm wide, as the resolution test does
MIN_SIZE_MM = disc_width(rs.RECIPE.min_defect_area) / SCALE  # the default 40 px of area as a size: 1.67 mm
# NG boards the default recipe misses at 1x by a few px (regions of 31 and 37 px against 40) and finds at 2x, where the
# noise clean-up and the shift tolerance, both in px, take less of a region: open with Jay (S29 change note)
FOUND_ONLY_AT_2X = {"ng_02_misalignment.png", "ng_04_contamination.png"}
# What the same boards do at 2x with the minimum defect area left at 40 px: five more change
CHANGED_IN_PX = FOUND_ONLY_AT_2X | {
    "ng_01_solder_bridge.png", "ng_06_solder_ball.png", "ng_08_solder_bridge.png", "ng_13_solder_ball.png",
    "ng_15_solder_bridge.png",
}  # fmt: skip


def _twice(img: np.ndarray) -> np.ndarray:
    """`img` at twice its width and height, with cubic interpolation, as the resolution test scales its boards."""
    out: np.ndarray = cv2.resize(img, None, fx=2, fy=2, interpolation=cv2.INTER_CUBIC)
    return out


def test_req_rcp_006_verdicts_with_the_size_in_mm_at_1x_and_2x(request: pytest.FixtureRequest) -> None:
    """The default recipe with its minimum defect size in mm (1.67 mm: its 40 px of area at the set's 4.27 px/mm) judges
    every board of the regression set at 1x as expected.json holds, so no verdict changes at the set's own scale; at 2x
    (boards and golden board twice the size, the scale calibrated again to 8.53 px/mm, as it does not follow the image
    size; that size is then 160 px of area) 38 of the 40 boards keep their verdict. The two others are NG boards the
    recipe misses at 1x by a few px and finds at 2x (FOUND_ONLY_AT_2X); with the size left in px (40 px of area at 2x
    too) seven boards change. The acceptance "the same verdicts when the image size changes" is met in part: the compare
    step's blur, shift tolerance and noise clean-up stay in px, which is open with Jay (S29 change note)."""
    out, boards, golden = request.getfixturevalue("regression_set")  # as make_regression_set.py draws them
    images = {b.name: cv2.imread(str(out / b.name)) for b in boards}
    recipe = Recipe(board_model=rs.BOARD_MODEL, use_ai=False, min_defect_mm=MIN_SIZE_MM)
    assert recipe.in_px(SCALE).to_dict() == {**rs.RECIPE.to_dict(), "min_defect_mm": MIN_SIZE_MM}
    assert recipe.in_px(2 * SCALE).min_defect_area == 4 * rs.RECIPE.min_defect_area
    at_1x = Inspector(recipe, reference=golden, px_per_mm=SCALE)
    at_2x = Inspector(recipe, reference=_twice(golden), px_per_mm=2 * SCALE)
    one, two, two_in_px = {}, {}, {}
    for name, img in images.items():
        one[name] = at_1x.inspect(img).verdict
        res = at_2x.inspect(_twice(img))
        two[name], two_in_px[name] = res.verdict, re_grade(res, rs.RECIPE, None).verdict
    assert one == {name: b["verdict"] for name, b in BOARDS.items()}
    changed = {name: (one[name], two[name]) for name in one if two[name] != one[name]}
    assert changed == dict.fromkeys(FOUND_ONLY_AT_2X, ("OK", "NG")), changed
    assert {name for name in one if two_in_px[name] != one[name]} == CHANGED_IN_PX
