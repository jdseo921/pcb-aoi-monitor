"""#246 (stage S25): a save that is refused leaves no picture in results/ that no record names (REQ-INSP-008)."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import numpy as np
import pytest

from aoi.config import Settings
from aoi.core import maps, services
from aoi.core.services import AppContext
from aoi.data.db import Database
from tests.test_req_done_in_v01 import BOARD

EVIDENCE = ("overlay_path", "diff_map_path", "ai_map_path")


def _files(ctx: AppContext) -> list[str]:
    """Every file under results/, by name."""
    return sorted(p.name for p in ctx.settings.results_dir.rglob("*") if p.is_file())


def test_req_insp_008_a_save_the_database_refuses_leaves_no_file_in_results(
    trained_ctx: AppContext, ng_board: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The re-test's scenario: the database refuses the record of an NG board twice (another program holds aoi.sqlite).
    Before, each refused save left its overlay, difference map and AI map in results/<day>/ with no record naming
    them, and neither the OK-map sweep nor a restart removed them (6 files); now none is left."""
    ctx = trained_ctx
    assert _files(ctx) == []

    def locked(*args: object, **kwargs: object) -> int:
        raise sqlite3.OperationalError("database is locked")

    monkeypatch.setattr(Database, "add_inspection", locked)
    for _ in range(2):
        with pytest.raises(sqlite3.OperationalError, match="database is locked"):
            ctx.inspect_file(BOARD, str(ng_board))
    monkeypatch.undo()
    assert ctx.inspections() == [] and _files(ctx) == []
    ctx.close()
    again = AppContext(Settings(workspace=ctx.settings.workspace, device="cpu"))  # a restart sweeps nothing either
    assert again.inspections() == [] and _files(again) == []
    again.close()


@pytest.mark.parametrize("failing", ["_diff.png", maps.AI_FILE])
def test_req_insp_008_a_map_write_that_fails_leaves_no_file(
    trained_ctx: AppContext, ng_board: Path, monkeypatch: pytest.MonkeyPatch, failing: str
) -> None:
    """The difference map's write fails after the overlay's, or the AI map's after both: the files written before it
    are removed and no record is saved. Before, the overlay (and the difference map) stayed in results/."""
    ctx = trained_ctx
    real, written = maps.save_image, []

    def save_image(path: Path, img: np.ndarray, params: tuple[int, ...] = ()) -> None:
        if str(path).endswith(failing):
            raise OSError(28, "No space left on device")
        real(path, img, params)
        written.append(Path(path).name.rsplit("_NG", 1)[1])  # ".png" for the overlay, then the map's ending

    monkeypatch.setattr(services, "save_image", save_image)
    monkeypatch.setattr(maps, "save_image", save_image)
    insp = ctx.inspector(BOARD)
    res = insp.inspect(ctx.load_image(str(ng_board)))
    with pytest.raises(OSError, match="No space left"):
        ctx.log_result(BOARD, str(ng_board), res, insp)
    assert written == ([".png"] if failing == "_diff.png" else [".png", "_diff.png"]), written
    assert ctx.inspections() == [] and _files(ctx) == [], "the overlay and the map written before are removed"


def test_req_insp_008_a_failure_after_the_record_is_saved_removes_no_file(
    trained_ctx: AppContext, ng_board: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Once the record has committed, its files are named and stay, even when the log line after it fails."""
    ctx = trained_ctx
    real = ctx.log.info

    def info(msg: str, *args: object, **kwargs: object) -> None:
        if msg == "inspection.saved":
            raise OSError(5, "Input/output error")
        real(msg, *args, **kwargs)

    monkeypatch.setattr(ctx.log, "info", info)
    with pytest.raises(OSError, match="Input/output error"):
        ctx.inspect_file(BOARD, str(ng_board))
    (rec,) = ctx.inspections()
    assert all(rec[k] and Path(rec[k]).is_file() for k in EVIDENCE) and len(_files(ctx)) == 3
