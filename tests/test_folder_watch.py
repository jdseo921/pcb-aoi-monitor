"""The watched input folder (REQ-INSP-020, ADR 0024 D26): a complete file is inspected within 2 s and moved to done/,
a partial one waited for, one that breaks the naming contract, was inspected before or cannot be read moved to
failed/ with its code, one of another board model left where it is, and a board never inspected twice."""

from __future__ import annotations

import json
import os
import shutil
import time
from pathlib import Path

import numpy as np
import pytest

from aoi.config import Settings
from aoi.core import folder_watch
from aoi.core.cycle import FrameMeta
from aoi.core.folder_watch import DONE, FAILED, WORKING, FolderWatch, board_id, parse
from aoi.core.imaging import list_images, load_image_sha256
from aoi.core.services import AppContext
from aoi.errors import AoiError
from tests.test_req_done_in_v01 import BOARD

NAMES = [f"{BOARD}_R1_{i:04d}_Side_20261106T1030{i:02d}Z.png" for i in range(10)]
OTHER = "OTHER_R1_3_Top_20261106T103000Z.png"


def arrive(src: Path, folder: Path, name: str) -> None:
    """As the contract asks of the imaging station: written under a temporary name, renamed once complete."""
    shutil.copyfile(src, folder / f"{name}.part")
    os.replace(folder / f"{name}.part", folder / name)


def taken(watch: FolderWatch) -> tuple[np.ndarray, FrameMeta] | None:
    """Look as the line does, every LOOK_S, until a file is taken, or for 3 s."""
    until = time.monotonic() + 3
    while (got := watch.grab(BOARD)) is None and time.monotonic() < until:
        time.sleep(folder_watch.LOOK_S)
    return got


def bare(folder: Path) -> tuple[FolderWatch, list[AoiError], dict[str, Path]]:
    """A watch with no context: the records' images by SHA-256 are a dict the test fills."""
    told: list[AoiError] = []
    records: dict[str, Path] = {}
    return FolderWatch(folder, load_image_sha256, records.get, told.append), told, records


def test_req_insp_020_a_complete_file_is_inspected_within_2_s_and_moved_to_done(
    trained_ctx: AppContext, synthetic_dataset: Path, tmp_path: Path
) -> None:
    inbox, out = tmp_path / "in", tmp_path / "out"
    inbox.mkdir(), out.mkdir()
    trained_ctx.settings.input_folder, trained_ctx.settings.output_folder = str(inbox), str(out)
    watch, cycle = trained_ctx.folder_watch(), trained_ctx.inspection_cycle()
    assert watch is not None
    srcs, waits = sorted(list_images(synthetic_dataset / "test"))[:10], []
    for src, name in zip(srcs, NAMES, strict=True):
        arrive(src, inbox, name)
        arrived, verdict_at = time.perf_counter(), []

        def report(got: object, at: list[float] = verdict_at) -> None:
            if not isinstance(got, FrameMeta):
                at.append(time.perf_counter())

        while (outcome := cycle.watched(BOARD, watch, report)()) is None:
            time.sleep(folder_watch.LOOK_S)  # the page's pace between looks
        waits.append(verdict_at[0] - arrived)
        assert outcome.record_id is not None and outcome.path == inbox / DONE / name and outcome.result.view == "Side"
        assert (inbox / DONE / name).is_file() and not (inbox / name).exists() and not any((inbox / WORKING).iterdir())
    print(
        f"REQ-INSP-020 arrival to verdict at the line's pace: max {1000 * max(waits):.0f} ms over {len(waits)} boards"
    )
    assert max(waits) < 2.0
    stored = trained_ctx.inspections(board_model=BOARD)
    assert sorted(Path(r["image_path"]).name for r in stored) == NAMES
    docs = [json.loads(f.read_text("utf-8")) for f in out.glob("*.json")]
    assert sorted(d["board_id"] for d in docs) == [f"{i:04d}" for i in range(10)]
    assert {a["level"] for a in trained_ctx.alarms()} <= {"NG"}
    arrive(srcs[0], inbox, NAMES[0].replace("_0000_", "_0100_"))
    assert taken(watch) is None  # the same image under another name: its record keeps its SHA-256
    assert [a["code"] for a in trained_ctx.alarms() if a["level"] == "WARN"] == ["AOI-INSP-021"]


def test_req_insp_020_a_file_still_being_written_is_waited_for(synthetic_dataset: Path, tmp_path: Path) -> None:
    inbox = tmp_path / "in"
    inbox.mkdir()
    watch, told, _ = bare(inbox)
    data = next(iter(list_images(synthetic_dataset / "test"))).read_bytes()
    piece = len(data) // 8 + 1
    with open(inbox / NAMES[0], "wb") as f:  # written in place, in pieces, by a station that does not rename it
        for i in range(0, len(data), piece):
            f.write(data[i : i + piece])
            f.flush()
            os.utime(inbox / NAMES[0], (0, 0))  # a writer that keeps an old time (copy2, robocopy) waits as long
            assert watch.grab(BOARD) is None and watch.waiting == 1
            time.sleep(0.15)
    started = time.monotonic()
    got = taken(watch)
    assert got is not None and time.monotonic() - started >= folder_watch.SETTLE_S - 0.2 and not told


def test_req_insp_020_a_file_that_breaks_the_contract_or_cannot_be_read_goes_to_failed(
    synthetic_dataset: Path, tmp_path: Path
) -> None:
    inbox = tmp_path / "in"
    inbox.mkdir()
    watch, told, _ = bare(inbox)
    src = next(iter(list_images(synthetic_dataset / "test")))
    bad = ["board1.png", f"{BOARD}_R1_1_Front_20261106T103000Z.png", f"{BOARD}_R1_1_Top_20261399T103000Z.png"]
    for name in bad:
        arrive(src, inbox, name)
    unread = f"{BOARD}_R1_2_Top_20261106T103000Z.png"
    (inbox / unread).write_bytes(b"not an image")
    (inbox / "notes.txt").write_text("not a board")  # not an image file: never touched
    assert taken(watch) is None
    assert sorted(p.name for p in (inbox / FAILED).iterdir()) == sorted([*bad, unread])
    assert sorted(e.code for e in told) == ["AOI-INSP-020"] * 3 + ["AOI-INSP-022"]
    assert any("not a real date" in e.what for e in told) and (inbox / "notes.txt").is_file()
    arrive(src, inbox, OTHER)
    with pytest.raises(AoiError, match="AOI-INSP-024"):  # another board model's board: the line pauses on it
        taken(watch)
    assert (inbox / OTHER).is_file()


def test_req_insp_020_a_board_is_never_inspected_twice_by_name_or_image(
    synthetic_dataset: Path, tmp_path: Path
) -> None:
    inbox = tmp_path / "in"
    inbox.mkdir()
    watch, told, records = bare(inbox)
    first, other = sorted(list_images(synthetic_dataset / "test"))[:2]
    arrive(first, inbox, NAMES[0])
    got = taken(watch)
    assert got is not None and got[1].sha256 is not None
    records[got[1].sha256] = got[1].path  # as its record keeps it
    watch.finish(got[1], saved=True)
    arrive(other, inbox, NAMES[0])  # the same name, another image
    arrive(first, inbox, NAMES[1])  # the same image, another name
    assert taken(watch) is None and [e.code for e in told] == ["AOI-INSP-021"] * 2
    assert any(NAMES[0] in e.what for e in told if "same image" in e.what)
    assert len(list((inbox / FAILED).iterdir())) == 2 and [p.name for p in (inbox / DONE).iterdir()] == [NAMES[0]]


def test_req_insp_020_a_board_not_saved_goes_back_and_one_saved_before_a_stop_goes_to_done(
    synthetic_dataset: Path, tmp_path: Path
) -> None:
    inbox = tmp_path / "in"
    inbox.mkdir()
    watch, told, records = bare(inbox)
    arrive(next(iter(list_images(synthetic_dataset / "test"))), inbox, NAMES[0])
    got = taken(watch)
    assert got is not None and (inbox / WORKING / NAMES[0]).is_file()
    watch.finish(got[1], saved=False)
    assert (inbox / NAMES[0]).is_file() and not (inbox / DONE / NAMES[0]).exists()
    got = taken(watch)
    assert got is not None and got[1].sha256 is not None
    records[got[1].sha256] = got[1].path  # its record saved; the station stops before the file moves
    again, told2, _ = bare(inbox)
    again.inspected = records.get
    assert taken(again) is None and (inbox / DONE / NAMES[0]).is_file()  # put back, then known: done, not repeated
    assert not any((inbox / WORKING).iterdir()) and not told and not told2


def test_req_insp_020_a_folder_gone_is_alarmed_once(tmp_path: Path) -> None:
    inbox = tmp_path / "share"
    inbox.mkdir()
    watch, told, _ = bare(inbox)
    shutil.rmtree(inbox)  # the share went
    assert watch.grab(BOARD) is None and watch.grab(BOARD) is None and [e.code for e in told] == ["AOI-INSP-023"]
    inbox.mkdir()
    (inbox / WORKING).mkdir()
    assert watch.grab(BOARD) is None and watch.lost is False
    with pytest.raises(FileNotFoundError):  # its folders are made in it; the input folder itself never is
        bare(tmp_path / "gone")
    assert not (tmp_path / "gone").exists()


def test_req_insp_020_the_context_never_makes_the_folder_and_its_self_check_names_both(
    ctx: AppContext, tmp_path: Path
) -> None:
    ctx.settings.input_folder = str(tmp_path / "gone")
    with pytest.raises(AoiError, match="AOI-INSP-023"):
        ctx.folder_watch()
    assert not (tmp_path / "gone").exists()
    ctx.settings.output_folder = str(tmp_path / "out gone")
    assert ctx.self_check()["line_folders"] == ["input_folder", "output_folder"]  # the start-up self-check
    assert "AOI-SET-025" in {a["code"] for a in ctx.alarms()}
    ctx.settings.input_folder = ""
    assert ctx.folder_watch() is None
    Settings.check("input_folder", "")
    Settings.check("input_folder", str(tmp_path))
    with pytest.raises(AoiError, match="AOI-SET-008"):
        Settings.check("input_folder", "in")
    assert Settings().input_folder == ""


def test_req_insp_020_the_contract_names_the_board() -> None:
    board = parse("TBOX_A1_R3_0001_top_20261106T103000Z.PNG")  # a board model's own "_" stays in it
    assert (board.board_model, board.revision, board.serial, board.view) == ("TBOX_A1", "R3", "0001", "Top")
    assert board.captured == "2026-11-06T10:30:00+00:00"
    assert (
        board_id("C:/line/done/TBOX-A1_R3_0001_Top_20261106T103000Z.png") == "0001" and board_id("x/A_1.png") == "A_1"
    )
    for name in ("TBOX_R3_Top_20261106T103000Z.png", "TBOX_R3_1_Top_20261106T1030Z.png", "TBOX_R3_1_Top_x.bmp"):
        with pytest.raises(AoiError, match="AOI-INSP-020"):
            parse(name)
