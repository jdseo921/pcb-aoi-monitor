"""Result files (REQ-INSP-021, ADR 0024 D10): each saved board as a JSON file and a one-line CSV in the output folder,
written atomically after its record commits, and a line in the shift CSV of the local date, which lists every board of
the day. The fields are those of `docs/schemas/result-file.schema.json`; the CSV columns are `COLUMNS`. Its CSV files
are for machines: UTF-8 with no byte order mark and cells as they are, with no formula guard, unlike the CSV export a
person opens in Excel (`AppContext.csv_bytes`, #113), since a guard would change a board ID. Until the line's
file-naming contract arrives (REQ-INSP-020), a board's ID is its image file's stem."""

from __future__ import annotations

import csv
import errno
import io
import json
import os
import threading
from pathlib import Path
from typing import Any

from ..data import atomic
from .inspector import InspectionResult, Inspector

SCHEMA_VERSION = 1
COLUMNS = (
    "board_id", "view", "verdict", "time", "model_version", "recipe_rev", "defect_count", "defects", "evidence",
    "board_model", "record_uuid",
)  # fmt: skip
SHIFT_PREFIX = "shift_"
_shift_lock = threading.Lock()  # one line at a time into a shift CSV, whichever cycle saved the board
Held = dict[Path, list[str]]  # the lines shift CSVs refused, in board order, by shift CSV: one per AppContext


class ShiftNotWritten(Exception):
    """The board's own result files were written, but a shift CSV, `shift`, still refuses the lines kept back for it
    (`cause`), this board's or an earlier one's: they stay kept, for the next write or `flush` that it takes. `first`:
    `shift` kept no line before this board's, so its refusal is new and is alarmed; a file newly refused is named
    before one refused already."""

    def __init__(self, shift: Path, cause: Exception, first: bool) -> None:
        super().__init__(str(cause))
        self.shift, self.cause, self.first = shift, cause, first


def document(
    board_model: str, path: str, res: InspectionResult, insp: Inspector, uid: str, evidence: str, time: str
) -> dict[str, Any]:
    """One board's result file: `evidence` is what the record kept (png, jpeg, or none at a full disk)."""
    return {
        "schema_version": SCHEMA_VERSION,
        "board_id": Path(path).stem,
        "board_model": board_model,
        "view": res.view,
        "verdict": res.verdict,
        "time": time,
        "model_version": insp.model_version,
        "recipe_rev": insp.recipe_rev,
        "defects": [
            {
                "no": d.no,
                "type": d.type,
                "severity": d.severity,
                "score": round(d.score, 3),
                "box": {"x": d.x, "y": d.y, "w": d.w, "h": d.h},
            }
            for d in res.defects
        ],
        "evidence": evidence,
        "record_uuid": uid,
    }


def csv_row(doc: dict[str, Any]) -> str:
    """The document as one CSV line in `COLUMNS` order; each defect is type:severity:x,y,w,h, joined by |."""
    boxes = [",".join(str(v) for v in d["box"].values()) for d in doc["defects"]]
    defects = "|".join(f"{d['type']}:{d['severity']}:{box}" for d, box in zip(doc["defects"], boxes, strict=True))
    values = {**doc, "defect_count": len(doc["defects"]), "defects": defects}
    out = io.StringIO()
    csv.writer(out, lineterminator="\n").writerow(["" if values[c] is None else values[c] for c in COLUMNS])
    return out.getvalue()


def write(folder: Path, doc: dict[str, Any], day: str, stem: str, held: Held) -> list[Path]:
    """Write the board's `<stem>_<record UUID>.json` and `.csv` together or not at all, then add its line to
    `shift_<day>.csv` (with the header first in a new one), replacing the file whole, so a reader never sees half of
    one. The names are put together whole, so a stem with a dot in it (a revision R1.2) keeps its record UUID. The
    folder must exist: one gone (a share or drive not there) is never made again on the station's own disk. The shift
    CSV is this station's: two stations never share an output folder. A shift CSV that refuses the write (Windows
    refuses to replace a file a spreadsheet holds open) keeps the line back in `held`, and every line kept back for any
    shift CSV goes in with the next write it takes (`ShiftNotWritten` while one is still kept). Returns the paths."""
    if not folder.is_dir():
        raise FileNotFoundError(errno.ENOENT, os.strerror(errno.ENOENT), str(folder))
    name, row = f"{stem}_{doc['record_uuid']}", csv_row(doc)
    body = (json.dumps(doc, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    files = [folder / f"{name}.json", folder / f"{name}.csv"]
    atomic.write_all([(files[0], body), (files[1], row.encode("utf-8"))])
    shift = folder / f"{SHIFT_PREFIX}{day}.csv"
    with _shift_lock:
        kept = set(held)  # the shift CSVs that kept lines before this board's
        held.setdefault(shift, []).append(row)
        refused = _add(held)
    if refused:
        new = [r for r in refused if r[0] not in kept]
        raise ShiftNotWritten(*(new or refused)[0], first=bool(new))
    return [*files, shift]


def flush(held: Held) -> tuple[Path, Exception] | None:
    """Add the lines kept back in `held` to the shift CSVs that take them now (the heartbeat's timer, and close): the
    first that still refuses and why, else None."""
    with _shift_lock:
        refused = _add(held)
    return refused[0] if refused else None


def _add(held: Held) -> list[tuple[Path, Exception]]:
    """Each shift CSV's kept lines added after what it holds, in board order, and dropped from `held` once in: a file
    whose folder is gone is never made again, and one a spreadsheet saved in another encoding, or that refuses the
    write, keeps them. A write refused after the file took the lines (a folder that cannot be synced) counts as in, so
    no line goes in twice. Under `_shift_lock`. Returns each file that keeps lines, with why, in board order."""
    refused: list[tuple[Path, Exception]] = []
    for shift, lines in list(held.items()):
        text = None
        try:
            if not shift.parent.is_dir():
                raise FileNotFoundError(errno.ENOENT, os.strerror(errno.ENOENT), str(shift.parent))
            before = shift.read_text(encoding="utf-8") if shift.is_file() else ",".join(COLUMNS) + "\n"
            text = before + "".join(lines)
            atomic.write_text(shift, text)
        except (OSError, UnicodeError) as e:
            if text is None or not _holds(shift, text):
                refused.append((shift, e))
                continue
        del held[shift]
    return refused


def _holds(path: Path, text: str) -> bool:
    try:
        return path.read_text(encoding="utf-8") == text
    except (OSError, UnicodeError):
        return False
