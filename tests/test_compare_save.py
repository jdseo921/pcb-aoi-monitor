"""REQ-CMP-005, the Save half (S28d): on Compare, Save to Recipe (Ctrl+S, the page's one blue primary, Engineer and
Admin) makes the thresholds an Engineer tried the board model's recipe. An inline sheet, never a dialog, lists each
threshold that changes, before -> after, and asks for a reason, which is required; Save Revision stores a new recipe
revision through AppContext with an audit entry of before, after, user, time and reason. Nothing is stored until then,
and Save to Recipe is off while nothing differs from the recipe. The Recipe Editor and Inspection pick the revision up
as they do one the Recipe Editor saves (sketch docs/sketches/compare-decision-table.md, Controls and Rules applied)."""

from __future__ import annotations

import copy
import threading
from collections.abc import Callable, Iterator
from datetime import datetime, timedelta
from pathlib import Path

import pytest
from PySide6.QtCore import Qt
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import QApplication, QDialog, QMessageBox, QPushButton, QWidget
from pytestqt.qtbot import QtBot

from aoi.core.services import REQUIRED_ROLE, AppContext
from aoi.times import now_utc
from aoi.ui import theme
from aoi.ui.main_window import MainWindow
from aoi.ui.pages.compare import ComparePage
from aoi.ui.pages.inspection import InspectionPage
from aoi.ui.pages.recipe_editor import RecipeEditorPage
from tests.conftest import wrapped
from tests.test_compare_reevaluate import _pass_every_check, _press, _stored_on_compare, _walk
from tests.test_compare_stored import save_to_recipe
from tests.test_req_done_in_v01 import BOARD, _inspect_one, _save_recipe, _window

REASON = "Pixel noise from the new lighting"
SIGN_IN = "Sign in as a user with that role, or ask one to do it."  # AOI-USR-001's step


@pytest.fixture(autouse=True)
def _no_key_left_held() -> Iterator[None]:
    """Each test here lets go of the keys it pressed: Qt keeps a modifier held from one test to the next."""
    yield
    assert QGuiApplication.keyboardModifiers() == Qt.KeyboardModifier.NoModifier, "a key is still held"


def _press_save(qtbot: QtBot, win: MainWindow, compare: ComparePage) -> None:
    """Save to Recipe's key, Ctrl+S, as an Engineer presses it on the page, then let go."""
    key = compare.act_save.shortcut()[0]
    qtbot.keyClick(win, key.key(), key.keyboardModifiers())
    qtbot.keyRelease(win, key.key())


def _no_dialog(monkeypatch: pytest.MonkeyPatch) -> list[object]:
    """Every message box or dialog opened from here on, recorded in place of shown: the sheet is never one."""
    opened: list[object] = []

    def record(*args: object) -> QMessageBox.StandardButton:
        opened.append(args)
        return QMessageBox.StandardButton.Yes

    for name in ("question", "information", "warning"):
        monkeypatch.setattr(QMessageBox, name, staticmethod(record))
    monkeypatch.setattr(QMessageBox, "exec", record)
    monkeypatch.setattr(QDialog, "exec", record)
    return opened


def _note(revision: int) -> str:
    """The sheet's note under its lines of changes, naming the revision the save makes."""
    return f"Boards inspected after the save are judged by revision {revision}; stored results keep their verdicts."


def _stored(ctx: AppContext) -> tuple[object, ...]:
    """What Save Revision may store: the recipe revisions, the audit trail and the inspection records."""
    return ctx.recipe_history(BOARD), ctx.audit_entries(), ctx.inspections()


def test_req_cmp_005_save_creates_audited_revision(
    qtbot: QtBot,
    trained_ctx: AppContext,
    ng_board: Path,
    dialogs: list[tuple[str, str]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An Engineer tries two thresholds on a stored NG result, Re-evaluates and presses Ctrl+S: an inline sheet in place
    of the panel, no dialog, lists the two before -> after and asks for a reason; with none, or spaces only, Save
    Revision is off and Enter stores nothing, Ctrl+S and Ctrl+R in the open sheet do nothing and keep the reason typed,
    and until Save Revision is pressed nothing is stored at all. Then Enter stores revision n+1 with the thresholds
    tried and the rest of the recipe as it was, and one `recipe.save` audit entry names the user, the time (UTC, with
    its offset), the recipe before and after and the reason; the override set is audited as `recipe.ai_threshold` with
    that reason too. The stored result keeps its verdict and "Would be", the sheet closes, and Save to Recipe is off
    again, as the form now holds the recipe. The sheet's text and buttons keep the size and contrast rules, its labels
    are plain text, and the page keeps one blue primary. A threshold tried after the save opens a sheet that names the
    revision after it, which Compare left and shown again keeps open, reason and all: nothing was saved since."""
    ctx = trained_ctx
    win, compare, _ = _stored_on_compare(qtbot, ctx, ng_board, "Engineer")
    rev, before = ctx.recipe(BOARD)
    assert before.anomaly_threshold is None and before.diff_threshold != 255
    assert compare.btn_save.objectName() == "primary" and compare.act_save.shortcut().toString() == "Ctrl+S"
    assert not compare.btn_save.isEnabled() and not compare.act_save.isEnabled(), "nothing differs from the recipe"
    compare.diff_thr.setValue(255)
    compare.ai_thr.tick.setChecked(True)
    compare.ai_thr.field.setValue(7.0)
    assert compare.btn_save.isEnabled()
    _press(qtbot, win, compare)  # Re-evaluate: what the thresholds would give the stored result
    qtbot.waitUntil(lambda: compare.would_be.isVisible() and compare._trying is None, timeout=10000)
    stored, opened = _stored(ctx), _no_dialog(monkeypatch)
    _press_save(qtbot, win, compare)
    assert compare.sheet.isVisible() and compare.tryout.isHidden() and not compare.sheet.isWindow()
    assert compare.isAncestorOf(compare.sheet) and QApplication.activeModalWidget() is None
    assert dialogs == [] and opened == [], "no dialog, the sheet only"
    assert compare.sheet_heading.text() == f"Save these thresholds as revision {rev + 1} of the recipe of {BOARD}?"
    assert compare.sheet_note.text() == _note(rev + 1)
    labels = (compare.sheet_heading, compare.sheet_changes, compare.sheet_note)
    assert {w.textFormat() for w in labels} == {Qt.TextFormat.PlainText}, "a board model's name is never markup"
    assert compare.sheet_changes.text().splitlines() == [
        "AI score threshold: the AI model's calibrated value → 7.000",
        f"Pixel difference (0-255): {before.diff_threshold} → 255",
    ]
    assert compare.btn_confirm.text() == f"Save Revision {rev + 1}" and compare.btn_confirm.objectName() != "primary"
    assert [b for b in compare.findChildren(QPushButton) if b.objectName() == "primary"] == [compare.btn_save]
    assert compare.reason.hasFocus() and not compare.btn_confirm.isEnabled(), "a reason is required"
    found, seen = _walk(win, [w for w in [compare.sheet, *compare.sheet.findChildren(QWidget)] if w.isVisible()])
    assert not found and seen["buttons"] == 2 and seen["text"] >= 6, (found, seen)
    qtbot.keyClick(compare.reason, Qt.Key.Key_Return)  # Enter with no reason
    compare.reason.setText("   ")
    assert not compare.btn_confirm.isEnabled()
    qtbot.keyClick(compare.reason, Qt.Key.Key_Return)
    assert _stored(ctx) == stored and compare.sheet.isVisible(), "nothing is stored until Save Revision"
    earlier = {e["uuid"] for e in ctx.audit_entries()}
    t0 = now_utc()
    compare.reason.setText(f"  {REASON}  ")
    assert compare.btn_confirm.isEnabled() and not (compare.act_save.isEnabled() or compare.act_try.isEnabled())
    _press_save(qtbot, win, compare)  # Ctrl+S and Ctrl+R in the open sheet do nothing: the sheet keeps its reason
    _press(qtbot, win, compare)
    assert compare.reason.text() == f"  {REASON}  " and compare.sheet.isVisible() and compare._trying is None
    qtbot.keyClick(compare.reason, Qt.Key.Key_Return)
    t1 = now_utc()
    new_rev, after = ctx.recipe(BOARD)
    want = copy.deepcopy(before)
    want.diff_threshold, want.anomaly_threshold = 255, 7.0
    assert (new_rev, after) == (rev + 1, want), "the thresholds tried, the rest of the recipe as it was"
    entries = [e for e in ctx.audit_entries() if e["uuid"] not in earlier]
    assert sorted(e["action"] for e in entries) == ["recipe.ai_threshold", "recipe.save"]
    (saved,) = (e for e in entries if e["action"] == "recipe.save")
    assert saved["object_uuid"] == ctx.recipe_history(BOARD)[0]["uuid"]
    assert (saved["before"], saved["after"], saved["reason"]) == (before.to_dict(), after.to_dict(), REASON)
    assert (saved["user_uuid"], saved["role"]) == (ctx.db.user_uuid("engineer"), "Engineer")
    at = datetime.fromisoformat(saved["at_utc"])
    assert t0 <= saved["at_utc"] <= t1 and at.utcoffset() == timedelta(0), saved["at_utc"]
    (ai,) = (e for e in entries if e["action"] == "recipe.ai_threshold")
    assert (ai["reason"], ai["before"]["override"], ai["after"]["override"]) == (REASON, None, 7.0)
    assert compare.sheet.isHidden() and compare.tryout.isVisible() and compare.reason.text() == ""
    assert not compare.btn_save.isEnabled(), "the form holds the recipe now"
    assert compare.verdict.text() == theme.verdict_label("NG") and compare.would_be.isVisible()
    assert ctx.inspections() == stored[2], "the stored result keeps its verdict"
    assert win.statusBar().currentMessage() == f"Recipe saved as revision {rev + 1}"
    compare.min_area.setValue(77)  # tried after the save: the sheet lists it against the revision just saved
    compare.btn_save.click()
    assert compare.sheet_heading.text() == f"Save these thresholds as revision {rev + 2} of the recipe of {BOARD}?"
    assert (compare.btn_confirm.text(), compare.sheet_note.text()) == (f"Save Revision {rev + 2}", _note(rev + 2))
    compare.reason.setText(REASON)
    win.navigate("Inspection")  # away and back with no revision saved since the sheet opened: it stays as it was
    win.navigate("Compare")
    assert compare.sheet.isVisible() and compare.reason.text() == REASON and ctx.recipe(BOARD)[0] == rev + 1
    assert dialogs == [] and opened == [], "no AOI-RCP-004: nothing was saved since the sheet opened"


def test_req_cmp_005_save_to_recipe_is_for_an_engineer_or_admin(
    qtbot: QtBot, trained_ctx: AppContext, ng_board: Path, dialogs: list[tuple[str, str]]
) -> None:
    """An Operator has no Save to Recipe: the panel and the sheet are hidden, Ctrl+S opens nothing, the action stays off
    even with the hidden form changed, and the page's action called anyway refuses with AOI-USR-001 and opens nothing.
    An Engineer's sheet closes at any sign-in, an Admin's included, its reason gone and nothing stored, so a revision
    never carries another user's reason; the Admin then saves as an Engineer does, the audit entry naming the Admin.
    Should the role be gone when Save Revision is pressed, the service refuses with AOI-USR-001, nothing is stored, and
    the sheet keeps its reason."""
    ctx = trained_ctx
    win, compare, _ = _stored_on_compare(qtbot, ctx, ng_board, "Operator")
    history = ctx.recipe_history(BOARD)
    assert compare.tryout.isHidden() and compare.sheet.isHidden() and not compare.act_save.isEnabled()
    _press_save(qtbot, win, compare)
    assert compare.sheet.isHidden() and dialogs == []
    compare.diff_thr.setValue(255)  # the hidden form changed by code, not by the Operator: still off
    assert not compare.act_save.isEnabled() and not compare.btn_save.isEnabled()
    compare.save_recipe()
    refused = "Changing recipes needs the Engineer or Admin role."
    assert dialogs == [("AOI-USR-001 Not allowed for this role", f"{refused}\n\n{SIGN_IN}")]
    assert compare.sheet.isHidden() and ctx.recipe_history(BOARD) == history
    win.set_user("engineer")
    compare.diff_thr.setValue(255)
    _press_save(qtbot, win, compare)
    compare.reason.setText("an Engineer's reason")
    win.set_user("admin")
    assert compare.sheet.isHidden() and compare.tryout.isVisible() and compare.reason.text() == ""
    assert ctx.recipe_history(BOARD) == history and compare.diff_thr.value() == 255, "the Admin finds what was tried"
    compare.btn_save.click()
    compare.reason.setText("the Admin's reason")
    ctx.set_user("operator")  # the role gone behind the page's back: no sign-in reached it
    compare.btn_confirm.click()
    refused = "Saving a recipe needs the Engineer or Admin role."
    assert dialogs[-1] == ("AOI-USR-001 Not allowed for this role", f"{refused}\n\n{SIGN_IN}"), "the service's check"
    assert ctx.recipe_history(BOARD) == history and compare.sheet.isVisible()
    assert compare.reason.text() == "the Admin's reason"
    ctx.set_user("admin")
    compare.btn_confirm.click()
    entry, admin = ctx.audit_entries(action="recipe.save")[0], ctx.db.user_uuid("admin")
    assert (entry["user_uuid"], entry["role"], entry["reason"]) == (admin, "Admin", "the Admin's reason")
    assert ctx.recipe(BOARD)[0] == history[0]["revision"] + 1 and compare.sheet.isHidden() and len(dialogs) == 2


def test_req_cmp_005_nothing_is_stored_until_save_revision(
    qtbot: QtBot,
    trained_ctx: AppContext,
    ng_board: Path,
    monkeypatch: pytest.MonkeyPatch,
    dialogs: list[tuple[str, str]],
) -> None:
    """With all five thresholds tried, the sheet lists all five. Cancel and Esc close it and store nothing, the
    thresholds tried staying in the form and the focus going back to Save to Recipe. A board model change closes it too,
    the focus left where it was moved, in the header, as a run's end leaves it. Compare left and shown again keeps it
    open with its reason while no revision was saved; a revision saved on the Recipe Editor while it is open closes it,
    the form then holding that revision and AOI-RCP-004 saying, once Compare shows it, that nothing was saved and what
    to do (sketch, Errors)."""
    ctx = trained_ctx
    monkeypatch.setattr(QMessageBox, "information", staticmethod(lambda *_: QMessageBox.StandardButton.Ok))
    win, compare, _ = _stored_on_compare(qtbot, ctx, ng_board, "Engineer")
    stored = _stored(ctx)
    compare.diff_thr.setValue(255)
    compare.min_area.setValue(77)
    compare.ssim_min.setValue(0.5)
    compare.max_regions.setValue(3)
    compare.ai_thr.set_override(5.5)
    compare.btn_save.click()
    assert compare.sheet_changes.text().splitlines() == [  # each of the five, as its field shows it
        "AI score threshold: the AI model's calibrated value → 5.500",
        "Pixel difference (0-255): 45 → 255",
        "Minimum defect area (px): 40 → 77",
        "Similarity minimum (SSIM): 0.80 → 0.50",
        "Allowed difference regions: 0 → 3",
    ]
    compare.reason.setText("not saved")
    compare.btn_cancel.click()
    tried = (compare.ai_thr.override(), compare.min_area.value(), compare.ssim_min.value(), compare.max_regions.value())
    assert compare.sheet.isHidden() and compare.tryout.isVisible() and compare.diff_thr.value() == 255
    assert tried == (5.5, 77, 0.5, 3), "Cancel keeps the values tried"
    _press_save(qtbot, win, compare)
    assert compare.reason.text() == "", "Cancel let the reason go"
    qtbot.keyClick(compare.reason, Qt.Key.Key_Escape)
    assert compare.sheet.isHidden() and compare.btn_save.isEnabled() and _stored(ctx) == stored
    assert compare.btn_save.hasFocus(), "the focus back on the panel, not lost with the sheet"
    compare.btn_save.click()
    win.bm_combo.setFocus(Qt.FocusReason.MouseFocusReason)  # the Engineer goes to the header's board model
    win._on_board_model("")  # and clears it: the form follows it
    assert compare.sheet.isHidden() and not compare.act_save.isEnabled()
    assert QApplication.focusWidget() is win.bm_combo, "the focus stays where it was moved, as at a run's end"
    win._on_board_model(BOARD)
    compare.diff_thr.setValue(255)
    compare.btn_save.click()
    assert compare.sheet.isVisible() and _stored(ctx)[:2] == stored[:2]
    compare.reason.setText("kept")
    win.navigate("Inspection")  # away and back with no revision saved: the sheet stays, reason and all, no AOI-RCP-004
    win.navigate("Compare")
    assert compare.sheet.isVisible() and compare.reason.text() == "kept" and dialogs == []
    win.navigate("Recipe Editor")
    editor = win.pages["Recipe Editor"]
    assert isinstance(editor, RecipeEditorPage)
    editor.diff.setValue(30)
    _save_recipe(qtbot, editor)
    rev = ctx.recipe(BOARD)[0]
    win.navigate("Compare")
    assert compare.sheet.isHidden() and compare.diff_thr.value() == 30 and not compare.btn_save.isEnabled()
    what = (
        f"Revision {rev} of board model {BOARD} was saved after revision {rev - 1}, the one Save to Recipe listed its"
        f" changes against; saving them would undo revision {rev}, so the sheet closed and nothing was saved. Compare"
        f" now shows the thresholds of revision {rev}."
    )
    step = f"Try your thresholds again on revision {rev}, then press Save to Recipe."
    assert dialogs == [("AOI-RCP-004 Recipe saved while Save to Recipe was open", f"{what}\n\n{step}")]
    assert ctx.alarms()[0]["code"] == "AOI-RCP-004", "logged and alarmed as every coded error"
    assert len(ctx.recipe_history(BOARD)) == len(stored[0]) + 1, "the Recipe Editor's revision only"


def test_req_cmp_005_save_to_recipe_is_off_while_no_threshold_differs(
    qtbot: QtBot, trained_ctx: AppContext, ng_board: Path, dialogs: list[tuple[str, str]]
) -> None:
    """Save to Recipe is off while the form holds the recipe's thresholds, as the engine judges by them (an AI score
    threshold stored as 0 is none, as the form shows it): on with one changed, off again with it set back to the
    recipe's, a tick cleared included, and off once the thresholds are saved, as the form then holds the recipe, or once
    a revision saved elsewhere holds the value tried (with no sheet open, no AOI-RCP-004); a revision that changes
    nothing is never stored, and the page's action called anyway opens no sheet. The sheet lists no AI score threshold
    line while the recipe's is 0 and the form's none."""
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
    assert ctx.recipe(BOARD)[0] == rev and compare.sheet.isHidden(), "no revision, and no sheet, that changes nothing"
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
    compare.btn_save.click()  # an AI score threshold of 0 is none: the sheet lists Pixel difference alone
    assert compare.sheet_changes.text() == f"Pixel difference (0-255): {recipe.diff_threshold} → 255"
    compare.btn_cancel.click()
    assert save_to_recipe(compare) == rev + 1 and ctx.recipe(BOARD)[1].diff_threshold == 255
    assert not compare.btn_save.isEnabled(), "the form holds the recipe now"
    compare.min_area.setValue(77)  # tried, and then the same value saved elsewhere, on the Recipe Editor say
    same = ctx.recipe(BOARD)[1]
    same.min_defect_area = 77
    ctx.save_recipe(same)
    win.navigate("Inspection")
    win.navigate("Compare")
    assert compare.form_revision == (BOARD, rev + 2) and not compare.btn_save.isEnabled(), "nothing differs from it"
    assert dialogs == [], "no AOI-RCP-004 without a sheet open"


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
    rev = save_to_recipe(compare, "every check of the NG board within its threshold")
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


def test_req_cmp_005_save_revision_never_undoes_a_revision_saved_since(
    qtbot: QtBot, trained_ctx: AppContext, ng_board: Path, dialogs: list[tuple[str, str]]
) -> None:
    """A revision saved while the sheet is open and Compare stays shown (through AppContext, as another window's page
    would) is never undone: Save Revision then stores nothing, the sheet closes with its reason, the form takes that
    revision up, and AOI-RCP-004 says so, as when Compare is shown again (sketch, Errors: nothing was overwritten)."""
    ctx = trained_ctx
    win, compare, _ = _stored_on_compare(qtbot, ctx, ng_board, "Engineer")
    compare.diff_thr.setValue(255)
    compare.btn_save.click()
    compare.reason.setText(REASON)
    other = ctx.recipe(BOARD)[1]
    other.min_defect_area = 99
    rev = ctx.save_recipe(other, "saved elsewhere")
    compare.btn_confirm.click()
    assert ctx.recipe(BOARD) == (rev, other), f"revision {rev} stands"
    assert compare.sheet.isHidden() and compare.reason.text() == "" and compare.form_revision == (BOARD, rev)
    assert (compare.min_area.value(), compare.diff_thr.value()) == (99, other.diff_threshold)
    assert [title for title, _ in dialogs] == ["AOI-RCP-004 Recipe saved while Save to Recipe was open"]
    assert dialogs[0][1].startswith(f"Revision {rev} of board model {BOARD} was saved after revision {rev - 1}, ")


def test_req_cmp_005_any_board_opened_closes_the_sheet(
    qtbot: QtBot, trained_ctx: AppContext, ng_board: Path, dialogs: list[tuple[str, str]]
) -> None:
    """Any board opened on Compare, a stored result (Inspection's link, Last Inspected), the one shown included, or an
    image file, closes the sheet with nothing stored, so a reason typed before never goes with what is opened; the
    values tried stay. A record that cannot be read leaves the page as it was, the sheet and its reason included."""
    ctx = trained_ctx
    win, compare, iid = _stored_on_compare(qtbot, ctx, ng_board, "Engineer")
    stored = _stored(ctx)[:2]
    compare.diff_thr.setValue(255)
    compare.btn_save.click()
    compare.reason.setText("for the board shown")
    compare.show_stored(iid + 1)  # no record has that number: AOI-CMP-002
    assert [title for title, _ in dialogs] == ["AOI-CMP-002 Result has no stored decision table"]
    assert compare.sheet.isVisible() and compare.reason.text() == "for the board shown" and compare.stored is not None
    assert compare.stored["id"] == iid and compare.diff_thr.value() == 255, "the page as it was"
    win.open_stored(iid)  # the record shown, opened again by Inspection's link
    assert compare.sheet.isHidden() and compare.reason.text() == "" and compare.diff_thr.value() == 255
    qtbot.waitUntil(lambda: compare.loaded and compare._bg is None, timeout=10000)
    compare.btn_save.click()
    compare.reason.setText("for the board before")
    ctx.inspect_file(BOARD, str(ng_board))
    compare.show_stored(ctx.inspections(board_model=BOARD)[0]["id"])  # the newest record, as Inspection's link opens
    assert compare.sheet.isHidden() and compare.reason.text() == "" and compare.diff_thr.value() == 255
    qtbot.waitUntil(lambda: compare.loaded and compare._bg is None, timeout=10000)
    compare.btn_save.click()
    compare.reason.setText("for the board before")
    compare.set_test(str(ng_board))  # an image file, as Test Image… opens
    assert compare.sheet.isHidden() and compare.reason.text() == "" and compare.diff_thr.value() == 255
    qtbot.waitUntil(lambda: ctx.jobs.idle() and compare._bg is None, timeout=20000)
    assert _stored(ctx)[:2] == stored and len(dialogs) == 1


def test_req_cmp_005_the_sheet_names_values_as_the_recipe_holds_them(
    qtbot: QtBot, ctx: AppContext, dialogs: list[tuple[str, str]]
) -> None:
    """The sheet lists a value with more decimals than its field shows with every decimal the recipe holds, 15 here,
    never in exponent form, and the AI score threshold without an override as what the saved revision judges by, read
    from the board model's active AI model as the sheet opens, whatever the panel names (it names the AI model of when
    Compare was shown, or of a stored result): "none" with no AI model active, or one whose calibration cannot be read,
    as the audit entry of the save then names no threshold, else "the AI model's calibrated value"."""
    ctx.ensure_board_model(BOARD)
    recipe = ctx.recipe(BOARD)[1]
    recipe.anomaly_threshold, recipe.ssim_min = 1.23e-05, 0.812345678901234
    ctx.save_recipe(recipe)
    win = _window(qtbot, ctx, "Engineer")
    compare = win.pages["Compare"]
    assert isinstance(compare, ComparePage) and win.navigate("Compare")
    assert compare.ai_thr.tick.text() == "Set my own value" and compare.ai_thr.override() == 1.23e-05, "none named"
    compare.ai_thr.tick.setChecked(False)
    compare.btn_save.click()
    ssim = "Similarity minimum (SSIM): 0.812345678901234 → 0.81"
    assert compare.sheet_changes.text().splitlines() == ["AI score threshold: 0.0000123 → none", ssim]
    compare.btn_cancel.click()
    models = ctx.settings.root / "models"
    calibrated = {"image_threshold": 3.0, "pixel_threshold": 2.0}
    ctx.db.register_model(BOARD, "v1.0", str(models / "v1.pt"), calibrated, activate=True)  # as training, meanwhile
    compare.btn_save.click()
    assert compare.ai_thr.tick.text() == "Set my own value", "the panel names none until Compare is shown again"
    named = "AI score threshold: 0.0000123 → the AI model's calibrated value"
    assert compare.sheet_changes.text().splitlines() == [named, ssim]
    compare.reason.setText(REASON)
    compare.btn_confirm.click()
    assert ctx.audit_entries(action="recipe.ai_threshold")[0]["after"]["threshold"] == 3.0, "what the sheet named"
    compare.ai_thr.tick.setChecked(True)  # by hand: the panel names v1.0's value, which the field starts from
    ctx.db.register_model(BOARD, "v2.0", str(models / "v2.pt"), {}, activate=True)  # no calibration to read
    compare.btn_save.click()
    assert compare.ai_thr.tick.text() == "Override the AI model's value 3.000"
    assert compare.sheet_changes.text().splitlines() == ["AI score threshold: none → 3.000"]
    assert dialogs == []


def test_req_cmp_005_the_sheet_breaks_a_board_model_name_after_each_underscore_and_hyphen(
    qtbot: QtBot, ctx: AppContext
) -> None:
    """The sheet's heading names the board model with a break after each _ and each - and nowhere else, as Compare's
    file names (#245), so a name of 120 characters in short parts leaves the window within a 1920 px screen with the
    sheet open; its - comes before a digit, where Qt itself never breaks. Unbroken, it made the window 2305 px wide."""
    name = "PANEL_SIDE-1" * 10
    ctx.ensure_board_model(BOARD)
    win = _window(qtbot, ctx, "Engineer")
    ctx.ensure_board_model(name)
    win._reload_board_models(name)  # as "+ New board model" selects it
    compare = win.pages["Compare"]
    assert isinstance(compare, ComparePage) and win.navigate("Compare")
    compare.diff_thr.setValue(compare.diff_thr.value() + 1)
    compare.btn_save.click()
    for _ in range(10):  # each layout asks the one above it by a posted event: passes of the event loop, not time
        QApplication.processEvents()
    assert win.minimumSizeHint().width() <= 1920, "the open sheet asks for more than a 1920 px screen"
    assert compare.sheet_heading.text() == f"Save these thresholds as revision 2 of the recipe of {wrapped(name)}?"


def test_req_cmp_005_save_revision_while_a_stored_result_loads_leaves_the_focus_in_the_why_box(
    qtbot: QtBot, trained_ctx: AppContext, ng_board: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Save Revision pressed with Space while a stored result's pictures and maps still load, so Re-evaluate is off, and
    with nothing differing then Save to Recipe too: the focus goes to the "why" box, where a run puts it, so a
    second Space presses nothing. Qt passed it on to the header's board model, whose list a second Space opened. Once it
    has loaded, the focus goes on to Re-evaluate, as at a run's end, unless moved, to Show: say; an Operator's sign-in
    with the focus in the sheet while it loads closes the sheet first, the focus then in the "why" box, out of the panel
    the sign-in hides, where the load's end leaves it, Re-evaluate being off for an Operator (S28d, review). With
    nothing loading, it is there for no one to take back: Ctrl+R there once an Engineer signs in leaves it there, as
    a run started from the "why" box always does (S28d, review)."""
    ctx = trained_ctx
    win, compare, iid = _stored_on_compare(qtbot, ctx, ng_board, "Engineer")
    gate, judged_reference = threading.Event(), AppContext.judged_reference
    monkeypatch.setattr(AppContext, "judged_reference", lambda c, i: gate.wait(20) and judged_reference(c, i))
    compare.diff_thr.setValue(255)
    compare.show_stored(iid)  # its pictures and maps held on the pool thread
    _press_save(qtbot, win, compare)
    qtbot.keyClicks(compare.reason, "while it loads")
    compare.btn_confirm.setFocus(Qt.FocusReason.TabFocusReason)
    revisions = len(ctx.recipe_history(BOARD))
    qtbot.keyClick(compare.btn_confirm, Qt.Key.Key_Space)  # Save Revision: nothing differs afterwards
    assert compare.sheet.isHidden() and len(ctx.recipe_history(BOARD)) == revisions + 1, "the revision saved"
    assert not compare.act_save.isEnabled() and not compare.act_try.isEnabled(), "both off while it loads"
    assert QApplication.focusWidget() is compare.why, "the focus in the why box while both buttons are off"
    qtbot.keyClick(compare.why, Qt.Key.Key_Space)  # a second Space
    assert QApplication.focusWidget() is compare.why and QApplication.activePopupWidget() is None
    assert len(ctx.recipe_history(BOARD)) == revisions + 1 and compare.diff_thr.value() == 255
    gate.set()
    qtbot.waitUntil(lambda: compare.loaded and compare._bg is None, timeout=20000)
    assert QApplication.focusWidget() is compare.btn_try, "on to Re-evaluate once it has loaded (S28d, review)"
    for then in ("moved", "an Operator's sign-in"):  # the focus moved from the why box, or in the sheet at a sign-in
        gate.clear()
        compare.diff_thr.setValue(250 if then == "moved" else 245)
        compare.show_stored(iid)
        _press_save(qtbot, win, compare)
        if then == "moved":
            qtbot.keyClicks(compare.reason, then)
            qtbot.keyClick(compare.reason, Qt.Key.Key_Return)  # Save Revision by Enter: the focus to the why box
            compare.mode.setFocus(Qt.FocusReason.TabFocusReason)  # and the Engineer moves it, to Show: say
        else:
            win.set_user("operator")  # the sheet closes first, the focus in the why box, out of the panel it hides
        kept = compare.mode if then == "moved" else compare.why
        assert QApplication.focusWidget() is kept and compare.sheet.isHidden() and not compare.loaded, then
        gate.set()
        qtbot.waitUntil(lambda: compare.loaded and compare._bg is None, timeout=20000)
        assert QApplication.focusWidget() is kept, f"the focus stays after {then} when it has loaded"
    win.set_user("engineer")
    compare.diff_thr.setValue(240)
    _press_save(qtbot, win, compare)
    win.set_user("operator")  # with nothing loading: the focus in the why box, for no one to take back
    win.set_user("engineer")
    assert QApplication.focusWidget() is compare.why
    _press(qtbot, win, compare)  # Ctrl+R in the why box
    qtbot.waitUntil(compare.would_be.isVisible, timeout=20000)
    assert QApplication.focusWidget() is compare.why, "Ctrl+R in the why box leaves the focus there, as ever"
