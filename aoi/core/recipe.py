"""Inspection recipe: ROIs and thresholds per board model (spec 4.2)."""

from __future__ import annotations

import copy
import math
from dataclasses import asdict, dataclass, field
from typing import Any

ROI_TYPES = ["Presence", "Polarity", "Solder Bridge", "Height", "Anomaly"]

# Defect name reported when a region fails inside an ROI of this type.
ROI_DEFECT = {
    "Presence": "Missing Component",
    "Polarity": "Polarity Error",
    "Solder Bridge": "Solder Bridge",
    "Height": "Pin Height Error",
    "Anomaly": "Anomaly",
}


@dataclass
class ROI:
    name: str
    type: str = "Anomaly"
    x: int = 0
    y: int = 0
    w: int = 50
    h: int = 50
    ai_score: float = 1.0  # NG when the ROI's AI score peak / the AI score threshold (recipe's, else AI model's) ≥ this
    height_min: float | None = None  # Stage 2 (3D camera) parameters, stored now
    height_max: float | None = None
    volume_min: float | None = None
    volume_max: float | None = None
    side: str = "Top"
    enabled: bool = True
    mm: list[float] | None = None  # x, y, w, h in mm of the board, where the engine places it at a scale (REQ-RCP-006)


@dataclass
class Recipe:
    board_model: str
    # AI (self-trained anomaly model)
    use_ai: bool = True
    anomaly_threshold: float | None = None  # None -> use the model's calibrated value
    warn_ratio: float = 0.8  # score >= warn_ratio * threshold -> Warning
    # Golden-sample comparison
    use_compare: bool = True
    diff_threshold: int = 45  # per-pixel colour difference (0-255)
    min_defect_area: int = 40  # px of area; smaller blobs are ignored as noise
    min_defect_mm: float | None = None  # with a scale, the minimum defect size (REQ-RCP-006): sets min_defect_area
    ssim_min: float = 0.80  # whole-board structural similarity floor
    changed_pct_max: float = 0.50  # % of board pixels allowed to differ
    max_diff_regions: int = 0  # NG when more difference blobs than this
    rois: list[ROI] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """The recipe as stored; a size in mm it does not set is left out, so a recipe in px, as every recipe before
        S29, is stored, compared and audited exactly as before."""
        d = asdict(self)
        if d["min_defect_mm"] is None:
            del d["min_defect_mm"]
        for roi in d["rois"]:
            if roi["mm"] is None:
                del roi["mm"]
        return d

    def in_mm(self, px_per_mm: float | None) -> Recipe:
        """The recipe with each size it holds in px given in mm too at `px_per_mm`, as Save Recipe stores it under a
        scale (REQ-RCP-006): the minimum defect size as the width of a round defect of its area, and each ROI's box.
        `in_px` at that scale gives back the same sizes in px, so no verdict changes. Without a scale, the recipe."""
        if px_per_mm is None:
            return self
        out = copy.deepcopy(self)
        if out.min_defect_mm is None:
            out.min_defect_mm = disc_width(out.min_defect_area) / px_per_mm
        for roi in out.rois:
            roi.mm = roi.mm or [v / px_per_mm for v in (roi.x, roi.y, roi.w, roi.h)]
        return out

    def in_px(self, px_per_mm: float | None) -> Recipe:
        """The recipe as the engine applies it at `px_per_mm`, its board model's scale (REQ-RCP-006): a copy whose
        minimum defect area is the area of a round defect `min_defect_mm` wide and whose ROIs sit at their place in mm,
        to the nearest px, for each that the recipe sets in mm; a size in px stays as it is. Without a scale, or with
        no size in mm, it judges exactly as the recipe in px; without a scale it is the recipe itself."""
        if px_per_mm is None:
            return self
        out = copy.deepcopy(self)
        if out.min_defect_mm is not None:
            out.min_defect_area = disc_area(out.min_defect_mm * px_per_mm)
        for roi in out.rois:
            if roi.mm is not None:
                roi.x, roi.y, roi.w, roi.h = (round(v * px_per_mm) for v in roi.mm)
        return out

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> Recipe:
        d = dict(d)
        rois = [ROI(**r) for r in d.pop("rois", [])]
        known = {k: v for k, v in d.items() if k in cls.__dataclass_fields__}
        return cls(rois=rois, **known)


def disc_area(width_px: float) -> int:
    """The smallest region, in px of area, that a round defect `width_px` px wide covers: rounded up, so that a defect
    of exactly that width is kept (a difference region smaller than the minimum defect area is dropped as noise)."""
    return max(1, math.ceil(math.pi / 4 * width_px**2 - 1e-9))  # 1e-9: 40 px of area back from its width is 40, not 41


def disc_width(area_px: float) -> float:
    """The width in px of a round defect of `area_px` px of area: a minimum defect area as a size (`disc_area` back)."""
    return math.sqrt(4 * area_px / math.pi)
