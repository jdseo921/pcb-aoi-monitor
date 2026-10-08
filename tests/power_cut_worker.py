"""The power-cut test's victim: inspect boards in a loop, saving every result, until killed.

    python -m tests.power_cut_worker <workspace>   (from the repository root)

Prints "ready" once the model is loaded, then one line per finished inspection.
"""

from __future__ import annotations

import sys

from aoi.config import Settings
from aoi.core.services import AppContext


def main(workspace: str) -> None:
    ctx = AppContext(Settings(workspace=workspace, device="cpu"))
    boards = [s["path"] for s in ctx.db.samples("TINY")]
    inspector = ctx.inspector("TINY")
    print("ready", flush=True)
    i = 0
    while True:
        iid = ctx.inspect_file("TINY", boards[i % len(boards)], inspector)
        print(f"done {i} {iid.verdict}", flush=True)
        i += 1


if __name__ == "__main__":
    main(sys.argv[1])
