"""Drawn boards that differ from one another as photographed boards do (#460, #461), for the tests and for a look at
what a customer's own photos ask of the program before any are at hand.

The boards of tools/make_synthetic_dataset.py are one drawing photographed with a little noise: every good board is the
Golden board, give or take a grey level. Photographed boards are not. Each part carries a date code of its own and
each board a serial-number label, solder shines differently on every joint, the surface is mottled, parts sit a pixel
or two off, and the camera's light, focus and placement change from one board to the next. `varied_board` draws a
board with all of these, each from the same random generator, so the same seed gives the same boards on every machine.

    python tools/varied_boards.py OUT [--ok 80] [--ng 3] [--seed 11]

writes OUT/ok/*.png and OUT/ng/<defect type>/*.png, the layout Pick Folder… and Import Folder… take.

What these boards show is that the steps work on boards that vary. They are drawings: no count on them is an accuracy,
and none is quoted as one (docs/requirements/stage1.md, G2 is measured on the factory's own boards).
"""

from __future__ import annotations

import argparse
import random
from pathlib import Path

import cv2
import numpy as np

from tools.make_synthetic_dataset import DEFECTS, LAYOUT, H, W, draw_board

DATE_CODE_GREY = (150, 150, 150)
LABEL = (480, 395, 76, 22)  # x, y, width, height of the serial-number label, on bare board
SHINE = (0.82, 1.12)  # a joint's pads, lighter or darker by this factor
OFF_PX = 0.7  # how far a part sits off, as the deviation of a smooth displacement field, in pixels
TURN_DEG, SHIFT_PX = 1.5, 8.0  # the board's placement under the camera
GAIN, TILT, BLACK = (0.9, 1.1), 0.04, 8.0  # the lighting: overall, from one side to the other, and the black level
NOISE = 4.0  # the camera's noise, in grey levels


def _smooth(nrng: np.random.Generator, cells: tuple[int, int]) -> np.ndarray:
    """A smooth random field over the board, of deviation near 1."""
    out: np.ndarray = cv2.resize(nrng.normal(0, 1, cells).astype(np.float32), (W, H), interpolation=cv2.INTER_CUBIC)
    return out


def varied_board(rng: random.Random, defect: str | None = None) -> np.ndarray:
    """One board, good or with `defect` (one of make_synthetic_dataset.DEFECTS), as one photo of it."""
    nrng = np.random.default_rng(rng.randrange(1 << 30))
    drawn = draw_board(rng, defect).astype(np.float32) + _smooth(nrng, (H // 40, W // 40))[..., None] * 5.0
    out = np.clip(drawn, 0, 255).astype(np.uint8)  # a mottled surface
    for kind, x, y, w, h in LAYOUT:
        if kind == "ic":  # a date code, different on every board
            code = f"{rng.randrange(10, 53):02d}{rng.randrange(20, 27):02d}"
            cv2.putText(out, code, (x + 8, y + h // 2 + 14), cv2.FONT_HERSHEY_SIMPLEX, 0.45, DATE_CODE_GREY, 1)
        elif kind in ("res", "cap", "diode"):  # solder that shines differently on every joint
            f = rng.uniform(*SHINE)
            pad = out[y - 3 : y + h + 3, x - 7 : x + w + 7].astype(np.float32)
            bright = pad.mean(axis=2, keepdims=True) > 150
            out[y - 3 : y + h + 3, x - 7 : x + w + 7] = np.clip(np.where(bright, pad * f, pad), 0, 255).astype(np.uint8)
            if rng.random() < 0.5:  # a highlight
                at = (x - 2 + rng.randrange(0, 4), y + rng.randrange(0, max(1, h)))
                cv2.circle(out, at, 1, (250, 250, 250), -1)
    x, y, w, h = LABEL  # a serial-number label: the same sticker, another number on every board
    cv2.rectangle(out, (x, y), (x + w, y + h), (235, 238, 240), -1)
    cv2.putText(out, f"{rng.randrange(10**6):06d}", (x + 5, y + h - 6), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (25, 25, 25), 1)
    gx, gy = np.meshgrid(np.arange(W, dtype=np.float32), np.arange(H, dtype=np.float32))
    dx, dy = _smooth(nrng, (6, 8)) * OFF_PX, _smooth(nrng, (6, 8)) * OFF_PX  # parts a pixel or two off
    out = cv2.remap(out, gx + dx, gy + dy, cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE)
    m = cv2.getRotationMatrix2D((W / 2, H / 2), rng.uniform(-TURN_DEG, TURN_DEG), 1.0)
    m[:, 2] += (rng.uniform(-SHIFT_PX, SHIFT_PX), rng.uniform(-SHIFT_PX, SHIFT_PX))
    photo = cv2.warpAffine(out, m, (W, H), borderMode=cv2.BORDER_REPLICATE).astype(np.float32)
    tilt = rng.uniform(-TILT, TILT)
    photo = photo * rng.uniform(*GAIN) * np.linspace(1 - tilt, 1 + tilt, W, dtype=np.float32)[None, :, None]
    photo += rng.uniform(-BLACK, BLACK)
    if (soft := rng.uniform(0, 0.8)) > 0.3:  # a focus that is not always the same
        photo = cv2.GaussianBlur(photo, (0, 0), soft)
    photo += nrng.normal(0, NOISE, photo.shape)
    return np.clip(photo, 0, 255).astype(np.uint8)


def write_boards(out: Path, ok: int = 80, ng: int = 3, seed: int = 11) -> list[Path]:
    """`ok` good boards in OUT/ok and `ng` of each defect type in OUT/ng/<type>, and their paths."""
    rng, paths = random.Random(seed), []
    (out / "ok").mkdir(parents=True, exist_ok=True)
    for i in range(ok):
        paths.append(out / "ok" / f"ok_{i:03d}.png")
        cv2.imwrite(str(paths[-1]), varied_board(rng))
    for defect in DEFECTS:
        (out / "ng" / defect).mkdir(parents=True, exist_ok=True)
        for i in range(ng):
            paths.append(out / "ng" / defect / f"ng_{i:03d}.png")
            cv2.imwrite(str(paths[-1]), varied_board(rng, defect))
    return paths


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("out", type=Path)
    ap.add_argument("--ok", type=int, default=80)
    ap.add_argument("--ng", type=int, default=3)
    ap.add_argument("--seed", type=int, default=11)
    args = ap.parse_args()
    print(f"{len(write_boards(args.out, args.ok, args.ng, args.seed))} boards written to {args.out}")


if __name__ == "__main__":
    main()
