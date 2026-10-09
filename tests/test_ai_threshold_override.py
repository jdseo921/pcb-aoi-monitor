"""REQ-TRN-015 (S28c, 2 of 3): the AI score threshold on the Recipe Editor names the AI model's calibrated value beside
a tick and shows it greyed until the tick is set; ticked, the field holds the board model's override, and clearing
the tick restores the calibrated value. With no calibrated value to name, the note under the tick says why, with
AOI-TRN-012 for a calibration that cannot be read (sketch recipe-editor.md, Thresholds tab: "AI threshold [▢ override
5.69]"). Compare's field, and the test that tick and note never widen the window, come with the next commit."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from PySide6.QtWidgets import QMessageBox
from pytestqt.qtbot import QtBot

from aoi.core.inspector import InspectionResult
from aoi.core.services import AppContext
from aoi.ui import theme
from aoi.ui.main_window import MainWindow
from aoi.ui.pages.recipe_editor import RecipeEditorPage
from aoi.ui.widgets.ai_threshold import AiThresholdField
from tests.test_req_done_in_v01 import BOARD, _window

OWN = "Set my own value"  # the tick's text with no calibrated value to name
UNTRAINED = "No AI model is trained yet: there is no calibrated value."
INACTIVE = "No AI model version is active: there is no calibrated value."


def _ai_threshold(res: InspectionResult) -> float:
    """The threshold the AI check of `res` was judged by."""
    return next(c.threshold for c in res.checks if c.source == "AI")


def _judged_by(ctx: AppContext, board: Path) -> float:
    """The threshold the AI check of a new inspection of `board` judges by."""
    return _ai_threshold(ctx.inspect_file(BOARD, str(board), save=False))


def _shows_calibrated(field: AiThresholdField, value: float) -> bool:
    """The tick clear and naming `value`, which the greyed field shows; the recipe keeps no threshold of its own."""
    return (
        field.tick.text() == f"Override {value:.3f}"
        and not field.tick.isChecked()
        and not field.field.isEnabled()
        and field.field.isVisibleTo(field)
        and field.field.value() == round(value, 3)
        and field.override() is None
        and field.note.isHidden()
    )


def _editor(qtbot: QtBot, ctx: AppContext, monkeypatch: pytest.MonkeyPatch) -> tuple[MainWindow, RecipeEditorPage]:
    """A window signed in as the Engineer, on the Recipe Editor; Save's "Saved revision" box answers itself."""
    monkeypatch.setattr(QMessageBox, "information", staticmethod(lambda *a: QMessageBox.StandardButton.Ok))
    win = _window(qtbot, ctx, "Engineer")
    editor = win.pages["Recipe Editor"]
    assert isinstance(editor, RecipeEditorPage) and win.navigate("Recipe Editor")
    return win, editor


def _save_override(ctx: AppContext, value: float | None) -> None:
    recipe = ctx.recipe(BOARD)[1]
    recipe.anomaly_threshold = value
    ctx.save_recipe(recipe)


def test_req_trn_015_override_and_clear(
    qtbot: QtBot, trained_ctx: AppContext, ng_board: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """On the Recipe Editor the field shows the AI model's calibrated value, greyed, until the tick is set. The override
    saved is a new revision that judges the next inspection, and its audit entry names the board model, the user and
    the value before and after; clearing the tick shows the calibrated value again, and that save is a new revision
    audited the same way. A save that keeps the override writes no entry of it. With no override, a newly trained AI
    model's calibrated value judges, and the field names it when the page is shown again."""
    ctx = trained_ctx
    cal, model = ctx.calibrated_threshold(BOARD), ctx.active_model(BOARD)
    assert cal is not None and model is not None and cal == json.loads(model["metrics"])["image_threshold"]
    win, editor = _editor(qtbot, ctx, monkeypatch)
    assert _shows_calibrated(editor.ai_thr, cal)
    editor.ai_thr.tick.ensurePolished()  # the stylesheet's size class F sets its minimum
    assert editor.ai_thr.tick.minimumHeight() >= theme.FIELD_H, "the tick is as tall as the field beside it"
    rev, override, engineer = ctx.recipe(BOARD)[0], round(cal * 2, 3), ctx.db.user_uuid("engineer")
    editor.ai_thr.tick.setChecked(True)
    assert editor.ai_thr.field.isEnabled() and editor.ai_thr.override() == cal, "ticking starts from it, exactly"
    editor.ai_thr.field.setValue(override)
    editor.save()
    (entry,) = ctx.audit_entries(action="recipe.ai_threshold")
    assert (entry["user_uuid"], entry["before"]["override"], entry["after"]["override"]) == (engineer, None, override)
    assert ctx.recipe(BOARD)[0] == rev + 1 and ctx.recipe(BOARD)[1].anomaly_threshold == override
    assert _judged_by(ctx, ng_board) == pytest.approx(override)
    assert editor.ai_thr.override() == override and editor.ai_thr.field.isEnabled(), "the saved override shows"
    editor.ai_thr.tick.setChecked(False)
    assert _shows_calibrated(editor.ai_thr, cal), "clearing the tick restores the calibrated value"
    editor.save()
    entry = ctx.audit_entries(action="recipe.ai_threshold")[0]
    assert (entry["user_uuid"], entry["before"]["override"], entry["after"]) == (
        engineer, override, {"revision": rev + 2, "override": None, "threshold": cal, "ai_model": model["version"],
                             "calibrated": cal}
    )  # fmt: skip
    assert ctx.recipe(BOARD)[1].anomaly_threshold is None and _judged_by(ctx, ng_board) == pytest.approx(cal)
    editor.save()  # nothing of the AI score threshold changes: the revision's own entry, none of the override
    assert ctx.recipe(BOARD)[0] == rev + 3 and len(ctx.audit_entries(action="recipe.ai_threshold")) == 2
    ctx.train(BOARD, epochs=1, image_size=32)  # a newly trained AI model, calibrated afresh
    newer = ctx.calibrated_threshold(BOARD)
    assert newer is not None and newer != cal and _judged_by(ctx, ng_board) == pytest.approx(newer)
    win.navigate("Home")
    win.navigate("Recipe Editor")
    assert _shows_calibrated(editor.ai_thr, newer), "the field names the AI model that judges now"


def test_req_trn_015_a_calibration_that_cannot_be_read_says_so_with_a_code(
    qtbot: QtBot,
    trained_ctx: AppContext,
    monkeypatch: pytest.MonkeyPatch,
    dialogs: list[tuple[str, str]],
) -> None:
    """An active AI model whose registry row holds no usable calibration (AOI-TRN-012) is said in the note under the
    tick, with the code and what to do, on the Recipe Editor, never as "no AI model" and with no dialog; an override
    can still be set and saved. With AI model versions but none active, and with none trained, the note says which, and
    the field shows once the tick is set; with no board model, the tick names nothing and no note shows."""
    ctx = trained_ctx
    model = ctx.active_model(BOARD)
    assert model is not None
    metrics = {**json.loads(model["metrics"]), "image_threshold": "damaged"}
    ctx.db.execute("UPDATE models SET metrics=? WHERE uuid=?", (json.dumps(metrics), model["uuid"]))  # by hand
    win, editor = _editor(qtbot, ctx, monkeypatch)
    field = editor.ai_thr
    assert field.tick.text() == OWN and not field.tick.isChecked() and field.field.isHidden()
    assert not field.note.isHidden() and field.note.text().startswith("AOI-TRN-012 ")
    assert "train again or activate another version on Training" in field.note.text()
    editor.ai_thr.tick.setChecked(True)
    assert editor.ai_thr.field.isVisibleTo(editor.ai_thr) and editor.ai_thr.field.isEnabled()
    editor.ai_thr.field.setValue(4.0)
    editor.save()
    assert ctx.recipe(BOARD)[1].anomaly_threshold == 4.0
    ctx.db.execute("UPDATE models SET active=0 WHERE board_model=?", (BOARD,))
    _save_override(ctx, None)
    for none, said in (("active", INACTIVE), ("trained", UNTRAINED)):
        editor.load()
        assert editor.ai_thr.tick.text() == OWN and editor.ai_thr.note.text() == said, none
        assert not editor.ai_thr.note.isHidden() and editor.ai_thr.field.isHidden(), none
        assert editor.ai_thr.override() is None, none
        editor.ai_thr.tick.setChecked(True)
        assert editor.ai_thr.field.isVisibleTo(editor.ai_thr) and editor.ai_thr.field.isEnabled(), none
        ctx.db.execute("DELETE FROM models WHERE board_model=?", (BOARD,))  # none trained, for the next turn
    editor.show_calibrated(editor.ai_thr, None)  # no board model, as Compare can have: nothing to name, nor why
    assert editor.ai_thr.tick.text() == OWN and editor.ai_thr.note.isHidden()
    assert not dialogs, "the field says it; no dialog when a page is shown"


def test_req_trn_015_the_field_keeps_what_the_recipe_holds(qtbot: QtBot) -> None:
    """`changed` fires when the tick moves and when a ticked value is edited, not when a calibrated value is shown; an
    override the field cannot show as it is (more decimals than 3, or outside 0.001 to 10000) is given back as the
    recipe holds it until it is edited, so opening and saving a recipe never changes it, and ticking by hand starts
    from the calibrated value to every decimal. 0, which the engine reads as no override, shows as none."""
    field = AiThresholdField(("Override {value}", "None to name"))
    qtbot.addWidget(field)
    said: list[None] = []
    field.changed.connect(lambda: said.append(None))
    field.show_calibrated(3.0631147)
    assert not said and field.field.value() == 3.063 and field.tick.text() == "Override 3.063"
    field.tick.setChecked(True)
    assert field.override() == 3.0631147, "ticked by hand: the calibrated value, exactly"
    field.field.setValue(5.0)
    assert len(said) == 2 and field.override() == 5.0
    field.set_override(None)
    assert field.override() is None and field.field.value() == 3.063 and not field.tick.isChecked()
    for kept, shown in ((2.99837, 2.998), (20000.0, 10000.0), (0.0004, 0.001), (12345.6789, 10000.0)):
        field.set_override(kept)
        assert field.override() == kept and field.field.value() == shown, f"{kept} kept until edited"
    field.field.setValue(2.5)
    assert field.override() == 2.5
    field.tick.setChecked(False)
    field.tick.setChecked(True)
    assert field.override() == 3.0631147, "ticked again: from the calibrated value the clear restored"
    field.set_override(0.0)
    assert field.override() is None and not field.tick.isChecked()
    field.show_calibrated(None, "AOI-TRN-012 What happened. What to do.")
    assert field.tick.text() == "None to name" and field.note.text() == "AOI-TRN-012 What happened. What to do."
    assert field.field.isHidden() and not field.note.isHidden()
    field.show_calibrated(None)
    assert field.tick.text() == "None to name" and field.note.isHidden()
