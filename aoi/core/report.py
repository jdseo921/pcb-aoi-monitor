"""What the validation report of an AI Model Test run holds beyond its rows (REQ-TST-004, stage S47): the misses and
false calls it must show one by one, with their overlays, and recall per defect type. Data only, no Qt and no text: AI
Model Test words and lays it out through tr(), so the report reads in the UI language (Engineering, "Language")."""

from __future__ import annotations

import base64
from typing import Any

import cv2
import numpy as np

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
