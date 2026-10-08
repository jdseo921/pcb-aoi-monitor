"""The power-cut test's victim: inspect boards in a loop, saving every result, until killed.

    python -m tests.power_cut_worker <workspace>   (from the repository root)

Prints "ready" once the model is loaded, then "done ..." for each finished inspection, after its row is committed.
Two test-only switches in the environment: AOI_POWER_CUT_SLOW_S adds that many seconds inside every inspection (a
busy PC), and AOI_POWER_CUT_IN_WRITE=<n> ends the process inside the n-th file write once half of its bytes are on
disk, after printing "dying <path>".
"""

from __future__ import annotations

import io
import os
import sys
import time
from collections.abc import Callable
from pathlib import Path
from typing import BinaryIO

import numpy as np

from aoi.config import Settings
from aoi.core.inspector import InspectionResult, Inspector
from aoi.core.services import AppContext
from aoi.data import atomic


def slow_inspections(inspector: Inspector, seconds: float) -> None:
    inspect = inspector.inspect

    def slowed(img: np.ndarray) -> InspectionResult:
        time.sleep(seconds)
        return inspect(img)

    inspector.inspect = slowed  # type: ignore[method-assign]


def die_inside_write(n: int) -> None:
    real = atomic.write_with
    count = 0

    def write_with(path: str | Path, writer: Callable[[BinaryIO], object]) -> None:
        nonlocal count
        count += 1
        if count < n:
            return real(path, writer)

        def half(f: BinaryIO) -> None:
            buf = io.BytesIO()
            writer(buf)
            f.write(buf.getvalue()[: len(buf.getvalue()) // 2])
            f.flush()
            os.fsync(f.fileno())
            print(f"dying {path}", flush=True)
            os._exit(3)  # nothing is cleaned up, as with a power cut

        real(path, half)

    atomic.write_with = write_with  # write_bytes, write_text and copy_file call it through the module


def main(workspace: str) -> None:
    ctx = AppContext(Settings(workspace=workspace, device="cpu"))
    boards = [s["path"] for s in ctx.db.samples("TINY")]
    inspector = ctx.inspector("TINY")
    if os.environ.get("AOI_POWER_CUT_SLOW_S"):
        slow_inspections(inspector, float(os.environ["AOI_POWER_CUT_SLOW_S"]))
    if os.environ.get("AOI_POWER_CUT_IN_WRITE"):
        die_inside_write(int(os.environ["AOI_POWER_CUT_IN_WRITE"]))
    print("ready", flush=True)
    i = 0
    while True:
        iid = ctx.inspect_file("TINY", boards[i % len(boards)], inspector)
        print(f"done {i} {iid.verdict}", flush=True)
        i += 1


if __name__ == "__main__":
    main(sys.argv[1])
