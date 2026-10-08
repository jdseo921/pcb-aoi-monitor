"""REQ-INSP-012 (S25c): the difference and AI score maps of every result are stored as PNG beside the overlay and read
back with it; OK maps go after `map_retention_days_ok` days, NG and WARN maps stay; the save runs on the pool thread."""

from __future__ import annotations

import os
import shutil
import struct
import threading
import time
import zlib
from datetime import UTC, datetime, timedelta
from pathlib import Path

import cv2
import numpy as np
import pytest
from pytestqt.qtbot import QtBot

from aoi.config import Settings
from aoi.core import maps
from aoi.core.compare import CompareResult
from aoi.core.imaging import list_images, save_image
from aoi.core.inspector import InspectionResult
from aoi.core.services import AppContext
from aoi.errors import AoiError
from tests.conftest import TrainedModel
from tests.test_no_freeze import gap_meter
from tests.test_req_done_in_v01 import BOARD, _window


def test_maps_encode_the_difference_exactly_and_the_ai_score_within_a_step() -> None:
    """8 bits hold the difference map (whole values 0-255) exactly; the AI map is kept in 0.001 sigma steps up to
    32.767 sigma and in steps of 1/8192 of the value above (format 2, since S28a)."""
    diff = np.array([[0.0, 1.0, 254.0, 255.0]], dtype=np.float32)
    assert maps.encode_diff(diff).dtype == np.uint8 and np.array_equal(maps.encode_diff(diff), diff)
    amap = np.array([[0.0, 0.0004, 1.2346, 70.0, 800.0, np.inf, np.nan, -1.0, -np.inf]], np.float32)  # no model
    with np.errstate(all="raise"):  # makes the last four, stored without NumPy's warnings as the top code and as 0
        back = maps.decode_ai(maps.encode_ai(amap))
    assert maps.encode_ai(amap).dtype == np.uint16 and back.dtype == np.float32 and back[0, 5] == maps.AI_MAX
    assert back[0, :3].tolist() == pytest.approx([0.0, 0.0, 1.235], abs=1e-6) and back[0, 6:].tolist() == [0.0] * 3
    assert back[0, 3:5].tolist() == pytest.approx([70.0, 800.0], rel=0.5 / maps.AI_LOG_STEPS)


def test_req_insp_012_maps_are_stored_beside_the_overlay_and_read_back_with_the_result(
    trained_ctx: AppContext, ng_board: Path
) -> None:
    """A saved result names its two map files, stored relative to the workspace beside the overlay; read back with
    `with_maps`, the difference map equals the live one exactly and the AI map within one step, each pixel on the side
    of the AI model's pixel threshold it is on live (S28a)."""
    ctx = trained_ctx
    ctx.inspect_file(BOARD, str(ng_board))
    (row,) = ctx.inspections(board_model=BOARD)
    iid = row["id"]
    overlay = Path(row["overlay_path"])
    assert row["diff_map_path"] == str(overlay.with_name(overlay.stem + "_diff.png"))
    assert row["ai_map_path"] == str(overlay.with_name(overlay.stem + maps.AI_FILE))
    assert Path(row["diff_map_path"]).is_file() and Path(row["ai_map_path"]).is_file()
    raw = ctx.db.query("SELECT diff_map_path, ai_map_path FROM inspections WHERE id=?", (iid,))[0]
    assert all(not Path(p).is_absolute() for p in raw.values()), raw
    live = ctx.inspector(BOARD).inspect(ctx.load_image(ng_board))  # the engine as the save saw it
    assert live.compare is not None and live.compare.diff_map is not None and live.anomaly_map is not None
    stored = ctx.inspection_result(iid, with_maps=True)
    assert stored is not None and stored.compare is not None and stored.compare.diff_map is not None
    assert stored.compare.diff_map.dtype == np.float32 and (stored.compare.diff_map == live.compare.diff_map).all()
    assert stored.anomaly_map is not None and stored.anomaly_map.shape == live.anomaly_map.shape
    step = np.maximum(1 / maps.AI_SCALE, live.anomaly_map / maps.AI_LOG_STEPS) * 1.001  # one step at each value
    rounding = float(live.anomaly_map.max()) * np.finfo(np.float32).eps
    assert float((np.abs(stored.anomaly_map - live.anomaly_map) - step).max()) < rounding
    model = ctx.inspector(BOARD).model
    assert model is not None
    assert np.array_equal(stored.anomaly_map >= model.pixel_threshold, live.anomaly_map >= model.pixel_threshold)
    plain = ctx.inspection_result(iid)  # without with_maps: no maps, as before
    assert plain and plain.compare and plain.anomaly_map is None and plain.compare.diff_map is None


def test_req_insp_012_a_map_that_cannot_be_read_says_which_and_why(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A map whose file is gone reads as None (the sweep or a hand deleted it, maybe while it was being read); one that
    is there but damaged (no PNG, or a header claiming 10^10 pixels, which OpenCV refuses with an exception), or held by
    another program, raises AOI-CMP-003 naming the file and why (S28a reviews B, B2, and C, N3)."""
    path = tmp_path / ("board" + maps.AI_FILE)
    assert maps.read_map(path) is None
    huge = bytearray(cv2.imencode(".png", np.zeros((2, 2), np.uint16))[1].tobytes())
    huge[16:24] = struct.pack(">II", 100000, 100000)  # the IHDR's width and height, with a valid CRC after them
    huge[29:33] = struct.pack(">I", zlib.crc32(bytes(huge[12:29])))
    for damaged in (b"not a PNG", bytes(huge)):
        path.write_bytes(damaged)
        with pytest.raises(AoiError, match="board_ai2.png could not be read: the file is damaged") as bad:
            maps.load_maps(InspectionResult("OK", 0.0), None, str(path))
    save_image(path, np.zeros((2, 2), np.uint16))

    def held(self: Path) -> bytes:
        raise PermissionError(13, "Permission denied", str(self))

    monkeypatch.setattr(Path, "read_bytes", held)
    with pytest.raises(AoiError, match="board_ai2.png could not be read: Permission denied") as locked:
        maps.load_maps(InspectionResult("OK", 0.0), None, str(path))
    assert bad.value.code == locked.value.code == "AOI-CMP-003" and path.name in str(locked.value.detail)


def _backdate(ctx: AppContext, days: int, *ids: int) -> None:
    """Move records `days` back (and a second, so a sweep with `days` as its cutoff takes a record this old)."""
    then = (datetime.now(UTC) - timedelta(days=days, seconds=1)).isoformat(timespec="seconds")
    ctx.db.execute(f"UPDATE inspections SET time=? WHERE id IN ({','.join('?' * len(ids))})", (then, *ids))


def test_req_insp_012_a_map_that_is_not_the_map_written_reads_as_damaged(tmp_path: Path) -> None:
    """A map that decodes but is not the map written cannot be judged as it, so it raises AOI-CMP-003 naming it as
    damaged (#249): one in colour, a 16-bit difference map, an 8-bit AI map, two maps of different sizes when no board
    picture gives the size (the difference map is named), and maps not the size of the board picture, read from its
    header. Before, each was put on the result as it decoded."""
    diff, ai, picture, junk = (tmp_path / f"b{end}" for end in ("_diff.png", maps.AI_FILE, ".png", "_junk.png"))

    def loaded(d: np.ndarray, a: np.ndarray, *shape: tuple[int, int] | None) -> str:
        save_image(diff, d)
        save_image(ai, a)
        res = InspectionResult("NG", 0.0, compare=CompareResult())
        try:
            maps.load_maps(res, str(diff), str(ai), *shape)
        except AoiError as e:
            assert e.code == "AOI-CMP-003" and str(e.what).endswith(" could not be read: the file is damaged."), e
            return next(p.name for p in (diff, ai) if p.name in str(e.what))
        assert res.compare is not None and res.compare.diff_map is not None and res.anomaly_map is not None
        return "loaded"

    u8, u16, small = np.zeros((4, 6), np.uint8), np.zeros((4, 6), np.uint16), np.zeros((2, 3), np.uint16)
    got = {
        "intact": loaded(u8, u16),
        "colour AI map": loaded(u8, cv2.cvtColor(u16, cv2.COLOR_GRAY2BGR)),
        "16-bit difference map": loaded(u16, u16),
        "8-bit AI map": loaded(u8, u8),
        "sizes differ": loaded(u8, small),
    }
    named = {"colour AI map": ai.name, "16-bit difference map": diff.name, "8-bit AI map": ai.name}
    assert got == {"intact": "loaded", **named, "sizes differ": diff.name}
    save_image(picture, np.zeros((4, 6, 3), np.uint8))
    junk.write_bytes(b"not a PNG")
    shape = maps.picture_shape(picture)
    assert shape == (4, 6) and [maps.picture_shape(p) for p in (None, tmp_path / "gone.png", junk)] == [None] * 3
    assert loaded(u8, u16, shape) == "loaded" and loaded(small.astype(np.uint8), small, shape) == ai.name


def test_req_cmp_005_the_difference_map_is_worked_on_while_the_ai_map_decodes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`load_maps` hands the difference map, as float32, to `on_diff` while the AI map is still decoding on its own
    thread, once it passes its checks against the board picture's size, so judging a stored result again finds the
    difference regions meanwhile (#249); without that size, once both maps pass. A difference map that fails is never
    handed over, and a map that fails raises as without `on_diff`, the result getting neither map."""
    diff, ai = tmp_path / "b_diff.png", tmp_path / ("b" + maps.AI_FILE)
    read_ai, handed, order = maps._read_ai, threading.Event(), list[object]()

    def held(path: str, shape: tuple[int, int] | None) -> tuple[np.ndarray | None, np.ndarray | None]:
        handed.wait(10)  # the AI map's thread decodes only once the difference map was handed over, or after 10 s
        order.append("AI map decoded" if handed.is_set() else "AI map decoded first")
        return read_ai(path, shape)

    def on_diff(d: np.ndarray) -> None:
        order.append(("difference map", d))
        handed.set()

    def load(d: np.ndarray, a: np.ndarray, shape: tuple[int, int] | None) -> InspectionResult:
        save_image(diff, d)
        save_image(ai, a)
        handed.clear()
        order.clear()
        res = InspectionResult("NG", 0.0, compare=CompareResult())
        return maps.load_maps(res, str(diff), str(ai), shape, on_diff=on_diff)

    monkeypatch.setattr(maps, "_read_ai", held)
    res = load(np.full((4, 6), 7, np.uint8), np.full((4, 6), 1235, np.uint16), (4, 6))
    assert res.compare is not None and order == [("difference map", res.compare.diff_map), "AI map decoded"]
    assert res.compare.diff_map.dtype == np.float32 and res.compare.diff_map.tolist() == [[7.0] * 6] * 4
    assert res.anomaly_map is not None and np.allclose(res.anomaly_map, 1.235)

    def late(path: str, shape: tuple[int, int] | None) -> tuple[np.ndarray | None, np.ndarray | None]:
        early = handed.wait(1)  # a hand-over before the AI map is decoded would come within this second
        out = read_ai(path, shape)
        order.append("AI map decoded after a hand-over" if early else "AI map decoded")
        return out

    monkeypatch.setattr(maps, "_read_ai", late)  # without the board picture's size, the difference map waits for it
    res = load(np.full((4, 6), 7, np.uint8), np.zeros((4, 6), np.uint16), None)
    assert res.compare is not None and order == ["AI map decoded", ("difference map", res.compare.diff_map)]
    monkeypatch.setattr(maps, "_read_ai", read_ai)
    for d, a, shape, named in (
        (np.zeros((2, 3), np.uint8), np.zeros((4, 6), np.uint16), (4, 6), diff.name),  # not the board picture's size
        (np.zeros((2, 3), np.uint8), np.zeros((4, 6), np.uint16), None, diff.name),  # without it, not the AI map's
        (np.zeros((4, 6), np.uint8), np.zeros((4, 6), np.uint8), (4, 6), ai.name),  # an 8-bit AI map, the other fine
    ):
        save_image(diff, d)
        save_image(ai, a)
        handed_over: list[np.ndarray] = []
        res = InspectionResult("NG", 0.0, compare=CompareResult())
        with pytest.raises(AoiError, match=f"{named} could not be read: the file is damaged"):
            maps.load_maps(res, str(diff), str(ai), shape, on_diff=handed_over.append)
        assert len(handed_over) == (named == ai.name) and res.compare is not None
        assert res.compare.diff_map is None and res.anomaly_map is None, "neither map"


def test_req_cmp_005_maps_are_written_to_be_read_fast(tmp_path: Path) -> None:
    """`save_maps` writes both maps at zlib level 1 with deflate's default strategy and PNG's Up filter on every row
    (`maps.PNG_SETTINGS`): the pixels saved, which on the 5 MP test board read back in about two thirds of the time
    OpenCV's own settings take, what judging a stored result again waits on (#249). Before, OpenCV's own settings took
    the run-length strategy and the Sub filter."""
    y, x = np.mgrid[0:37, 0:53]  # a gradient: random pixels would come out the same under either strategy
    diff = ((x * 5 + y * 3) % 256).astype(np.float32)
    amap = diff / 255 * 40
    res = InspectionResult("NG", 0.0, anomaly_map=amap, compare=CompareResult(diff_map=diff))
    diff_path, ai_path = maps.save_maps(res, tmp_path / "b", pixel_threshold=None)
    for path, written in ((diff_path, maps.encode_diff(diff)), (ai_path, maps.encode_ai(amap))):
        assert path is not None
        data, at, idat = Path(path).read_bytes(), 8, b""
        while at < len(data):  # the chunks after the signature: length, type, body, CRC
            (n,) = struct.unpack(">I", data[at : at + 4])
            idat += data[at + 8 : at + 8 + n] if data[at + 4 : at + 8] == b"IDAT" else b""
            at += 12 + n
        rows, stride = zlib.decompress(idat), 1 + 53 * written.itemsize  # each row: its filter type, then its pixels
        assert len(rows) == 37 * stride and set(rows[::stride]) == {2}, "the Up filter on every row"
        assert np.array_equal(maps.read_map(path), written)
        level_1 = [cv2.IMWRITE_PNG_COMPRESSION, 1, cv2.IMWRITE_PNG_STRATEGY, cv2.IMWRITE_PNG_STRATEGY_DEFAULT]
        up = [cv2.IMWRITE_PNG_FILTER, cv2.IMWRITE_PNG_FILTER_UP]
        assert data == cv2.imencode(".png", written, level_1 + up)[1].tobytes(), "the level and the strategy too"


def test_req_insp_012_ok_maps_are_swept_after_retention_and_ng_maps_stay(
    tmp_path: Path, tiny_model: TrainedModel, ng_board: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The start-up sweep (and `_sweep_ok_maps`) deletes the map files of OK results older than `map_retention_days_ok`
    days and forgets their paths, audited as the system's `maps.sweep`; NG and WARN maps and every record stay; a result
    whose maps are gone reads back without them; a locked file, or one outside results/, keeps its row's paths."""
    ws = tmp_path / "ws"
    shutil.copytree(tiny_model.ctx.settings.root, ws)
    app = AppContext(Settings(workspace=str(ws), device="cpu", map_retention_days_ok=7))
    doc = app.inspect_file(BOARD, str(ng_board)).to_dict()
    assert doc["verdict"] == "NG"
    ng = app.db.inspections(board_model=BOARD)[0]["id"]
    ids = []
    for verdict in ("OK", "OK", "WARN"):  # records as the engine writes them: map files beside an overlay
        base = app.settings.results_dir / f"{verdict.lower()}_{len(ids)}"
        save_image(base.with_name(base.name + "_diff.png"), np.zeros((4, 4), np.uint8))
        save_image(base.with_name(base.name + "_ai.png"), np.zeros((4, 4), np.uint16))
        rec = {"board_model": BOARD, "result": verdict, "view": "Top", "diff_map_path": f"{base}_diff.png"}
        rec["result_json"] = {**doc, "verdict": verdict}  # a stored result, so the record reads back like a real one
        ids.append(app.db.add_inspection({**rec, "ai_map_path": f"{base}_ai.png"}, [], None))
    old_ok, fresh_ok, old_warn = ids
    _backdate(app, 8, old_ok)
    _backdate(app, 0, fresh_ok)  # written a second ago: within any retention above 0 days
    _backdate(app, 400, old_warn, ng)
    paths = {i: app.db.map_paths(i) for i in (ng, old_ok, fresh_ok, old_warn)}
    assert all(p and Path(p).is_file() for pair in paths.values() for p in pair)
    app.close()
    app = AppContext(Settings(workspace=str(ws), device="cpu", map_retention_days_ok=7))  # the start-up sweep
    assert app.db.map_paths(old_ok) == (None, None) and not any(Path(p).exists() for p in paths[old_ok] if p)
    for i in (ng, fresh_ok, old_warn):
        assert app.db.map_paths(i) == paths[i] and all(Path(p).is_file() for p in paths[i] if p), i
    (entry,) = app.audit_entries(action="maps.sweep")
    assert (entry["user_uuid"], entry["role"], entry["after"]) == (None, None, {"days": 7, "swept": 1, "skipped": 0})
    gone = app.inspection_result(old_ok, with_maps=True)
    assert gone is not None and gone.anomaly_map is None and gone.verdict == "OK"
    assert app._sweep_ok_maps() == 0, "the fresh OK's maps go only when asked to"
    outside = tmp_path / "elsewhere_diff.png"  # a row edited on disk names a file outside results/ (threat model #112)
    save_image(outside, np.zeros((4, 4), np.uint8))
    tampered = app.db.add_inspection({**rec, "result": "OK", "diff_map_path": str(outside)}, [], None)
    _backdate(app, 400, tampered)
    real_unlink, locked = os.unlink, Path(paths[fresh_ok][1]).resolve()

    def unlink(p: str | os.PathLike[str], *a: object, **k: object) -> None:
        if Path(p).resolve() == locked:  # a file another program holds open: WinError 32 on Windows
            raise PermissionError(32, "held open")
        real_unlink(p, *a, **k)

    monkeypatch.setattr(os, "unlink", unlink)
    assert app._sweep_ok_maps(0) == 0 and app.db.map_paths(fresh_ok) == paths[fresh_ok], "kept for the next start"
    monkeypatch.setattr(os, "unlink", real_unlink)
    half = app.inspection_result(fresh_ok, with_maps=True)  # its difference file went before the AI file was refused
    assert half and half.compare and half.compare.diff_map is None and half.anomaly_map is not None
    locked.unlink()  # deleted by hand: the path stays, the map reads as None
    assert (h := app.inspection_result(fresh_ok, with_maps=True)) is not None and h.anomaly_map is None
    assert app._sweep_ok_maps(0) == 1 and outside.is_file(), "the locked row goes now; the outside file never does"
    assert app.db.map_paths(fresh_ok) == (None, None) and app.db.map_paths(old_warn) == paths[old_warn]
    assert {r["id"] for r in app.db.inspections(board_model=BOARD, include_archived=True)} >= {ng, old_ok, fresh_ok}
    app.close()


def test_req_set_021_the_save_runs_on_the_pool_thread(
    qtbot: QtBot, trained_ctx: AppContext, synthetic_dataset: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The overlay, the maps and the row are written in the board's pool job, not in the result slot: a 1.2 s save
    leaves the window's thread free (S25b review S1; REQ-SET-021) and each record is there before the next board."""
    boards = list_images(synthetic_dataset / "test" / "ng")[:2]
    win = _window(qtbot, trained_ctx, "Operator")
    page = win.pages["Inspection"]
    win.navigate("Inspection")
    qtbot.waitUntil(trained_ctx.jobs.idle, timeout=10000)
    real = AppContext.log_result
    monkeypatch.setattr(AppContext, "log_result", lambda *a: (time.sleep(1.2), real(*a))[1])  # a 1.2 s save
    with gap_meter(qtbot) as g:
        page._set_queue(boards)
        page.start_run()
        qtbot.waitUntil(lambda: not page.running and page.worker is None, timeout=60000)
    assert g["longest_s"] < 0.6, g
    assert len(trained_ctx.inspections(board_model=BOARD)) == 2
