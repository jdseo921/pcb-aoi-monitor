"""Crash-safe file writes (REQ-INSP-008, ADR 0004 decision 6).

Every file the app writes goes to a temporary name in the same folder, is flushed and fsynced, then
renamed over the target with ``os.replace``, which is atomic on NTFS and on POSIX file systems. A reader
sees the old file or the whole new one, never a partial write, and a finished write survives a power cut:
the data is on disk before the rename, and on POSIX the folder entry is synced after it.
"""

from __future__ import annotations

import contextlib
import os
import re
import shutil
import uuid
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import BinaryIO

TEMP_SUFFIX = ".tmp"
TEMP_NAME = re.compile(r"\..+\.[0-9a-f]{8}" + re.escape(TEMP_SUFFIX))  # what `temp_path` makes, and nothing else


def write_with(path: str | Path, writer: Callable[[BinaryIO], object]) -> None:
    """Call `writer` with a binary file on a temporary name next to `path`, then move it into place."""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = temp_path(target)
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


def write_all(files: Sequence[tuple[str | Path, bytes]]) -> None:
    """Write several files together or not at all (#195): each to a temporary name first, then each moved into place,
    the file it replaces kept under a temporary name until all are in place. When one cannot be moved (another program
    holds it open), the files already moved are taken back out and the ones they replaced put back."""
    staged: list[tuple[Path, Path]] = []
    moved: list[tuple[Path, Path | None]] = []  # a target in place, and the file it replaced
    target = Path()
    try:
        for path, data in files:
            target = Path(path)
            target.parent.mkdir(parents=True, exist_ok=True)
            staged.append((target, temp_path(target)))
            with open(staged[-1][1], "wb") as f:
                f.write(data)
                f.flush()
                os.fsync(f.fileno())
        for target, tmp in staged:
            old = temp_path(target) if target.is_file() else None
            if old is not None:
                os.replace(target, old)
            try:
                os.replace(tmp, target)
            except BaseException:
                if old is not None:
                    os.replace(old, target)
                raise
            moved.append((target, old))
    except BaseException as e:
        for done, old in reversed(moved):
            with contextlib.suppress(OSError):  # the error that stopped the write is the one to report
                if old is None:
                    done.unlink()
                else:
                    os.replace(old, done)
        for _, tmp in staged:
            tmp.unlink(missing_ok=True)
        if isinstance(e, OSError):  # named by the file that could not be written, not by a temporary name
            raise OSError(e.errno, e.strerror, str(target)) from e
        raise
    for _, old in moved:
        if old is not None:
            old.unlink(missing_ok=True)
    for folder in {done.parent for done, _ in moved}:
        _sync_folder(folder)


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


def sweep_temp_files(folder: str | Path) -> tuple[int, list[tuple[Path, str]]]:
    """Remove the temporary files a crash left behind under `folder`: only names `temp_path` makes, so a file another
    program left is never touched. A file that cannot be deleted (read-only, held open) is harmless and skipped, never
    an error (#204). Returns how many were removed, and each file skipped with the reason."""
    leftovers = [p for p in Path(folder).rglob(f".*{TEMP_SUFFIX}") if TEMP_NAME.fullmatch(p.name) and p.is_file()]
    removed, skipped = 0, list[tuple[Path, str]]()
    for p in leftovers:
        try:
            p.unlink(missing_ok=True)
        except OSError as e:
            skipped.append((p, str(e)))
        else:
            removed += 1
    return removed, skipped


def temp_path(target: Path) -> Path:
    """A hidden name beside `target`, ``.<name>.<8 hex digits>.tmp``, that `sweep_temp_files` removes after a crash."""
    return target.with_name(f".{target.name}.{uuid.uuid4().hex[:8]}{TEMP_SUFFIX}")


def _sync_folder(folder: Path) -> None:
    """Make the rename durable: POSIX needs the folder entry synced; NTFS journals it and has no folder fsync."""
    if os.name == "nt":
        return
    fd = os.open(folder, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)
