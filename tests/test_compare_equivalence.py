"""The rewritten compare step gives the same results as v0.1's (stage S08, issue #12, REQ-INSP-007 part).

tests/compare_v01_oracle.py is v0.1's step, kept only here. On every board of the synthetic regression set and on
5 MP synthetic boards, old and new must give identical difference maps, masks and regions, equal metrics, an
SSIM score within 1e-6 and an SSIM map within 5e-4 (float32 box filters against float64).
"""

from __future__ import annotations

import random
from pathlib import Path

import cv2
import numpy as np
import pytest

from aoi.core import compare as new
from aoi.core.imaging import align_to_reference
from tests import compare_v01_oracle as old
from tests.regression import make_regression_set as rs
from tools.make_synthetic_dataset import draw_board

SSIM_SCORE_TOL = 1e-6
SSIM_MAP_TOL = 5e-4
FIVE_MP = (2592, 1944)


def assert_equivalent(test: np.ndarray, golden: np.ndarray, label: str) -> float:
    aligned, info = align_to_reference(test, golden)
    before = old.compare(test, golden, aligned=aligned, align_info=info)
    after = new.compare(test, golden, aligned=aligned, align_info=info)
    assert np.array_equal(before.diff_map, after.diff_map), f"{label}: difference map"
    assert after.diff_map.dtype == np.float32 and after.ssim_map.dtype == np.float32
    assert np.array_equal(before.mask, after.mask), f"{label}: mask"
    key = [(r.x, r.y, r.w, r.h, r.area, r.peak, r.source) for r in before.regions]
    assert key == [(r.x, r.y, r.w, r.h, r.area, r.peak, r.source) for r in after.regions], f"{label}: regions"
    for metric, value in before.metrics.items():
        if metric != "ssim":
            assert after.metrics[metric] == value, f"{label}: {metric}"
    ssim_gap = abs(before.metrics["ssim"] - after.metrics["ssim"])
    assert ssim_gap <= SSIM_SCORE_TOL, f"{label}: SSIM {before.metrics['ssim']} vs {after.metrics['ssim']}"
    assert float(np.abs(before.ssim_map - after.ssim_map).max()) <= SSIM_MAP_TOL, f"{label}: SSIM map"
    return ssim_gap


@pytest.fixture(scope="module")
def regression_boards(tmp_path_factory: pytest.TempPathFactory) -> tuple[Path, list[rs.Board], np.ndarray]:
    out = tmp_path_factory.mktemp("regression")
    return out, rs.generate(out), cv2.imread(str(out / "golden.png"))


def test_req_insp_007_rewritten_compare_matches_v01_on_every_regression_board(regression_boards) -> None:
    out, boards, golden = regression_boards
    gaps = [assert_equivalent(cv2.imread(str(out / b.name)), golden, b.name) for b in boards]
    assert len(gaps) == rs.N_OK + rs.N_NG
    print(f"largest SSIM gap over {len(gaps)} boards: {max(gaps):.2e}")


@pytest.mark.parametrize("defect", [None, "Missing Component"])
def test_req_insp_007_rewritten_compare_matches_v01_at_5mp(defect: str | None) -> None:
    """A clean and a defective board scaled to 5 MP with cubic interpolation and the generator's capture jitter."""
    rng = random.Random(8)
    w, h = FIVE_MP
    golden = cv2.resize(draw_board(rng), (w, h), interpolation=cv2.INTER_CUBIC)
    drawn = cv2.resize(draw_board(rng, defect), (w, h), interpolation=cv2.INTER_CUBIC)
    assert_equivalent(capture_scaled(drawn, rng), golden, f"5MP {defect or 'OK'}")


def capture_scaled(img: np.ndarray, rng: random.Random) -> np.ndarray:
    """tools.make_synthetic_dataset.capture works at 640 x 480; apply the same jitter at the image's own size."""
    h, w = img.shape[:2]
    scale = w / 640
    m = cv2.getRotationMatrix2D((w / 2, h / 2), rng.uniform(-1.0, 1.0), 1.0)
    m[:, 2] += (rng.uniform(-6, 6) * scale, rng.uniform(-6, 6) * scale)
    out = cv2.warpAffine(img, m, (w, h), borderMode=cv2.BORDER_REPLICATE).astype(np.float32)
    out = out * rng.uniform(0.95, 1.05) + rng.uniform(-6, 6)
    out += np.random.default_rng(rng.randrange(1 << 30)).normal(0, 3, out.shape)
    return np.clip(out, 0, 255).astype(np.uint8)


def test_shift_tolerant_diff_rejects_a_negative_tolerance() -> None:
    img = np.zeros((8, 8, 3), np.uint8)
    with pytest.raises(ValueError, match="tol"):
        new.shift_tolerant_diff(img, img, tol=-1)
    assert np.array_equal(new.shift_tolerant_diff(img, img, tol=0), np.zeros((8, 8), np.uint8))
