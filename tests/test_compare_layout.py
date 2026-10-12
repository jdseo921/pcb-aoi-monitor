"""Compare's Try other thresholds under the images, as wide as the page (Jay's choice of layout, 2026-10-08; sketch
docs/sketches/compare-decision-table.md): the decision table keeps every row of a board with an ROI in view, for an
Engineer and an Admin, at 1920 x 1080 and at 1600 x 900, in every state of the panel, and the window stays within the
screen. In the panel beside the images it showed five of seven rows at 1920 x 1080 and one at 1600 x 900."""

from __future__ import annotations

import threading
from pathlib import Path
from typing import Any

import pytest
from PySide6.QtWidgets import QApplication
from pytestqt.qtbot import QtBot

from aoi.core.recipe import ROI
from aoi.core.services import AppContext
from aoi.ui import theme
from aoi.ui.main_window import MainWindow
from aoi.ui.pages.compare import MODE_BOXES, MODE_SIDE, ComparePage
from aoi.ui.widgets.busy import BusyOverlay
from tests.test_compare_reevaluate import _stored_on_compare
from tests.test_req_done_in_v01 import BOARD, _window
from tools.render_screens import settle
from tools.screen_sizes import cut_off

SIZES = ((1920, 1080), (1600, 900))


def _rows_in_view(compare: ComparePage) -> tuple[int, int]:
    """How many of the decision table's rows show whole, and how many it has."""
    for _ in range(10):  # each layout asks the one above it by a posted event: passes of the event loop, not time
        QApplication.processEvents()
    t = compare.metrics
    shown = [r for r in range(t.rowCount()) if 0 <= t.rowViewportPosition(r)]
    whole = [r for r in shown if t.rowViewportPosition(r) + t.rowHeight(r) <= t.viewport().height()]
    return len(whole), t.rowCount()


def _every_row_at_both_sizes(win: MainWindow, compare: ComparePage, state: str) -> dict[tuple[int, int], int]:
    """All the decision table's rows whole at each size, the window the screen's size; the pictures' height at each."""
    pictures = {}
    for size in SIZES:
        win.resize(*size)
        whole, rows = _rows_in_view(compare)
        assert rows == theme.DECISION_ROWS and whole == rows, (state, size, whole, rows)
        assert win.size().toTuple() == size, (state, size, win.size(), "the window outgrew the screen")
        pictures[size] = compare.test_view.height()
    return pictures


@pytest.mark.parametrize("role", ["Engineer", "Admin"])
def test_req_cmp_005_every_decision_row_shows_with_the_panel_under_the_images(
    qtbot: QtBot, trained_ctx: AppContext, ng_board: Path, role: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A stored result, the same while Re-evaluate runs (its indicator over the table) and judged again (Would be
    shown), the Save to Recipe sheet open with all five thresholds changed, the result again once the recipe has moved
    on and its maps are gone (AOI-CMP-001 in the note), the board model given a scale (the size in mm, AOI-RCP-007 in
    the "why" box), and no calibrated value named, the tick clear and ticked (the note shown, the tick beside the
    field): each keeps all seven rows of the decision table in view at 1920 x 1080 and at 1600 x 900, the window as
    large as the screen, and Try other thresholds and the sheet under the images and the panel. The pictures are never
    more than three fields' height shorter than the stored result's: a label goes over its field in the tightest state,
    85 px at 1600 x 900 on Linux with DejaVu Sans (layout review)."""
    ctx = trained_ctx
    recipe = ctx.recipe(BOARD)[1]
    recipe.rois = [ROI("U1", "Presence", 0, 0, 4000, 4000)]  # its row makes the sketch's seven
    ctx.save_recipe(recipe)
    gate, judge_again = threading.Event(), AppContext.re_evaluate

    def held(self: AppContext, *args: Any) -> Any:
        assert gate.wait(20)
        return judge_again(self, *args)

    monkeypatch.setattr(AppContext, "re_evaluate", held)
    monkeypatch.setattr(BusyOverlay, "SHOW_AFTER_S", 0.0)  # the indicator and its Cancel at its first tick
    monkeypatch.setattr(BusyOverlay, "DETAIL_AFTER_S", 0.0)
    win, compare, shown = _stored_on_compare(qtbot, ctx, ng_board, role)
    for box in (compare.tryout, compare.sheet):
        assert not compare.splitter.isAncestorOf(box), "under the images and the panel, not in the panel"
    stored = _every_row_at_both_sizes(win, compare, "stored")

    def check(state: str) -> None:
        for size, height in _every_row_at_both_sizes(win, compare, state).items():
            assert height >= stored[size] - 3 * theme.FIELD_H, (state, size, height, stored[size])

    compare.diff_thr.setValue(200)
    compare.btn_try.click()
    qtbot.waitUntil(compare.try_busy.cancel_button.isVisible, timeout=10000)
    check("busy")
    gate.set()
    qtbot.waitUntil(lambda: compare._trying is None and compare.would_be.isVisible(), timeout=20000)
    check("judged again")
    compare.min_area.setValue(77)
    compare.ssim_min.setValue(0.5)
    compare.max_regions.setValue(9)
    compare.ai_thr.tick.setChecked(True)
    compare.ai_thr.field.setValue(7.0)
    compare.btn_save.click()
    assert compare.sheet.isVisible() and len(compare.sheet_changes.text().splitlines()) == 5
    check("sheet open")
    compare.btn_cancel.click()
    recipe = ctx.recipe(BOARD)[1]
    recipe.ssim_min = 0.5
    ctx.save_recipe(recipe)
    ctx.db.clear_map_paths([shown])

    def show_again() -> None:
        win._on_board_model(BOARD)
        compare.show_stored(shown)
        qtbot.waitUntil(lambda: compare.loaded and compare._bg is None, timeout=20000)

    show_again()
    assert "AOI-CMP-001" in compare.note.text()
    check("moved on, maps gone")
    ctx.set_scale(BOARD, 476, 10)
    recipe = ctx.recipe(BOARD)[1]
    recipe.min_defect_area, recipe.min_defect_mm = 12, None  # under 4 px
    ctx.save_recipe(recipe)
    show_again()
    assert compare.min_size.mm.isVisible() and "AOI-RCP-007" in compare.why.toPlainText()
    check("in mm, AOI-RCP-007")
    ctx.db.execute("DELETE FROM models WHERE board_model=?", (BOARD,))
    show_again()  # no AI model trained: the note says so, and the tick goes beside the field
    assert compare.ai_thr.note.isVisible() and compare.ai_thr.tick.parentWidget() is compare.ai_thr
    for ticked in (False, True):
        compare.ai_thr.tick.setChecked(ticked)
        check(f"no calibrated value, ticked {ticked}")


def test_req_set_004_compare_needs_the_same_width_in_either_arrangement_and_view(
    qtbot: QtBot, trained_ctx: AppContext, ng_board: Path
) -> None:
    """The width Compare's pair needs beside the panel (`_wide_need`) is the same with the table beside the pair or
    under it, and with Defect boxes only, which hides the Golden board (review of A7): the panel's margin there side by
    side and not under the pair turned the pair, at a width within those 8 px of its need, from one arrangement to the
    other until Python's stack ran out; and a view that hid the Golden board moved the verdict and the table beside the
    test board, which then had half the width Defect boxes only gives it."""
    _win, compare, _iid = _stored_on_compare(qtbot, trained_ctx, ng_board, "Engineer")
    needs = set()
    for wide in (True, False):
        compare.splitter._arrange(wide)
        for mode in (MODE_SIDE, MODE_BOXES):
            compare.mode.setCurrentIndex(mode)
            QApplication.processEvents()
            needs.add(compare._wide_need())
    assert len(needs) == 1, needs


def test_req_set_004_compares_why_box_stands_beside_the_pair_over_the_table(
    qtbot: QtBot, trained_ctx: AppContext, ng_board: Path
) -> None:
    """With the decision table under the pair, the "why" box stands beside the pair under the verdict, whole and in
    view, as tall as theme.WHY_H at least and down to the foot of the column, taller where the column has the room, and
    the table is as tall as its rows, the boards taking the rest; with the table beside the pair, the box is under the
    table again, theme.WHY_H at most (review of A7: under the table it gave way to the boards, and showed a line and a
    half of its reasons at 1920 x 1080 in the presenter theme and none above the fold at 1366 x 768; and the table, held
    to a least height read before the page had taken the turn, kept a blank band under its rows). At 1920 x 1080, then
    with the presenter theme switched on there, which turns the page, in a 1600 x 900 window with it on and off again,
    and at 1366 x 768 with it on; each switched while another page shows, as an Admin switches it on Settings."""
    ctx = trained_ctx
    ctx.inspect_file(BOARD, str(ng_board))
    win = _window(qtbot, ctx, "Engineer")
    compare = win.pages["Compare"]
    assert isinstance(compare, ComparePage)
    win.resize(1920, 1080)
    assert win.navigate("Compare")
    compare.show_stored(ctx.inspections(board_model=BOARD)[0]["id"])
    qtbot.waitUntil(lambda: compare.loaded and compare._bg is None, timeout=10000)
    seen, heights = {}, {}
    steps = ((1920, 1080, False), (1920, 1080, True), (1600, 900, True), (1600, 900, False), (1366, 768, True))
    for width, height, presenter in steps:
        size = (width, height)
        assert win.navigate("Home")
        win.resize(*size)
        ctx.settings.presenter_theme = presenter
        win.apply_theme()
        settle()
        assert win.navigate("Compare")
        settle()
        why, table, under = compare.why, compare.metrics, not compare.splitter.wide()
        beside = compare.beside.isAncestorOf(why) and why.visibleRegion().boundingRect() == why.rect()
        if under:
            tall = why.height() >= theme.WHY_H and why.geometry().bottom() == compare.beside.rect().bottom()
        else:
            tall = why.height() <= theme.WHY_H
        rows = table.height() == table.minimumHeight() if under else None
        seen[size, presenter] = (under, beside, tall, compare.decision.isAncestorOf(why), rows, cut_off(win, "Compare"))
        heights[size, presenter] = why.height()
    assert seen == {
        ((1920, 1080), False): (False, False, True, True, None, []),
        ((1920, 1080), True): (True, True, True, False, True, []),
        ((1600, 900), True): (True, True, True, False, True, []),
        ((1600, 900), False): (True, True, True, False, True, []),
        ((1366, 768), True): (True, True, True, False, True, []),
    }, seen
    assert heights[(1920, 1080), True] > theme.WHY_H, heights  # the room under the note, more than under the table


@pytest.mark.parametrize("size", [(1600, 900), (1920, 1080)])
def test_req_set_004_compares_arrangement_follows_the_window_not_the_record(
    qtbot: QtBot, trained_ctx: AppContext, ng_board: Path, size: tuple[int, int]
) -> None:
    """Compare empty, then with a stored NG record, keeps one arrangement in a window of a given size (review of A7):
    read from the decision table's columns, the width the pair needs beside it rose as the first record filled them,
    and an engineer's 1600 x 900 page turned the pair from beside the table to over it under their eyes. At 1600 x 900
    the table is under the pair and at 1920 x 1080 beside it, in the 14 pt theme, and whole either way."""
    ctx = trained_ctx
    ctx.inspect_file(BOARD, str(ng_board))
    win = _window(qtbot, ctx, "Engineer")
    compare = win.pages["Compare"]
    assert isinstance(compare, ComparePage)
    win.resize(*size)
    assert win.navigate("Compare")
    settle()
    turns: list[bool] = []
    compare.splitter.arranged.connect(turns.append)
    empty = compare.splitter.wide()
    compare.show_stored(ctx.inspections(board_model=BOARD)[0]["id"])
    qtbot.waitUntil(lambda: compare.loaded and compare._bg is None, timeout=10000)
    settle()
    assert compare.metrics.rowCount() >= 5 and turns == [], turns
    assert compare.splitter.wide() is empty is (size == (1920, 1080))
    assert cut_off(win, "Compare") == [], size
