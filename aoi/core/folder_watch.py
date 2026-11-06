"""The watched input folder (REQ-INSP-020, ADR 0024 D26): a frame source for the inspection cycle that takes each
complete image file the imaging station writes to the input folder, oldest first. Its name keeps the Engineering
standard's capture name (`NAME`, `docs/schemas/input-file-naming.md`). A file is complete once two looks found the same
size and modification time and it has held them for `SETTLE_S`. It is claimed by moving it to `working/`, so no other
reader takes it, then read with its SHA-256, which its record keeps (migration 0031); once the record is saved the file
goes to `done/`. A file whose name breaks the contract, whose name is in `done/` or whose image a record already judged,
or which cannot be read goes to `failed/` with a coded alarm. A file whose board was not saved goes back to the input
folder, so it is inspected when the line runs again, as one left in `working/` by a station that stopped. Nothing is
ever deleted: `done/` and `failed/` keep the originals until an Admin removes them (ADR 0024 D20)."""

from __future__ import annotations

import contextlib
import os
import re
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import numpy as np

from ..errors import QT_TRANSLATE_NOOP, AoiError, system_reason
from .cycle import FrameMeta

NAME = re.compile(
    r"(?P<board_model>.+)_(?P<revision>[A-Za-z0-9-]{1,16})_(?P<serial>[A-Za-z0-9-]{1,64})_(?P<view>Top|Side|Bottom)"
    r"_(?P<time>\d{8}T\d{6}Z)\.(?:png|jpe?g)",
    re.IGNORECASE,
)  # the fields after the board model hold no "_", so a board model's own "_" stays in it
VIEWS = {"top": "Top", "side": "Side", "bottom": "Bottom"}
EXTS = (".png", ".jpg", ".jpeg")  # PNG, or a customer's JPEG (Engineering, "Capture")
SETTLE_S = 0.5  # a file whose size and modification time held this long over two looks is complete
LOOK_S = 0.25  # how often a running line looks: a file is inspected within 2 s of its arrival
WORKING, DONE, FAILED = "working", "done", "failed"

# Why a file is not taken, as phrases the alarm list shows translated (#198)
NOT_THE_PATTERN = QT_TRANSLATE_NOOP(
    "Errors", "its name is not <board model>_<revision>_<serial>_<view>_<UTC time>.png, such as {example}"
)
NOT_A_TIME = QT_TRANSLATE_NOOP("Errors", "its time {time} is not a real date and time")
SAME_NAME = QT_TRANSLATE_NOOP("Errors", "a file of the same name is in done/")
SAME_IMAGE = QT_TRANSLATE_NOOP("Errors", "the same image was inspected before, as {earlier}")
NOT_DECODED = QT_TRANSLATE_NOOP("Errors", "it could not be decoded as an image.")
EXAMPLE = "TBOX-A1_R3_0001_Top_20261106T103000Z.png"


@dataclass(frozen=True)
class BoardName:
    """What a file name of the contract says: the board model, the PCB revision, the board's serial (its board ID),
    its view and its capture time (UTC, ISO 8601)."""

    board_model: str
    revision: str
    serial: str
    view: str
    captured: str


def parse(name: str) -> BoardName:
    """The contract's fields of a file name; AOI-INSP-020 with the reason when it breaks the contract."""
    m = NAME.fullmatch(name)
    if m is None:
        raise AoiError("AOI-INSP-020", file=name, reason=NOT_THE_PATTERN.fill(example=EXAMPLE))
    try:
        at = datetime.strptime(m["time"].upper(), "%Y%m%dT%H%M%SZ").replace(tzinfo=UTC)
    except ValueError:
        raise AoiError("AOI-INSP-020", file=name, reason=NOT_A_TIME.fill(time=m["time"])) from None
    return BoardName(m["board_model"], m["revision"], m["serial"], VIEWS[m["view"].lower()], at.isoformat())


def board_id(path: str | Path) -> str:
    """The board ID a result file names: the serial of a file name of the contract, or the file's stem for one that
    keeps none (a board an operator loaded by hand)."""
    try:
        return parse(Path(path).name).serial
    except AoiError:
        return Path(path).stem


class FolderWatch:
    """The input folder `folder` as a frame source. `load` reads a file as the context does (its size limits) with its
    SHA-256; `inspected` gives the image file of a record that judged an image of that SHA-256, or None; `refused` gets
    each file moved to `failed/` with its error, and the folder's error once until the folder answers again. One
    station per input folder; `grab` and `finish` run on one thread at a time."""

    def __init__(
        self,
        folder: Path,
        load: Callable[[Path], tuple[np.ndarray, str]],
        inspected: Callable[[str], Path | None],
        refused: Callable[[AoiError], None],
        settle_s: float = SETTLE_S,
    ) -> None:
        self.folder, self.load, self.inspected, self.refused, self.settle_s = folder, load, inspected, refused, settle_s
        self.seen: dict[str, tuple[tuple[int, int], float]] = {}  # name: (size, mtime) and since when it held
        self.waiting = 0  # image files in the input folder at the last look: the queue depth
        self.claimed: dict[Path, Path] = {}  # the done/ path a record names: its file in working/
        self.unmoved: dict[Path, Path] = {}  # a saved board's file in working/ that could not reach done/ yet
        self.lost = False  # the folder's error was told and the folder has not answered since
        for sub in (WORKING, DONE, FAILED):
            (folder / sub).mkdir(exist_ok=True)  # made in the input folder; the input folder itself never is

    def grab(self, board_model: str) -> tuple[np.ndarray, FrameMeta] | None:
        """The next complete file of `board_model`, read and claimed, with the done/ path its record names, the view its
        name gives and its SHA-256; None while none is complete (never the end: the line waits). A file of another
        board model stays where it is and stops the line with AOI-INSP-024: a line runs one board model."""
        try:
            self._tidy()
            files = self._look()
        except OSError as e:
            if not self.lost:
                self.lost = True
                self.refused(AoiError("AOI-INSP-023", str(e), folder=str(self.folder), reason=system_reason(e)))
            return None
        self.lost = False
        for name in files:
            src, done = self.folder / name, self.folder / DONE / name
            try:
                board = parse(name)
                if done.exists():
                    raise AoiError("AOI-INSP-021", file=name, reason=SAME_NAME)
            except AoiError as e:
                self._refuse(src, e)
                continue
            if board.board_model != board_model:
                raise AoiError("AOI-INSP-024", file=name, named=board.board_model, board_model=board_model)
            work = self.folder / WORKING / name
            try:
                os.replace(src, work)  # the claim; refused while the imaging station still holds the file open
            except OSError:
                continue
            self.seen.pop(name, None)
            try:
                frame, sha = self.load(work)
            except AoiError as e:
                self._refuse(work, AoiError("AOI-INSP-022", str(e), file=name, reason=e.what))
                continue
            except Exception as e:  # a decoder's own failure: the file is the cause, the line goes on
                self._refuse(work, AoiError("AOI-INSP-022", repr(e), file=name, reason=NOT_DECODED))
                continue
            if (earlier := self.inspected(sha)) == done:  # saved before a stop moved it: done now, nothing repeated
                self.unmoved[work] = done
                continue
            if earlier is not None:
                self._refuse(work, AoiError("AOI-INSP-021", file=name, reason=SAME_IMAGE.fill(earlier=earlier.name)))
                continue
            self.claimed[done] = work
            return frame, FrameMeta(done, board.view, sha)
        return None

    def finish(self, meta: FrameMeta, saved: bool) -> None:
        """After the board of `meta`: to done/ when its record was saved, else back to the input folder, where the line
        takes it again. Never raises: a move the folder refuses now is made at a later look."""
        work = self.claimed.pop(meta.path)
        if saved:
            self.unmoved[work] = meta.path
        with contextlib.suppress(OSError):
            self._tidy()

    def _tidy(self) -> None:
        """Move each saved board's file to done/, and put back in the input folder each file left in working/ that no
        board in hand holds (a board not saved, or a station that stopped during one), unless one of its name is
        there."""
        for work, done in list(self.unmoved.items()):
            os.replace(work, done)
            del self.unmoved[work]
        held = set(self.claimed.values()) | set(self.unmoved)
        for left in (self.folder / WORKING).iterdir():
            if left not in held and not (self.folder / left.name).exists():
                os.replace(left, self.folder / left.name)

    def _look(self) -> list[str]:
        """The image files of the input folder that are complete, oldest first, and the queue depth. A file first seen
        counts its hold from its modification time when that is under `settle_s` old, so a file copied in before the
        line looked waits no longer than it must; any change starts the hold again from the look that saw it."""
        now, wall, sizes = time.monotonic(), time.time(), {}
        with os.scandir(self.folder) as it:
            for e in it:
                if e.is_file() and not e.name.startswith((".", "~")) and Path(e.name).suffix.lower() in EXTS:
                    st = e.stat()
                    sizes[e.name] = (st.st_size, st.st_mtime_ns)
        before, self.seen = self.seen, {}
        for n, sig in sizes.items():
            if n in before and before[n][0] == sig:
                self.seen[n] = before[n]
            elif n in before:
                self.seen[n] = (sig, now)
            else:
                self.seen[n] = (sig, now - min(max(0.0, wall - sig[1] / 1e9), self.settle_s))
        self.waiting = len(sizes)
        ready = [
            n
            for n, (sig, since) in self.seen.items()
            if n in before and before[n][0] == sig and sig[0] > 0 and now - since >= self.settle_s
        ]
        return sorted(ready, key=lambda n: (self.seen[n][0][1], n))

    def _refuse(self, path: Path, e: AoiError) -> None:
        """Move `path` to failed/ (under a free name: no move replaces a file) and tell `refused`; one that cannot be
        moved is tried again at the next look, and told then."""
        target = self.folder / FAILED / path.name
        while target.exists():
            target = target.with_stem(f"{path.stem}~{uuid.uuid4().hex[:8]}")
        try:
            os.replace(path, target)
        except OSError:
            return
        self.seen.pop(path.name, None)
        self.refused(e)
