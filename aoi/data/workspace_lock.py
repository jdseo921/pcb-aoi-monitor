"""One copy of the app per workspace (REQ-SET-016, REQ-INSP-008, #204). No Qt.

`AppContext` holds an exclusive lock on ``<workspace>/.aoi.lock`` from before it opens the log and the database until
it closes the workspace. A second copy started on the same folder meanwhile, in another process or another user's
session, is refused with AOI-SET-019 before it reads, writes or deletes anything there, so the start-up sweep of
temporary files only ever meets what a crash left. The lock is the operating system's (``fcntl.flock`` on POSIX,
``msvcrt.locking`` on Windows), not the file's existence: the system lets go when the process ends, so a crash or a
power cut never blocks the next start. The file itself stays; while the lock is held it names the copy that holds it,
its process and, once shown, its window, so a second start can bring that window to the front (A6 of the 2026-10
business-readiness brief, F12). What a copy that ended wrote there is read only while another holds the lock, which
writes its own first.
"""

from __future__ import annotations

import contextlib
import errno
import json
import os
import sys
from pathlib import Path

from ..errors import system_detail, system_reason
from .errors import WorkspaceError

LOCK_NAME = ".aoi.lock"
# Windows byte-range locks are mandatory: the byte locked lies far past the holder's note at the file's start, so a
# backup or a copy of the workspace folder, and a second start reading the note, still read the file while the app runs.
_WINDOWS_OFFSET = 1 << 30
_HELD = {errno.EAGAIN, errno.EWOULDBLOCK, errno.EACCES, errno.EDEADLK}  # what each system says when another holds it
_HOLDER_BYTES = 64  # the holder's JSON, padded with spaces: a later, shorter note leaves nothing of the one before


class WorkspaceLock:
    """The lock one open workspace holds; `release` lets go of it (again is a no-op)."""

    def __init__(self, fd: int, path: Path) -> None:
        self._fd: int | None = fd
        self.path = path
        self.note(0)

    @classmethod
    def acquire(cls, folder: str | Path) -> WorkspaceLock:
        """Take the workspace's lock without waiting: AOI-SET-019 when another copy of the app holds it, AOI-SET-011
        when the lock file cannot be created or locked for another reason."""
        path = Path(folder) / LOCK_NAME
        try:
            fd = os.open(path, os.O_RDWR | os.O_CREAT, 0o644)
        except OSError as e:
            raise WorkspaceError("AOI-SET-011", system_detail(e), path=str(folder), error=system_reason(e)) from e
        try:
            _lock(fd)
        except OSError as e:
            os.close(fd)
            if e.errno in _HELD:
                raise WorkspaceError("AOI-SET-019", path=str(folder)) from e
            raise WorkspaceError("AOI-SET-011", system_detail(e), path=str(folder), error=system_reason(e)) from e
        return cls(fd, path)

    def note(self, window: int) -> None:
        """Write this process and its `window` (0 until one is shown) into the lock file, for a second start to find
        (`holder`). A write the system refuses changes nothing: that start then says the app is open instead."""
        if self._fd is None:
            return
        held = json.dumps({"pid": os.getpid(), "window": window}).ljust(_HOLDER_BYTES).encode("ascii")
        with contextlib.suppress(OSError):
            os.lseek(self._fd, 0, os.SEEK_SET)
            os.write(self._fd, held)

    def release(self) -> None:
        if self._fd is None:
            return
        fd, self._fd = self._fd, None
        with contextlib.suppress(OSError):  # closing lets go too, on every system
            _unlock(fd)
        os.close(fd)


def in_use(folder: str | Path) -> bool:
    """True when another copy of the app, or another open workspace of this one, holds the workspace's lock now: asked
    by the lock itself, taken and let go at once, so a note left by a copy that ended counts for nothing. A folder with
    no lock file, or one that cannot be opened, is not in use; nothing is created."""
    try:
        fd = os.open(Path(folder) / LOCK_NAME, os.O_RDWR)
    except OSError:
        return False
    try:
        _lock(fd)
    except OSError as e:
        return e.errno in _HELD
    else:
        with contextlib.suppress(OSError):
            _unlock(fd)
        return False
    finally:
        os.close(fd)


def holder(folder: str | Path) -> tuple[int, int] | None:
    """(process id, window) of the copy that holds the workspace's lock, as it noted them, or None when the file cannot
    be read or holds no such note. Read without the lock: only a second start, refused, asks."""
    try:
        with open(Path(folder) / LOCK_NAME, "rb") as f:
            held = json.loads(f.read(_HOLDER_BYTES))
        pid, window = held["pid"], held["window"]
    except (OSError, ValueError, KeyError, TypeError):
        return None
    if not all(isinstance(v, int) and not isinstance(v, bool) and v >= 0 for v in (pid, window)):
        return None
    return pid, window


if sys.platform == "win32":
    import msvcrt

    def _lock(fd: int) -> None:
        os.lseek(fd, _WINDOWS_OFFSET, os.SEEK_SET)
        msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)

    def _unlock(fd: int) -> None:
        os.lseek(fd, _WINDOWS_OFFSET, os.SEEK_SET)
        msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)

else:
    import fcntl

    def _lock(fd: int) -> None:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)

    def _unlock(fd: int) -> None:
        fcntl.flock(fd, fcntl.LOCK_UN)
