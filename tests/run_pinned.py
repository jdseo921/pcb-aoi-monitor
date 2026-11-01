"""Run a module as `python -m` does, on a drive pinned at 60 % used (REQ-LOG-006): the subprocess a test starts (the
soak tool, the power-cut worker) then sees what conftest's tests see, not the free space of the machine running it.
"""

from __future__ import annotations

import runpy
import sys

from aoi.core import disk

PINNED_DRIVE = disk.Usage(500 * 10**9, 300 * 10**9, 200 * 10**9)  # 60 % used, as tools/render_screens.py's

if __name__ == "__main__":
    disk.usage = lambda folder: PINNED_DRIVE
    module, sys.argv = sys.argv[1], sys.argv[1:]
    runpy.run_module(module, run_name="__main__", alter_sys=True)
