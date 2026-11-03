"""Result files (REQ-INSP-021, ADR 0024 D10): each saved board as a JSON file and a one-line CSV in the output folder,
written atomically after its record commits, and a line in the shift CSV of the local date, which lists every board of
the day. The fields are those of `docs/schemas/result-file.schema.json`; the CSV columns are `COLUMNS`. Until the line's
file-naming contract arrives (REQ-INSP-020), a board's ID is its image file's stem."""

from __future__ import annotations

import csv
import io
import json
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


def write(folder: Path, doc: dict[str, Any], day: str, stem: str) -> list[Path]:
    """Write the board's `<stem>_<record UUID>.json` and `.csv`, then add its line to `shift_<day>.csv` (with the
    header first in a new one); each file is replaced whole, so a reader never sees half of one. Returns the paths."""
    name = folder / f"{stem}_{doc['record_uuid']}"
    row = csv_row(doc)
    atomic.write_text(name.with_suffix(".json"), json.dumps(doc, ensure_ascii=False, indent=2) + "\n")
    atomic.write_text(name.with_suffix(".csv"), row)
    shift = folder / f"{SHIFT_PREFIX}{day}.csv"
    with _shift_lock:
        before = shift.read_text(encoding="utf-8") if shift.is_file() else ",".join(COLUMNS) + "\n"
        atomic.write_text(shift, before + row)
    return [name.with_suffix(".json"), name.with_suffix(".csv"), shift]
