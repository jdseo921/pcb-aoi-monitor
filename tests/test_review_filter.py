"""Logs & Export's Review filter (REQ-LOG-009, ADR 0013): the records listed by their review on the line, so an
Engineer finds a board model's false calls, its real defects, or the NG and WARN boards no one has reviewed yet. The
records are written through the data layer with made-up verdicts, so nothing here is an accuracy."""

from __future__ import annotations

from pathlib import Path
from typing import cast

import pytest
from PySide6.QtWidgets import QFileDialog
from pytestqt.qtbot import QtBot

from aoi.core.services import DEFECT, FALSE_CALL, AppContext
from aoi.data.db import NOT_REVIEWED
from aoi.ui.main_window import MainWindow
from aoi.ui.pages.logs import LogsPage
from tests.conftest import listed


def _record(ctx: AppContext, result: str) -> int:
    rec = {"board_model": "B", "result": result, "operator": "kim", "image_path": f"{result}.png",
           "model_version": "v1.0", "recipe_rev": 1, "view": "Top", "score": 0.5}  # fmt: skip
    return ctx.db.add_inspection(rec, [])


def _line(ctx: AppContext) -> dict[str, int]:
    """An NG board reviewed as a false call, one reviewed as a real defect, an NG and a WARN board not reviewed, and an
    OK board, which is never reviewed."""
    ctx.ensure_board_model("B")
    ids = {name: _record(ctx, result) for name, result in
           (("false", "NG"), ("real", "NG"), ("ng", "NG"), ("warn", "WARN"), ("ok", "OK"))}  # fmt: skip
    ctx.review_result(ids["false"], FALSE_CALL, "Dust on the board")
    ctx.review_result(ids["real"], DEFECT)
    return ids


def test_req_log_009_the_review_filter_lists_false_calls_real_defects_or_the_boards_not_reviewed(
    ctx: AppContext,
) -> None:
    """False call and Real defect list the records reviewed so; Not reviewed lists the NG and WARN records with no
    review, never an OK one; no review filter lists every record; and it combines with the Result filter."""
    ids = _line(ctx)
    by = {review: {r["id"] for r in ctx.inspections(review=review)} for review in (None, FALSE_CALL, DEFECT)}
    assert by == {None: set(ids.values()), FALSE_CALL: {ids["false"]}, DEFECT: {ids["real"]}}
    assert {r["id"] for r in ctx.inspections(review=NOT_REVIEWED)} == {ids["ng"], ids["warn"]}
    assert {r["id"] for r in ctx.inspections(result="WARN", review=NOT_REVIEWED)} == {ids["warn"]}
    assert ctx.inspections(result="OK", review=FALSE_CALL) == []


def test_req_log_009_logs_lists_by_review_resets_it_and_audits_it_with_an_export(
    qtbot: QtBot, ctx: AppContext, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The Review filter sits after Result: All, Not reviewed, Real defect, False call. Filter lists the records it
    names, Reset Filters puts it back to All, and an export audits it with the rest of the filter (REQ-LOG-002)."""
    ids = _line(ctx)
    win = MainWindow(ctx)
    qtbot.addWidget(win)
    win.set_user("admin")
    win.navigate("Logs & Export")
    page = cast(LogsPage, win.pages["Logs & Export"])
    listed(qtbot, page)
    f = page.review_filter
    assert [f.itemText(i) for i in range(f.count())] == ["All", "Not reviewed", "Real defect", "False call"]
    assert {r["id"] for r in page.rows} == set(ids.values())

    f.setCurrentIndex(f.findData(FALSE_CALL))
    page.refresh()  # Filter
    assert [r["id"] for r in page.rows] == [ids["false"]]
    assert page.listed.review == FALSE_CALL
    out = tmp_path / "history.csv"
    monkeypatch.setattr(QFileDialog, "getSaveFileName", staticmethod(lambda *a, **k: (str(out), "")))
    page.export_csv()
    qtbot.waitUntil(lambda: page._bg is None, timeout=30000)
    entries = ctx.audit_entries(action="export.csv")  # the records' file and their checks' file
    assert entries and {(e["after"]["filter"]["review"], e["after"]["records"]) for e in entries} == {(FALSE_CALL, 1)}

    f.setCurrentIndex(f.findData(NOT_REVIEWED))
    page.refresh()
    assert {r["id"] for r in page.rows} == {ids["ng"], ids["warn"]}
    page.reset_filters()
    assert f.currentIndex() == 0 and {r["id"] for r in page.rows} == set(ids.values())
