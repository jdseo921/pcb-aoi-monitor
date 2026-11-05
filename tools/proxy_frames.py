"""The ways the industry scenarios of tools/proxy_scenarios.py (#459) change a board's photo, each seeded: the camera's
drift over a shift, a board's placement on the conveyor, the same board shot again, the bad images that must never pass,
the variation a good board legitimately shows, and the board's next revision. A change that moves the board takes its
defect mask too, so a defect box is still judged against the right place. Nothing here reads a dataset.
"""

from __future__ import annotations

import math
import random
from collections.abc import Callable
from typing import Any

import cv2
import numpy as np

Image = np.ndarray
Mask = np.ndarray | None


# --- S2, S3, S7: the board moved, the camera drifting, the board shot again -------------------------------------------
def _warp(img: Image, mask: Mask, m: np.ndarray) -> tuple[Image, Mask]:
    size = (img.shape[1], img.shape[0])
    out = cv2.warpAffine(img, m, size, flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE)
    moved = None if mask is None else cv2.warpAffine(mask, m, size, flags=cv2.INTER_NEAREST, borderValue=0)
    return out, moved


def placed(img: Image, mask: Mask, angle: float, dx: float, dy: float) -> tuple[Image, Mask]:
    """The board rotated by `angle` degrees about the image's centre and moved by (dx, dy) px; the edge repeats into
    the border, as a camera sees more conveyor."""
    h, w = img.shape[:2]
    m = cv2.getRotationMatrix2D((w / 2, h / 2), angle, 1.0)
    m[:, 2] += (dx, dy)
    return _warp(img, mask, m)


def drift(i: int, n: int) -> dict[str, float]:
    """The camera at board `i` of `n` (S2), each change a smooth ramp from nothing to its full size at the shift's end:
    light 10 % down, colour 5 % warmer (red up, blue down), 15 px of creep, 0.5 degree, focus softening to a blur of
    sigma 1 px."""
    f = i / max(1, n - 1)
    return {"light": 1 - 0.10 * f, "warm": 0.05 * f, "dx": 15 * f, "angle": 0.5 * f, "blur": 1.0 * f}


def drifted(img: Image, mask: Mask, d: dict[str, float]) -> tuple[Image, Mask]:
    out, moved = placed(img, mask, d["angle"], d["dx"], 0.0)
    gains = np.array([1 - d["warm"], 1.0, 1 + d["warm"]]) * d["light"]  # BGR
    out = np.clip(np.rint(out.astype(np.float32) * gains), 0, 255).astype(np.uint8)
    if d["blur"] > 0.05:
        out = cv2.GaussianBlur(out, (0, 0), d["blur"])
    return out, moved


def placement(rng: random.Random, backwards_every: int = 200) -> dict[str, Any]:
    """A board's place on the conveyor (S3): up to ±5 degrees, up to 60 px each way, and 1 in `backwards_every`
    loaded backwards (180 degrees)."""
    back = rng.randrange(backwards_every) == 0
    return {"angle": rng.uniform(-5, 5) + (180 if back else 0), "dx": rng.uniform(-60, 60), "dy": rng.uniform(-60, 60)}


def reshot(img: Image, mask: Mask, rng: random.Random) -> tuple[Image, Mask]:
    """The same board photographed again (S7): a sub-pixel shift, sensor noise (sigma 2 levels) and light ±3 %."""
    out, moved = placed(img, mask, 0.0, rng.uniform(-0.5, 0.5), rng.uniform(-0.5, 0.5))
    noise = np.random.default_rng(rng.randrange(2**32)).normal(0, 2, out.shape)
    gain = rng.uniform(0.97, 1.03)
    return np.clip(np.rint(out.astype(np.float32) * gain + noise), 0, 255).astype(np.uint8), moved


# --- S4: images that are not a proper photo of the right board ------------------------------------------------------
def _box(img: Image, fx: float, fy: float, fw: float, fh: float) -> tuple[int, int, int, int]:
    h, w = img.shape[:2]
    return int(fx * w), int(fy * h), max(1, int(fw * w)), max(1, int(fh * h))


def bad_frames() -> dict[str, Callable[[Image], Image]]:
    """The bad photos S4 makes from a good one, in memory; the bad files (truncated, empty, 16-bit, CMYK, EXIF) are
    written by the driver, as they test the reader."""

    def gain(g: float) -> Callable[[Image], Image]:
        return lambda im: np.clip(im.astype(np.float32) * g, 0, 255).astype(np.uint8)

    def motion(im: Image) -> Image:
        k = np.zeros((1, 31), np.float32)
        k[0, :] = 1 / 31
        return cv2.filter2D(im, -1, k)

    def hand(im: Image) -> Image:
        out = im.copy()
        x, y, w, h = _box(im, 0.30, 0.20, 0.35, 0.60)
        cv2.ellipse(out, (x + w // 2, y + h // 2), (w // 2, h // 2), 20, 0, 360, (120, 150, 200), -1)  # skin, BGR
        return out

    def empty(im: Image) -> Image:
        rng = np.random.default_rng(0)
        belt = np.full(im.shape, 60, np.float32) + rng.normal(0, 6, im.shape)
        return np.clip(belt, 0, 255).astype(np.uint8)

    def small(im: Image) -> Image:
        return cv2.resize(im, (im.shape[1] // 6, im.shape[0] // 6), interpolation=cv2.INTER_AREA)

    return {
        "overexposed": gain(2.5),
        "underexposed": gain(0.25),
        "motion blur": motion,
        "out of focus": lambda im: cv2.GaussianBlur(im, (0, 0), 6),
        "hand over the board": hand,
        "empty conveyor": empty,
        "much smaller image": small,
    }


# --- S5: good boards that legitimately vary ---------------------------------------------------------------------------
def variations() -> dict[str, Callable[[Image, random.Random], Image]]:
    """Good boards changed the ways a good board does from lot to lot (S5), each at a seeded place."""

    def label(im: Image, rng: random.Random) -> Image:
        out = im.copy()
        x, y, w, h = _box(im, rng.uniform(0.05, 0.75), rng.uniform(0.05, 0.85), 0.14, 0.06)
        cv2.rectangle(out, (x, y), (x + w, y + h), (235, 235, 235), -1)
        text = f"SN{rng.randrange(10**6):06d}"
        cv2.putText(out, text, (x + 4, y + h - 6), cv2.FONT_HERSHEY_SIMPLEX, h / 40, (20, 20, 20), 2)
        return out

    def component(im: Image, rng: random.Random) -> Image:
        out = im.copy()
        x, y, w, h = _box(im, rng.uniform(0.1, 0.8), rng.uniform(0.1, 0.8), 0.08, 0.08)
        hsv = cv2.cvtColor(out[y : y + h, x : x + w], cv2.COLOR_BGR2HSV)
        hsv[..., 0] = (hsv[..., 0].astype(int) + 60) % 180  # same part, another body colour
        out[y : y + h, x : x + w] = cv2.cvtColor(hsv, cv2.COLOR_HSV2BGR)
        return out

    def lot_code(im: Image, rng: random.Random) -> Image:
        out = im.copy()
        x, y, _, h = _box(im, rng.uniform(0.05, 0.7), rng.uniform(0.1, 0.9), 0.1, 0.03)
        cv2.putText(out, f"L{rng.randrange(10**4):04d}", (x, y + h), cv2.FONT_HERSHEY_PLAIN, h / 12, (230, 230, 230), 1)
        return out

    def sheen(im: Image, rng: random.Random) -> Image:
        out = im.astype(np.float32)
        for _ in range(6):
            x, y, w, h = _box(im, rng.uniform(0.1, 0.85), rng.uniform(0.1, 0.85), 0.03, 0.03)
            out[y : y + h, x : x + w] *= rng.uniform(1.10, 1.25)  # a solder joint that shines more
        return np.clip(out, 0, 255).astype(np.uint8)

    return {"serial label": label, "component colour": component, "lot code": lot_code, "solder sheen": sheen}


def revised(im: Image) -> Image:
    """The board's next revision (S8): a part added in an area that was empty, a dark body with four light pads,
    where the revision moved nothing else."""
    out = im.copy()
    x, y, w, h = _box(im, 0.62, 0.70, 0.10, 0.07)
    cv2.rectangle(out, (x, y), (x + w, y + h), (40, 40, 40), -1)
    for px in (x - w // 8, x + w):
        for py in (y + h // 5, y + 3 * h // 5):
            cv2.rectangle(out, (px, py), (px + w // 8, py + h // 5), (200, 200, 200), -1)
    return out


def angle_of(p: dict[str, Any]) -> float:
    return math.remainder(p["angle"], 360)
