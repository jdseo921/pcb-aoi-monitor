"""Result files (REQ-INSP-021): each saved board's JSON and one-line CSV in the output folder within 1 s of its verdict,
valid against `docs/schemas/result-file.schema.json`, and the shift CSV listing every board."""

from __future__ import annotations

import csv
import json
import os
import re
import shutil
import time
from pathlib import Path
from typing import Any
from unittest.mock import ANY

import pytest

from aoi.config import Settings
from aoi.core import result_files
from aoi.core.cycle import FrameMeta
from aoi.core.imaging import list_images
from aoi.core.result_files import COLUMNS, SHIFT_PREFIX, csv_row
from aoi.core.services import AppContext
from aoi.data import atomic
from aoi.errors import AoiError
from tests.conftest import log_rows
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
    out.mkdir()  # an Admin points it at a folder that exists
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
        boxes = [
            f"{e['type']}:{e['severity']}:{b['x']},{b['y']},{b['w']},{b['h']}" for e in d["defects"] for b in [e["box"]]
        ]
        assert line[7] == "|".join(boxes) and d["time"] == stored[d["record_uuid"]]["time"]
    (shift,) = out.glob(f"{SHIFT_PREFIX}*.csv")
    rows = list(csv.DictReader(shift.read_text("utf-8").splitlines()))
    assert [r["record_uuid"] for r in rows] == [r["uuid"] for r in sorted(stored.values(), key=lambda r: r["id"])]
    assert len(rows) == 10 and list(rows[0]) == list(COLUMNS)
    singles = {f.stem.rsplit("_", 1)[1]: f.read_text("utf-8") for f in out.glob("*.csv") if f != shift}
    assert shift.read_text("utf-8").splitlines(keepends=True)[1:] == [singles[r["record_uuid"]] for r in rows]


def test_req_insp_021_a_board_id_with_a_dot_keeps_its_own_result_files(
    trained_ctx: AppContext, synthetic_dataset: Path, tmp_path: Path
) -> None:
    """A revision such as R1.2 in the image's name: each board keeps its own `<board ID>_<record UUID>` files."""
    out, boards = tmp_path / "out", tmp_path / "boards"
    out.mkdir()
    boards.mkdir()
    trained_ctx.settings.output_folder = str(out)
    cycle = trained_ctx.inspection_cycle()
    for n, path in enumerate(sorted(list_images(synthetic_dataset / "test"))[:3], 1):
        cycle.board(BOARD, FrameMeta(shutil.copy(path, boards / f"TBOXA1_R1.2_SN000{n}_TOP.png")))()
    stored = {r["uuid"] for r in trained_ctx.inspections(board_model=BOARD)}
    docs = [json.loads(f.read_text("utf-8")) for f in out.glob("TBOXA1_*.json")]
    names = {f"{d['board_id']}_{d['record_uuid']}" for d in docs}
    assert len(docs) == 3 and {d["record_uuid"] for d in docs} == stored
    assert {d["board_id"] for d in docs} == {f"TBOXA1_R1.2_SN000{n}_TOP" for n in (1, 2, 3)}
    files = {f.name for f in out.iterdir() if not f.name.startswith(SHIFT_PREFIX)}
    assert files == {f"{n}{e}" for n in names for e in (".json", ".csv")}


def _refusing(monkeypatch: pytest.MonkeyPatch, refused: list[str]) -> None:
    """Windows refuses to replace a file a spreadsheet holds open: os.replace on a file whose name starts with one of
    `refused` fails, as long as it is listed there."""
    replace = os.replace

    def refusing(src: str, dst: str) -> None:
        if any(Path(dst).name.startswith(name) for name in refused):
            raise PermissionError(13, "Access is denied", str(dst))
        replace(src, dst)

    monkeypatch.setattr(atomic.os, "replace", refusing)


def test_req_insp_021_a_shift_csv_held_open_loses_no_line_and_says_so(
    trained_ctx: AppContext, synthetic_dataset: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The board's own files are written, its line is kept and goes in with the next board's, and the alarm names the
    shift file, not the board's files: once while lines are kept, and again for a refusal after they all went in."""
    out, refused = tmp_path / "out", list[str]()
    out.mkdir()
    trained_ctx.settings.output_folder = str(out)
    _refusing(monkeypatch, refused)
    paths, cycle = sorted(list_images(synthetic_dataset / "test"))[:6], trained_ctx.inspection_cycle()
    for n, path in enumerate(paths):
        refused[:] = [SHIFT_PREFIX] if n in (1, 2, 4) else []  # open in a spreadsheet for boards 2 and 3, then 5
        assert cycle.board(BOARD, FrameMeta(path))().record_id is not None
    (shift,) = out.glob(f"{SHIFT_PREFIX}*.csv")
    rows = list(csv.DictReader(shift.read_text("utf-8").splitlines()))
    stored = sorted(trained_ctx.inspections(board_model=BOARD), key=lambda r: r["id"])
    assert [r["record_uuid"] for r in rows] == [r["uuid"] for r in stored] and len(rows) == 6
    assert len(list(out.glob("*.json"))) == 6 and not trained_ctx._shift_lines
    alarms = [a for a in trained_ctx.alarms() if a["code"] in ("AOI-INSP-019", "AOI-INSP-020")]
    assert sorted(a["code"] for a in alarms) == ["AOI-INSP-020"] * 2, "once per refusal, never AOI-INSP-019"
    named = {p.name for p in paths for a in alarms if p.name in a["message"]}
    assert named == {paths[1].name, paths[4].name} and all(shift.name in a["message"] for a in alarms)


def test_req_insp_021_a_line_kept_back_goes_in_by_the_timer_or_at_close(
    trained_ctx: AppContext, synthetic_dataset: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """With no board after it, a kept line goes in from the heartbeat's timer once the file takes it, and at close."""
    out, refused = tmp_path / "out", list[str]()
    out.mkdir()
    trained_ctx.settings.output_folder = str(out)
    _refusing(monkeypatch, refused)
    cycle = trained_ctx.inspection_cycle()
    for step, path in enumerate(sorted(list_images(synthetic_dataset / "test"))[:2]):
        refused[:] = [SHIFT_PREFIX]
        cycle.board(BOARD, FrameMeta(path))()
        trained_ctx._add_shift_lines()  # the timer, while the file is still refused: kept
        assert [len(lines) for lines in trained_ctx._shift_lines.values()] == [1]
        refused.clear()
        if step == 0:  # one beat of the heartbeat's timer: stopping is set, so it beats once and returns
            trained_ctx._stopping.set()
            trained_ctx._beat()
        else:
            trained_ctx.close()
        (shift,) = out.glob(f"{SHIFT_PREFIX}*.csv")
        assert len(shift.read_text("utf-8").splitlines()) == step + 2 and not trained_ctx._shift_lines


def test_req_insp_021_a_line_still_refused_at_close_is_logged_with_its_record(
    trained_ctx: AppContext, synthetic_dataset: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A line the shift CSV still refuses when the app closes is not added: the log names its file and record."""
    out = tmp_path / "out"
    out.mkdir()
    trained_ctx.settings.output_folder = str(out)
    _refusing(monkeypatch, [SHIFT_PREFIX])
    record = trained_ctx.inspection_cycle().board(
        BOARD, FrameMeta(sorted(list_images(synthetic_dataset / "test"))[0])
    )()
    uuid = trained_ctx.db.inspection(record.record_id)["uuid"]
    trained_ctx.close()
    (lost,) = [r for r in log_rows(trained_ctx.settings.root / "logs") if r["event"] == "result_file.shift_lines_lost"]
    assert list(lost["records"].values()) == [[uuid]]


def _doc(uuid: str) -> dict[str, Any]:
    return {c: c for c in COLUMNS} | {"record_uuid": uuid, "model_version": None, "recipe_rev": None, "defects": []}


def _uuids(shift: Path) -> list[str]:
    return [line.rsplit(",", 1)[-1] for line in shift.read_text("utf-8").splitlines()[1:]]


def test_req_insp_021_kept_lines_survive_a_day_change_a_resave_and_a_gone_folder(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Yesterday's file still refused keeps the alarm standing (no new one) while today's takes its line; a file a
    spreadsheet saved in another encoding keeps the lines until it is moved away, then starts again with them; a write
    that fails after the file took the lines adds them once; and a held file's folder gone is never made again."""
    folder, refused, kept = tmp_path / "out", ["shift_2026-11-05"], result_files.Held()
    folder.mkdir()
    yesterday, today = folder / "shift_2026-11-05.csv", folder / "shift_2026-11-06.csv"
    _refusing(monkeypatch, refused)
    with pytest.raises(result_files.ShiftNotWritten) as first:
        result_files.write(folder, _doc("u1"), "2026-11-05", "b1", kept)
    assert first.value.first and first.value.shift == yesterday
    with pytest.raises(result_files.ShiftNotWritten) as standing:
        result_files.write(folder, _doc("u2"), "2026-11-06", "b2", kept)
    assert not standing.value.first and standing.value.shift == yesterday and _uuids(today) == ["u2"]
    refused[:] = [SHIFT_PREFIX]  # today's file opened too: a refusal of its own, named and alarmed
    with pytest.raises(result_files.ShiftNotWritten) as also:
        result_files.write(folder, _doc("u3"), "2026-11-06", "b3", kept)
    assert also.value.first and also.value.shift == today
    refused[:] = ["shift_2026-11-06"]  # yesterday's closed: its lines go in from the timer, today's stay kept
    assert result_files.flush(kept) == (today, ANY) and _uuids(yesterday) == ["u1"]
    with pytest.raises(result_files.ShiftNotWritten) as still:
        result_files.write(folder, _doc("u4"), "2026-11-06", "b4", kept)
    assert not still.value.first and still.value.shift == today
    refused.clear()
    assert result_files.flush(kept) is None and not kept and _uuids(today) == ["u2", "u3", "u4"]
    today.unlink()
    today.write_bytes("board_id,뷰\n".encode("cp949"))  # saved over by a spreadsheet, in the Korean code page
    with pytest.raises(result_files.ShiftNotWritten) as resaved:
        result_files.write(folder, _doc("u5"), "2026-11-06", "b5", kept)
    assert resaved.value.first and isinstance(resaved.value.cause, UnicodeError)
    today.rename(tmp_path / "saved_over.csv")
    sync, syncs = atomic._sync_folder, [0]

    def shift_sync_fails(path: Path) -> None:  # the board's own files' sync first, then the shift CSV's, refused
        syncs[0] += 1
        if syncs[0] == 2:
            raise OSError(5, "Input/output error")
        sync(path)

    monkeypatch.setattr(atomic, "_sync_folder", shift_sync_fails)
    result_files.write(folder, _doc("u6"), "2026-11-06", "b6", kept)
    assert syncs[0] == 2 and _uuids(today) == ["u5", "u6"] and not kept
    refused.append(SHIFT_PREFIX)
    with pytest.raises(result_files.ShiftNotWritten):
        result_files.write(folder, _doc("u7"), "2026-11-06", "b7", kept)
    shutil.rmtree(folder)
    refused.clear()
    assert result_files.flush(kept) is not None and not folder.exists() and kept


def test_req_insp_021_a_csv_line_leaves_an_empty_cell_for_none_and_quotes_a_comma() -> None:
    doc = {c: f"{c}" for c in COLUMNS} | {"board_id": 'A,"1"', "model_version": None, "recipe_rev": None, "defects": []}
    (line,) = csv.reader([csv_row(doc)])
    assert line[0] == 'A,"1"' and line[4:8] == ["", "", "0", ""] and csv_row(doc).count("\n") == 1


def test_req_insp_021_a_folder_that_refuses_the_files_is_alarmed_and_the_record_kept(
    trained_ctx: AppContext, synthetic_dataset: Path, tmp_path: Path
) -> None:
    (tmp_path / "a file").write_text("not a folder")
    trained_ctx.settings.output_folder = str(tmp_path / "a file")
    first, second = sorted(list_images(synthetic_dataset / "test"))[:2]
    cycle = trained_ctx.inspection_cycle()
    outcomes = [cycle.board(BOARD, FrameMeta(p))() for p in (first, second)]
    assert all(o.record_id is not None and o.save_error is None for o in outcomes)
    (alarm,) = [a for a in trained_ctx.alarms() if a["code"] == "AOI-INSP-019"]  # once, not once per board
    assert first.name in alarm["message"] and "a file" in alarm["message"]
    trained_ctx.settings.output_folder = str(tmp_path / "gone")  # never made on the station's own disk
    cycle.board(BOARD, FrameMeta(second))()
    assert not (tmp_path / "gone").exists()


def test_req_insp_021_no_output_folder_writes_none_and_a_relative_one_is_refused(tmp_path: Path) -> None:
    Settings.check("output_folder", "")
    Settings.check("output_folder", str(tmp_path))
    with pytest.raises(AoiError, match="AOI-SET-008"):
        Settings.check("output_folder", "out")
    assert Settings().output_folder == ""
