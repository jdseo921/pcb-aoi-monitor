"""REQ-CMP-003 and REQ-INSP-009 (S26): Compare shows a stored result as it was decided and never inspects the board
again: its decision table equals the stored checks row for row for every board of the synthetic regression set, one
click from Inspection opens it within 300 ms at 5 MP with the failing rows highlighted, and a note names the versions
used."""

from __future__ import annotations

import hashlib
import sqlite3
from pathlib import Path
from time import perf_counter
from typing import Any

import cv2
import numpy as np
import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QInputDialog
from pytestqt.qtbot import QtBot

from aoi.core import anomaly
from aoi.core.explain import explain
from aoi.core.imaging import save_image
from aoi.core.inspector import NO_AI_NOTE, NO_GOLDEN_NOTE, Check, InspectionResult, Inspector, draw_overlay
from aoi.core.recipe import Recipe
from aoi.core.services import AppContext
from aoi.times import to_local
from aoi.ui import theme
from aoi.ui.pages.base import cell_item
from aoi.ui.pages.compare import JUDGED, ComparePage
from tests.conftest import wrapped
from tests.regression import make_regression_set as rs
from tests.test_alarms_and_errors import _log_rows
from tests.test_no_freeze import board_5mp  # noqa: F401  # the 5 MP fixture
from tests.test_req_done_in_v01 import BOARD, _inspect_one, _window

FAILING = ("NG", "WARN")


def _refuse_inspection(monkeypatch: pytest.MonkeyPatch) -> None:
    """A stored result comes from the record: an inspection or an AI model load from here on fails the test."""

    def refuse(*a: object, **k: object) -> None:
        raise AssertionError("Compare inspected the board or loaded a model instead of showing the stored result")

    for owner, name in ((Inspector, "inspect"), (AppContext, "inspect"), (anomaly.AnomalyModel, "load")):
        monkeypatch.setattr(owner, name, refuse)


def _table(page: ComparePage) -> list[tuple[object, ...]]:
    """The decision table's rows as (check, source, value, threshold, rule, result, row colour)."""
    t, rows = page.metrics, []
    for r in range(t.rowCount()):
        cells = [cell_item(t, r, c) for c in range(6)]
        brush = cells[5].background()
        color = brush.color().name().lower() if brush.style() != Qt.BrushStyle.NoBrush else None
        rows.append((*(c.data(Qt.ItemDataRole.DisplayRole) for c in cells), color))  # floats as fill_table set them
    return rows


def _expected(page: ComparePage, checks: list[dict[str, object]]) -> list[tuple[object, ...]]:
    """The stored checks as the table must show them: names in the UI language, values to 4 decimals, NG and WARN
    rows in the verdict's colour."""
    rows = []
    for c in checks:
        fields = {k: c[k] for k in ("value", "threshold", "rule", "source", "explain", "region")}
        check = Check(name=str(c["metric"]), verdict=str(c["result"]), **fields)  # type: ignore[arg-type]
        name, source, rule = page._check_text(check)
        color = theme.VERDICT_COLORS[check.verdict].lower() if check.verdict in FAILING else None
        rows.append((name, source, round(check.value, 4), round(check.threshold, 4), rule, check.verdict, color))
    return rows


def test_req_cmp_003_table_equals_stored_checks(
    qtbot: QtBot, trained_ctx: AppContext, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Every board of the synthetic regression set, inspected and stored through the engine, then opened on Compare from
    its record: the verdict and the decision table are the stored ones, row for row, the failing rows highlighted and
    the inspection time last; the engine is not run again."""
    ctx, out, ids = trained_ctx, tmp_path / "regression", []
    for board in rs.generate(out):
        ctx.inspect_file(BOARD, str(out / board.name))
        ids.append(ctx.inspections(board_model=BOARD)[0]["id"])
    win = _window(qtbot, ctx, "Operator")
    page = win.pages["Compare"]
    assert isinstance(page, ComparePage)
    win.navigate("Compare")
    qtbot.waitUntil(ctx.jobs.idle, timeout=10000)
    _refuse_inspection(monkeypatch)
    verdicts = set()
    for iid in ids:
        page.show_stored(iid)
        rec, checks, stored = ctx.inspection(iid), ctx.checks_for(iid), ctx.inspection_result(iid)
        assert rec is not None and stored is not None and checks and page.stored and page.stored["id"] == iid
        assert page.verdict.text() == theme.verdict_label(rec["result"])
        rows = _table(page)
        assert rows[:-1] == _expected(page, checks), iid
        tr, ms, spec = page.tr, round(stored.elapsed_ms, 4), "OK" if stored.elapsed_ms < 1000 else "WARN"
        assert rows[-1] == (tr("Inspection time (ms)"), tr("System"), ms, 1000.0, tr("spec < 1 s"), spec, None)
        verdicts.add(rec["result"])
    assert verdicts >= {"OK", "NG"}, "the set holds OK and NG boards"
    qtbot.waitUntil(lambda: ctx.jobs.idle() and page._bg is None, timeout=30000)  # the last picture has landed


def test_req_insp_009_one_click_opens_within_300_ms(
    qtbot: QtBot,
    trained_ctx: AppContext,
    board_5mp: Path,  # noqa: F811  # the fixture, imported from test_no_freeze
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A 5 MP board inspected on Inspection; "Compare with Golden board" opens its record: the verdict, the table with
    failing rows highlighted and the note are on screen when the click returns, within 300 ms, before any picture is
    read; the pictures and stored maps follow from the pool thread. Without a record it opens the file, as before."""
    ctx = trained_ctx
    win = _window(qtbot, ctx, "Operator")
    insp, compare = win.pages["Inspection"], win.pages["Compare"]
    assert isinstance(compare, ComparePage)
    win.navigate("Inspection")
    qtbot.waitUntil(ctx.jobs.idle, timeout=10000)
    insp._set_queue([board_5mp])
    insp.next_board()
    qtbot.waitUntil(lambda: insp.last is not None and insp.worker is None, timeout=60000)
    (row,) = ctx.inspections(board_model=BOARD)
    assert insp.last_id == row["id"] and win.last_inspected is not None and win.last_inspected[2] == row["id"]
    qtbot.waitUntil(ctx.jobs.idle, timeout=10000)
    _refuse_inspection(monkeypatch)
    t0 = perf_counter()
    insp.open_compare()  # the one click
    took = perf_counter() - t0
    checks = ctx.checks_for(row["id"])
    assert win.stack.currentWidget() is compare and compare.verdict.text() == theme.verdict_label(row["result"])
    rows = _table(compare)
    assert rows[:-1] == _expected(compare, checks) and took < 0.3, took
    assert any(r[6] for r in rows[:-1]), "an NG board has highlighted rows"
    assert compare.note.isVisible() and "recipe revision" in compare.note.text()
    assert compare.test_view._pix is None, "the 5 MP picture and maps are read on the pool thread, after the click"
    qtbot.waitUntil(lambda: compare.test_view._pix is not None and compare.ref_view._pix is not None, timeout=20000)
    assert compare.res is not None and compare.res.anomaly_map is not None and compare.res.compare is not None
    assert compare.res.compare.diff_map is not None, "the stored maps serve the heat views"
    compare.mode.setCurrentIndex(2)  # the AI heatmap, drawn from the stored map
    assert compare.test_view._pix is not None and _table(compare)[:-1] == _expected(compare, checks)
    opened: list[str] = []
    monkeypatch.setattr(win, "open_compare", opened.append)
    insp.last_id = None  # as after a failed save: no record to open
    insp.open_compare()
    assert opened == [str(board_5mp)]


def test_req_cmp_003_note_names_the_versions_and_missing_maps(
    qtbot: QtBot,
    trained_ctx: AppContext,
    ng_board: Path,
    monkeypatch: pytest.MonkeyPatch,
    dialogs: list[tuple[str, str]],
) -> None:
    """The note names when and with which versions the result was judged, on the picture judged; inspecting again
    leaves it, and no busy overlay behind; a new recipe revision and model version are named while the table keeps the
    old thresholds and no model loads; AOI-CMP-001 once both maps are gone; a deleted picture says so; Use Last
    Inspected opens the record or inspects a preview; an unknown record gives AOI-CMP-002."""
    ctx = trained_ctx
    res = ctx.inspect_file(BOARD, str(ng_board))
    iid = (rec := ctx.inspections(board_model=BOARD)[0])["id"]  # the record as Logs & Export lists it
    win = _window(qtbot, ctx, "Engineer")
    compare = win.pages["Compare"]
    assert isinstance(compare, ComparePage) and rec is not None
    win.navigate("Compare")
    qtbot.waitUntil(ctx.jobs.idle, timeout=10000)
    compare.show_stored(iid)
    compare.run()  # inspected again from its image file: a fresh inspection, no longer the stored result
    assert compare.stored is None and compare.note.isHidden()
    compare.show_stored(iid)  # while that inspection runs
    qtbot.waitUntil(lambda: ctx.jobs.idle() and compare.test_view._pix is not None, timeout=20000)
    assert compare.busy.isHidden() and not compare.busy._timer.isActive(), "no busy overlay left behind"
    note = compare.note.text()
    assert to_local(rec["time"]) in note and f"recipe revision {rec['recipe_rev']}," in note and "moved" not in note
    assert compare.test_label.text().endswith("(stored result)")
    why = compare.why.toPlainText()  # the heading with the verdict, then the deciding checks first (REQ-CMP-004)
    assert why.startswith(f"Why this board is {rec['result']}:\n• {explain(res)[0].text()}"), why
    assert compare.res is not None and np.array_equal(compare.res.image, draw_overlay(res)), "the picture judged"
    _refuse_inspection(monkeypatch)
    first = ctx.active_model(BOARD)
    ctx.db.register_model(BOARD, "v9.9", str(first["path"]), {})  # a new AI model version, made active
    compare.show_stored(iid)
    assert f"to AI model v9.9 and recipe revision {rec['recipe_rev']}." in compare.note.text(), compare.note.text()
    ctx.db.activate_model(first["id"])  # rolled back; then a new recipe revision alone
    recipe = ctx.recipe(BOARD)[1]
    recipe.ssim_min += 0.05
    new_rev = ctx.save_recipe(recipe)
    compare.show_stored(iid)
    note = compare.note.text()
    assert f"revision {rec['recipe_rev']}," in note, note  # the stored revision, then what the board moved to
    assert f"{first['version']} and recipe revision {new_rev}." in note, note
    thresholds = [r[3] for r in _table(compare)[:-1]]
    assert thresholds == [round(float(str(c["threshold"])), 4) for c in ctx.checks_for(iid)]
    assert round(recipe.ssim_min, 4) not in thresholds, "the thresholds that applied then, not the new revision's"
    diff_path, ai_path = ctx.db.map_paths(iid)
    qtbot.waitUntil(ctx.jobs.idle, timeout=10000)  # the pool reads the maps; Windows cannot delete a file held open
    Path(str(diff_path)).unlink()  # one map gone: the other still serves its view
    compare.show_stored(iid)
    qtbot.waitUntil(lambda: compare.test_view._pix is not None, timeout=10000)
    assert "AOI-CMP-001" not in compare.note.text() and compare.res.compare and compare.res.compare.diff_map is None
    assert compare.res.anomaly_map is not None
    Path(str(ai_path)).unlink()
    for clear in (False, True):  # the files deleted by hand, then the paths cleared as the retention sweep leaves them
        if clear:
            ctx.db.clear_map_paths([iid])
        compare.show_stored(iid)
        assert "AOI-CMP-001" in compare.note.text() and _table(compare)[:-1] == _expected(compare, ctx.checks_for(iid))
    qtbot.waitUntil(lambda: compare.test_view._pix is not None, timeout=10000)
    assert compare.res is not None and compare.res.anomaly_map is None, "the maps are gone, the picture is not"
    compare.mode.setCurrentIndex(2)  # the AI heatmap view without a map: the picture alone, no error
    assert compare.test_view._pix is not None and not dialogs
    Path(rec["overlay_path"]).unlink()  # the picture deleted by hand
    compare.show_stored(iid)
    qtbot.waitUntil(compare.test_empty.isVisible, timeout=10000)
    assert compare.test_view._pix is None and not compare.test_view._overlay_items and compare.note.isVisible()
    assert "Re-evaluate" in compare.test_empty.sentence.text() and compare.test_empty.link.isVisibleTo(
        compare.test_empty
    )
    win.last_inspected = (str(ng_board), res, iid)
    compare.use_last()
    assert compare.stored is not None and compare.stored["id"] == iid
    ran: list[int] = []
    monkeypatch.setattr(compare, "run", lambda: ran.append(1))
    win.last_inspected = (str(ng_board), res, None)  # a preview from AI Model Test is not recorded: inspected again
    compare.use_last()
    assert ran and compare.test_path == str(ng_board)
    compare.show_stored(iid + 1000)
    assert dialogs and dialogs[-1][0].startswith("AOI-CMP-002"), dialogs
    compare.show_stored(iid)  # the board model cleared before its pictures arrive: nothing of the load is drawn
    win._on_board_model("")
    qtbot.waitUntil(lambda: ctx.jobs.idle() and compare._bg is None, timeout=10000)
    assert compare.res is None and compare.stored is None and compare.note.isHidden()


def test_req_cmp_003_golden_board_as_judged(
    qtbot: QtBot, trained_ctx: AppContext, ng_board: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Each record names the golden board its engine judged against, with the SHA-256 of its bytes (migration 0008):
    Compare shows that board after an Engineer set another, and inspecting the board again keeps it until Golden Board;
    when its file has other bytes, cannot be read or is gone, or none was recorded, the pane says so and what to do,
    one click from Re-evaluate ›; nothing is inspected again."""
    ctx, golden = trained_ctx, Path(str(trained_ctx.reference_image(BOARD)))
    engine = ctx.inspector(BOARD)  # an Inspection run keeps one engine while an Engineer sets another golden board
    other = next(s for s in ctx.samples(BOARD, "OK") if Path(s["path"]) != golden)
    ctx.set_reference(BOARD, other["id"])
    ctx.inspect_file(BOARD, str(ng_board), inspector=engine)
    iid = ctx.inspections(board_model=BOARD)[0]["id"]
    rec = ctx.inspection(iid)
    assert rec is not None and rec["reference_path"] == str(golden) and ctx.judged_reference(iid + 1000)[1] == "none"
    assert rec["reference_sha256"] == hashlib.sha256(golden.read_bytes()).hexdigest()
    assert ctx.inspector(BOARD, reference=engine.reference).reference_path is None, "a reference passed in names none"
    win = _window(qtbot, ctx, "Operator")
    compare = win.pages["Compare"]
    assert isinstance(compare, ComparePage)
    win.navigate("Compare")
    qtbot.waitUntil(lambda: ctx.jobs.idle() and compare._bg is None, timeout=10000)
    shown: list[np.ndarray | None] = []
    monkeypatch.setattr(compare.ref_view, "set_image", lambda img, *a: shown.append(img))
    as_judged = f"Golden board as judged: {wrapped(golden.name)}"
    for press in (lambda: compare.show_stored(iid), compare.run):  # the stored result, then inspected again
        press()
        qtbot.waitUntil(lambda: compare._bg is None, timeout=10000)
        assert np.array_equal(shown[-1], ctx.load_image(golden)) and compare.ref_label.text() == as_judged
        assert compare.ref_empty.isHidden()
    compare.use_golden()
    qtbot.waitUntil(lambda: compare._bg is None, timeout=10000)
    assert np.array_equal(shown[-1], ctx.load_image(other["path"])), "Golden Board compares with today's"
    _refuse_inspection(monkeypatch)
    compare.show_stored(iid)
    qtbot.waitUntil(lambda: compare._bg is None, timeout=10000)
    assert f"Golden board is now {wrapped(Path(other['path']).name)}." in compare.note.text(), compare.note.text()
    compare.on_board_model_changed(None)
    assert compare.as_judged is None, "another board model drops the golden board as judged"
    sql = "UPDATE inspections SET {} = NULL WHERE id=?"
    changes = {  # other bytes, cut short, a folder at the path; then no hash, then judged without one, as decided
        "changed": lambda: golden.write_bytes(golden.read_bytes() + b"\0"),
        "unreadable": lambda: golden.write_bytes(golden.read_bytes()[:64]),
        "missing": lambda: (golden.unlink(), golden.mkdir()),
        "unrecorded": lambda: ctx.db.execute(sql.format("reference_sha256"), (iid,)),
        "none": lambda: (
            ctx.db.execute(sql.format("reference_path"), (iid,)),
            ctx.db.execute("DELETE FROM checks WHERE inspection_id=? AND source='Compare'", (iid,)),
        ),
    }
    for why, change in changes.items():
        change()
        compare.show_stored(iid)
        qtbot.waitUntil(lambda: compare._bg is None, timeout=10000)
        named = why in ("changed", "unreadable", "missing")
        assert shown[-1] is None and compare.ref_empty.isVisible(), why
        assert compare.ref_label.text() == (as_judged if named else "Reference: Golden board"), why
        sentence = compare.ref_empty.sentence.text()
        assert (
            sentence.startswith(compare.tr(JUDGED[why]).format(file=wrapped(golden.name))) and "Re-evaluate" in sentence
        )
        assert compare.ref_empty.link.isVisibleTo(compare.ref_empty), "the next step is one click away"
    assert "Golden board is now" not in compare.note.text(), "a record that names none says nothing of a change"
    logged = [r["reason"] for r in _log_rows(ctx, "compare.golden_board_not_as_judged")]
    assert logged == ["changed", "unreadable", "missing"], logged


def test_req_cmp_005_a_record_is_judged_under_its_own_board_model(
    qtbot: QtBot,
    trained_ctx: AppContext,
    ng_board: Path,
    monkeypatch: pytest.MonkeyPatch,
    dialogs: list[tuple[str, str]],
) -> None:
    """#172: once the header shows another board model, Inspection forgets its last board and Compare drops a record's
    board, so neither is judged as the new board model's; Re-evaluate on a record of another board model is refused
    with AOI-CMP-005 naming the board model to pick, and under that board model it judges the board."""
    ctx = trained_ctx
    ctx.ensure_board_model("ZZZ")
    win = _window(qtbot, ctx, "Engineer")
    insp, compare = win.pages["Inspection"], win.pages["Compare"]
    assert isinstance(compare, ComparePage)
    iid = _inspect_one(qtbot, win, ng_board).last_id
    assert iid is not None and win.last_inspected is not None
    insp.open_compare()  # the record, on Compare
    qtbot.waitUntil(lambda: ctx.jobs.idle() and compare._bg is None, timeout=20000)
    calls: list[tuple[str, str | None]] = []
    real = AppContext.inspect

    def spy(c: AppContext, bm: str, image: np.ndarray, recipe: Recipe | None = None, **k: Any) -> InspectionResult:
        calls.append((bm, recipe.board_model if recipe else None))  # the board model judged under, and its recipe's
        return real(c, bm, image, recipe, **k)

    monkeypatch.setattr(AppContext, "inspect", spy)
    win.bm_combo.setCurrentText("ZZZ")
    qtbot.waitUntil(lambda: ctx.jobs.idle() and compare._bg is None, timeout=20000)
    assert insp.last is None and insp.last_id is None and insp.last_path is None and win.last_inspected is None
    assert insp.verdict.text() == "—" and insp.table.rowCount() == 0 and not insp.act_save.isEnabled()
    assert compare.test_path is None and compare.verdict.text() == "—" and compare.metrics.rowCount() == 0
    assert compare.test_empty.heading.text() == "No board to compare yet" and calls == []
    win.navigate("Inspection")
    insp.open_compare()  # nothing of TINY opens as ZZZ's
    assert win.stack.currentWidget() is insp and compare.stored is None
    compare.show_stored(iid)  # a TINY record shown while the header shows ZZZ, as a link from elsewhere would
    qtbot.waitUntil(lambda: ctx.jobs.idle() and compare._bg is None, timeout=20000)
    compare.run()  # Re-evaluate
    assert dialogs and dialogs[-1][0].startswith("AOI-CMP-005") and "board model TINY" in dialogs[-1][1], dialogs
    assert calls == [] and compare.stored is not None, "nothing was judged; the stored result stays"
    win.bm_combo.setCurrentText(BOARD)  # its own board model: the board is judged under it,
    assert compare._bg is None and calls == []
    win.navigate("Compare")  # once Compare is shown, never behind the page in use (#247)
    qtbot.waitUntil(lambda: ctx.jobs.idle() and compare._bg is None and compare.res is not None, timeout=20000)
    assert calls == [(BOARD, BOARD)]


def test_req_cmp_005_form_follows_a_revision_saved_elsewhere(
    qtbot: QtBot, trained_ctx: AppContext, monkeypatch: pytest.MonkeyPatch
) -> None:
    """#172: a recipe revision saved while Compare's form holds the revision before (as Recipe Editor saves one): back
    on Compare the form shows the new revision, so Save to Recipe keeps it; edits not saved stay while no revision is
    saved."""
    ctx = trained_ctx
    win = _window(qtbot, ctx, "Engineer")
    compare = win.pages["Compare"]
    assert isinstance(compare, ComparePage)
    win.navigate("Compare")
    qtbot.waitUntil(lambda: ctx.jobs.idle() and compare._bg is None, timeout=20000)
    recipe = ctx.recipe(BOARD)[1]
    assert compare.diff_thr.value() == recipe.diff_threshold
    compare.min_area.setValue(recipe.min_defect_area + 5)  # tried, not saved
    win.navigate("Home")
    win.navigate("Compare")
    assert compare.min_area.value() == recipe.min_defect_area + 5, "no revision since: the form keeps what was tried"
    recipe.diff_threshold += 20
    ctx.save_recipe(recipe)  # as Recipe Editor's Save Recipe stores it
    win.navigate("Recipe Editor")
    win.navigate("Compare")
    assert compare.diff_thr.value() == recipe.diff_threshold and compare.min_area.value() == recipe.min_defect_area
    compare.ssim_min.setValue(compare.ssim_min.value() - 0.01)
    compare.save_recipe()
    saved = ctx.recipe(BOARD)[1]
    assert saved.diff_threshold == recipe.diff_threshold and saved.ssim_min == pytest.approx(recipe.ssim_min - 0.01)
    qtbot.waitUntil(lambda: ctx.jobs.idle() and compare._bg is None, timeout=20000)


def test_req_cmp_003_re_evaluate_hides_board_picture_no_longer_stored(
    qtbot: QtBot, trained_ctx: AppContext, ng_board: Path
) -> None:
    """#172: a stored result whose picture was deleted says "Board picture no longer stored"; its own Re-evaluate ›
    shows the fresh result, and the block goes."""
    ctx = trained_ctx
    ctx.inspect_file(BOARD, str(ng_board))
    rec = ctx.inspections(board_model=BOARD)[0]
    win = _window(qtbot, ctx, "Engineer")
    compare = win.pages["Compare"]
    assert isinstance(compare, ComparePage)
    win.navigate("Compare")
    qtbot.waitUntil(lambda: ctx.jobs.idle() and compare._bg is None, timeout=20000)
    Path(rec["overlay_path"]).unlink()
    compare.show_stored(rec["id"])
    qtbot.waitUntil(compare.test_empty.isVisible, timeout=10000)
    assert compare.test_empty.heading.text() == "Board picture no longer stored"
    compare.test_empty.link.click()  # Re-evaluate ›
    qtbot.waitUntil(lambda: compare._bg is None and compare.test_view._pix is not None, timeout=20000)
    assert compare.stored is None and compare.test_empty.isHidden(), "the fresh result is not under the block"


def test_req_cmp_004_a_stored_results_notes_on_compare_speak_of_the_day_it_was_inspected(
    qtbot: QtBot, ctx: AppContext, synthetic_dataset: Path, ng_board: Path, dialogs: list[tuple[str, str]]
) -> None:
    """A board inspected while its board model had a Golden board and no AI model is stored with the note that the AI
    check did not run. Opened on Compare, the "why" box said "No AI model is trained for this board model", of today
    (review B of S28a, N7); it now says that none was trained when the board was inspected. Inspected again,
    it gives a fresh result whose note speaks of today again. The next test has an AI model trained since."""
    ok = sorted(synthetic_dataset.glob("train/ok/*.png"))[:2]
    ctx.import_samples(BOARD, [str(p) for p in ok], "OK")  # a new board model: its Golden board, and no AI model
    ctx.inspect_file(BOARD, str(ng_board))
    iid = ctx.inspections(board_model=BOARD)[0]["id"]
    stored = ctx.inspection_result(iid)
    assert stored is not None and stored.notes == [NO_AI_NOTE], "the record keeps that the AI check did not run"
    win = _window(qtbot, ctx, "Operator")
    compare = win.pages["Compare"]
    assert isinstance(compare, ComparePage)
    win.navigate("Compare")
    qtbot.waitUntil(lambda: ctx.jobs.idle() and compare._bg is None, timeout=20000)
    compare.show_stored(iid)
    qtbot.waitUntil(lambda: compare._bg is None and compare.test_view._pix is not None, timeout=20000)
    then = (
        "• No AI model was trained for this board model when the board was inspected, so the AI check did not run:"
        " inspect the board again once one is trained."
    )
    assert compare.why.toPlainText().split("\n")[-1] == then, compare.why.toPlainText()
    assert compare.test_empty.isHidden() and compare.ref_empty.isHidden(), "both pictures show: no pane's link"
    compare.run()  # inspected again from its image file: a fresh result, with today's board model
    qtbot.waitUntil(lambda: compare._bg is None and compare.stored is None and compare.res is not None, timeout=20000)
    today = "• No AI model is trained for this board model, so the AI check did not run: an Engineer trains one on"
    assert compare.why.toPlainText().split("\n")[-1].startswith(today), compare.why.toPlainText()
    assert not dialogs


def test_req_cmp_004_a_board_inspected_before_its_ai_model_was_trained_says_so_once_one_is(
    qtbot: QtBot,
    trained_ctx: AppContext,
    ng_board: Path,
    monkeypatch: pytest.MonkeyPatch,
    dialogs: list[tuple[str, str]],
) -> None:
    """N7 itself (review B of S28a): a board inspected before its board model had an AI model, opened on Compare once
    one is active, says that none was trained when it was inspected, and the note names the AI model the board model
    moved to; inspected again, it gets that AI model. A board inspected without a Golden board says so too; while
    the board model still has none, the Golden board pane promises none (its link inspects the board again from its
    image file, and does so without one), and once one is set it names today's (S28b review)."""
    ctx = trained_ctx
    golden = ctx.reference_image(BOARD)
    with monkeypatch.context() as m:
        m.setattr(ctx, "load_model", lambda *_: None)  # no AI model yet when this board was inspected
        ctx.inspect_file(BOARD, str(ng_board))
    no_ai = ctx.inspections(board_model=BOARD)[0]["id"]
    ctx.db.execute("UPDATE board_models SET reference_image=NULL WHERE name=?", (BOARD,))  # nor a Golden board
    ctx.inspect_file(BOARD, str(ng_board))
    no_golden = ctx.inspections(board_model=BOARD)[0]["id"]
    notes = [r.notes if (r := ctx.inspection_result(i)) else None for i in (no_ai, no_golden)]
    assert notes == [[NO_AI_NOTE], [NO_GOLDEN_NOTE]] and ctx.active_model(BOARD) is not None, notes
    win = _window(qtbot, ctx, "Operator")
    compare = win.pages["Compare"]
    assert isinstance(compare, ComparePage)
    win.navigate("Compare")
    qtbot.waitUntil(lambda: ctx.jobs.idle() and compare._bg is None, timeout=20000)

    def last(stored: int | None) -> str:
        """The last line of the "why" box once the stored result `stored`, or a fresh one (None), shows."""
        qtbot.waitUntil(lambda: compare._bg is None and (compare.stored or {}).get("id") == stored, timeout=20000)
        return compare.why.toPlainText().split("\n")[-1]

    compare.show_stored(no_ai)
    assert last(no_ai).startswith("• No AI model was trained for this board model when the board was inspected")
    assert "Since then the board model moved to AI model v1.0" in compare.note.text(), compare.note.text()
    compare.run()  # inspected again from its image file: judged with the AI model active today
    assert "No AI model" not in last(None) and compare.res is not None and compare.res.notes == []
    compare.show_stored(no_golden)
    assert last(no_golden).startswith("• No Golden board was in use for this board model when the board was inspected")
    judged_without = "This result was judged without a Golden board. The verdict and the decision table are the stored"
    from_file = f"{judged_without} ones; press Re-evaluate › to inspect the board again from its image file."
    assert compare.ref_empty.sentence.text() == from_file and compare.ref_empty.link.text() == "Re-evaluate ›"
    compare.ref_empty.link.click()  # still no Golden board today: the board is judged without one
    assert last(None).startswith("• No Golden board is set for this board model"), compare.why.toPlainText()
    assert golden is not None
    ctx.db.set_reference(BOARD, golden)
    compare.show_stored(no_golden)
    assert last(no_golden).startswith("• No Golden board was in use for this board model when the board was inspected")
    assert compare.ref_empty.sentence.text().endswith(
        "press Re-evaluate › to inspect the board again with today's Golden board."
    )
    assert not dialogs


@pytest.mark.parametrize(
    "damaged", ["diff_map_path", "overlay_path", "database", "busy", "colour diff map", "half-size AI map"]
)
def test_req_cmp_003_another_records_golden_board_never_stays_beside_a_stored_result(
    qtbot: QtBot,
    trained_ctx: AppContext,
    ng_board: Path,
    monkeypatch: pytest.MonkeyPatch,
    dialogs: list[tuple[str, str]],
    damaged: str,
) -> None:
    """#247: record A opened on Compare, then record B, judged against another Golden board, whose stored difference
    map or overlay cannot be read (or whose pictures the database refuses): the Golden board pane kept A's golden board,
    its "as judged" label and A's boxes beside B's verdict, the test pane said nothing, and a damaged overlay showed
    AOI-INSP-004, which advises saving the image with an image tool. Now the pane shows B's golden board as judged, or
    says why it shows none, and the dialog names the file: AOI-CMP-003 for a map, AOI-CMP-006 for the overlay. A
    database another program holds is AOI-SET-013 on both panes, as in the dialog (review). A map an image editor
    re-saved in colour or at half size reads as damaged (#249), as a map that cannot be read; before, no dialog
    opened."""
    ctx = trained_ctx
    golden = Path(str(ctx.reference_image(BOARD)))
    ctx.inspect_file(BOARD, str(ng_board))
    a = ctx.inspections(board_model=BOARD)[0]["id"]
    other = next(s for s in ctx.samples(BOARD, "OK") if Path(s["path"]) != golden)
    ctx.set_reference(BOARD, other["id"])
    ctx.inspect_file(BOARD, str(ng_board))
    b = ctx.inspections(board_model=BOARD)[0]["id"]
    rec = ctx.inspection(b)
    assert rec is not None
    judged = Path(str(rec["reference_path"]))
    assert b != a and judged.name != golden.name
    win = _window(qtbot, ctx, "Operator")
    compare = win.pages["Compare"]
    assert isinstance(compare, ComparePage)
    win.navigate("Compare")
    qtbot.waitUntil(lambda: ctx.jobs.idle() and compare._bg is None, timeout=20000)
    compare.show_stored(a)
    qtbot.waitUntil(lambda: compare._bg is None and bool(compare.ref_view._overlay_items), timeout=20000)
    assert compare.ref_label.text() == f"Golden board as judged: {wrapped(golden.name)}"
    boxes = list(compare.ref_view._overlay_items)  # A's dashed defect boxes, on A's golden board

    def refused(*args: object) -> None:
        if damaged == "busy":
            held = sqlite3.OperationalError("database is locked")
            held.sqlite_errorcode = sqlite3.SQLITE_BUSY  # type: ignore[attr-defined]
            raise held
        raise sqlite3.DatabaseError("database disk image is malformed")

    code = "AOI-SET-013" if damaged == "busy" else "AOI-SET-007"
    column = {"colour diff map": "diff_map_path", "half-size AI map": "ai_map_path"}.get(damaged, damaged)
    if damaged in ("database", "busy"):
        monkeypatch.setattr(ctx, "judged_reference", refused)
    elif column != damaged:  # a whole PNG that decodes, as an image editor saves it
        stored = cv2.imread(str(rec[column]), cv2.IMREAD_UNCHANGED)
        h, w = stored.shape
        edited = (
            cv2.cvtColor(stored, cv2.COLOR_GRAY2BGR) if "colour" in damaged else cv2.resize(stored, (w // 2, h // 2))
        )
        save_image(str(rec[column]), edited)
    else:
        Path(str(rec[damaged])).write_bytes(b"damaged")
    compare.show_stored(b)
    qtbot.waitUntil(lambda: compare._bg is None and bool(dialogs), timeout=20000)
    assert compare.stored is not None and compare.stored["id"] == b
    assert compare.verdict.text() == theme.verdict_label(rec["result"]) and compare.note.isVisible()
    assert golden.name not in compare.ref_label.text(), compare.ref_label.text()
    assert all(box.scene() is None for box in boxes), "none of A's boxes stays on the Golden board pane"
    if damaged in ("database", "busy"):  # neither pane shows another record's picture, and each says why
        assert compare.ref_label.text() == "Golden board" and compare.ref_view._pix is None
        for empty, heading in (
            (compare.ref_empty, "Golden board not shown"),
            (compare.test_empty, "Board picture not shown"),
        ):
            assert (
                empty.isVisible() and empty.heading.text() == heading and empty.sentence.text().startswith(f"{code} ")
            )
        what, do = dialogs[0][1].split("\n\n")
        assert compare.ref_empty.sentence.text() == f"{code} {what} {do}", "the next step, as the dialog says (review)"
        assert [d[0].split()[0] for d in dialogs] == [code]
        return
    assert (
        compare.ref_label.text() == f"Golden board as judged: {wrapped(judged.name)}" and compare.ref_empty.isHidden()
    )
    assert compare.as_judged is not None and np.array_equal(compare.as_judged[1], ctx.load_image(judged))
    assert compare.ref_view._pix is not None
    name = Path(str(rec[column])).name
    assert f"{dialogs[0][0].split()[0]} " in compare.note.text(), "the note keeps why a stored file is not shown"
    if column != "overlay_path":  # the maps go; the picture and B's boxes on both panes stay
        assert dialogs == [("AOI-CMP-003 Stored map cannot be read", dialogs[0][1])] and name in dialogs[0][1]
        assert compare.test_view._pix is not None and compare.ref_view._overlay_items and compare.test_empty.isHidden()
        assert compare.res is not None and compare.res.compare is not None and compare.res.compare.diff_map is None
        assert compare.res.anomaly_map is None
    else:  # the picture goes, said on the test pane; the dialog speaks of a stored file, not of re-saving an image
        assert [d[0] for d in dialogs] == ["AOI-CMP-006 Stored board picture cannot be read"] and name in dialogs[0][1]
        assert "image tool" not in dialogs[0][1]
        assert compare.test_view._pix is None and not compare.ref_view._overlay_items
        assert compare.test_empty.isVisible() and compare.test_empty.heading.text() == "Board picture no longer stored"


def test_req_cmp_003_new_with_the_board_models_own_name_keeps_the_stored_result(
    qtbot: QtBot,
    trained_ctx: AppContext,
    ng_board: Path,
    monkeypatch: pytest.MonkeyPatch,
    dialogs: list[tuple[str, str]],
) -> None:
    """#247: "+ New" with the name of the board model in the header, while Compare showed a stored result judged with
    recipe revision 1: Compare dropped it and inspected the board again with revision 2, unasked, and lost the values
    typed in the Try other thresholds form. Now nothing changes, also for any other notice of the same board model,
    and the status bar says the board model is already selected."""
    ctx = trained_ctx
    ctx.inspect_file(BOARD, str(ng_board))
    rid = ctx.inspections(board_model=BOARD)[0]["id"]
    recipe = ctx.recipe(BOARD)[1]
    recipe.changed_pct_max, recipe.max_diff_regions, recipe.anomaly_threshold = 50, 100, 100
    ctx.save_recipe(recipe)
    win = _window(qtbot, ctx, "Engineer")
    compare = win.pages["Compare"]
    assert isinstance(compare, ComparePage)
    win.navigate("Compare")
    qtbot.waitUntil(lambda: ctx.jobs.idle() and compare._bg is None, timeout=20000)
    compare.show_stored(rid)
    qtbot.waitUntil(lambda: compare._bg is None and compare.test_view._pix is not None, timeout=20000)
    compare.min_area.setValue(compare.min_area.value() + 7)  # a threshold tried, typed and not saved

    def page() -> tuple[object, ...]:
        return (compare.verdict.text(), compare.test_label.text(), compare.note.text(), _table(compare))

    shown, typed, calls = page(), compare.min_area.value(), []
    real = AppContext.inspect

    def spy(c: AppContext, *args: Any, **kwargs: Any) -> InspectionResult:
        calls.append(1)
        return real(c, *args, **kwargs)

    monkeypatch.setattr(AppContext, "inspect", spy)
    monkeypatch.setattr(QInputDialog, "getText", staticmethod(lambda *a, **k: (BOARD, True)))
    win.new_board_model()
    said = win.statusBar().currentMessage()
    win._on_board_model(BOARD)  # any other notice of the same board model changes nothing on Compare either
    qtbot.waitUntil(lambda: ctx.jobs.idle() and compare._bg is None, timeout=20000)
    assert compare.stored is not None and compare.stored["id"] == rid and compare.note.isVisible()
    assert page() == shown and compare.test_label.text().endswith("(stored result)")
    assert compare.min_area.value() == typed and calls == [] and dialogs == []
    assert said == f"Board model {BOARD} is already selected."


@pytest.mark.parametrize("link", ["open_stored", "open_compare"])
def test_req_insp_009_a_link_to_compare_starts_no_run_of_the_board_before(
    qtbot: QtBot,
    trained_ctx: AppContext,
    ng_board: Path,
    monkeypatch: pytest.MonkeyPatch,
    dialogs: list[tuple[str, str]],
    link: str,
) -> None:
    """#247 review: a test image picked on Compare, then the header changed and back on Inspection, so Compare judges
    that image when next shown. Inspection's "Compare with Golden board" (open_stored) or AI Model Test's link
    (open_compare) then showed Compare, whose on_show started a full inspection of that image, replaced at once by the
    record or the new file. Now only what the link asks for runs: nothing for a record, one run for a file."""
    ctx = trained_ctx
    ctx.ensure_board_model("ZZZ")
    win = _window(qtbot, ctx, "Engineer")
    compare = win.pages["Compare"]
    assert isinstance(compare, ComparePage)
    win.navigate("Compare")
    compare.set_test(str(ng_board))
    qtbot.waitUntil(lambda: compare.res is not None and compare._bg is None, timeout=60000)
    win.navigate("Inspection")
    win.bm_combo.setCurrentText("ZZZ")
    win.bm_combo.setCurrentText(BOARD)
    assert compare.judge_on_show
    insp = _inspect_one(qtbot, win, ng_board)
    runs: list[bool] = []
    real = ComparePage._start

    def spy(page: ComparePage, quiet: bool) -> None:
        runs.append(quiet)
        real(page, quiet)

    monkeypatch.setattr(ComparePage, "_start", spy)
    if link == "open_stored":
        insp.open_compare()  # the record, as it was decided
    else:
        win.open_compare(str(ng_board))
    qtbot.waitUntil(lambda: ctx.jobs.idle() and compare._bg is None, timeout=20000)
    assert runs == ([] if link == "open_stored" else [False]) and dialogs == []
    assert (compare.stored is not None) == (link == "open_stored") and compare.res is not None
