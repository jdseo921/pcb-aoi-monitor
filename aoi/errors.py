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
            "Use a smaller image, or ask an Admin whether the limit can be raised.",
        ),
        ErrorCode(
            "AOI-INSP-006",
            "Image file cannot be decoded",
            "The {kind} image {path} could not be decoded: {reason}.",
            "Copy the file again from the camera or its source; if it fails again, save it as PNG or JPG with an image "
            "tool and load that file.",
        ),
        ErrorCode(
            "AOI-TRN-001",
            "AI model file refused",
            "AI model file refused: {path} is not a weights-only model file this app wrote ({reason}).",
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
            "AOI-USR-001",
            "Not allowed for this role",
            "{what} needs the {roles} role.",
            "Sign in as a user with that role, or ask one to do it.",
        ),
        ErrorCode(
            "AOI-SET-001",
            "Workspace from version 0.1",
            "This workspace was created by AOI PoC Inspector 0.1 and cannot be upgraded.",
            "Choose a new workspace folder in Settings.",
        ),
        ErrorCode(
            "AOI-SET-002",
            "Workspace newer than the app",
            "The workspace database was written by a newer build of the app: it records migration {migration}, "
            "which this build does not have.",
            "Update the app, or choose another workspace folder in Settings.",
        ),
        ErrorCode(
            "AOI-SET-003",
            "Migration file changed",
            "Migration {file} differs from the one recorded in the workspace database; a shipped migration is never "
            "edited.",
            "Reinstall the app to restore the file, or choose another workspace folder in Settings.",
        ),
        ErrorCode(
            "AOI-SET-004",
            "Migration failed",
            "Migration {file} failed and was rolled back: {error}.",
            "Restart the app; if it happens again, report it with the log file.",
        ),
        ErrorCode(
            "AOI-SET-005",
            "Workspace folder cannot hold the database",
            "The workspace folder does not support the database's write-ahead log (is it on a network drive?).",
            "Choose a folder on this computer in Settings.",
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
