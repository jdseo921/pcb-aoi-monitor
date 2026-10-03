"""The Qt shell opens offscreen (stage S05): page tests can run in CI on Windows and Linux.

pytest-qt supplies `qtbot`; conftest.py sets QT_QPA_PLATFORM=offscreen before Qt is imported.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, cast

import cv2
import numpy as np
import pytest
from PySide6.QtCore import QDate, QItemSelectionModel
from pytestqt.qtbot import QtBot

from aoi import times
from aoi.core.services import AppContext
from aoi.ui.main_window import MainWindow
from aoi.ui.pages.base import cell_text
from aoi.ui.pages.compare import ComparePage
from aoi.ui.pages.logs import LogsPage

PAGES = [
    "Home",
    "Inspection",
    "Compare",
    "Training",
    "AI Model Test",
    "Recipe Editor",
    "3D Profile",
    "Logs & Export",
    "Settings",
]


def test_main_window_shows_every_page_offscreen(qtbot: QtBot, ctx: AppContext) -> None:
    win = MainWindow(ctx)
    qtbot.addWidget(win)
    win.show()
    assert list(win.pages) == PAGES
    assert win.ctx.role == "Admin", "an empty workspace opens as Admin so the first user can set up"
    for title in PAGES:
        win.navigate(title)
        assert win.stack.currentWidget() is win.pages[title], title


def test_operator_cannot_open_an_admin_page(qtbot: QtBot, ctx: AppContext) -> None:
    win = MainWindow(ctx)
    qtbot.addWidget(win)
    win.set_user("operator")
    win.navigate("Settings")
    assert win.stack.currentWidget() is win.pages["Home"]
    assert win.statusBar().currentMessage() == "Settings needs the Admin role"


def _record(iid: int, overlay: str | None = None) -> dict[str, Any]:
    """A Logs & Export row as `AppContext.inspections` returns it, with the keys the page reads."""
    return {
        "id": iid, "time": "2026-10-01T05:05:00+00:00", "board_model": "TBOX-A1", "result": "NG", "defect_count": 1,
        "score": 0.5, "operator": "operator", "view": "Top", "image_path": f"board{iid}.png", "overlay_path": overlay,
    }  # fmt: skip


def _logs(qtbot: QtBot, ctx: AppContext, monkeypatch: pytest.MonkeyPatch, records: list[dict[str, Any]]) -> LogsPage:
    """Logs & Export listing `records`, which the test may change before the next Filter."""
    win = MainWindow(ctx)
    qtbot.addWidget(win)
    monkeypatch.setattr(ctx, "inspections", lambda *a, **k: list(records))
    assert win.navigate("Logs & Export")
    return cast(LogsPage, win.pages["Logs & Export"])


def test_logs_date_filter_never_raises_at_the_edges(qtbot: QtBot, ctx: AppContext) -> None:
    """#174: the From and To boxes stop at 2000-01-01 and 2100-12-31, and a day past what the clock can convert is no
    bound on its side, so Filter at the widest dates lists the records in place of an unexpected-error dialog."""
    assert times.local_day_bounds_utc("2026-10-01", "9999-12-31")[1] is None  # past datetime.max: no upper bound
    win = MainWindow(ctx)
    qtbot.addWidget(win)
    assert win.navigate("Logs & Export")
    page = cast(LogsPage, win.pages["Logs & Export"])
    page.d_from.setDate(QDate(1752, 9, 14))  # the earliest and latest days a QDateEdit takes by default
    page.d_to.setDate(QDate(9999, 12, 31))
    assert (page.d_from.date(), page.d_to.date()) == (QDate(2000, 1, 1), QDate(2100, 12, 31))
    with qtbot.captureExceptions() as raised:
        page.refresh()
    assert raised == []


def test_switch_user_refreshes_the_page_on_screen(qtbot: QtBot, ctx: AppContext) -> None:
    """#174: Switch User on a page the new role may still open shows that page again for the new role: an Engineer
    can export from Logs & Export at once, and an Operator on Compare no longer sees Save to Recipe enabled."""
    win = MainWindow(ctx)
    qtbot.addWidget(win)
    win.set_user("operator")
    assert win.navigate("Logs & Export")
    logs = cast(LogsPage, win.pages["Logs & Export"])
    assert not logs.btn_csv.isEnabled()
    win.set_user("engineer")
    assert win.stack.currentWidget() is logs
    assert logs.btn_csv.isEnabled() and logs.btn_img.isEnabled() and logs.btn_arch.isEnabled()
    assert win.navigate("Compare")
    compare = cast(ComparePage, win.pages["Compare"])
    assert compare.btn_save.isEnabled()
    win.set_user("operator")
    assert win.stack.currentWidget() is compare and not compare.btn_save.isEnabled()


def test_logs_preview_survives_a_narrower_filter(
    qtbot: QtBot, ctx: AppContext, monkeypatch: pytest.MonkeyPatch
) -> None:
    """#174: with two rows selected, Filter (or Archive) leaving fewer rows never has the preview read a row the refresh
    is replacing; before, it raised StopIteration, shown as an unexpected-error dialog."""
    records = [_record(3), _record(2), _record(1)]
    page = _logs(qtbot, ctx, monkeypatch, records)
    selection = page.table.selectionModel()
    rows = QItemSelectionModel.SelectionFlag.Select | QItemSelectionModel.SelectionFlag.Rows
    for row in (0, 2):  # Ctrl-click on the first and the third row
        selection.select(page.table.model().index(row, 0), rows)
    assert len(selection.selectedRows()) == 2
    records[:] = [_record(2)]
    with qtbot.captureExceptions() as raised:
        page.refresh()
    assert raised == [] and page.table.rowCount() == 1


def test_logs_preview_shows_only_the_selected_records_overlay(
    qtbot: QtBot, ctx: AppContext, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """#174: the picture is the selected record's overlay or none: a record whose overlay file is gone, an empty
    selection and Filter each clear it, so another board's defects never show beside a record."""
    overlay = tmp_path / "overlay.png"
    assert cv2.imwrite(str(overlay), np.full((40, 60, 3), 200, np.uint8))
    page = _logs(qtbot, ctx, monkeypatch, [_record(2, str(tmp_path / "gone.png")), _record(1, str(overlay))])
    row_of = {int(cell_text(page.table, i, 0)): i for i in range(page.table.rowCount())}
    page.table.selectRow(row_of[1])
    assert page.view._pix is not None
    page.table.selectRow(row_of[2])  # its overlay file was deleted, or the workspace was copied without results/
    assert page.view._pix is None and page.view._placeholder.isVisible()
    page.table.selectRow(row_of[1])
    page.table.clearSelection()
    assert page.view._pix is None
    page.table.selectRow(row_of[1])
    page.refresh()
    assert page.view._pix is None
