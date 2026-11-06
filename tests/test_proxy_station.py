"""The commissioning arithmetic of the scenario station (#459): the whole-board limits and the typical board, on
boards drawn here: no dataset runs in CI."""

from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np

from tests.test_proxy_frames import board
from tools.proxy_station import limits, typical


def test_459_limits_leave_the_worst_good_board_outside_the_warn_band() -> None:
    seen = {"SSIM similarity": [0.40, 0.55], "Changed area %": [2.5, 8.2], "Difference regions": [196.0, 491.0]}
    got = limits(seen, warn_ratio=0.8)
    ssim, area = got["ssim_min"], got["changed_pct_max"]
    assert 0.40 >= ssim + 0.2 * (1 - ssim)  # SSIM: WARN below thr + 0.2 (1 - thr)
    assert 8.2 < 0.8 * area  # higher is worse: WARN from 0.8 of the limit
    assert got["max_diff_regions"] == 491
    assert limits({}, 0.8) == {}


def test_459_typical_picks_the_board_that_looks_most_like_the_rest(tmp_path: Path) -> None:
    paths = []
    for i in range(5):
        img = board(seed=0)
        if i == 2:
            img = 255 - img  # the odd one out
        img = np.clip(img.astype(int) + i, 0, 255).astype(np.uint8)
        paths.append(tmp_path / f"{i}.png")
        cv2.imwrite(str(paths[-1]), img)
    assert typical(paths) in (1, 3)  # the middle of the others, never the odd one out
