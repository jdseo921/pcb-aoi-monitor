"""One catalogue of error codes (REQ-LOG-004, REQ-SET-019; stage S12).

Every error a user can see is an ``AoiError`` with a code ``AOI-<AREA>-<NNN>``, a plain message that says
what happened and what to do, and optional ``detail`` for the log, never for the dialog. The areas are the
requirement register's (docs/requirements/README.md). ``docs/error-codes.md`` is generated from ``CODES``
by ``python -m aoi.errors``; a test fails when the two differ.
"""

from __future__ import annotations

import argparse
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
                "An Engineer sets a Golden board or trains an AI model on Training, or turns on the Golden board"
                " comparison or the AI model in the Recipe Editor; then inspect the board again.",
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
            QT_TRANSLATE_NOOP("Errors", "AI model, recipe or Golden board changed during a run"),
            QT_TRANSLATE_NOOP(
                "Errors",
                "The AI model, recipe or Golden board of {board} changed during a run (training ended, a version was"
                " activated, a recipe saved or a Golden board set), so {file} and the boards after it are judged with"
                " what is active now; the boards before keep what judged them.",
            ),
            QT_TRANSLATE_NOOP(
                "Errors",
                "No action is needed: each record names the AI model version, recipe revision and Golden board that"
                " judged it.",
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
                "The decision table is the stored one; use Side by side or Boxes only, or inspect the board again on"
                " Inspection to see its heatmaps.",
            ),
        ),
        ErrorCode(
            "AOI-CMP-002",
            QT_TRANSLATE_NOOP("Errors", "Result has no stored decision table"),
            QT_TRANSLATE_NOOP(
                "Errors",
                "Record {id} ({file}) has no stored decision table: it was saved before migration 0006, or no record "
                "has that number or UUID.",
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
            "AOI-TRN-001",
            QT_TRANSLATE_NOOP("Errors", "AI model file refused"),
            QT_TRANSLATE_NOOP(
                "Errors",
                "AI model file refused: {path} could not be loaded as a weights-only AI model file this app wrote "
                "({reason}).",
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
            QT_TRANSLATE_NOOP("Errors", "Folder import stopped part-way"),
            QT_TRANSLATE_NOOP(
                "Errors",
                "Copying {path} into the workspace failed ({reason}), so the import of {folder} stopped at image {at}"
                " of {total}; the {imported} image(s) imported before it stay in the sample table.",
            ),
            QT_TRANSLATE_NOOP(
                "Errors",
                "Check that the file is still there and can be opened and that the workspace drive has free space."
                " Importing the folder again would add those {imported} a second time: import the images not yet"
                " imported with + OK or + NG, or first remove the {imported} from the sample table.",
            ),
        ),
        ErrorCode(
            "AOI-TRN-010",
            QT_TRANSLATE_NOOP("Errors", "Folder import stopped by an error"),
            QT_TRANSLATE_NOOP(
                "Errors",
                "Importing {path} failed ({reason}), so the import of {folder} stopped at image {at} of {total}; the"
                " {imported} image(s) imported before it stay in the sample table.",
            ),
            QT_TRANSLATE_NOOP(
                "Errors",
                "Fix what stopped it (the log file in the workspace's logs folder has the details; send it to support"
                " if the cause is unclear). Importing the folder again would add those {imported} a second time:"
                " import the images not yet imported with + OK or + NG, or first remove the {imported} from the sample"
                " table.",
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
            QT_TRANSLATE_NOOP("Errors", "An unexpected error ({error_type}) stopped the last action{context}."),
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
                "Close the other program (another copy of this app, a database tool or a backup), then choose the "
                "same folder in the window that opens next; or choose another workspace folder there. Cancel there "
                "closes the app.",
            ),
        ),
        ErrorCode(
            "AOI-SET-013",
            QT_TRANSLATE_NOOP("Errors", "Workspace database busy"),
            QT_TRANSLATE_NOOP(
                "Errors",
                "Another program holds the workspace database {path}, so the app could not write to it: {error}.",
            ),
            QT_TRANSLATE_NOOP(
                "Errors",
                "Close the other program (another copy of this app, a database tool or a backup), then do the last "
                "action again.",
            ),
        ),
    )
}


class AoiError(Exception):
    """An error with a code and a plain message. ``str(e)`` is "<code> <what> <action>" in English, for the log; its
    title, what and action are phrases a screen shows in the UI language."""

    def __init__(self, code: str, detail: str | None = None, **params: object) -> None:
        self.entry = CODES[code]
        self.code = code
        self.detail = detail
        self.params = params  # the values, phrases among them, that a screen fills the translated templates with
        self.title = Phrase("Errors", self.entry.title)
        self.what = Phrase("Errors", self.entry.what, params)
        self.action = Phrase("Errors", self.entry.action, params)
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
