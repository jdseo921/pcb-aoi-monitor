"""One copy of the app per workspace (REQ-SET-016, REQ-INSP-008, #204). No Qt.

`AppContext` holds an exclusive lock on ``<workspace>/.aoi.lock`` from before it opens the log and the database until
it closes the workspace. A second copy started on the same folder meanwhile, in another process or another user's
session, is refused with AOI-SET-012 before it reads, writes or deletes anything there, so the start-up sweep of
temporary files only ever meets what a crash left. The lock is the operating system's (``fcntl.flock`` on POSIX,
``msvcrt.locking`` on Windows), not the file's existence: the system lets go when the process ends, so a crash or a
power cut never blocks the next start. The file itself stays and holds nothing.
"""

from __future__ import annotations

import contextlib
import errno
import os
import sys
from pathlib import Path

from ..errors import QT_TRANSLATE_NOOP
from .errors import WorkspaceError

LOCK_NAME = ".aoi.lock"
# Windows byte-range locks are mandatory: the byte locked lies far past the empty file's end, so a backup or a copy of
# the workspace folder still reads the file while the app runs.
_WINDOWS_OFFSET = 1 << 30
_HELD = {errno.EAGAIN, errno.EWOULDBLOCK, errno.EACCES, errno.EDEADLK}  # what each system says when another holds it
ANOTHER_COPY = QT_TRANSLATE_NOOP("Errors", "another copy of this app has this workspace open")  # AOI-SET-012's {error}


class WorkspaceLock:
    """The lock one open workspace holds; `release` lets go of it (again is a no-op)."""

    def __init__(self, fd: int, path: Path) -> None:
        self._fd: int | None = fd
        self.path = path

    @classmethod
    def acquire(cls, folder: str | Path) -> WorkspaceLock:
        """Take the workspace's lock without waiting: AOI-SET-012 when another copy of the app holds it, AOI-SET-011
        when the lock file cannot be created or locked for another reason."""
        path = Path(folder) / LOCK_NAME
        try:
            fd = os.open(path, os.O_RDWR | os.O_CREAT, 0o644)
        except OSError as e:
            raise WorkspaceError("AOI-SET-011", path=str(folder), error=str(e)) from e
        try:
            _lock(fd)
        except OSError as e:
            os.close(fd)
            if e.errno in _HELD:
                raise WorkspaceError("AOI-SET-012", path=str(path), error=ANOTHER_COPY) from e
            raise WorkspaceError("AOI-SET-011", path=str(folder), error=str(e)) from e
        return cls(fd, path)

    def release(self) -> None:
        if self._fd is None:
            return
        fd, self._fd = self._fd, None
        with contextlib.suppress(OSError):  # closing lets go too, on every system
            _unlock(fd)
        os.close(fd)


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
