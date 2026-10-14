"""The USB drives plugged into the station (B5 of the 2026-10 business-readiness brief,
docs/sketches/first-run-guide.md, Q68): the first-run guide's dialogs open on the one plugged in last. A drive counts
when the system says it can be removed: on Windows a drive letter of the removable type that holds a volume, so a USB
hard drive Windows calls fixed is not one; on Linux a partition mounted whole, of a disk marked removable or on a USB
bus, and not of the disk the system runs from. The order is the one the app saw them in: those there at its first look
in the system's order (the order they were mounted in on Linux, the drive letter on Windows), then each one found at a
later look, so a drive plugged in while the app runs is the last. The window looks once as it opens; pages ask
`AppContext.usb_drive`."""

from __future__ import annotations

import logging
import re
import sys
import threading
from pathlib import Path
from typing import Protocol

SEM_FAILCRITICALERRORS = 0x0001  # an empty card reader asks for no disk
DRIVE_REMOVABLE = 2  # GetDriveTypeW's type of a USB stick or a card reader
log = logging.getLogger("aoi")
_seen: list[Path] = []  # the drives mounted at the last look, in the order the app saw them, the one plugged last last
_lock = threading.Lock()


class Letters(Protocol):
    """What Windows says of its drive letters (kernel32)."""

    def mounted(self) -> int:
        """A bit for each drive letter in use, A the lowest (GetLogicalDrives)."""
        ...

    def drive_type(self, root: str) -> int:
        """The type of the drive at `root`, such as "E:\\" (GetDriveTypeW)."""
        ...

    def holds_volume(self, root: str) -> bool:
        """Whether a volume is in the drive at `root`: False for a card reader with no card (GetVolumeInformationW)."""
        ...

    def error_mode(self, mode: int) -> int:
        """This thread's error mode set to `mode`; the one before (SetThreadErrorMode)."""
        ...


def removable() -> list[Path]:
    """The removable drives mounted now, each by the folder it opens on, in the system's order; [] where the system
    cannot say, or listing them fails, so a dialog opens where it did and no window fails to open (logged)."""
    try:
        if sys.platform == "win32":
            return _windows(_Kernel32())
        if sys.platform.startswith("linux"):
            return _linux(Path("/proc/self/mountinfo"), Path("/sys/dev/block"))
    except Exception:
        log.warning("drives.not_listed", exc_info=True)
    return []


def last_plugged() -> Path | None:
    """The removable drive plugged in last of those mounted now, in the order the app saw them; None with none."""
    now = removable()
    with _lock:
        _seen[:] = [d for d in _seen if d in now] + [d for d in now if d not in _seen]
        return _seen[-1] if _seen else None


def _linux(mountinfo: Path, block: Path) -> list[Path]:
    """Each mount point in `mountinfo` (proc(5): one line a mount, in the order they were mounted) of a whole
    filesystem whose device, under `block` by its major:minor, is removable and not on the disk mounted at the root: a
    system started from a USB drive lists none of its own partitions, /boot/efi say."""
    mounts = [line.split(" - ", 1)[0].split() for line in mountinfo.read_text("utf-8", errors="replace").splitlines()]
    mounts = [m for m in mounts if len(m) >= 5 and m[3] == "/"]  # a folder of a drive mounted again is not one
    system = {_disk(block / m[2]) for m in mounts if m[4] == "/"} - {None}
    drives: list[Path] = []
    for m in mounts:
        disk = _disk(block / m[2])
        if disk is not None and disk not in system and _removable(disk):
            drives.append(Path(re.sub(r"\\([0-7]{3})", lambda o: chr(int(o.group(1), 8)), m[4])))
    return drives


def _disk(device: Path) -> Path | None:
    """The disk the block device `device` links to is on: itself when it is no partition; None with no block device
    (a tmpfs, a network share)."""
    try:
        real = device.resolve(strict=True)
    except OSError:
        return None
    return real.parent if (real / "partition").is_file() else real


def _removable(disk: Path) -> bool:
    """Whether `disk` sits on a USB bus or is marked removable."""
    mark = disk / "removable"
    if "/usb" in disk.as_posix():
        return True
    return mark.is_file() and mark.read_text(encoding="ascii", errors="replace").strip() == "1"


def _windows(kernel32: Letters) -> list[Path]:
    """Each drive letter of the removable type holding a volume, A to Z, by its root; with critical-error boxes off on
    this thread meanwhile, so an empty card reader asks for no disk."""
    before = kernel32.error_mode(SEM_FAILCRITICALERRORS)
    try:
        letters = kernel32.mounted()
        roots = [f"{chr(ord('A') + i)}:\\" for i in range(26) if letters >> i & 1]
        return [Path(r) for r in roots if kernel32.drive_type(r) == DRIVE_REMOVABLE and kernel32.holds_volume(r)]
    finally:
        kernel32.error_mode(before)


if sys.platform == "win32":
    import ctypes
    from ctypes import wintypes

    class _Kernel32:
        """kernel32's calls of our own, with their argument and result types declared, as aoi/ui/front.py has user32's:
        no other module's argtypes on the shared `windll` change them."""

        def __init__(self) -> None:
            kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
            self._mounted = kernel32.GetLogicalDrives
            self._mounted.argtypes, self._mounted.restype = [], wintypes.DWORD
            self._type = kernel32.GetDriveTypeW
            self._type.argtypes, self._type.restype = [wintypes.LPCWSTR], wintypes.UINT
            self._volume = kernel32.GetVolumeInformationW
            self._volume.argtypes = [
                wintypes.LPCWSTR,
                wintypes.LPWSTR,
                wintypes.DWORD,
                wintypes.LPDWORD,
                wintypes.LPDWORD,
                wintypes.LPDWORD,
                wintypes.LPWSTR,
                wintypes.DWORD,
            ]
            self._volume.restype = wintypes.BOOL
            self._mode = kernel32.SetThreadErrorMode
            self._mode.argtypes, self._mode.restype = [wintypes.DWORD, wintypes.LPDWORD], wintypes.BOOL

        def mounted(self) -> int:
            return int(self._mounted())

        def drive_type(self, root: str) -> int:
            return int(self._type(root))

        def holds_volume(self, root: str) -> bool:
            return bool(self._volume(root, None, 0, None, None, None, None, 0))

        def error_mode(self, mode: int) -> int:
            before = wintypes.DWORD(0)
            if not self._mode(mode, ctypes.byref(before)):
                raise ctypes.WinError(ctypes.get_last_error())
            return int(before.value)
