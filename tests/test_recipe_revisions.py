"""REQ-RCP-004 and REQ-RCP-005 (S50): Save Recipe asks first on a sheet listing what the save changes, before → after,
never overwrites a revision, and audits each one with its body before and after; the Revisions tab lists them with
their changes and reasons, opens any read-only and restores one as a new revision (Q24); a save leaving a Stage 1 AOI
check uncovered needs a reason, kept with the revision (recipe-editor sketch)."""

from __future__ import annotations

import json

import pytest
from PySide6.QtCore import QRectF, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QAbstractItemView, QMessageBox, QTabWidget
from pytestqt.qtbot import QtBot

from aoi.core.recipe import ROI
from aoi.core.services import AppContext
from aoi.ui.pages.recipe_editor import RecipeEditorPage
from tests.test_recipe_rois import _page
from tests.test_req_done_in_v01 import BOARD

CTRL = Qt.KeyboardModifier.ControlModifier
STAGE_1_ROI_CHECKS = "Missing Component, Polarity Error, Solder Bridge"


@pytest.fixture
def page(qtbot: QtBot, trained_ctx: AppContext, monkeypatch: pytest.MonkeyPatch) -> RecipeEditorPage:
    """The Recipe Editor on a recipe with no ROI; the "Saved revision" box answers itself."""
    monkeypatch.setattr(QMessageBox, "information", staticmethod(lambda *_: QMessageBox.StandardButton.Ok))
    return _page(qtbot, trained_ctx)


def _bodies(ctx: AppContext) -> dict[int, str]:
    """Every revision's body as stored, by revision."""
    rows = ctx.db.query("SELECT revision, body FROM recipes WHERE board_model=?", (BOARD,))
    return {r["revision"]: r["body"] for r in rows}


def _rows(page: RecipeEditorPage) -> list[list[str]]:
    t = page.history
    return [[t.item(r, c).text() for c in range(t.columnCount())] for r in range(t.rowCount())]


def test_req_rcp_004_save_creates_revision_with_diff(page: RecipeEditorPage, trained_ctx: AppContext) -> None:
    """Ctrl+S opens the sheet, which names revision n+1 and lists each change before → after, saving nothing yet; Save
    Revision stores revision n+1, every revision before it as it was, with an audit entry holding the body before and
    after and the reason, and the Revisions tab lists it first with its changes. Esc closes the sheet unsaved, and with
    nothing changed Save Revision is off, as a revision never repeats the one before."""
    ctx, rev = trained_ctx, page.rev
    before = _bodies(ctx)
    page.roi_type.setCurrentIndex(page.roi_type.findData("Presence"))
    page.view.roiDrawn.emit(QRectF(100, 100, 80, 60))
    page.diff.setValue(30)
    page.view.setFocus()
    QTest.keyClick(page.view, Qt.Key.Key_S, CTRL)
    sheet = page.save_sheet
    assert sheet.isVisible() and sheet.btn_save.text() == f"Save Revision {rev + 1}"
    assert f"as revision {rev + 1}? Revision {rev} stays as it was saved." in sheet.heading.text()
    assert sheet.changes.text().split("\n") == ["Pixel difference: 45 → 30", "ROI R1 added"]
    assert _bodies(ctx) == before, "nothing saved before Save Revision"
    QTest.keyClick(sheet.reason, Qt.Key.Key_Escape)
    assert sheet.isHidden() and _bodies(ctx) == before

    page.view.setFocus()
    QTest.keyClick(page.view, Qt.Key.Key_S, CTRL)
    sheet.reason.setText("R1 added for the new connector")
    sheet.btn_save.click()
    assert ctx.recipe(BOARD)[0] == rev + 1 and page.rev == rev + 1 and sheet.isHidden()
    after = _bodies(ctx)
    assert {k: v for k, v in after.items() if k != rev + 1} == before, "no revision overwritten"
    entry = ctx.audit_entries(action="recipe.save", object_uuid=ctx.recipe_history(BOARD)[0]["uuid"])[0]
    assert (entry["before"], entry["after"]) == (json.loads(before[rev]), json.loads(after[rev + 1]))
    assert entry["before"]["diff_threshold"] == 45 and entry["before"]["rois"] == []
    assert entry["after"]["diff_threshold"] == 30 and [r["name"] for r in entry["after"]["rois"]] == ["R1"]
    assert entry["reason"] == "R1 added for the new connector" and entry["user_uuid"] == ctx.actor.uuid
    top = _rows(page)[0]
    assert top[0] == str(rev + 1) and top[1] == ctx.user
    assert top[3:] == ["Pixel difference: 45 → 30; ROI R1 added", "R1 added for the new connector"]
    assert _rows(page)[-1][3] == "first revision"

    page.ask_save()
    sheet.reason.setText("typed, so that nothing changed alone keeps Save Revision off")
    assert sheet.changes.text() == f"Nothing changed since revision {rev + 1}." and not sheet.btn_save.isEnabled()


def test_req_rcp_004_old_revision_viewable(page: RecipeEditorPage, trained_ctx: AppContext) -> None:
    """Open shows the revision picked read-only beside the recipe as edited: its settings, its ROIs and what the edits
    change from it, nothing editable and nothing saved; Restore as New Revision saves a copy of it as the next revision,
    after the sheet, which never replaces one."""
    ctx = trained_ctx
    old = ctx.recipe(BOARD)[1]
    old.rois = [ROI("R1", "Presence", 10, 20, 30, 40)]
    first = ctx.save_recipe(old, "first ROI")
    newer = ctx.recipe(BOARD)[1]
    newer.diff_threshold, newer.rois = 30, []
    ctx.save_recipe(newer)
    page.on_show()  # the revisions saved since are loaded
    assert ctx.recipe_revisions("NEWB") == [], "a board model with no recipe has none"
    tabs = page.findChild(QTabWidget)
    assert tabs is not None
    tabs.setCurrentIndex([tabs.tabText(i) for i in range(tabs.count())].index("Revisions"))  # as an Engineer would
    page.ssim.setValue(0.9)  # an edit not saved
    rows = _rows(page)
    assert [r[0] for r in rows[:2]] == [str(first + 1), str(first)]
    assert rows[1][3:] == ["ROI R1 added", "first ROI"] and rows[0][3:] == [
        "Pixel difference: 45 → 30; ROI R1 removed",
        "—",
    ]
    assert not page.open_btn.isEnabled() and not page.restore_btn.isEnabled(), "no revision picked"
    page.history.selectRow(1)
    page.open_btn.click()
    pane = page.revision_pane
    assert pane.isVisible() and pane.title().startswith(f"Revision {first}, read-only: saved by {ctx.user}")
    assert "Pixel difference: 45" in pane.settings.text() and "Similarity minimum (SSIM): 0.8" in pane.settings.text()
    assert pane.against.text().split("\n") == [
        f"What the recipe as edited changes from revision {first}:",
        "Pixel difference: 45 → 30",
        "Similarity minimum (SSIM): 0.8 → 0.9",
        "ROI R1 removed",
    ]
    cells = [[pane.rois.item(r, c).text() for c in range(pane.rois.columnCount())] for r in range(pane.rois.rowCount())]
    assert cells == [["R1", "Presence", "10", "20", "30", "40", "1"]], "as the ROIs tab shows them"
    assert pane.rois.editTriggers() == QAbstractItemView.EditTrigger.NoEditTriggers
    assert page.ssim.value() == pytest.approx(0.9) and page.edited_recipe.rois == [], "the edits kept"
    assert ctx.recipe(BOARD)[0] == first + 1, "nothing saved"

    bodies = _bodies(ctx)
    page.history.selectRow(1)
    page.restore_btn.click()
    sheet = page.save_sheet
    assert sheet.heading.text().startswith(f"Restore revision {first} of {BOARD} as revision {first + 2}?")
    assert sheet.changes.text().split("\n") == ["Pixel difference: 30 → 45", "ROI R1 added"]
    assert sheet.missing.isVisible(), "revision 2 leaves Polarity Error and Solder Bridge uncovered"
    sheet.reason.setText("back to revision 2")
    answers = [QMessageBox.StandardButton.Yes]
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(QMessageBox, "question", staticmethod(lambda *_: answers.pop(0)))
        sheet.btn_save.click()
    assert not answers, "the unsaved edit was asked about first"
    saved = _bodies(ctx)
    assert {k: v for k, v in saved.items() if k != first + 2} == bodies and saved[first + 2] == bodies[first]
    assert page.rev == first + 2 and page.ssim.value() == pytest.approx(0.8) and len(page.edited_recipe.rois) == 1
    assert _rows(page)[0][3:] == ["Pixel difference: 30 → 45; ROI R1 added", "back to revision 2"]
    assert not page.open_btn.isEnabled() and pane.isHidden(), "the list filled again, no row is another revision"


def test_req_rcp_005_uncovered_check_needs_reason(page: RecipeEditorPage, trained_ctx: AppContext) -> None:
    """With a Stage 1 AOI check uncovered, the sheet names it and Save Revision stays off until a reason is typed
    (blank is none); the reason is kept in the revision's audit entry and on the Revisions tab. With every Stage 1
    check covered no reason is asked. An edit made while the sheet is open shows it again, so what is saved is what
    was confirmed: an ROI deleted then uncovers its check and asks for a reason."""
    ctx, sheet = trained_ctx, page.save_sheet
    page.diff.setValue(40)
    page.ask_save()
    assert sheet.missing.isVisible() and sheet.missing.text().startswith(f"Not covered: {STAGE_1_ROI_CHECKS}.")
    assert sheet.reason_label.text() == "Reason (required)" and not sheet.btn_save.isEnabled()
    sheet.reason.setText("   ")
    assert not sheet.btn_save.isEnabled(), "blank is no reason"
    sheet.reason.setText("ROIs follow with the new fixture")
    sheet.btn_save.click()
    entry = ctx.audit_entries(action="recipe.save")[0]
    assert entry["reason"] == "ROIs follow with the new fixture" and _rows(page)[0][4] == entry["reason"]

    for i, roi_type in enumerate(("Presence", "Polarity", "Solder Bridge")):
        page.roi_type.setCurrentIndex(page.roi_type.findData(roi_type))
        page.view.roiDrawn.emit(QRectF(20 + 60 * i, 30, 40, 50))
    page.ask_save()
    assert sheet.missing.isHidden() and sheet.reason_label.text() == "Reason" and sheet.btn_save.isEnabled()
    page.roi_table.selectRow(2)
    page.delete_roi()  # while the sheet is open
    rev = ctx.recipe(BOARD)[0]
    sheet.btn_save.click()
    assert ctx.recipe(BOARD)[0] == rev, "not saved: the sheet shows the change first"
    assert sheet.missing.text().startswith("Not covered: Solder Bridge.") and not sheet.btn_save.isEnabled()
    assert sheet.changes.text().split("\n") == ["ROI R1 added", "ROI R2 added"]
    sheet.reason.setText("bridge ROI redrawn next shift")
    sheet.btn_save.click()
    assert ctx.recipe(BOARD)[0] == rev + 1 and ctx.audit_entries(action="recipe.save")[0]["reason"] == (
        "bridge ROI redrawn next shift"
    )
    page.ask_save()
    assert not sheet.btn_save.isEnabled(), "nothing changed"
