"""The inspection cycle with no screen (#447): ten boards from a frame source give the Inspection page's records, and a
recipe saved during a run is named by AOI-INSP-013."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

import numpy as np
from pytestqt.qtbot import QtBot

from aoi.config import Settings
from aoi.core.cycle import FrameMeta
from aoi.core.imaging import list_images
from aoi.core.services import AppContext
from aoi.hal import FolderCamera
from tests.conftest import TrainedModel, engineer, restored
from tests.test_req_done_in_v01 import BOARD, _window


class CameraSource:
    """A `FolderCamera` as a frame source, each frame with its file; `between` runs before each frame is handed over."""

    def __init__(self, paths: list[Path], between: Callable[[], None] = lambda: None) -> None:
        self.camera, self.between = FolderCamera(paths), between
        self.camera.open()

    def grab(self) -> tuple[np.ndarray | None, FrameMeta] | None:
        frame = self.camera.grab()
        if frame is None or self.camera.current_path is None:
            return None
        self.between()
        return frame, FrameMeta(self.camera.current_path, "Side")


def records(ctx: AppContext) -> list[tuple[Any, ...]]:
    """Each record without its id, time or UUID, oldest first, with its defects."""
    keys = ("result", "view", "model_version", "recipe_rev", "operator")
    return [
        (Path(r["image_path"]).name, round(r["score"], 6), *(r[k] for k in keys),
         [(d["no"], d["type"], round(d["score"], 6), d["side"], d["x"], d["y"]) for d in ctx.defects_for(r["id"])])
        for r in sorted(ctx.inspections(board_model=BOARD), key=lambda r: r["id"])
    ]  # fmt: skip


def test_447_ten_boards_through_the_cycle_give_the_records_the_page_gives(
    qtbot: QtBot, trained_ctx: AppContext, tiny_model: TrainedModel, synthetic_dataset: Path, tmp_path: Path
) -> None:
    paths = sorted(list_images(synthetic_dataset / "test"))[:10]  # OK and NG boards
    win = _window(qtbot, trained_ctx, "Engineer")
    page = win.pages["Inspection"]
    win.navigate("Inspection")
    page.view_combo.setCurrentIndex(page.view_combo.findData("Side"))
    page._set_queue(paths)
    page.start_run()
    qtbot.waitUntil(lambda: page.queue_pos == 9 and page.worker is None and not page.running, timeout=120000)
    headless = engineer(AppContext(Settings(workspace=str(restored(tiny_model, tmp_path / "ws2")), device="cpu")))
    try:
        outcomes = list(headless.inspection_cycle().run(BOARD, CameraSource(paths)))
        assert [o.path for o in outcomes] == paths and all(o.record_id is not None for o in outcomes)
        assert [o.built for o in outcomes] == [True] + [False] * 9  # one engine, kept while it is what is active
        assert len(records(trained_ctx)) == 10 and records(headless) == records(trained_ctx)
        assert not [a for a in headless.alarms() if a["code"] == "AOI-INSP-013"]
    finally:
        headless.close()


def test_447_a_recipe_saved_during_a_headless_run_is_named_by_aoi_insp_013(
    trained_ctx: AppContext, synthetic_dataset: Path
) -> None:
    grabbed: list[int] = []

    def save_before_the_second() -> None:
        grabbed.append(0)
        if len(grabbed) == 2:
            recipe = trained_ctx.recipe(BOARD)[1]
            recipe.anomaly_threshold = 0.5
            grabbed[1] = trained_ctx.save_recipe(recipe)

    source = CameraSource(sorted(list_images(synthetic_dataset / "test"))[:3], save_before_the_second)
    outcomes = list(trained_ctx.inspection_cycle().run(BOARD, source))
    assert [(o.built, o.moved) for o in outcomes] == [(True, False), (True, True), (False, False)]
    (alarm,) = [a for a in trained_ctx.alarms() if a["code"] == "AOI-INSP-013"]
    assert outcomes[1].path.name in alarm["message"] and f"recipe revision {grabbed[1]}" in alarm["message"]
    assert alarm["phrase"]  # shown in the UI language of the day it is read
