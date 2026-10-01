"""Crash-safe file writes (REQ-INSP-008, ADR 0004 decision 6).

Every file the app writes goes to a temporary name in the same folder, is flushed and fsynced, then
renamed over the target with ``os.replace``, which is atomic on NTFS and on POSIX file systems. A reader
sees the old file or the whole new one, never a partial write, and a finished write survives a power cut:
the data is on disk before the rename, and on POSIX the folder entry is synced after it.
"""

from __future__ import annotations

import os
import shutil
import uuid
from collections.abc import Callable
from pathlib import Path
from typing import BinaryIO

TEMP_SUFFIX = ".tmp"


def write_with(path: str | Path, writer: Callable[[BinaryIO], object]) -> None:
    """Call `writer` with a binary file on a temporary name next to `path`, then move it into place."""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_name(f".{target.name}.{uuid.uuid4().hex[:8]}{TEMP_SUFFIX}")
    try:
        with open(tmp, "wb") as f:
            writer(f)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, target)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise
    _sync_folder(target.parent)


def write_bytes(path: str | Path, data: bytes) -> None:
    write_with(path, lambda f: f.write(data))


def write_text(path: str | Path, text: str, encoding: str = "utf-8") -> None:
    write_bytes(path, text.encode(encoding))


def copy_file(src: str | Path, dst: str | Path) -> None:
    """Copy `src` to `dst` so that `dst` is either absent, the old file or the whole copy."""

    def copy(f: BinaryIO) -> None:
        with open(src, "rb") as s:
            shutil.copyfileobj(s, f)

    write_with(dst, copy)


def sweep_temp_files(folder: str | Path) -> int:
    """Remove temporary files a crash left behind under `folder`; returns how many."""
    leftovers = [p for p in Path(folder).rglob(f".*{TEMP_SUFFIX}") if p.is_file()]
    for p in leftovers:
        p.unlink(missing_ok=True)
    return len(leftovers)


def _sync_folder(folder: Path) -> None:
    """Make the rename durable: POSIX needs the folder entry synced; NTFS journals it and has no folder fsync."""
    if os.name == "nt":
        return
    fd = os.open(folder, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)
