"""The memory a process holds, as the memory tests (tests/training_memory_worker.py) and the soak (tools/soak.py)
read it, with the standard library only."""

from __future__ import annotations

import os
import sys
from pathlib import Path


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
