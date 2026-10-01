"""Inspection recipe: ROIs and thresholds per board model (spec 4.2)."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field

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
    ai_score: float = 1.0  # ROI fails when (anomaly / model threshold) >= this
    height_min: float | None = None  # Stage 2 (3D camera) parameters, stored now
    height_max: float | None = None
    volume_min: float | None = None
    volume_max: float | None = None
    side: str = "Top"
    enabled: bool = True


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
    min_defect_area: int = 40  # px; smaller blobs are ignored as noise
    ssim_min: float = 0.80  # whole-board structural similarity floor
    changed_pct_max: float = 0.50  # % of board pixels allowed to differ
    max_diff_regions: int = 0  # NG when more difference blobs than this
    rois: list[ROI] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> Recipe:
        d = dict(d)
        rois = [ROI(**r) for r in d.pop("rois", [])]
        known = {k: v for k, v in d.items() if k in cls.__dataclass_fields__}
        return cls(rois=rois, **known)
