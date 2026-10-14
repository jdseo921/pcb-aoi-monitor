"""One catalogue of error codes (REQ-LOG-004, REQ-SET-019; stage S12).

Every error a user can see is an ``AoiError`` with a code ``AOI-<AREA>-<NNN>``, a plain message that says
what happened and what to do, and optional ``detail``, the technical words for the log and the dialog's Show Details,
never for the message (A5 of the 2026-10 business-readiness brief). The areas are the
requirement register's (docs/requirements/README.md). ``docs/error-codes.md`` is generated from ``CODES``
by ``python -m aoi.errors``; a test fails when the two differ.
"""

from __future__ import annotations

import argparse
import errno
import sqlite3
import sys
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

AREAS = ("INSP", "CMP", "TRN", "TST", "RCP", "LOG", "P3D", "USR", "SET", "CAM", "ROB", "MES")
DOC_PATH = Path(__file__).resolve().parents[1] / "docs" / "error-codes.md"


class Phrase(str):
    """English text a screen shows in the UI language (#198): `source` is marked for pyside6-lupdate under `context`
    and filled with `values`, plain values or phrases in turn. The str is the English text filled in, which the log, an
    alarm's message and the docs keep; aoi/ui/errors.py `phrase_text()` translates the source first and fills it after,
    so a translation puts the values in its own order and no sentence is glued from English pieces."""

    context: str
    source: str
    values: dict[str, object]
    filled: bool  # False for a template such as a catalogue text: its {placeholders} stay as they are

    def __new__(cls, context: str, source: str, values: dict[str, object] | None = None) -> Phrase:
        self = super().__new__(cls, source if values is None else source.format(**values))
        self.context, self.source, self.values, self.filled = context, source, values or {}, values is not None
        return self

    def __reduce__(self) -> tuple[type[Phrase], tuple[str, str, dict[str, object] | None]]:
        """How copy, deepcopy and pickle rebuild the phrase: a template without values, so it is not filled."""
        return Phrase, (self.context, self.source, self.values if self.filled else None)

    def fill(self, **values: object) -> Phrase:
        """This phrase with its {placeholders} filled in."""
        return Phrase(self.context, self.source, values)

    def to_json(self) -> dict[str, object]:
        """The phrase as JSON, so a stored alarm is shown in the UI language of the day it is read; a value that is
        not a phrase, a number or None is kept as its English text."""
        values: dict[str, object] = {
            k: v if isinstance(v, (int, float, type(None))) else str(v) for k, v in self.values.items()
        }
        values.update((k, v.to_json()) for k, v in self.values.items() if isinstance(v, Phrase))
        return {"context": self.context, "source": self.source, "values": values if self.filled else None}

    @classmethod
    def from_json(cls, doc: dict[str, Any]) -> Phrase:
        if doc["values"] is None:
            return cls(doc["context"], doc["source"])
        values = {k: cls.from_json(v) if isinstance(v, dict) else v for k, v in doc["values"].items()}
        return cls(doc["context"], doc["source"], values)


def joined(joint: Phrase, items: Sequence[str]) -> str:
    """`items` joined pairwise by `joint`, a phrase such as "{first}; {rest}", so a translation joins them its own way;
    "" for none (#198)."""
    text = items[-1] if items else ""
    for item in reversed(items[:-1]):
        text = joint.fill(first=item, rest=text)
    return text


def QT_TRANSLATE_NOOP(context: str, text: str) -> Phrase:
    """Mark `text` for pyside6-lupdate, which finds the call by this name, under `context`, as a phrase a screen
    translates; no Qt here, since the engine raises errors too. Pages take it from aoi/ui/pages/base.py."""
    return Phrase(context, text)


# What a refusal of the system means, in words a user acts on (A5 of the 2026-10 business-readiness brief, F8). The
# system's own text, which can name an exception class, an errno or SQLite's words, goes to an error's detail, which the
# log and the dialog's Details hold, and never into what a message says (`system_reason`, `system_detail`).
FULL = QT_TRANSLATE_NOOP("Errors", "the drive is full")
DENIED = QT_TRANSLATE_NOOP("Errors", "the system refused access to it: it may be read-only, or open in another app")
IN_USE = QT_TRANSLATE_NOOP("Errors", "another app has it open")
MISSING = QT_TRANSLATE_NOOP("Errors", "it is not there")
GONE = QT_TRANSLATE_NOOP("Errors", "its folder or drive is not there")  # MISSING, for a file being written
WRITE_PROTECTED = QT_TRANSLATE_NOOP("Errors", "the drive is write-protected")
NOT_READY = QT_TRANSLATE_NOOP("Errors", "the drive is not ready: it may have been removed")
NOT_READ = QT_TRANSLATE_NOOP("Errors", "the drive could not be read or written")
TOO_LONG = QT_TRANSLATE_NOOP("Errors", "its path is too long")
TAKEN = QT_TRANSLATE_NOOP("Errors", "something of that name is already there")
NOT_EMPTY = QT_TRANSLATE_NOOP("Errors", "the folder still holds files, which another app may have open")
A_FOLDER = QT_TRANSLATE_NOOP("Errors", "it is a folder, not a file")
NOT_A_FOLDER = QT_TRANSLATE_NOOP("Errors", "part of its path is a file, not a folder")
DB_HELD = QT_TRANSLATE_NOOP("Errors", "another app holds the database")
DB_DAMAGED = QT_TRANSLATE_NOOP("Errors", "the database file is damaged")
DB_NOT_OPENED = QT_TRANSLATE_NOOP("Errors", "the database file could not be opened")
DB_READ_ONLY = QT_TRANSLATE_NOOP("Errors", "the database file or its folder is set to read-only")
DB_REFUSED = QT_TRANSLATE_NOOP("Errors", "the database refused it")
REFUSED = QT_TRANSLATE_NOOP("Errors", "the system refused it")
_BY_ERRNO = {  # by name: a system without one of these numbers leaves it out
    getattr(errno, name): reason
    for names, reason in (
        (("ENOSPC", "EDQUOT"), FULL), (("EACCES", "EPERM"), DENIED), (("EBUSY", "ETXTBSY"), IN_USE),
        (("ENOENT",), MISSING), (("EROFS",), WRITE_PROTECTED), (("ENODEV", "ENXIO"), NOT_READY), (("EIO",), NOT_READ),
        (("ENAMETOOLONG",), TOO_LONG), (("EEXIST",), TAKEN), (("ENOTEMPTY",), NOT_EMPTY),
        (("EISDIR",), A_FOLDER), (("ENOTDIR",), NOT_A_FOLDER),
    )
    for name in names
    if hasattr(errno, name)
}  # fmt: skip
_BY_WINERROR = {  # Windows' own numbers, which say more than the errno Python maps them to
    5: DENIED, 32: IN_USE, 33: IN_USE, 2: MISSING, 3: MISSING, 19: WRITE_PROTECTED, 21: NOT_READY, 15: NOT_READY,
    112: FULL, 39: FULL, 23: NOT_READ, 1117: NOT_READ, 206: TOO_LONG, 80: TAKEN, 183: TAKEN, 145: NOT_EMPTY,
    267: NOT_A_FOLDER,
}  # fmt: skip


def system_reason(e: BaseException | None, writing: bool = False) -> Phrase:
    """What the system's refusal `e` means for the user, as a phrase that names no exception, errno or SQLite text: a
    full, removed or write-protected drive, a file another app has open, one that is not there (its folder or drive,
    when `writing` it), a damaged database; "the system refused it" for anything else. Windows' own number is read from
    `e` or the error it was raised from, as a file written crash-safe re-raises one under the file's name. The words of
    `e` itself go in the error's detail (`system_detail`)."""
    reason = _system_reason(e)
    return GONE if writing and reason == MISSING else reason


def _system_reason(e: BaseException | None) -> Phrase:
    if isinstance(e, sqlite3.Error):
        text = str(e).lower()
        if "locked" in text or "busy" in text:
            return DB_HELD
        if "not a database" in text or "malformed" in text or "corrupt" in text:
            return DB_DAMAGED
        if "disk i/o" in text or "disk is full" in text or "full" in text:
            return NOT_READ if "i/o" in text else FULL
        if "unable to open" in text:
            return DB_NOT_OPENED
        if "readonly" in text or "read-only" in text:
            return DB_READ_ONLY
        return DB_REFUSED
    if isinstance(e, OSError):
        winerror = getattr(e, "winerror", None) or getattr(e.__cause__, "winerror", None)
        if winerror in _BY_WINERROR:
            return _BY_WINERROR[winerror]
        return _BY_ERRNO.get(e.errno or 0, REFUSED)
    return REFUSED


def system_detail(e: BaseException | None) -> str | None:
    """The technical words of `e` for the log and the dialog's Details: its class and its own text."""
    return None if e is None else f"{type(e).__name__}: {e}"


@dataclass(frozen=True)
class ErrorCode:
    code: str
    title: str
    what: str  # what happened; {placeholders} are filled at the raise site
    action: str  # what the user does next
    personal: tuple[str, ...] = ()  # placeholders that hold personal data, which the log never holds (REQ-LOG-004)


CODES: dict[str, ErrorCode] = {
    c.code: c
    for c in (
        ErrorCode(
            "AOI-INSP-001",
            QT_TRANSLATE_NOOP("Errors", "Image cannot be read"),
            QT_TRANSLATE_NOOP("Errors", "The file {path} could not be opened as an image."),
            QT_TRANSLATE_NOOP("Errors", "Check that the file exists and is a PNG, JPG, BMP or TIFF image."),
        ),
        ErrorCode(
            "AOI-INSP-002",
            QT_TRANSLATE_NOOP("Errors", "Image cannot be written"),
            QT_TRANSLATE_NOOP("Errors", "The image {path} could not be encoded for writing."),
            QT_TRANSLATE_NOOP("Errors", "Check the file name's extension (.png or .jpg) and try again."),
        ),
        ErrorCode(
            "AOI-INSP-003",
            QT_TRANSLATE_NOOP("Errors", "Board judged NG"),
            QT_TRANSLATE_NOOP("Errors", "Board {board} was judged NG with {defects} defect(s)."),
            QT_TRANSLATE_NOOP("Errors", "Review the result on the Compare page before the board moves on."),
        ),
        ErrorCode(
            "AOI-INSP-004",
            QT_TRANSLATE_NOOP("Errors", "File format not supported"),
            QT_TRANSLATE_NOOP(
                "Errors",
                "The file {path} does not hold a PNG, JPG, BMP or TIFF image; the format is read from the file's "
                "content, not its name.",
            ),
            QT_TRANSLATE_NOOP(
                "Errors", "Save the image as PNG, JPG, BMP or TIFF with an image tool and load that file."
            ),
        ),
        ErrorCode(
            "AOI-INSP-005",
            QT_TRANSLATE_NOOP("Errors", "Image over the size limit"),
            QT_TRANSLATE_NOOP("Errors", "The image {path} is {size}, over the limit of {limit}."),
            QT_TRANSLATE_NOOP(
                "Errors",
                "Use a smaller image, or ask an Admin to raise the limit: max_image_megapixels or max_image_megabytes "
                "in settings.json, in the default workspace folder.",
            ),
        ),
        ErrorCode(
            "AOI-INSP-006",
            QT_TRANSLATE_NOOP("Errors", "Image file cannot be decoded"),
            QT_TRANSLATE_NOOP("Errors", "The {kind} image {path} could not be decoded: {reason}."),
            QT_TRANSLATE_NOOP(
                "Errors",
                "Copy the file again from the camera or its source; if it fails again, save it as PNG or JPG with an "
                "image tool and load that file.",
            ),
        ),
        ErrorCode(
            "AOI-INSP-007",
            QT_TRANSLATE_NOOP("Errors", "Image side too long"),
            QT_TRANSLATE_NOOP(
                "Errors",
                "The image {path} is {width} × {height} px; a side over {limit} px is beyond what this app decodes.",
            ),
            QT_TRANSLATE_NOOP(
                "Errors",
                "Crop or scale the image so that no side is over {limit} px; this limit is the decoder's and cannot be "
                "raised.",
            ),
        ),
        ErrorCode(
            "AOI-INSP-008",
            QT_TRANSLATE_NOOP("Errors", "Result not saved"),
            QT_TRANSLATE_NOOP(
                "Errors", "The result of {file} was shown but could not be saved, so it is not in Logs & Export."
            ),
            QT_TRANSLATE_NOOP(
                "Errors",
                "Check the free disk space and that the workspace folder can be written, then press Next Board to "
                "carry on and inspect {file} again later.",
            ),
        ),
        ErrorCode(
            "AOI-INSP-009",
            QT_TRANSLATE_NOOP("Errors", "Golden board file not available"),
            QT_TRANSLATE_NOOP(
                "Errors",
                "Board model {board} names {file} as its Golden board, but {reason}, so no board of it can be compared"
                " with the Golden board. The board was not inspected.",
            ),
            QT_TRANSLATE_NOOP(
                "Errors",
                "Put the file back, for example from a backup of the workspace, or have an Engineer choose another OK"
                " sample as the Golden board with Set Reference on Training; then inspect the board again.",
            ),
        ),
        ErrorCode(
            "AOI-INSP-010",
            QT_TRANSLATE_NOOP("Errors", "Nothing can judge the board"),
            QT_TRANSLATE_NOOP(
                "Errors",
                "No check can judge this board of board model {board}: {reason}. The board was given no verdict.",
            ),
            QT_TRANSLATE_NOOP(
                "Errors",
                "An Engineer sets a Golden board, or trains or activates an AI model, on Training, or turns on the"
                " Golden board comparison or the AI model in the Recipe Editor; then inspect the board again.",
            ),
        ),
        ErrorCode(
            "AOI-INSP-011",
            QT_TRANSLATE_NOOP("Errors", "Image too small to inspect"),
            QT_TRANSLATE_NOOP(
                "Errors", "The {image} is {width} × {height} px; inspecting needs at least {minimum} px on each side."
            ),
            QT_TRANSLATE_NOOP(
                "Errors",
                "Load a picture of the whole board as the camera takes it; if the Golden board is the small one, an"
                " Engineer sets another on Training.",
            ),
        ),
        ErrorCode(
            "AOI-INSP-012",
            QT_TRANSLATE_NOOP("Errors", "Run stopped: board model changed"),
            QT_TRANSLATE_NOOP(
                "Errors",
                "The board model changed from {old} to {new} during a run, so the run stopped after the board in "
                "hand; the boards inspected before the change are saved under {old}.",
            ),
            QT_TRANSLATE_NOOP(
                "Errors", "Check the board model in the header, then press Start to carry on with the queue under it."
            ),
        ),
        ErrorCode(
            "AOI-INSP-013",
            QT_TRANSLATE_NOOP("Errors", "AI model, recipe, scale or Golden board changed during a run"),
            QT_TRANSLATE_NOOP(
                "Errors",
                "The AI model, recipe, scale or Golden board of {board} changed during a run (training ended, a version"
                " was activated while the recipe has the AI check on, a recipe saved, a scale set while it holds a size"
                " in mm, or a Golden board set), so {file} and the boards after it are judged with what is active now;"
                " the boards before keep what judged them.",
            ),
            QT_TRANSLATE_NOOP(
                "Errors",
                "No action is needed: each record names the AI model version active when its board was judged, the"
                " recipe revision that judged it, which says whether the AI check ran, and the Golden board it was"
                " judged against.",
            ),
        ),
        ErrorCode(
            "AOI-INSP-014",
            QT_TRANSLATE_NOOP("Errors", "Result not saved: path too long"),
            QT_TRANSLATE_NOOP(
                "Errors",
                "The result of {file} was shown but could not be saved, so it is not in Logs & Export: the system "
                "refused the path of its evidence files in the workspace folder {workspace} as too long.",
            ),
            QT_TRANSLATE_NOOP(
                "Errors",
                "Ask an Admin to save a workspace folder with a shorter path on Settings and then, with the app "
                "closed, to copy everything in the folder {workspace} into that folder, or to turn on long paths in "
                "Windows; then inspect {file} again.",
            ),
        ),
        ErrorCode(
            "AOI-INSP-015",
            QT_TRANSLATE_NOOP("Errors", "Board cannot be reviewed"),
            QT_TRANSLATE_NOOP("Errors", "Record {record} cannot be reviewed: {reason}. Nothing was changed."),
            QT_TRANSLATE_NOOP(
                "Errors",
                "Review an NG or WARN board that is still in Logs & Export, and give a reason when you mark a False"
                " call.",
            ),
        ),
        ErrorCode(
            "AOI-INSP-016",
            QT_TRANSLATE_NOOP("Errors", "Shift check needed"),
            QT_TRANSLATE_NOOP(
                "Errors",
                "Boards of {board_model} are inspected only after a shift check judges every master sample right, and"
                " {reason}. No board was inspected.",
            ),
            QT_TRANSLATE_NOOP(
                "Errors",
                "Press Shift Check (F7) to judge the master samples. If one is judged wrongly, call an Engineer to"
                " check the recipe, the AI model and the Golden board before production goes on.",
            ),
        ),
        ErrorCode(
            "AOI-INSP-017",
            QT_TRANSLATE_NOOP("Errors", "Shift check has no master samples"),
            QT_TRANSLATE_NOOP(
                "Errors",
                "Board model {board_model} has no sample labelled {label} to judge, so the shift check cannot run."
                " Nothing was stored.",
            ),
            QT_TRANSLATE_NOOP(
                "Errors",
                "Ask an Engineer to import a known-OK board and a known-NG board of each Critical defect type in"
                " Training. Until then, an Admin can turn the shift check off on Settings.",
            ),
        ),
        ErrorCode(
            "AOI-INSP-018",
            QT_TRANSLATE_NOOP("Errors", "The line has drifted"),
            QT_TRANSLATE_NOOP(
                "Errors",
                "On {board} ({view}), a measure of the newest boards judged by the active AI model and recipe moved"
                " further than chance explains from the boards judged before them: {measure}. No verdict was changed.",
            ),
            QT_TRANSLATE_NOOP(
                "Errors",
                "Look at the boards and the station: the lighting, the camera and its focus, the board revision and the"
                " parts supplier. Review the calls on Logs & Export; if one of these changed, retrain the AI model or"
                " tune the recipe and validate it again.",
            ),
        ),
        ErrorCode(
            "AOI-CMP-001",
            QT_TRANSLATE_NOOP("Errors", "Result has no stored heatmaps"),
            QT_TRANSLATE_NOOP(
                "Errors",
                "The result of {file} was saved without its difference and AI maps, or they were deleted after the"
                " retention period of {days} days.",
            ),
            QT_TRANSLATE_NOOP(
                "Errors",
                "The decision table is the stored one; use Side by side or Defect boxes only, or inspect the board"
                " again on Inspection to see its heatmaps.",
            ),
        ),
        ErrorCode(
            "AOI-CMP-002",
            QT_TRANSLATE_NOOP("Errors", "Result has no stored decision table"),
            QT_TRANSLATE_NOOP(
                "Errors",
                "Record {id} ({file}) has no stored decision table that can be read: it was saved before migration"
                " 0006, it is damaged, or no record has that number or UUID.",
            ),
            QT_TRANSLATE_NOOP("Errors", "Inspect the board again on Inspection; Compare then opens the new result."),
        ),
        ErrorCode(
            "AOI-CMP-003",
            QT_TRANSLATE_NOOP("Errors", "Stored map cannot be read"),
            QT_TRANSLATE_NOOP("Errors", "The stored map {file} could not be read: {reason}."),
            QT_TRANSLATE_NOOP(
                "Errors",
                "The stored verdict and decision table still stand. Close any program that has the file open and open "
                "the result again; if the file is damaged, inspect the board again on Inspection.",
            ),
        ),
        ErrorCode(
            "AOI-CMP-004",
            QT_TRANSLATE_NOOP("Errors", "Result cannot be judged again"),
            QT_TRANSLATE_NOOP(
                "Errors",
                "The result of {file} cannot be judged again with other thresholds: what it was judged on is no longer"
                " stored ({missing}).",
            ),
            QT_TRANSLATE_NOOP(
                "Errors",
                "Its stored verdict and decision table still stand. Inspect the board again on Inspection, then try the"
                " thresholds on the new result. The maps of OK results are deleted {days} days after inspection; NG and"
                " WARN maps are kept.",
            ),
        ),
        ErrorCode(
            "AOI-CMP-005",
            QT_TRANSLATE_NOOP("Errors", "Thresholds of another board model"),
            QT_TRANSLATE_NOOP(
                "Errors",
                "The thresholds tried are board model {tried}'s, but the result of {file} was judged for board model"
                " {judged}.",
            ),
            QT_TRANSLATE_NOOP(
                "Errors",
                "Nothing was judged. Open the result on Compare with its own board model picked, then try the "
                "thresholds again.",
            ),
        ),
        ErrorCode(
            "AOI-CMP-006",
            QT_TRANSLATE_NOOP("Errors", "Stored board picture cannot be read"),
            QT_TRANSLATE_NOOP(
                "Errors",
                "The stored board picture {file} of this result could not be read ({error_code} {error_title}).",
            ),
            QT_TRANSLATE_NOOP(
                "Errors",
                "The stored verdict and decision table still stand. Close any program that has the file open and open "
                "the result again; if the file is damaged, inspect the board again on Inspection.",
            ),
        ),
        ErrorCode(
            "AOI-TRN-001",
            QT_TRANSLATE_NOOP("Errors", "AI model file refused"),
            QT_TRANSLATE_NOOP(
                "Errors",
                "AI model file refused: {path} could not be loaded as an AI model file this app wrote ({reason}).",
            ),
            QT_TRANSLATE_NOOP("Errors", "Train the board model again."),
        ),
        ErrorCode(
            "AOI-TRN-002",
            QT_TRANSLATE_NOOP("Errors", "Not enough good boards to train"),
            QT_TRANSLATE_NOOP("Errors", "Training needs at least 2 OK (good board) images; {found} found."),
            QT_TRANSLATE_NOOP("Errors", "Upload more OK images for this board model, then train again."),
        ),
        ErrorCode(
            "AOI-TRN-003",
            QT_TRANSLATE_NOOP("Errors", "No trained AI model"),
            QT_TRANSLATE_NOOP(
                "Errors", "Board model {board} has no trained AI model, so only the golden-board comparison runs."
            ),
            QT_TRANSLATE_NOOP("Errors", "Train an AI model on the Training page when the AI checks are needed."),
        ),
        ErrorCode(
            "AOI-TRN-004",
            QT_TRANSLATE_NOOP("Errors", "Training gave an AI model that cannot judge boards"),
            QT_TRANSLATE_NOOP(
                "Errors",
                "Training made an AI model that cannot judge boards ({reason}), so it was not saved; the AI model in "
                "use is unchanged.",
            ),
            QT_TRANSLATE_NOOP(
                "Errors",
                "Import photos of several different good boards (copies of one photo leave nothing to learn), then "
                "train again.",
            ),
        ),
        ErrorCode(
            "AOI-TRN-005",
            QT_TRANSLATE_NOOP("Errors", "Board model name already taken"),
            QT_TRANSLATE_NOOP(
                "Errors",
                "Board model {existing} already exists, and {name} differs from it only in upper and lower case; "
                "Windows would store the AI model and golden board files of both as the same files.",
            ),
            QT_TRANSLATE_NOOP(
                "Errors",
                "Select {existing} in the top bar, or give the new board model a name that differs in more than case.",
            ),
        ),
        ErrorCode(
            "AOI-TRN-006",
            QT_TRANSLATE_NOOP("Errors", "Reference must be a good board"),
            QT_TRANSLATE_NOOP(
                "Errors",
                "Sample {sample} is labelled {label}; only an OK (good board) sample can be the reference image that "
                "inspections compare against.",
            ),
            QT_TRANSLATE_NOOP(
                "Errors",
                "Select an OK sample, or relabel this one OK if it shows a good board, then press Set Reference again.",
            ),
        ),
        ErrorCode(
            "AOI-TRN-007",
            QT_TRANSLATE_NOOP("Errors", "Reference sample cannot change"),
            QT_TRANSLATE_NOOP(
                "Errors",
                "Sample {sample} is the reference image that inspections compare against, so it cannot be {change} "
                "while it is; it was left unchanged.",
            ),
            QT_TRANSLATE_NOOP("Errors", "Select another good (OK) sample and press Set Reference; then try again."),
        ),
        ErrorCode(
            "AOI-TRN-008",
            QT_TRANSLATE_NOOP("Errors", "Images not imported"),
            QT_TRANSLATE_NOOP(
                "Errors",
                "Copying {path} into the workspace failed ({reason}), so none of the {count} image(s) picked were"
                " imported.",
            ),
            QT_TRANSLATE_NOOP(
                "Errors",
                "Check that the file is still there and can be opened and that the workspace drive has free space, then"
                " import the images again.",
            ),
        ),
        ErrorCode(
            "AOI-TRN-009",
            QT_TRANSLATE_NOOP("Errors", "Import stopped part-way"),
            QT_TRANSLATE_NOOP(
                "Errors",
                "Copying {path} into the workspace failed ({reason}), so the import stopped at image {at} of {total};"
                " the {imported} image(s) imported before it stay in the sample table.",
            ),
            QT_TRANSLATE_NOOP(
                "Errors",
                "Check that the file is still there and can be opened and that the workspace drive has free space,"
                " then, with {name} picked in the header, press Import again: the {imported} image(s) already imported"
                " are skipped.",
            ),
        ),
        ErrorCode(
            "AOI-TRN-010",
            QT_TRANSLATE_NOOP("Errors", "Import stopped by an error"),
            QT_TRANSLATE_NOOP(
                "Errors",
                "Importing {path} failed ({reason}), so the import stopped at image {at} of {total}; the {imported}"
                " image(s) imported before it stay in the sample table.",
            ),
            QT_TRANSLATE_NOOP(
                "Errors",
                "Fix what stopped it (the log file in the workspace's logs folder has the details; send it to support"
                " if the cause is unclear), then, with {name} picked in the header, press Import again: the {imported}"
                " image(s) already imported are skipped.",
            ),
        ),
        ErrorCode(
            "AOI-TRN-011",
            QT_TRANSLATE_NOOP("Errors", "Images not imported: path too long"),
            QT_TRANSLATE_NOOP(
                "Errors",
                "None of the {count} image(s) picked were imported: the system refused the path of the copy of {path}"
                " in the workspace folder {workspace} as too long.",
            ),
            QT_TRANSLATE_NOOP(
                "Errors",
                "Ask an Admin to save a workspace folder with a shorter path on Settings and then, with the app closed,"
                " to copy everything in the folder {workspace} into that folder, or to turn on long paths in Windows;"
                " then import the images again.",
            ),
        ),
        ErrorCode(
            "AOI-TRN-012",
            QT_TRANSLATE_NOOP("Errors", "AI model calibration cannot be read"),
            QT_TRANSLATE_NOOP(
                "Errors",
                "AI model {version} of board model {board} has no usable calibration in the AI model registry.",
            ),
            QT_TRANSLATE_NOOP(
                "Errors",
                "For the next boards, train again or activate another version on Training, or set a value of your own.",
            ),
        ),
        ErrorCode(
            "AOI-TRN-013",
            QT_TRANSLATE_NOOP("Errors", "NG image needs a defect type"),
            QT_TRANSLATE_NOOP(
                "Errors",
                "{path} was not taken as an NG sample: an NG sample needs one of the 37 defect types of the defect"
                " classification table, and {why}.",
            ),
            QT_TRANSLATE_NOOP("Errors", "Pick the defect type the image shows, then try again."),
        ),
        ErrorCode(
            "AOI-TRN-014",
            QT_TRANSLATE_NOOP("Errors", "Image changed while it was copied"),
            QT_TRANSLATE_NOOP(
                "Errors",
                "{path} changed while it was copied into the workspace: its SHA-256 after the copy differs from the"
                " one checked before it, so it was not imported.",
            ),
            QT_TRANSLATE_NOOP(
                "Errors",
                "Wait until the file is complete (a camera or a copy may still be writing it), then import it again.",
            ),
        ),
        ErrorCode(
            "AOI-TRN-015",
            QT_TRANSLATE_NOOP("Errors", "Image already imported"),
            QT_TRANSLATE_NOOP(
                "Errors",
                "{path} was skipped: board model {board_model} already has the same image (the same SHA-256) as"
                " sample {sample}, labelled {label}.",
            ),
            QT_TRANSLATE_NOOP("Errors", "Nothing to do: the image is in the sample table once."),
        ),
        ErrorCode(
            "AOI-TRN-016",
            QT_TRANSLATE_NOOP("Errors", "Image has no label"),
            QT_TRANSLATE_NOOP(
                "Errors", "{path} was not imported: it is in neither an ok/ nor an ng/ folder, so it has no label."
            ),
            QT_TRANSLATE_NOOP(
                "Errors",
                "Pick OK or NG in its row of the import sheet, then press Import again: the images already imported"
                " are skipped.",
            ),
        ),
        ErrorCode(
            "AOI-TRN-017",
            QT_TRANSLATE_NOOP("Errors", "View not known"),
            QT_TRANSLATE_NOOP("Errors", '{path} was not imported: its view "{view}" is not one of {views}.'),
            QT_TRANSLATE_NOOP(
                "Errors", "Give the image the view it was taken from, one of {views}, and import it again."
            ),
        ),
        ErrorCode(
            "AOI-TRN-018",
            QT_TRANSLATE_NOOP("Errors", "Label not known"),
            QT_TRANSLATE_NOOP("Errors", '{path} was not given the label "{label}": it is not one of {labels}.'),
            QT_TRANSLATE_NOOP("Errors", "Give it the label OK or NG, then try again."),
        ),
        ErrorCode(
            "AOI-TRN-019",
            QT_TRANSLATE_NOOP("Errors", "Board model name not allowed"),
            QT_TRANSLATE_NOOP(
                "Errors",
                'The board model name "{name}" cannot be the name of its folders in the workspace: a folder name is'
                ' not empty, holds none of / : * ? " < > and no backslash, vertical bar or control character, does not'
                " end with a dot or a space, and is not a name the system keeps for a device (CON, NUL, COM1 and the"
                " like).",
            ),
            QT_TRANSLATE_NOOP(
                "Errors",
                "Use another name, such as TBOX-A1 Rev2: create the board model with it and add its images there."
                " Nothing was written.",
            ),
        ),
        ErrorCode(
            "AOI-TRN-020",
            QT_TRANSLATE_NOOP("Errors", "Dataset not frozen: NG labels not checked"),
            QT_TRANSLATE_NOOP("Errors", "{name} was not frozen: a second user has not checked {count} NG label(s)."),
            QT_TRANSLATE_NOOP("Errors", "Have another Engineer or Admin check each NG label, then freeze again."),
        ),
        ErrorCode(
            "AOI-TRN-021",
            QT_TRANSLATE_NOOP("Errors", "Dataset not frozen: OK labels not checked"),
            QT_TRANSLATE_NOOP(
                "Errors",
                "{name} was not frozen: {checked} of the {needed} OK label(s) to check (10 % of {ok}) are checked.",
            ),
            QT_TRANSLATE_NOOP(
                "Errors", "Draw OK labels for a check and have another Engineer or Admin check them, then freeze again."
            ),
        ),
        ErrorCode(
            "AOI-TRN-022",
            QT_TRANSLATE_NOOP("Errors", "Validation set not locked"),
            QT_TRANSLATE_NOOP("Errors", "The validation set of {name} was not locked: {reason}."),
            QT_TRANSLATE_NOOP(
                "Errors",
                "Add OK images if there are too few, freeze a new dataset version and lock its validation set; nothing"
                " was written.",
            ),
        ),
        ErrorCode(
            "AOI-TRN-023",
            QT_TRANSLATE_NOOP("Errors", "Manifest does not match"),
            QT_TRANSLATE_NOOP("Errors", "{name} does not match what was frozen: {reason}."),
            QT_TRANSLATE_NOOP(
                "Errors",
                "Train from another version, or freeze the working set again; the files are named under the Versions"
                " table.",
            ),
        ),
        ErrorCode(
            "AOI-TRN-024",
            QT_TRANSLATE_NOOP("Errors", "Dataset not frozen: no customer"),
            QT_TRANSLATE_NOOP("Errors", "{name} was not frozen: no customer is set."),
            QT_TRANSLATE_NOOP("Errors", "Enter the customer the dataset is for, then freeze it again."),
        ),
        ErrorCode(
            "AOI-TRN-025",
            QT_TRANSLATE_NOOP("Errors", "Dataset store not opened"),
            QT_TRANSLATE_NOOP("Errors", "The dataset store of {store} was not opened: {reason}."),
            QT_TRANSLATE_NOOP(
                "Errors",
                "An Admin types the store's recovery key into Settings › Dataset stores › Advanced › Restore Key… on"
                " this station when its key is missing or wrong; a file changed outside the app comes back only from a"
                " backup. Nothing was changed.",
            ),
        ),
        ErrorCode(
            "AOI-TRN-027",
            QT_TRANSLATE_NOOP("Errors", "Dataset not frozen"),
            QT_TRANSLATE_NOOP("Errors", "{name} was not frozen: {reason}."),
            QT_TRANSLATE_NOOP(
                "Errors",
                "Nothing was written. Type a board revision of 1 to 16 letters and digits, or the customer whose "
                "dataset store holds the images, and tick at least one use; label images OK or NG and run an "
                "agreement check that reaches its targets; an Admin moves the board model into a dataset store first. "
                "A board model whose store was shredded is never frozen again.",
            ),
        ),
        ErrorCode(
            "AOI-TRN-028",
            QT_TRANSLATE_NOOP("Errors", "Dataset version not found"),
            QT_TRANSLATE_NOOP("Errors", "The workspace holds no dataset version {dataset}, so nothing was verified."),
            QT_TRANSLATE_NOOP("Errors", "Show the dataset versions again and pick one of them."),
        ),
        ErrorCode(
            "AOI-TRN-030",
            QT_TRANSLATE_NOOP("Errors", "Label not changed"),
            QT_TRANSLATE_NOOP("Errors", "The label of {sample} was not changed: {reason}."),
            QT_TRANSLATE_NOOP(
                "Errors",
                "Label the image OK, NG or UNSURE, and give an NG image's defect boxes one of the 37 defect types each;"
                " then save the label again.",
            ),
        ),
        ErrorCode(
            "AOI-TRN-031",
            QT_TRANSLATE_NOOP("Errors", "Defect box outside the image"),
            QT_TRANSLATE_NOOP(
                "Errors",
                "Defect box {number} on {sample}, {w} × {h} px at x {x}, y {y}, does not lie inside the image of"
                " {width} × {height} px, so the label and its boxes were not changed.",
            ),
            QT_TRANSLATE_NOOP("Errors", "Move or resize the box so that it lies inside the image, then save again."),
        ),
        ErrorCode(
            "AOI-TRN-032",
            QT_TRANSLATE_NOOP("Errors", "Sample not found"),
            QT_TRANSLATE_NOOP("Errors", "The workspace holds no sample {sample}, so nothing was changed."),
            QT_TRANSLATE_NOOP(
                "Errors", "Show the sample table again: the sample may have been removed since it was shown."
            ),
        ),
        ErrorCode(
            "AOI-TRN-033",
            QT_TRANSLATE_NOOP("Errors", "Check refused: you labelled this image"),
            QT_TRANSLATE_NOOP(
                "Errors", "The label of {sample} was not checked: you labelled it, and a second user checks each label."
            ),
            QT_TRANSLATE_NOOP("Errors", "Ask another Engineer or Admin to check the label."),
        ),
        ErrorCode(
            "AOI-TRN-034",
            QT_TRANSLATE_NOOP("Errors", "Label cannot be checked"),
            QT_TRANSLATE_NOOP("Errors", "The label of {sample} was not checked: {reason}."),
            QT_TRANSLATE_NOOP(
                "Errors",
                "Draw an NG image's defect boxes, or label the image again, then check its label; an UNSURE image is "
                "not checked, and a label checked already needs nothing.",
            ),
        ),
        ErrorCode(
            "AOI-TRN-035",
            QT_TRANSLATE_NOOP("Errors", "Calibration set not made"),
            QT_TRANSLATE_NOOP("Errors", "The calibration set was not made: {reason}."),
            QT_TRANSLATE_NOOP(
                "Errors",
                "Pick 100 different images of one board model, each labelled OK or NG, and make the set again.",
            ),
        ),
        ErrorCode(
            "AOI-TRN-036",
            QT_TRANSLATE_NOOP("Errors", "Blind label not kept"),
            QT_TRANSLATE_NOOP("Errors", "The blind label of {sample} was not kept: {reason}."),
            QT_TRANSLATE_NOOP(
                "Errors", "Label each image of the set once, as yourself: OK, or NG with one of the 37 defect types."
            ),
        ),
        ErrorCode(
            "AOI-TRN-037",
            QT_TRANSLATE_NOOP("Errors", "Agreement check did not run"),
            QT_TRANSLATE_NOOP("Errors", "The agreement check did not run: {reason}."),
            QT_TRANSLATE_NOOP(
                "Errors",
                "Pick two different labellers who have each labelled every image of the set blind, then run the check"
                " again.",
            ),
        ),
        ErrorCode(
            "AOI-TRN-038",
            QT_TRANSLATE_NOOP("Errors", "View not known"),
            QT_TRANSLATE_NOOP("Errors", "{view} is not a camera view of this app, so nothing was read or changed."),
            QT_TRANSLATE_NOOP("Errors", "Name the view as the Inspection and Training pages do: Top, Side or Bottom."),
        ),
        ErrorCode(
            "AOI-TRN-039",
            QT_TRANSLATE_NOOP("Errors", "Dataset not frozen: no version name"),
            QT_TRANSLATE_NOOP(
                "Errors",
                "Board model {board} was not frozen: its name has no Latin letter or digit, which a dataset version is"
                " named with.",
            ),
            QT_TRANSLATE_NOOP(
                "Errors",
                "Import the images under a board model whose name has a Latin letter or digit, such as TBOX-A1, and"
                " freeze that board model.",
            ),
        ),
        ErrorCode(
            "AOI-TRN-040",
            QT_TRANSLATE_NOOP("Errors", "Dataset not frozen: version name taken"),
            QT_TRANSLATE_NOOP(
                "Errors",
                "{name} was not frozen: board model {other} has frozen versions under the same letters and digits as"
                " board model {board}, so their names would mix.",
            ),
            QT_TRANSLATE_NOOP(
                "Errors",
                "Import the images under a board model whose letters and digits differ from those of {other}, and"
                " freeze that board model.",
            ),
        ),
        ErrorCode(
            "AOI-TRN-041",
            QT_TRANSLATE_NOOP("Errors", "Dataset not frozen: manifest not written"),
            QT_TRANSLATE_NOOP("Errors", "{name} was not frozen: its manifest {path} could not be written ({reason})."),
            QT_TRANSLATE_NOOP(
                "Errors",
                "Check the free space on the workspace drive and that its datasets folder can be written, then freeze"
                " again; nothing of the version was kept.",
            ),
        ),
        ErrorCode(
            "AOI-TRN-042",
            QT_TRANSLATE_NOOP("Errors", "Dataset not frozen: path too long"),
            QT_TRANSLATE_NOOP(
                "Errors",
                "{name} was not frozen: the system refused the path of its manifest in the workspace folder {workspace}"
                " as too long.",
            ),
            QT_TRANSLATE_NOOP(
                "Errors",
                "Ask an Admin to save a workspace folder with a shorter path on Settings and then, with the app closed,"
                " to copy everything in the folder {workspace} into that folder, or to turn on long paths in Windows;"
                " then freeze again.",
            ),
        ),
        ErrorCode(
            "AOI-TRN-043",
            QT_TRANSLATE_NOOP("Errors", "Training not started: locked validation images"),
            QT_TRANSLATE_NOOP(
                "Errors",
                "{name} was not trained: {count} of its training set's images are, by their content, in a locked"
                " validation set, and an AI model is never trained on one.",
            ),
            QT_TRANSLATE_NOOP(
                "Errors",
                "Freeze a new version and lock its validation set, which keeps those images locked, then train from it;"
                " nothing was saved, and the active AI model is unchanged.",
            ),
        ),
        ErrorCode(
            "AOI-TRN-044",
            QT_TRANSLATE_NOOP("Errors", "Dataset store not changed"),
            QT_TRANSLATE_NOOP("Errors", "The dataset store of {store} was not changed: {reason}."),
            QT_TRANSLATE_NOOP(
                "Errors",
                "A move-in or a shred stopped part-way keeps the steps it made: start it again to finish. Anything "
                "else changed nothing: type the customer, the board model or the store's key again, or close the app "
                "that has a file of the store open, then try again.",
            ),
        ),
        ErrorCode(
            "AOI-TRN-045",
            QT_TRANSLATE_NOOP("Errors", "Training not started"),
            QT_TRANSLATE_NOOP("Errors", "{name} was not trained: {reason}."),
            QT_TRANSLATE_NOOP(
                "Errors",
                "Nothing was saved, and the active AI model is unchanged. Freeze a dataset version with enough OK "
                "images and lock its validation set on Training's Datasets tab, then start again from it; for a file "
                "changed since the freeze, put the frozen file back or freeze a new version (in the demo workspace, "
                "Reset Demo puts it back).",
            ),
        ),
        ErrorCode(
            "AOI-TRN-046",
            QT_TRANSLATE_NOOP("Errors", "Training not started: customer or use not allowed"),
            QT_TRANSLATE_NOOP("Errors", "{name} was not trained for the use {use}: {reason}."),
            QT_TRANSLATE_NOOP(
                "Errors",
                "Train from a version of one customer's dataset store that allows this use; the refusal is in the audit"
                " log, and the active AI model is unchanged.",
            ),
        ),
        ErrorCode(
            "AOI-TRN-047",
            QT_TRANSLATE_NOOP("Errors", "Training already running"),
            QT_TRANSLATE_NOOP(
                "Errors", "An AI model is already training on this station, so a second training run was not started."
            ),
            QT_TRANSLATE_NOOP(
                "Errors",
                "Wait for the run to end, or press Cancel on the Training page, then start again; the header shows how"
                " far the run is.",
            ),
        ),
        ErrorCode(
            "AOI-TRN-048",
            QT_TRANSLATE_NOOP("Errors", "AI model not made active"),
            QT_TRANSLATE_NOOP("Errors", "AI model {version} of board model {board} was not made active: {reason}."),
            QT_TRANSLATE_NOOP(
                "Errors",
                "Activate another version on Training, or train again; the active AI model and its Golden board are"
                " unchanged.",
            ),
        ),
        ErrorCode(
            "AOI-TRN-049",
            QT_TRANSLATE_NOOP("Errors", "Activation refused: no AI model card"),
            QT_TRANSLATE_NOOP(
                "Errors", "AI model {version} of board model {board} was not made active: it has no AI model card."
            ),
            QT_TRANSLATE_NOOP(
                "Errors",
                "Train again, so the new version has its card, or activate a version that has one; the active AI model"
                " and its Golden board are unchanged.",
            ),
        ),
        ErrorCode(
            "AOI-TRN-050",
            QT_TRANSLATE_NOOP("Errors", "Board not added to Training"),
            QT_TRANSLATE_NOOP("Errors", "Record {record} was not added to Training: {reason}. Nothing was changed."),
            QT_TRANSLATE_NOOP(
                "Errors",
                "Add a board that is still listed on Logs & Export with its board image and reviewed as a False call"
                " (F11); review it first if the board is good.",
            ),
        ),
        ErrorCode(
            "AOI-TRN-051",
            QT_TRANSLATE_NOOP("Errors", "AI model not active"),
            QT_TRANSLATE_NOOP(
                "Errors",
                "Board model {board} has AI model {version}, trained but not active, so only the golden-board"
                " comparison runs.",
            ),
            QT_TRANSLATE_NOOP(
                "Errors",
                "An Engineer activates it with Activate {version} on Inspection, or with Activate Selected on"
                " Training.",
            ),
        ),
        ErrorCode(
            "AOI-TRN-052",
            QT_TRANSLATE_NOOP("Errors", "A Trial AI model does not replace a Validated one"),
            QT_TRANSLATE_NOOP(
                "Errors",
                "AI model {version} of board model {board} was not made active: a Validated AI model already judges"
                " the boards of {board}, and a Trial AI model never replaces one. It was trained from {dataset}, a"
                " Trial version that one person froze without a second person checking its labels or an agreement"
                " check.",
            ),
            QT_TRANSLATE_NOOP(
                "Errors",
                "Start the Checks on Training: a second person checks the labels and two people run an agreement"
                " check; then freeze a Validated version and train from it. The active AI model and Golden board stay"
                " as they are.",
            ),
        ),
        ErrorCode(
            "AOI-TRN-053",
            QT_TRANSLATE_NOOP("Errors", "No dataset store on this system"),
            QT_TRANSLATE_NOOP(
                "Errors",
                "No dataset store was made for {customer}: this system keeps a store's key in memory only, so the key"
                " would be gone when the app closes and the store's files would open again only from its recovery"
                " sheet.",
            ),
            QT_TRANSLATE_NOOP(
                "Errors",
                "Make customers' dataset stores on the Windows station, whose Credential Manager keeps each key on the"
                " PC. This system serves development and testing only. Nothing was made.",
            ),
        ),
        ErrorCode(  # a new board model's name, where it is entered (B4 of the 2026-10 business-readiness brief, F9)
            "AOI-TRN-054",
            QT_TRANSLATE_NOOP("Errors", "Board model name not allowed: no Latin letter or digit"),
            QT_TRANSLATE_NOOP(
                "Errors",
                'The board model name "{name}" has no Latin letter or digit (A to Z, 0 to 9, as an English keyboard'
                " types them), and a board model's dataset versions are named with those in its name.",
            ),
            QT_TRANSLATE_NOOP(
                "Errors",
                "Give the board model a name with at least one Latin letter or digit, such as TBOX-A1; other letters,"
                ' such as Korean ones, may be added to it, as in "TBOX-A1 메인보드". Nothing was made.',
            ),
        ),
        ErrorCode(  # a new board model's name that looks like an existing one (Jay, 2026-10-13; ADR 0023, decision 6)
            "AOI-TRN-055",
            QT_TRANSLATE_NOOP("Errors", "Board model name not allowed: reads as another"),
            QT_TRANSLATE_NOOP(
                "Errors",
                'The board model name "{name}" reads the same as board model "{existing}", which exists already, once'
                " upper and lower case, full-width and other forms of the same letter or digit, the kind of space and"
                " characters that show nothing are set aside.",
            ),
            QT_TRANSLATE_NOOP(
                "Errors",
                'Select "{existing}" in the top bar to work on that board model, or type a name that differs from it in'
                " a letter A to Z or a digit 0 to 9, typed on an English keyboard. Nothing was made.",
            ),
        ),
        ErrorCode(  # a new board model's name whose versions would mix with another's (Jay, 2026-10-13; ADR 0023, 7)
            "AOI-TRN-056",
            QT_TRANSLATE_NOOP("Errors", "Board model name not allowed: version names would mix"),
            QT_TRANSLATE_NOOP(
                "Errors",
                'The board model name "{name}" has the same letters A to Z and digits 0 to 9 as board model'
                ' "{existing}", case aside, so the dataset versions of both would be named DS-{token}-…, and their'
                " names would mix.",
            ),
            QT_TRANSLATE_NOOP(
                "Errors",
                'Select "{existing}" in the top bar if it is the same board, or give the new board model a name whose'
                ' letters A to Z or digits 0 to 9 differ from those of "{existing}", such as one with another digit'
                " added. Nothing was made.",
            ),
        ),
        ErrorCode(  # the first-run guide's Train while a Validated AI model is active (B5; ADR 0020, decision 4)
            "AOI-TRN-057",
            QT_TRANSLATE_NOOP("Errors", "Train makes a Trial AI model, which does not replace a Validated one"),
            QT_TRANSLATE_NOOP(
                "Errors",
                "Nothing was trained for board model {board}: Validated AI model {version} judges its boards, and the"
                " first-run guide's Train makes a Trial AI model, which never replaces a Validated one.",
            ),
            QT_TRANSLATE_NOOP(
                "Errors",
                "Train a next AI model on Training from a Validated version. The active AI model and Golden board stay"
                " as they are. Nothing was written.",
            ),
        ),
        ErrorCode(
            "AOI-TST-001",
            QT_TRANSLATE_NOOP("Errors", "AI model, recipe, scale or Golden board changed since the run"),
            QT_TRANSLATE_NOOP(
                "Errors",
                "{file} was judged in this run by {run_model}, recipe revision {run_recipe}, {run_golden} and"
                " {run_scale}; {board_model} now uses {model}, recipe revision {recipe}, {golden} and {scale}, so a"
                " preview could show another verdict than its row.",
            ),
            QT_TRANSLATE_NOOP(
                "Errors",
                "Press Run Test Again in the preview pane to test the run's folder with what is in use now; the run's"
                " rows, CSV and report keep the verdicts it gave.",
            ),
        ),
        ErrorCode(
            "AOI-TST-003",
            QT_TRANSLATE_NOOP("Errors", "The validation did not start"),
            QT_TRANSLATE_NOOP("Errors", "Dataset version {name} was not tested: {reason}."),
            QT_TRANSLATE_NOOP(
                "Errors",
                "Split and lock its validation set on Training's Datasets tab, or pick another dataset version; nothing"
                " was stored.",
            ),
        ),
        ErrorCode(
            "AOI-TST-007",
            QT_TRANSLATE_NOOP("Errors", "The validation report was not made"),
            QT_TRANSLATE_NOOP("Errors", "No customer validation report was made: {reason}."),
            QT_TRANSLATE_NOOP(
                "Errors",
                "Run Test on a frozen dataset version's locked validation set, with a labeller agreement check stored"
                " on Training's Datasets tab, then make the report from that run.",
            ),
        ),
        ErrorCode(
            "AOI-TST-008",
            QT_TRANSLATE_NOOP("Errors", "Targets not saved"),
            QT_TRANSLATE_NOOP("Errors", "The targets of {board_model} were not saved: {reason}. Nothing was changed."),
            QT_TRANSLATE_NOOP(
                "Errors",
                "Enter each target within its range and who at the customer agreed them, then save again; the next run"
                " keeps the targets in force until then.",
            ),
        ),
        ErrorCode(
            "AOI-TST-009",
            QT_TRANSLATE_NOOP("Errors", "No validation report from a Trial version"),
            QT_TRANSLATE_NOOP("Errors", "No customer validation report was made: {reason}."),
            QT_TRANSLATE_NOOP(
                "Errors",
                "Start the Checks on Training: a second person checks the labels and two people run an agreement"
                " check, then freeze a Validated version, train from it and test again. The run and its CSV are kept.",
            ),
        ),
        ErrorCode(
            "AOI-RCP-001",
            QT_TRANSLATE_NOOP("Errors", "Recipe saved since it was opened"),
            QT_TRANSLATE_NOOP(
                "Errors",
                "Revision {latest} of board model {board_model} was saved after revision {revision}, the one the Recipe"
                " Editor holds; saving it would undo revision {latest}, so nothing was saved.",
            ),
            QT_TRANSLATE_NOOP(
                "Errors",
                "Press Save Recipe again and choose Yes to load revision {latest}, then make your changes again on it;"
                " until then they stay on screen.",
            ),
        ),
        ErrorCode(
            "AOI-RCP-002",
            QT_TRANSLATE_NOOP("Errors", "ROI thresholds refused"),
            QT_TRANSLATE_NOOP(
                "Errors",
                "ROI {roi}: {quantity} min {low} and max {high} cannot be stored; a threshold is 0 or more, and min is"
                " not above max.",
            ),
            QT_TRANSLATE_NOOP(
                "Errors",
                "Nothing was applied. Correct the two values, or step a threshold down below 0 to — to leave it unset,"
                " then press Apply again.",
            ),
        ),
        ErrorCode(
            "AOI-RCP-004",
            QT_TRANSLATE_NOOP("Errors", "Recipe saved while Save to Recipe was open"),
            QT_TRANSLATE_NOOP(
                "Errors",
                "Revision {latest} of board model {board_model} was saved after revision {revision}, the one Save to"
                " Recipe listed its changes against; saving them would undo revision {latest}, so the sheet closed and"
                " nothing was saved. Compare now shows the thresholds of revision {latest}.",
            ),
            QT_TRANSLATE_NOOP("Errors", "Try your thresholds again on revision {latest}, then press Save to Recipe."),
        ),
        ErrorCode(
            "AOI-RCP-005",
            QT_TRANSLATE_NOOP("Errors", "Sizes are shown in px"),
            QT_TRANSLATE_NOOP(
                "Errors",
                "Board model {board_model} has no scale yet, so its recipe's minimum defect size and ROIs are in px of"
                " its images: a recipe saves so and judges as before, but its sizes keep their px after a camera"
                " change, where sizes in mm would follow the scale set again on the new Golden board.",
            ),
            QT_TRANSLATE_NOOP(
                "Errors",
                "To give them in mm, press Calibrate Scale…, click two points on the Golden board a known distance"
                " apart, enter that distance in mm and press Set Scale.",
            ),
        ),
        ErrorCode(
            "AOI-RCP-007",
            QT_TRANSLATE_NOOP("Errors", "Minimum defect size under 4 px"),
            QT_TRANSLATE_NOOP(
                "Errors",
                "The minimum defect size, {size}, spans {px:.1f} px in the board images: under 4 px, a defect is not"
                " told from image noise.",
            ),
            QT_TRANSLATE_NOOP(
                "Errors",
                "Raise it to {least} or more, or use images of a higher resolution. The recipe saves as it is; its"
                " audit entry keeps this code.",
            ),
        ),
        ErrorCode(
            "AOI-RCP-008",
            QT_TRANSLATE_NOOP("Errors", "Scale not set"),
            QT_TRANSLATE_NOOP("Errors", "The scale of board model {board_model} was not set: {reason}."),
            QT_TRANSLATE_NOOP(
                "Errors",
                "Nothing was changed. On the Recipe Editor, press Calibrate Scale…, click two points on the Golden"
                " board a known distance apart, enter that distance in mm and press Set Scale.",
            ),
        ),
        ErrorCode(
            "AOI-RCP-009",
            QT_TRANSLATE_NOOP("Errors", "Sizes are held in px"),
            QT_TRANSLATE_NOOP(
                "Errors",
                "Revision {revision} of board model {board_model} holds {count} of its {total} size(s) in px of its"
                " images (the minimum defect size and each ROI's box): shown in mm at this scale, they keep their px"
                " when the scale is set again, as after a camera change, while sizes in mm follow it.",
            ),
            QT_TRANSLATE_NOOP(
                "Errors",
                "Press Save Recipe to store them in mm, so that they follow the scale; that alone changes no verdict"
                " at this scale.",
            ),
        ),
        ErrorCode(
            "AOI-RCP-010",
            QT_TRANSLATE_NOOP("Errors", "Scale set after Compare showed the recipe"),
            QT_TRANSLATE_NOOP(
                "Errors",
                "The scale of board model {board_model} was set to {scale:.2f} px/mm after Compare showed revision"
                " {revision}, so Save to Recipe listed its changes at the scale before, or in px without one; the"
                " sheet closed and nothing was saved. Compare now shows the thresholds of revision {revision} at the"
                " new scale.",
            ),
            QT_TRANSLATE_NOOP("Errors", "Try your thresholds again at this scale, then press Save to Recipe."),
        ),
        ErrorCode(
            "AOI-RCP-011",
            QT_TRANSLATE_NOOP("Errors", "Size in mm refused"),
            QT_TRANSLATE_NOOP(
                "Errors",
                "The {size} of board model {board_model} cannot be {value} mm: a size in mm is a number above 0 and at"
                " most {most}, and an ROI's box is four of them, its x and y 0 or more.",
            ),
            QT_TRANSLATE_NOOP("Errors", "Nothing was saved. Correct the size, then save the recipe again."),
        ),
        ErrorCode(
            "AOI-RCP-012",
            QT_TRANSLATE_NOOP("Errors", "Scale cannot be read"),
            QT_TRANSLATE_NOOP(
                "Errors", "The stored scale of board model {board_model}, {value}, is not a finite number above 0."
            ),
            QT_TRANSLATE_NOOP(
                "Errors",
                "Nothing was judged or saved with it. On the Recipe Editor, press Calibrate Scale… and set the scale"
                " again; Set Scale replaces it.",
            ),
        ),
        ErrorCode(
            "AOI-RCP-013",
            QT_TRANSLATE_NOOP("Errors", "Too few labelled boards to learn from"),
            QT_TRANSLATE_NOOP(
                "Errors", "The comparison's thresholds of board model {board_model} cannot be learned: {reason}."
            ),
            QT_TRANSLATE_NOOP(
                "Errors",
                "Nothing was changed. On Training, label more boards of this board model: NG images with each defect"
                " boxed, and OK images, in the Golden board's view; then press Learn From Labelled Boards… again.",
            ),
        ),
        ErrorCode(
            "AOI-LOG-001",
            QT_TRANSLATE_NOOP("Errors", "Export stopped part-way"),
            QT_TRANSLATE_NOOP(
                "Errors",
                "Copying {file} to {folder} failed ({reason}), so the export stopped after {copied} of {total} overlay"
                " image(s); the audit trail records those {copied}.",
            ),
            QT_TRANSLATE_NOOP(
                "Errors",
                "Check that the drive is connected, has free space and can be written, that nothing in the folder"
                " already has the name {file}, and that the record's overlay image is still in the results folder; then"
                " export again.",
            ),
        ),
        ErrorCode(
            "AOI-LOG-002",
            QT_TRANSLATE_NOOP("Errors", "Export not written"),
            QT_TRANSLATE_NOOP(
                "Errors",
                "The export {path} could not be written: {reason}. Nothing was exported, and a file of that name"
                " already there is left as it was.",
            ),
            QT_TRANSLATE_NOOP(
                "Errors",
                "Choose a folder that can be written, close any program that has the file open and check the free disk"
                " space, then export again.",
            ),
        ),
        ErrorCode(
            "AOI-LOG-003",
            QT_TRANSLATE_NOOP("Errors", "Reason needed"),
            QT_TRANSLATE_NOOP(
                "Errors", "Deleting {count} record(s) needs a reason, which the audit trail keeps with the deletion."
            ),
            QT_TRANSLATE_NOOP("Errors", "Nothing was deleted. Press Delete Records… again and type why they go."),
        ),
        ErrorCode(
            "AOI-LOG-004",
            QT_TRANSLATE_NOOP("Errors", "Evidence files left"),
            QT_TRANSLATE_NOOP(
                "Errors",
                "{count} record(s) were deleted and the audit trail records it, but {left} of their evidence file(s)"
                " would not go, {file} first ({reason}).",
            ),
            QT_TRANSLATE_NOOP(
                "Errors",
                "Close the image viewer or other app that has the file open, then delete the files the log names"
                " (records.evidence_left) from the results folder.",
            ),
        ),
        ErrorCode(
            "AOI-USR-001",
            QT_TRANSLATE_NOOP("Errors", "Not allowed for this role"),
            QT_TRANSLATE_NOOP("Errors", "{what} needs the {roles} role."),
            QT_TRANSLATE_NOOP("Errors", "Sign in as a user with that role, or ask one to do it."),
        ),
        ErrorCode(
            "AOI-USR-002",
            QT_TRANSLATE_NOOP("Errors", "Last Admin"),
            QT_TRANSLATE_NOOP(
                "Errors",
                "{name} is the only user with the Admin role, so it cannot change to {role}: no one could then manage "
                "users or settings.",
            ),
            QT_TRANSLATE_NOOP("Errors", "Give another user the Admin role first, then change this one."),
            personal=("name",),  # a user's name: the log names the user by UUID (#195)
        ),
        ErrorCode(
            "AOI-USR-003",
            QT_TRANSLATE_NOOP("Errors", "Unknown user"),
            QT_TRANSLATE_NOOP("Errors", "There is no user named {name} in this workspace, so no role to sign in with."),
            QT_TRANSLATE_NOOP(
                "Errors", "Pick a user from the list under Switch User; an Admin adds users on the Settings page."
            ),
        ),
        ErrorCode(
            "AOI-SET-001",
            QT_TRANSLATE_NOOP("Errors", "Workspace from version 0.1"),
            QT_TRANSLATE_NOOP("Errors", "This workspace was created by AOI PoC Inspector 0.1 and cannot be upgraded."),
            QT_TRANSLATE_NOOP(
                "Errors", "Choose a new workspace folder in the window that opens next; Cancel there closes the app."
            ),
        ),
        ErrorCode(
            "AOI-SET-002",
            QT_TRANSLATE_NOOP("Errors", "Workspace newer than the app"),
            QT_TRANSLATE_NOOP(
                "Errors",
                "The workspace database was written by a newer build of the app: it records migration {migration}, "
                "which this build does not have.",
            ),
            QT_TRANSLATE_NOOP(
                "Errors",
                "Update the app, or choose another workspace folder in the window that opens next; Cancel there closes "
                "the app.",
            ),
        ),
        ErrorCode(
            "AOI-SET-003",
            QT_TRANSLATE_NOOP("Errors", "Migration file changed"),
            QT_TRANSLATE_NOOP(
                "Errors",
                "Migration {file} differs from the one recorded in the workspace database; a shipped migration is "
                "never edited.",
            ),
            QT_TRANSLATE_NOOP(
                "Errors",
                "Reinstall the app to restore the file, or choose another workspace folder in the window that opens "
                "next; Cancel there closes the app.",
            ),
        ),
        ErrorCode(
            "AOI-SET-004",
            QT_TRANSLATE_NOOP("Errors", "Migration failed"),
            QT_TRANSLATE_NOOP("Errors", "Migration {file} failed and was rolled back: {error}."),
            QT_TRANSLATE_NOOP(
                "Errors",
                "Restart the app; if it happens again, report it with the log file. To go back to the version you "
                "upgraded from, close the app and copy the backup aoi.sqlite.bak-… in the workspace folder over "
                "aoi.sqlite (engineer manual, chapter 1).",
            ),
        ),
        ErrorCode(
            "AOI-SET-005",
            QT_TRANSLATE_NOOP("Errors", "Workspace folder cannot hold the database"),
            QT_TRANSLATE_NOOP(
                "Errors",
                "The workspace folder does not support the database's write-ahead log (is it on a network drive?).",
            ),
            QT_TRANSLATE_NOOP(
                "Errors", "Choose a folder on this computer in the window that opens next; Cancel there closes the app."
            ),
        ),
        ErrorCode(
            "AOI-SET-006",
            QT_TRANSLATE_NOOP("Errors", "Migration files invalid"),
            QT_TRANSLATE_NOOP("Errors", "The app's migration files are not valid: {problem}."),
            QT_TRANSLATE_NOOP("Errors", "Reinstall the app and report it; this is a defect in the build."),
        ),
        ErrorCode(
            "AOI-SET-007",
            QT_TRANSLATE_NOOP("Errors", "Unexpected error"),
            QT_TRANSLATE_NOOP("Errors", "An unexpected error stopped the last action{context}{reason}."),
            QT_TRANSLATE_NOOP(
                "Errors",
                "Try again; if it happens again, restart the app and send the log file (the workspace's logs folder) "
                "to support.",
            ),
        ),
        ErrorCode(
            "AOI-SET-008",
            QT_TRANSLATE_NOOP("Errors", "Setting invalid"),
            QT_TRANSLATE_NOOP("Errors", "The setting {name} is {value}; it must be {expected}."),
            QT_TRANSLATE_NOOP(
                "Errors",
                "On the Settings page, correct it and save again. If the app stopped at start-up, fix or remove that "
                "line in settings.json, in the default workspace folder, and start the app again.",
            ),
        ),
        ErrorCode(
            "AOI-SET-009",
            QT_TRANSLATE_NOOP("Errors", "Backup before upgrade failed"),
            QT_TRANSLATE_NOOP(
                "Errors",
                "The workspace database could not be copied to {file} before this version upgrades it: {error}. "
                "Nothing was changed.",
            ),
            QT_TRANSLATE_NOOP(
                "Errors",
                "Free disk space on the workspace folder's drive and check that the folder can be written, then start "
                "the app again.",
            ),
        ),
        ErrorCode(
            "AOI-SET-010",
            QT_TRANSLATE_NOOP("Errors", "Settings file cannot be read"),
            QT_TRANSLATE_NOOP("Errors", "The settings file {path} could not be read: {reason}."),
            QT_TRANSLATE_NOOP(
                "Errors",
                "Correct the file, or rename it so the app starts with the default settings, then start the app again.",
            ),
        ),
        ErrorCode(
            "AOI-SET-011",
            QT_TRANSLATE_NOOP("Errors", "Workspace cannot be opened"),
            QT_TRANSLATE_NOOP("Errors", "The workspace folder {path} could not be opened: {error}."),
            QT_TRANSLATE_NOOP(
                "Errors",
                "If the folder is on a drive that is not connected, connect it and start the app again; if its "
                "database aoi.sqlite is damaged, restore the backup aoi.sqlite.bak-… (engineer manual, chapter 1). Or "
                "choose another workspace folder in the window that opens next; Cancel there closes the app.",
            ),
        ),
        ErrorCode(
            "AOI-SET-012",
            QT_TRANSLATE_NOOP("Errors", "Workspace in use"),
            QT_TRANSLATE_NOOP(
                "Errors", "Another program is using {path} in the workspace, so the app could not open it: {error}."
            ),
            QT_TRANSLATE_NOOP(
                "Errors",
                "Close the other program (a database tool or a backup), then choose the same folder in the window "
                "that opens next; or choose another workspace folder there. Cancel there closes the app.",
            ),
        ),
        ErrorCode(
            "AOI-SET-013",
            QT_TRANSLATE_NOOP("Errors", "Workspace database busy"),
            QT_TRANSLATE_NOOP(
                "Errors",
                "Another program holds the workspace database {path}, so the app could not write to it.",
            ),
            QT_TRANSLATE_NOOP(
                "Errors",
                "Close the other program (a database tool or a backup), then do the last action again.",
            ),
        ),
        ErrorCode(
            "AOI-SET-014",
            QT_TRANSLATE_NOOP("Errors", "No board model selected"),
            QT_TRANSLATE_NOOP("Errors", "{page} needs a board model, and none is selected in the top bar."),
            QT_TRANSLATE_NOOP(
                "Errors",
                "Select a board model in the top bar. If the list is empty, an Engineer or Admin creates one with "
                "+ New.",
            ),
        ),
        ErrorCode(
            "AOI-SET-015",
            QT_TRANSLATE_NOOP("Errors", "Demo bundle cannot be used"),
            QT_TRANSLATE_NOOP("Errors", "The demo bundle {path} cannot be used: {reason}."),
            QT_TRANSLATE_NOOP(
                "Errors",
                "Reinstall the app, which puts the demo bundle back. Nothing in the production workspace was changed.",
            ),
        ),
        ErrorCode(
            "AOI-SET-016",
            QT_TRANSLATE_NOOP("Errors", "Folder is not a demo workspace"),
            QT_TRANSLATE_NOOP(
                "Errors",
                "The folder {path} holds files and is not a demo workspace, so the demo was not written there.",
            ),
            QT_TRANSLATE_NOOP(
                "Errors",
                "Move or rename that folder, then load the demo again; the app never deletes a folder it did not "
                "make for the demo.",
            ),
        ),
        ErrorCode(
            "AOI-SET-017",
            QT_TRANSLATE_NOOP("Errors", "Demo reset did not finish"),
            QT_TRANSLATE_NOOP("Errors", "The demo workspace could not be put back: {path}: {error}."),
            QT_TRANSLATE_NOOP(
                "Errors",
                "Close the program that holds the file (an image viewer, Explorer or a backup), then press Reset "
                "Demo again; the production workspace is not touched.",
            ),
        ),
        ErrorCode(
            "AOI-SET-018",
            QT_TRANSLATE_NOOP("Errors", "A stored path leads outside the workspace"),
            QT_TRANSLATE_NOOP(
                "Errors",
                "The database names {path}, which leads outside the workspace folder {root}, so the app neither opens "
                "nor writes it. The app never stores such a path: the database was changed outside the app.",
            ),
            QT_TRANSLATE_NOOP(
                "Errors",
                "Ask an Admin to restore the workspace from its backup (installation guide, Backup and restore).",
            ),
        ),
        ErrorCode(  # one sentence and one button when the copy open cannot be brought to the front (A6, F12)
            "AOI-SET-019",
            QT_TRANSLATE_NOOP("Errors", "App already open"),
            QT_TRANSLATE_NOOP(
                "Errors",
                "AOI PoC Inspector is already open on this workspace: switch to it on the taskbar, or, if it is not "
                "there, ask whoever has it open on another account or PC to close it.",
            ),
            QT_TRANSLATE_NOOP(
                "Errors",
                "Switch to the copy that is open, on the taskbar; if it is open on another account or another PC, have "
                "it closed there and start the app again. This start changed nothing in the workspace.",
            ),
        ),
    )
}


def _same(line: Phrase, *codes: str) -> dict[str, Phrase]:
    return dict.fromkeys(codes, line)


# What the first-run guide on Home says of a code it raises, in the guide's words, in place of what happened and what
# to do, which its Show Details holds (REQ-TRN-021; B5, docs/sketches/first-run-guide.md, "Errors", Q78). Each line's
# {placeholders} are its code's own; `AoiError.guide` fills them, and docs/error-codes.md lists the lines.
GUIDE: dict[str, Phrase] = {
    # screen 1, the board model
    "AOI-TRN-019": QT_TRANSLATE_NOOP(
        "Errors",
        'Leave out / : * ? " < > \\ | and control characters, end with no dot or space, and use no device name such as'
        " CON or NUL.",
    ),
    "AOI-TRN-054": QT_TRANSLATE_NOOP("Errors", "Add a letter A to Z or a digit, such as TBOX-A1 or 기판 2호."),
    **_same(
        QT_TRANSLATE_NOOP("Errors", "{existing} is already here. Pick it in the top bar, or type another name."),
        "AOI-TRN-005",
        "AOI-TRN-055",
    ),
    "AOI-TRN-056": QT_TRANSLATE_NOOP(
        "Errors", "This has the letters and digits of {existing}. Change or add a letter or digit."
    ),
    "AOI-TRN-044": QT_TRANSLATE_NOOP("Errors", "Nothing was made: {reason}."),
    "AOI-TRN-053": QT_TRANSLATE_NOOP(
        "Errors", "This computer cannot keep the key, so nothing was made. Set up on the station itself."
    ),
    "AOI-LOG-002": QT_TRANSLATE_NOOP(
        "Errors", "The key was not saved there ({reason}). Save it on a USB drive, or print it."
    ),
    # screen 2, the images
    **_same(
        QT_TRANSLATE_NOOP("Errors", "Not an image this app reads. Save it as PNG or JPG and pick the folder again."),
        "AOI-INSP-001",
        "AOI-INSP-004",
        "AOI-INSP-006",
    ),
    **_same(
        QT_TRANSLATE_NOOP("Errors", "Not the camera's usual size. Use the image as the camera takes it."),
        "AOI-INSP-005",
        "AOI-INSP-007",
    ),
    "AOI-TRN-013": QT_TRANSLATE_NOOP(
        "Errors", "Put it in a folder of ng named after its defect, then pick the folder again."
    ),
    "AOI-TRN-014": QT_TRANSLATE_NOOP(
        "Errors", "Wait until copying from the camera has ended, then pick the folder again."
    ),
    "AOI-TRN-015": QT_TRANSLATE_NOOP("Errors", "Taken once already; nothing to do. Not counted twice."),
    "AOI-TRN-016": QT_TRANSLATE_NOOP("Errors", "Not in ok or ng. Move it into one and pick the folder again."),
    "AOI-TRN-008": QT_TRANSLATE_NOOP(
        "Errors", "Not copied ({reason}). Check the USB drive and the free space, then pick the folder again."
    ),
    "AOI-TRN-009": QT_TRANSLATE_NOOP(
        "Errors",
        "Copying stopped at image {at} of {total}; the ones before it are kept. Check the USB drive and the free space,"
        " then pick the folder again.",
    ),
    "AOI-TRN-010": QT_TRANSLATE_NOOP(
        "Errors",
        "Copying stopped at image {at} of {total} ({reason}); the ones before it are kept. Fix that, then pick the"
        " folder again.",
    ),
    "AOI-TRN-011": QT_TRANSLATE_NOOP(
        "Errors", "The workspace folder's path is too long. Pick a shorter one on Settings, then the folder again."
    ),
    "AOI-TRN-025": QT_TRANSLATE_NOOP(
        "Errors",
        "{store}'s images cannot be opened on this station: {reason}. An Admin types the saved recovery key on Settings"
        " (Restore Key…).",
    ),
    "AOI-TRN-030": QT_TRANSLATE_NOOP("Errors", "The box was not kept: {reason}. Draw it again."),
    "AOI-TRN-031": QT_TRANSLATE_NOOP("Errors", "The box was not kept: it lies outside the image. Draw it again."),
    "AOI-TRN-032": QT_TRANSLATE_NOOP(
        "Errors", "The box was not kept: the image is no longer in the workspace. Pick the folder again."
    ),
    # screen 3, Train
    **_same(
        QT_TRANSLATE_NOOP("Errors", "Train stopped: {reason}. Fix that, then press Train again."),
        "AOI-TRN-027",
        "AOI-TRN-022",
    ),
    "AOI-TRN-040": QT_TRANSLATE_NOOP(
        "Errors", "Another board model's names would mix with this one's. Set the boards up under a new name."
    ),
    **_same(
        QT_TRANSLATE_NOOP(
            "Errors",
            "Nothing was kept. Free space on the workspace drive, or pick a shorter workspace folder on Settings.",
        ),
        "AOI-TRN-041",
        "AOI-TRN-042",
    ),
    "AOI-TRN-047": QT_TRANSLATE_NOOP("Errors", "Wait for the training under way to end, then press Train again."),
    **_same(
        QT_TRANSLATE_NOOP(
            "Errors",
            "No AI model was made: {reason}. Add images of more good boards on Training, then press Train again.",
        ),
        "AOI-TRN-045",
        "AOI-TRN-004",
    ),
    "AOI-TRN-043": QT_TRANSLATE_NOOP(
        "Errors",
        "No AI model was made: {count} of the images it would train on are kept apart already. Add images of more good"
        " boards on Training, then press Train again.",
    ),
    "AOI-TRN-048": QT_TRANSLATE_NOOP("Errors", "The AI model was made but does not judge boards yet: {reason}."),
    "AOI-TRN-049": QT_TRANSLATE_NOOP(
        "Errors", "The AI model was made but does not judge boards yet: it has no AI model card. Press Train again."
    ),
    "AOI-TRN-052": QT_TRANSLATE_NOOP(
        "Errors",
        "The AI model was made but does not judge boards yet: a Validated AI model judges {board}'s boards, and a Trial"
        " one never replaces it.",
    ),
    "AOI-TRN-057": QT_TRANSLATE_NOOP(
        "Errors",
        "Nothing was made: Validated AI model {version} judges {board}'s boards, and Train makes a Trial one, which"
        " never replaces it.",
    ),
    "AOI-TST-003": QT_TRANSLATE_NOOP(
        "Errors", "Not tested: {reason}. The AI model judges boards; AI Model Test tests it again."
    ),
}


class AoiError(Exception):
    """An error with a code and a plain message. ``str(e)`` is "<code> <what> <action>" in English, for the log; its
    title, what and action are phrases a screen shows in the UI language, and `guide` the first-run guide's line for
    its code (`GUIDE`), or None."""

    def __init__(self, code: str, detail: str | None = None, **params: object) -> None:
        self.entry = CODES[code]
        self.code = code
        self.detail = detail
        self.params = params  # the values, phrases among them, that a screen fills the translated templates with
        self.title = Phrase("Errors", self.entry.title)
        self.what = Phrase("Errors", self.entry.what, params)
        self.action = Phrase("Errors", self.entry.action, params)
        line = GUIDE.get(code)  # the first-run guide's line (Q78), said in place of what and action there
        self.guide = None if line is None else line.fill(**params)
        super().__init__(f"{code} {self.what} {self.action}")

    @property
    def message(self) -> str:
        """What the user reads: what happened and what to do, without the code."""
        return f"{self.what} {self.action}"

    def log_safe(self, pseudonym: Callable[[object], object]) -> AoiError:
        """This error as the log may hold it (REQ-LOG-004, #195): each value the catalogue marks personal, such as a
        user's name, replaced by `pseudonym(value)`, such as that user's UUID, with the same trace; itself when none."""
        personal = {k: pseudonym(v) for k, v in self.params.items() if k in self.entry.personal}
        if not personal:
            return self
        safe = type(self)(self.code, self.detail, **{**self.params, **personal})
        safe.__cause__ = self.__cause__
        return safe.with_traceback(self.__traceback__)


def render() -> str:
    """docs/error-codes.md as generated from the catalogue."""
    lines = [
        "# Error codes",
        "",
        "Generated from `aoi/errors.py` by `python -m aoi.errors`; do not edit. Every error a user can see carries one",
        "of these codes with what happened and what to do (REQ-LOG-004, REQ-SET-019). Areas follow the requirement",
        "register; `{braces}` are filled in when the error is raised.",
        "",
        "| Code | Title | What happened | What to do |",
        "|---|---|---|---|",
    ]
    lines += [f"| {c.code} | {c.title} | {c.what} | {c.action} |" for c in sorted(CODES.values(), key=lambda c: c.code)]
    lines += [
        "",
        "## The first-run guide's lines",
        "",
        "The first-run guide on Home says these in place of what happened and what to do, which its Show Details holds",
        "(REQ-TRN-021, Q78). Any other code is said there as the table above gives it.",
        "",
        "| Code | Title | The guide's line |",
        "|---|---|---|",
    ]
    bar = "\\|"  # a vertical bar in a cell, as Markdown keeps it
    lines += [f"| {code} | {CODES[code].title} | {GUIDE[code].replace('|', bar)} |" for code in sorted(GUIDE)]
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Write docs/error-codes.md from the catalogue, or --check it.")
    ap.add_argument("--check", action="store_true", help="exit 1 if the file differs instead of writing it")
    a = ap.parse_args(argv)
    current = DOC_PATH.read_text(encoding="utf-8") if DOC_PATH.exists() else ""
    if a.check:
        print("docs/error-codes.md is up to date" if current == render() else "docs/error-codes.md is out of date")
        return 0 if current == render() else 1
    DOC_PATH.write_text(render(), encoding="utf-8")
    print(f"Wrote {DOC_PATH}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
