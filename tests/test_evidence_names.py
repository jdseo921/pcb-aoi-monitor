"""#245 (stage S25): a record's evidence files and a sample's file are named after its UUID, from a stem cut to
STEM_CHARS characters, so a board with another's file name never takes its evidence and a long file name is still
saved; a path the system still refuses as too long has its own code (REQ-INSP-012, REQ-INSP-008, REQ-TRN-001,
REQ-LOG-002, REQ-SET-019)."""

from __future__ import annotations

import errno
import hashlib
import os
import shutil
import uuid
from pathlib import Path
from unittest import mock

import pytest
from pytestqt.qtbot import QtBot

from aoi.config import Settings
from aoi.core import services
from aoi.core.imaging import list_images
from aoi.core.services import AppContext
from aoi.data import atomic
from aoi.errors import CODES, AoiError
from tests.test_req_done_in_v01 import BOARD, _window

EVIDENCE = ("overlay_path", "diff_map_path", "ai_map_path")


@pytest.fixture
def same_six_hex(monkeypatch: pytest.MonkeyPatch) -> None:
    """Every uuid4() starts 3ce496, as two draws whose first 6 hex digits collide do (the re-test's set-up)."""
    real = uuid.uuid4
    monkeypatch.setattr(uuid, "uuid4", lambda: uuid.UUID(hex="3ce496" + real().hex[6:]))


def _sha(path: str) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _two_tops(synthetic_dataset: Path, tmp_path: Path, split: str = "test/ng") -> tuple[Path, Path]:
    """Two different boards, each saved as top.png in a folder of its own serial number."""
    images = list_images(synthetic_dataset / split)
    a, b = tmp_path / "in" / "SN0001" / "top.png", tmp_path / "in" / "SN0002" / "top.png"
    for src, dst in ((images[0], a), (images[-1], b)):
        dst.parent.mkdir(parents=True)
        shutil.copy(src, dst)
    return a, b


def test_req_insp_012_two_boards_with_one_file_name_keep_their_own_evidence(
    trained_ctx: AppContext, synthetic_dataset: Path, tmp_path: Path, same_six_hex: None
) -> None:
    """Two NG boards saved as SN0001/top.png and SN0002/top.png on one day each name their own overlay, difference map
    and AI map, named after the record's UUID, and the first record's files keep their bytes. Before, both records named
    results/<day>/top_3ce496_NG.png and its maps, and the second save replaced the first board's evidence."""
    a, b = _two_tops(synthetic_dataset, tmp_path)
    trained_ctx.inspect_file(BOARD, str(a))
    (first,) = trained_ctx.inspections(board_model=BOARD)
    before = [_sha(first[k]) for k in EVIDENCE]
    trained_ctx.inspect_file(BOARD, str(b))
    rows = {r["id"]: r for r in trained_ctx.inspections(board_model=BOARD)}
    second = rows[max(rows)]
    assert (first["result"], second["result"]) == ("NG", "NG")
    assert [first[k] != second[k] for k in EVIDENCE] == [True, True, True], "both records name the same files"
    assert [_sha(rows[first["id"]][k]) for k in EVIDENCE] == before, "record 1 evidence overwritten"
    assert Path(first["overlay_path"]).name == f"top_{first['uuid']}_NG.png"


def test_req_insp_012_a_save_never_replaces_another_records_file(
    trained_ctx: AppContext, ng_board: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Should two records ever draw one UUID, the second save is refused before it writes a file (the Inspection page
    shows AOI-INSP-008) and the first record's files keep their bytes. Before, the second save replaced them."""
    monkeypatch.setattr(services, "new_uuid", lambda: "3ce49600-0000-4000-8000-000000000000")
    trained_ctx.inspect_file(BOARD, str(ng_board))
    (first,) = trained_ctx.inspections(board_model=BOARD)
    before = {k: _sha(first[k]) for k in EVIDENCE}
    with pytest.raises(FileExistsError):
        trained_ctx.inspect_file(BOARD, str(ng_board))
    assert [r["id"] for r in trained_ctx.inspections(board_model=BOARD)] == [first["id"]]
    assert {k: _sha(first[k]) for k in EVIDENCE} == before


def test_req_trn_001_two_samples_with_one_file_name_keep_their_own_bytes(
    ctx: AppContext, synthetic_dataset: Path, tmp_path: Path, same_six_hex: None
) -> None:
    """Samples imported from SN0001/top.png and SN0002/top.png, in two imports, each name a file of their own, named
    after the sample's UUID, with their own source's bytes, and the first, the Golden board, stays the first board.
    Before, both rows named images/TINY/OK/top_3ce496.png, which held the second board's bytes."""
    a, b = _two_tops(synthetic_dataset, tmp_path, "train/ok")
    ctx.import_samples(BOARD, [str(a)], "OK")
    ctx.import_samples(BOARD, [str(b)], "OK")
    rows = ctx.samples(BOARD)
    assert [Path(r["path"]).read_bytes() for r in rows] == [a.read_bytes(), b.read_bytes()]
    assert Path(rows[0]["path"]).name == f"top_{rows[0]['uuid']}.png"
    assert Path(str(ctx.db.reference(BOARD))).read_bytes() == a.read_bytes()


def test_req_log_002_overlays_of_two_days_with_one_file_name_export_as_two_files(
    trained_ctx: AppContext,
    synthetic_dataset: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    same_six_hex: None,
) -> None:
    """Two NG boards named top.png, saved on two days, export as two overlay files with their own bytes. Before, both
    overlays were named top_3ce496_NG.png (in two date folders), so the export folder kept one and counted two."""
    a, b = _two_tops(synthetic_dataset, tmp_path)
    for day, board in (("2026-10-01", a), ("2026-10-02", b)):
        monkeypatch.setattr(services, "local_date", lambda day=day: day)
        trained_ctx.inspect_file(BOARD, str(board))
    rows = trained_ctx.inspections(board_model=BOARD)
    out = tmp_path / "export"
    trained_ctx.set_user("admin")  # only an Admin exports (Q58, #151)
    assert trained_ctx.export_overlays(rows, out) == 2
    assert sorted(_sha(str(p)) for p in out.iterdir()) == sorted(_sha(r["overlay_path"]) for r in rows)


@pytest.mark.parametrize("n", [225, 240])
def test_req_insp_008_a_board_with_a_long_file_name_is_saved_with_its_evidence(
    trained_ctx: AppContext, ng_board: Path, tmp_path: Path, n: int
) -> None:
    """A board whose file name has a stem of 225 or 240 characters is saved: one record, its three files named after
    the stem's first STEM_CHARS characters, and no other file in results/<day>/; the record keeps the whole file name.
    Before: OSError [Errno 36] File name too long, no record, and at 225 an overlay that no record names."""
    board = tmp_path / ("b" * n + ".png")
    shutil.copy(ng_board, board)
    trained_ctx.inspect_file(BOARD, str(board))
    (row,) = trained_ctx.inspections(board_model=BOARD)
    files = [Path(row[k]) for k in EVIDENCE]
    assert sorted(files[0].parent.iterdir()) == sorted(files)
    assert files[0].name == f"{'b' * services.STEM_CHARS}_{row['uuid']}_NG.png"
    assert Path(row["image_path"]).name == board.name


def test_req_trn_001_a_sample_with_a_long_file_name_is_imported(
    ctx: AppContext, ng_board: Path, tmp_path: Path
) -> None:
    """A sample whose file name has a 240-character stem is imported under its stem's first STEM_CHARS characters and
    its UUID. Before: AOI-TRN-008, the copy refused with [Errno 36] File name too long."""
    board = tmp_path / ("b" * 240 + ".png")
    shutil.copy(ng_board, board)
    assert ctx.import_samples(BOARD, [str(board)], "OK") == 1
    (row,) = ctx.samples(BOARD)
    assert Path(row["path"]).name == f"{'b' * services.STEM_CHARS}_{row['uuid']}.png"
    assert Path(row["path"]).read_bytes() == board.read_bytes()


def test_req_insp_008_a_run_saves_a_board_with_a_long_file_name(
    qtbot: QtBot, trained_ctx: AppContext, ng_board: Path, synthetic_dataset: Path, tmp_path: Path,
    dialogs: list[tuple[str, str]],
) -> None:  # fmt: skip
    """An Operator runs [an NG board with a 240-character stem, an OK board]: both are saved and no dialog shows.
    Before: "AOI-INSP-008 Result not saved ... Check the free disk space", the run stopped and nothing was saved."""
    board = tmp_path / ("b" * 240 + ".png")
    shutil.copy(ng_board, board)
    ok = list_images(synthetic_dataset / "test" / "ok")[0]
    win = _window(qtbot, trained_ctx, "Operator")
    page = win.pages["Inspection"]
    win.navigate("Inspection")
    qtbot.waitUntil(trained_ctx.jobs.idle, timeout=10000)
    page._set_queue([board, ok])
    page.start_run()
    qtbot.waitUntil(lambda: not page.running and page.worker is None, timeout=60000)
    assert dialogs == []
    saved = sorted(Path(r["image_path"]).name for r in trained_ctx.inspections(board_model=BOARD))
    assert saved == sorted([board.name, ok.name])


def _too_long(path: str | Path, data: bytes) -> None:
    raise OSError(errno.ENAMETOOLONG, os.strerror(errno.ENAMETOOLONG), str(path))


def test_req_insp_008_a_path_the_system_refuses_as_too_long_has_its_own_code(
    qtbot: QtBot,
    trained_ctx: AppContext,
    synthetic_dataset: Path,
    monkeypatch: pytest.MonkeyPatch,
    dialogs: list[tuple[str, str]],
) -> None:
    """A save refused with ENAMETOOLONG (the workspace's path too long for the system): the dialog carries AOI-INSP-014,
    which names the workspace folder and copying its contents to a shorter path as the step, not AOI-INSP-008's disk
    space; the run stops before the next board, the verdict stays and the alarm list shows the code. Any other AoiError
    from the save, such as AOI-INSP-002, stays AOI-INSP-008. Before: "AOI-INSP-008 Result not saved" with "Check the
    free disk space and that the workspace folder can be written"."""
    boards = list_images(synthetic_dataset / "test" / "ng")[:2]
    win = _window(qtbot, trained_ctx, "Operator")
    page = win.pages["Inspection"]
    win.navigate("Inspection")
    qtbot.waitUntil(trained_ctx.jobs.idle, timeout=10000)
    monkeypatch.setattr(atomic, "write_bytes", _too_long)
    page._set_queue(boards)
    page.start_run()
    qtbot.waitUntil(lambda: len(dialogs) == 1, timeout=30000)
    title, text = dialogs[-1]
    assert title == "AOI-INSP-014 Result not saved: path too long" and boards[0].name in text
    assert f"copy everything in the folder {trained_ctx.settings.root} into that folder" in text, text
    assert "disk space" not in text
    assert not page.running and page.worker is None and page.queue_pos == 0, "the run stopped before the next board"
    assert page.last is not None and "AOI-INSP-014" in page.alarms.item(0).text()
    assert trained_ctx.inspections(board_model=BOARD) == []
    monkeypatch.setattr(services, "save_image", mock.Mock(side_effect=AoiError("AOI-INSP-002", path="x.png")))
    page.next_board()  # an encoder refusal's step (the file name's extension) names nothing the user chose
    qtbot.waitUntil(lambda: len(dialogs) == 2, timeout=30000)
    assert dialogs[-1][0] == "AOI-INSP-008 Result not saved"


def test_req_insp_008_the_headless_save_names_a_path_too_long_and_nothing_else(
    trained_ctx: AppContext, ng_board: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`inspect_file` raises AOI-INSP-014 for ENAMETOOLONG and, on Windows, for a file not found at a path of 260
    UTF-16 units or more (how such a path fails there with long paths off; 29 emoji are 58), each of its names no
    longer than the 255 units Windows takes in one; a file not found at a shorter path, or on Linux, stays the OSError
    it is (the Inspection page shows it as AOI-INSP-008). Before, each was a bare OSError, ENAMETOOLONG included."""
    monkeypatch.setattr(atomic, "write_bytes", _too_long)
    with pytest.raises(AoiError) as caught:
        trained_ctx.inspect_file(BOARD, str(ng_board))
    assert caught.value.code == "AOI-INSP-014" and isinstance(caught.value.__cause__, OSError)
    assert caught.value.params == {"file": ng_board.name, "workspace": str(trained_ctx.settings.root)}
    monkeypatch.setattr(services, "WINDOWS", True)
    at_260, emoji_260, at_259 = (
        "x" * 200 + "/" + "x" * 59,
        "x" * 201 + "/" + "\U0001f600" * 29,
        "x" * 200 + "/" + "x" * 58,
    )
    for name, code in ((at_260, "AOI-INSP-014"), (emoji_260, "AOI-INSP-014"), (at_259, None)):
        gone = FileNotFoundError(errno.ENOENT, os.strerror(errno.ENOENT), name)
        monkeypatch.setattr(atomic, "write_bytes", mock.Mock(side_effect=gone))
        with pytest.raises((AoiError, FileNotFoundError)) as refused:
            trained_ctx.inspect_file(BOARD, str(ng_board))
        assert getattr(refused.value, "code", None) == code
    monkeypatch.setattr(services, "WINDOWS", False)
    with pytest.raises(FileNotFoundError):
        trained_ctx.inspect_file(BOARD, str(ng_board))  # the same 259 characters on Linux
    assert trained_ctx.inspections(board_model=BOARD) == []


def test_req_trn_001_a_copy_the_system_refuses_as_too_long_has_its_own_code(
    ctx: AppContext, ng_board: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An import whose copy the system refuses as too long stops with AOI-TRN-011: ENAMETOOLONG, or on Windows a file
    not found at a path of 260 characters or more (no name in it over 255). It names the picked file and the workspace
    folder, gives copying the workspace as the step, not AOI-TRN-008's free space, and imports nothing. A copy not found
    at 259 characters stays AOI-TRN-008, and a picked file whose own path is refused is that file's, AOI-INSP-001 (S31).
    Before: AOI-TRN-008 for each."""
    copy = str(ctx.settings.images_dir / BOARD / "OK" / ".copy.tmp")
    cases = [
        (False, OSError(errno.ENAMETOOLONG, os.strerror(errno.ENAMETOOLONG), copy), "AOI-TRN-011"),
        (True, FileNotFoundError(errno.ENOENT, os.strerror(errno.ENOENT), "x" * 200 + "/" + "x" * 59), "AOI-TRN-011"),
        (True, FileNotFoundError(errno.ENOENT, os.strerror(errno.ENOENT), "x" * 200 + "/" + "x" * 58), "AOI-TRN-008"),
        (False, OSError(errno.ENAMETOOLONG, os.strerror(errno.ENAMETOOLONG), str(ng_board)), "AOI-INSP-001"),
    ]
    for windows, refusal, code in cases:

        def refused(src: str | Path, dst: str | Path, refusal: OSError = refusal) -> None:
            raise refusal

        monkeypatch.setattr(atomic, "copy_file", refused)
        monkeypatch.setattr(services, "WINDOWS", windows)
        with pytest.raises(AoiError) as caught:
            ctx.import_samples(BOARD, [str(ng_board)], "OK")
        assert (caught.value.code, caught.value.__cause__) == (code, refusal)
        if code == "AOI-TRN-011":
            assert caught.value.params == {"path": str(ng_board), "workspace": str(ctx.settings.root), "count": 1}
            assert f"copy everything in the folder {ctx.settings.root} into that folder" in caught.value.message
            assert "free space" not in caught.value.message
    assert ctx.samples(BOARD) == []


@pytest.mark.parametrize(
    ("refused", "kept", "title", "says"),
    [
        ("ok_2.png", 2, "AOI-TRN-010 Import stopped by an error", "image 3 of 5"),
        ("ok_0.png", 0, "AOI-TRN-011 Images not imported: path too long", "None of the 5 image(s) picked"),
    ],
    ids=["third", "first"],
)
def test_req_trn_001_a_folder_import_names_a_copy_refused_as_too_long(
    qtbot: QtBot, ctx: AppContext, synthetic_dataset: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    dialogs: list[tuple[str, str]], refused: str, kept: int, title: str, says: str,
) -> None:  # fmt: skip
    """Import Folder… imports one file per call: when the third file's copy is refused as too long, the two before it
    stay, and AOI-TRN-010 says so and names AOI-TRN-011, not AOI-TRN-009's free space. When the first is, none went in,
    and AOI-TRN-011 itself names all five images and its step. Before, that read "None of the 1 image(s) picked"."""
    for i, p in enumerate(list_images(synthetic_dataset / "train" / "ok")[:5]):
        (tmp_path / "fold" / "ok").mkdir(parents=True, exist_ok=True)
        shutil.copy(p, tmp_path / "fold" / "ok" / f"ok_{i}.png")
    copy = atomic.copy_file

    def copy_or_refuse(src: str | Path, dst: str | Path) -> None:
        if Path(src).name == refused:
            raise OSError(errno.ENAMETOOLONG, os.strerror(errno.ENAMETOOLONG), str(dst))
        copy(src, dst)

    monkeypatch.setattr(atomic, "copy_file", copy_or_refuse)
    ctx.ensure_board_model(BOARD)
    page = _window(qtbot, ctx, "Engineer").pages["Training"]
    page.import_from(str(tmp_path / "fold"))
    page.sheet.btn_import.click()
    qtbot.waitUntil(lambda: page._bg is None, timeout=30000)
    assert len(ctx.samples(BOARD)) == kept
    [(shown, text)] = dialogs
    assert shown == title and says in text and "free space" not in text, (shown, text)
    assert "AOI-TRN-011 Images not imported: path too long" in f"{shown} {text}"


def test_req_set_001_the_step_for_a_path_too_long_keeps_the_stations_records(
    synthetic_dataset: Path, ng_board: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The step of AOI-INSP-014 and AOI-TRN-011, as their texts say, followed with the default workspace (AOI_WORKSPACE,
    with settings.json) open: the next start opens the copy with every sample and record. A move, the old step, took
    settings.json along."""
    monkeypatch.setenv("AOI_WORKSPACE", str(tmp_path / ("long_" + "w" * 40) / "AOI_Workspace"))
    ctx = AppContext(Settings.load())
    ctx.set_user("admin")
    ctx.import_samples(BOARD, [str(p) for p in list_images(synthetic_dataset / "train" / "ok")[:3]], "OK")
    ctx.inspect_file(BOARD, str(ng_board))
    old, short = ctx.settings.root, tmp_path / "AOI"
    ctx.save_settings({"workspace": str(short)})  # an Admin saves a shorter path on Settings
    kept = [[r["uuid"] for r in rows] for rows in (ctx.samples(BOARD), ctx.inspections(board_model=BOARD))]
    ctx.close()
    for code in ("AOI-INSP-014", "AOI-TRN-011"):  # a copy, not a move
        assert "copy everything in the folder {workspace} into that folder" in CODES[code].action, code
    shutil.copytree(old, short)  # with the app closed, everything in the folder is copied into that folder
    again = AppContext(Settings.load())  # the next start
    samples, records = again.samples(BOARD), again.inspections(board_model=BOARD)
    assert again.settings.root == short and [[r["uuid"] for r in rows] for rows in (samples, records)] == kept
    files = [r["path"] for r in samples] + [r[k] for r in records for k in ("overlay_path", "diff_map_path")]
    assert all(Path(f).is_relative_to(short) and Path(f).is_file() for f in files), files
