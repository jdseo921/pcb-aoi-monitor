"""Generate a synthetic PCB dataset so the app can be tried before real customer images arrive.

    python tools/make_synthetic_dataset.py --out sample_data

Creates:
    sample_data/train/ok/*.png      good boards for self-training
    sample_data/train/ng/*.png      a few labelled defects (optional, for calibration)
    sample_data/test/ok|ng/*.png    held-out set for the AI Model Test screen
    sample_data/labels.csv          file, label, defect_type
"""
from __future__ import annotations

import argparse
import csv
import random
from pathlib import Path

import cv2
import numpy as np

W, H = 640, 480
GREEN = (40, 110, 30)
PAD = (90, 190, 215)      # tin/gold (BGR)
TRACE = (50, 140, 45)
IC = (30, 30, 30)
RES = (60, 75, 95)

# Component layout: (kind, x, y, w, h)
LAYOUT = [
    ("ic", 120, 120, 90, 90), ("ic", 380, 110, 120, 70),
    ("res", 260, 260, 34, 14), ("res", 260, 300, 34, 14), ("res", 330, 300, 34, 14),
    ("cap", 450, 260, 20, 30), ("cap", 500, 260, 20, 30),
    ("conn", 90, 360, 200, 40), ("diode", 400, 360, 40, 18),
]


def draw_board(rng: random.Random, defect: str | None = None) -> np.ndarray:
    img = np.full((H, W, 3), GREEN, np.uint8)
    for x, y in ((20, 20), (W - 20, 20), (20, H - 20), (W - 20, H - 20)):
        cv2.circle(img, (x, y), 8, PAD, -1)                       # fiducials
    for i in range(8):                                             # traces
        cv2.line(img, (30, 60 + i * 45), (W - 30, 70 + i * 40), TRACE, 3)
    cv2.putText(img, "TBOX-A1 REV2", (420, 450), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (230, 230, 230), 1)

    layout = list(LAYOUT)
    missing = rng.randrange(len(layout)) if defect == "Missing Component" else None
    shifted = rng.randrange(len(layout)) if defect == "Misalignment" else None
    for i, (kind, x, y, w, h) in enumerate(layout):
        # pads are always printed, even if the part is missing
        if kind in ("res", "cap", "diode"):
            if w > h:
                cv2.rectangle(img, (x - 6, y - 2), (x + 6, y + h + 2), PAD, -1)
                cv2.rectangle(img, (x + w - 6, y - 2), (x + w + 6, y + h + 2), PAD, -1)
            else:
                cv2.rectangle(img, (x - 2, y - 6), (x + w + 2, y + 6), PAD, -1)
                cv2.rectangle(img, (x - 2, y + h - 6), (x + w + 2, y + h + 6), PAD, -1)
        if i == missing:
            continue
        dx = dy = 0
        if i == shifted:
            dx, dy = rng.choice([(10, 0), (-10, 0), (0, 9), (0, -9)])
        x, y = x + dx, y + dy
        if kind == "ic":
            for k in range(0, w, 10):                                # leads
                cv2.rectangle(img, (x + k + 2, y - 8), (x + k + 6, y), PAD, -1)
                cv2.rectangle(img, (x + k + 2, y + h), (x + k + 6, y + h + 8), PAD, -1)
            cv2.rectangle(img, (x, y), (x + w, y + h), IC, -1)
            pol = (x + 8, y + 8) if defect != "Polarity Error" or i != 0 else (x + w - 8, y + h - 8)
            cv2.circle(img, pol, 4, (200, 200, 200), -1)            # pin-1 mark
        elif kind == "res":
            cv2.rectangle(img, (x, y), (x + w, y + h), RES, -1)
        elif kind == "cap":
            cv2.rectangle(img, (x, y), (x + w, y + h), (40, 90, 160), -1)
        elif kind == "diode":
            cv2.rectangle(img, (x, y), (x + w, y + h), IC, -1)
            cv2.rectangle(img, (x + w - 8, y), (x + w - 4, y + h), (220, 220, 220), -1)
        elif kind == "conn":
            cv2.rectangle(img, (x, y), (x + w, y + h), (210, 210, 210), -1)
            for k in range(10, w, 18):
                cv2.rectangle(img, (x + k, y + 10), (x + k + 6, y + h - 10), PAD, -1)

    if defect == "Solder Bridge":
        x, y = 120 + rng.randrange(0, 80, 10), 120 + 90
        cv2.rectangle(img, (x + 2, y + 2), (x + 16, y + 8), PAD, -1)
    elif defect == "Contamination":
        cx, cy = rng.randint(80, W - 80), rng.randint(80, H - 80)
        cv2.ellipse(img, (cx, cy), (rng.randint(8, 16), rng.randint(5, 12)), rng.randint(0, 180), 0, 360,
                    (120, 150, 160), -1)
    elif defect == "Scratch":
        x1, y1 = rng.randint(50, W - 150), rng.randint(50, H - 150)
        cv2.line(img, (x1, y1), (x1 + rng.randint(60, 120), y1 + rng.randint(20, 80)), (150, 200, 150), 2)
    elif defect == "Solder Ball":
        for _ in range(3):
            cv2.circle(img, (rng.randint(240, 320), rng.randint(240, 330)), 3, (210, 220, 225), -1)
    return img


def capture(img: np.ndarray, rng: random.Random) -> np.ndarray:
    """Simulate placement and lighting variation of a real fixture."""
    ang = rng.uniform(-1.0, 1.0)
    M = cv2.getRotationMatrix2D((W / 2, H / 2), ang, 1.0)
    M[:, 2] += (rng.uniform(-6, 6), rng.uniform(-6, 6))
    out = cv2.warpAffine(img, M, (W, H), borderMode=cv2.BORDER_REPLICATE).astype(np.float32)
    out = out * rng.uniform(0.95, 1.05) + rng.uniform(-6, 6)
    out += np.random.default_rng(rng.randrange(1 << 30)).normal(0, 3, out.shape)
    return np.clip(out, 0, 255).astype(np.uint8)


DEFECTS = ["Missing Component", "Solder Bridge", "Misalignment", "Polarity Error",
           "Contamination", "Scratch", "Solder Ball"]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="sample_data")
    ap.add_argument("--ok", type=int, default=60)
    ap.add_argument("--ng", type=int, default=14)
    ap.add_argument("--seed", type=int, default=7)
    a = ap.parse_args()
    rng = random.Random(a.seed)
    out = Path(a.out)
    rows = []

    def write(split: str, label: str, name: str, img: np.ndarray, dtype: str = ""):
        p = out / split / label.lower() / name
        p.parent.mkdir(parents=True, exist_ok=True)
        cv2.imwrite(str(p), img)
        rows.append({"file": str(p.relative_to(out)), "label": label, "defect_type": dtype})

    cv2.imwrite(str(out.mkdir(parents=True, exist_ok=True) or out / "golden.png"), draw_board(rng))
    n_test_ok = max(4, a.ok // 3)
    for i in range(a.ok):
        write("train" if i >= n_test_ok else "test", "OK", f"ok_{i:03d}.png", capture(draw_board(rng), rng))
    for i in range(a.ng):
        d = DEFECTS[i % len(DEFECTS)]
        split = "train" if i < len(DEFECTS) // 2 else "test"
        write(split, "NG", f"ng_{i:03d}_{d.replace(' ', '_').lower()}.png", capture(draw_board(rng, d), rng), d)
    with open(out / "labels.csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["file", "label", "defect_type"])
        w.writeheader(); w.writerows(rows)
    print(f"Wrote {len(rows)} images to {out.resolve()}")


if __name__ == "__main__":
    main()
