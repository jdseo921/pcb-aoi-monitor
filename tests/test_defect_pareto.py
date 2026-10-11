"""Logs & Export's Defect types tab (REQ-LOG-008): the listed records' defects by type, most first, with each type's
share, the running total and the false calls among the records holding it, as an AOI line's defect Pareto reports
them. The records are written through the data layer with made-up defects, so nothing here is an accuracy."""

from __future__ import annotations

from typing import Any, cast

import pytest
from PySide6.QtCore import Qt
from pytestqt.qtbot import QtBot

from aoi.core.services import DEFECT, FALSE_CALL, AppContext
from aoi.data import db as db_module
from aoi.ui import theme
from aoi.ui.main_window import MainWindow
from aoi.ui.pages.base import row_key
from aoi.ui.pages.logs import BAR_COLUMN, RECORDS_TAB, TYPES_TAB, LogsPage
from tests.conftest import listed
from tests.screens.test_sizes_and_contrast import GRAPHIC_RATIO, _ratio


def _record(ctx: AppContext, result: str, *types: str) -> int:
    """An NG, WARN or OK record of board model B holding one defect of each of `types`, in order."""
    rec = {"board_model": "B", "result": result, "operator": "kim", "image_path": f"{result}.png",
           "model_version": "v1.0", "recipe_rev": 1, "view": "Top", "score": 0.5}  # fmt: skip
    box = {"score": 0.9, "side": "Top", "x": 1, "y": 1, "w": 4, "h": 4}
    return ctx.db.add_inspection(rec, [{"no": n, "type": t, **box} for n, t in enumerate(types, 1)])


def _line(ctx: AppContext) -> dict[str, int]:
    """Four records: an NG board with three opens and a short, an NG board with one open later reviewed as a false
    call, a WARN board with two spurs, and an OK board with none."""
    ctx.ensure_board_model("B")
    return {
        "ng": _record(ctx, "NG", "Open Circuit", "Open Circuit", "Short Circuit", "Open Circuit"),
        "false": _record(ctx, "NG", "Open Circuit"),
        "warn": _record(ctx, "WARN", "Spur", "Spur"),
        "ok": _record(ctx, "OK"),
    }


def _counts(rows: list[dict[str, Any]]) -> list[tuple[str, int, int, int, int]]:
    return [(r["type"], r["defects"], r["boards"], r["reviewed"], r["false_calls"]) for r in rows]


def test_req_log_008_defect_types_count_the_given_records_most_first_with_their_false_calls(
    ctx: AppContext, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Per type: its defects, the records holding one, and of those the ones reviewed and the false calls; most first,
    ties by name; each type's share of every defect counted and the running total, ending at 1. Only the records given
    count, any number of them: two per query here, so the counts add up across queries as they do 500 at a time."""
    ids = _line(ctx)
    ctx.review_result(ids["false"], FALSE_CALL, "Dust on the board")
    ctx.review_result(ids["warn"], DEFECT)
    monkeypatch.setattr(db_module, "IN_CHUNK", 2)
    rows = ctx.defect_pareto(ids.values())
    assert _counts(rows) == [("Open Circuit", 4, 2, 1, 1), ("Spur", 2, 1, 1, 0), ("Short Circuit", 1, 1, 0, 0)]
    assert [(r["share"], r["cumulative"]) for r in rows] == [(4 / 7, 4 / 7), (2 / 7, 6 / 7), (1 / 7, 1.0)]
    assert _counts(ctx.defect_pareto([ids["warn"], ids["ok"]])) == [("Spur", 2, 1, 1, 0)]
    assert ctx.defect_pareto([ids["ok"]]) == [] and ctx.defect_pareto([]) == []
    tie = [_record(ctx, "NG", "Spur"), _record(ctx, "NG", "Mousebite")]
    assert [r["type"] for r in ctx.defect_pareto(tie)] == ["Mousebite", "Spur"]  # one defect each: by name


def _cells(page: LogsPage) -> list[list[Any]]:
    t = page.type_table
    cell = Qt.ItemDataRole.DisplayRole
    return [[t.item(r, c).data(cell) for c in range(t.columnCount())] for r in range(t.rowCount())]


def _counted(qtbot: QtBot, page: LogsPage) -> None:
    qtbot.waitUntil(lambda: page.counting is None, timeout=30000)


def _colours(page: LogsPage, row: int, column: int) -> set[str]:
    """The colours drawn in a cell of the Defect types table."""
    t = page.type_table
    image = t.viewport().grab(t.visualItemRect(t.item(row, column))).toImage()
    return {image.pixelColor(x, y).name() for x in range(image.width()) for y in range(image.height())}


def test_req_log_008_the_defect_types_tab_counts_the_listed_records_and_follows_the_filter_and_reviews(
    qtbot: QtBot, ctx: AppContext
) -> None:
    """Two tabs, Records and Defect types. Defect types counts the records listed, most first: per type its defects,
    the records holding it, how many of those were reviewed and how many as a false call, the running total and the
    share, and beside it a bar as long as the type's defects against the most, in a column of its own, so that no text
    is drawn on it (#390's CI), in a colour that reads at 3:1 on the rows in both themes; a tooltip says it in a
    sentence. It counts only when shown, and again when Filter lists other records and when a review is saved, and says
    why it is empty."""
    ids = _line(ctx)
    ctx.review_result(ids["warn"], DEFECT)
    win = MainWindow(ctx)
    qtbot.addWidget(win)
    win.resize(1920, 1080)  # the whole table in view, its bars drawn
    win.show()
    qtbot.waitExposed(win)
    win.set_user("operator")  # every role reads it, as every role views the history
    win.navigate("Logs & Export")
    page = cast(LogsPage, win.pages["Logs & Export"])
    listed(qtbot, page)
    assert [page.tabs.tabText(i) for i in range(page.tabs.count())] == ["Records", "Defect types"]
    assert page.tabs.currentIndex() == RECORDS_TAB and page.counting is None  # counted only when shown
    headers = [page.type_table.horizontalHeaderItem(c).text() for c in range(page.type_table.columnCount())]
    assert headers == ["Defect type", "Defects", "Records", "Reviewed", "False calls", "Cumulative", "Share", ""]

    page.tabs.setCurrentIndex(TYPES_TAB)
    _counted(qtbot, page)
    assert _cells(page) == [
        ["Open Circuit", 4, 2, 0, 0, "57.1 %", "57.1 %", ""],
        ["Spur", 2, 1, 1, 0, "85.7 %", "28.6 %", ""],
        ["Short Circuit", 1, 1, 0, 0, "100.0 %", "14.3 %", ""],
    ]
    bars = [page.type_table.item(r, BAR_COLUMN).data(Qt.ItemDataRole.UserRole) for r in range(3)]
    assert bars == [1.0, 0.5, 0.25]  # against the most defects, Open Circuit's 4
    assert all(theme.ACCENT in _colours(page, r, BAR_COLUMN) for r in range(3))  # drawn, in its own column
    assert not any(theme.ACCENT in _colours(page, r, c) for r in range(3) for c in range(BAR_COLUMN))
    for tokens in (theme.TOKENS, theme.PRESENTER):  # the rows' two grounds, in the production and presenter themes
        assert min(_ratio(theme.ACCENT, tokens[ground]) for ground in ("BG_DEEP", "BG_ALT")) >= GRAPHIC_RATIO
    assert page.type_table.item(1, 0).toolTip() == (
        "Spur: 2 defect(s), 28.6 % of those listed, on 1 record(s); 1 of them reviewed, 0 as a false call"
    )
    assert not page.types_empty.isVisibleTo(page)

    page.result.setCurrentIndex(page.result.findData("NG"))
    page.refresh()  # Filter: the NG records alone
    _counted(qtbot, page)
    assert _cells(page) == [
        ["Open Circuit", 4, 2, 0, 0, "80.0 %", "80.0 %", ""],
        ["Short Circuit", 1, 1, 0, 0, "100.0 %", "20.0 %", ""],
    ]

    page.tabs.setCurrentIndex(RECORDS_TAB)
    page.table.selectRow(next(r for r in range(page.table.rowCount()) if int(row_key(page.table, r)) == ids["false"]))
    page.tabs.setCurrentIndex(TYPES_TAB)
    _counted(qtbot, page)
    page.review.store_review(FALSE_CALL, "Dust on the board")  # F11 on the record selected on Records
    qtbot.waitUntil(lambda: page.review.saving is None and page.counting is None, timeout=30000)
    assert _cells(page)[0][:5] == ["Open Circuit", 4, 2, 1, 1]

    page.result.setCurrentIndex(page.result.findData("OK"))
    page.refresh()
    _counted(qtbot, page)
    assert page.type_table.rowCount() == 0 and page.types_empty.isVisibleTo(page)
    assert page.types_empty.heading.text() == "No defects"
    assert page.types_empty.sentence.text() == "None of the 1 listed record(s) holds a defect."
    page.d_from.setDate(page.d_to.date().addDays(1))  # from tomorrow: no record
    page.refresh()
    _counted(qtbot, page)
    assert (page.types_empty.heading.text(), page.types_empty.sentence.text()) == (
        "No records",
        "Widen the dates or the filters.",
    )
