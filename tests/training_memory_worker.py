"""A training run in a process of its own, so that the process's peak memory is the run's (REQ-TRN-007):

    python -m tests.training_memory_worker <folder> <width> <height> <ok> <ng> <band bytes> <epochs> <input size> <ext>

Draws `ok` OK and `ng` NG synthetic boards at 640 × 480 with a fixture's variation (tools/make_synthetic_dataset.py),
scales each up to <width> × <height> with cubic interpolation and writes it under <folder>/boards as an <ext> file
(.png or .jpg), one at a time. It imports them into a workspace under <folder>, freezes a version with all of them in
its training set, in a customer's dataset store (tools/trainable.py), and trains from it with the Golden board's band
at <band bytes> (0: golden.BAND_BYTES as shipped). Its last line is JSON: "baseline", the bytes resident just before
training; "peak", the process's peak resident bytes, an upper bound on training's since the boards were drawn and
imported first, one at a time; "seconds", training's wall time; "raw", the bytes of every board decoded; "machine".
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
from aoi.core.services import AppContext
from aoi.data import credentials
from tools.make_synthetic_dataset import DEFECTS, capture, draw_board
from tools.trainable import trainable


def resident() -> tuple[int, int]:
    """The bytes the process holds in memory now and at its peak: the working set on Windows, the resident set
    elsewhere."""
    if sys.platform == "win32":
        import ctypes
        from ctypes import wintypes

        class Counters(ctypes.Structure):  # PROCESS_MEMORY_COUNTERS
            _fields_ = [("cb", wintypes.DWORD), ("faults", wintypes.DWORD)] + [
                (name, ctypes.c_size_t)
                for name in ("peak", "now", "pool_peak", "pool", "nonpaged_peak", "nonpaged", "page_file", "page_peak")
            ]

        c = Counters()
        c.cb = ctypes.sizeof(Counters)
        process = ctypes.windll.kernel32.GetCurrentProcess()
        ctypes.windll.psapi.GetProcessMemoryInfo(ctypes.c_void_p(process), ctypes.byref(c), c.cb)
        return int(c.now), int(c.peak)
    import resource

    pages = int(Path("/proc/self/statm").read_text().split()[1])  # Linux, the other CI runner
    return pages * os.sysconf("SC_PAGE_SIZE"), resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * 1024


def main(folder: Path, width: int, height: int, ok: int, ng: int, band: int, epochs: int, size: int, ext: str) -> None:
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
    start = time.perf_counter()
    ctx.train(version, epochs=epochs, image_size=size)
    seconds = time.perf_counter() - start
    machine = f"{os.cpu_count()} CPUs, {platform.processor() or platform.machine()}, {platform.platform()}"
    measured = {"baseline": baseline, "peak": resident()[1], "seconds": round(seconds, 1)}
    print(json.dumps(measured | {"raw": (ok + ng) * width * height * 3, "machine": machine}), flush=True)


if __name__ == "__main__":
    a = sys.argv[1:]
    main(Path(a[0]), *(int(v) for v in a[1:8]), a[8])
