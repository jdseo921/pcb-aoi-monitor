"""A training run in a process of its own, so that the process's peak memory is the run's (REQ-TRN-007):

    python -m tests.training_memory_worker <folder> <width> <height> <ok> <ng> <band bytes> <epochs> <input size> <ext>
        [<reports>]

Draws `ok` OK and `ng` NG synthetic boards at 640 × 480 with a fixture's variation (tools/make_synthetic_dataset.py),
scales each up to <width> × <height> with cubic interpolation and writes it under <folder>/boards as an <ext> file
(.png or .jpg), one at a time. It imports them into a workspace under <folder>, freezes a version with all of them in
its training set, in a customer's dataset store (tools/trainable.py), and trains from it with the Golden board's band
at <band bytes> (0: golden.BAND_BYTES as shipped). Its last line is JSON: "baseline", the bytes resident just before
training; "peak", the process's peak resident bytes, an upper bound on training's since the boards were drawn and
imported first, one at a time; "seconds", training's wall time; "raw", the bytes of every board decoded; "machine".
With <reports>, a JSON file, the run's reports go there as they come (REQ-TRN-008): "end", training's wall time, and
"reports", each one's seconds since training started, percent, seconds left (null while unknown) and phrase.
Synthetic boards: a measure of time and memory, never of accuracy."""

from __future__ import annotations

import json
import os
import platform
import random
import sys
import time
from pathlib import Path

import cv2

from aoi.config import Settings
from aoi.core import golden
from aoi.core.run_progress import RunProgress
from aoi.core.services import AppContext
from aoi.data import credentials
from tools.make_synthetic_dataset import DEFECTS, capture, draw_board
from tools.memory import resident
from tools.trainable import trainable


def main(
    folder: Path, width: int, height: int, ok: int, ng: int, band: int, epochs: int, size: int, ext: str, reports: str
) -> None:
    rng = random.Random(7)
    boards = folder / "boards"
    boards.mkdir(parents=True, exist_ok=True)
    ctx = AppContext(Settings(workspace=str(folder / "workspace"), device="cpu"), credentials.MemoryCredentials())
    ctx.set_user("engineer")
    for i in range(ok + ng):
        defect = None if i < ok else DEFECTS[i % len(DEFECTS)]
        board = cv2.resize(capture(draw_board(rng, defect), rng), (width, height), interpolation=cv2.INTER_CUBIC)
        path = boards / f"{'ok' if defect is None else 'ng'}_{i:03d}{ext}"
        cv2.imwrite(str(path), board)
        del board
        ctx.import_samples("MEM", [str(path)], "OK" if defect is None else "NG", defect)
    version = trainable(ctx, "MEM")
    golden.BAND_BYTES = band or golden.BAND_BYTES
    baseline = resident()[0]
    said: list[tuple[float, int, float | None, str]] = []

    def heard(p: RunProgress) -> None:
        said.append((time.perf_counter() - start, p.percent, p.left_s, str(p.phase)))

    start = time.perf_counter()
    ctx.train(version, epochs=epochs, image_size=size, progress=heard if reports else None)
    seconds = time.perf_counter() - start
    if reports:
        Path(reports).write_text(json.dumps({"end": seconds, "reports": said}), encoding="utf-8")
    machine = f"{os.cpu_count()} CPUs, {platform.processor() or platform.machine()}, {platform.platform()}"
    measured = {"baseline": baseline, "peak": resident()[1], "seconds": round(seconds, 1)}
    print(json.dumps(measured | {"raw": (ok + ng) * width * height * 3, "machine": machine}), flush=True)


if __name__ == "__main__":
    a = sys.argv[1:]
    main(Path(a[0]), *(int(v) for v in a[1:8]), a[8], a[9] if len(a) > 9 else "")
