"""REQ-CMP-005, the Save half (S28d): on Compare, Save to Recipe, the page's one blue primary for an Engineer or Admin,
makes the thresholds an Engineer tried the board model's recipe. It is off while nothing differs from the recipe, so a
revision that changes nothing is never stored, and the Recipe Editor and Inspection pick the revision up as they do one
the Recipe Editor saves (sketch docs/sketches/compare-decision-table.md, Controls and Rules applied)."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import pytest
from PySide6.QtWidgets import QMessageBox
from pytestqt.qtbot import QtBot

from aoi.core.services import REQUIRED_ROLE, AppContext
from aoi.ui.pages.compare import ComparePage
from aoi.ui.pages.inspection import InspectionPage
from aoi.ui.pages.recipe_editor import RecipeEditorPage
from tests.test_compare_reevaluate import _pass_every_check, _stored_on_compare
from tests.test_compare_stored import save_to_recipe
from tests.test_req_done_in_v01 import BOARD, _inspect_one, _window


def test_req_cmp_005_save_to_recipe_is_off_while_no_threshold_differs(
    qtbot: QtBot, trained_ctx: AppContext, ng_board: Path
) -> None:
    """Save to Recipe is off while the form holds the recipe's thresholds, as the engine judges by them (an AI score
    threshold stored as 0 is none, as the form shows it): on with one changed, off again with it set back to the
    recipe's, a tick cleared included, and off once the thresholds are saved, as the form then holds the recipe, or once
    a revision saved elsewhere holds the value tried; a revision that changes nothing is never stored, not even by the
    page's action called anyway."""
    ctx = trained_ctx
    win, compare, _ = _stored_on_compare(qtbot, ctx, ng_board, "Engineer")
    zero = ctx.recipe(BOARD)[1]
    zero.anomaly_threshold = 0.0  # as a recipe may hold it: the engine reads 0 as no override, and so does the form
    ctx.save_recipe(zero)
    win.navigate("Inspection")
    win.navigate("Compare")  # the form takes the revision up
    rev, recipe = ctx.recipe(BOARD)
    assert compare.form_revision == (BOARD, rev) and recipe.anomaly_threshold == 0.0
    assert not compare.btn_save.isEnabled(), "nothing differs from the recipe"
    compare.save_recipe()  # called anyway
    assert ctx.recipe(BOARD)[0] == rev, "no revision that changes nothing"
    edits: dict[str, tuple[Callable[[], None], Callable[[], None]]] = {  # a threshold changed, then set back
        "diff": (lambda: compare.diff_thr.setValue(46), lambda: compare.diff_thr.setValue(recipe.diff_threshold)),
        "area": (lambda: compare.min_area.setValue(41), lambda: compare.min_area.setValue(recipe.min_defect_area)),
        "ssim": (lambda: compare.ssim_min.setValue(0.79), lambda: compare.ssim_min.setValue(recipe.ssim_min)),
        "regions": (lambda: compare.max_regions.setValue(1), lambda: compare.max_regions.setValue(0)),
        "tick": (lambda: compare.ai_thr.tick.setChecked(True), lambda: compare.ai_thr.tick.setChecked(False)),
    }
    assert (recipe.diff_threshold, recipe.min_defect_area, recipe.ssim_min, recipe.max_diff_regions) == (45, 40, 0.8, 0)
    for name, (change, back) in edits.items():
        change()
        assert compare.btn_save.isEnabled(), name
        back()
        assert not compare.btn_save.isEnabled(), (name, "set back to the recipe's")
    assert ctx.recipe(BOARD)[0] == rev
    compare.diff_thr.setValue(255)
    assert save_to_recipe(compare) == rev + 1 and ctx.recipe(BOARD)[1].diff_threshold == 255
    assert not compare.btn_save.isEnabled(), "the form holds the recipe now"
    compare.min_area.setValue(77)  # tried, and then the same value saved elsewhere, on the Recipe Editor say
    same = ctx.recipe(BOARD)[1]
    same.min_defect_area = 77
    ctx.save_recipe(same)
    win.navigate("Inspection")
    win.navigate("Compare")
    assert compare.form_revision == (BOARD, rev + 2) and not compare.btn_save.isEnabled(), "nothing differs from it"


def test_req_cmp_005_a_revision_saved_on_compare_judges_the_next_boards(
    qtbot: QtBot, trained_ctx: AppContext, ng_board: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The revision Save to Recipe stores is the one the Recipe Editor shows when it is opened again and the one
    Inspection judges its next board by, as for a revision the Recipe Editor saves: Inspection judged a board by the
    revision before and keeps its engine, and its next board names the new revision and gets the verdict it gives."""
    ctx = trained_ctx
    monkeypatch.setattr(QMessageBox, "information", staticmethod(lambda *_: QMessageBox.StandardButton.Ok))
    win = _window(qtbot, ctx, "Engineer")
    inspection = _inspect_one(qtbot, win, ng_board)
    assert isinstance(inspection, InspectionPage) and inspection.last_id is not None
    first = ctx.inspection(inspection.last_id)
    assert first is not None and first["result"] == "NG"
    win.navigate("Recipe Editor")
    editor = win.pages["Recipe Editor"]
    assert isinstance(editor, RecipeEditorPage) and editor.rev == first["recipe_rev"]
    win.navigate("Compare")
    compare = win.pages["Compare"]
    assert isinstance(compare, ComparePage)
    qtbot.waitUntil(lambda: ctx.jobs.idle() and compare._bg is None, timeout=20000)
    _pass_every_check(compare)
    rev = save_to_recipe(compare)
    assert rev == first["recipe_rev"] + 1
    win.navigate("Recipe Editor")
    assert (editor.rev, editor.diff.value(), editor.ssim.value(), editor.ai_thr.override()) == (rev, 255, 0.0, 500.0)
    win.navigate("Inspection")
    last = inspection.last_id
    inspection._set_queue([ng_board])
    inspection.next_board()
    qtbot.waitUntil(lambda: inspection.last_id != last and ctx.jobs.idle(), timeout=30000)
    assert inspection.last_id is not None
    record = ctx.inspection(inspection.last_id)
    want = ctx.inspect(BOARD, ctx.load_image(str(ng_board)))  # by the latest revision
    assert record is not None and (record["recipe_rev"], record["result"]) == (rev, want.verdict) != (rev, "NG")


def test_req_cmp_005_save_to_recipe_is_off_with_no_board_model(
    qtbot: QtBot, ctx: AppContext, dialogs: list[tuple[str, str]]
) -> None:
    """With no board model in the header there is no recipe for a threshold to differ from: Save to Recipe stays off
    whatever the form holds, so AOI-SET-014 never opens from it; with the board model back, a threshold changed turns
    it on."""
    ctx.ensure_board_model(BOARD)
    win = _window(qtbot, ctx, "Engineer")
    compare = win.pages["Compare"]
    assert isinstance(compare, ComparePage) and win.navigate("Compare")
    win._on_board_model("")
    compare.diff_thr.setValue(compare.diff_thr.value() + 1)
    compare.btn_save.click()
    assert not compare.btn_save.isEnabled() and dialogs == []
    win._on_board_model(BOARD)
    compare.diff_thr.setValue(compare.diff_thr.value() + 1)
    assert compare.btn_save.isEnabled()


def test_req_cmp_005_save_to_recipe_follows_the_role_its_service_requires(
    qtbot: QtBot, ctx: AppContext, monkeypatch: pytest.MonkeyPatch, dialogs: list[tuple[str, str]]
) -> None:
    """Save to Recipe follows the role `AppContext.save_recipe`'s @requires names (REQUIRED_ROLE), never one written out
    on the page (#241): raised to Admin, an Engineer's stays off with a threshold changed and the page's action called
    anyway is refused with AOI-USR-001 naming that role; after Switch User to the Admin, it is on."""
    ctx.ensure_board_model(BOARD)
    monkeypatch.setitem(REQUIRED_ROLE, "save_recipe", "Admin")
    win = _window(qtbot, ctx, "Engineer")
    compare = win.pages["Compare"]
    assert isinstance(compare, ComparePage) and win.navigate("Compare")
    compare.diff_thr.setValue(compare.diff_thr.value() + 1)
    assert not compare.btn_save.isEnabled(), "an Engineer under Admin"
    compare.save_recipe()
    refused = "Changing recipes needs the Admin role.\n\nSign in as a user with that role, or ask one to do it."
    assert dialogs == [("AOI-USR-001 Not allowed for this role", refused)] and ctx.recipe(BOARD)[0] == 1
    win.set_user("admin")
    assert compare.btn_save.isEnabled(), "after Switch User to the Admin"
