"""REQ-TST-006 and REQ-TST-003 on AI Model Test (stage S46, part 2): the results table grows board by board, its first
row within 2 s of Run Test; selecting a row shows the overlay stored as the run judged it, within 300 ms, and never
judges the board again, whatever changed since. Results on the synthetic boards prove a code path; they are never quoted
as accuracy."""

from __future__ import annotations

from pathlib import Path
from time import perf_counter
from typing import Any, cast

import pytest
from PySide6.QtCore import QTimer
from pytestqt.qtbot import QtBot

from aoi.core.inspector import Inspector
from aoi.core.services import AppContext
from aoi.ui.pages.base import cell_text
from aoi.ui.pages.model_test import ModelTestPage
from tests.conftest import activated
from tests.test_req_done_in_v01 import BOARD, _window
from tools.trainable import trainable


def page_of(qtbot: QtBot, ctx: AppContext) -> ModelTestPage:
    win = _window(qtbot, ctx, "Engineer")
    assert win.navigate("AI Model Test")
    page = cast(ModelTestPage, win.pages["AI Model Test"])
    page.source.setCurrentIndex(page.source.count() - 1)  # a labelled folder
    return page


def test_req_tst_006_first_row_within_2s(qtbot: QtBot, trained_ctx: AppContext, synthetic_dataset: Path) -> None:
    """The first row shows within 2 s of Run Test, and the table holds more rows as the run goes on, before it ends."""
    page = page_of(qtbot, trained_ctx)
    page.folder = str(synthetic_dataset / "test")
    counts: list[tuple[float, int, bool]] = []  # (seconds since Run Test, rows shown, run still going)
    timer = QTimer()
    timer.setInterval(20)
    start = perf_counter()
    timer.timeout.connect(
        lambda: counts.append((perf_counter() - start, page.table.rowCount(), not page.btn_run.isEnabled()))
    )
    timer.start()
    page.run()
    qtbot.waitUntil(lambda: page.btn_run.isEnabled() and bool(page.rows), timeout=120000)
    timer.stop()
    first = next(t for t, n, _ in counts if n > 0)
    during = sorted({n for _, n, going in counts if going and n > 0})
    print(f"first row after {first * 1000:.0f} ms; rows seen while running {during}")
    assert first < 2.0, first
    assert len(during) >= 3, during  # it grew board by board, not all at once at the end
    assert page.table.rowCount() == len(page.rows) == 21


@pytest.mark.parametrize("change", ["none", "retrain", "recipe"])
def test_req_tst_003_preview_under_300ms_no_reinspect(
    qtbot: QtBot,
    trained_ctx: AppContext,
    synthetic_dataset: Path,
    monkeypatch: pytest.MonkeyPatch,
    change: str,
) -> None:
    """After Run Test, and after a retrain or a new recipe revision, every row shows its stored overlay with its own
    verdict within 300 ms, and no board is judged again."""
    ctx = trained_ctx
    page = page_of(qtbot, ctx)
    page.folder = str(synthetic_dataset / "test")
    page.run()
    qtbot.waitUntil(lambda: page.btn_run.isEnabled() and bool(page.rows), timeout=120000)
    if change == "retrain":
        activated(ctx, ctx.train(trainable(ctx, BOARD), epochs=1, image_size=64))
    elif change == "recipe":
        recipe = ctx.recipe(BOARD)[1]
        recipe.ssim_min = 0.75
        ctx.save_recipe(recipe)
    page.on_show()

    def never(*_: Any) -> None:
        raise AssertionError("a preview judged its board again")

    monkeypatch.setattr(Inspector, "inspect", never)
    slowest = 0.0
    for i in range(page.table.rowCount()):
        page.table.clearSelection()
        start = perf_counter()
        page.table.selectRow(i)
        qtbot.waitUntil(lambda: page.view._pix is not None and page._bg is None, timeout=5000)
        slowest = max(slowest, perf_counter() - start)
        assert page.preview_verdict.text() == cell_text(page.table, i, 2)  # the row's own Verdict cell
        assert page.preview_empty.isHidden()
    print(f"slowest preview {slowest * 1000:.0f} ms")
    assert slowest < 0.3, slowest
    assert page.run_note.isVisible() == (change != "none")
