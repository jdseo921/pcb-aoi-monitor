"""Tables filled by `fill_table` (aoi/ui/pages/base.py): what a row carries stays with the row when the table sorts."""

from __future__ import annotations

from PySide6.QtCore import Qt
from pytestqt.qtbot import QtBot

from aoi.ui.pages.base import cell_item, cell_text, fill_table, make_table

PATHS = {k: f"/boards/board-{k}.png" for k in (1, 2, 3)}


def test_issue_111_a_row_keeps_its_tooltip_and_colour_when_the_table_sorts(qtbot: QtBot) -> None:
    """`setSortingEnabled(True)` sorts at once, by the header's indicator, so a tooltip set afterwards by data order
    landed on whichever row the sort had moved there (the Training samples and the AI Model Test results)."""
    t = make_table(["ID", "File"])
    qtbot.addWidget(t)
    t.sortItems(0, Qt.SortOrder.DescendingOrder)
    ids = sorted(PATHS)
    fill_table(t, [[k, f"board-{k}.png"] for k in ids], [None, "#ff0000", None], [PATHS[k] for k in ids])
    shown = [int(cell_text(t, i, 0)) for i in range(t.rowCount())]
    assert shown == [3, 2, 1], "the table is sorted as soon as the rows are in"
    for i, k in enumerate(shown):
        assert [cell_item(t, i, c).toolTip() for c in range(2)] == [PATHS[k], PATHS[k]]
        assert (cell_item(t, i, 0).background().color().name() == "#ff0000") == (k == 2)
