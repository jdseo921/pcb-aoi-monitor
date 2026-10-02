"""The two maps a result is judged on, stored as PNG files beside the overlay (REQ-INSP-012, S25c).
The difference map holds whole values 0-255 (`compare.shift_tolerant_diff` on 8-bit Lab images), so an 8-bit PNG
keeps it exactly. The AI score map, "standard deviations above normal" per pixel as float32, is kept as 16-bit in steps
of 1/AI_SCALE (0.001 sigma), clipped at 65.535 sigma: enough for the heat view and for re-evaluating thresholds on the
stored map (REQ-CMP-005), while the values that decided the verdict are the stored checks. Both files are written whole
or not at all (`save_image`). A change of AI_SCALE needs a migration, since a stored map carries no scale of its own.
"""

from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np

from ..errors import AoiError
from .imaging import save_image
from .inspector import InspectionResult

AI_SCALE = 1000.0  # stored value = sigma * AI_SCALE: a uint16 holds 0 .. 65.535 sigma in steps of 0.001


def encode_diff(diff: np.ndarray) -> np.ndarray:
    """The difference map as the 8-bit image a PNG stores exactly (its values are whole numbers 0-255)."""
    return np.asarray(np.clip(np.rint(diff), 0, 255), dtype=np.uint8)


def encode_ai(amap: np.ndarray) -> np.ndarray:
    """The AI score map as 16-bit: sigma * AI_SCALE, rounded in float64 (an exact step) and clipped; NaN stores as 0."""
    scaled = np.nan_to_num(np.asarray(amap, dtype=np.float64)) * AI_SCALE
    return np.asarray(np.clip(np.rint(scaled), 0, 65535), dtype=np.uint16)


def decode_ai(img: np.ndarray) -> np.ndarray:
    """A stored AI map back to sigma, as float32: within half a step of the live value, plus its float32 rounding."""
    return np.asarray(np.asarray(img, dtype=np.float64) / AI_SCALE, dtype=np.float32)


def save_maps(res: InspectionResult, base: Path) -> tuple[str | None, str | None]:
    """Write the maps `res` holds as `<base>_diff.png` and `<base>_ai.png` (base: the overlay path, no suffix)."""
    diff_path = ai_path = None
    if res.compare is not None and res.compare.diff_map is not None:
        diff_path = base.with_name(base.name + "_diff.png")
        save_image(diff_path, encode_diff(res.compare.diff_map))
    if res.anomaly_map is not None:
        ai_path = base.with_name(base.name + "_ai.png")
        save_image(ai_path, encode_ai(res.anomaly_map))
    return (str(diff_path) if diff_path else None, str(ai_path) if ai_path else None)


def read_map(path: str | Path) -> np.ndarray:
    """A stored map as written, 8- or 16-bit, from a path that may hold non-ASCII characters (Windows)."""
    img = cv2.imdecode(np.frombuffer(Path(path).read_bytes(), dtype=np.uint8), cv2.IMREAD_UNCHANGED)
    if img is None:
        raise AoiError("AOI-INSP-001", path=str(path))
    return img


def load_maps(res: InspectionResult, diff_path: str | None, ai_path: str | None) -> InspectionResult:
    """Put the stored maps back on a result; a map never stored, or whose file the sweep deleted, stays None."""
    if diff_path and res.compare is not None and Path(diff_path).is_file():
        res.compare.diff_map = np.asarray(read_map(diff_path), dtype=np.float32)  # the float32 the compare step makes
    if ai_path and Path(ai_path).is_file():
        res.anomaly_map = decode_ai(read_map(ai_path))
    return res
