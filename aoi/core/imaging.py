"""Image I/O and registration helpers (OpenCV)."""

from __future__ import annotations

import re
import struct
from pathlib import Path
from typing import Any

import cv2
import numpy as np

from ..data import atomic
from ..errors import AoiError

IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".bmp", ".tif", ".tiff"}
# Limits an image must stay within to be decoded (REQ-INSP-001), at the register's proposed values; a station's own
# values live in Settings and reach here through AppContext.load_image.
MAX_MEGAPIXELS = 50
MAX_MEGABYTES = 200
MAX_SIDE = 1 << 20  # a side longer than this is beyond the decoder (OpenCV's CV_IO_MAX_IMAGE_WIDTH and _HEIGHT)
BMP_HEADER_SIZES = {12, 16, 40, 52, 56, 64, 108, 124}  # BITMAPCOREHEADER to BITMAPV5HEADER: how a bitmap is known
JPEG_FRAME_MARKERS = {0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF}
JPEG_BARE_MARKERS = {0x00, 0x01, 0xD8, *range(0xD0, 0xD8)}  # no length field follows: a stuffed byte, TEM, SOI, RSTn
JPEG_MAX_MARKERS = 65536  # more markers than any camera writes before the frame: past it the walk gives up
JPEG_FILL = re.compile(rb"\xff+")
TIFF_INT_TYPES = {1: "B", 3: "H", 4: "I", 6: "b", 8: "h", 9: "i", 16: "Q", 17: "q"}  # BYTE to SLONG8: a size's types


def image_header(data: bytes) -> tuple[str, int, int] | None:
    """(format, width, height) of a PNG, JPEG, BMP or TIFF file read from its bytes, never from its name; None for
    anything else. Only the header is read, so a file is measured before any pixel is decoded. Wherever a file can be
    read in two ways the readers follow the decoders (libjpeg, libtiff, OpenCV's bitmap reader), so no file measures
    small here and decodes large; a recognised format whose size still cannot be read gives width and height 0, and
    `load_image` refuses it rather than hand it to the decoder."""
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        if len(data) < 24 or data[12:16] != b"IHDR":
            return "PNG", 0, 0
        w, h = struct.unpack(">II", data[16:24])
        return "PNG", int(w), int(h)
    if data[:2] == b"BM" and len(data) >= 18 and (dib := struct.unpack("<I", data[14:18])[0]) in BMP_HEADER_SIZES:
        if len(data) < 26:
            return "BMP", 0, 0
        if dib == 12:  # the 12-byte OS/2 header holds 16-bit sizes
            w, h = struct.unpack("<HH", data[18:22])
            return "BMP", int(w), int(h)
        w, h = struct.unpack("<ii", data[18:26])
        return "BMP", int(w), abs(int(h))  # a negative height means the rows run top-down
    if data[:3] == b"\xff\xd8\xff":
        return _jpeg_header(data)
    if data[:4] in (b"II*\x00", b"MM\x00*", b"II+\x00", b"MM\x00+"):
        return _tiff_header(data)
    return None


def _jpeg_header(data: bytes) -> tuple[str, int, int]:
    """Walk the segments to the start-of-frame marker, which holds the size; (JPEG, 0, 0) when none is found. Bytes
    between segments that belong to no marker are skipped, as libjpeg skips them ("extraneous bytes before marker"),
    so a stray byte cannot hide the frame from this reader while the decoder still finds it."""
    i = 2
    for _ in range(JPEG_MAX_MARKERS):
        i = data.find(b"\xff", i)
        if i < 0:
            break
        fill = JPEG_FILL.match(data, i)
        i = fill.end() - 1 if fill else i  # fill bytes: the marker byte follows the last 0xFF
        if i + 2 > len(data):
            break
        marker = data[i + 1]
        if marker in JPEG_FRAME_MARKERS:
            if i + 9 > len(data):
                break
            h, w = struct.unpack(">HH", data[i + 5 : i + 9])
            return "JPEG", int(w), int(h)
        if marker in (0xD9, 0xDA):  # end of image, or the scan data: no frame came before it
            break
        if marker in JPEG_BARE_MARKERS:
            i += 2
        elif i + 4 <= len(data):
            i += 2 + struct.unpack(">H", data[i + 2 : i + 4])[0]
        else:
            break
    return "JPEG", 0, 0


def _tiff_header(data: bytes) -> tuple[str, int, int]:
    """ImageWidth (tag 256) and ImageLength (257) from the first directory of a classic or a BigTIFF file; the directory
    may sit anywhere in the file. (TIFF, 0, 0) when it or either tag cannot be read. A size tag counts when it holds one
    value of an integer type, as libtiff reads it; a value of 0 or less is no size."""
    order = "<" if data[:2] == b"II" else ">"
    big = data[2:4] in (b"+\x00", b"\x00+")  # BigTIFF: 8-byte offsets and counts, 20-byte entries
    head, count_fmt, values_fmt, entry_len, value_at = (16, "Q", "Q", 20, 12) if big else (8, "H", "I", 12, 8)
    if len(data) < head:
        return "TIFF", 0, 0
    (offset,) = struct.unpack(order + "Q", data[8:16]) if big else struct.unpack(order + "I", data[4:8])
    count_len = struct.calcsize(count_fmt)
    if offset + count_len > len(data):
        return "TIFF", 0, 0
    (count,) = struct.unpack(order + count_fmt, data[offset : offset + count_len])
    size = {256: 0, 257: 0}
    for n in range(min(int(count), 65535)):  # a classic count's maximum; libtiff refuses a directory over 4,096 entries
        at = offset + count_len + entry_len * n
        entry = data[at : at + entry_len]
        if len(entry) < entry_len:
            break
        tag, kind = struct.unpack(order + "HH", entry[:4])
        fmt = TIFF_INT_TYPES.get(kind)
        if tag not in size or fmt is None or (kind in (16, 17) and not big):  # LONG8 and SLONG8 exist only in BigTIFF
            continue
        (values,) = struct.unpack(order + values_fmt, entry[4:value_at])
        if values != 1:
            continue
        (value,) = struct.unpack(order + fmt, entry[value_at : value_at + struct.calcsize(fmt)])
        if value > 0:
            size[tag] = int(value)
    return "TIFF", size[256], size[257]


def load_image(
    path: str | Path, max_megapixels: float = MAX_MEGAPIXELS, max_megabytes: float = MAX_MEGABYTES
) -> np.ndarray:
    """Read as BGR uint8 after checking the file (REQ-INSP-001): it must hold a PNG, JPEG, BMP or TIFF image by its
    content, whatever its name, and stay within `max_megabytes` on disk, `max_megapixels` by its header and `MAX_SIDE`
    on either side; all three are checked before a pixel is decoded, so a huge or forged file costs nothing, and a
    recognised format whose header gives no size is refused, never decoded. Decoding the bytes with `imdecode` keeps
    non-ASCII (Korean) Windows paths working."""
    p = Path(path)
    try:
        size = p.stat().st_size
        if size > max_megabytes * 1e6:
            found = f"{size / 1e6:.1f} MB ({size:,} bytes)"
            raise AoiError("AOI-INSP-005", path=str(p), size=found, limit=f"{max_megabytes:g} MB")
        data = p.read_bytes()
    except OSError as e:  # missing file, folder, or no permission
        raise AoiError("AOI-INSP-001", detail=str(e), path=str(p)) from e
    header = image_header(data)
    if header is None:
        raise AoiError("AOI-INSP-004", path=str(p))
    kind, w, h = header
    if w <= 0 or h <= 0:
        raise AoiError("AOI-INSP-006", path=str(p), kind=kind, reason="its header holds no image size")
    if w * h > max_megapixels * 1e6:
        found = f"{w * h / 1e6:.2f} MP ({w} × {h})"
        raise AoiError("AOI-INSP-005", path=str(p), size=found, limit=f"{max_megapixels:g} MP")
    if max(w, h) > MAX_SIDE:
        raise AoiError("AOI-INSP-007", path=str(p), width=w, height=h, limit=f"{MAX_SIDE:,}")
    try:
        img = cv2.imdecode(np.frombuffer(data, dtype=np.uint8), cv2.IMREAD_COLOR)
    except cv2.error as e:  # the decoder's own limits, which hold whatever the settings say
        raise AoiError("AOI-INSP-006", detail=str(e), path=str(p), kind=kind, reason="the decoder refused it") from e
    if img is None:
        reason = "it is cut short, damaged, or a variant this app does not read"
        raise AoiError("AOI-INSP-006", path=str(p), kind=kind, reason=reason)
    return img


def save_image(path: str | Path, img: np.ndarray) -> None:
    ext = Path(path).suffix or ".png"
    ok, buf = cv2.imencode(ext, img)
    if not ok:
        raise AoiError("AOI-INSP-002", path=str(path))
    atomic.write_bytes(path, buf.tobytes())  # whole file or nothing, and non-ASCII Windows paths work


def list_images(folder: str | Path) -> list[Path]:
    return sorted(p for p in Path(folder).rglob("*") if p.suffix.lower() in IMAGE_EXTS)


def align_to_reference(img: np.ndarray, ref: np.ndarray, max_features: int = 4000) -> tuple[np.ndarray, dict[str, Any]]:
    """Register `img` onto `ref` with ORB features + RANSAC homography.

    Boards are never placed at exactly the same spot, so every pixel comparison
    (golden-sample diff, ROI checks) happens after this step. Falls back to a plain
    resize when not enough features match; `info["aligned"]` tells the UI which.
    """
    h, w = ref.shape[:2]
    info: dict[str, Any] = {"aligned": False, "inliers": 0, "method": "resize"}
    g1 = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    g2 = cv2.cvtColor(ref, cv2.COLOR_BGR2GRAY)
    orb = cv2.ORB.create(max_features)
    k1, d1 = orb.detectAndCompute(g1, None)
    k2, d2 = orb.detectAndCompute(g2, None)
    if d1 is not None and d2 is not None and len(k1) >= 10 and len(k2) >= 10:
        matcher = cv2.BFMatcher(cv2.NORM_HAMMING, crossCheck=True)
        matches = sorted(matcher.match(d1, d2), key=lambda m: m.distance)[:500]
        if len(matches) >= 10:
            src = np.array([k1[m.queryIdx].pt for m in matches], dtype=np.float32).reshape(-1, 1, 2)
            dst = np.array([k2[m.trainIdx].pt for m in matches], dtype=np.float32).reshape(-1, 1, 2)
            H, mask = cv2.findHomography(src, dst, cv2.RANSAC, 4.0)
            if H is not None and mask is not None and int(mask.sum()) >= 12:
                warped = cv2.warpPerspective(img, H, (w, h), borderMode=cv2.BORDER_REPLICATE)
                info.update(aligned=True, inliers=int(mask.sum()), method="orb-homography")
                return warped, info
    return cv2.resize(img, (w, h), interpolation=cv2.INTER_AREA), info


def heatmap(values: np.ndarray, vmax: float | None = None) -> np.ndarray:
    """Float map -> BGR color heatmap (for the Compare page and overlays)."""
    v = values.astype(np.float32)
    vmax = vmax if vmax and vmax > 0 else float(v.max() or 1.0)
    u8 = np.clip(v / vmax * 255.0, 0, 255).astype(np.uint8)
    colored: np.ndarray = cv2.applyColorMap(u8, cv2.COLORMAP_JET)
    return colored


def blend(img: np.ndarray, overlay: np.ndarray, alpha: float = 0.45) -> np.ndarray:
    if overlay.shape[:2] != img.shape[:2]:
        overlay = cv2.resize(overlay, (img.shape[1], img.shape[0]))
    blended: np.ndarray = cv2.addWeighted(img, 1 - alpha, overlay, alpha, 0)
    return blended


def heat_overlay(img: np.ndarray, values: np.ndarray, vmax: float) -> np.ndarray:
    """Colour only where `values` is high, so the board stays readable underneath."""
    if values.shape[:2] != img.shape[:2]:
        values = cv2.resize(values, (img.shape[1], img.shape[0]))
    a = np.clip(values.astype(np.float32) / max(vmax, 1e-6), 0, 1)[..., None] * 0.8
    shaded: np.ndarray = (img * (1 - a) + heatmap(values, vmax) * a).astype(np.uint8)
    return shaded
