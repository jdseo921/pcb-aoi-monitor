"""Inspection pipeline: one image in, a verdict with its evidence out.

Both the Inspection page and the Compare page call `Inspector.inspect`, so the
metrics shown side-by-side are exactly the ones that produced the OK/NG result.
"""

from __future__ import annotations

import math
import time
from dataclasses import asdict, dataclass, field
from typing import Any

import cv2
import numpy as np

from .. import defects as taxonomy
from ..errors import QT_TRANSLATE_NOOP, AoiError, joined
from .anomaly import AnomalyModel
from .compare import MIN_SIDE, CompareResult, Region, changed_regions, compare, regions_from_mask
from .imaging import align_to_reference
from .recipe import ROI_DEFECT, Recipe

OK, WARN, NG = "OK", "WARN", "NG"
# The engine's notes, stored with each result as written; aoi/core/explain.py words them for the screen.
NO_GOLDEN_NOTE = "No golden reference image set for this board model; comparison skipped."
NO_AI_NOTE = "No trained model for this board model; AI check skipped."
# A re-evaluation's (REQ-CMP-005), when the recipe turns on a check that did not run when the board was inspected.
NOT_COMPARED_NOTE = "Comparison with the golden board did not run at inspection; not judged again."
NOT_AI_JUDGED_NOTE = "AI check did not run at inspection; not judged again."
NOT_RUN = {  # why a check did not run, by its note, for AOI-INSP-010
    NO_GOLDEN_NOTE: QT_TRANSLATE_NOOP("Errors", "no Golden board is set"),
    NOT_COMPARED_NOTE: QT_TRANSLATE_NOOP(
        "Errors", "the Golden board comparison did not run when the board was inspected"
    ),
    NO_AI_NOTE: QT_TRANSLATE_NOOP("Errors", "no AI model is trained"),
    NOT_AI_JUDGED_NOTE: QT_TRANSLATE_NOOP("Errors", "the AI check did not run when the board was inspected"),
}


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


@dataclass(frozen=True)
class AiEvidence:
    """What the AI model gave a board besides its map: the score, and the calibration of the AI model that made the
    map: its image threshold (which applies unless the recipe sets its own), its pixel threshold (which marks the pixels
    of an AI defect) and the rule it was calibrated by. A re-evaluation takes the score from the stored check and the
    calibration from the model registry (REQ-CMP-005)."""

    score: float
    image_threshold: float
    pixel_threshold: float
    rule: str = ""


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
    if not math.isfinite(value):  # NaN fails every comparison below and would pass: a value that is no number is NG
        return NG
    if higher_is_bad:
        if value >= threshold:
            return NG
        return WARN if value >= threshold * warn_ratio else OK
    if value < threshold:
        return NG
    return WARN if value < threshold + (1 - warn_ratio) * (1 - threshold) else OK


def _overlap(r: Region, x: int, y: int, w: int, h: int) -> bool:
    return not (r.x + r.w <= x or x + w <= r.x or r.y + r.h <= y or y + h <= r.y)


CELL = 64  # px: the side of the grid cells `merge_regions` indexes the regions it keeps by


def merge_regions(regions: list[Region]) -> list[Region]:
    """The regions kept as defects: largest area first (ties in the order given), each that overlaps none kept before
    it, boxes that only touch being apart (`_overlap`). The kept boxes are indexed by the CELL px cells they cover, and
    two boxes that overlap share a cell, so a region is tested only against those in its cells: the same regions as
    testing every kept box, which took about 1.5 s for the 5,600 regions that Pixel difference 10 and Minimum defect
    area 1 leave on a 5 MP board (#249)."""
    merged: list[Region] = []
    grid: dict[tuple[int, int], list[Region]] = {}
    for reg in sorted(regions, key=lambda q: -q.area):
        cells = [
            (cx, cy)  # a box with no width or height still covers its corner's cell, which `_overlap` may count
            for cx in range(reg.x // CELL, (reg.x + max(reg.w, 1) - 1) // CELL + 1)
            for cy in range(reg.y // CELL, (reg.y + max(reg.h, 1) - 1) // CELL + 1)
        ]
        if any(_overlap(reg, m.x, m.y, m.w, m.h) for cell in cells for m in grid.get(cell, ())):
            continue
        merged.append(reg)
        for cell in cells:
            grid.setdefault(cell, []).append(reg)
    return merged


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

    @property
    def inputs(self) -> tuple[str | None, str | None, str | None]:
        """What the engine was built from: the AI model's UUID, the recipe revision's UUID and the Golden board's path,
        each None when it has none. `AppContext.engine_is_current` compares them with what is active now (#243)."""
        return self.model_uuid, self.recipe_uuid, self.reference_path

    def inspect(self, img: np.ndarray) -> InspectionResult:
        """The board in `img` aligned, compared and judged. AOI-INSP-011 before any work when it, or the golden board,
        has a side under MIN_SIDE px; AOI-INSP-010 when no check could judge it (`judge`)."""
        board, golden = QT_TRANSLATE_NOOP("Errors", "board image"), QT_TRANSLATE_NOOP("Errors", "Golden board")
        for image, im in ((board, img), (golden, self.reference)):
            if im is not None and min(im.shape[:2]) < MIN_SIDE:
                h, w = im.shape[:2]
                raise AoiError("AOI-INSP-011", image=image, width=w, height=h, minimum=MIN_SIDE)
        t0 = time.perf_counter()
        r = self.recipe
        res = InspectionResult(verdict=OK, score=0.0, reference=self.reference, view=self.side)
        work = img

        # 0) Register onto the golden board so pixels mean the same place on every board; then the evidence, from the
        # golden board comparison (its maps and metrics) and from the AI model (its map, score and calibration).
        align_info = None
        if self.reference is not None:
            work, align_info = align_to_reference(img, self.reference)
        if r.use_compare and self.reference is not None:
            res.compare = compare(img, self.reference, r.diff_threshold, r.min_defect_area, work, align_info)
        elif r.use_compare:
            res.notes.append(NO_GOLDEN_NOTE)
        ai = None
        if r.use_ai and self.model is not None:
            m, res.anomaly_map = self.model, self.model.anomaly_map(work)
            rule = m.meta.get("threshold_rule", "")
            ai = AiEvidence(m.score(res.anomaly_map), m.image_threshold, m.pixel_threshold, rule)
        elif r.use_ai:
            res.notes.append(NO_AI_NOTE)
        res.image = work
        self.judge(res, ai)
        res.elapsed_ms = (time.perf_counter() - t0) * 1000
        return res

    def judge(self, res: InspectionResult, ai: AiEvidence | None, peaks: dict[str, float] | None = None) -> None:
        """Steps 1 to 5 on the evidence `res` holds, by this engine's recipe: the checks of its golden board
        comparison, of its AI map with `ai` and of the recipe's ROIs, then its defects and its verdict. `inspect` calls
        it on a board just inspected and `re_grade` on a stored result's maps (REQ-CMP-005), so both judge by one set
        of rules. `peaks` holds the highest AI map value of each ROI the result was judged on, by the region its check
        names; an ROI found there takes that value, not one read from a stored map that holds it to a step. A board no
        check judged gets no verdict: AOI-INSP-010, saying why each check did not run (#169)."""
        r = self.recipe
        regions: list[Region] = []
        res.checks, res.defects, res.score = [], [], 0.0  # judged afresh, never added to

        # 1) Golden-sample comparison --------------------------------------------
        if res.compare is not None:
            m = res.compare.metrics
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
            regions += res.compare.regions

        # 2) Self-trained anomaly model ------------------------------------------
        if ai is not None and res.anomaly_map is not None:
            amap = res.anomaly_map
            thr = r.anomaly_threshold or ai.image_threshold
            score = ai.score
            res.score = score / thr
            res.checks.append(
                Check(
                    "AI anomaly score",
                    score,
                    thr,
                    "≥ thr → NG",
                    _grade(score, thr, r.warn_ratio),
                    "AI",
                    ai.rule,
                )
            )
            pix_thr = ai.pixel_threshold
            mask: np.ndarray = (amap >= pix_thr).astype(np.uint8) * 255
            mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((5, 5), np.uint8))
            regions += regions_from_mask(mask, amap / thr, r.min_defect_area, "ai")

        # 3) ROI checks ----------------------------------------------------------
        for roi in (x for x in r.rois if x.enabled):
            if res.anomaly_map is None or ai is None:
                break
            thr = r.anomaly_threshold or ai.image_threshold
            patch = res.anomaly_map[roi.y : roi.y + roi.h, roi.x : roi.x + roi.w]
            if patch.size == 0:
                continue
            where = f"{roi.name} @ {roi.x},{roi.y} {roi.w}x{roi.h}"
            val = (peaks[where] if peaks and where in peaks else float(patch.max())) / thr
            res.checks.append(
                Check(
                    f"ROI {roi.name} [{roi.type}]",
                    val,
                    roi.ai_score,
                    "≥ thr → NG",
                    _grade(val, roi.ai_score, r.warn_ratio),
                    "ROI",
                    f"fails as {ROI_DEFECT.get(roi.type, 'Anomaly')}",
                    region=where,
                )
            )

        # 4) Merge evidence into a defect list ------------------------------------
        res.defects = self._defects(regions, res)

        # 5) Verdict: any NG check -> NG; else any WARN -> WARN. No check, no verdict: never OK on no evidence (#169).
        if not res.checks:
            turned_off = (
                (QT_TRANSLATE_NOOP("Errors", "the recipe turns the Golden board comparison off"), r.use_compare),
                (QT_TRANSLATE_NOOP("Errors", "the recipe turns the AI model off"), r.use_ai),
            )
            why = [NOT_RUN[n] for n in res.notes if n in NOT_RUN] + [text for text, on in turned_off if not on]
            reason = joined(QT_TRANSLATE_NOOP("Errors", "{first}; {rest}"), why) or QT_TRANSLATE_NOOP(
                "Errors", "no check ran"
            )
            raise AoiError("AOI-INSP-010", board=r.board_model, reason=reason)
        verdicts = [c.verdict for c in res.checks]
        res.verdict = NG if NG in verdicts else WARN if WARN in verdicts else OK
        if res.verdict == OK and res.defects and any(d.severity != "Minor" for d in res.defects):
            res.verdict = WARN

    def _defects(self, regions: list[Region], res: InspectionResult) -> list[Defect]:
        out = []
        for i, reg in enumerate(merge_regions(regions), 1):
            dtype = "Anomaly"
            for roi in self.recipe.rois:
                if roi.enabled and _overlap(reg, roi.x, roi.y, roi.w, roi.h):
                    dtype = ROI_DEFECT.get(roi.type, "Anomaly")
                    break
            score = reg.peak if reg.source == "ai" else reg.peak / max(1, self.recipe.diff_threshold)
            sev = taxonomy.BY_NAME.get(dtype, taxonomy.ANOMALY).severity
            out.append(Defect(i, dtype, float(score), res.view, reg.x, reg.y, reg.w, reg.h, reg.source, sev))
        return out


def re_grade(
    judged: InspectionResult,
    recipe: Recipe,
    ai: AiEvidence | None,
    *,
    changed: tuple[np.ndarray, list[Region], dict[str, Any]] | None = None,
) -> InspectionResult:
    """The checks, defects and verdict `judged` would get under `recipe`, judged again from the evidence it holds
    without aligning, comparing or running the AI model (REQ-CMP-005): the difference regions are found again on its
    difference map with the recipe's pixel difference and minimum area, the AI score in `ai` is graded against the
    recipe's threshold, and the AI defects are read from its AI map. An ROI it was judged on keeps the peak it was
    judged by; an ROI added, moved or renamed since is read from the AI map. `judged` is a result as inspected or
    stored, not one this function made; `ai` is its AI evidence (the score of its AI check, the AI model's calibration)
    when its AI check ran, else None. Similarity, alignment and the AI score keep the values `judged` holds, since no
    threshold changes them, and so do the inspection time, the view and the picture. A check the recipe turns on that
    did not run on the board is not judged, with a note saying so, as inspecting with the recipe notes a check it cannot
    run. `judged` is not changed; the result shares its maps. `changed`, when given, is what `changed_regions` gives
    for `judged`'s difference map with the recipe's pixel difference and minimum area, found by the caller
    (`AppContext.re_evaluate` finds them while the AI map decodes, #249). ValueError when a check the recipe uses ran
    on the board but its map, or its AI evidence, is not given; AOI-INSP-010 when the recipe leaves no check that ran
    on it."""
    cr, ran_ai = judged.compare, any(c.source == "AI" for c in judged.checks)
    if (recipe.use_compare and cr is not None and cr.diff_map is None) or (
        recipe.use_ai and ran_ai and (ai is None or judged.anomaly_map is None)
    ):
        raise ValueError("re_grade needs the maps and the AI evidence the result was judged on")
    res = InspectionResult(OK, 0.0, image=judged.image, reference=judged.reference, view=judged.view)
    res.elapsed_ms = judged.elapsed_ms
    if recipe.use_compare and cr is not None and cr.diff_map is not None:
        mask, regions, found = changed or changed_regions(cr.diff_map, recipe.diff_threshold, recipe.min_defect_area)
        res.compare = CompareResult(cr.aligned, cr.diff_map, cr.ssim_map, mask, regions, {**cr.metrics, **found})
    if recipe.use_ai and ran_ai:
        res.anomaly_map = judged.anomaly_map
    skipped = {NO_GOLDEN_NOTE, NO_AI_NOTE, NOT_COMPARED_NOTE, NOT_AI_JUDGED_NOTE}  # worked out again, in this order
    if recipe.use_compare and cr is None:
        res.notes.append(NO_GOLDEN_NOTE if NO_GOLDEN_NOTE in judged.notes else NOT_COMPARED_NOTE)
    if recipe.use_ai and not ran_ai:
        res.notes.append(NO_AI_NOTE if NO_AI_NOTE in judged.notes else NOT_AI_JUDGED_NOTE)
    res.notes += [n for n in judged.notes if n not in skipped]
    ai_thr = next((c.threshold for c in judged.checks if c.source == "AI"), None)
    peaks = {  # each ROI's peak as it was judged: its value times the AI threshold it was divided by, in float32
        c.region: float(np.float32(c.value * ai_thr)) for c in judged.checks if c.source == "ROI" and ai_thr
    }
    Inspector(recipe).judge(res, ai, peaks)  # no AI map when the recipe turns the AI check off: no AI check
    return res


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
