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
    aligned: np.ndarray  # test image registered onto the reference
    diff_map: np.ndarray  # float32 0-255 colour difference
    ssim_map: np.ndarray  # float32 -1..1 (1 = identical)
    mask: np.ndarray  # uint8 0/255 changed pixels after clean-up
    regions: list[Region] = field(default_factory=list)
    metrics: dict[str, Any] = field(default_factory=dict)


def regions_from_mask(mask: np.ndarray, value_map: np.ndarray, min_area: int, source: str) -> list[Region]:
    n, _, stats, _ = cv2.connectedComponentsWithStats(mask, connectivity=8)
    out = []
    for i in range(1, n):
        x, y, w, h, area = (int(v) for v in stats[i])
        if area < min_area:
            continue
        peak = float(value_map[y : y + h, x : x + w].max())
        out.append(Region(x, y, w, h, area, peak, source))
    return sorted(out, key=lambda r: -r.peak)


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
    m = max(4, min(diff.shape) // 60)  # ignore warped borders
    diff[:m, :] = diff[-m:, :] = 0
    diff[:, :m] = diff[:, -m:] = 0

    g1 = cv2.cvtColor(aligned, cv2.COLOR_BGR2GRAY)
    g2 = cv2.cvtColor(reference, cv2.COLOR_BGR2GRAY)
    score, ssim_map = ssim(g1, g2)

    mask: np.ndarray = (diff >= diff_threshold).astype(np.uint8) * 255
    k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3))
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, k)
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, k, iterations=2)
    regions = regions_from_mask(mask, diff, min_area, "compare")

    metrics = {
        "alignment_method": align_info["method"],
        "alignment_inliers": align_info["inliers"],
        "ssim": score,
        "mean_abs_diff": float(diff.mean()),
        "max_diff": float(diff.max()),
        "changed_pct": float((mask > 0).mean() * 100.0),
        "compare_regions": len(regions),
        "largest_region_px": max((r.area for r in regions), default=0),
    }
    return CompareResult(aligned, diff, ssim_map, mask, regions, metrics)
