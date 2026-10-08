"""The two maps a result is judged on, as PNG files beside the overlay (REQ-INSP-012, S25c): the difference map
(whole values 0-255 from `compare.shift_tolerant_diff`) exactly, as 8-bit; the AI score map ("standard deviations
above normal" per pixel, float32) as 16-bit codes, `<base>_ai2.png` since S28a (format 2): a code below AI_KNEE is a
value in steps of 0.001 sigma, up to 32.767 sigma, and a code from AI_KNEE up a value on a log scale, in steps of
1/AI_LOG_STEPS of the value, up to AI_MAX (about 1789 sigma; a model this app trains gives less than
1 / anomaly.SPREAD_FLOOR = 1000, its error being at most 1). Each pixel is kept on the side of the AI model's pixel
threshold it was judged on, so judging a stored result again (REQ-CMP-005) finds the AI defects it was judged with and
reads every value within one step. `<base>_ai.png` files (format 1, S25c to S27) hold 0.001 sigma steps clipped at
65.535 sigma and read as such. Both maps are written whole or not at all (`save_image`); another format takes another
file name (docs/adr/0005-stored-ai-map-format-2.md)."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import cv2
import numpy as np

from ..errors import QT_TRANSLATE_NOOP, AoiError
from .imaging import save_image
from .inspector import InspectionResult

AI_SCALE = 1000  # codes per sigma below AI_KNEE: steps of 0.001 sigma
AI_KNEE = 32768  # the code of 32.768 sigma, where the log scale starts
AI_LOG_STEPS = 8192  # codes per factor e above the knee: each step 1/8192 of the value
AI_FILE, AI_FILE_V1 = "_ai2.png", "_ai.png"  # the AI map's file name ending, by format


def _values(codes: np.ndarray) -> np.ndarray:
    c, knee = codes.astype(np.float64), AI_KNEE / AI_SCALE
    return np.where(c < AI_KNEE, c / AI_SCALE, knee * np.exp((c - AI_KNEE) / AI_LOG_STEPS))


AI_VALUES = _values(np.arange(65536)).astype(np.float32)  # each format-2 code's value in sigma, rising with the code
AI_MAX = float(AI_VALUES[-1])


def encode_diff(diff: np.ndarray) -> np.ndarray:
    """The difference map as the 8-bit image a PNG stores exactly (its values are whole numbers 0-255)."""
    return np.asarray(np.clip(np.rint(diff), 0, 255), dtype=np.uint8)


def encode_ai(amap: np.ndarray, pixel_threshold: float | None = None) -> np.ndarray:
    """The AI score map as format-2 codes, each the nearest, worked out in float64; NaN and values below 0 store as 0,
    values from AI_MAX up as the top code. With the AI model's `pixel_threshold` (above 0, at most AI_MAX), a pixel the
    rounding took across it is taken back one code, so the stored map marks the very pixels of an AI defect the live
    one did (`Inspector.judge`), each still within one step of its value; a threshold outside that range keeps the
    nearest codes."""
    codes = np.multiply(amap, AI_SCALE, dtype=np.float64)  # exact for a float32 map
    high = codes > AI_KNEE
    codes[high] = AI_KNEE + AI_LOG_STEPS * np.log(codes[high] / AI_KNEE)
    np.rint(codes, out=codes)
    np.fmax(codes, 0, out=codes)  # NaN and values below 0 store as 0
    out: np.ndarray = np.fmin(codes, 65535).astype(np.uint16)
    above = None if pixel_threshold is None else AI_VALUES >= pixel_threshold  # each code as the engine compares it
    if above is not None and above[-1] and not above[0]:  # the threshold lies above code 0 and at most AI_MAX
        first, live = int(np.argmax(above)), amap >= pixel_threshold  # the lowest code read as on or above it
        out += live & (out < first)  # rounding took the pixel below the threshold: up one code
        out -= ~live & (out >= first)  # or up to it: down one code
    return out


def decode_ai(img: np.ndarray) -> np.ndarray:
    """Format-2 codes back to sigma, as float32: one table lookup per pixel."""
    return AI_VALUES[np.asarray(img, dtype=np.uint16)]


def save_maps(res: InspectionResult, base: Path, *, pixel_threshold: float | None) -> tuple[str | None, str | None]:
    """Write the maps `res` holds as `<base>_diff.png` and `<base>_ai2.png` (base: the overlay path, no suffix); the AI
    map on the sides of `pixel_threshold`, that of the AI model that made it (None only without one)."""
    diff_path = ai_path = None
    if res.compare is not None and res.compare.diff_map is not None:
        diff_path = base.with_name(base.name + "_diff.png")
        save_image(diff_path, encode_diff(res.compare.diff_map))
    if res.anomaly_map is not None:
        ai_path = base.with_name(base.name + AI_FILE)
        save_image(ai_path, encode_ai(res.anomaly_map, pixel_threshold))
    return (str(diff_path) if diff_path else None, str(ai_path) if ai_path else None)


def read_map(path: str | Path) -> np.ndarray | None:
    """A stored map as written, 8- or 16-bit, from a path that may hold non-ASCII characters (Windows); None when its
    file is gone (the sweep deleted it, or it went as it was read). A file that is there but cannot be read (locked by
    another program, no permission) or decoded (damaged) raises AOI-CMP-003, naming it."""
    try:
        data = Path(path).read_bytes()
    except FileNotFoundError:
        return None
    except OSError as e:
        raise AoiError("AOI-CMP-003", detail=str(e), file=Path(path).name, reason=e.strerror or type(e).__name__) from e
    try:
        img = cv2.imdecode(np.frombuffer(data, dtype=np.uint8), cv2.IMREAD_UNCHANGED)
    except cv2.error:  # a header claiming more pixels than OpenCV decodes
        img = None
    if img is None:
        raise AoiError("AOI-CMP-003", file=Path(path).name, reason=QT_TRANSLATE_NOOP("Errors", "the file is damaged"))
    return img


def load_maps(res: InspectionResult, diff_path: str | None, ai_path: str | None) -> InspectionResult:
    """Put the stored maps back on a result; a map never stored, or whose file is gone, stays None, and one that cannot
    be read raises AOI-CMP-003 (`read_map`). The AI map decodes on a thread of its own while the difference map decodes
    here (decoding a PNG releases the GIL), so at 5 MP reading both takes about as long as the slower one."""
    with ThreadPoolExecutor(max_workers=1) as pool:
        ai = pool.submit(read_map, ai_path) if ai_path else None
        if diff_path and res.compare is not None and (diff := read_map(diff_path)) is not None:
            res.compare.diff_map = np.asarray(diff, dtype=np.float32)  # the compare step's float32
        if ai is not None and ai_path is not None and (codes := ai.result()) is not None:
            v1 = ai_path.endswith(AI_FILE_V1)
            res.anomaly_map = np.asarray(codes, dtype=np.float32) / np.float32(AI_SCALE) if v1 else decode_ai(codes)
    return res
