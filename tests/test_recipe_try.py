"""REQ-RCP-003 (S49): Try Recipe… (Ctrl+T) runs the recipe as edited on a board, the one last inspected under the board
model picked first (Q23), off the UI thread (REQ-SET-021), and shows the verdict and the checks behind it as Compare's
decision table names them, while storing nothing (sketch docs/sketches/recipe-editor.md)."""

from __future__ import annotations

import copy
from pathlib import Path

import pytest
from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QFileDialog, QWidget
from pytestqt.qtbot import QtBot

from aoi.core.services import AppContext
from aoi.ui import theme
from aoi.ui.pages.compare import check_text
from tests.test_label_editor import CTRL, _wheel
from tests.test_recipe_rois import _pens
from tests.test_req_done_in_v01 import BOARD, _inspect_one, _window


def _stored(ctx: AppContext) -> tuple[dict[str, int], list[str]]:
    """Every table's row count, and every file in the workspace but the database's own and the logs."""
    tables = [r["name"] for r in ctx.db.query("SELECT name FROM sqlite_master WHERE type='table'")]
    counts = {t: ctx.db.query(f'SELECT COUNT(*) AS n FROM "{t}"')[0]["n"] for t in tables}
    ws = Path(ctx.settings.workspace)
    files = [str(p.relative_to(ws)) for p in ws.rglob("*") if p.is_file()]
    return counts, sorted(f for f in files if not f.startswith("logs") and ".sqlite" not in f and ".db" not in f)


def test_req_rcp_003_test_run_shows_checks_stores_nothing(
    qtbot: QtBot, trained_ctx: AppContext, ng_board: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Ctrl+T offers the board last inspected under the board model first; the Try judges it with the recipe as edited,
    an ROI not saved included, and shows its verdict and a row per check (name and result as Compare shows them) and
    the inspection time; its defects stay drawn through a zoom, and nothing is stored: no row in any table, no file."""
    ctx = trained_ctx
    win = _window(qtbot, ctx)
    _inspect_one(qtbot, win, ng_board)
    last = ctx.inspections(board_model=BOARD)[0]["image_path"]
    offered: list[str] = []

    def pick(parent: QWidget, caption: str, start: str, filters: str) -> tuple[str, str]:
        offered.append(start)
        return start, filters

    monkeypatch.setattr(QFileDialog, "getOpenFileName", staticmethod(pick))
    win.navigate("Recipe Editor")
    qtbot.waitUntil(win.isActiveWindow, timeout=5000)
    page = win.pages["Recipe Editor"]
    page.view.roiDrawn.emit(QRectF(100, 100, 80, 60))  # an ROI not saved: the Try judges the recipe as edited
    recipe = copy.deepcopy(page.edited_recipe)
    before = _stored(ctx)
    assert page.try_checks.isHidden()
    page.view.setFocus()
    QTest.keyClick(page.view, Qt.Key.Key_T, CTRL)
    qtbot.waitUntil(lambda: page.test_verdict.text().startswith("Try result:"), timeout=60000)

    assert offered == [last]
    res = ctx.inspector(BOARD, recipe=recipe).inspect(ctx.load_image(last))
    t = page.try_checks
    rows = [[t.item(r, c).text() for c in (0, 5)] for r in range(t.rowCount())]
    assert rows[:-1] == [[check_text(c)[0], c.verdict] for c in res.checks] and rows[-1][0] == "Inspection time (ms)"
    assert any(c.source == "ROI" for c in res.checks), "the ROI not saved was judged"
    assert t.isVisible() and res.verdict in page.test_verdict.text()
    ng = QColor(theme.NG_COLOR).name()
    defects = {(d.x, d.y, d.w, d.h) for d in res.defects}
    _wheel(page.view.viewport(), -1)
    assert defects and defects <= {box for box, (colour, _) in _pens(page.view).items() if colour == ng}
    assert _stored(ctx) == before, "a Try stores nothing"


def test_req_rcp_003_the_board_offered_is_the_newest_not_archived_of_its_board_model(
    trained_ctx: AppContext, ng_board: Path
) -> None:
    """`AppContext.last_board`, the board Try Recipe… offers first (Q23): none before an inspection, then the board
    inspected last under the board model, never one of another board model, and none once its records are archived."""
    ctx = trained_ctx
    assert ctx.last_board(BOARD) is None
    ok = next((ng_board.parent.parent / "ok").glob("*.png"))
    for path in (ng_board, ok):
        ctx.inspect_file(BOARD, str(path))
    assert Path(ctx.last_board(BOARD) or "").name == ok.name and ctx.last_board("OTHER") is None
    ctx.db.execute("UPDATE inspections SET archived=1")  # what the retention sweep does to an old record
    assert ctx.last_board(BOARD) is None
