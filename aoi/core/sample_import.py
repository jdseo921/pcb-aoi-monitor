"""What a sample import is given and what it did with each file (REQ-TRN-001, stage S31). No Qt: the Training page's
import sheet shows these, and `AppContext.import_files` fills the report."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from .. import defects as taxonomy
from ..errors import AoiError
from .imaging import list_images

LABELS = ("OK", "NG")  # a sample's label as the samples table holds it, and the name of its copy's folder
OK_FOLDERS = ("ok", "good")
NG_FOLDERS = ("ng", "bad", "defect", "defects")
# a file refused with one of these is listed with its code and the import goes on: what is wrong is that file's
REFUSED = frozenset(
    {"AOI-INSP-001", "AOI-INSP-004", "AOI-INSP-005", "AOI-INSP-006", "AOI-INSP-007"}  # Inspection's checks (Q30)
    | {"AOI-TRN-013", "AOI-TRN-014", "AOI-TRN-015", "AOI-TRN-016"}  # no type, changed, already imported, no label
    | {"AOI-TRN-017", "AOI-TRN-018"}  # a view or a label not known
)


@dataclass
class ImportFile:
    """One file to import: its path, its label ("OK" or "NG"; None while it has none), its defect type (one of the 33
    DCT types for NG) and its camera view."""

    path: str
    label: str | None
    defect_type: str | None = None
    side: str = "Top"


@dataclass
class ImportReport:
    """What an import did with the files it was given: each one imported, each refused or skipped with its coded
    error, the file an error stopped it at with that error, and the files it never reached (after Cancel or that
    error), each list in the order the files were given."""

    added: list[ImportFile] = field(default_factory=list)
    refused: list[tuple[ImportFile, AoiError]] = field(default_factory=list)
    stopped: tuple[ImportFile, Exception] | None = None
    left: list[ImportFile] = field(default_factory=list)


def defect_type_named(name: str) -> str | None:
    """The DCT type a folder is named after, with spaces or underscores and in any case ("solder_bridge" is Solder
    Bridge), or None: "Unknown" and the AI model's "Anomaly" are not among the 33."""
    key = name.replace("_", " ").strip().casefold()
    return next((n for n in taxonomy.names() if n.casefold() == key), None)


def folder_files(folder: str | Path) -> list[ImportFile]:
    """Every image file under `folder`, labelled by its sub-folders: OK under ok/ (or good/), NG under ng/ (or bad/,
    defect/, defects/) with the type its own folder is named after (ng/solder_bridge/), and no label anywhere else,
    so the user picks one (AOI-TRN-016)."""
    files = []
    for p in list_images(folder):
        parts = [x.lower() for x in p.relative_to(folder).parts[:-1]]
        if any(x in OK_FOLDERS for x in parts):
            files.append(ImportFile(str(p), "OK"))
        elif any(x in NG_FOLDERS for x in parts):
            files.append(ImportFile(str(p), "NG", defect_type_named(p.parent.name)))
        else:
            files.append(ImportFile(str(p), None))
    return files
