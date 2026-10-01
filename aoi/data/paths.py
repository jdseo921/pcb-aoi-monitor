"""Paths stored relative to the workspace (REQ-SET-001, ADR 0004).

A workspace folder can be moved, copied or restored from a backup; everything it holds still opens
because the database never stores where the folder was. A path outside the workspace (a test folder the
user chose) is stored as given.
"""

from __future__ import annotations

from pathlib import Path


def to_stored(path: str | Path, root: Path) -> str:
    """The form kept in the database: relative to `root` with '/' separators when inside it, else as given."""
    p = Path(path)
    try:
        return p.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return str(p)


def resolve(stored: str, root: Path) -> Path:
    """The stored form back to a path that opens on this computer, for this workspace."""
    p = Path(stored)
    return p if p.is_absolute() else root / p
