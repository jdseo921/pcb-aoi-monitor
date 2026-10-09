"""REQ-RCP-006 on Compare (S29 parts 3 and 4): what judged a board counts the scale, at which the engine applies a
recipe's sizes in mm, when an Operator signs in and in a stored result's note; at a scale, Save to Recipe counts
and lists the minimum defect size in mm, and a scale set after Compare showed the recipe saves nothing (AOI-RCP-010)."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from pytestqt.qtbot import QtBot

from aoi.core.recipe import disc_area
from aoi.core.services import AppContext
from aoi.ui.pages.compare import NO_VERDICT, ComparePage
from tests.test_compare_reevaluate import _stored_on_compare
from tests.test_req_done_in_v01 import BOARD, _window

TITLE = "AOI-RCP-010 Scale set after Compare showed the recipe"


def test_req_rcp_006_an_operators_sign_in_judges_again_a_board_judged_at_another_scale(
    qtbot: QtBot, trained_ctx: AppContext, ng_board: Path
) -> None:
    """A board an Engineer inspected on Compare, then a scale set and an Operator's sign-in: with every size held in px,
    nothing that judged the board changed, and it keeps its verdict; with the minimum defect size held in mm, the recipe
    gives other px at the new scale, so the board is cleared and judged again by the recipe at that scale, as after a
    revision saved since (S28c's _judging, which now compares the recipe in px at the scale each judges at), and the
    Operator signing in again keeps that board, judged by the recipe in px at the scale (S29 review)."""
    ctx = trained_ctx
    scale = ctx.set_scale(BOARD, 476, 10)
    win = _window(qtbot, ctx, "Engineer")
    compare = win.pages["Compare"]
    assert isinstance(compare, ComparePage) and win.navigate("Compare")
    for mm in (None, 0.5):
        win.set_user("engineer")
        if mm is not None:  # held in mm with its area at the scale, as Save Recipe stores it; taken up when shown
            _, recipe = ctx.recipe(BOARD)
            recipe.min_defect_mm, recipe.min_defect_area = mm, disc_area(mm * scale)
            ctx.save_recipe(recipe)
            ctx.set_scale(BOARD, 714, 10)  # after the save: the board is judged at 71.4 px/mm, not as stored
            win.navigate("Inspection")
            win.navigate("Compare")
        compare.set_test(str(ng_board))
        qtbot.waitUntil(lambda: ctx.jobs.idle() and compare._bg is None and compare.res is not None, timeout=60000)
        judged = compare.res
        win.set_user("operator")
        assert compare.res is judged and compare._bg is None, "nothing that judged the board changed (S29 review)"
        win.set_user("engineer")
        scale = ctx.set_scale(BOARD, 952 if mm is None else 1428, 10)
        win.set_user("operator")
        if mm is None:
            assert compare.res is judged and compare._bg is None, "a size in px judges alike at any scale"
            continue
        assert (compare.verdict.text(), compare.metrics.rowCount(), compare._bg is not None) == (NO_VERDICT, 0, True)
        qtbot.waitUntil(lambda: ctx.jobs.idle() and compare._bg is None and compare.res is not None, timeout=60000)
        judged = compare.res  # judged for the Operator by the recipe in px at the scale, which signing in again keeps
        win.set_user("operator")
        regions = next(c.explain for c in judged.checks if c.name == "Difference regions")
        assert compare.res is judged and regions == f"blobs ≥ {disc_area(mm * scale)} px after noise clean-up"


def test_req_rcp_006_a_stored_result_judged_at_another_scale_names_both(
    qtbot: QtBot, trained_ctx: AppContext, ng_board: Path
) -> None:
    """A stored result judged at one scale, opened on Compare once its board model has another, names both in the line
    under the verdict: Re-evaluate applies sizes in mm at the one it was judged at (ADR 0006), and Try other thresholds
    shows them at the board model's (S29). Judged at the board model's scale, it names none."""
    ctx = trained_ctx
    ctx.set_scale(BOARD, 476, 10)
    _, compare, iid = _stored_on_compare(qtbot, ctx, ng_board, "Engineer")
    assert "scale" not in compare.note.text()
    ctx.set_scale(BOARD, 952, 10)
    compare.show_stored(iid)
    qtbot.waitUntil(lambda: compare.loaded and compare._bg is None, timeout=10000)
    assert compare.note.text().endswith(
        "It was judged at a scale of 47.60 px/mm, at which Re-evaluate applies sizes in mm; the board model's scale, at"
        " which Try other thresholds shows them, is now 95.20 px/mm."
    )
    ctx.set_scale(BOARD, 476.01, 10)  # 47.601 px/mm, 47.60 at two decimals as the result's: told apart (S29 review)
    compare.show_stored(iid)
    qtbot.waitUntil(lambda: compare.loaded and compare._bg is None, timeout=10000)
    assert "scale of 47.600 px/mm, at" in compare.note.text() and compare.note.text().endswith("now 47.601 px/mm.")


def test_req_cmp_005_save_to_recipe_counts_and_lists_the_minimum_defect_size_in_mm(
    qtbot: QtBot, trained_ctx: AppContext, dialogs: list[tuple[str, str]]
) -> None:
    """At a scale, Save to Recipe counts the minimum defect size in mm, as its field shows it, also when its area is the
    recipe's, and the sheet lists it so, with the field's two decimals or every decimal the recipe holds (a size held
    in px as its width at the scale), its area, which follows it, not apart; the revision's audit entry holds it."""
    ctx = trained_ctx
    ctx.set_scale(BOARD, 427, 100)  # 4.27 px/mm: the recipe's 40 px of area, 7.14 px wide, read 1.67 mm
    win = _window(qtbot, ctx, "Engineer")
    compare = win.pages["Compare"]
    assert isinstance(compare, ComparePage) and win.navigate("Compare")
    size, rev = compare.min_size, ctx.recipe(BOARD)[0]
    assert size.mm.value() == 1.67 and not compare.btn_save.isEnabled()
    size.mm.setValue(1.66)  # 7.09 px wide: 40 px of area too, held in mm once saved
    assert disc_area(1.66 * 4.27) == 40 and compare.btn_save.isEnabled()
    compare.ssim_min.setDecimals(3)  # the size shows its own field's decimals, not another's (S29 review)
    compare.btn_save.click()
    assert compare.sheet_changes.text() == "Minimum defect size (mm): 1.67 → 1.66"
    compare.reason.setText("held in mm")
    compare.btn_confirm.click()
    saved = ctx.recipe(BOARD)
    assert saved[0] == rev + 1 and (saved[1].min_defect_area, saved[1].min_defect_mm) == (40, 1.66)
    assert ctx.audit_entries(action="recipe.save")[0]["after"]["min_defect_mm"] == 1.66
    saved[1].min_defect_mm = 1.6634  # more decimals than the field shows
    ctx.save_recipe(saved[1])
    win.navigate("Inspection")
    win.navigate("Compare")
    size.mm.setValue(2.0)
    compare.btn_save.click()
    assert compare.sheet_changes.text() == "Minimum defect size (mm): 1.6634 → 2.00" and dialogs == []


def test_req_rcp_006_a_scale_set_after_compare_showed_the_recipe_saves_nothing(
    qtbot: QtBot, trained_ctx: AppContext, ng_board: Path, dialogs: list[tuple[str, str]]
) -> None:
    """A scale set while Save to Recipe's sheet is open stores nothing, as a revision saved since does (AOI-RCP-004,
    S28d). Set with Compare shown (through AppContext, as another window's page would), Save Revision, pressed by key,
    closes the sheet with its reason, the form shows the recipe at the new scale and AOI-RCP-010 says so; the focus
    goes back to the panel, on Re-evaluate, where one more Space judges the board again and stores nothing either. Set
    while Compare is hidden, on the Recipe Editor, it closes the sheet and AOI-RCP-010 says so once Compare shows; set
    before the sheet opens, its title still holds (S29 review)."""
    ctx = trained_ctx
    win, compare, _ = _stored_on_compare(qtbot, ctx, ng_board, "Engineer")
    win.activateWindow()  # the focus moves only in the active window
    qtbot.waitUntil(win.isActiveWindow, timeout=5000)
    rev = ctx.recipe(BOARD)[0]
    compare.diff_thr.setValue(255)
    compare.btn_save.click()
    compare.reason.setText("tried before the scale")
    ctx.set_scale(BOARD, 952, 10)
    compare.btn_confirm.setFocus(Qt.FocusReason.TabFocusReason)
    qtbot.keyClick(compare.btn_confirm, Qt.Key.Key_Space)
    assert ctx.recipe(BOARD)[0] == rev and compare.sheet.isHidden() and compare.reason.text() == ""
    assert compare.min_size.label.text() == "Minimum defect size (mm)" and compare.diff_thr.value() != 255
    assert [title for title, _ in dialogs] == [TITLE]
    assert dialogs[0][1].startswith(f"The scale of board model {BOARD} was set to 95.20 px/mm after Compare showed")
    assert win.focusWidget() is compare.btn_try
    qtbot.keyClick(compare.btn_try, Qt.Key.Key_Space)  # one more Space: Re-evaluate
    qtbot.waitUntil(lambda: compare._trying is None and compare.would_be.isVisible(), timeout=20000)
    assert ctx.recipe(BOARD)[0] == rev and len(dialogs) == 1
    compare.diff_thr.setValue(254)
    compare.btn_save.click()
    win.navigate("Recipe Editor")
    ctx.set_scale(BOARD, 476, 10)  # with Compare hidden
    win.navigate("Compare")
    what = (
        f"The scale of board model {BOARD} was set to 47.60 px/mm after Compare showed revision {rev}, so Save to"
        f" Recipe listed its changes at the scale before, or in px without one; the sheet closed and nothing was"
        f" saved. Compare now shows the thresholds of revision {rev} at the new scale."
    )
    step = "Try your thresholds again at this scale, then press Save to Recipe."
    assert compare.sheet.isHidden() and ctx.recipe(BOARD)[0] == rev and ctx.alarms()[0]["code"] == "AOI-RCP-010"
    assert dialogs[1:] == [(TITLE, f"{what}\n\n{step}")]
    compare.diff_thr.setValue(253)
    ctx.set_scale(BOARD, 500, 10)  # set before the sheet opens
    compare.btn_save.click()
    compare.reason.setText("opened after the scale was set")
    compare.btn_confirm.click()
    assert ctx.recipe(BOARD)[0] == rev and [title for title, _ in dialogs[2:]] == [TITLE]
