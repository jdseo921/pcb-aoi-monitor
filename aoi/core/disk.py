"""Free space on the workspace's drive (REQ-LOG-006), measured at start and before each save. At 80 % used the context
alarms AOI-LOG-005; at 95 % AOI-LOG-006, and an OK board is saved without its overlay and maps, its record noting
SKIPPED_NOTE, while an NG or WARN board keeps all its evidence. No Qt here.
"""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import NamedTuple

LOW, FULL = 0.80, 0.95  # the shares of the drive in use that alarm AOI-LOG-005 and AOI-LOG-006
OK, LOW_LEVEL, FULL_LEVEL = "ok", "low", "full"
LEVELS = (OK, LOW_LEVEL, FULL_LEVEL)  # in order, so a crossing upward is a higher index
SKIPPED_NOTE = "Drive at least 95 % full; the OK overlay and maps were not saved."  # in the record, as written


class Usage(NamedTuple):
    total: int  # bytes
    used: int
    free: int

    @property
    def share(self) -> float:
        """The share of the drive not free, 0 to 1: what a program may still write decides, not the bytes used."""
        return 1 - self.free / self.total if self.total else 1.0

    @property
    def level(self) -> str:
        return FULL_LEVEL if self.share >= FULL else LOW_LEVEL if self.share >= LOW else OK

    @property
    def percent(self) -> int:
        """The share in whole percent, rounded down so 94.9 % never reads as the 95 % that skips evidence."""
        return int(self.share * 100)

    @property
    def free_gb(self) -> float:
        return round(self.free / 1e9, 1)


def usage(folder: Path) -> Usage:
    """The drive's sizes as the system gives them; tests put a drive at each threshold by replacing this."""
    return Usage(*shutil.disk_usage(folder))


def measure(folder: Path) -> Usage | None:
    """The drive that holds `folder`; None when the system cannot say (a drive gone), which stops no save: the write
    itself then reports why."""
    try:
        return usage(folder)
    except OSError:
        return None
