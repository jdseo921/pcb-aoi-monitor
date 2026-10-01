"""REQ-INSP-008 on the Inspection page: a saved record names the engine that inspected the board."""

from __future__ import annotations

from pathlib import Path

import pytest
from PySide6.QtWidgets import QFileDialog
from pytestqt.qtbot import QtBot

from aoi.core.services import AppContext
from tests.test_req_done_in_v01 import BOARD, _inspect_one, _window


def test_req_insp_008_a_saved_result_names_the_model_version_and_recipe_revision_that_produced_it(
    qtbot: QtBot, trained_ctx: AppContext, ng_board: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Save Result after the page was left and reopened: reopening drops the page's cached engine, and before S22b the
    record was then written without the model version and recipe revision, under whatever board model was current."""
    win = _window(qtbot, trained_ctx, "Operator")
    page = win.pages["Inspection"]
    page.autosave.setChecked(False)
    _inspect_one(qtbot, win, ng_board)
    assert trained_ctx.inspections(board_model=BOARD) == [], "autosave is off, so nothing is saved yet"
    win.navigate("Home")
    win.navigate("Inspection")
    assert page.inspector is None and page.last is not None, "reopening the page drops its cached engine"
    out = tmp_path / "saved.png"
    monkeypatch.setattr(QFileDialog, "getSaveFileName", staticmethod(lambda *a, **k: (str(out), "PNG (*.png)")))
    page.save_result()
    assert out.exists()
    (row,) = trained_ctx.inspections(board_model=BOARD)
    active = trained_ctx.active_model(BOARD)
    assert active is not None
    rev, _ = trained_ctx.recipe(BOARD)
    assert (row["board_model"], row["model_version"], row["recipe_rev"]) == (BOARD, active["version"], rev)
    assert row["result"] == page.last.verdict
