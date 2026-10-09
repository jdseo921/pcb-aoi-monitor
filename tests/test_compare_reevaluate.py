"""REQ-CMP-005 on Compare (S28b part 2): the "Try other thresholds" panel is for an Engineer or Admin and hidden for an
Operator, whose inspections on Compare are judged by the recipe (ADR 0006 decision 4; sketch
docs/sketches/compare-decision-table.md, Q17 and Q19). An Engineer tries other thresholds on a stored result, which
Re-evaluate judges again from its stored maps without the AI model (`AppContext.re_evaluate`); the verdict they would
give shows beside Re-evaluate while the banner keeps the stored one."""

from __future__ import annotations

import itertools
import sqlite3
import statistics
import sys
import threading
from collections import Counter
from collections.abc import Iterator
from dataclasses import asdict, replace
from pathlib import Path
from time import perf_counter
from typing import Any

import pytest
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QGuiApplication, QPalette
from PySide6.QtWidgets import QAbstractButton, QAbstractSpinBox, QApplication, QPushButton, QWidget
from pytestqt.qtbot import QtBot

from aoi.core.explain import TRIED_AI_OFF, explain
from aoi.core.inspector import InspectionResult, ai_check
from aoi.core.jobs import Job
from aoi.core.recipe import ROI
from aoi.core.services import AppContext
from aoi.errors import AoiError
from aoi.ui import theme
from aoi.ui.main_window import MainWindow
from aoi.ui.pages.compare import MODE_DIFF, MODE_SIDE, NO_VERDICT, ComparePage
from aoi.ui.widgets.busy import BusyOverlay
from tests.screens.test_sizes_and_contrast import _check_widget, _pixels
from tests.test_compare_stored import _expected, _refuse_inspection, _table, save_to_recipe
from tests.test_no_freeze import BUDGET_S, assert_off_ui_thread, board_5mp, gap_meter, heavy_calls  # noqa: F401
from tests.test_re_evaluate import _store_5mp
from tests.test_req_done_in_v01 import BOARD, _window
from tests.test_stored_result import _ai_off
from tools import render_screens

Dialogs = list[tuple[str, str]]  # the `dialogs` fixture: each error dialog shown, as (title, text)


@pytest.fixture(autouse=True)
def _no_key_left_held() -> Iterator[None]:
    """Each test here lets go of the keys it pressed: Qt keeps a modifier held from one test to the next, and a Ctrl
    left held turns a later test's selectRow() into a Ctrl+click, which adds the row to the selection (review)."""
    yield
    assert QGuiApplication.keyboardModifiers() == Qt.KeyboardModifier.NoModifier, "a key is still held"


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
    assert not compare.act_try.isEnabled(), "Re-evaluate waits for the pictures and maps, whose load it would stop"
    qtbot.waitUntil(lambda: compare.loaded and compare._bg is None, timeout=10000)
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
    compare.ai_thr.set_override(500.0)


def _walk(win: MainWindow, widgets: list[QWidget]) -> tuple[list[str], Counter[str]]:
    """What breaks the screen tests' size, font and contrast rules among `widgets`, and how many were measured."""
    app = QApplication.instance()
    assert isinstance(app, QApplication)
    seen: Counter[str] = Counter()
    with render_screens.pinned_rendering(app, render_screens.TEST_FONT if sys.platform == "linux" else ""):
        QApplication.processEvents()
        shot = _pixels(win.grab().toImage())
        found = [f for w in widgets for f in _check_widget("Compare (Engineer)", win, shot, w, seen)]
    return found, seen


def _ink(widget: QWidget, color: QColor) -> float:
    """How much of `widget`, as drawn, is `color`: one pixel in 16 sampled."""
    img = widget.grab().toImage()
    seen = [img.pixelColor(x, y) for x in range(0, img.width(), 4) for y in range(0, img.height(), 4)]
    return sum(c == color for c in seen) / len(seen)


def _press(qtbot: QtBot, win: MainWindow, compare: ComparePage) -> None:
    """Re-evaluate's key, as an Engineer presses it, then let go: QTest's click leaves Qt holding Ctrl (review)."""
    key = compare.act_try.shortcut()[0]
    qtbot.keyClick(win, key.key(), key.keyboardModifiers())
    qtbot.keyRelease(win, key.key())  # with no modifier, so a later test's selectRow() no longer adds a row


def test_req_cmp_005_reevaluate_on_compare_shows_what_the_stored_result_would_be(
    qtbot: QtBot, trained_ctx: AppContext, ng_board: Path, monkeypatch: pytest.MonkeyPatch, dialogs: Dialogs
) -> None:
    """On a stored NG result, Ctrl+R with thresholds that pass every check judges it again from its stored maps, with no
    inspection and no AI model loaded: the banner keeps the stored verdict, "Would be" beside Re-evaluate shows the one
    those thresholds give, and the table and the explanation show their checks; the board keeps its stored boxes, so
    defects that make the WARN are said to be ones the thresholds would mark, not ones marked on the board (review);
    nothing is stored; "Would be", a bar of the verdict's colour beside words in the theme's text colour (review), and
    the panel's buttons meet the screen tests' size, font and contrast rules. A
    threshold changed, or the result opened again, brings back its own checks; a result whose AI map is gone is refused
    with AOI-CMP-004, keeps its own and holds no worker (#132), the answer before going at the press (review), and
    Re-evaluate is on again after the refusal (review)."""
    ctx = trained_ctx
    win, compare, iid = _stored_on_compare(qtbot, ctx, ng_board, "Engineer")
    rec = ctx.inspection(iid)
    assert rec is not None and rec["result"] == "NG" and compare.act_try.isEnabled()
    stored, why = _table(compare), compare.why.toPlainText()
    _pass_every_check(compare)
    _refuse_inspection(monkeypatch)
    before = (ctx.inspections(), ctx.audit_entries(), ctx.recipe_history(BOARD))
    want = ctx.re_evaluate(rec["uuid"], compare._form_recipe(BOARD))
    assert want.verdict != "NG", "these thresholds change the verdict"
    _press(qtbot, win, compare)
    qtbot.waitUntil(compare.would_be.isVisible, timeout=10000)
    assert compare.would_be.text() == f"Would be: {theme.verdict_label(want.verdict)}"
    inked = _ink(compare.would_be, QColor(theme.VERDICT_COLORS[want.verdict]))
    assert 0 < inked < 0.2, f"the verdict's colour as a bar beside it, not a filled box like a button: {inked:.0%}"
    app, text = QApplication.instance(), QColor("#203040")
    assert isinstance(app, QApplication)
    qss = app.styleSheet()
    try:  # a theme with another text colour, as the presenter theme will be (REQ-SET-008), colours its words (review)
        app.setStyleSheet(theme.stylesheet(TEXT=text.name()))
        QApplication.processEvents()
        assert compare.would_be.palette().color(QPalette.ColorRole.WindowText) == text
    finally:
        app.setStyleSheet(qss)
    assert compare.verdict.text() == theme.verdict_label("NG") and compare.note.isVisible(), "the stored verdict stays"
    rows = [{**asdict(c), "metric": c.name, "result": c.verdict} for c in want.checks]
    assert _table(compare)[:-1] == _expected(compare, rows) != stored[:-1]
    tried = compare.why.toPlainText()
    assert want.verdict == "WARN" and {c.verdict for c in want.checks} <= {"OK", "INFO"}, "a WARN from defects alone"
    assert "marked on the board" not in tried, "the board shows the stored result's boxes, not these (review)"
    sentences = [f"• {s.text()}" for s in explain(want, stored=True, tried=True)]
    assert tried.split("\n") == ["Why this board would be WARN with these thresholds:", *sentences]
    assert "the boxes on the board are the stored result's" in sentences[0], sentences
    assert (ctx.inspections(), ctx.audit_entries(), ctx.recipe_history(BOARD)) == before, "nothing is stored"
    found, seen = _walk(win, [compare.would_be, *compare.tryout.findChildren(QPushButton)])
    assert not found and seen["text"] >= 1 and seen["buttons"] == 2 and seen["contrast"] >= 3, (found, seen)
    compare.min_area.setValue(compare.min_area.value() + 1)
    assert compare.would_be.isHidden() and _table(compare) == stored and compare.why.toPlainText() == why
    compare.re_evaluate()
    qtbot.waitUntil(compare.would_be.isVisible, timeout=10000)
    compare.show_stored(iid)  # opened again: its stored verdict alone until Re-evaluate is pressed
    assert compare.would_be.isHidden() and _table(compare) == stored and not compare.act_try.isEnabled()
    qtbot.waitUntil(lambda: compare.loaded, timeout=10000)
    compare.re_evaluate()
    qtbot.waitUntil(compare.would_be.isVisible, timeout=10000)
    Path(str(ctx.db.map_paths(iid)[1])).unlink()  # its AI map gone: refused with the code, its own checks stand
    compare.re_evaluate()
    assert compare.would_be.isHidden() and _table(compare) == stored, "the last answer goes at the press (review)"
    qtbot.waitUntil(lambda: bool(dialogs), timeout=10000)
    title, text = dialogs.pop()
    assert title.startswith("AOI-CMP-004") and "AI score map" in text, text
    assert _table(compare) == stored and compare.would_be.isHidden() and not dialogs
    assert compare._trying is None, "a refusal holds no worker past its end (#132)"
    assert compare.act_try.isEnabled(), "Re-evaluate is on again after a refusal"


def test_req_cmp_005_what_was_tried_goes_once_it_no_longer_applies(
    qtbot: QtBot, trained_ctx: AppContext, ng_board: Path, monkeypatch: pytest.MonkeyPatch, dialogs: Dialogs
) -> None:
    """The checks other thresholds gave go once they no longer apply, and the result's own show: when an Operator
    signs in, after the answer or while it is worked out (stopped: its answer never shows, and the job, which acts as
    the Engineer who started it, #177, is not refused; an error of it shows no dialog but is alarmed, #206), also on
    another page with Compare never opened, so the next Engineer finds the recipe's thresholds (review), while an
    Admin's or an Engineer's sign-in keeps it and the values tried (review); when a
    threshold changes while it is worked out; when a revision saved elsewhere keeps the form's thresholds but judges
    otherwise (review); when the board model changes; and when inspecting the board again fails (the table then goes
    too, #182). Re-evaluate's key is Ctrl+R."""
    ctx = trained_ctx
    win, compare, iid = _stored_on_compare(qtbot, ctx, ng_board, "Engineer")
    assert compare.act_try.shortcut().toString() == "Ctrl+R"
    stored, why = _table(compare), compare.why.toPlainText()
    gate, started, judge_again, fail = threading.Event(), threading.Event(), AppContext.re_evaluate, [False]

    def held(self: AppContext, *args: Any) -> InspectionResult:
        started.set()
        assert gate.wait(10)
        if fail[0]:
            raise AoiError("AOI-CMP-004", file=ng_board.name, missing="AI score map", days=7)
        return judge_again(self, *args)

    def try_thresholds(hold: bool) -> None:
        gate.clear() if hold else gate.set()
        started.clear()
        _pass_every_check(compare)
        compare.re_evaluate()
        assert started.wait(10), "working it out, not still queued"
        if not hold:
            qtbot.waitUntil(compare.would_be.isVisible, timeout=10000)
            assert _table(compare) != stored

    def shows_its_own_checks() -> None:
        gate.set()
        qtbot.waitUntil(lambda: ctx.jobs.idle() and compare._bg is None, timeout=10000)
        qtbot.wait(50)  # an answer or an error still on its way lands now
        assert compare.would_be.isHidden() and _table(compare) == stored and compare.why.toPlainText() == why
        assert not dialogs

    monkeypatch.setattr(AppContext, "re_evaluate", held)
    for hold in (False, True):  # after the answer, then while it is worked out
        try_thresholds(hold)
        win.set_user("operator")
        shows_its_own_checks()
        win.set_user("engineer")
    assert "AOI-USR-001" not in [a["code"] for a in ctx.alarms()], "the stopped job acted as the Engineer"
    try_thresholds(hold=False)
    tried, form = _table(compare), compare._form_recipe(BOARD)
    win.navigate("Home")
    win.set_user("admin")  # an Admin, then an Engineer, signs in: what was tried stays, as no Operator did (review)
    win.set_user("engineer")
    win.navigate("Compare")
    assert compare.would_be.isVisible() and _table(compare) == tried != stored and compare.why.toPlainText() != why
    assert compare._form_recipe(BOARD) == form != ctx.recipe(BOARD)[1], "the form keeps the values tried, not saved"
    win.navigate("Home")
    win.set_user("operator")  # on another page, and Compare is not opened before an Engineer signs in again (review)
    win.set_user("engineer")
    win.navigate("Compare")
    assert compare.would_be.isHidden() and _table(compare) == stored and compare.why.toPlainText() == why
    assert compare._form_recipe(BOARD) == ctx.recipe(BOARD)[1], "the form holds the recipe's thresholds again"
    fail[0] = True
    try_thresholds(hold=True)
    win.set_user("operator")  # signs in while it is worked out, and it fails: no dialog, but alarmed (#206)
    shows_its_own_checks()
    assert ctx.alarms()[0]["code"] == "AOI-CMP-004"
    win.set_user("engineer")
    fail[0] = False
    try_thresholds(hold=True)
    compare.min_area.setValue(compare.min_area.value() + 1)  # changed while the answer is worked out
    shows_its_own_checks()
    try_thresholds(hold=False)
    revision = compare._form_recipe(BOARD)  # saved elsewhere with the form's five thresholds, so no field changes,
    revision.warn_ratio /= 2  # and another warn ratio, which judges too: what was tried no longer applies
    ctx.save_recipe(revision)
    win.navigate("Home")
    win.navigate("Compare")
    assert compare.would_be.isHidden() and _table(compare) == stored and compare.why.toPlainText() == why
    try_thresholds(hold=False)
    ctx.ensure_board_model("OTHER")
    win._reload_board_models("OTHER")  # another board model: the record's board goes, and what was tried with it
    assert compare.would_be.isHidden() and not compare.tried and compare.stored is None
    win._reload_board_models(BOARD)
    qtbot.waitUntil(lambda: ctx.jobs.idle() and compare._bg is None, timeout=10000)
    compare.show_stored(iid)
    qtbot.waitUntil(lambda: compare.loaded, timeout=10000)
    try_thresholds(hold=False)

    def unreadable(self: AppContext, path: object) -> None:
        raise AoiError("AOI-INSP-006", kind="test", path=str(path), reason="moved away")

    monkeypatch.setattr(AppContext, "load_image", unreadable)
    compare.run()  # a pane's Re-evaluate ›, which inspects the board again from its image file, and fails
    qtbot.waitUntil(lambda: bool(dialogs), timeout=10000)
    assert dialogs.pop()[0].startswith("AOI-INSP-006")
    assert compare.would_be.isHidden() and not compare.tried and compare.metrics.rowCount() == 0, "no checks of it stay"


def test_req_cmp_005_reevaluate_on_what_compare_shows(
    qtbot: QtBot, trained_ctx: AppContext, ng_board: Path, monkeypatch: pytest.MonkeyPatch, dialogs: Dialogs
) -> None:
    """Re-evaluate is ready on a fresh result after Golden Board is pressed while a stored one loads; a result of
    another board model than the header's is refused with AOI-CMP-005, not judged by the header's thresholds; a result
    whose stored picture cannot be read (AOI-CMP-006, its pane "Board picture no longer stored") is still judged again
    from its maps, and once the recipe turns the AI check off, the explanation says those thresholds judge it without
    the AI check (#246); and one none of whose pictures load because another program holds the database (AOI-SET-013,
    #247) is still judged again from its maps once that load has ended (review). On a board not stored, Re-evaluate
    inspects it again with the form's thresholds (review). After a refusal Re-evaluate is on again (review)."""
    ctx = trained_ctx
    win, compare, iid = _stored_on_compare(qtbot, ctx, ng_board, "Engineer")
    compare.show_stored(iid)
    compare.use_golden()  # while its pictures and maps load
    qtbot.waitUntil(lambda: compare._bg is None and compare.stored is None and compare.res is not None, timeout=30000)
    assert compare.act_try.isEnabled()
    fresh = compare.res
    assert fresh is not None and next(c.value for c in fresh.checks if c.name == "Difference regions") > 0
    compare.diff_thr.setValue(255)  # no pixel differs enough
    _press(qtbot, win, compare)  # a board not stored: inspected again with the form's thresholds (review)
    qtbot.waitUntil(lambda: compare._bg is None and compare.res is not fresh, timeout=30000)
    assert compare.stored is None and compare.would_be.isHidden() and compare.res is not None
    assert next(c.value for c in compare.res.checks if c.name == "Difference regions") == 0
    ctx.ensure_board_model("OTHER")
    win._reload_board_models("OTHER")
    qtbot.waitUntil(lambda: ctx.jobs.idle() and compare._bg is None, timeout=10000)
    res = ctx.inspection_result(iid)
    assert res is not None
    win.last_inspected = (str(ng_board), res, iid)  # a record of BOARD under OTHER, as no page leaves it today
    compare.use_last()
    qtbot.waitUntil(lambda: compare.loaded, timeout=10000)
    compare.re_evaluate()
    qtbot.waitUntil(lambda: bool(dialogs), timeout=10000)
    assert dialogs.pop()[0].startswith("AOI-CMP-005") and compare.would_be.isHidden()
    assert compare._trying is None and compare.act_try.isEnabled(), "Re-evaluate is on again after a refusal"
    win._reload_board_models(BOARD)
    qtbot.waitUntil(lambda: ctx.jobs.idle() and compare._bg is None, timeout=30000)
    rec = ctx.inspection(iid)
    assert rec is not None
    Path(rec["overlay_path"]).write_bytes(b"damaged")
    compare.show_stored(iid)
    qtbot.waitUntil(lambda: compare.loaded and bool(dialogs), timeout=10000)
    title, text = dialogs.pop()
    assert title.startswith("AOI-CMP-006") and Path(rec["overlay_path"]).name in text
    assert compare.test_empty.isVisible() and compare.ref_view._pix is not None and compare.act_try.isEnabled()
    _pass_every_check(compare)
    compare.re_evaluate()
    qtbot.waitUntil(compare.would_be.isVisible, timeout=10000)
    assert compare.verdict.text() == theme.verdict_label("NG") and not dialogs
    _ai_off(ctx)  # judged by the AI model, its recipe now turning the AI check off: of the thresholds tried (#246)
    compare.re_evaluate()
    qtbot.waitUntil(compare.would_be.isVisible, timeout=10000)
    assert compare.why.toPlainText().endswith(f"• {TRIED_AI_OFF}"), compare.why.toPlainText()

    def busy(*args: object) -> None:
        held = sqlite3.OperationalError("database is locked")
        held.sqlite_errorcode = sqlite3.SQLITE_BUSY  # type: ignore[attr-defined]
        raise held

    monkeypatch.setattr(ctx, "judged_reference", busy)
    compare.show_stored(iid)
    qtbot.waitUntil(lambda: compare._bg is None and bool(dialogs), timeout=10000)
    assert dialogs.pop()[0].startswith("AOI-SET-013") and compare.would_be.isHidden()
    assert compare.act_try.isEnabled(), "its load has ended, read or not: Re-evaluate no longer stops it"
    compare.re_evaluate()
    qtbot.waitUntil(compare.would_be.isVisible, timeout=10000)
    assert compare.verdict.text() == theme.verdict_label("NG") and not dialogs


def test_req_cmp_005_an_operator_does_not_see_the_threshold_panel(
    qtbot: QtBot, trained_ctx: AppContext, ng_board: Path
) -> None:
    """An Operator sees a stored result's verdict, table and explanation but not the threshold panel; switching to an
    Engineer on the page shows it, titled "Try other thresholds", and back to an Operator hides it again. The Operator's
    Golden Board then inspects the board by the recipe, not by thresholds the Engineer left in the hidden panel. Ctrl+R
    does nothing for the Operator, and Re-evaluate is on for the Engineer."""
    win, compare, _ = _stored_on_compare(qtbot, trained_ctx, ng_board, "Operator")
    assert compare.metrics.rowCount() > 1 and compare.why.toPlainText().startswith("Why this board is NG:")
    assert _panel(compare).isHidden(), "an Operator never sees what other thresholds would give"
    assert not compare.act_try.isEnabled()
    _press(qtbot, win, compare)
    assert trained_ctx.jobs.idle() and compare._bg is None and compare.would_be.isHidden()
    win.set_user("engineer")
    assert _panel(compare).isVisible() and compare.tryout.title().startswith("Try other thresholds")
    assert compare.act_try.isEnabled()
    compare.diff_thr.setValue(255)  # tried by an Engineer, not saved: no pixel differs enough
    win.set_user("operator")
    assert _panel(compare).isHidden() and not compare.act_try.isEnabled()
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


def test_req_cmp_005_one_threshold_not_saved_is_enough_to_have_an_operator_s_board_judged_again(
    qtbot: QtBot, trained_ctx: AppContext, ng_board: Path, dialogs: list[tuple[str, str]]
) -> None:
    """Each of the five thresholds, changed alone by an Engineer (the AI score threshold by its tick, and Similarity
    minimum, a float, among them), makes Golden Board's board one judged by thresholds the recipe does not hold: an
    Operator signing in clears it at once and has it judged again by the recipe, ✗ NG row for row (review). The recipe
    is the one saved when the Operator signs in, not when the board was inspected (review): thresholds saved with Save
    to Recipe after the board was judged by the recipe's own have it judged again, by the new ones; a board judged by
    values not saved then, and saved since, keeps its verdict and is not inspected again; so does one judged with the
    form untouched while the recipe holds an AI score threshold of 0, which judges as none; and another value saved
    since an Operator's own board was inspected (a warn ratio, as the Recipe Editor saves) has it judged again too.
    With the recipe's AI check off no AI model judges, so neither does an AI score threshold not saved: the board
    judged with one keeps its verdict (#243, #246); so does one judged with it and no AI model active, or with a Pixel
    difference not saved and the Golden board comparison off or no Golden board set: a value that did not judge the
    board is no change (review). A board still worked out is held by the recipe's switches, not the result before it,
    the AI check off included. Nor do an ROI's AI score and name judge with the AI check off, nor a disabled ROI, the
    AI check on or off, nor an ROI's Stage 2 values and side, which nothing reads yet; an ROI moved or given another
    type with the AI check off and two ROIs over the defects swapped, which name the defects otherwise (their type and
    severity, never the verdict), an ROI's AI score and name with the AI check on, and Minimum defect area with the
    comparison off, which sizes the AI model's defects, do count (verification, and the second). Save to Recipe reads 0
    as none too, but a value that did not judge the board is still a change to save (S28d)."""
    ctx = trained_ctx
    win, compare, _ = _stored_on_compare(qtbot, ctx, ng_board, "Engineer")
    _, recipe = ctx.recipe(BOARD)
    want = ctx.inspect(BOARD, ctx.load_image(str(ng_board)))
    rows = [{**asdict(c), "metric": c.name, "result": c.verdict} for c in want.checks]
    assert want.verdict == "NG" and recipe.anomaly_threshold is None and 0.01 <= recipe.ssim_min <= 0.99
    edits = {
        "anomaly_threshold": lambda: (compare.ai_thr.tick.setChecked(True), compare.ai_thr.field.setValue(500.0)),
        "diff_threshold": lambda: compare.diff_thr.setValue(recipe.diff_threshold + 1),
        "min_defect_area": lambda: compare.min_area.setValue(recipe.min_defect_area + 1),
        "ssim_min": lambda: compare.ssim_min.setValue(recipe.ssim_min - 0.01),
        "max_diff_regions": lambda: compare.max_regions.setValue(recipe.max_diff_regions + 1),
    }
    for field, edit in edits.items():
        win.set_user("engineer")
        edit()
        form = compare._form_recipe(BOARD)
        assert [f for f in edits if getattr(form, f) != getattr(recipe, f)] == [field], "that one alone"
        compare.use_golden()
        qtbot.waitUntil(lambda: ctx.jobs.idle() and compare._bg is None and compare.res is not None, timeout=20000)
        engineers = compare.res
        win.set_user("operator")
        cleared = (compare.verdict.text(), compare.metrics.rowCount(), compare._bg is not None)
        assert cleared == (NO_VERDICT, 0, True), f"only {field} not saved: cleared and judged again by the recipe"
        qtbot.waitUntil(lambda: ctx.jobs.idle() and compare._bg is None, timeout=20000)
        assert compare.res is not engineers and compare.verdict.text() == theme.verdict_label("NG"), field
        assert _table(compare)[:-1] == _expected(compare, rows) and not dialogs, field

    def golden_board() -> InspectionResult:
        """Golden Board pressed: the board judged by the form's thresholds, or for an Operator by the recipe."""
        compare.use_golden()
        qtbot.waitUntil(lambda: ctx.jobs.idle() and compare._bg is None and compare.res is not None, timeout=20000)
        assert compare.res is not None
        return compare.res

    def operator_signs_in(step: str, again: bool) -> None:
        """An Operator signs in on Compare: the board is cleared and judged by the recipe saved now (`again`), or it
        keeps its verdict with no run started, a run still going left to end; either way the verdict and table end as
        that recipe gives them."""
        engineers, going, now = compare.res, compare._bg, ctx.inspect(BOARD, ctx.load_image(str(ng_board)))
        win.set_user("operator")
        cleared = (compare.verdict.text(), compare.metrics.rowCount(), compare._bg is not None)
        if again:
            assert cleared == (NO_VERDICT, 0, True), f"{step}: cleared and judged again by the recipe saved now"
        else:
            kept = compare._bg is going and (going is None or not going.job.cancelled) and compare.res is engineers
            assert kept, f"{step}: its verdict kept, not inspected again"
        qtbot.waitUntil(lambda: ctx.jobs.idle() and compare._bg is None, timeout=20000)
        assert compare.verdict.text() == theme.verdict_label(now.verdict) and not dialogs, step
        rows = [{**asdict(c), "metric": c.name, "result": c.verdict} for c in now.checks]
        assert _table(compare)[:-1] == _expected(compare, rows), step

    win.set_user("engineer")
    assert golden_board().verdict == "NG", "the recipe's own thresholds"
    _pass_every_check(compare)
    save_to_recipe(compare)  # saved after the board was judged, which is not judged again here
    assert ctx.recipe(BOARD)[1].diff_threshold == 255 and compare.verdict.text() == theme.verdict_label("NG")
    operator_signs_in("saved since by Save to Recipe", again=True)
    assert compare.verdict.text() == theme.verdict_label("WARN"), "the thresholds saved since judge it"
    win.set_user("engineer")
    compare.diff_thr.setValue(200)
    golden_board()
    assert compare._form_recipe(BOARD) != ctx.recipe(BOARD)[1], "judged by values not saved"
    save_to_recipe(compare)
    operator_signs_in("values not saved when inspected, saved since", again=False)
    win.set_user("engineer")
    zero = ctx.recipe(BOARD)[1]
    zero.anomaly_threshold = 0.0
    ctx.save_recipe(zero)
    win.navigate("Home")
    win.navigate("Compare")  # the form takes the revision saved since, its AI score threshold as none
    assert compare._form_recipe(BOARD).anomaly_threshold is None and ctx.recipe(BOARD)[1].anomaly_threshold == 0.0
    golden_board()
    assert not compare.btn_save.isEnabled() and compare._changes() == [], "0 is none to Save to Recipe too (S28d)"
    operator_signs_in("an AI score threshold of 0 saved, the form untouched", again=False)
    golden_board()  # by the Operator: judged by the recipe
    win.set_user("engineer")
    ratio = ctx.recipe(BOARD)[1]
    ratio.warn_ratio /= 2  # saved on the Recipe Editor, say: a value the form does not hold, which judges too
    ctx.save_recipe(ratio)
    operator_signs_in("a warn ratio saved since an Operator's board was inspected", again=True)
    win.set_user("engineer")
    _ai_off(ctx)
    win.navigate("Home")
    win.navigate("Compare")  # the form takes the revision with the AI check off
    compare.ai_thr.tick.setChecked(True)
    compare.ai_thr.field.setValue(500.0)
    golden_board()
    assert compare.btn_save.isEnabled() and [k for k, _, _ in compare._changes()] == ["anomaly_threshold"], "S28d"
    operator_signs_in("an AI score threshold not saved, the AI check off", again=False)
    win.set_user("engineer")
    compare.ai_thr.tick.setChecked(True)
    compare.ai_thr.field.setValue(500.0)
    compare.use_golden()  # still worked out at the sign-in: the recipe's AI check off, so its threshold judges nothing
    operator_signs_in("an AI score threshold not saved, the AI check off, the board still worked out", again=False)
    win.set_user("engineer")
    roi = ctx.recipe(BOARD)[1]  # the AI check off: no ROI check, so an ROI only names the defects in it, by its type
    roi.rois = [ROI("U1", "Presence", 0, 0, 4000, 4000), ROI("off", enabled=False)]
    ctx.save_recipe(roi)
    win.navigate("Home")
    win.navigate("Compare")
    golden_board()
    stage_2 = {"height_min": 0.5, "height_max": 1.0, "volume_min": 2.0, "volume_max": 3.0, "side": "Bottom"}
    for i, values, again in (
        (0, {"ai_score": 0.5}, False),
        (0, {"name": "U2"}, False),
        (0, stage_2, False),  # which nothing reads in this build, the AI check on or off
        (1, {"x": 9, "ai_score": 0.5}, False),  # a disabled ROI judges nothing
        (0, {"type": "Height"}, True),  # its defects named Pin Height Error, Major, not Missing Component, Critical
        (0, {"x": 3000}, True),  # moved off the defects it named: they are named Anomaly now
    ):
        win.set_user("engineer")
        roi.rois[i] = replace(roi.rois[i], **values)
        ctx.save_recipe(roi)
        operator_signs_in(f"ROI {i + 1}'s {', '.join(values)} saved since, the AI check off", again)
    win.set_user("engineer")
    roi.use_ai, roi.rois[0].x = True, 0  # ROI 1 over the board again, now checked by the AI model's map
    roi.rois.append(ROI("U9", "Polarity", w=4000, h=4000))  # over the defects too, behind ROI 1, which names them
    ctx.save_recipe(roi)
    win.navigate("Home")
    win.navigate("Compare")
    golden_board()
    for i, values, again in (  # ROI 1's AI score and name judge the board now, its Stage 2 values and ROI 2 still not
        (0, {"height_max": 4.0, "side": "Top"}, False),
        (1, {"x": 5, "ai_score": 0.3}, False),  # a disabled ROI judges nothing with the AI check on either
        (0, {"ai_score": 0.7}, True),
        (0, {"name": "U3"}, True),
    ):
        win.set_user("engineer")
        roi.rois[i] = replace(roi.rois[i], **values)
        ctx.save_recipe(roi)
        operator_signs_in(f"ROI {i + 1}'s {', '.join(values)} saved since, the AI check on", again)
    win.set_user("engineer")
    roi.rois.reverse()  # ROI 3 now first over the defects: they are named Polarity Error, not Pin Height Error
    ctx.save_recipe(roi)
    operator_signs_in("ROI 1 and ROI 3, both over the defects, swapped, the AI check on", again=True)
    win.set_user("engineer")
    switched = ctx.recipe(BOARD)[1]
    switched.use_ai, switched.use_compare = True, False  # the AI model alone judges (review)
    ctx.save_recipe(switched)
    win.navigate("Home")
    win.navigate("Compare")  # the form takes that revision
    compare.diff_thr.setValue(compare.diff_thr.value() + 7)
    assert golden_board().compare is None and ai_check(compare.res) == "RAN"
    assert compare.btn_save.isEnabled() and [k for k, _, _ in compare._changes()] == ["diff_threshold"], "S28d"
    operator_signs_in("a Pixel difference not saved, the Golden board comparison off", again=False)
    win.set_user("engineer")
    compare.min_area.setValue(compare.min_area.value() + 1)  # it also sizes the AI model's defects (verification)
    golden_board()
    operator_signs_in("a Minimum defect area not saved, the Golden board comparison off", again=True)
    win.set_user("engineer")
    switched.use_compare = True
    ctx.save_recipe(switched)
    win.navigate("Home")
    win.navigate("Compare")
    compare.diff_thr.setValue(compare.diff_thr.value() + 7)
    compare.use_golden()  # still worked out at the sign-in: held by the recipe, not by the result shown before it
    operator_signs_in("a Pixel difference not saved, the comparison on again, the board still worked out", again=True)
    win.set_user("engineer")
    ctx.db.execute("UPDATE models SET active=0 WHERE board_model=?", (BOARD,))  # the AI check on, but it cannot run
    win.navigate("Home")
    win.navigate("Compare")
    compare.ai_thr.tick.setChecked(True)
    compare.ai_thr.field.setValue(500.0)
    assert ai_check(golden_board()) == "NO_AI_MODEL"
    operator_signs_in("an AI score threshold not saved, no AI model active", again=False)
    win.set_user("engineer")
    ctx.db.execute("UPDATE models SET active=1 WHERE board_model=?", (BOARD,))  # its one AI model again
    ctx.db.execute("UPDATE board_models SET reference_image=NULL WHERE name=?", (BOARD,))  # the comparison on, no
    win.navigate("Home")  # Golden board to compare with
    win.navigate("Compare")
    compare.diff_thr.setValue(compare.diff_thr.value() + 7)
    assert golden_board().compare is None and ai_check(compare.res) == "RAN"
    operator_signs_in("a Pixel difference not saved, no Golden board set", again=False)


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
    and then opens Compare, or an Engineer does after the Operator (review round 4), the Engineer's run then stopped
    even when it ends before Compare is opened (review). From the sign-in the page, shown or hidden, never shows its
    verdict, table or "why" (review). The form is read at the sign-in only, and an Engineer's run stopped by
    Cancel stays cancelled (review round 3); a board an Engineer inspected with the recipe's own thresholds keeps its
    verdict when an Operator signs in, and is not inspected again (review round 4)."""
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

    def now() -> tuple[str, int, str]:
        return compare.verdict.text(), compare.metrics.rowCount(), compare.why.toPlainText()

    def judged() -> bool:
        """What the Operator sees, each change of it, until the recipe's run ends."""
        seen.extend([now()] if now() != seen[-1] else [])
        return ctx.jobs.idle() and compare._bg is None

    gate, started, inspect = threading.Event(), threading.Event(), AppContext.inspect

    def held(self: AppContext, *args: Any, **kwargs: Any) -> InspectionResult:
        started.set()
        assert gate.wait(20)
        return inspect(self, *args, **kwargs)

    monkeypatch.setattr(AppContext, "inspect", held)
    steps = ((0, 0, 0), (1, 0, 0), (1, 1, 0), (1, 1, 1), (0, 1, 1), (0, 1, 0))
    for in_flight, elsewhere, engineer_next in steps:
        step = f"in flight {in_flight}, on another page {elsewhere}, an Engineer next {engineer_next}"
        win.set_user("engineer")
        _pass_every_check(compare)
        shown.clear()
        gate.clear() if in_flight and elsewhere else gate.set()  # held: it ends after the sign-ins on Home (review)
        started.clear()
        if in_flight:
            compare._clear_result()  # nothing shown, as after Cancel: the run is all there is to replace
        compare.use_golden()
        if in_flight:
            assert compare._bg is not None and not shown, "the Engineer's inspection is still worked out"
            assert gate.is_set() or started.wait(20), "in the engine, not still queued"
        else:
            qtbot.waitUntil(lambda: compare._bg is None and bool(shown), timeout=20000)
            assert shown == ["WARN"], "the Engineer's thresholds judge the board WARN"
        win.navigate("Home" if elsewhere else "Compare")
        win.set_user("operator")
        if engineer_next:  # an Engineer signs in next, before Compare is opened (review round 4)
            win.set_user("engineer")
        if elsewhere:  # the Engineer's run ends while Compare is hidden: none of it lands there (review)
            gate.set()
            qtbot.waitUntil(lambda: ctx.jobs.idle() and compare._bg is None, timeout=20000)
            qtbot.wait(50)  # a result still on its way lands now
            no_more = [] if in_flight else ["WARN"]  # what was shown before the sign-in
            assert now() == (NO_VERDICT, 0, "") and shown == no_more, f"hidden Compare shows none of it: {step}"
        win.navigate("Compare")
        seen[:] = [now()]
        qtbot.waitUntil(judged, timeout=20000)
        assert seen[0] == (NO_VERDICT, 0, ""), f"from the sign-in, no verdict, table or why of the Engineer's: {step}"
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
    win.set_user("engineer")
    compare.use_golden()  # with the recipe's own thresholds, which the form holds since the sign-in
    qtbot.waitUntil(lambda: ctx.jobs.idle() and compare._bg is None, timeout=20000)
    assert shown == ["WARN", "NG", "NG"]
    win.set_user("operator")  # the recipe judged it: its verdict stays, and it is not inspected again (review)
    assert compare._bg is None and compare.verdict.text() == theme.verdict_label("NG") and shown == ["WARN", "NG", "NG"]


def test_req_set_021_a_re_evaluation_over_a_second_shows_a_busy_indicator_over_the_decision_table(
    qtbot: QtBot,
    trained_ctx: AppContext,
    ng_board: Path,
    monkeypatch: pytest.MonkeyPatch,
    dialogs: list[tuple[str, str]],
) -> None:
    """REQ-SET-021, and the sketch's busy indicator for any recompute over 1 s (review): Re-evaluate on a stored result
    that takes over a second shows "Re-evaluating…" and the seconds so far over the decision table and the "why" box,
    where the checks tried will appear, and nothing in its first second; Re-evaluate is off meanwhile, so a second
    press starts no second job (the sketch's busy pattern, review); at the window's least size the indicator's text,
    bar and Cancel, shown from 10 s, fit inside it (review). Pressed with Space, its focus waits in the "why" box, one
    Tab before Cancel once that shows, so a second Space presses nothing, Save to Recipe next in the Tab order included,
    and comes back when the run ends, unless moved (review). It goes when "Would be" shows or a refusal's dialog does,
    not at the job's end, which a loaded pool thread may signal later, with Cancel still there to take the focus
    (verification), and at once when a threshold changes or Cancel is pressed, the stored checks then showing, no answer
    landing after and no worker held. Cancel, by Tab and Space after Ctrl+R in the "why" box or by a click after Ctrl+R
    on Show, gives the focus to Re-evaluate, so a second Space never sets the AI score threshold's tick, next after
    Cancel in the Tab order; Ctrl+R in the "why" box leaves the focus there when the answer comes, and an answer within
    the first second leaves no indicator to show after it while the job's end is still to come (verification). Save to
    Recipe is off meanwhile too, so Ctrl+S opens no sheet over the run, and on again with Cancel: Ctrl+S then opens the
    sheet at once, the worker Cancel stopped still held, and Save Revision, pressed with Space, gives the focus to
    Re-evaluate, as Cancel does, Save to Recipe being off then, so a second Space re-evaluates and never sets the tick
    (S28d). Ctrl+R with the focus on Save to Recipe, back there from the sheet by Esc, which the run turns off, sends
    it to the "why" box too, and to Re-evaluate at the run's end: Qt passed it on to the header's board model list,
    where Down picked another board model (S28d, review)."""
    ctx = trained_ctx
    win, compare, _ = _stored_on_compare(qtbot, ctx, ng_board, "Engineer")
    win.resize(win.minimumSizeHint())  # the panel at its least height (review)
    stored = _table(compare)
    _pass_every_check(compare)
    gate, judge_again, fail = threading.Event(), AppContext.re_evaluate, [False]

    def held(self: AppContext, *args: Any) -> InspectionResult:
        assert gate.wait(20)
        if fail[0]:  # refused: a map deleted since, say
            raise AoiError("AOI-CMP-004", file=ng_board.name, missing="AI score map", days=7)
        return judge_again(self, *args)

    monkeypatch.setattr(AppContext, "re_evaluate", held)
    monkeypatch.setattr(BusyOverlay, "DETAIL_AFTER_S", 1.2)  # what shows from 10 s, sooner
    end, call = threading.Event(), Job._call

    def ending(job: Job[Any], event: str, *args: Any) -> None:
        if event == "finished":
            end.wait(20)  # on the pool thread, which, loaded, may signal a job's end well after its answer
        call(job, event, *args)

    end.set()
    monkeypatch.setattr(Job, "_call", ending)

    def over_the_checks() -> list[BusyOverlay]:
        """The busy indicators shown over the decision table."""
        found = [(o, o.parentWidget()) for o in compare.findChildren(BusyOverlay) if o.isVisible()]
        return [o for o, on in found if on is compare.metrics or on is not None and on.isAncestorOf(compare.metrics)]

    revisions = len(ctx.recipe_history(BOARD))
    for then in ("the answer", "a refusal", "a threshold changed", "Cancel"):
        gate.clear()
        compare.btn_try.setFocus(Qt.FocusReason.TabFocusReason)  # by keyboard (review)
        qtbot.keyClick(compare.btn_try, Qt.Key.Key_Space)
        trying = compare._trying
        assert trying is not None and not over_the_checks(), "nothing in the first second, so quick work never flickers"
        try:
            qtbot.waitUntil(lambda: any(o.cancel_button.isVisible() for o in over_the_checks()), timeout=10000)
        except qtbot.TimeoutError:
            pytest.fail(f"no busy indicator with Cancel over the decision table, before {then}")
        qtbot.wait(100)  # laid out with Cancel shown
        (busy,) = over_the_checks()
        for part in (busy.label, busy.bar, busy.cancel_button):  # none cut off or squeezed (review)
            fits = busy.rect().contains(part.geometry()) and part.height() >= part.sizeHint().height()
            assert fits, (type(part).__name__, part.geometry(), part.sizeHint(), busy.size())
        over = busy.parentWidget()
        assert over is not None and over.isAncestorOf(compare.why) and busy.geometry() == over.rect(), "and the why"
        assert busy.label.text().startswith("Re-evaluating…")
        assert compare.would_be.isHidden() and _table(compare) == stored
        assert not compare.act_try.isEnabled(), "Re-evaluate is off while it runs"
        qtbot.keyClick(win, Qt.Key.Key_S, Qt.KeyboardModifier.ControlModifier)  # Save to Recipe's key, then let go
        qtbot.keyRelease(win, Qt.Key.Key_S)
        assert compare.sheet.isHidden() and not compare.act_save.isEnabled(), "nor does Save to Recipe (S28d)"
        focus = QApplication.focusWidget()
        assert focus is not None
        qtbot.keyClick(focus, Qt.Key.Key_Space)  # a second Space, where the focus went
        assert len(ctx.recipe_history(BOARD)) == revisions, "a second Space saves no recipe revision (review)"
        assert QApplication.focusWidget() is compare.why, "the focus waits under the indicator, one Tab before Cancel"
        _press(qtbot, win, compare)
        assert compare._trying is trying is compare._bg, "a second press starts no second job"
        if then in ("the answer", "a refusal"):
            end.clear()  # the job's end signalled only after the checks below: the indicator goes with the answer
            fail[0] = then == "a refusal"
            gate.set()
            qtbot.waitUntil(lambda: compare.would_be.isVisible() or bool(dialogs), timeout=20000)
            assert not over_the_checks() and compare.act_try.isEnabled(), f"the indicator goes with {then}, not later"
            assert (_table(compare) != stored) == (not fail[0]), f"{then}: the checks tried show with an answer only"
            assert compare.act_save.isEnabled(), f"Save to Recipe on again with {then} (S28d)"
            assert QApplication.focusWidget() is compare.btn_try, f"the focus back on Re-evaluate with {then}"
            end.set()
            qtbot.waitUntil(lambda: compare._bg is None, timeout=20000)
            assert [title.split()[0] for title, _ in dialogs] == ["AOI-CMP-004"] * fail[0] and not over_the_checks()
            fail[0] = False
            dialogs.clear()
            continue
        if then == "Cancel":
            qtbot.keyClick(compare.why, Qt.Key.Key_Tab)
            assert QApplication.focusWidget() is busy.cancel_button, "one Tab from the focus to Cancel"
            qtbot.keyClick(busy.cancel_button, Qt.Key.Key_Space)
        else:
            compare.min_area.setFocus(Qt.FocusReason.TabFocusReason)  # the Engineer moves the focus there
            qtbot.keyClick(compare.min_area, Qt.Key.Key_Up)
        assert not over_the_checks() and _table(compare) == stored, f"the indicator goes at once with {then}"
        assert compare.act_try.isEnabled(), f"Re-evaluate is on again at once with {then}"
        assert compare.act_save.isEnabled(), f"Save to Recipe on again at once with {then} (S28d)"
        back, where = (compare.btn_try, "back on Re-evaluate") if then == "Cancel" else (compare.min_area, "kept")
        assert QApplication.focusWidget() is back, f"the focus {where} after {then}"
        gate.set()
        qtbot.waitUntil(lambda: ctx.jobs.idle() and compare._bg is None, timeout=20000)
        qtbot.wait(50)  # an answer still on its way lands now
        assert compare.would_be.isHidden() and _table(compare) == stored and not over_the_checks() and not dialogs
        assert compare._trying is None, f"no worker held past its end after {then} (#132)"
    compare.ai_thr.tick.setChecked(False)  # next after Cancel in the Tab order: a Space there would set it
    for start, how in ((compare.why, "by Tab and Space"), (compare.mode, "by a click")):  # Ctrl+R pressed elsewhere
        gate.clear()
        start.setFocus(Qt.FocusReason.TabFocusReason)
        _press(qtbot, win, compare)
        qtbot.waitUntil(lambda: any(o.cancel_button.isVisible() for o in over_the_checks()), timeout=10000)
        (busy,) = over_the_checks()
        if start is compare.why:
            qtbot.keyClick(compare.why, Qt.Key.Key_Tab)
            assert QApplication.focusWidget() is busy.cancel_button, "one Tab from the why box to Cancel once it shows"
            qtbot.keyClick(busy.cancel_button, Qt.Key.Key_Space)
        else:
            qtbot.mouseClick(busy.cancel_button, Qt.MouseButton.LeftButton)
        focus = QApplication.focusWidget()
        assert focus is not None
        qtbot.keyClick(focus, Qt.Key.Key_Space)  # a second Space, where Cancel left the focus
        assert not compare.ai_thr.tick.isChecked(), f"a second Space after Cancel {how} sets no tick (verification)"
        assert focus is compare.btn_try and compare._trying is not None, f"Cancel {how}: the focus on Re-evaluate"
        gate.set()
        qtbot.waitUntil(compare.would_be.isVisible, timeout=20000)
        assert QApplication.focusWidget() is compare.btn_try and len(ctx.recipe_history(BOARD)) == revisions, how
    compare.why.setFocus(Qt.FocusReason.TabFocusReason)
    end.clear()  # an answer within the indicator's first second, the job's end signalled after it (verification)
    _press(qtbot, win, compare)  # after a run pressed with Space, which takes its focus back at the end
    qtbot.waitUntil(compare.would_be.isVisible, timeout=20000)
    assert QApplication.focusWidget() is compare.why, "Ctrl+R in the why box: the focus stays there (verification)"
    qtbot.wait(1500)  # past the indicator's first second, the job's end still to come
    assert not compare.try_busy.isVisible(), "no indicator after the answer: its timer stopped with it (verification)"
    end.set()
    qtbot.waitUntil(lambda: compare._bg is None, timeout=20000)
    gate.clear()  # where Cancel and Save to Recipe's sheet meet (S28d)
    compare.mode.setFocus(Qt.FocusReason.TabFocusReason)
    _press(qtbot, win, compare)
    qtbot.waitUntil(lambda: any(o.cancel_button.isVisible() for o in over_the_checks()), timeout=10000)
    qtbot.mouseClick(over_the_checks()[0].cancel_button, Qt.MouseButton.LeftButton)
    qtbot.keyClick(win, Qt.Key.Key_S, Qt.KeyboardModifier.ControlModifier)  # at once: the worker stopped is still held
    qtbot.keyRelease(win, Qt.Key.Key_S)
    qtbot.keyClicks(compare.reason, "after Cancel")
    compare.btn_confirm.setFocus(Qt.FocusReason.TabFocusReason)  # two Tabs from the reason, past the sheet's Cancel
    qtbot.keyClick(compare.btn_confirm, Qt.Key.Key_Space)  # Save Revision: nothing differs then, Save to Recipe off
    focus = QApplication.focusWidget()
    assert focus is not None
    qtbot.keyClick(focus, Qt.Key.Key_Space)  # a second Space, where Save Revision left the focus
    assert not compare.ai_thr.tick.isChecked() and len(ctx.recipe_history(BOARD)) == revisions + 1, "one revision"
    assert focus is compare.btn_try and compare._trying is not None, "Save Revision: the focus on Re-evaluate (S28d)"
    gate.set()
    qtbot.waitUntil(compare.would_be.isVisible, timeout=20000)
    ctx.ensure_board_model("ZZZ")  # sorted after BOARD in the header's list, so Down there would pick it (S28d, review)
    win._reload_board_models(BOARD)
    compare.min_area.setValue(compare.min_area.value() + 1)  # a threshold differs again: Save to Recipe on
    qtbot.keyClick(win, Qt.Key.Key_S, Qt.KeyboardModifier.ControlModifier)  # the sheet, then Esc in it
    qtbot.keyRelease(win, Qt.Key.Key_S)
    qtbot.keyClick(compare.reason, Qt.Key.Key_Escape)
    assert QApplication.focusWidget() is compare.btn_save, "the focus back on Save to Recipe, which a run turns off"
    gate.clear()
    _press(qtbot, win, compare)
    focus, going = QApplication.focusWidget(), compare._trying is not None
    assert focus is not None and going
    qtbot.keyClick(focus, Qt.Key.Key_Down)  # Down, where the focus went while the run goes
    picked = win.board_model
    gate.set()
    qtbot.waitUntil(lambda: ctx.jobs.idle() and compare._bg is None, timeout=20000)
    assert focus is compare.why and picked == BOARD, f"the focus on {type(focus).__name__}, board model {picked}"
    assert compare.would_be.isVisible() and QApplication.focusWidget() is compare.btn_try, "on Re-evaluate at its end"
    qtbot.keyClick(compare.btn_try, Qt.Key.Key_Down)
    assert win.board_model == BOARD and len(ctx.recipe_history(BOARD)) == revisions + 1, "Down there changes nothing"


def test_req_set_021_however_a_re_evaluation_starts_and_ends_a_further_space_writes_nothing(
    qtbot: QtBot, trained_ctx: AppContext, ng_board: Path, monkeypatch: pytest.MonkeyPatch, dialogs: Dialogs
) -> None:
    """Each way a re-evaluation of a stored result starts (Space on Re-evaluate, a click on it, Ctrl+R with the focus in
    the "why" box, in Show: or in the decision table) with each way it ends (its answer, an error, Cancel by Space or by
    a click, its answer or an error landing while Cancel holds the focus, an Operator signing in while Cancel or the AI
    score threshold's tick does, its answer while another window is in front, with Cancel holding the focus or not, when
    no control has hasFocus(), and an Operator's sign-in then with the tick holding it, and another stored result shown,
    as Inspection's "Compare with Golden board ›" shows one, with Cancel holding the focus or not or another window in
    front, which turns Re-evaluate off until its pictures and maps have loaded): the focus ends on Re-evaluate, where
    Ctrl+R found it, or, once the sign-in hides the panel, in the "why" box, which an Engineer's sign-in next leaves it
    in, never on a control of the panel that writes (Save to Recipe, a threshold, the tick), and a further Space saves
    no recipe revision and sets no tick (second and third verification, review). With no run, an Operator's sign-in puts
    a focus on any control of the panel in the "why" box too, where an Admin's leaves it, and leaves one on Show: there
    (review)."""
    ctx = trained_ctx
    win, compare, first = _stored_on_compare(qtbot, ctx, ng_board, "Engineer")
    ctx.inspect_file(BOARD, str(ng_board))  # a second stored result, for the ends that show another
    shown_next = [next(r["id"] for r in ctx.inspections(board_model=BOARD) if r["id"] != first), first]
    other = QWidget()  # another window, in front while a run ends
    qtbot.addWidget(other)
    gate, judge_again, fail = threading.Event(), AppContext.re_evaluate, [False]

    def held(self: AppContext, *args: Any) -> InspectionResult:
        assert gate.wait(20)
        if fail[0]:
            raise AoiError("AOI-CMP-004", file=ng_board.name, missing="AI score map", days=7)
        return judge_again(self, *args)

    monkeypatch.setattr(AppContext, "re_evaluate", held)
    monkeypatch.setattr(BusyOverlay, "SHOW_AFTER_S", 0.0)  # the indicator and its Cancel at its first tick, not at 10 s
    monkeypatch.setattr(BusyOverlay, "DETAIL_AFTER_S", 0.0)
    cancel, panel = compare.try_busy.cancel_button, _panel(compare)
    writes = set(panel.findChildren(QWidget)) - {compare.btn_try}
    starts = {
        "Space on Re-evaluate": compare.btn_try,  # where the focus is before
        "a click on Re-evaluate": compare.why,
        "Ctrl+R in the why box": compare.why,
        "Ctrl+R in Show:": compare.mode,
        "Ctrl+R in the decision table": compare.metrics,
    }
    ends = ("answer", "error", "Cancel by Space", "Cancel by a click", "answer on Cancel", "error on Cancel")
    ends += ("Operator's sign-in on Cancel", "Operator's sign-in on the tick")
    ends += ("answer behind another window", "answer on Cancel behind another window")  # hasFocus() False for all
    ends += ("Operator's sign-in on the tick behind another window", "another stored result")
    ends += ("another stored result on Cancel", "another stored result behind another window")
    wrong = []

    def space(focus: QWidget) -> None:
        """A further Space where the focus is, and a list it opened, Show:'s say, closed."""
        qtbot.keyClick(focus, Qt.Key.Key_Space)
        if (popup := QApplication.activePopupWidget()) is not None:
            popup.close()
            win.activateWindow()  # which the offscreen platform leaves inactive once a popup closes
            qtbot.waitUntil(lambda: QApplication.activeWindow() is win, timeout=5000)

    for (start, before), end in itertools.product(starts.items(), ends):
        gate.clear()
        fail[0], revisions = "error" in end, len(ctx.recipe_history(BOARD))
        compare.ai_thr.tick.setChecked(False)  # a Space on it would set it
        before.setFocus(Qt.FocusReason.TabFocusReason)
        if start.startswith("Ctrl+R"):
            _press(qtbot, win, compare)
        elif start.startswith("Space"):
            qtbot.keyClick(compare.btn_try, Qt.Key.Key_Space)
        else:
            qtbot.mouseClick(compare.btn_try, Qt.MouseButton.LeftButton)
        qtbot.waitUntil(cancel.isVisible, timeout=10000)
        if "Cancel" in end:
            cancel.setFocus(Qt.FocusReason.TabFocusReason)  # reached by Tab, one from the "why" box
        elif "tick" in end:
            compare.ai_thr.tick.setFocus(Qt.FocusReason.TabFocusReason)  # moved to the panel while it runs
        if "behind" in end:
            other.show()
            other.activateWindow()
            qtbot.waitUntil(lambda: not win.isActiveWindow(), timeout=5000)
        if end == "Cancel by Space":
            qtbot.keyClick(cancel, Qt.Key.Key_Space)
        elif end == "Cancel by a click":
            qtbot.mouseClick(cancel, Qt.MouseButton.LeftButton)
        elif "sign-in" in end:
            win.set_user("operator")
        elif "stored result" in end:
            win.open_stored(shown_next[0])  # as Inspection's button opens one, the focus where it is
            shown_next.reverse()
        gate.set()
        qtbot.waitUntil(lambda: ctx.jobs.idle() and compare._bg is None, timeout=20000)
        if "behind" in end:
            other.hide()
            win.activateWindow()  # in front again: the focus is the control the window holds it on
            qtbot.waitUntil(win.isActiveWindow, timeout=5000)
        back = "Re-evaluate" in start or "Cancel" in end  # pressed, or Cancel, which hides: back on Re-evaluate
        want = compare.why if "sign-in" in end else compare.btn_try if back else before
        focus, shown = QApplication.focusWidget(), [title.split()[0] for title, _ in dialogs]
        assert focus is not None, (start, end)
        space(focus)
        qtbot.waitUntil(lambda: ctx.jobs.idle() and compare._bg is None, timeout=20000)  # a run it started
        saved, ticked = len(ctx.recipe_history(BOARD)) - revisions, compare.ai_thr.tick.isChecked()
        if focus is not want or focus in writes or saved or ticked or shown != ["AOI-CMP-004"] * fail[0]:
            name = f"{type(focus).__name__} {getattr(focus, 'text', str)()!r}"
            wrong.append(f"{start}, ended by {end}: focus on {name}, revisions +{saved}, ticked {ticked}, {shown}")
        dialogs.clear()
        if "sign-in" in end:
            win.set_user("engineer")  # Re-evaluate on again: the focus the sign-in put in the "why" box stays there
            if QApplication.focusWidget() is not compare.why:
                wrong.append(f"{start}, ended by {end}: an Engineer's sign-in after it moved the focus")
    for control in (*panel.findChildren(QAbstractSpinBox), *panel.findChildren(QAbstractButton), compare.mode):
        compare.ai_thr.tick.setChecked(True)  # its field takes the focus only then
        if control is compare.min_size.mm and control.isHidden():  # DefectSizeField's mm, hidden without a scale (S29)
            continue
        control.setFocus(Qt.FocusReason.TabFocusReason)
        win.set_user("admin")
        kept, revisions = QApplication.focusWidget() is control, len(ctx.recipe_history(BOARD))
        win.set_user("operator")  # with no run
        focus, want = QApplication.focusWidget(), compare.why if panel.isAncestorOf(control) else control
        assert focus is not None, control
        space(focus)
        if focus is not want or not kept or len(ctx.recipe_history(BOARD)) != revisions:
            on = [f"{type(w).__name__} {getattr(w, 'text', str)()!r}" for w in (control, focus)]
            wrong.append(f"no run, the focus on {on[0]}, kept by an Admin's sign-in {kept}, an Operator's: on {on[1]}")
        win.set_user("engineer")
    assert not wrong, "\n".join(wrong)


def test_req_set_021_a_stored_result_opened_from_inspection_never_leaves_the_focus_on_save_to_recipe(
    qtbot: QtBot, trained_ctx: AppContext, ng_board: Path, monkeypatch: pytest.MonkeyPatch, dialogs: Dialogs
) -> None:
    """Inspection's "Compare with Golden board ›", by a click or by Space, after a re-evaluation on Compare gave the
    focus back to Re-evaluate, or with one still running there: Compare shows with the focus it had, which Qt gives a
    page shown again, and Re-evaluate goes off until the result's pictures and maps have loaded. The focus waits in the
    "why" box meanwhile and is on Re-evaluate once they have, never passed on to Save to Recipe, where one more Space
    saved the Engineer's unsaved thresholds as a recipe revision (third verification)."""
    ctx = trained_ctx
    win, compare, _ = _stored_on_compare(qtbot, ctx, ng_board, "Engineer")
    insp = win.pages["Inspection"]
    gate, judge_again = threading.Event(), AppContext.re_evaluate

    def held(self: AppContext, *args: Any) -> InspectionResult:
        assert gate.wait(20)
        return judge_again(self, *args)

    monkeypatch.setattr(AppContext, "re_evaluate", held)
    wrong = []
    for by, going in itertools.product(("a click", "Space"), (False, True)):
        compare.min_area.setValue(compare.min_area.value() + 7)  # tried, not saved
        revisions = len(ctx.recipe_history(BOARD))
        (gate.clear if going else gate.set)()
        compare.btn_try.setFocus(Qt.FocusReason.TabFocusReason)
        qtbot.keyClick(compare.btn_try, Qt.Key.Key_Space)
        if not going:
            qtbot.waitUntil(lambda: compare.would_be.isVisible() and compare._bg is None, timeout=20000)
        item = win.nav.visualItemRect(win._items["Inspection"])
        qtbot.mouseClick(win.nav.viewport(), Qt.MouseButton.LeftButton, pos=item.center())
        last = insp.last_id
        insp._set_queue([ng_board])
        insp.next_board()  # inspected and stored on Inspection
        qtbot.waitUntil(lambda: insp.worker is None, timeout=30000)  # a re-evaluation held on Compare still going
        assert insp.last_id not in (None, last)
        if by == "Space":
            insp.btn_compare.setFocus(Qt.FocusReason.TabFocusReason)
            qtbot.keyClick(insp.btn_compare, Qt.Key.Key_Space)
        else:
            qtbot.mouseClick(insp.btn_compare, Qt.MouseButton.LeftButton)
        assert win.stack.currentWidget() is compare and not compare.act_try.isEnabled(), "off until it has loaded"
        meanwhile = QApplication.focusWidget()
        gate.set()
        qtbot.waitUntil(lambda: compare.loaded and ctx.jobs.idle() and compare._bg is None, timeout=30000)
        focus = QApplication.focusWidget()
        assert focus is not None
        qtbot.keyClick(focus, Qt.Key.Key_Space)  # one more Space
        qtbot.waitUntil(lambda: ctx.jobs.idle() and compare._bg is None, timeout=20000)
        saved = len(ctx.recipe_history(BOARD)) - revisions
        if meanwhile is not compare.why or focus is not compare.btn_try or saved or dialogs:
            names = [f"{type(w).__name__} {getattr(w, 'text', str)()!r}" for w in (meanwhile, focus)]
            wrong.append(f"by {by}, a run going {going}: focus {names[0]}, then {names[1]}; revisions +{saved}")
    assert not wrong, "\n".join(wrong)


def test_req_cmp_005_reevaluate_at_5_mp_answers_within_300_ms_off_the_window_thread(
    qtbot: QtBot,
    trained_ctx: AppContext,
    board_5mp: Path,  # noqa: F811  # the fixture, imported from test_no_freeze
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A stored 5 MP NG result with both maps, judged against a 5 MP Golden board, opened on Compare by an Engineer:
    Re-evaluate judges it again on the pool thread, so the window never stalls while it works (REQ-SET-021), and with
    nothing inspected and no AI model loaded "Would be" shows within 300 ms of the key, the median of five presses."""
    ctx = trained_ctx
    iid = ctx.db.inspection_id(_store_5mp(ctx, board_5mp))
    assert iid is not None
    win = _window(qtbot, ctx, "Engineer")
    compare = win.pages["Compare"]
    assert isinstance(compare, ComparePage)
    win.navigate("Compare")
    qtbot.waitUntil(ctx.jobs.idle, timeout=10000)
    compare.show_stored(iid)
    qtbot.waitUntil(lambda: compare.loaded and compare._bg is None, timeout=30000)
    _refuse_inspection(monkeypatch)
    with heavy_calls(stall="AppContext.re_evaluate") as calls, gap_meter(qtbot) as g:
        _press(qtbot, win, compare)
        assert compare.would_be.isHidden(), "judged on a pool thread: no answer before the key returns"
        qtbot.waitUntil(compare.would_be.isVisible, timeout=20000)
    assert_off_ui_thread(calls, "AppContext.re_evaluate")
    assert g["longest_s"] < BUDGET_S, g
    took = []
    for _ in range(5):
        compare.min_area.setValue(compare.min_area.value() + 1)  # what was tried goes, and is tried again
        t0 = perf_counter()
        _press(qtbot, win, compare)
        qtbot.waitUntil(compare.would_be.isVisible, timeout=10000)
        took.append(perf_counter() - t0)
    median, worst = statistics.median(took), max(took)
    print(f"Re-evaluate on Compare at 5 MP: median {median * 1000:.0f} ms, worst {worst * 1000:.0f} ms")
    assert median < 0.3, took
