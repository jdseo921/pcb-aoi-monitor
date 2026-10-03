"""REQ-CMP-003 and REQ-INSP-009 (S26): Compare shows a stored result as it was decided and never inspects the board
again: its decision table equals the stored checks row for row for every board of the synthetic regression set, one
click from Inspection opens it within 300 ms at 5 MP with the failing rows highlighted, and a note names the versions
used."""

from __future__ import annotations

import hashlib
from pathlib import Path
from time import perf_counter
from typing import Any

import numpy as np
import pytest
from PySide6.QtCore import Qt
from pytestqt.qtbot import QtBot

from aoi.core import anomaly
from aoi.core.explain import explain
from aoi.core.inspector import Check, InspectionResult, Inspector, draw_overlay
from aoi.core.recipe import Recipe
from aoi.core.services import AppContext
from aoi.times import to_local
from aoi.ui import theme
from aoi.ui.pages.base import cell_item
from aoi.ui.pages.compare import JUDGED, ComparePage
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
    """The note names when and with which versions the result was judged, on the picture judged; Re-evaluate leaves
    it and leaves no busy overlay behind; a new recipe revision and model version are named while the table keeps the
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
    compare.run()  # Re-evaluate: a fresh inspection with the form's thresholds, no longer the stored result
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
    Compare shows that board after an Engineer set another, and Re-evaluate keeps it until Golden Board is pressed;
    when its file has other bytes, cannot be read or is gone, or none was recorded, the pane says so and what to do,
    one click from Re-evaluate; nothing is inspected again."""
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
    as_judged = f"Golden board as judged: {golden.name}"
    for press in (lambda: compare.show_stored(iid), compare.run):  # the stored result, then Re-evaluate
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
    assert f"Golden board is now {Path(other['path']).name}." in compare.note.text(), compare.note.text()
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
        assert sentence.startswith(compare.tr(JUDGED[why]).format(file=golden.name)) and "Re-evaluate" in sentence
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
    win.bm_combo.setCurrentText(BOARD)  # its own board model: the board is judged under it
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
