"""The Golden board a training run builds: the per-pixel median of its aligned OK images (REQ-TRN-007), worked out a
band of rows at a time, so a run holds that band of every image rather than every image whole. No Qt."""

from __future__ import annotations

import json
import struct
import zlib
from collections.abc import Callable
from typing import Any

import cv2
import numpy as np

from . import run_progress

BAND_BYTES = 1 << 30  # the band of every image held at once: 1 GiB, whatever the images' number and size
# the rows of every image one step of a band's median works out at once: 64 MiB, about 0.85 s on a 4-core cloud VM for
# 50 images at 20 MP, where a whole band of 1 GiB took 15 s, more than the 10 s between a run's reports (REQ-TRN-008)
STEP_BYTES = 1 << 26


class Median:
    """`np.median(np.stack(images), axis=0).astype(np.uint8)` of `count` colour images of `shape` (height, width), to
    the bit, worked out band by band: the caller adds every image for the first band, then reads them again and adds
    every image for each later band, until `done`. Each band of every image takes at most `budget` bytes, and each
    step of its median `step` bytes."""

    def __init__(self, count: int, shape: tuple[int, int], budget: int = BAND_BYTES, step: int = STEP_BYTES) -> None:
        height, width = shape
        rows = max(1, min(height, budget // max(1, count * width * 3)))
        self.bands = [slice(top, min(top + rows, height)) for top in range(0, height, rows)]
        self.step_rows = max(1, min(rows, step // max(1, count * width * 3)))
        self.steps = sum(-(-(b.stop - b.start) // self.step_rows) for b in self.bands)  # of every band's median
        self.board = np.zeros((height, width, 3), np.uint8)
        self._count, self._band, self._added = count, 0, 0
        self._stack = np.empty((count, rows, width, 3), np.uint8)

    @property
    def done(self) -> bool:
        return self._band == len(self.bands)

    def add(self, image: np.ndarray, stepped: Callable[[], None] | None = None) -> None:
        """Take the band in hand of the next image; the last image of a band works the band out, `step_rows` rows at a
        time, calling `stepped()` after each step, so a training run reports, and can stop, between them."""
        rows = self.bands[self._band]
        self._stack[self._added, : rows.stop - rows.start] = image[rows]
        self._added += 1
        if self._added == self._count:
            for top in range(rows.start, rows.stop, self.step_rows):
                self._work(rows.start, top, min(top + self.step_rows, rows.stop))
                if stepped is not None:
                    stepped()
            self._band, self._added = self._band + 1, 0

    def _work(self, start: int, top: int, end: int) -> None:
        """The median of rows `top` to `end` of the board, from the band in hand, which starts at row `start`."""
        part = self._stack[:, top - start : end - start]
        self.board[top:end] = np.median(part, axis=0, overwrite_input=True).astype(np.uint8)

    def probe(self) -> float:
        """The seconds one step of the median takes, timed on noise before any image is added (REQ-TRN-008)."""
        rows, rng = self.step_rows, np.random.default_rng(0)
        self._stack[:, :rows] = rng.integers(0, 256, (self._count, rows, self.board.shape[1], 3), dtype=np.uint8)
        started = run_progress.clock()
        self._work(0, 0, rows)
        return run_progress.clock() - started


TOLERANCE_SIGMAS = 3.0  # a pixel's tolerance: its mean difference on good boards plus this many of its deviations
TOLERANCE_CHUNK = b"aoTl"  # a private PNG chunk, safe to copy: the Golden board file carries its own tolerance
TOLERANCE_FORMAT = 1
PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"


class Spread:
    """How far each pixel of good boards lies from the Golden board (#461), from the comparison's own difference map,
    one good board added at a time, so a run holds five maps and never the boards.

    The comparison passes over a pixel that differs no more than `tolerance()` there. A date code, a joint's shine or
    an edge that sits a pixel off differ from board to board on good boards; a place that never differs keeps a
    tolerance near 0, and every place keeps its full sensitivity to a difference beyond it. The tolerance is the
    larger of the mean plus TOLERANCE_SIGMAS deviations and the second-highest difference a good board showed: the
    highest alone would let one board labelled good by mistake blind the comparison at its defect for good."""

    def __init__(self, shape: tuple[int, int]) -> None:
        self.count = 0
        self._sum = np.zeros(shape, np.float64)
        self._squares = np.zeros(shape, np.float64)
        self._top = np.zeros(shape, np.uint8)
        self._second = np.zeros(shape, np.uint8)

    def add(self, difference: np.ndarray) -> None:
        d = difference.astype(np.float64)
        self._sum += d
        self._squares += d * d
        seen = np.clip(difference, 0, 255).astype(np.uint8)
        self._second = np.maximum(self._second, np.minimum(self._top, seen))
        self._top = np.maximum(self._top, seen)
        self.count += 1

    def tolerance(self) -> np.ndarray:
        """The tolerance map, 8-bit, rounded up and spread by a pixel each way."""
        mean = self._sum / max(1, self.count)
        deviation = np.sqrt(np.maximum(self._squares / max(1, self.count) - mean * mean, 0.0))
        tol = np.clip(np.ceil(mean + TOLERANCE_SIGMAS * deviation), 0, 255).astype(np.uint8)
        out: np.ndarray = cv2.dilate(np.maximum(tol, self._second), np.ones((3, 3), np.uint8))
        return out


def _chunks(png: bytes) -> list[tuple[bytes, int, int]]:
    """Each chunk of a PNG as (type, start of its length field, end of its CRC); [] for bytes that are no PNG."""
    out, at = [], len(PNG_SIGNATURE)
    if not png.startswith(PNG_SIGNATURE):
        return []
    while at + 12 <= len(png):
        (size,) = struct.unpack(">I", png[at : at + 4])
        end = at + 12 + size
        if end > len(png):
            return []
        out.append((png[at + 4 : at + 8], at, end))
        at = end
    return out


def embed(png: bytes, tolerance: np.ndarray, learned: dict[str, Any]) -> bytes:
    """`png`, a Golden board's file, with `tolerance` and what was `learned` with it in a chunk before IEND. Viewers
    and decoders pass over the chunk; the file's SHA-256, which every result names, covers it."""
    chunks = _chunks(png)
    if not chunks or chunks[-1][0] != b"IEND":
        raise ValueError("not a PNG file")
    head = json.dumps({"format": TOLERANCE_FORMAT, "shape": list(tolerance.shape), **learned}).encode("utf-8")
    body = struct.pack(">I", len(head)) + head + zlib.compress(np.ascontiguousarray(tolerance).tobytes(), 6)
    crc = zlib.crc32(TOLERANCE_CHUNK + body) & 0xFFFFFFFF
    chunk = struct.pack(">I", len(body)) + TOLERANCE_CHUNK + body + struct.pack(">I", crc)
    kept = b"".join(png[a:b] for kind, a, b in chunks[:-1] if kind != TOLERANCE_CHUNK)
    return PNG_SIGNATURE + kept + chunk + png[chunks[-1][1] : chunks[-1][2]]


def extract(png: bytes, shape: tuple[int, int]) -> tuple[np.ndarray, dict[str, Any]] | None:
    """The tolerance map a Golden board file carries, and what was learned with it; None for a file with none, or one
    whose chunk is damaged or is not for an image of `shape` (height, width): the board is then compared without."""
    for kind, a, b in _chunks(png):
        if kind != TOLERANCE_CHUNK:
            continue
        body, crc = png[a + 8 : b - 4], png[b - 4 : b]
        if struct.pack(">I", zlib.crc32(TOLERANCE_CHUNK + body) & 0xFFFFFFFF) != crc or len(body) < 4:
            return None
        (n,) = struct.unpack(">I", body[:4])
        try:
            learned = json.loads(body[4 : 4 + n].decode("utf-8"))
            raw = zlib.decompress(body[4 + n :])
        except (ValueError, zlib.error):
            return None
        if not isinstance(learned, dict) or learned.get("format") != TOLERANCE_FORMAT:
            return None
        if learned.get("shape") != list(shape) or len(raw) != shape[0] * shape[1]:
            return None
        return np.frombuffer(raw, np.uint8).reshape(shape).copy(), learned
    return None
