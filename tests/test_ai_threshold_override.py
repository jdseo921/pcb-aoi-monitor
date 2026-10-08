"""REQ-TRN-015 (S28c): the AI score threshold on the Recipe Editor and on Compare names the AI model's calibrated
value beside a tick and shows it greyed until the tick is set; ticked, the field holds the board model's override, and
clearing the tick restores the calibrated value. Inspection, Compare's tried thresholds, Re-evaluate and AI Model Test
judge by the same threshold. With no calibrated value to name, the note under the tick says why, with AOI-TRN-012 for a
calibration that cannot be read; tick and note never widen the window (sketches recipe-editor.md, Thresholds tab, and
compare-decision-table.md, "AI threshold override")."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest
from PySide6.QtWidgets import QApplication, QFormLayout, QMessageBox, QTabWidget, QWidget
from pytestqt.qtbot import QtBot

from aoi.core.inspector import InspectionResult, ai_check
from aoi.core.services import AppContext
from aoi.ui import theme
from aoi.ui.main_window import MainWindow
from aoi.ui.pages.compare import ComparePage
from aoi.ui.pages.inspection import InspectionPage
from aoi.ui.pages.model_test import ModelTestPage
from aoi.ui.pages.recipe_editor import RecipeEditorPage
from aoi.ui.widgets.ai_threshold import AiThresholdField
from tests.test_compare_stored import _table
from tests.test_req_done_in_v01 import BOARD, _inspect_one, _window

OWN = "Set my own value"  # the tick's text with no calibrated value to name
UNTRAINED = "No AI model is trained yet: there is no calibrated value."
INACTIVE = "No AI model version is active: there is no calibrated value."
MIN_WIDTH = 1616  # the window's minimum width before the tick (S28b): the review found 1729 to 1929 px with it


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


def test_req_trn_015_inspection_compare_reevaluate_and_model_test_judge_by_one_threshold(
    qtbot: QtBot, trained_ctx: AppContext, ng_board: Path, tmp_path: Path
) -> None:
    """With an override saved, a board inspected on Inspection, the thresholds Compare tries on a stored result
    (Re-evaluate) and on a board it inspects, and an AI Model Test run all judge the AI check by the override; with it
    cleared, all by the AI model's calibrated value. Compare's field shows what the recipe holds, and gives back an
    override with more decimals than it shows as the recipe holds it, so Compare judges by the value the rest do."""
    ctx = trained_ctx
    cal = ctx.calibrated_threshold(BOARD)
    assert cal is not None
    folder = tmp_path / "run"
    (folder / "ng").mkdir(parents=True)
    shutil.copy(ng_board, folder / "ng" / ng_board.name)
    win = _window(qtbot, ctx, "Engineer")
    compare, tester = win.pages["Compare"], win.pages["AI Model Test"]
    assert isinstance(compare, ComparePage) and isinstance(tester, ModelTestPage)
    for override in (round(cal * 1.5, 3) + 0.0004, None):  # 4 decimals: the field shows 3
        _save_override(ctx, override)
        want = override or cal
        inspection = win.pages["Inspection"]
        assert isinstance(inspection, InspectionPage)
        inspection.last = None  # the board of the last turn is not this one's
        _inspect_one(qtbot, win, ng_board)
        assert inspection.last is not None and inspection.last_id is not None
        assert _ai_threshold(inspection.last) == pytest.approx(want), "Inspection"
        win.navigate("Compare")
        assert compare.ai_thr.override() == override and compare.ai_thr.tick.isChecked() == (override is not None)
        rec = ctx.inspection(inspection.last_id)
        assert rec is not None
        compare.show_stored(inspection.last_id)
        qtbot.waitUntil(lambda: compare.loaded and compare._bg is None, timeout=10000)
        tried = ctx.re_evaluate(rec["uuid"], compare._form_recipe(BOARD))  # what Re-evaluate asks
        assert _ai_threshold(tried) == pytest.approx(want), "Re-evaluate"
        compare.set_test(str(ng_board))  # a board Compare inspects with the thresholds it tries
        qtbot.waitUntil(lambda: compare._bg is None and compare.res is not None, timeout=30000)
        assert compare.res is not None and _ai_threshold(compare.res) == pytest.approx(want), "Compare"
        ai_score = next(c.value for c in compare.res.checks if c.source == "AI")
        win.navigate("AI Model Test")
        tester.folder = str(folder)
        tester.run()
        qtbot.waitUntil(lambda: bool(tester.rows) and ctx.jobs.idle(), timeout=30000)
        (row,) = tester.rows
        assert row["score"] == pytest.approx(round(ai_score / want, 3)), "AI Model Test"
        tester._clear_run()


def test_req_trn_015_compare_names_the_value_that_judges_its_board(
    qtbot: QtBot, trained_ctx: AppContext, ng_board: Path
) -> None:
    """Compare's tick tries an override, and its clear the calibrated value. The value named is the active AI model's
    for a board Compare inspects, and for a stored result that of the AI model that judged it, which Re-evaluate applies
    (ADR 0006 decision 2); a newly trained AI model is named when the page is shown again, and when a fresh board starts
    after a stored result, which it then judges. Setting the tick, or editing the value while ticked, drops what
    Re-evaluate showed, as any other threshold does. An Operator never sees the field."""
    ctx = trained_ctx
    cal = ctx.calibrated_threshold(BOARD)
    assert cal is not None
    ctx.inspect_file(BOARD, str(ng_board))
    (rec,) = ctx.inspections(board_model=BOARD)
    win = _window(qtbot, ctx, "Engineer")
    compare = win.pages["Compare"]
    assert isinstance(compare, ComparePage) and win.navigate("Compare")
    qtbot.waitUntil(ctx.jobs.idle, timeout=10000)
    assert _shows_calibrated(compare.ai_thr, cal) and compare._form_recipe(BOARD).anomaly_threshold is None
    compare.ai_thr.tick.setChecked(True)
    compare.ai_thr.field.setValue(cal + 1)
    assert compare._form_recipe(BOARD).anomaly_threshold == round(cal + 1, 3)
    compare.ai_thr.tick.setChecked(False)
    assert _shows_calibrated(compare.ai_thr, cal) and compare._form_recipe(BOARD).anomaly_threshold is None
    ctx.train(BOARD, epochs=1, image_size=32)  # a newer AI model, calibrated afresh, judges the next board
    newer = ctx.calibrated_threshold(BOARD)
    assert newer is not None and round(newer, 3) != round(cal, 3)
    win.navigate("Home")
    win.navigate("Compare")
    assert _shows_calibrated(compare.ai_thr, newer), "the active AI model judges a board inspected here"
    compare.show_stored(rec["id"])
    qtbot.waitUntil(lambda: compare.loaded and compare._bg is None, timeout=10000)
    assert _shows_calibrated(compare.ai_thr, cal), "the AI model that judged the stored result"
    res = ctx.inspection_result(rec["id"])
    assert res is not None
    ai_check = compare._check_text(next(c for c in res.checks if c.source == "AI"))[0]
    compare.re_evaluate()
    qtbot.waitUntil(compare.would_be.isVisible, timeout=10000)
    assert [r[3] for r in _table(compare) if r[0] == ai_check] == [round(cal, 4)], "Re-evaluate applies it"
    compare.ai_thr.tick.setChecked(True)  # another AI score threshold: what Re-evaluate showed no longer applies
    assert not compare.would_be.isVisible() and not compare.tried, "setting the tick drops what was tried"
    compare.re_evaluate()
    qtbot.waitUntil(compare.would_be.isVisible, timeout=10000)
    assert compare.tried
    compare.ai_thr.field.setValue(cal + 2)
    assert not compare.would_be.isVisible() and not compare.tried, "an edit while ticked drops it too"
    compare.ai_thr.tick.setChecked(False)
    compare.set_test(str(ng_board))  # a fresh board after the stored result: the active AI model judges it
    qtbot.waitUntil(lambda: compare._bg is None and compare.res is not None, timeout=30000)
    assert compare.stored is None and _shows_calibrated(compare.ai_thr, newer), "named when a fresh board starts"
    assert _ai_threshold(compare.res) == pytest.approx(newer), "the value named judges it"
    win.navigate("Home")  # a rollback on Training as the fresh board shows, which is not inspected again (review)
    ctx.activate_model(next(m["id"] for m in ctx.models(BOARD) if m["uuid"] == rec["model_uuid"]))
    win.navigate("Compare")  # so only on_show names the value of the AI model activated
    shown = compare.ai_thr.tick.text().endswith(f" {cal:.3f}") and compare.ai_thr.field.value() == round(cal, 3)
    assert shown and compare.stored is None and compare._bg is None, "named when the page is shown again"
    win.set_user("operator")
    assert not compare.ai_thr.isVisibleTo(win) and not win.navigate("Recipe Editor")


def test_req_trn_015_compare_names_no_value_of_an_ai_model_that_judged_nothing(
    qtbot: QtBot, trained_ctx: AppContext, ng_board: Path
) -> None:
    """A stored result judged with the recipe's AI check off still names the AI model active then (#246), which judged
    nothing and whose calibration Re-evaluate never applies to it: on it, Compare's tick names the active AI model's
    value, which judges the next board, as on a fresh board, when it shows and when the page is shown again, a newer AI
    model trained meanwhile included (review); a stored result that AI model judged names that AI model's value."""
    ctx = trained_ctx
    cal, recipe = ctx.calibrated_threshold(BOARD), ctx.recipe(BOARD)[1]
    for use_ai in (False, True):  # the first record judged with the AI check off, the second by the AI model
        recipe.use_ai = use_ai
        ctx.save_recipe(recipe)
        ctx.inspect_file(BOARD, str(ng_board))
    off, ran = sorted(ctx.inspections(board_model=BOARD), key=lambda r: int(r["id"]))
    assert off["model_uuid"] == ran["model_uuid"] is not None, "the AI-off record names the AI model active then"
    win = _window(qtbot, ctx, "Engineer")
    compare = win.pages["Compare"]
    assert isinstance(compare, ComparePage) and win.navigate("Compare")
    compare.show_stored(off["id"])  # shown before the training run (review), which on_show alone names then
    qtbot.waitUntil(lambda: compare.loaded and compare._bg is None, timeout=10000)
    win.navigate("Home")
    ctx.train(BOARD, epochs=1, image_size=32)  # a newer AI model, calibrated afresh, judges the next board
    newer = ctx.calibrated_threshold(BOARD)
    assert cal is not None and newer is not None and round(newer, 3) != round(cal, 3)
    win.navigate("Compare")
    shown = compare.ai_thr.tick.text().endswith(f" {newer:.3f}") and compare.ai_thr.field.value() == round(newer, 3)
    assert shown and compare.stored is not None and compare.stored["id"] == off["id"], "named when shown again"
    for rec, check, named in ((off, "OFF", newer), (ran, "RAN", cal), (off, "OFF", newer)):
        compare.show_stored(rec["id"])
        qtbot.waitUntil(lambda: compare.loaded and compare._bg is None, timeout=10000)
        assert ai_check(compare.res) == check and _shows_calibrated(compare.ai_thr, named), (check, "shown")
        win.navigate("Home")
        win.navigate("Compare")
        assert compare.stored is not None and compare.stored["id"] == rec["id"], "the stored result is still shown"
        assert _shows_calibrated(compare.ai_thr, named), (check, "the page shown again")


def test_req_trn_015_a_calibration_that_cannot_be_read_says_so_with_a_code(
    qtbot: QtBot,
    trained_ctx: AppContext,
    monkeypatch: pytest.MonkeyPatch,
    dialogs: list[tuple[str, str]],
) -> None:
    """An active AI model whose registry row holds no usable calibration (AOI-TRN-012) is said in the note under the
    tick, with the code and what to do, on Compare and on the Recipe Editor, never as "no AI model" and with no dialog;
    an override can still be set and saved. With AI model versions but none active, and with none trained, the note
    says which, and the field shows once the tick is set; with no board model, the tick names nothing and no note
    shows."""
    ctx = trained_ctx
    model = ctx.active_model(BOARD)
    assert model is not None
    metrics = {**json.loads(model["metrics"]), "image_threshold": "damaged"}
    ctx.db.execute("UPDATE models SET metrics=? WHERE uuid=?", (json.dumps(metrics), model["uuid"]))  # by hand
    win, editor = _editor(qtbot, ctx, monkeypatch)
    compare = win.pages["Compare"]
    assert isinstance(compare, ComparePage)
    for title, field in (("Compare", compare.ai_thr), ("Recipe Editor", editor.ai_thr)):
        win.navigate(title)
        assert field.tick.text() == OWN and not field.tick.isChecked() and field.field.isHidden(), title
        assert not field.note.isHidden() and field.note.text().startswith("AOI-TRN-012 "), title
        assert "train again or activate another version on Training" in field.note.text(), title
    win.navigate("Recipe Editor")
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
    win.navigate("Compare")
    win._on_board_model("")  # no board model: nothing to name, and nothing to say why
    assert compare.ai_thr.tick.text() == OWN and compare.ai_thr.note.isHidden()
    assert not dialogs, "the field says it; no dialog when a page is shown"


def _without_rows(fields: list[AiThresholdField]) -> int:
    """The window's minimum width with the form rows of `fields` and their notes hidden, as if their pages had no AI
    score threshold; each row is shown again as it was."""
    win = fields[0].window()
    rows: list[QWidget] = []
    for field in fields:
        form = field.parentWidget().layout()
        assert isinstance(form, QFormLayout)
        rows += [w for w in (form.labelForField(field), field, field.note) if w is not None and not w.isHidden()]
    for w in rows:
        w.hide()
    QApplication.processEvents()
    width = win.minimumSizeHint().width()
    for w in rows:
        w.show()
    QApplication.processEvents()
    return width


@pytest.mark.parametrize("state", ["calibrated", "unreadable", "none-trained"])
def test_req_trn_015_tick_and_note_never_widen_the_window(qtbot: QtBot, trained_ctx: AppContext, state: str) -> None:
    """The tick's words are short in every state and its note wraps in a row as wide as the form, so the AI score
    threshold never widens the window: its minimum width stays 1616 px, as before the tick, and the same as with the AI
    score threshold's rows hidden on the Recipe Editor and Compare, cleared and ticked (the review found 1929 px, wider
    than a 1920 px screen). At 1600 x 900 and at 1920 x 1080 each page's note is as tall as its text at its width, so
    what to do shows whole, no row around it is squeezed to make room (on Compare the "why" box gives way first), and
    the tick is as tall as the fields beside it (size class F)."""
    ctx = trained_ctx
    model = ctx.active_model(BOARD)
    assert model is not None
    if state == "unreadable":
        metrics = {**json.loads(model["metrics"]), "image_threshold": "damaged"}
        ctx.db.execute("UPDATE models SET metrics=? WHERE uuid=?", (json.dumps(metrics), model["uuid"]))
    elif state == "none-trained":
        ctx.db.execute("DELETE FROM models WHERE board_model=?", (BOARD,))
    win = _window(qtbot, ctx, "Engineer")
    editor, compare = win.pages["Recipe Editor"], win.pages["Compare"]
    assert isinstance(editor, RecipeEditorPage) and isinstance(compare, ComparePage)
    pages = {"Recipe Editor": editor.ai_thr, "Compare": compare.ai_thr}
    tabs = editor.findChild(QTabWidget)
    assert tabs is not None
    tabs.setCurrentWidget(editor.ai_thr.parentWidget())  # the Thresholds tab, where the field is
    for title in pages:  # each page built and shown once
        win.navigate(title)
    for ticked in (False, True):
        for field in pages.values():
            field.tick.setChecked(ticked)
            assert field.field.isVisibleTo(field) == (ticked or state == "calibrated"), (state, ticked)
        QApplication.processEvents()
        width = win.minimumSizeHint().width()
        assert width <= MIN_WIDTH, (state, ticked, width, "the AI score threshold widens the window")
        assert width == _without_rows([*pages.values()]), (state, ticked, width, "its rows widen the window")
    for size in ((1600, 900), (1920, 1080)):
        win.resize(*size)
        for title, field in pages.items():
            win.navigate(title)
            QApplication.processEvents()
            assert win.height() == size[1] and win.width() <= max(size[0], MIN_WIDTH), (size, win.size())
            note = field.note
            assert note.isHidden() == (state == "calibrated") == (note.text() == ""), (title, state)
            if not note.isHidden():
                assert note.height() >= note.heightForWidth(note.width()), (title, size, note.height(), note.text())
            rows = field.parentWidget()  # on Windows Compare's panel was too short for its rows and squeezed the note
            assert rows.height() >= rows.heightForWidth(rows.width()), (title, size, rows.height(), "a row squeezed")
            assert field.tick.height() >= theme.FIELD_H, (title, state, size)


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
