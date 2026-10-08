"""Inspection pipeline: one image in, a verdict with its evidence out.

Both the Inspection page and the Compare page call `Inspector.inspect`, so the
metrics shown side-by-side are exactly the ones that produced the OK/NG result.
"""

from __future__ import annotations

import time
from dataclasses import asdict, dataclass, field
from typing import Any

import cv2
import numpy as np

from .. import defects as taxonomy
from .anomaly import AnomalyModel
from .compare import CompareResult, Region, compare, regions_from_mask
from .imaging import align_to_reference
from .recipe import ROI_DEFECT, Recipe

OK, WARN, NG = "OK", "WARN", "NG"


@dataclass
class Check:
    """One decision variable, shown as a row in the Compare page metrics table."""

    name: str
    value: float
    threshold: float
    rule: str  # human-readable rule, e.g. "value < threshold"
    verdict: str  # OK | WARN | NG | INFO
    source: str  # AI | Compare | ROI
    explain: str = ""
    region: str = "Board"  # where the check looked: the whole board, or an ROI's name and box (REQ-INSP-012)


@dataclass
class Defect:
    no: int
    type: str
    score: float  # normalised: 1.0 == exactly at threshold
    side: str
    x: int
    y: int
    w: int
    h: int
    source: str
    severity: str = "Major"

    def as_row(self) -> dict[str, Any]:
        return dict(
            no=self.no,
            type=self.type,
            score=round(self.score, 3),
            side=self.side,
            x=self.x,
            y=self.y,
            w=self.w,
            h=self.h,
        )


@dataclass
class InspectionResult:
    verdict: str
    score: float
    checks: list[Check] = field(default_factory=list)
    defects: list[Defect] = field(default_factory=list)
    image: np.ndarray | None = None  # test image (aligned to reference when available)
    reference: np.ndarray | None = None
    anomaly_map: np.ndarray | None = None
    compare: CompareResult | None = None
    elapsed_ms: float = 0.0
    notes: list[str] = field(default_factory=list)
    view: str = "Top"  # the camera view the board was inspected under, kept with the result (REQ-INSP-010)

    def metrics_dict(self) -> dict[str, Any]:
        d = {c.name: c.value for c in self.checks}
        d["elapsed_ms"] = round(self.elapsed_ms, 1)
        if self.compare:
            d.update({k: v for k, v in self.compare.metrics.items() if k not in d})
        return d

    def to_dict(self) -> dict[str, Any]:
        """The result without its images, as plain values `json.dumps` writes and `from_dict` reads back unchanged:
        verdict, score, every check and defect, the compare metrics and regions, notes, view and elapsed time
        (REQ-INSP-008). The images (board, reference, maps) are files, not JSON."""
        compare = None
        if self.compare is not None:
            regions = [_plain(asdict(r)) for r in self.compare.regions]
            compare = {"metrics": _plain(self.compare.metrics), "regions": regions}
        return {
            "verdict": self.verdict,
            "score": _plain(self.score),
            "checks": [_plain(asdict(c)) for c in self.checks],
            "defects": [_plain(asdict(d)) for d in self.defects],
            "compare": compare,
            "elapsed_ms": _plain(self.elapsed_ms),
            "notes": list(self.notes),
            "view": self.view,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> InspectionResult:
        """A stored result read back from `to_dict`: the same checks, defects, metrics and regions; no images. A field
        a later build added is left out, so a result written by that build still reads."""
        compare = None
        if d.get("compare") is not None:
            regions = [Region(**_known(Region, r)) for r in d["compare"].get("regions", [])]
            compare = CompareResult(regions=regions, metrics=dict(d["compare"].get("metrics", {})))
        return cls(
            verdict=d["verdict"],
            score=float(d["score"]),
            checks=[Check(**_known(Check, c)) for c in d.get("checks", [])],
            defects=[Defect(**_known(Defect, x)) for x in d.get("defects", [])],
            compare=compare,
            elapsed_ms=float(d.get("elapsed_ms", 0.0)),
            notes=list(d.get("notes", [])),
            view=str(d.get("view", "Top")),
        )


def _known(cls: type[Any], d: dict[str, Any]) -> dict[str, Any]:
    """`d` without the keys the dataclass `cls` has no field for."""
    return {k: v for k, v in d.items() if k in cls.__dataclass_fields__}


def _plain(v: Any) -> Any:
    """`v` with every NumPy scalar made the Python value it holds, so JSON and SQLite take it and give it back equal."""
    if isinstance(v, np.generic):
        return v.item()
    if isinstance(v, dict):
        return {k: _plain(x) for k, x in v.items()}
    if isinstance(v, (list, tuple)):
        return [_plain(x) for x in v]
    return v


def _grade(value: float, threshold: float, warn_ratio: float, higher_is_bad: bool = True) -> str:
    if higher_is_bad:
        if value >= threshold:
            return NG
        return WARN if value >= threshold * warn_ratio else OK
    if value < threshold:
        return NG
    return WARN if value < threshold + (1 - warn_ratio) * (1 - threshold) else OK


def _overlap(r: Region, x: int, y: int, w: int, h: int) -> bool:
    return not (r.x + r.w <= x or x + w <= r.x or r.y + r.h <= y or y + h <= r.y)


class Inspector:
    """The engine for one board model. `model_version`, `recipe_rev` and their UUIDs name the AI model version and the
    recipe revision a saved record carries (REQ-INSP-008, REQ-INSP-012), and `reference_path` and `reference_sha256`
    the golden board file it judges against and the SHA-256 of its bytes (REQ-CMP-003): `AppContext.inspector()` fills
    them; an Inspector built bare has none."""

    def __init__(
        self,
        recipe: Recipe,
        model: AnomalyModel | None = None,
        reference: np.ndarray | None = None,
        side: str = "Top",
        model_version: str | None = None,
        recipe_rev: int | None = None,
        model_uuid: str | None = None,
        recipe_uuid: str | None = None,
        reference_path: str | None = None,
        reference_sha256: str | None = None,
    ) -> None:
        self.recipe = recipe
        self.model = model
        self.reference = reference
        self.side = side
        self.model_version = model_version
        self.recipe_rev = recipe_rev
        self.model_uuid = model_uuid
        self.recipe_uuid = recipe_uuid
        self.reference_path = reference_path
        self.reference_sha256 = reference_sha256

    def inspect(self, img: np.ndarray) -> InspectionResult:
        t0 = time.perf_counter()
        r = self.recipe
        res = InspectionResult(verdict=OK, score=0.0, reference=self.reference, view=self.side)
        regions: list[Region] = []
        work = img

        # 0) Register onto the golden board so pixels mean the same place on every board.
        align_info = None
        if self.reference is not None:
            work, align_info = align_to_reference(img, self.reference)

        # 1) Golden-sample comparison --------------------------------------------
        if r.use_compare and self.reference is not None:
            cr = compare(img, self.reference, r.diff_threshold, r.min_defect_area, work, align_info)
            res.compare = cr
            m = cr.metrics
            res.checks.append(
                Check(
                    "SSIM similarity",
                    m["ssim"],
                    r.ssim_min,
                    "< thr → NG",
                    _grade(m["ssim"], r.ssim_min, r.warn_ratio, higher_is_bad=False),
                    "Compare",
                    "1.0 = identical to the golden board",
                )
            )
            res.checks.append(
                Check(
                    "Changed area %",
                    m["changed_pct"],
                    r.changed_pct_max,
                    "≥ thr → NG",
                    _grade(m["changed_pct"], r.changed_pct_max, r.warn_ratio),
                    "Compare",
                    f"pixels whose colour differs by ≥ {r.diff_threshold}",
                )
            )
            res.checks.append(
                Check(
                    "Difference regions",
                    m["compare_regions"],
                    r.max_diff_regions,
                    "> thr → NG",
                    NG if m["compare_regions"] > r.max_diff_regions else OK,
                    "Compare",
                    f"blobs ≥ {r.min_defect_area} px after noise clean-up",
                )
            )
            res.checks.append(
                Check(
                    "Alignment inliers",
                    m["alignment_inliers"],
                    12,
                    "info only",
                    "INFO" if m["alignment_inliers"] >= 12 else WARN,
                    "Compare",
                    m["alignment_method"],
                )
            )
            regions += cr.regions
        elif r.use_compare:
            res.notes.append("No golden reference image set for this board model; comparison skipped.")

        # 2) Self-trained anomaly model ------------------------------------------
        if r.use_ai and self.model is not None:
            amap = self.model.anomaly_map(work)
            res.anomaly_map = amap
            thr = r.anomaly_threshold or self.model.image_threshold
            score = self.model.score(amap)
            res.score = score / thr
            res.checks.append(
                Check(
                    "AI anomaly score",
                    score,
                    thr,
                    "≥ thr → NG",
                    _grade(score, thr, r.warn_ratio),
                    "AI",
                    self.model.meta.get("threshold_rule", ""),
                )
            )
            pix_thr = self.model.pixel_threshold
            mask: np.ndarray = (amap >= pix_thr).astype(np.uint8) * 255
            mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((5, 5), np.uint8))
            regions += regions_from_mask(mask, amap / thr, r.min_defect_area, "ai")
        elif r.use_ai:
            res.notes.append("No trained model for this board model; AI check skipped.")
        res.image = work

        # 3) ROI checks ----------------------------------------------------------
        for roi in (x for x in r.rois if x.enabled):
            if res.anomaly_map is None or self.model is None:
                break
            thr = r.anomaly_threshold or self.model.image_threshold
            patch = res.anomaly_map[roi.y : roi.y + roi.h, roi.x : roi.x + roi.w]
            if patch.size == 0:
                continue
            val = float(patch.max()) / thr
            res.checks.append(
                Check(
                    f"ROI {roi.name} [{roi.type}]",
                    val,
                    roi.ai_score,
                    "≥ thr → NG",
                    _grade(val, roi.ai_score, r.warn_ratio),
                    "ROI",
                    f"fails as {ROI_DEFECT.get(roi.type, 'Anomaly')}",
                    region=f"{roi.name} @ {roi.x},{roi.y} {roi.w}x{roi.h}",
                )
            )

        # 4) Merge evidence into a defect list ------------------------------------
        res.defects = self._defects(regions, res)

        # 5) Verdict: any NG check -> NG; else any WARN -> WARN.
        verdicts = [c.verdict for c in res.checks]
        res.verdict = NG if NG in verdicts else WARN if WARN in verdicts else OK
        if res.verdict == OK and res.defects and any(d.severity != "Minor" for d in res.defects):
            res.verdict = WARN
        res.elapsed_ms = (time.perf_counter() - t0) * 1000
        return res

    def _defects(self, regions: list[Region], res: InspectionResult) -> list[Defect]:
        merged: list[Region] = []
        for reg in sorted(regions, key=lambda q: -q.area):
            if any(_overlap(reg, m.x, m.y, m.w, m.h) for m in merged):
                continue
            merged.append(reg)
        out = []
        for i, reg in enumerate(merged, 1):
            dtype = "Anomaly"
            for roi in self.recipe.rois:
                if roi.enabled and _overlap(reg, roi.x, roi.y, roi.w, roi.h):
                    dtype = ROI_DEFECT.get(roi.type, "Anomaly")
                    break
            score = reg.peak if reg.source == "ai" else reg.peak / max(1, self.recipe.diff_threshold)
            sev = taxonomy.BY_NAME.get(dtype, taxonomy.ANOMALY).severity
            out.append(Defect(i, dtype, float(score), res.view, reg.x, reg.y, reg.w, reg.h, reg.source, sev))
        return out


def draw_overlay(res: InspectionResult) -> np.ndarray:
    """Annotated image: bounding boxes + labels, colour by severity (spec 4.1)."""
    if res.image is None:
        raise ValueError("draw_overlay needs an inspected image")
    img = res.image.copy()
    colors = {"Critical": (53, 57, 229), "Major": (0, 140, 251), "Minor": (53, 216, 253)}
    th = max(2, img.shape[1] // 400)
    for d in res.defects:
        c = colors.get(d.severity, (0, 0, 255))
        cv2.rectangle(img, (d.x, d.y), (d.x + d.w, d.y + d.h), c, th)
        label = f"{d.no}:{d.type} {d.score:.2f}"
        cv2.putText(img, label, (d.x, max(14, d.y - 4)), cv2.FONT_HERSHEY_SIMPLEX, 0.45 * th / 2 + 0.2, c, th // 2 + 1)
    banner = {OK: (80, 175, 76), WARN: (53, 216, 253), NG: (53, 57, 229)}[res.verdict]
    cv2.rectangle(img, (0, 0), (110, 34), banner, -1)
    cv2.putText(img, res.verdict, (10, 26), cv2.FONT_HERSHEY_SIMPLEX, 0.9, (255, 255, 255), 2)
    return img
