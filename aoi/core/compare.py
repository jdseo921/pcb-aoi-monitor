"""Golden-sample comparison: test board vs. reference (good) board of the same model."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import cv2
import numpy as np

from .imaging import align_to_reference

# SSIM as scikit-image's structural_similarity computes it with its defaults: 7 px uniform window, sample
# covariance, K1 = 0.01, K2 = 0.03, data range 255, "reflect" border, mean over the map without the border.
SSIM_WINDOW, SSIM_K1, SSIM_K2, SSIM_RANGE = 7, 0.01, 0.03, 255.0
DIFF_BORDER = 4  # px at each edge of the difference map that are never judged: warping leaves no board there
# The shortest side the engine inspects (#169): SSIM needs one whole window (under 7 px its score is the mean of
# nothing, NaN), and the difference map 3 px inside its border for the 3 × 3 noise clean-up to keep a pixel (at 10 px
# or less no pixel is ever judged changed); ORB's image pyramid fails on a 1 px side.
MIN_SIDE = max(SSIM_WINDOW, 2 * DIFF_BORDER + 3)  # 11 px


@dataclass
class Region:
    x: int
    y: int
    w: int
    h: int
    area: int
    peak: float  # strongest evidence inside the region (map units)
    source: str  # "compare" | "ai"


@dataclass
class CompareResult:
    """What `compare()` found. The four maps are None on a result read back from the database (REQ-INSP-008), which
    keeps the regions and metrics only; `InspectionResult.from_dict` builds that one."""

    aligned: np.ndarray | None = None  # test image registered onto the reference
    diff_map: np.ndarray | None = None  # float32 0-255 colour difference
    ssim_map: np.ndarray | None = None  # float32 -1..1 (1 = identical)
    mask: np.ndarray | None = None  # uint8 0/255 changed pixels after clean-up
    regions: list[Region] = field(default_factory=list)
    metrics: dict[str, Any] = field(default_factory=dict)


SMALL = 8  # px: the boxes this wide and high or less have their peaks read together, CHUNK boxes at a time
CHUNK = 8192  # so that reading them never takes more than a few MB, however many regions a board has


def regions_from_mask(mask: np.ndarray, value_map: np.ndarray, min_area: int, source: str) -> list[Region]:
    """The regions of `mask` (8-connected) of `min_area` px or more, each with its box and the highest value of
    `value_map` in that box, highest first (ties in the order found). The peaks of boxes up to SMALL px a side are read
    together from SMALL x SMALL windows, the cells outside each box left out, and the others one box at a time: the
    same values as reading every box alone, which took about 20 ms for the 5,600 regions that Pixel difference 10 and
    Minimum defect area 1 leave on a 5 MP board (#249)."""
    _, _, stats, _ = cv2.connectedComponentsWithStats(mask, connectivity=8)
    kept = stats[1:][stats[1:, cv2.CC_STAT_AREA] >= min_area]
    x, y, w, h = kept[:, 0], kept[:, 1], kept[:, 2], kept[:, 3]
    peaks, k = np.empty(len(kept)), np.arange(SMALL)
    small = np.flatnonzero((w <= SMALL) & (h <= SMALL))
    for part in (small[i : i + CHUNK] for i in range(0, len(small), CHUNK)):
        rows = np.minimum(y[part, None, None] + k[None, :, None], value_map.shape[0] - 1)
        cols = np.minimum(x[part, None, None] + k[None, None, :], value_map.shape[1] - 1)
        inside = (k[None, :, None] < h[part, None, None]) & (k[None, None, :] < w[part, None, None])
        peaks[part] = np.where(inside, value_map[rows, cols], -np.inf).max(axis=(1, 2))
    for i in np.flatnonzero((w > SMALL) | (h > SMALL)).tolist():
        peaks[i] = value_map[y[i] : y[i] + h[i], x[i] : x[i] + w[i]].max()
    boxes = zip(kept.tolist(), peaks.tolist(), strict=True)
    out = [Region(bx, by, bw, bh, area, peak, source) for (bx, by, bw, bh, area), peak in boxes]
    return sorted(out, key=lambda r: -r.peak)


def changed_mask(diff: np.ndarray, diff_threshold: int) -> np.ndarray:
    """The pixels of a difference map that differ by `diff_threshold` or more, cleaned of noise (0 or 255):
    `changed_regions` finds its regions in it, and the comparison's training (aoi/core/tuning.py) counts on it."""
    mask: np.ndarray = (diff >= diff_threshold).astype(np.uint8) * 255
    k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3))
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, k)
    out: np.ndarray = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, k, iterations=2)
    return out


def changed_regions(
    diff: np.ndarray, diff_threshold: int, min_area: int
) -> tuple[np.ndarray, list[Region], dict[str, Any]]:
    """The pixels of a difference map that differ by `diff_threshold` or more, cleaned of noise, the difference regions
    of `min_area` px or more among them, and their metrics: the changed area % and the region count, which the recipe
    judges, and the largest region's area, shown with them. `compare` and the re-evaluation of a stored result
    (REQ-CMP-005) both find them here."""
    mask = changed_mask(diff, diff_threshold)
    regions = regions_from_mask(mask, diff, min_area, "compare")
    metrics = {
        "changed_pct": cv2.countNonZero(mask) / mask.size * 100.0,  # as (mask > 0).mean() * 100, in a tenth of the time
        "compare_regions": len(regions),
        "largest_region_px": max((r.area for r in regions), default=0),
    }
    return mask, regions, metrics


def shift_tolerant_diff(a: np.ndarray, b: np.ndarray, tol: int = 2) -> np.ndarray:
    """Per-pixel colour difference, taking the best match within ±tol px.

    Registration is never perfect to the pixel; without this every component
    edge lights up. Max over Lab channels keeps colour-only defects visible.

    Channel-split OpenCV operations on the 8-bit Lab images (S08, #12): the same values as the float32
    NumPy version it replaces, about 100 times faster at 5 MP. Returns the input dtype (uint8 for Lab images).
    """
    if tol < 0:
        raise ValueError(f"tol must be >= 0, got {tol}")
    h, w = a.shape[:2]
    ap = cv2.split(a)
    bp = cv2.split(cv2.copyMakeBorder(b, tol, tol, tol, tol, cv2.BORDER_REPLICATE))
    best: np.ndarray | None = None
    for dy in range(2 * tol + 1):
        for dx in range(2 * tol + 1):
            d = cv2.absdiff(ap[0], bp[0][dy : dy + h, dx : dx + w])
            for c in range(1, len(ap)):
                d = cv2.max(d, cv2.absdiff(ap[c], bp[c][dy : dy + h, dx : dx + w]))
            best = d if best is None else cv2.min(best, d)
    assert best is not None  # tol >= 0 always runs the (0, 0) offset
    return best


def ssim(g1: np.ndarray, g2: np.ndarray) -> tuple[float, np.ndarray]:
    """Structural similarity of two 8-bit grey images: the score and the per-pixel map.

    OpenCV box filters in float32 instead of scikit-image in float64 (S08, #12): the score agrees with
    scikit-image within 1e-6 and the map within 5e-4, which tests/test_compare_equivalence.py checks; the
    whole-board score is what the recipe thresholds.
    """
    x, y = g1.astype(np.float32), g2.astype(np.float32)
    win = SSIM_WINDOW

    def mean(img: np.ndarray) -> np.ndarray:
        out: np.ndarray = cv2.boxFilter(img, cv2.CV_32F, (win, win), normalize=True, borderType=cv2.BORDER_REFLECT)
        return out

    ux, uy = mean(x), mean(y)
    unbias = win * win / (win * win - 1.0)  # sample covariance, as scikit-image uses
    vx = unbias * (mean(x * x) - ux * ux)
    vy = unbias * (mean(y * y) - uy * uy)
    vxy = unbias * (mean(x * y) - ux * uy)
    c1, c2 = (SSIM_K1 * SSIM_RANGE) ** 2, (SSIM_K2 * SSIM_RANGE) ** 2
    s = ((2 * ux * uy + c1) * (2 * vxy + c2)) / ((ux * ux + uy * uy + c1) * (vx + vy + c2))
    pad = (win - 1) // 2
    return float(s[pad:-pad, pad:-pad].astype(np.float64).mean()), s


def compare(
    test: np.ndarray,
    reference: np.ndarray,
    diff_threshold: int = 45,
    min_area: int = 40,
    aligned: np.ndarray | None = None,
    align_info: dict[str, Any] | None = None,
) -> CompareResult:
    if aligned is None:
        aligned, align_info = align_to_reference(test, reference)
    elif align_info is None:
        raise ValueError("align_info is required when a pre-aligned image is passed")

    a = cv2.cvtColor(cv2.GaussianBlur(aligned, (5, 5), 0), cv2.COLOR_BGR2LAB)
    b = cv2.cvtColor(cv2.GaussianBlur(reference, (5, 5), 0), cv2.COLOR_BGR2LAB)
    diff = shift_tolerant_diff(a, b).astype(np.float32)
    m = max(DIFF_BORDER, min(diff.shape) // 60)  # ignore warped borders
    diff[:m, :] = diff[-m:, :] = 0
    diff[:, :m] = diff[:, -m:] = 0

    g1 = cv2.cvtColor(aligned, cv2.COLOR_BGR2GRAY)
    g2 = cv2.cvtColor(reference, cv2.COLOR_BGR2GRAY)
    score, ssim_map = ssim(g1, g2)

    mask, regions, found = changed_regions(diff, diff_threshold, min_area)
    metrics = {
        "alignment_method": align_info["method"],
        "alignment_inliers": align_info["inliers"],
        "ssim": score,
        "mean_abs_diff": float(diff.mean()),
        "max_diff": float(diff.max()),
        **found,
    }
    return CompareResult(aligned, diff, ssim_map, mask, regions, metrics)
