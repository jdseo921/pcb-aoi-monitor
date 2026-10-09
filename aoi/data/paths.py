"""Paths stored relative to the workspace (REQ-SET-001, ADR 0004).

A workspace folder can be moved, copied or restored from a backup; everything it holds still opens
because the database never stores where the folder was. A path outside the workspace (a test folder the
user chose) is stored as given.
"""

from __future__ import annotations

import os
from pathlib import Path

DEVICES = {"CON", "PRN", "AUX", "NUL", "CONIN$", "CONOUT$"}  # what Windows keeps for a device, in any case
DEVICES |= {port + n for port in ("COM", "LPT") for n in "0123456789¹²³"}
NOT_IN_A_NAME = set('/\\:*?"<>|') | {chr(i) for i in range(32)}  # a separator, or refused in a Windows file name


def one_folder_name(name: str) -> bool:
    """Whether `name` names one folder of the workspace, the same on Windows as on Linux (a board model's folders
    under images/ and models/, S31): not empty, no separator, none of : * ? " < > | or a control character, no dot or
    space at its end (Windows drops them, and . and .. lead elsewhere), and not a device name Windows keeps, in any
    case, with or without an extension (CON, NUL, COM0 to COM9 and COM¹ to COM³, LPT the same, CONIN$, CONOUT$:
    COM1, LPT9.txt, conin$)."""
    stem = name.split(".")[0].rstrip(" ").upper()
    return bool(name) and name[-1] not in ". " and not set(name) & NOT_IN_A_NAME and stem not in DEVICES


def inside(path: str | Path, folder: str | Path) -> bool:
    """Whether `path`, its . and .. resolved as written (no link followed), lies inside `folder`."""
    return Path(os.path.abspath(path)).is_relative_to(os.path.abspath(folder))


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
