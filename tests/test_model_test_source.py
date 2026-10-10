"""REQ-TST-001 and REQ-TST-002 on AI Model Test (stage S44 and S45, part 2): the source is a frozen dataset version's
locked validation set, picked by default, or a labelled folder; 100 images at 5 MP test without freezing the window;
the tiles show each rate as n of N with its one-sided 95 % bound, missed defects and false calls first. Results on the
synthetic boards prove a code path; they are never quoted as accuracy."""

from __future__ import annotations

from pathlib import Path
from typing import cast

from pytestqt.qtbot import QtBot

from aoi.core.services import AppContext
from aoi.ui.pages.model_test import ModelTestPage
from tests.conftest import distinct_copies
from tests.test_no_freeze import BUDGET_S, board_5mp, gap_meter  # noqa: F401  # the 5 MP fixture
from tests.test_req_done_in_v01 import BOARD, _window
from tests.test_test_dataset import held_out


def page_of(qtbot: QtBot, ctx: AppContext) -> ModelTestPage:
    win = _window(qtbot, ctx, "Engineer")
    assert win.navigate("AI Model Test")
    return cast(ModelTestPage, win.pages["AI Model Test"])


def ran(qtbot: QtBot, page: ModelTestPage) -> None:
    page.run()
    qtbot.waitUntil(lambda: page.btn_run.isEnabled() and bool(page.rows), timeout=300000)


def test_req_tst_001_dataset_version_is_the_default_source(qtbot: QtBot, trained_ctx: AppContext) -> None:
    """A version with a locked validation set is listed first and picked; Run Test judges exactly its validation set,
    labelled as frozen, and the run names the version."""
    version, labels = held_out(trained_ctx)
    name = trained_ctx.db.datasets("", version)[0]["name"]
    page = page_of(qtbot, trained_ctx)
    assert page.source.currentData() == version
    assert page.source.currentText() == f"{name}: its locked validation set, {len(labels)} images"
    assert page.source.itemData(page.source.count() - 1) is None  # a labelled folder, last
    ran(qtbot, page)
    assert len(page.rows) == len(labels) and {r["gt"] for r in page.rows} == set(labels.values())
    run = trained_ctx.db.latest_test_run(BOARD)
    assert run is not None and run["dataset_uuid"] == version


def test_req_tst_002_tiles_show_counts_and_bounds(qtbot: QtBot, trained_ctx: AppContext) -> None:
    """Each tile reads its rate's count, n of N, and its bound under it; missed defects and false calls come first."""
    held_out(trained_ctx)
    page = page_of(qtbot, trained_ctx)
    ran(qtbot, page)
    assert list(page.tiles) == ["missed_defects", "false_calls", "recall", "precision", "accuracy"]
    rates = page.metrics["rates"]
    for key, tile in page.tiles.items():
        r = rates[key]
        assert f"{r['n']} of {r['of']}" in tile.text(), key
        if r["of"]:
            shown = tile.text().replace("\u00a0", " ")  # the number and its % are kept together on a wrapped line
            assert f"95 % {r['bound']} bound {round(100 * r['limit'], 1)} %" in shown, key


def test_req_tst_001_100_images_no_freeze(
    qtbot: QtBot,
    trained_ctx: AppContext,
    board_5mp: Path,  # noqa: F811  # the fixture, imported from test_no_freeze
    tmp_path: Path,
) -> None:
    """100 images at 5 MP, in a labelled folder, test with no UI-thread stall of 2 s or more."""
    folder = tmp_path / "boards"
    distinct_copies(board_5mp, folder / "ng", 100)
    page = page_of(qtbot, trained_ctx)
    page.folder = str(folder)
    page.source.setCurrentIndex(page.source.count() - 1)  # the labelled folder
    with gap_meter(qtbot) as g:
        ran(qtbot, page)
    assert len(page.rows) == 100 and g["longest_s"] < BUDGET_S, g
