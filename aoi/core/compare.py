"""Golden-sample comparison: test board vs. reference (good) board of the same model."""
from __future__ import annotations

from dataclasses import dataclass, field

import cv2
import numpy as np
from skimage.metrics import structural_similarity

from .imaging import align_to_reference


@dataclass
class Region:
    x: int
    y: int
    w: int
    h: int
    area: int
    peak: float          # strongest evidence inside the region (map units)
    source: str          # "compare" | "ai"


@dataclass
class CompareResult:
    aligned: np.ndarray                 # test image registered onto the reference
    diff_map: np.ndarray                # float32 0-255 colour difference
    ssim_map: np.ndarray                # float32 -1..1 (1 = identical)
    mask: np.ndarray                    # uint8 0/255 changed pixels after clean-up
    regions: list[Region] = field(default_factory=list)
    metrics: dict = field(default_factory=dict)


def regions_from_mask(mask: np.ndarray, value_map: np.ndarray, min_area: int, source: str) -> list[Region]:
    n, _, stats, _ = cv2.connectedComponentsWithStats(mask, connectivity=8)
    out = []
    for i in range(1, n):
        x, y, w, h, area = (int(v) for v in stats[i])
        if area < min_area:
            continue
        peak = float(value_map[y:y + h, x:x + w].max())
        out.append(Region(x, y, w, h, area, peak, source))
    return sorted(out, key=lambda r: -r.peak)


def shift_tolerant_diff(a: np.ndarray, b: np.ndarray, tol: int = 2) -> np.ndarray:
    """Per-pixel colour difference, taking the best match within ±tol px.

    Registration is never perfect to the pixel; without this every component
    edge lights up. Max over Lab channels keeps colour-only defects visible.
    """
    best = None
    bp = cv2.copyMakeBorder(b, tol, tol, tol, tol, cv2.BORDER_REPLICATE)
    h, w = a.shape[:2]
    for dy in range(2 * tol + 1):
        for dx in range(2 * tol + 1):
            d = np.abs(a - bp[dy:dy + h, dx:dx + w]).max(axis=2)
            best = d if best is None else np.minimum(best, d)
    return best


def compare(test: np.ndarray, reference: np.ndarray, diff_threshold: int = 45,
            min_area: int = 40, aligned: np.ndarray | None = None, align_info: dict | None = None) -> CompareResult:
    if aligned is None:
        aligned, align_info = align_to_reference(test, reference)

    a = cv2.cvtColor(cv2.GaussianBlur(aligned, (5, 5), 0), cv2.COLOR_BGR2LAB).astype(np.float32)
    b = cv2.cvtColor(cv2.GaussianBlur(reference, (5, 5), 0), cv2.COLOR_BGR2LAB).astype(np.float32)
    diff = shift_tolerant_diff(a, b)
    m = max(4, min(diff.shape) // 60)        # ignore warped borders
    diff[:m, :] = diff[-m:, :] = 0
    diff[:, :m] = diff[:, -m:] = 0

    g1 = cv2.cvtColor(aligned, cv2.COLOR_BGR2GRAY)
    g2 = cv2.cvtColor(reference, cv2.COLOR_BGR2GRAY)
    ssim, ssim_map = structural_similarity(g1, g2, full=True, data_range=255)

    mask = (diff >= diff_threshold).astype(np.uint8) * 255
    k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3))
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, k)
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, k, iterations=2)
    regions = regions_from_mask(mask, diff, min_area, "compare")

    metrics = {
        "alignment_method": align_info["method"],
        "alignment_inliers": align_info["inliers"],
        "ssim": float(ssim),
        "mean_abs_diff": float(diff.mean()),
        "max_diff": float(diff.max()),
        "changed_pct": float((mask > 0).mean() * 100.0),
        "compare_regions": len(regions),
        "largest_region_px": max((r.area for r in regions), default=0),
    }
    return CompareResult(aligned, diff.astype(np.float32), ssim_map.astype(np.float32), mask, regions, metrics)
