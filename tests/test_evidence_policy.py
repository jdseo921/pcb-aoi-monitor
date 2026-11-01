"""The evidence policy (D1, ADR 0024; REQ-INSP-012): NG and WARN boards keep a full-resolution PNG overlay and both
maps; an OK board a JPEG overlay at quality 90 and a preview, its maps until `map_retention_days_ok`. What is judged
never changes (tests/regression), only what is stored; every reader takes whichever file is there."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest
from PySide6.QtWidgets import QMessageBox
from pytestqt.qtbot import QtBot

from aoi.config import Settings
from aoi.core import disk
from aoi.core.imaging import PREVIEW_PX, list_images, load_image, preview_path
from aoi.core.inspector import InspectionResult, Inspector
from aoi.core.maps import picture_shape
from aoi.core.services import AppContext, HistoryFilter
from aoi.errors import AoiError
from aoi.ui.pages.base import row_key
from tests.conftest import listed
from tests.test_req_done_in_v01 import BOARD, _window


def ok_board(ctx: AppContext, insp: Inspector, dataset: Path) -> tuple[str, InspectionResult]:
    judged = ((str(p), insp.inspect(ctx.load_image(str(p)))) for p in list_images(dataset / "test" / "ok"))
    return next((p, r) for p, r in judged if r.verdict == "OK")


def saved(ctx: AppContext, synthetic_dataset: Path, ng_board: Path) -> tuple[dict[str, object], dict[str, object]]:
    insp = ctx.inspector(BOARD)
    ctx.log_result(BOARD, *ok_board(ctx, insp, synthetic_dataset), insp)
    ctx.log_result(BOARD, str(ng_board), insp.inspect(ctx.load_image(str(ng_board))), insp)
    ng, ok = ctx.inspections(board_model=BOARD)  # newest first
    return ok, ng


def test_req_insp_012_an_ok_board_keeps_a_jpeg_and_a_preview_an_ng_board_a_png(
    trained_ctx: AppContext, synthetic_dataset: Path, ng_board: Path
) -> None:
    ok, ng = saved(trained_ctx, synthetic_dataset, ng_board)
    overlay = Path(str(ok["overlay_path"]))
    assert overlay.name.endswith("_OK.jpg") and overlay.read_bytes()[:3] == b"\xff\xd8\xff"
    preview = load_image(str(preview_path(overlay)))
    assert max(preview.shape[:2]) <= PREVIEW_PX and Path(str(ok["diff_map_path"])).is_file()
    assert Path(str(ng["overlay_path"])).name.endswith("_NG.png") and Path(str(ng["ai_map_path"])).is_file()
    assert not preview_path(Path(str(ng["overlay_path"]))).exists()
    # the readers: the picture's size from the JPEG's header, the maps checked against it, Compare's stored result
    board = load_image(str(overlay))
    assert picture_shape(overlay) == board.shape[:2]
    stored = trained_ctx.inspection_result(int(str(ok["id"])), with_maps=True)
    assert stored is not None and stored.verdict == "OK" and stored.anomaly_map is not None
    assert disk.evidence(ok, []) == "jpeg+preview+maps" and disk.evidence(ng, []) == "overlay+maps"


def test_req_insp_012_full_resolution_for_every_board_where_the_factory_asks(
    trained_ctx: AppContext, synthetic_dataset: Path, ng_board: Path
) -> None:
    trained_ctx.settings.ok_evidence = "full"
    ok, _ = saved(trained_ctx, synthetic_dataset, ng_board)
    assert str(ok["overlay_path"]).endswith("_OK.png") and disk.evidence(ok, []) == "overlay+maps"
    with pytest.raises(AoiError, match="AOI-SET-008"):
        Settings.check("ok_evidence", "png")


def test_req_insp_012_deleting_an_ok_record_deletes_its_preview(
    trained_ctx: AppContext, synthetic_dataset: Path, ng_board: Path
) -> None:
    ok, _ = saved(trained_ctx, synthetic_dataset, ng_board)
    trained_ctx.set_user("admin")
    done = trained_ctx.delete_inspections([int(str(ok["id"]))], HistoryFilter(), "test")
    assert done["files"] == 4 and not preview_path(Path(str(ok["overlay_path"]))).exists()


def test_req_insp_012_a_save_that_fails_takes_back_the_preview_too(
    trained_ctx: AppContext, synthetic_dataset: Path
) -> None:
    insp = trained_ctx.inspector(BOARD)
    trained_ctx.db._conn.execute(
        "CREATE TEMP TRIGGER refuse BEFORE INSERT ON inspections BEGIN SELECT RAISE(ABORT, 'refused'); END"
    )
    with pytest.raises(sqlite3.IntegrityError, match="refused"):
        trained_ctx.log_result(BOARD, *ok_board(trained_ctx, insp, synthetic_dataset), insp)
    assert [p.name for p in trained_ctx.settings.results_dir.rglob("*") if p.is_file()] == []


def test_req_insp_012_logs_shows_the_preview_and_settings_sets_the_policy(
    qtbot: QtBot, trained_ctx: AppContext, synthetic_dataset: Path, ng_board: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ok, _ = saved(trained_ctx, synthetic_dataset, ng_board)
    win = _window(qtbot, trained_ctx, "Admin")
    logs = win.pages["Logs & Export"]
    win.navigate("Logs & Export")
    listed(qtbot, logs)
    read: list[str] = []
    real = trained_ctx.load_image
    monkeypatch.setattr(trained_ctx, "load_image", lambda path: read.append(path) or real(path))
    logs.table.selectRow(next(i for i in range(logs.table.rowCount()) if row_key(logs.table, i) == ok["id"]))
    assert read[-1] == str(preview_path(Path(str(ok["overlay_path"]))))  # the preview, not the full JPEG
    settings = win.pages["Settings"]
    settings.ok_evidence.setCurrentIndex(settings.ok_evidence.findData("full"))
    monkeypatch.setattr(QMessageBox, "information", staticmethod(lambda *a, **k: QMessageBox.StandardButton.Ok))
    settings.save()
    stored = json.loads(trained_ctx.settings._file().read_text(encoding="utf-8"))
    assert trained_ctx.settings.ok_evidence == "full" and stored["ok_evidence"] == "full"
