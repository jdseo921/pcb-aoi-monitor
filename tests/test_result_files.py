"""Result files (REQ-INSP-021): each saved board's JSON and one-line CSV in the output folder within 1 s of its verdict,
valid against `docs/schemas/result-file.schema.json`, and the shift CSV listing every board."""

from __future__ import annotations

import csv
import json
import re
import time
from pathlib import Path
from typing import Any

import pytest

from aoi.config import Settings
from aoi.core.cycle import FrameMeta
from aoi.core.imaging import list_images
from aoi.core.result_files import COLUMNS, SHIFT_PREFIX
from aoi.core.services import AppContext
from aoi.errors import AoiError
from tests.test_req_done_in_v01 import BOARD

SCHEMA = json.loads((Path(__file__).parents[1] / "docs" / "schemas" / "result-file.schema.json").read_text("utf-8"))
TYPES = {"object": dict, "array": list, "string": str, "integer": int, "number": (int, float), "null": type(None)}


def problems(value: Any, schema: dict[str, Any], at: str = "$") -> list[str]:
    """What `value` breaks of `schema`, for the keywords the result-file schema uses (no validator is a dependency)."""
    out: list[str] = []
    kinds = schema.get("type", [])
    kinds = [kinds] if isinstance(kinds, str) else kinds
    if kinds and not any(isinstance(value, TYPES[k]) and not isinstance(value, bool) for k in kinds):
        return [f"{at}: {value!r} is not {kinds}"]
    if "const" in schema and value != schema["const"] or "enum" in schema and value not in schema["enum"]:
        out.append(f"{at}: {value!r} is not allowed")
    if isinstance(value, str):
        if len(value) < schema.get("minLength", 0) or not re.search(schema.get("pattern", ""), value):
            out.append(f"{at}: {value!r} is too short or does not match")
    if isinstance(value, int) and value < schema.get("minimum", value):
        out.append(f"{at}: {value} is below the minimum")
    if isinstance(value, dict):
        props = schema.get("properties", {})
        out += [f"{at}: no {k}" for k in schema.get("required", []) if k not in value]
        if schema.get("additionalProperties") is False:
            out += [f"{at}: {k} is not in the schema" for k in value if k not in props]
        out += [p for k, v in value.items() if k in props for p in problems(v, props[k], f"{at}.{k}")]
    if isinstance(value, list) and "items" in schema:
        out += [p for i, v in enumerate(value) for p in problems(v, schema["items"], f"{at}[{i}]")]
    return out


def test_req_insp_021_every_board_has_its_result_files_within_1_s_of_its_verdict(
    trained_ctx: AppContext, synthetic_dataset: Path, tmp_path: Path
) -> None:
    out = tmp_path / "out"
    trained_ctx.settings.output_folder = str(out)
    cycle, waits = trained_ctx.inspection_cycle(), []
    for path in sorted(list_images(synthetic_dataset / "test"))[:10]:  # OK and NG boards
        verdict_at: list[float] = []
        report = verdict_at.append  # the verdict's time, before the save (REQ-INSP-002)
        outcome = cycle.board(BOARD, FrameMeta(path, "Side"), report=lambda r, at=report: at(time.perf_counter()))()
        waits.append(time.perf_counter() - verdict_at[0])  # verdict to files on disk: the save writes them
        assert len(list(out.glob(f"{path.stem}_*.json"))) == 1 and outcome.record_id is not None
    print(f"REQ-INSP-021 verdict to result files: max {1000 * max(waits):.0f} ms over {len(waits)} boards")
    assert max(waits) < 1.0
    docs = [json.loads(f.read_text("utf-8")) for f in sorted(out.glob("*.json"))]
    assert [p for d in docs for p in problems(d, SCHEMA)] == []
    stored = {r["uuid"]: r for r in trained_ctx.inspections(board_model=BOARD)}
    assert {d["record_uuid"] for d in docs} == set(stored) and len(docs) == 10
    assert any(d["defects"] for d in docs) and {d["view"] for d in docs} == {"Side"}
    for d in docs:
        assert d["verdict"] == stored[d["record_uuid"]]["result"] and d["evidence"] in ("png", "jpeg")
        (line,) = csv.reader(out.joinpath(f"{d['board_id']}_{d['record_uuid']}.csv").read_text("utf-8").splitlines())
        cells = ["" if d[c] is None else str(d[c]) for c in COLUMNS[:6]] + [str(len(d["defects"]))]
        assert line[:7] == cells and line[-3:] == [d["evidence"], d["board_model"], d["record_uuid"]]
    (shift,) = out.glob(f"{SHIFT_PREFIX}*.csv")
    rows = list(csv.DictReader(shift.read_text("utf-8").splitlines()))
    assert [r["record_uuid"] for r in rows] == [r["uuid"] for r in sorted(stored.values(), key=lambda r: r["id"])]
    assert len(rows) == 10 and list(rows[0]) == list(COLUMNS)


def test_req_insp_021_a_folder_that_refuses_the_files_is_alarmed_and_the_record_kept(
    trained_ctx: AppContext, synthetic_dataset: Path, tmp_path: Path
) -> None:
    (tmp_path / "a file").write_text("not a folder")
    trained_ctx.settings.output_folder = str(tmp_path / "a file")
    path = sorted(list_images(synthetic_dataset / "test"))[0]
    outcome = trained_ctx.inspection_cycle().board(BOARD, FrameMeta(path))()
    assert outcome.record_id is not None and outcome.save_error is None
    (alarm,) = [a for a in trained_ctx.alarms() if a["code"] == "AOI-INSP-019"]
    assert path.name in alarm["message"] and "a file" in alarm["message"]


def test_req_insp_021_no_output_folder_writes_none_and_a_relative_one_is_refused(tmp_path: Path) -> None:
    Settings.check("output_folder", "")
    Settings.check("output_folder", str(tmp_path))
    with pytest.raises(AoiError, match="AOI-SET-008"):
        Settings.check("output_folder", "out")
    assert Settings().output_folder == ""
