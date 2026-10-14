"""The USB drives plugged into the station (B5 of the 2026-10 business-readiness brief,
docs/sketches/first-run-guide.md, Q68): the first-run guide's dialogs open on the one plugged in last. A drive counts
when the system says it can be removed: on Windows a drive letter of the removable type that holds a volume, so a USB
hard drive Windows calls fixed is not one; on Linux a partition mounted whole, of a disk marked removable or on a USB
bus. The order is the one the app saw them in: those there at its first look in the system's order (the order they were
mounted in on Linux, the drive letter on Windows), then each one found at a later look, so a drive plugged in while the
app runs is the last. The window looks once as it opens (`last_plugged`)."""

from __future__ import annotations

import re
import sys
import threading
from pathlib import Path

_seen: list[Path] = []  # the drives mounted at the last look, in the order the app saw them, the one plugged last last
_lock = threading.Lock()


def removable() -> list[Path]:
    """The removable drives mounted now, each by the folder it opens on, in the system's order; [] where the system
    cannot say."""
    try:
        if sys.platform == "win32":
            return _windows()
        if sys.platform.startswith("linux"):
            return _linux(Path("/proc/self/mountinfo"), Path("/sys/dev/block"))
    except OSError:
        pass
    return []


def last_plugged() -> Path | None:
    """The removable drive plugged in last of those mounted now, in the order the app saw them; None with none."""
    now = removable()
    with _lock:
        _seen[:] = [d for d in _seen if d in now] + [d for d in now if d not in _seen]
        return _seen[-1] if _seen else None


def _linux(mountinfo: Path, block: Path) -> list[Path]:
    """Each mount point in `mountinfo` (proc(5): one line a mount, in the order they were mounted) of a whole
    filesystem whose device, under `block` by its major:minor, is removable; not the root, a system started from a USB
    drive."""
    drives: list[Path] = []
    for line in mountinfo.read_text(encoding="utf-8", errors="replace").splitlines():
        fields = line.split(" - ", 1)[0].split()
        if len(fields) < 5 or fields[3] != "/" or fields[4] == "/":  # a folder of one, or the system's own disk
            continue
        if _removable(block / fields[2]):
            drives.append(Path(re.sub(r"\\([0-7]{3})", lambda m: chr(int(m.group(1), 8)), fields[4])))
    return drives


def _removable(device: Path) -> bool:
    """Whether the block device `device` links to sits on a USB bus, or it or its disk is marked removable."""
    try:
        real = device.resolve(strict=True)
    except OSError:
        return False  # no block device: a tmpfs, a network share
    if "/usb" in real.as_posix():
        return True
    for place in (real, real.parent):  # a partition's disk holds the mark
        mark = place / "removable"
        if mark.is_file() and mark.read_text(encoding="ascii", errors="replace").strip() == "1":
            return True
    return False


def _windows() -> list[Path]:
    """Each drive letter of the removable type (GetDriveTypeW's DRIVE_REMOVABLE) holding a volume, A to Z; an empty card
    reader asks for no disk (SEM_FAILCRITICALERRORS)."""
    if sys.platform == "win32":
        import ctypes

        kernel32 = ctypes.windll.kernel32
        before = int(kernel32.SetErrorMode(0x0001))
        try:
            letters = int(kernel32.GetLogicalDrives())
            roots = [f"{chr(ord('A') + i)}:\\" for i in range(26) if letters >> i & 1]
            return [
                Path(r)
                for r in roots
                if int(kernel32.GetDriveTypeW(r)) == 2
                and int(kernel32.GetVolumeInformationW(r, None, 0, None, None, None, None, 0)) != 0
            ]
        finally:
            kernel32.SetErrorMode(before)
    return []
