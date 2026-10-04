"""REQ-CMP-005 on Compare (S28b part 2): the "Try other thresholds" panel is for an Engineer or Admin and hidden for an
Operator, whose inspections on Compare are judged by the recipe (ADR 0006 decision 4; sketch
docs/sketches/compare-decision-table.md, Q17)."""

from __future__ import annotations

from dataclasses import asdict
from pathlib import Path

import pytest
from PySide6.QtWidgets import QWidget
from pytestqt.qtbot import QtBot

from aoi.core.inspector import InspectionResult
from aoi.core.services import AppContext
from aoi.ui import theme
from aoi.ui.main_window import MainWindow
from aoi.ui.pages.compare import MODE_DIFF, MODE_SIDE, NO_VERDICT, ComparePage
from tests.test_compare_stored import _expected, _table
from tests.test_req_done_in_v01 import BOARD, _window


def _stored_on_compare(qtbot: QtBot, ctx: AppContext, board: Path, role: str) -> tuple[MainWindow, ComparePage, int]:
    """`board` inspected and stored, then opened on Compare by `role`, its pictures and maps loaded."""
    ctx.inspect_file(BOARD, str(board))
    (rec,) = ctx.inspections(board_model=BOARD)
    win = _window(qtbot, ctx, role)
    compare = win.pages["Compare"]
    assert isinstance(compare, ComparePage)
    win.navigate("Compare")
    qtbot.waitUntil(ctx.jobs.idle, timeout=10000)
    compare.show_stored(rec["id"])
    qtbot.waitUntil(lambda: compare._bg is None and compare.test_view._pix is not None, timeout=10000)
    return win, compare, rec["id"]


def _panel(compare: ComparePage) -> QWidget:
    """The panel that holds the thresholds form, Re-evaluate and Save to Recipe."""
    panel = compare.ai_thr.parentWidget()
    assert panel is not None and panel.isAncestorOf(compare.btn_save)
    return panel


def _pass_every_check(compare: ComparePage) -> None:
    """Thresholds no check of the NG board fails: no pixel differs enough, any similarity, AI score threshold 500."""
    compare.diff_thr.setValue(255)
    compare.ssim_min.setValue(0.0)
    compare.ai_thr.setValue(500.0)


def test_req_cmp_005_an_operator_does_not_see_the_threshold_panel(
    qtbot: QtBot, trained_ctx: AppContext, ng_board: Path
) -> None:
    """An Operator sees a stored result's verdict, table and explanation but not the threshold panel; switching to an
    Engineer on the page shows it, titled "Try other thresholds", and back to an Operator hides it again. The Operator's
    Golden Board then inspects the board by the recipe, not by thresholds the Engineer left in the hidden panel."""
    win, compare, _ = _stored_on_compare(qtbot, trained_ctx, ng_board, "Operator")
    assert compare.metrics.rowCount() > 1 and compare.why.toPlainText().startswith("Why this board is NG:")
    assert _panel(compare).isHidden(), "an Operator never sees what other thresholds would give"
    win.set_user("engineer")
    assert _panel(compare).isVisible() and compare.tryout.title().startswith("Try other thresholds")
    compare.diff_thr.setValue(255)  # tried by an Engineer, not saved: no pixel differs enough
    win.set_user("operator")
    assert _panel(compare).isHidden()
    compare.use_golden()  # inspected again, against today's Golden board
    qtbot.waitUntil(lambda: compare._bg is None and compare.stored is None, timeout=20000)
    assert compare.res is not None and next(c.value for c in compare.res.checks if c.name == "Difference regions") > 0


def test_req_cmp_005_an_operators_inspection_on_compare_takes_the_recipe_as_stored(
    qtbot: QtBot, trained_ctx: AppContext, ng_board: Path
) -> None:
    """A recipe revision with a Similarity minimum of 0.805, finer than the form's two decimals (0.81 there, loaded at
    the sign-in): an Operator's Golden Board judges the board with the recipe's 0.805, never with the hidden form's
    value (review of the replay)."""
    ctx = trained_ctx
    _, recipe = ctx.recipe(BOARD)
    recipe.ssim_min = 0.805
    ctx.save_recipe(recipe)  # trained_ctx acts as an Engineer
    _, compare, _ = _stored_on_compare(qtbot, ctx, ng_board, "Operator")
    assert round(compare.ssim_min.value(), 3) != 0.805, "the hidden form cannot hold the recipe's value"
    compare.use_golden()
    qtbot.waitUntil(lambda: compare._bg is None and compare.stored is None and compare.res is not None, timeout=20000)
    assert compare.res is not None
    ssim = next(c for c in compare.res.checks if c.name == "SSIM similarity")
    assert ssim.threshold == 0.805, ssim


def test_req_cmp_005_an_operator_never_sees_a_board_judged_by_thresholds_not_saved(
    qtbot: QtBot,
    trained_ctx: AppContext,
    ng_board: Path,
    monkeypatch: pytest.MonkeyPatch,
    dialogs: list[tuple[str, str]],
) -> None:
    """When an Operator signs in, the hidden form goes back to the recipe's thresholds, which the Difference heatmap
    shown follows, and a board an Engineer inspected on Compare with thresholds not saved is cleared and judged again by
    the recipe: after its verdict shows, or while it is worked out, and also when the Operator signs in on another page
    and then opens Compare. From the sign-in the page never shows its verdict, table or "why" (review). The form is
    read at the sign-in only, and an Engineer's run stopped by Cancel stays cancelled (review round 3)."""
    ctx = trained_ctx
    win, compare, _ = _stored_on_compare(qtbot, ctx, ng_board, "Engineer")
    _, recipe = ctx.recipe(BOARD)
    compare.diff_thr.setValue(255)  # tried by an Engineer, not saved
    compare.mode.setCurrentIndex(MODE_DIFF)
    win.set_user("operator")
    assert compare.diff_thr.value() == recipe.diff_threshold != 255
    assert list(compare._views) == [(MODE_DIFF, recipe.diff_threshold)], "the heatmap at the recipe's pixel difference"
    compare.mode.setCurrentIndex(MODE_SIDE)
    want = ctx.inspect(BOARD, ctx.load_image(str(ng_board)))  # the board by the recipe, against today's Golden board
    rows = [{**asdict(c), "metric": c.name, "result": c.verdict} for c in want.checks]
    assert want.verdict == "NG"
    shown: list[str] = []
    show = ComparePage._show_result

    def showing(self: ComparePage, r: InspectionResult) -> None:
        shown.append(r.verdict)
        show(self, r)

    monkeypatch.setattr(ComparePage, "_show_result", showing)
    seen: list[tuple[str, int, str]] = []

    def judged() -> bool:
        """What the Operator sees, each change of it, until the recipe's run ends."""
        now = (compare.verdict.text(), compare.metrics.rowCount(), compare.why.toPlainText())
        seen.extend([now] if now != seen[-1] else [])
        return ctx.jobs.idle() and compare._bg is None

    for in_flight, elsewhere in ((False, False), (True, False), (False, True)):
        win.set_user("engineer")
        _pass_every_check(compare)
        shown.clear()
        if in_flight:
            compare._clear_result()  # nothing shown, as after Cancel: the run is all there is to replace
        compare.use_golden()
        if in_flight:
            assert compare._bg is not None and not shown, "the Engineer's inspection is still worked out"
        else:
            qtbot.waitUntil(lambda: compare._bg is None and bool(shown), timeout=20000)
            assert shown == ["WARN"], "the Engineer's thresholds judge the board WARN"
        win.navigate("Home" if elsewhere else "Compare")
        win.set_user("operator")
        win.navigate("Compare")
        seen[:] = [(compare.verdict.text(), compare.metrics.rowCount(), compare.why.toPlainText())]
        qtbot.waitUntil(judged, timeout=20000)
        assert seen[0] == (NO_VERDICT, 0, ""), "from the sign-in, no verdict, table or why of the Engineer's thresholds"
        assert [banner for banner, _, _ in seen] == [NO_VERDICT, theme.verdict_label("NG")], seen
        assert shown == (["NG"] if in_flight else ["WARN", "NG"]), "judged again by the recipe, the run replaced unseen"
        assert compare.verdict.text() == theme.verdict_label("NG") and compare.stored is None
        assert _table(compare)[:-1] == _expected(compare, rows), "the recipe's values and thresholds"
        assert compare.diff_thr.value() == recipe.diff_threshold and not dialogs
    reads: list[str] = []
    recipe_of = AppContext.recipe
    monkeypatch.setattr(AppContext, "recipe", lambda c, bm: reads.append(bm) or recipe_of(c, bm))
    win.navigate("Home")
    win.navigate("Compare")
    assert reads == [BOARD], "the form is the recipe's since the sign-in: only on_show's revision check reads it"
    win.set_user("engineer")
    _pass_every_check(compare)
    compare.use_golden()
    compare.busy.cancel_button.click()  # Cancel, the run still going
    win.set_user("operator")  # before the stopped run ends
    qtbot.waitUntil(lambda: ctx.jobs.idle() and compare._bg is None, timeout=20000)
    assert compare.verdict.text() == NO_VERDICT and compare.test_empty.heading.text() == "Inspection cancelled"
    assert shown == ["WARN", "NG"] and not dialogs, "nothing inspected again: the Engineer cancelled it"
