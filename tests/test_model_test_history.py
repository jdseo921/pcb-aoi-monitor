"""REQ-TST-005 on AI Model Test (stage S46, part 3): History lists every stored run of the board model, newest first,
with its AI model, its dataset version or folder, what judged it, its missed defects and false calls; Open shows the run
on Run as it was stored. Results on the synthetic boards prove a code path; they are never quoted as accuracy."""

from __future__ import annotations

from pathlib import Path
from typing import cast

from pytestqt.qtbot import QtBot

from aoi.core.services import AppContext
from aoi.ui.pages.base import cell_text
from aoi.ui.pages.model_test import ModelTestPage
from tests.test_req_done_in_v01 import BOARD, _window
from tests.test_test_dataset import held_out


def test_req_tst_005_run_reopens_with_versions(qtbot: QtBot, trained_ctx: AppContext, synthetic_dataset: Path) -> None:
    """Two runs, a dataset version's then a folder's, are listed newest first with their sources; Open on the first
    shows its rows, tiles and previews on Run."""
    ctx = trained_ctx
    version, labels = held_out(ctx)
    name = ctx.db.datasets("", version)[0]["name"]
    first = ctx.test_dataset(version)[1][0]["run_uuid"]
    ctx.batch_test(BOARD, str(synthetic_dataset / "test"))
    win = _window(qtbot, ctx, "Engineer")
    assert win.navigate("AI Model Test")
    page = cast(ModelTestPage, win.pages["AI Model Test"])
    assert page.history.rowCount() == 0 or page.tabs.currentIndex() == 0
    page.tabs.setCurrentIndex(1)
    assert page.history.rowCount() == 2 and page.history_empty.isHidden()
    assert cell_text(page.history, 0, 2) == str(synthetic_dataset / "test") and cell_text(page.history, 1, 2) == name
    run = ctx.test_run(first)
    assert run is not None
    assert cell_text(page.history, 1, 1) == run["model_version"]
    assert cell_text(page.history, 1, 3) == f"recipe revision {run['judged_by'].recipe_rev}"
    assert cell_text(page.history, 1, 4).startswith(f"{run['metrics']['rates']['missed_defects']['n']} of ")
    page.history.selectRow(1)
    page.open_run()
    assert page.tabs.currentIndex() == 0 and len(page.rows) == len(labels)
    assert {r["run_uuid"] for r in page.rows} == {first} and page.table.rowCount() == len(labels)
    page.table.selectRow(0)
    qtbot.waitUntil(lambda: page.view._pix is not None and page._bg is None, timeout=5000)
    assert page.preview_verdict.text() == cell_text(page.table, 0, 2)


def test_req_tst_005_history_empty_says_so(qtbot: QtBot, trained_ctx: AppContext) -> None:
    """With no run stored, History says so and how one is made."""
    win = _window(qtbot, trained_ctx, "Engineer")
    assert win.navigate("AI Model Test")
    page = cast(ModelTestPage, win.pages["AI Model Test"])
    page.tabs.setCurrentIndex(1)
    assert page.history.rowCount() == 0 and not page.history_empty.isHidden()
