"""Image I/O and registration helpers (OpenCV)."""

from __future__ import annotations

import hashlib
import re
import struct
from pathlib import Path
from typing import Any

import cv2
import numpy as np

from ..data import atomic
from ..errors import QT_TRANSLATE_NOOP, AoiError, Phrase

IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".bmp", ".tif", ".tiff"}
# Limits an image must stay within to be decoded (REQ-INSP-001), at the register's proposed values; a station's own
# values live in Settings and reach here through AppContext.load_image.
MAX_MEGAPIXELS = 50
MAX_MEGABYTES = 200
MAX_SIDE = 1 << 20  # a side longer than this is beyond the decoder (OpenCV's CV_IO_MAX_IMAGE_WIDTH and _HEIGHT)
BMP_HEADER_SIZES = {12, 16, 40, 52, 56, 64, 108, 124}  # BITMAPCOREHEADER to BITMAPV5HEADER: how a bitmap is known
JPEG_FRAME_MARKERS = {0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF}
JPEG_BARE_MARKERS = {0x00, 0x01, 0xD8, *range(0xD0, 0xD8)}  # no length field follows: a stuffed byte, TEM, SOI, RSTn
JPEG_MAX_MARKERS = 65536  # more markers than any camera writes: past it a walk gives up
JPEG_FILL = re.compile(rb"\xff+")
# libjpeg's progression writes 10 scans for a colour image, and its decoder reads every scan a file holds; libtiff stops
# a JPEG inside a TIFF at the same 100 scans by default (LIBTIFF_JPEG_MAX_ALLOWED_SCAN_NUMBER)
JPEG_MAX_SCANS = 100
# The markers libjpeg acts on in `_jpeg_scans`: EOI (D9) and SOS (DA), and the segments it reads by their length and
# goes on from (SOF0-3 and 9-11, DHT, DAC, DQT, DNL, DRI, APPn, COM). Any other pair is stuffing, fill, a restart or a
# marker libjpeg fails at or searches past, so the walk searches past it too and skips no byte libjpeg reads.
JPEG_WALK = re.compile(rb"\xff([\xc0-\xc4\xc9-\xcc\xd9-\xdd\xe0-\xef\xfe])")
TIFF_INT_TYPES = {1: "B", 3: "H", 4: "I", 6: "b", 8: "h", 9: "i", 16: "Q", 17: "q"}  # BYTE to SLONG8: a size's types
TIFF_TAGS = (256, 257, 278, 322, 323)  # ImageWidth, ImageLength, RowsPerStrip, TileWidth, TileLength
TIFF_TWICE = -1  # what `_tiff_tags` gives a tag listed twice: no single value
TIFF_WHOLE_SIDE = (0, 0xFFFFFFFF)  # a RowsPerStrip of 0, or the TIFF default 4,294,967,295, reads as the image height
TIFF_BLOCK_PIXELS = 1024 * 1024  # a tile or strip may always hold this many pixels, however small the image


def image_header(data: bytes) -> tuple[str, int, int] | None:
    """(format, width, height) of a PNG, JPEG, BMP or TIFF file read from its bytes, never from its name; None for
    anything else. Only the header is read, so a file is measured before any pixel is decoded. Wherever a file can be
    read in two ways the readers follow the decoders (libjpeg, libtiff, OpenCV's bitmap reader), so the size measured
    here is the size of the image the decoder returns; it bounds the image, not the decoder's work, which `load_image`
    bounds by a JPEG's scans and a TIFF's tiles and strips (#242). A recognised format whose size still cannot be read
    gives width and height 0, and `load_image` refuses it rather than hand it to the decoder."""
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
    """ImageWidth (tag 256) and ImageLength (257) from the first directory, as `_tiff_tags` reads them; (TIFF, 0, 0)
    when either cannot be read. A value of 0 or less is no size, and so is a size tag given twice: libtiff reads the
    first entry and ignores the rest, so a file listing 8000 then 10 would measure small and decode large wherever the
    last counted (#169)."""
    tags = _tiff_tags(data)
    if TIFF_TWICE in (tags.get(256), tags.get(257)):
        return "TIFF", 0, 0
    return "TIFF", tags.get(256, 0), tags.get(257, 0)


def _tiff_tags(data: bytes) -> dict[int, int]:
    """The TIFF_TAGS the first directory of a classic or a BigTIFF file holds, by tag; the directory may sit anywhere in
    the file. A tag counts when it holds one value of an integer type, BYTE to SLONG8, as libtiff's TIFFReadDirEntryLong
    reads it: in a classic file the 8 bytes of a LONG8 or SLONG8 sit at the offset its entry holds (#242 review), and a
    value below 0 reads as 0. A tag listed twice gives TIFF_TWICE whatever either entry holds, since libtiff reads the
    first."""
    order = "<" if data[:2] == b"II" else ">"
    big = data[2:4] in (b"+\x00", b"\x00+")  # BigTIFF: 8-byte offsets and counts, 20-byte entries
    head, count_fmt, values_fmt, entry_len, value_at = (16, "Q", "Q", 20, 12) if big else (8, "H", "I", 12, 8)
    if len(data) < head:
        return {}
    (offset,) = struct.unpack(order + "Q", data[8:16]) if big else struct.unpack(order + "I", data[4:8])
    count_len = struct.calcsize(count_fmt)
    if offset + count_len > len(data):
        return {}
    (count,) = struct.unpack(order + count_fmt, data[offset : offset + count_len])
    tags, seen = dict[int, int](), set[int]()
    for n in range(min(int(count), 65535)):  # a classic count's maximum; libtiff refuses a directory over 4,096 entries
        at = offset + count_len + entry_len * n
        entry = data[at : at + entry_len]
        if len(entry) < entry_len:
            break
        tag, kind = struct.unpack(order + "HH", entry[:4])
        if tag in TIFF_TAGS and tag in seen:  # whatever either entry holds: no single value, so the file is refused
            tags[tag] = TIFF_TWICE
            continue
        seen.add(tag)
        fmt = TIFF_INT_TYPES.get(kind)
        if tag not in TIFF_TAGS or fmt is None:
            continue
        (values,) = struct.unpack(order + values_fmt, entry[4:value_at])
        field = entry[value_at:]
        if kind in (16, 17) and not big:  # 8 bytes fit no classic entry: libtiff reads them where the entry points
            (where,) = struct.unpack(order + "I", field)
            field = data[where : where + 8]  # short past the end of the file, where libtiff refuses the directory
        if values == 1 and len(field) >= struct.calcsize(fmt):
            (value,) = struct.unpack(order + fmt, field[: struct.calcsize(fmt)])
            tags[tag] = max(int(value), 0)
    return tags


def _jpeg_scans(data: bytes) -> int:
    """The scans libjpeg decodes in a JPEG, or more, never fewer (#242 review). libjpeg reads from marker to marker: it
    reads a segment by its length, starts a scan at each SOS, searches past a scan's coded data, stuffed and fill bytes,
    restarts and stray bytes for the next marker, and stops at the first EOI it meets. So the scans of an EXIF thumbnail
    (inside a segment) or the bytes after the image (a phone's video) are no scans of its. Past JPEG_MAX_MARKERS
    markers the walk stops and every FF DA pair left counts as a scan, so the count never exceeds the file's FF DA
    pairs either."""
    scans, i = 0, 2
    for _ in range(JPEG_MAX_MARKERS):
        found = JPEG_WALK.search(data, i)
        if found is None or found[1] == b"\xd9":
            return scans
        scans += found[1] == b"\xda"
        i = found.end() + int.from_bytes(data[found.end() : found.end() + 2], "big")  # the length counts its 2 bytes
    return scans + data.count(b"\xff\xda", i)


def _decoder_work(data: bytes, kind: str, width: int, height: int) -> Phrase | None:
    """Why decoding the file would cost far more than its `width` × `height` image, or None (#242). libjpeg decodes
    every scan of a progressive JPEG, each a pass over the image, and a file can repeat a scan thousands of times at 31
    bytes each: a JPEG with more than JPEG_MAX_SCANS is refused, counted by `_jpeg_scans` once the file holds more FF DA
    pairs than that (the walk can only lower the count, so a file with fewer is never walked). OpenCV allocates its
    TIFF buffer by one tile or strip, up to 1 GiB, whatever the image (libtiff fills a whole tile, but of a strip only
    the image's rows): a TIFF is refused when its tile or strip, TileWidth (or the width) by TileLength (or
    RowsPerStrip, or the height), holds more pixels than the larger of TIFF_BLOCK_PIXELS and the image with each side
    rounded up to a multiple of 16, as TIFF 6.0 makes tile sides."""
    if kind == "JPEG" and data.count(b"\xff\xda") > JPEG_MAX_SCANS and (scans := _jpeg_scans(data)) > JPEG_MAX_SCANS:
        reason = QT_TRANSLATE_NOOP("Errors", "it holds {scans} scans, more than the {most} this app decodes")
        return reason.fill(scans=f"{scans:,}", most=JPEG_MAX_SCANS)
    if kind != "TIFF":
        return None
    tags = _tiff_tags(data)
    if TIFF_TWICE in (tags.get(t) for t in TIFF_TAGS[2:]):
        return QT_TRANSLATE_NOOP("Errors", "it gives the size of its tiles or strips twice")
    rows = tags.get(278, 0)
    rows = height if rows in TIFF_WHOLE_SIDE else rows
    cols, rows = tags.get(322) or width, tags.get(323) or rows
    if cols * rows <= max(TIFF_BLOCK_PIXELS, -(-width // 16) * 16 * (-(-height // 16) * 16)):
        return None
    if 322 in tags or 323 in tags:
        reason = QT_TRANSLATE_NOOP(
            "Errors", "its tiles are {cols} × {rows} px, more than its {width} × {height} px image needs"
        )
    else:
        reason = QT_TRANSLATE_NOOP(
            "Errors", "its strips are {cols} × {rows} px, more than its {width} × {height} px image needs"
        )
    return reason.fill(cols=cols, rows=rows, width=width, height=height)


def load_image(
    path: str | Path, max_megapixels: float = MAX_MEGAPIXELS, max_megabytes: float = MAX_MEGABYTES
) -> np.ndarray:
    """Read as BGR uint8 after checking the file (REQ-INSP-001): it must hold a PNG, JPEG, BMP or TIFF image by its
    content, whatever its name, and stay within `max_megabytes` on disk, `max_megapixels` by its header and `MAX_SIDE`
    on either side, and a JPEG within JPEG_MAX_SCANS scans and a TIFF's tiles or strips within its image's size, so the
    decoder's work stays near the image's (#242). All of these are checked before a pixel is decoded, and a recognised
    format whose header gives no size is refused, never decoded. Decoding the bytes with `imdecode` keeps non-ASCII
    (Korean) Windows paths working."""
    return _read_image(Path(path), max_megapixels, max_megabytes)[0]


def load_image_sha256(
    path: str | Path, max_megapixels: float = MAX_MEGAPIXELS, max_megabytes: float = MAX_MEGABYTES
) -> tuple[np.ndarray, str]:
    """`load_image`, with the SHA-256 of the very bytes decoded, in hex: a record names the golden board it was judged
    against by its content, read once, so no second read of the file can race a writer (REQ-CMP-003)."""
    img, data = _read_image(Path(path), max_megapixels, max_megabytes)
    return img, hashlib.sha256(data).hexdigest()


def _read_image(p: Path, max_megapixels: float, max_megabytes: float) -> tuple[np.ndarray, bytes]:
    """The image and the bytes it was decoded from, after `load_image`'s checks."""
    try:
        size = p.stat().st_size
        if size > max_megabytes * 1e6:
            in_bytes = QT_TRANSLATE_NOOP("Errors", "{megabytes} MB ({count} bytes)")
            found = in_bytes.fill(megabytes=f"{size / 1e6:.1f}", count=f"{size:,}")
            raise AoiError("AOI-INSP-005", path=str(p), size=found, limit=f"{max_megabytes:g} MB")
        data = p.read_bytes()
    except OSError as e:  # missing file, folder, or no permission
        raise AoiError("AOI-INSP-001", detail=str(e), path=str(p)) from e
    header = image_header(data)
    if header is None:
        raise AoiError("AOI-INSP-004", path=str(p))
    kind, w, h = header
    if w <= 0 or h <= 0:
        raise AoiError(
            "AOI-INSP-006", path=str(p), kind=kind, reason=QT_TRANSLATE_NOOP("Errors", "its header holds no image size")
        )
    if w * h > max_megapixels * 1e6:
        pixels = f"{w * h / 1e6:.2f} MP ({w} × {h})"
        raise AoiError("AOI-INSP-005", path=str(p), size=pixels, limit=f"{max_megapixels:g} MP")
    if max(w, h) > MAX_SIDE:
        raise AoiError("AOI-INSP-007", path=str(p), width=w, height=h, limit=f"{MAX_SIDE:,}")
    if (costly := _decoder_work(data, kind, w, h)) is not None:
        raise AoiError("AOI-INSP-006", path=str(p), kind=kind, reason=costly)
    try:
        img = cv2.imdecode(np.frombuffer(data, dtype=np.uint8), cv2.IMREAD_COLOR)
    except cv2.error as e:  # the decoder's own limits, which hold whatever the settings say
        raise AoiError(
            "AOI-INSP-006",
            detail=str(e),
            path=str(p),
            kind=kind,
            reason=QT_TRANSLATE_NOOP("Errors", "the decoder refused it"),
        ) from e
    if img is None:
        reason = QT_TRANSLATE_NOOP("Errors", "it is cut short, damaged, or a variant this app does not read")
        raise AoiError("AOI-INSP-006", path=str(p), kind=kind, reason=reason)
    return img, data


def encode_image(path: str | Path, img: np.ndarray) -> bytes:
    """`img` in the image format `path`'s suffix names (PNG with none), before anything is written: AOI-INSP-002 for a
    suffix no format has."""
    ext = Path(path).suffix or ".png"
    try:
        ok, buf = cv2.imencode(ext, img)
    except cv2.error as e:  # OpenCV 5 raises for a suffix it cannot encode, such as "lot.txt" or "board_v1.2" (#195)
        raise AoiError("AOI-INSP-002", detail=str(e), path=str(path)) from e
    if not ok:
        raise AoiError("AOI-INSP-002", path=str(path))
    return buf.tobytes()


def save_image(path: str | Path, img: np.ndarray) -> None:
    atomic.write_bytes(path, encode_image(path, img))  # whole file or nothing, and non-ASCII Windows paths work


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


def blend(img: np.ndarray, overlay: np.ndarray, alpha: float = 0.45) -> np.ndarray:
    if overlay.shape[:2] != img.shape[:2]:
        overlay = cv2.resize(overlay, (img.shape[1], img.shape[0]))
    blended: np.ndarray = cv2.addWeighted(img, 1 - alpha, overlay, alpha, 0)
    return blended


def heat_overlay(img: np.ndarray, values: np.ndarray, vmax: float) -> np.ndarray:
    """Colour only where `values` is high, so the board stays readable underneath: the heat colour is blended in with
    a weight of 0.8 x value / vmax, at most 0.8, so `vmax` is the value shown in full colour (one at or below 0 counts
    as a tiny positive value: every positive value is in full colour); a map of another size is resized to the board's.
    OpenCV does the per-pixel blend, so a 5 MP view renders well inside the 300 ms of REQ-CMP-002."""
    if values.shape[:2] != img.shape[:2]:
        values = cv2.resize(values, (img.shape[1], img.shape[0]))
    weight = values.astype(np.float32) * np.float32(0.8 / max(vmax, 1e-6))
    np.clip(weight, 0.0, 0.8, out=weight)
    colours = cv2.applyColorMap(cv2.convertScaleAbs(weight, alpha=255 / 0.8), cv2.COLORMAP_JET)
    shaded: np.ndarray = cv2.blendLinear(img, colours, 1 - weight, weight)
    return shaded
