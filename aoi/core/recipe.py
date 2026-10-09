"""Inspection recipe: ROIs and thresholds per board model (spec 4.2)."""

from __future__ import annotations

import copy
import math
from dataclasses import asdict, dataclass, field
from typing import Any

from ..defects import MANDATORY_AOI_SET, REQUIRES_3D_OR_SIDE
from ..errors import QT_TRANSLATE_NOOP, AoiError

ROI_TYPES = ["Presence", "Polarity", "Solder Bridge", "Height", "Anomaly"]
MAX_MM = 10000  # the largest size or place in mm a recipe holds, 10 m: past any board (AOI-RCP-011, S29 review)
MIN_SIZE = QT_TRANSLATE_NOOP("Errors", "minimum defect size")  # what AOI-RCP-011 names
ROI_BOX = QT_TRANSLATE_NOOP("Errors", "box of ROI {roi}")
RESOLVED_PX = 4  # the smallest defect width, in px, told from image noise (REQ-INSP-014, the resolution test)
IN_MM = QT_TRANSLATE_NOOP("Errors", "{mm:.2f} mm")  # AOI-RCP-007's sizes, with a scale or without one
IN_AREA = QT_TRANSLATE_NOOP("Errors", "{area} px of area")

# Defect name reported when a region fails inside an ROI of this type.
ROI_DEFECT = {
    "Presence": "Missing Component",
    "Polarity": "Polarity Error",
    "Solder Bridge": "Solder Bridge",
    "Height": "Pin Height Error",
    "Anomaly": "Anomaly",
}
# The ROI type that checks one of the 10 mandatory AOI checks (classification table section 4) by itself; the others are
# covered by the whole-board AI check and the Golden board comparison (REQ-RCP-005).
ROI_FOR_CHECK = {
    "Missing Component": "Presence",
    "Polarity Error": "Polarity",
    "Solder Bridge": "Solder Bridge",
    "Connector Pin Height": "Height",
    "3D Coplanarity": "Height",
    "Solder Volume": "Height",
}
STAGE1_CHECKS = [c for c in MANDATORY_AOI_SET if c not in REQUIRES_3D_OR_SIDE]  # the 6 a Stage 1 station can cover


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

    def uncovered_checks(self) -> list[str]:
        """The Stage 1 mandatory AOI checks the recipe leaves uncovered, in the classification table's order: a check is
        covered by an enabled ROI of its type, or by the whole board, while the AI check or the Golden board comparison
        is on. A save that leaves one uncovered needs a reason (REQ-RCP-005); the 4 that need Stage 2 hardware are not
        counted."""
        types = {r.type for r in self.rois if r.enabled}
        if self.use_ai or self.use_compare:
            return []
        return [c for c in STAGE1_CHECKS if ROI_FOR_CHECK.get(c) not in types]

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

    def mm_refusal(self) -> AoiError | None:
        """AOI-RCP-011 for the first size in mm that `in_px` cannot apply, which `AppContext.save_recipe` refuses: a
        minimum defect size, or an ROI's width or height in mm, that is no number above 0, an ROI's x or y below 0, a
        size or place above MAX_MM, or a box that is not four numbers; None when there is none (S29 review)."""
        if self.min_defect_mm is not None and not _mm(self.min_defect_mm):
            return AoiError(
                "AOI-RCP-011", size=MIN_SIZE, board_model=self.board_model, value=self.min_defect_mm, most=MAX_MM
            )
        for roi in self.rois:
            box = roi.mm if isinstance(roi.mm, list) and len(roi.mm) == 4 else [math.nan]
            if roi.mm is not None and not all(_mm(v, place=i < 2) for i, v in enumerate(box)):
                return AoiError(
                    "AOI-RCP-011",
                    size=ROI_BOX.fill(roi=roi.name),
                    board_model=self.board_model,
                    value=roi.mm,
                    most=MAX_MM,
                )
        return None

    @property
    def sized_in_mm(self) -> bool:
        """Whether the recipe holds a size in mm, its minimum defect size or an enabled ROI's box: one a scale sizes."""
        return self.min_defect_mm is not None or any(roi.mm is not None and roi.enabled for roi in self.rois)

    def size_notice(self, px_per_mm: float | None) -> AoiError | None:
        """AOI-RCP-007 when the minimum defect size spans under RESOLVED_PX px at `px_per_mm`, as `in_px` applies it
        (REQ-INSP-014), with the size and the least size to give in mm at a scale, as an area without one; else None."""
        mm = self.min_defect_mm if px_per_mm else None
        width = mm * px_per_mm if mm is not None and px_per_mm else disc_width(self.min_defect_area)
        if width >= RESOLVED_PX - 1e-9:
            return None
        if px_per_mm:
            least_mm = math.ceil(RESOLVED_PX / px_per_mm * 100) / 100  # rounded up, so that it spans 4 px or more
            size, least = IN_MM.fill(mm=width / px_per_mm), IN_MM.fill(mm=least_mm)
        else:
            size, least = IN_AREA.fill(area=self.min_defect_area), IN_AREA.fill(area=disc_area(RESOLVED_PX))
        return AoiError("AOI-RCP-007", size=size, px=width, least=least)

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


def _mm(value: object, place: bool = False) -> bool:
    """Whether `value` is a size in mm the engine applies: a number, not true or false, above 0 (0 or more for a
    place) and at most MAX_MM, so that no size in px overflows."""
    if isinstance(value, bool) or not isinstance(value, int | float):
        return False
    return (0 <= value if place else 0 < value) and value <= MAX_MM


def scale_digits(a: float | None, b: float | None) -> int:
    """The decimals, 2 or more, that print two scales apart when they differ (S29 review), else 2."""
    return next((d for d in range(2, 17) if a and b and f"{a:.{d}f}" != f"{b:.{d}f}"), 2)


def changes(before: dict[str, Any] | None, after: dict[str, Any]) -> list[tuple[str, Any, Any]]:
    """What a save changes, as (field, before, after), in the stored recipe's order: each setting, and each ROI by name
    (added: before None; removed: after None), so a confirmation can list before -> after (REQ-RCP-004)."""
    old = before or {}
    out: list[tuple[str, Any, Any]] = []
    for key, value in after.items():
        if key not in ("rois", "board_model") and old.get(key) != value:
            out.append((key, old.get(key), value))
    if "min_defect_mm" in old and "min_defect_mm" not in after:
        out.append(("min_defect_mm", old["min_defect_mm"], None))
    rois_before = {r["name"]: r for r in old.get("rois", [])}
    rois_after = {r["name"]: r for r in after.get("rois", [])}
    for name in [*rois_after, *[n for n in rois_before if n not in rois_after]]:
        b, a = rois_before.get(name), rois_after.get(name)
        if b != a:
            out.append((f"ROI {name}", b, a))
    return out
