"""REQ-CMP-002 (S27b): each Compare view renders within 300 ms at 5 MP, the first time it is shown and again later;
the heat views (aoi/core/views.py) are drawn once per view for the result shown, and go with it."""

from __future__ import annotations

import gc
import statistics
import weakref
from pathlib import Path
from time import perf_counter

import cv2
import numpy as np
import pytest
from PySide6.QtWidgets import QApplication
from pytestqt.qtbot import QtBot

from aoi.core.imaging import heat_overlay
from aoi.core.inspector import InspectionResult
from aoi.core.services import AppContext
from aoi.core.views import difference_view
from aoi.ui.pages.compare import MODE_AI, MODE_BOXES, MODE_DIFF, MODE_SIDE, MODES, ComparePage
from tests.test_no_freeze import SIZE_5MP, board_5mp  # noqa: F401  # the 5 MP fixture
from tests.test_req_done_in_v01 import BOARD, _window

BUDGET_S = 0.3
VIEWS = (MODE_DIFF, MODE_AI, MODE_BOXES, MODE_SIDE)  # from Side by side, each one a change


def _compare(qtbot: QtBot, ctx: AppContext, monkeypatch: pytest.MonkeyPatch) -> tuple[ComparePage, list[np.ndarray]]:
    """Compare, opened as an Engineer, and the list of every picture its test board pane is given from now on."""
    win = _window(qtbot, ctx, "Engineer")
    page = win.pages["Compare"]
    assert isinstance(page, ComparePage)
    win.navigate("Compare")
    qtbot.waitUntil(lambda: ctx.jobs.idle() and page._bg is None, timeout=20000)
    shown: list[np.ndarray] = []
    draw = page.test_view.set_image
    monkeypatch.setattr(page.test_view, "set_image", lambda img, *a, **k: (shown.append(img), draw(img, *a, **k)))
    return page, shown


def _open(qtbot: QtBot, page: ComparePage, iid: int) -> InspectionResult:
    """A stored result, opened once its pictures and maps are loaded: a new result object each time."""
    page.show_stored(iid)
    qtbot.waitUntil(lambda: page._bg is None and page.res is not None and page.res.image is not None, timeout=20000)
    assert page.res is not None
    return page.res


def _switch(page: ComparePage, mode: int) -> float:
    """Seconds from choosing a view until both panes are painted."""
    t0 = perf_counter()
    page.mode.setCurrentIndex(mode)
    QApplication.processEvents()
    for view in (page.test_view, page.ref_view):
        view.viewport().repaint()
    return perf_counter() - t0


def test_req_cmp_002_each_view_under_300_ms(
    qtbot: QtBot,
    trained_ctx: AppContext,
    board_5mp: Path,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A stored 5 MP NG result with both maps, opened on Compare five times: for each of the four views, the median
    time from choosing it until both panes are painted is under 300 ms the first time (a heat view is drawn) and the
    second (it is shown again: the same picture); each heat view is drawn from its own map at its own scale."""
    ctx = trained_ctx
    golden = Path(str(ctx.reference_image(BOARD)))
    big = golden.with_name("golden_5mp.png")  # the customer's golden board is taken by the same 5 MP camera
    cv2.imwrite(str(big), cv2.resize(cv2.imread(str(golden)), SIZE_5MP, interpolation=cv2.INTER_CUBIC))
    ctx.db.set_reference(BOARD, str(big))
    ctx.inspect_file(BOARD, str(board_5mp))
    iid = ctx.inspections(board_model=BOARD)[0]["id"]
    page, shown = _compare(qtbot, ctx, monkeypatch)
    took: dict[tuple[int, int], list[float]] = {}
    for _ in range(5):  # the median: a CI machine's hiccup is not the page's cost, and a slow page is slow every time
        res = _open(qtbot, page, iid)
        for n in (1, 2):
            for mode in VIEWS:
                took.setdefault((n, mode), []).append(_switch(page, mode))
    medians = {f"{MODES[m]} pass {n}": statistics.median(s) for (n, m), s in took.items()}
    print({k: f"{s * 1000:.0f} ms" for k, s in medians.items()}, f"worst {max(map(max, took.values())) * 1000:.0f} ms")
    assert max(medians.values()) < BUDGET_S, medians
    assert res.image is not None and res.image.shape[1::-1] == SIZE_5MP
    first, second = shown[-8:-4], shown[-4:]
    assert first[0] is second[0] and first[1] is second[1], "a heat view is drawn once for the result shown"
    assert first[2] is second[2] is first[3] is res.image, "Defect boxes only and Side by side show the board"
    assert res.compare is not None and res.compare.diff_map is not None and res.anomaly_map is not None
    thr = next(c.threshold for c in res.checks if c.source == "AI")  # each from its own map, at its own scale
    assert np.array_equal(first[0], heat_overlay(res.image, res.compare.diff_map, 1.5 * page.diff_thr.value()))
    assert np.array_equal(first[1], heat_overlay(res.image, res.anomaly_map, 1.5 * thr))
    page.diff_thr.setValue(page.diff_thr.value() + 10)  # another scale: drawn anew, in place of the one before
    _switch(page, MODE_DIFF)
    assert shown[-1] is not first[0] and np.array_equal(shown[-1], difference_view(res, page.diff_thr.value()))


def test_req_cmp_002_views_go_with_their_result(
    qtbot: QtBot,
    trained_ctx: AppContext,
    ng_board: Path,
    synthetic_dataset: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The heat views drawn for a result go when another is shown (another stored result, Re-evaluate, another
    board model), and the next result's views are drawn from its own maps; switching views 50 times leaves the
    Golden board's pane with one set of boxes, not 50."""
    ctx = trained_ctx
    other = next(p for p in sorted(synthetic_dataset.glob("test/ng/*.png")) if p != ng_board)
    for path in (ng_board, other):
        ctx.inspect_file(BOARD, str(path))
    b_id, a_id = (r["id"] for r in ctx.inspections(board_model=BOARD)[:2])  # newest first
    page, shown = _compare(qtbot, ctx, monkeypatch)
    pixels = page.diff_thr.value()
    a = _open(qtbot, page, a_id)
    for mode in (MODE_DIFF, MODE_AI, MODE_SIDE):
        _switch(page, mode)
    drawn = [weakref.ref(v) for v in shown[-3:-1]]
    shown.clear()
    b = _open(qtbot, page, b_id)  # another stored result, opened in Side by side
    gc.collect()
    assert all(w() is None for w in drawn), "the last result's heat views go with it"
    _switch(page, MODE_DIFF)
    assert np.array_equal(shown[-1], difference_view(b, pixels))
    assert not np.array_equal(shown[-1], difference_view(a, pixels))
    page.run()  # Re-evaluate: a new result, drawn from its own maps
    qtbot.waitUntil(lambda: page._bg is None and page.res is not b and page.res is not None, timeout=20000)
    assert page.res is not None and np.array_equal(shown[-1], difference_view(page.res, pixels))
    items = len(page.ref_view.scene().items())
    for n in range(50):
        _switch(page, VIEWS[n % 4])
    assert len(page.ref_view.scene().items()) == items, "each switch draws the Golden board's boxes once"
    drawn = [weakref.ref(v) for v in shown[-2:]]  # the last two switches: the difference view, then the AI view
    shown.clear()
    page.on_board_model_changed(None)
    gc.collect()
    assert all(w() is None for w in drawn), "another board model drops the views"


def test_req_cmp_002_heat_overlay_draws_what_it_drew_before() -> None:
    """The OpenCV blend draws what the NumPy blend before it drew, within 3 levels of 255: the speed-up moves no
    colour a person could see; a smaller map is stretched to the board, and a vmax of 0 shows any value in full."""
    rng = np.random.default_rng(0)
    img = rng.integers(0, 256, (480, 640, 3), dtype=np.uint8)
    values = rng.random((480, 640), dtype=np.float32) * 60
    for vmax in (7.5, 40.0, 100.0):
        weight = np.clip(values / vmax, 0, 1)[..., None] * 0.8
        colours = cv2.applyColorMap(np.clip(values / vmax * 255.0, 0, 255).astype(np.uint8), cv2.COLORMAP_JET)
        before = (img * (1 - weight) + colours * weight).astype(np.uint8)  # the blend before S27b
        assert np.abs(heat_overlay(img, values, vmax).astype(int) - before).max() <= 3, vmax
    half = values[::2, ::2].copy()
    assert np.array_equal(heat_overlay(img, half, 40.0), heat_overlay(img, cv2.resize(half, (640, 480)), 40.0))
    zero = np.zeros((480, 640), np.float32)
    zero[0, 0] = 0.5
    shaded = heat_overlay(img, zero, 0.0)
    assert np.array_equal(shaded[1:], img[1:]) and np.array_equal(shaded[0, 1:], img[0, 1:])
    assert np.array_equal(shaded[0, 0], heat_overlay(img, zero, 0.5)[0, 0]), "in full colour"
