"""The workspace guard (REQ-SET-025): a workspace holds a live SQLite database in WAL mode, which needs the locks and
the shared memory of a local drive. On a network drive (a UNC path, or a drive letter Windows calls remote) its locks
can be lost and its writes reordered; in a folder OneDrive copies to the cloud, the sync client holds files open and
puts back copies of the database, its WAL and its evidence files that do not belong together. Either can damage records
without a sign, so both are refused with AOI-SET-024 when the folder is picked on Settings and at every start. No Qt
here."""

from __future__ import annotations

import ctypes
import os
from pathlib import Path

from ..errors import QT_TRANSLATE_NOOP, Phrase
from .errors import WorkspaceError
from .paths import inside

DRIVE_REMOTE = 4  # GetDriveTypeW's type of a network drive, a mapped drive letter included
NETWORK = QT_TRANSLATE_NOOP("Errors", "it is on a network drive, where the database's locks are not safe")
ONE_DRIVE = QT_TRANSLATE_NOOP(
    "Errors", "it is in a folder OneDrive copies to the cloud, which holds and puts back files"
)


def one_drive_roots() -> list[str]:
    """The folders OneDrive copies to the cloud on this Windows account, as Windows names them in the environment: the
    personal one and a work or school one; none elsewhere."""
    names = ("OneDrive", "OneDriveConsumer", "OneDriveCommercial")
    return [root for name in names if (root := os.environ.get(name, "").strip())]


def drive_type(anchor: str) -> int | None:
    """What Windows calls the drive at `anchor`, such as "Z:\\" (GetDriveTypeW); None elsewhere."""
    if os.name != "nt":
        return None
    return int(ctypes.windll.kernel32.GetDriveTypeW(anchor))  # type: ignore[attr-defined]


def refusal(folder: str | Path) -> Phrase | None:
    """Why `folder` cannot hold a workspace, or None when it can: judged as written and again with its links and
    junctions followed (os.path.realpath), so a local folder that leads to a share or into OneDrive is caught."""
    written = os.fspath(folder)
    for text in (written, os.path.realpath(written)):
        head = text[:4].replace("/", "\\")
        if head in ("\\\\?\\", "\\\\.\\"):  # a long-path prefix: \\?\C:\… is local, \\?\UNC\server\… is not
            text = text[4:]
            if text[:4].replace("/", "\\").upper() == "UNC\\":
                return NETWORK
        elif head.startswith("\\\\"):  # \\server\share, or //server/share
            return NETWORK
        text = os.path.abspath(text)
        anchor = Path(text).anchor
        if anchor and drive_type(anchor) == DRIVE_REMOTE:
            return NETWORK
        if any(inside(text, root) or inside(text, os.path.realpath(root)) for root in one_drive_roots()):
            return ONE_DRIVE
    return None


def check(folder: str | Path) -> None:
    """AOI-SET-024 naming `folder` and why, when it cannot hold a workspace."""
    why = refusal(folder)
    if why is not None:
        raise WorkspaceError("AOI-SET-024", path=str(folder), reason=why)
