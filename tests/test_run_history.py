"""REQ-TST-003, REQ-TST-005 and REQ-TST-006 (stage S46, part 1): a validation run hands each row on as its board is
judged, keeps each row's overlay for a preview that never judges the board again, and is stored with the AI model
version, the dataset version and what judged it, so any run can be listed and reopened. Results on the synthetic boards
prove a code path; they are never quoted as accuracy."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import cv2
import pytest

from aoi.core import services
from aoi.core.imaging import PREVIEW_PX, list_images
from aoi.core.services import AppContext
from tests.test_req_done_in_v01 import BOARD
from tests.test_test_dataset import held_out


def test_req_tst_006_rows_arrive_board_by_board(trained_ctx: AppContext, synthetic_dataset: Path) -> None:
    """Each row reaches `on_row` once its board is judged, in order, before the run returns, with the run's UUID."""
    folder = synthetic_dataset / "test"
    seen: list[dict[str, Any]] = []
    metrics, rows, _ = trained_ctx.batch_test(BOARD, str(folder), on_row=seen.append)
    assert len(seen) == len(rows) == len(list_images(folder))
    assert [s["image"] for s in seen] == [r["image"] for r in rows]
    assert {s["run_uuid"] for s in seen} == {rows[0]["run_uuid"]}


def test_req_tst_003_overlay_stored_per_row(trained_ctx: AppContext, synthetic_dataset: Path) -> None:
    """Every row names its overlay, kept under results/test_runs/<run>/ and at most PREVIEW_PX on its longest side."""
    _, rows, _ = trained_ctx.batch_test(BOARD, str(synthetic_dataset / "test"))
    folder = trained_ctx.settings.results_dir / services.TEST_RUNS / rows[0]["run_uuid"]
    for r in rows:
        overlay = Path(r["overlay"])
        assert overlay.parent == folder and overlay.is_file()
        h, w = cv2.imread(str(overlay)).shape[:2]
        assert max(h, w) <= PREVIEW_PX


def test_req_tst_003_a_failed_run_leaves_no_overlay(
    trained_ctx: AppContext, synthetic_dataset: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A run that fails part-way stores no run and leaves none of its overlays behind."""
    calls = {"n": 0}
    real = AppContext.load_image

    def fail_third(ctx: AppContext, path: str | Path) -> Any:
        calls["n"] += 1
        if calls["n"] == 3:
            raise OSError("the third board is gone")
        return real(ctx, path)

    monkeypatch.setattr(AppContext, "load_image", fail_third)
    with pytest.raises(OSError):
        trained_ctx.batch_test(BOARD, str(synthetic_dataset / "test"))
    runs = trained_ctx.settings.results_dir / services.TEST_RUNS
    assert not runs.exists() or not any(runs.iterdir())
    assert trained_ctx.test_runs(BOARD) == []


def test_req_tst_005_run_reopens_with_versions(trained_ctx: AppContext) -> None:
    """A run is listed, newest first, and reopens with its AI model version, its dataset version, what judged it, its
    metrics and its rows, overlays included."""
    ctx = trained_ctx
    version, _ = held_out(ctx)
    metrics, rows, judged = ctx.test_dataset(version)
    [listed] = ctx.test_runs(BOARD)
    opened = ctx.test_run(rows[0]["run_uuid"])
    assert opened is not None and opened["uuid"] == listed["uuid"] == rows[0]["run_uuid"]
    assert (opened["dataset_uuid"], opened["model_version"], opened["judged_by"]) == (
        version,
        rows[0]["model_version"],
        judged,
    )
    assert opened["metrics"] == metrics
    keys = ("gt", "ai_result", "score", "pass_fail", "run_uuid", "model_version")
    assert [{k: r[k] for k in keys} for r in opened["results"]] == [{k: r[k] for k in keys} for r in rows]
    assert all(Path(r["overlay"]).is_file() for r in opened["results"])
    assert ctx.test_run("no-such-run") is None
