"""What the validation report of an AI Model Test run holds beyond its rows (REQ-TST-004, stage S47): the misses and
false calls it must show one by one, with their overlays, and recall per defect type. Data only, no Qt and no text: AI
Model Test words and lays it out through tr(), so the report reads in the UI language (Engineering, "Language")."""

from __future__ import annotations

import base64
import math
from typing import Any

import cv2
import numpy as np

from .. import defects
from . import stats

REPORT_PX = 800  # the longest side of an overlay in the PDF: legible on an A4 page, small enough to embed many


def misses_and_false_calls(rows: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """The run's missed defects (NG images called OK) and false calls (OK images called NG or WARN), in row order: every
    one the report shows with its overlay (Customers & Launch, "Validation": one page per miss and false call)."""
    misses = [r for r in rows if r.get("gt") == "NG" and r.get("ai_result") == "OK"]
    false_calls = [r for r in rows if r.get("gt") == "OK" and r.get("ai_result") in ("NG", "WARN")]
    return misses, false_calls


def image_uri(image: np.ndarray, longest: int = REPORT_PX) -> str:
    """`image` scaled to at most `longest` px on its longest side, as a PNG data URI an HTML report embeds."""
    h, w = image.shape[:2]
    if max(h, w) > longest:
        f = longest / max(h, w)
        image = cv2.resize(image, (max(1, round(w * f)), max(1, round(h * f))), interpolation=cv2.INTER_AREA)
    ok, png = cv2.imencode(".png", image)
    if not ok:
        raise ValueError("the overlay could not be encoded as PNG")
    return "data:image/png;base64," + base64.b64encode(png.tobytes()).decode("ascii")


# The targets a customer validation is judged against unless the customer agrees others before testing (Charter, "Open
# product questions": proposed; Customers & Launch, Validation step 2): no missed Critical defect, a false call rate of
# 5 % or less, and 1 s or less per image (95th percentile) on the named PC.
DEFAULT_TARGETS = {"missed_critical": 0, "false_call_rate": 0.05, "seconds_per_image": 1.0}


def critical(defect_type: str | None) -> bool:
    """Whether a defect type is Critical in the classification table."""
    found = defects.BY_NAME.get(defect_type or "")
    return found is not None and found.severity == "Critical"


def p95(values: list[float]) -> float | None:
    """The 95th percentile of `values` (nearest rank), or None for none."""
    if not values:
        return None
    ordered = sorted(values)
    return ordered[max(0, math.ceil(0.95 * len(ordered)) - 1)]


def target_results(rows: list[dict[str, Any]], targets: dict[str, float] | None = None) -> list[dict[str, Any]]:
    """Each agreed target beside its result on the run's rows, with whether it is met (REQ-TST-008): missed Critical
    defects (Critical NG images called OK, of the Critical NG images), the false call rate with its count and bound, and
    the time per image at the 95th percentile (`ms` of each row; None, not met, when the rows carry no times)."""
    agreed = {**DEFAULT_TARGETS, **(targets or {})}
    crit = [r for r in rows if r.get("gt") == "NG" and critical(r.get("defect_type"))]
    missed = [r for r in crit if r.get("ai_result") == "OK"]
    ok = [r for r in rows if r.get("gt") == "OK"]
    fc = stats.rate(sum(r.get("ai_result") in ("NG", "WARN") for r in ok), len(ok))
    seconds = p95([float(r["ms"]) / 1000 for r in rows if r.get("ms") is not None])
    return [
        {"target": "missed_critical", "agreed": agreed["missed_critical"], "result": stats.rate(len(missed), len(crit)),
         "met": len(missed) <= agreed["missed_critical"]},
        {"target": "false_call_rate", "agreed": agreed["false_call_rate"], "result": fc,
         "met": fc["rate"] is not None and fc["rate"] <= agreed["false_call_rate"]},
        {"target": "seconds_per_image", "agreed": agreed["seconds_per_image"], "result": seconds,
         "met": seconds is not None and seconds <= agreed["seconds_per_image"]},
    ]  # fmt: skip


def label_counts(rows: list[dict[str, Any]]) -> dict[str, int]:
    """The validation set's images by label, and its NG images by defect type: what data the validation used."""
    out: dict[str, int] = {"OK": 0, "NG": 0}
    for r in rows:
        if r.get("gt") in out:
            out[r["gt"]] += 1
        if r.get("gt") == "NG" and r.get("defect_type"):
            key = f"NG: {r['defect_type']}"
            out[key] = out.get(key, 0) + 1
    return out
