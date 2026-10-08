"""One catalogue of error codes (REQ-LOG-004, REQ-SET-019; stage S12).

Every error a user can see is an ``AoiError`` with a code ``AOI-<AREA>-<NNN>``, a plain message that says
what happened and what to do, and optional ``detail`` for the log, never for the dialog. The areas are the
requirement register's (docs/requirements/README.md). ``docs/error-codes.md`` is generated from ``CODES``
by ``python -m aoi.errors``; a test fails when the two differ.
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from pathlib import Path

AREAS = ("INSP", "CMP", "TRN", "TST", "RCP", "LOG", "P3D", "USR", "SET", "CAM", "ROB", "MES")
DOC_PATH = Path(__file__).resolve().parents[1] / "docs" / "error-codes.md"


@dataclass(frozen=True)
class ErrorCode:
    code: str
    title: str
    what: str  # what happened; {placeholders} are filled at the raise site
    action: str  # what the user does next


CODES: dict[str, ErrorCode] = {
    c.code: c
    for c in (
        ErrorCode(
            "AOI-INSP-001",
            "Image cannot be read",
            "The file {path} could not be opened as an image.",
            "Check that the file exists and is a PNG, JPG, BMP or TIFF image.",
        ),
        ErrorCode(
            "AOI-INSP-002",
            "Image cannot be written",
            "The image {path} could not be encoded for writing.",
            "Check the file name's extension (.png or .jpg) and try again.",
        ),
        ErrorCode(
            "AOI-INSP-003",
            "Board failed inspection",
            "Board {board} failed inspection with {defects} defect(s).",
            "Review the result on the Compare page before the board moves on.",
        ),
        ErrorCode(
            "AOI-INSP-004",
            "File format not supported",
            "The file {path} does not hold a PNG, JPG, BMP or TIFF image; the format is read from the file's content, "
            "not its name.",
            "Save the image as PNG, JPG, BMP or TIFF with an image tool and load that file.",
        ),
        ErrorCode(
            "AOI-INSP-005",
            "Image over the size limit",
            "The image {path} is {size}, over the limit of {limit}.",
            "Use a smaller image, or ask an Admin to raise the limit: max_image_megapixels or max_image_megabytes in "
            "settings.json, in the default workspace folder.",
        ),
        ErrorCode(
            "AOI-INSP-006",
            "Image file cannot be decoded",
            "The {kind} image {path} could not be decoded: {reason}.",
            "Copy the file again from the camera or its source; if it fails again, save it as PNG or JPG with an image "
            "tool and load that file.",
        ),
        ErrorCode(
            "AOI-INSP-007",
            "Image side too long",
            "The image {path} is {width} × {height} px; a side over {limit} px is beyond what this app decodes.",
            "Crop or scale the image so that no side is over {limit} px; this limit is the decoder's and cannot be "
            "raised.",
        ),
        ErrorCode(
            "AOI-INSP-008",
            "Result not saved",
            "The result of {file} was shown but could not be saved, so it is not in Logs & Export.",
            "Check the free disk space and that the workspace folder can be written, then press Next Board to carry on"
            " and inspect {file} again later.",
        ),
        ErrorCode(
            "AOI-INSP-009",
            "Golden board file not available",
            "Board model {board} names {file} as its Golden board, but {reason}, so no board of it can be compared"
            " with the Golden board. The board was not inspected.",
            "Put the file back, for example from a backup of the workspace, or have an Engineer choose another OK"
            " sample as the Golden board with Set Reference on Training; then inspect the board again.",
        ),
        ErrorCode(
            "AOI-INSP-010",
            "Nothing can judge the board",
            "No check can judge this board of board model {board}: {reason}. The board was given no verdict.",
            "An Engineer sets a Golden board or trains an AI model on Training, or turns on the Golden board"
            " comparison or the AI model in the Recipe Editor; then inspect the board again.",
        ),
        ErrorCode(
            "AOI-INSP-011",
            "Image too small to inspect",
            "The {image} is {width} × {height} px; inspecting needs at least {minimum} px on each side.",
            "Load a picture of the whole board as the camera takes it; if the Golden board is the small one, an"
            " Engineer sets another on Training.",
        ),
        ErrorCode(
            "AOI-CMP-001",
            "Result has no stored heatmaps",
            "The result of {file} was saved without its difference and AI maps, or they were deleted after the"
            " retention period of {days} days.",
            "The decision table is the stored one; use Side by side or Boxes only, or inspect the board again on"
            " Inspection to see its heatmaps.",
        ),
        ErrorCode(
            "AOI-CMP-002",
            "Result has no stored decision table",
            "Record {id} ({file}) has no stored decision table: it was saved before migration 0006, or no record has"
            " that number or UUID.",
            "Inspect the board again on Inspection; Compare then opens the new result.",
        ),
        ErrorCode(
            "AOI-CMP-003",
            "Stored map cannot be read",
            "The stored map {file} could not be read: {reason}.",
            "The stored verdict and decision table still stand. Close any program that has the file open and open the"
            " result again; if the file is damaged, inspect the board again on Inspection.",
        ),
        ErrorCode(
            "AOI-CMP-004",
            "Result cannot be judged again",
            "The result of {file} cannot be judged again with other thresholds: what it was judged on is no longer"
            " stored ({missing}).",
            "Its stored verdict and decision table still stand. Inspect the board again on Inspection, then try the"
            " thresholds on the new result. The maps of OK results are deleted {days} days after inspection; NG and"
            " WARN maps are kept.",
        ),
        ErrorCode(
            "AOI-CMP-005",
            "Thresholds of another board model",
            "The thresholds tried are board model {tried}'s, but the result of {file} was judged for board model"
            " {judged}.",
            "Nothing was judged. Open the result on Compare with its own board model picked, then try the thresholds"
            " again.",
        ),
        ErrorCode(
            "AOI-TRN-001",
            "AI model file refused",
            "AI model file refused: {path} could not be loaded as a weights-only model file this app wrote ({reason}).",
            "Train the board model again, or import a model file exported by this app.",
        ),
        ErrorCode(
            "AOI-TRN-002",
            "Not enough good boards to train",
            "Training needs at least 2 OK (good board) images; {found} found.",
            "Upload more OK images for this board model, then train again.",
        ),
        ErrorCode(
            "AOI-TRN-003",
            "No trained AI model",
            "Board model {board} has no trained AI model, so only the golden-board comparison runs.",
            "Train a model on the Training page when the AI checks are needed.",
        ),
        ErrorCode(
            "AOI-TRN-004",
            "Training gave an AI model that cannot judge boards",
            "Training made an AI model that cannot judge boards ({reason}), so it was not saved; the AI model in use "
            "is unchanged.",
            "Import photos of several different good boards (copies of one photo leave nothing to learn), then train "
            "again.",
        ),
        ErrorCode(
            "AOI-TRN-005",
            "Board model name already taken",
            "Board model {existing} already exists, and {name} differs from it only in upper and lower case; Windows "
            "would store the AI model and golden board files of both as the same files.",
            "Select {existing} in the top bar, or give the new board model a name that differs in more than case.",
        ),
        ErrorCode(
            "AOI-TRN-006",
            "Reference must be a good board",
            "Sample {sample} is labelled {label}; only an OK (good board) sample can be the reference image that "
            "inspections compare against.",
            "Select an OK sample, or relabel this one OK if it shows a good board, then press Set Reference again.",
        ),
        ErrorCode(
            "AOI-TRN-007",
            "Reference sample cannot change",
            "Sample {sample} is the reference image that inspections compare against, so it cannot be {change} while"
            " it is; it was left unchanged.",
            "Select another good (OK) sample and press Set Reference; then try again.",
        ),
        ErrorCode(
            "AOI-USR-001",
            "Not allowed for this role",
            "{what} needs the {roles} role.",
            "Sign in as a user with that role, or ask one to do it.",
        ),
        ErrorCode(
            "AOI-USR-002",
            "Last Admin",
            "{name} is the only user with the Admin role, so it cannot change to {role}: no one could then manage "
            "users or settings.",
            "Give another user the Admin role first, then change this one.",
        ),
        ErrorCode(
            "AOI-SET-001",
            "Workspace from version 0.1",
            "This workspace was created by AOI PoC Inspector 0.1 and cannot be upgraded.",
            "Choose a new workspace folder in the window that opens next; Cancel there closes the app.",
        ),
        ErrorCode(
            "AOI-SET-002",
            "Workspace newer than the app",
            "The workspace database was written by a newer build of the app: it records migration {migration}, "
            "which this build does not have.",
            "Update the app, or choose another workspace folder in the window that opens next; Cancel there closes "
            "the app.",
        ),
        ErrorCode(
            "AOI-SET-003",
            "Migration file changed",
            "Migration {file} differs from the one recorded in the workspace database; a shipped migration is never "
            "edited.",
            "Reinstall the app to restore the file, or choose another workspace folder in the window that opens next; "
            "Cancel there closes the app.",
        ),
        ErrorCode(
            "AOI-SET-004",
            "Migration failed",
            "Migration {file} failed and was rolled back: {error}.",
            "Restart the app; if it happens again, report it with the log file. To go back to the version you "
            "upgraded from, close the app and copy the backup aoi.sqlite.bak-… in the workspace folder over aoi.sqlite "
            "(engineer manual, chapter 1).",
        ),
        ErrorCode(
            "AOI-SET-005",
            "Workspace folder cannot hold the database",
            "The workspace folder does not support the database's write-ahead log (is it on a network drive?).",
            "Choose a folder on this computer in the window that opens next; Cancel there closes the app.",
        ),
        ErrorCode(
            "AOI-SET-006",
            "Migration files invalid",
            "The app's migration files are not valid: {problem}.",
            "Reinstall the app and report it; this is a defect in the build.",
        ),
        ErrorCode(
            "AOI-SET-007",
            "Unexpected error",
            "An unexpected error ({error_type}) stopped the last action{context}.",
            "Try again; if it happens again, restart the app and send the log file (the workspace's logs folder) to "
            "support.",
        ),
        ErrorCode(
            "AOI-SET-008",
            "Setting invalid",
            "The setting {name} is {value}; it must be {expected}.",
            "On the Settings page, correct it and save again. If the app stopped at start-up, fix or remove that line "
            "in settings.json, in the default workspace folder, and start the app again.",
        ),
        ErrorCode(
            "AOI-SET-009",
            "Backup before upgrade failed",
            "The workspace database could not be copied to {file} before this version upgrades it: {error}. Nothing "
            "was changed.",
            "Free disk space on the workspace folder's drive and check that the folder can be written, then start the "
            "app again.",
        ),
        ErrorCode(
            "AOI-SET-010",
            "Settings file cannot be read",
            "The settings file {path} could not be read: {reason}.",
            "Correct the file, or rename it so the app starts with the default settings, then start the app again.",
        ),
        ErrorCode(
            "AOI-SET-011",
            "Workspace cannot be opened",
            "The workspace folder {path} could not be opened: {error}.",
            "If the folder is on a drive that is not connected, connect it and start the app again; if its database "
            "aoi.sqlite is damaged, restore the backup aoi.sqlite.bak-… (engineer manual, chapter 1). Or choose "
            "another workspace folder in the window that opens next; Cancel there closes the app.",
        ),
        ErrorCode(
            "AOI-SET-012",
            "Workspace database in use",
            "Another program holds the workspace database {path}, so the app could not write to it: {error}.",
            "Close the other program (another copy of this app, a database tool or a backup), then choose the same "
            "folder in the window that opens next; or choose another workspace folder there. Cancel there closes the "
            "app.",
        ),
    )
}


class AoiError(Exception):
    """An error with a code and a plain message. ``str(e)`` is "<code> <what> <action>"."""

    def __init__(self, code: str, detail: str | None = None, **params: object) -> None:
        self.entry = CODES[code]
        self.code = code
        self.detail = detail
        self.what = self.entry.what.format(**params)
        self.action = self.entry.action.format(**params)
        super().__init__(f"{code} {self.what} {self.action}")

    @property
    def message(self) -> str:
        """What the user reads: what happened and what to do, without the code."""
        return f"{self.what} {self.action}"


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
