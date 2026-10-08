"""REQ-INSP-012 (S25c): the difference and AI score maps of every result are stored as PNG beside the overlay and read
back with it; OK maps go after `map_retention_days_ok` days, NG and WARN maps stay; the save runs on the pool thread."""

from __future__ import annotations

import os
import shutil
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path

import numpy as np
import pytest
from pytestqt.qtbot import QtBot

from aoi.config import Settings
from aoi.core import maps
from aoi.core.imaging import list_images, save_image
from aoi.core.services import AppContext
from tests.conftest import TrainedModel
from tests.test_no_freeze import gap_meter
from tests.test_req_done_in_v01 import BOARD, _window


def test_maps_encode_the_difference_exactly_and_the_ai_score_to_a_thousandth() -> None:
    """8 bits hold the difference map (whole values 0-255) exactly; the AI map is kept in 0.001 sigma steps."""
    diff = np.array([[0.0, 1.0, 254.0, 255.0]], dtype=np.float32)
    assert maps.encode_diff(diff).dtype == np.uint8 and np.array_equal(maps.encode_diff(diff), diff)
    amap = np.array([[0.0, 0.0004, 1.2346, 70.0, np.nan]], dtype=np.float32)  # NaN, which no model makes, stores as 0
    with np.errstate(invalid="raise"):  # and without NumPy's cast warning for the NaN
        back = maps.decode_ai(maps.encode_ai(amap))
    assert maps.encode_ai(amap).dtype == np.uint16 and back.dtype == np.float32
    assert back[0].tolist() == pytest.approx([0.0, 0.0, 1.235, 65.535, 0.0], abs=1e-5)  # float32 holds 65.535004


def test_req_insp_012_maps_are_stored_beside_the_overlay_and_read_back_with_the_result(
    trained_ctx: AppContext, ng_board: Path
) -> None:
    """A saved result names its two map files, stored relative to the workspace beside the overlay; read back with
    `with_maps`, the difference map equals the live one exactly and the AI map to its stored precision."""
    ctx = trained_ctx
    ctx.inspect_file(BOARD, str(ng_board))
    (row,) = ctx.inspections(board_model=BOARD)
    iid = row["id"]
    overlay = Path(row["overlay_path"])
    assert row["diff_map_path"] == str(overlay.with_name(overlay.stem + "_diff.png"))
    assert row["ai_map_path"] == str(overlay.with_name(overlay.stem + "_ai.png"))
    assert Path(row["diff_map_path"]).is_file() and Path(row["ai_map_path"]).is_file()
    raw = ctx.db.query("SELECT diff_map_path, ai_map_path FROM inspections WHERE id=?", (iid,))[0]
    assert all(not Path(p).is_absolute() for p in raw.values()), raw
    live = ctx.inspector(BOARD).inspect(ctx.load_image(ng_board))  # the engine as the save saw it
    assert live.compare is not None and live.compare.diff_map is not None and live.anomaly_map is not None
    stored = ctx.inspection_result(iid, with_maps=True)
    assert stored is not None and stored.compare is not None and stored.compare.diff_map is not None
    assert stored.compare.diff_map.dtype == np.float32 and (stored.compare.diff_map == live.compare.diff_map).all()
    assert stored.anomaly_map is not None and stored.anomaly_map.shape == live.anomaly_map.shape
    step, rounding = 0.5 / maps.AI_SCALE, float(live.anomaly_map.max()) * np.finfo(np.float32).eps
    assert float(np.abs(stored.anomaly_map - live.anomaly_map).max()) <= step + rounding
    plain = ctx.inspection_result(iid)  # without with_maps: no maps, as before
    assert plain and plain.compare and plain.anomaly_map is None and plain.compare.diff_map is None


def _backdate(ctx: AppContext, days: int, *ids: int) -> None:
    """Move records `days` back (and a second, so a sweep with `days` as its cutoff takes a record this old)."""
    then = (datetime.now(UTC) - timedelta(days=days, seconds=1)).isoformat(timespec="seconds")
    ctx.db.execute(f"UPDATE inspections SET time=? WHERE id IN ({','.join('?' * len(ids))})", (then, *ids))


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
