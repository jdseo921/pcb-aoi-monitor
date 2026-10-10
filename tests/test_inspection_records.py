"""REQ-INSP-008 and REQ-INSP-010 on the Inspection page: a saved record names the engine that inspected the board and
the view it was inspected under."""

from __future__ import annotations

import csv
from pathlib import Path

import pytest
from PySide6.QtWidgets import QFileDialog, QMessageBox
from pytestqt.qtbot import QtBot

from aoi.core.services import AppContext
from aoi.hal import VIEWS
from aoi.ui.pages.base import cell_text
from tests.conftest import listed
from tests.test_req_done_in_v01 import BOARD, _inspect_one, _window


def test_req_insp_008_a_saved_result_names_the_model_version_and_recipe_revision_that_produced_it(
    qtbot: QtBot, trained_ctx: AppContext, ng_board: Path
) -> None:
    """The record written as the result arrives names the engine that produced it, by version and by UUID: the board
    model's active model and its latest recipe revision. (Since S25b every result is saved as it arrives; before, Save
    Result after the page was reopened wrote the record without the model version and recipe revision.)"""
    win = _window(qtbot, trained_ctx, "Operator")
    page = _inspect_one(qtbot, win, ng_board)
    (row,) = trained_ctx.inspections(board_model=BOARD)
    active = trained_ctx.active_model(BOARD)
    assert active is not None
    rev, _ = trained_ctx.recipe(BOARD)
    (latest,) = [h for h in trained_ctx.recipe_history(BOARD) if h["revision"] == rev]
    assert (row["board_model"], row["model_version"], row["recipe_rev"]) == (BOARD, active["version"], rev)
    assert (row["model_uuid"], row["recipe_uuid"]) == (active["uuid"], latest["uuid"])
    assert page.last is not None and row["result"] == page.last.verdict


def test_req_insp_010_view_stored_and_exported(
    qtbot: QtBot, trained_ctx: AppContext, ng_board: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The view picked on Inspection stays with the result: on the record (new), in its stored result as Compare reads
    it back (#246: only the column was checked), on every defect and in the Side column (as in v0.1), in the Logs &
    Export table's View column and in the CSV export (new)."""
    win = _window(qtbot, trained_ctx, "Admin")  # only an Admin exports (Q58, #151)
    page = win.pages["Inspection"]
    page.view_combo.setCurrentIndex(VIEWS.index("Side"))
    _inspect_one(qtbot, win, ng_board)
    assert page.last is not None and page.last.view == "Side"
    assert cell_text(page.table, 0, 3) == "Side"  # the Side column of the defect list
    (row,) = trained_ctx.inspections(board_model=BOARD)
    assert row["view"] == "Side" and {d["side"] for d in trained_ctx.defects_for(row["id"])} == {"Side"}
    stored = trained_ctx.inspection_result(row["id"])
    assert stored is not None and stored.view == "Side"
    logs = win.pages["Logs & Export"]
    win.navigate("Logs & Export")
    listed(qtbot, logs)
    headers = [logs.table.horizontalHeaderItem(c).text() for c in range(logs.table.columnCount())]
    assert cell_text(logs.table, 0, headers.index("View")) == "Side"  # wherever a later redesign puts the column
    out = tmp_path / "inspections.csv"
    monkeypatch.setattr(QFileDialog, "getSaveFileName", staticmethod(lambda *a, **k: (str(out), "CSV (*.csv)")))
    monkeypatch.setattr(QMessageBox, "question", staticmethod(lambda *a, **k: QMessageBox.StandardButton.Yes))
    logs.export_csv()  # on a pool thread since #194: the files are there once the status line says so
    qtbot.waitUntil(lambda: win.statusBar().currentMessage().startswith("Exported"), timeout=30000)
    with out.open(encoding="utf-8-sig", newline="") as f:
        (exported,) = list(csv.DictReader(f))
    assert list(exported)[:4] == ["id", "time", "board_model", "view"] and exported["view"] == "Side"
