"""AI Model Test (#180): a run's results stay with the board model they were run for, and Export Report writes the PDF
through the service layer: whole or not at all, role-checked and audited (REQ-TST-004, REQ-LOG-004). A row's preview
is judged by what judged its run, or not at all (#250, REQ-TST-003); a run judged with the AI check off says so (#246,
REQ-TST-005)."""

from __future__ import annotations

import copy
import csv
import shutil
import threading
from pathlib import Path
from typing import Any

import pytest
from PySide6.QtCore import QCoreApplication
from PySide6.QtWidgets import QFileDialog, QMessageBox
from pytestqt.qtbot import QtBot

from aoi.core.imaging import list_images
from aoi.core.inspector import JudgedBy
from aoi.core.recipe import ROI
from aoi.core.services import AppContext
from aoi.data import atomic
from aoi.errors import AoiError
from aoi.ui import workers
from aoi.ui.main_window import MainWindow
from aoi.ui.pages.base import cell_item, cell_text
from aoi.ui.pages.model_test import ModelTestPage
from tests.conftest import another_version, wrapped
from tests.test_error_translation import Marking
from tests.test_req_done_in_v01 import BOARD, _window
from tools.make_synthetic_dataset import ng_type


def _tested_page(qtbot: QtBot, win: MainWindow, folder: Path) -> ModelTestPage:
    """The AI Model Test page after Run Test on `folder` under the header's board model."""
    win.navigate("AI Model Test")
    page = win.pages["AI Model Test"]
    assert isinstance(page, ModelTestPage)
    page.folder = str(folder)
    page.run()
    qtbot.waitUntil(lambda: bool(page.rows) and page.btn_run.isEnabled(), timeout=60000)
    return page


def _save_as(monkeypatch: pytest.MonkeyPatch, path: Path) -> None:
    monkeypatch.setattr(QFileDialog, "getSaveFileName", staticmethod(lambda *a, **k: (str(path), "PDF (*.pdf)")))


def _preview_every_row(qtbot: QtBot, page: ModelTestPage) -> list[tuple[str, str, str, str]]:
    """Each row selected in turn: (image, its Verdict cell, the preview's banner, the preview pane's sentence)."""
    seen = []
    for i in range(page.table.rowCount()):
        page.table.clearSelection()
        page.table.selectRow(i)
        qtbot.waitUntil(lambda: page._bg is None, timeout=30000)
        pane = getattr(page, "preview_empty", None)
        said = pane.sentence.text() if pane is not None and not pane.isHidden() else ""
        seen.append((cell_text(page.table, i, 0), cell_text(page.table, i, 2), page.preview_verdict.text(), said))
    return seen


@pytest.mark.parametrize(
    "change", ["none", "retrain_away", "retrain_on_page", "activate", "activate_back", "recipe", "reference"]
)
def test_req_tst_003_a_preview_is_judged_by_what_judged_its_row_or_not_at_all(
    qtbot: QtBot,
    trained_ctx: AppContext,
    synthetic_dataset: Path,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    dialogs: list[tuple[str, str]],
    change: str,
) -> None:
    """Run Test on the 21 test images, one row previewed, then a change to what judges the board model's boards: a
    retrain (on Training, or while the page stays shown), an Activate of another version, a new recipe revision or a new
    Golden board; then every row selected. No preview may read another verdict than its row: each is refused with
    AOI-TST-001 in the preview pane, Use Last Inspected keeps the board before, and the note above the table names
    both AI model versions; Export CSV and Export Report still name the run's AI model. With no change ("none") every
    preview is judged and matches its row, as it is once the run's AI model is activated again ("activate_back"), when
    the row still selected is previewed again in place of its refusal. Before (#250), after a retrain 2 of 21 previews
    read OK beside a row the run judged NG, and nothing on the page said why."""
    ctx, train = trained_ctx, lambda: trained_ctx.train(BOARD, epochs=1, image_size=64)
    if change in ("activate", "activate_back"):  # the run is judged by v1.1; v1.0 is activated after it, which keeps
        train()  # the Golden board
    win = _window(qtbot, ctx)
    page = _tested_page(qtbot, win, synthetic_dataset / "test")
    run_version = page.rows[0]["model_version"]
    page.table.selectRow(0)
    qtbot.waitUntil(lambda: page._bg is None and win.last_inspected is not None, timeout=30000)
    before, said = win.last_inspected, []
    if change == "retrain_away":
        win.navigate("Training")
        train()
        win.navigate("AI Model Test")  # shown again, the note says what changed before another row is selected
        assert page.run_note.isVisible() and all(f"AI model {v}" in page.run_note.text() for v in ("v1.0", "v1.1"))
        first = cell_text(page.table, 0, 0)  # and row 0, still selected, no longer shows its preview from before
        assert "Not inspected" in page.preview_verdict.text() and page.view._pix is None
        assert page.preview_empty.sentence.text().startswith(
            f"AOI-TST-001 {wrapped(first)} was judged in this run by AI"
        )
    elif change == "retrain_on_page":
        train()
    elif change == "activate":
        ctx.activate_model(next(m["id"] for m in ctx.models(BOARD) if m["version"] == "v1.0"))
    elif change == "activate_back":  # v1.0 activated on Training, then v1.1 again, the page shown after each
        for version in ("v1.0", "v1.1"):
            win.navigate("Training")
            ctx.activate_model(next(m["id"] for m in ctx.models(BOARD) if m["version"] == version))
            win.navigate("AI Model Test")
            qtbot.waitUntil(lambda: page._bg is None, timeout=30000)
            refused_now = "Not inspected" in page.preview_verdict.text()
            assert refused_now == (version == "v1.0") == page.run_note.isVisible(), (version, refused_now)
        assert page.preview_empty.isHidden() and page.preview_verdict.text() == cell_text(page.table, 0, 2)
        assert page.view._pix is not None and win.last_inspected is not before  # row 0 previewed again, by v1.1
        assert win.last_inspected is not None and win.last_inspected[0] == cell_item(page.table, 0, 0).toolTip()
    elif change == "recipe":
        recipe = ctx.recipe(BOARD)[1]
        recipe.ssim_min = 0.75
        said = [f"recipe revision {ctx.save_recipe(recipe)}"]
    elif change == "reference":
        golden = ctx.reference_image(BOARD)
        ok = next(s for s in ctx.samples(BOARD, "OK") if s["path"] != golden)
        ctx.set_reference(BOARD, ok["id"])
        said = [f"Golden board {Path(ok['path']).name}"]
    seen = _preview_every_row(qtbot, page)
    active = (ctx.active_model(BOARD) or {}).get("version")
    diffs = [s for s in seen if "Not inspected" not in s[2] and s[2] != s[1]]
    refused = [s for s in seen if "Not inspected" in s[2]]
    print(f"run model {run_version} active {active} change {change} rows {len(seen)} diffs {len(diffs)}")
    print("refused", len(refused), "note:", page.run_note.text() if hasattr(page, "run_note") else "(no note)")
    for s in diffs:
        print("DIFF", s)
    assert diffs == [], f"{len(diffs)} of {len(seen)} previews read another verdict than their row"
    assert len(seen) == 21 and dialogs == []
    if change in ("none", "activate_back"):
        last = cell_item(page.table, len(seen) - 1, 0).toolTip()
        assert refused == [] and win.last_inspected is not None and win.last_inspected[0] == last
        assert page.run_note.isHidden()
        return
    assert refused == seen and all(s[3].startswith("AOI-TST-001 ") for s in seen), seen[:2]
    assert win.last_inspected is before  # Use Last Inspected still opens the board previewed before the change
    note, named = page.run_note.text(), (f"AI model {run_version}", f"AI model {active}", *said)
    assert page.run_note.isVisible() and all(s in note for s in named), note
    if change == "retrain_away":  # the exports describe the stored run, judged by v1.0
        assert (run_version, active) == ("v1.0", "v1.1")
        rows_csv = tmp_path / "rows.csv"
        monkeypatch.setattr(QFileDialog, "getSaveFileName", staticmethod(lambda *a, **k: (str(rows_csv), "")))
        page.export_csv()
        with rows_csv.open(encoding="utf-8-sig", newline="") as f:
            assert {r["model_version"] for r in csv.DictReader(f)} == {"v1.0"}
        _save_as(monkeypatch, tmp_path / "report.pdf")
        page.export_report()
        assert "AI model: v1.0" in page._report_html()
        assert ctx.audit_entries(action="export.report")[0]["after"]["model_version"] == "v1.0"
    run_uuid = page.rows[0]["run_uuid"]  # Run Test Again, as the pane says: a run of what is in use, previewed again
    page.folder = str(synthetic_dataset / "test" / "ng")  # another folder picked since: the pane's link tests the run's
    page.preview_empty.link.click()
    qtbot.waitUntil(lambda: page.rows[0]["run_uuid"] != run_uuid and page.btn_run.isEnabled(), timeout=60000)
    assert page.run_note.isHidden() and page.preview_empty.isHidden() and page.rows[0]["model_version"] == active
    assert page.run_folder == page.folder_label.text() == str(synthetic_dataset / "test") and len(page.rows) == 21
    again = _preview_every_row(qtbot, page)[:3]
    assert all(s[2] == s[1] and s[3] == "" for s in again) and win.last_inspected is not before, again


@pytest.mark.parametrize("row", ["same_row", "another_row", "shown_again"])
def test_req_tst_003_a_preview_inspected_across_a_change_is_not_shown(
    qtbot: QtBot,
    trained_ctx: AppContext,
    synthetic_dataset: Path,
    monkeypatch: pytest.MonkeyPatch,
    dialogs: list[tuple[str, str]],
    row: str,
) -> None:
    """A row's preview is still being inspected when what judges the board model changes: a training run ends
    ("same_row"), a recipe is saved and another row is selected, which is refused at once ("another_row"), or a recipe
    is saved on another page and the page is shown again ("shown_again"), which drops the preview at once, its busy
    overlay with it, and refuses the row still selected; that preview's job then fails, as for a file moved meanwhile.
    The preview that arrives late, or its error, is not shown and never reaches Use Last Inspected; the pane keeps
    AOI-TST-001 for the row selected last, and no dialog shows. Before (#250), the late preview of the new AI model was
    shown and handed to Compare."""
    win = _window(qtbot, trained_ctx)
    page = _tested_page(qtbot, win, synthetic_dataset / "test")
    gate, inspected = threading.Event(), []
    real = trained_ctx.inspect_file

    def slow_inspect(board_model: str, path: str, **kwargs: Any) -> Any:
        inspected.append(path)
        gate.wait(60)
        if row == "shown_again":  # a dropped preview's error shows no dialog and does not replace the refusal
            raise AoiError("AOI-INSP-001", path=path)
        return real(board_model, path, **kwargs)

    monkeypatch.setattr(trained_ctx, "inspect_file", slow_inspect)
    page.table.selectRow(0)
    qtbot.waitUntil(lambda: len(inspected) == 1, timeout=10000)
    last = 0
    if row == "same_row":
        trained_ctx.train(BOARD, epochs=1, image_size=64)
    elif row == "another_row":
        trained_ctx.save_recipe(trained_ctx.recipe(BOARD)[1])
        page.table.selectRow(last := 1)
    else:
        win.navigate("Training")
        trained_ctx.save_recipe(trained_ctx.recipe(BOARD)[1])
        win.navigate("AI Model Test")
        print("shown again: job", page._bg, "busy watching", page.busy._job)
        assert page._bg is None and page.busy._job is None  # the preview is dropped at once, not when its job ends
    gate.set()
    qtbot.waitUntil(lambda: page._bg is None and not workers._live, timeout=60000)  # every result has reached the page
    name = cell_text(page.table, last, 0)
    pane = getattr(page, "preview_empty", None)
    said = (pane.heading.text(), pane.sentence.text()) if pane is not None and not pane.isHidden() else ("", "")
    print(row, "inspected", len(inspected), "banner", page.preview_verdict.text(), "pane", said[0])
    print("last inspected:", win.last_inspected and Path(win.last_inspected[0]).name)
    assert win.last_inspected is None and "Not inspected" in page.preview_verdict.text()
    shown = wrapped(name)  # a name in the pane may break after each _ and - (#245)
    assert said[0] == f"{shown} was not inspected" and said[1].startswith(f"AOI-TST-001 {shown} was judged in this run")
    assert len(inspected) == 1 and page.view._pix is None and dialogs == []


@pytest.mark.parametrize("change", ["retrain", "another_folder"])
def test_req_tst_003_a_preview_of_the_run_before_is_not_shown_beside_a_new_run(
    qtbot: QtBot,
    trained_ctx: AppContext,
    synthetic_dataset: Path,
    monkeypatch: pytest.MonkeyPatch,
    dialogs: list[tuple[str, str]],
    change: str,
) -> None:
    """A row's preview is still being inspected, its engine already built, when Run Test Again ends: after a training
    run ("retrain"; the row is ng_013_solder_ball.png, which v1.0 judged NG and v1.1 OK in #250) or on another folder
    with nothing changed ("another_folder"). The preview of the run before is not shown beside the new rows and never
    reaches Use Last Inspected, and no row of the new run stands selected beside an empty pane. Before (#250 review),
    the late preview was shown, judged by v1.0 beside the new run's rows, and handed to Compare."""
    win = _window(qtbot, trained_ctx)
    page = _tested_page(qtbot, win, synthetic_dataset / "test")
    gate, built = threading.Event(), []
    real = trained_ctx.inspect_file

    def slow_inspect(board_model: str, path: str, **kwargs: Any) -> Any:
        insp = trained_ctx.inspector(board_model)  # the engine is built at the click, then the board is judged
        built.append((Path(path).name, insp.model_version))
        gate.wait(60)
        return real(board_model, path, inspector=insp, **kwargs)

    monkeypatch.setattr(trained_ctx, "inspect_file", slow_inspect)
    target = next(i for i in range(page.table.rowCount()) if cell_text(page.table, i, 0) == "ng_013_solder_ball.png")
    page.table.selectRow(target)
    qtbot.waitUntil(lambda: len(built) == 1, timeout=10000)
    if change == "retrain":
        trained_ctx.train(BOARD, epochs=1, image_size=64)
    else:
        page.folder = str(synthetic_dataset / "test" / "ng")
    run_uuid = page.rows[0]["run_uuid"]
    page.run()  # Run Test Again
    qtbot.waitUntil(lambda: page.rows[0]["run_uuid"] != run_uuid and page.btn_run.isEnabled(), timeout=60000)
    new = {cell_text(page.table, i, 0): cell_text(page.table, i, 2) for i in range(page.table.rowCount())}
    selected = [cell_text(page.table, r.row(), 0) for r in page.table.selectionModel().selectedRows()]
    gate.set()
    qtbot.waitUntil(lambda: not workers._live, timeout=60000)  # the late preview has reached the page
    last = win.last_inspected
    print(change, "built", built, "new run by", page.rows[0]["model_version"], len(new), "rows")
    print("new row ng_013_solder_ball.png reads", new.get("ng_013_solder_ball.png"), "selected", selected)
    print("banner", page.preview_verdict.text(), "picture", page.view._pix is not None)
    print("last inspected", last and (Path(last[0]).name, last[1].verdict))
    assert built == [("ng_013_solder_ball.png", "v1.0")] and len(new) == (21 if change == "retrain" else 11)
    assert page.rows[0]["model_version"] == ("v1.1" if change == "retrain" else "v1.0")
    assert selected == [] and page.table.selectionModel().selectedRows() == []
    assert last is None and page.preview_verdict.text() == "—" and page.view._pix is None
    assert page.preview_empty.isHidden() and dialogs == []


def test_req_tst_003_the_panes_run_test_again_during_a_run_changes_nothing(
    qtbot: QtBot,
    trained_ctx: AppContext,
    synthetic_dataset: Path,
    monkeypatch: pytest.MonkeyPatch,
    dialogs: list[tuple[str, str]],
) -> None:
    """Run Test on the 21 test images, then a recipe saved, so the run shown is no longer current; another folder
    (test/ng) picked and Run Test Again in the bar going on it. A row of the first run, selected meanwhile, is refused,
    and the preview pane's Run Test Again pressed then changes nothing: it starts no second run, and once the run ends
    the folder beside the bar is the one its rows came from. One run is stored and audited (#250 reviews: run() returns
    at once while a run is going, and _run_again sets the run's folder only when no run is going)."""
    win = _window(qtbot, trained_ctx)
    page = _tested_page(qtbot, win, synthetic_dataset / "test")
    trained_ctx.save_recipe(trained_ctx.recipe(BOARD)[1])
    picked = str(synthetic_dataset / "test" / "ng")
    page.folder = picked
    page.folder_label.setText(picked)  # as pick() does
    gate, calls, real = threading.Event(), [], trained_ctx.batch_test

    def slow_test(*args: Any, **kwargs: Any) -> Any:
        calls.append(args[1])  # the folder tested
        gate.wait(60)
        return real(*args, **kwargs)

    monkeypatch.setattr(trained_ctx, "batch_test", slow_test)
    runs = len(trained_ctx.audit_entries(action="test.run"))
    page.run()  # the bar's Run Test Again, on the folder picked
    page.table.selectRow(0)  # a row of the first run
    assert "Not inspected" in page.preview_verdict.text() and page.preview_empty.link.isVisible()
    page.preview_empty.link.click()
    gate.set()
    qtbot.waitUntil(lambda: page.btn_run.isEnabled() and not workers._live, timeout=60000)
    entries = len(trained_ctx.audit_entries(action="test.run")) - runs
    print("runs started:", calls, "test.run entries:", entries, "rows:", len(page.rows))
    print("run folder:", page.run_folder, "folder:", page.folder, "label:", page.folder_label.text())
    assert calls == [picked] and entries == 1 and len(page.rows) == 11 and dialogs == []
    assert page.run_folder == page.folder == page.folder_label.text() == picked


def test_req_tst_003_a_run_with_no_ai_model_or_golden_board_reads_so(
    qtbot: QtBot, trained_ctx: AppContext, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The note and AOI-TST-001 say "no AI model" and "no Golden board", never "AI model none" (#250 review). In another
    UI language the screen shows each phrase translated, while the error's own text, which a log would keep, stays
    English. The run's JudgedBy is built by hand with neither, to pin both phrases in one test: batch_test returns no
    such run, as Inspector.judge refuses every board of a board model with neither with AOI-INSP-010 (#169). A run with
    no AI model is tested end to end by test_req_tst_003_a_run_with_no_ai_model_says_so_once_one_is_trained."""
    win = _window(qtbot, trained_ctx)
    win.navigate("AI Model Test")
    page = win.pages["AI Model Test"]
    assert isinstance(page, ModelTestPage)
    recipe = trained_ctx.recipe_history(BOARD)[0]
    page.rows, page.run_board_model = [{}], BOARD
    page.run_judged = JudgedBy(None, None, recipe["revision"], recipe["uuid"], None)
    changed = page._judged_now() or {}
    page._refuse_preview("ok_009.png", changed)
    page._note(changed)
    note, said = page.run_note.text(), page.preview_empty.sentence.text()
    print(note, said, sep="\n")
    golden = Path(trained_ctx.reference_image(BOARD) or "").name
    now = f"{BOARD} now uses AI model v1.0, recipe revision 1, Golden board "  # the pane's names may wrap (#245)
    assert note.startswith(
        f"These results were judged by no AI model, recipe revision 1, no Golden board and no scale; {now}{golden} and"
    )
    assert said.startswith(
        f"AOI-TST-001 {wrapped('ok_009.png')} was judged in this run by no AI model, recipe revision 1, no Golden"
    )
    assert f"board and no scale; {now}{wrapped(golden)} and no scale, so" in said and "none" not in note + said
    errors: list[AoiError] = []
    shown = page.not_inspected
    monkeypatch.setattr(page, "not_inspected", lambda *a, **k: errors.append(a[2]) or shown(*a, **k))
    translator = Marking()  # marks every string it translates with "§"
    assert QCoreApplication.installTranslator(translator)
    try:  # a row refused in another UI language
        changed = page._judged_now() or {}
        page._refuse_preview("ok_009.png", changed)
        page._note(changed)
    finally:
        QCoreApplication.removeTranslator(translator)
    print(page.run_note.text(), page.preview_empty.sentence.text(), str(errors[0]), sep="\n")
    marked = ("§no AI model", "§AI model v1.0", "§no Golden board", "§no scale")
    assert all(m in page.run_note.text() and m in page.preview_empty.sentence.text() for m in marked)
    assert f"§Golden board {golden}" in page.run_note.text()
    assert f"§Golden board {wrapped(golden)}" in page.preview_empty.sentence.text()
    error = str(errors[0])
    assert "§" not in error and "by no AI model, recipe revision 1, no Golden board and no scale;" in error


def test_req_tst_003_a_run_with_no_ai_model_says_so_once_one_is_trained(
    qtbot: QtBot,
    ctx: AppContext,
    synthetic_dataset: Path,
    monkeypatch: pytest.MonkeyPatch,
    dialogs: list[tuple[str, str]],
) -> None:
    """End to end (#250 review): Run Test on a board model with a Golden board and no AI model yet, one row previewed,
    then an AI model trained on Training. Shown again, the page says that the run was judged by no AI model, in the note
    and in AOI-TST-001 for the row previewed before, and names the AI model in use now."""
    monkeypatch.setattr(QMessageBox, "information", staticmethod(lambda *a: QMessageBox.StandardButton.Ok))
    ctx.import_samples(BOARD, [str(p) for p in list_images(synthetic_dataset / "train" / "ok")], "OK")
    for p in list_images(synthetic_dataset / "train" / "ng"):
        ctx.import_samples(BOARD, [str(p)], "NG", ng_type(p))
    ctx.set_reference(BOARD, ctx.samples(BOARD, "OK")[0]["id"])
    golden = Path(ctx.reference_image(BOARD) or "").name
    win = _window(qtbot, ctx)
    page = _tested_page(qtbot, win, synthetic_dataset / "test" / "ng")
    assert page.run_judged is not None and page.run_judged.model_version is None and page.run_judged.reference_path
    page.table.selectRow(0)
    qtbot.waitUntil(lambda: page._bg is None and win.last_inspected is not None, timeout=30000)
    win.navigate("Training")
    ctx.train(BOARD, epochs=1, image_size=64)
    win.navigate("AI Model Test")
    note, said = page.run_note.text(), page.preview_empty.sentence.text()
    print(note, said, sep="\n")
    judged = f"by no AI model, recipe revision 1, Golden board {golden} and no scale; {BOARD} now uses AI model v1.0,"
    assert page.run_note.isVisible() and note.startswith(f"These results were judged {judged}")
    shown = judged.replace(golden, wrapped(golden))  # the pane's names may break after each _ and - (#245)
    assert said.startswith(f"AOI-TST-001 {wrapped(cell_text(page.table, 0, 0))} was judged in this run {shown}")
    assert "Not inspected" in page.preview_verdict.text() and dialogs == []


@pytest.mark.parametrize("change", ["activate", "recipe", "reference", "recipe_off", "scale", "scale_px", "roi"])
def test_req_tst_003_a_run_judged_with_the_ai_check_off_is_tied_to_its_recipe_golden_board_and_scale(
    qtbot: QtBot,
    trained_ctx: AppContext,
    synthetic_dataset: Path,
    tmp_path: Path,
    dialogs: list[tuple[str, str]],
    change: str,
) -> None:
    """#250 with #246 (stack review): no AI model judged a run made with the AI check off, so an AI model activated
    since ("activate") changes nothing that judged it: every row is previewed, its banner reads its Verdict cell, Use
    Last Inspected follows, and no note shows. A recipe saved since ("recipe", the AI check still off) or another
    Golden board set ("reference") refuses the rows, and the note and AOI-TST-001 say the run was judged, and the board
    model is now judged, by "no AI model (the AI check off)", never by AI model v1.0. A run judged with the AI check on,
    then a recipe saved that turns it off ("recipe_off"), names the run's AI model and the AI check off now. A scale set
    since refuses the rows of a run whose recipe holds its minimum defect size in mm ("scale", S29), which the scale
    sizes, and the note names it, and so does one whose only size in mm is an ROI's ("roi", S29 review), while one in
    px ("scale_px") is previewed, as no scale changes it. Before, the
    activation refused every row of the AI-off run with AOI-TST-001, and its text and the note said the run was "judged
    by AI model v1.0", while the run's report says that no AI model judged the images."""
    ctx = trained_ctx
    recipe = copy.deepcopy(ctx.recipe(BOARD)[1])
    recipe.use_ai = change == "recipe_off"
    recipe.min_defect_mm = 0.5 if change == "scale" else None  # 445 px of area at 47.6 px/mm; 40 px with no scale
    recipe.rois = [ROI("R1", mm=[0, 0, 1, 1])] if change == "roi" else recipe.rois  # an ROI in mm alone (S29 review)
    run_rev = ctx.save_recipe(recipe)
    folder = tmp_path / "validation"
    for label in ("ok", "ng"):
        (folder / label).mkdir(parents=True)
        for board in sorted(synthetic_dataset.glob(f"test/{label}/*.png"))[:2]:
            shutil.copy(board, folder / label / board.name)
    win = _window(qtbot, ctx)
    page = _tested_page(qtbot, win, folder)
    page.table.selectRow(0)
    qtbot.waitUntil(lambda: page._bg is None and win.last_inspected is not None, timeout=30000)
    before, now_rev, run_golden = win.last_inspected, run_rev, Path(ctx.reference_image(BOARD) or "").name
    win.navigate("Training")
    if change == "activate":  # another version, with the Golden board kept
        ctx.activate_model(another_version(ctx, BOARD, "v1.1"))
    elif change == "reference":  # another OK sample as the Golden board, with the recipe kept
        ok = next(s for s in ctx.samples(BOARD, "OK") if s["path"] != ctx.reference_image(BOARD))
        ctx.set_reference(BOARD, ok["id"])
    elif change.startswith(("scale", "roi")):
        ctx.set_scale(BOARD, 476, 10)
    else:
        recipe.use_ai, recipe.ssim_min = False, 0.75
        now_rev = ctx.save_recipe(recipe)
    win.navigate("AI Model Test")
    seen = _preview_every_row(qtbot, page)
    note, golden = page.run_note.text(), Path(ctx.reference_image(BOARD) or "").name
    print(change, seen, note, sep="\n")
    assert len(seen) == 4 and dialogs == [] and (golden != run_golden) == (change == "reference")
    if change in ("activate", "scale_px"):
        assert all(s[2] == s[1] and s[3] == "" for s in seen) and page.run_note.isHidden(), seen
        assert win.last_inspected is not None and win.last_inspected[0] == cell_item(page.table, 3, 0).toolTip()
        return
    off = "no AI model (the AI check off)"
    run_model = "AI model v1.0" if change == "recipe_off" else off
    scale = "a scale of 47.60 px/mm" if change in ("scale", "roi") else "no scale"
    judged = (
        f"by {run_model}, recipe revision {run_rev}, Golden board {run_golden} and no scale; {BOARD} now uses {off},"
        f" recipe revision {now_rev}, Golden board {golden} and {scale}"
    )
    assert all("Not inspected" in s[2] for s in seen) and win.last_inspected is before
    assert page.run_note.isVisible() and note.startswith(f"These results were judged {judged}."), note
    shown = judged  # the pane's names may break after each _ and - (#245), as the note's do not
    for name in {run_golden, golden}:
        shown = shown.replace(f"Golden board {name}", f"Golden board {wrapped(name)}")
    assert seen[-1][3].startswith(f"AOI-TST-001 {wrapped(seen[-1][0])} was judged in this run {shown}, so"), seen[-1][3]


def test_req_tst_004_a_run_is_not_shown_under_another_board_model(
    qtbot: QtBot,
    trained_ctx: AppContext,
    synthetic_dataset: Path,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    dialogs: list[tuple[str, str]],
) -> None:
    """Run Test on TINY, a row's preview still being inspected, then OTHER picked in the header: TINY's rows, tiles and
    preview go, the preview that arrives late is dropped (not shown, not Use Last Inspected), nothing is inspected
    under OTHER, and Export Report has no run to report under OTHER's name."""
    win = _window(qtbot, trained_ctx)
    page = _tested_page(qtbot, win, synthetic_dataset / "test" / "ng")
    assert f"Board model: <b>{BOARD}</b>" in page._report_html()
    gate, inspected = threading.Event(), []
    real = trained_ctx.inspect_file

    def slow_inspect(board_model: str, path: str, **kwargs: Any) -> Any:
        inspected.append(board_model)
        gate.wait(30)
        return real(board_model, path, **kwargs)

    monkeypatch.setattr(trained_ctx, "inspect_file", slow_inspect)
    page.table.selectRow(0)
    qtbot.waitUntil(lambda: inspected == [BOARD], timeout=10000)
    trained_ctx.ensure_board_model("OTHER")
    win._reload_board_models("OTHER")
    gate.set()
    qtbot.waitUntil(lambda: page._bg is None, timeout=30000)
    print("rows shown after the switch:", page.table.rowCount(), "preview:", page.preview_verdict.text())
    assert page.rows == [] and page.metrics == {} and page.table.rowCount() == 0 and page.run_board_model is None
    assert page.confusion.text() == "" and all("—" in t.text() for t in page.tiles.values())
    assert page.preview_verdict.text() == "—" and page.view._pix is None and win.last_inspected is None
    page.table.selectRow(0)
    asked: list[object] = []
    monkeypatch.setattr(QFileDialog, "getSaveFileName", staticmethod(lambda *a, **k: asked.append(a) or ("", "")))
    page.export_report()
    assert inspected == [BOARD] and asked == [] and dialogs == []
    assert not page.empty.isHidden() and "OTHER" in page.empty.heading.text()


def test_req_tst_004_a_run_that_ends_under_another_board_model_is_stored_not_shown(
    qtbot: QtBot, trained_ctx: AppContext, synthetic_dataset: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The header changes to OTHER while TINY's run is still going: the run is stored under TINY, and its rows never
    appear under OTHER; the status bar says where they went."""
    win = _window(qtbot, trained_ctx)
    win.navigate("AI Model Test")
    page = win.pages["AI Model Test"]
    assert isinstance(page, ModelTestPage)
    gate, real = threading.Event(), trained_ctx.batch_test

    def slow_test(*args: Any, **kwargs: Any) -> Any:
        gate.wait(30)
        return real(*args, **kwargs)

    monkeypatch.setattr(trained_ctx, "batch_test", slow_test)
    page.folder = str(synthetic_dataset / "test" / "ng")
    page.run()
    trained_ctx.ensure_board_model("OTHER")
    win._reload_board_models("OTHER")
    gate.set()
    qtbot.waitUntil(lambda: page.btn_run.isEnabled(), timeout=60000)
    print("rows shown under OTHER:", page.table.rowCount())
    assert page.rows == [] and page.table.rowCount() == 0 and page.run_board_model is None
    assert trained_ctx.db.latest_test_run(BOARD) is not None and trained_ctx.db.latest_test_run("OTHER") is None
    assert BOARD in win.statusBar().currentMessage() and "stored" in win.statusBar().currentMessage()
    assert page.btn_run.text() == "Run Test"


def test_req_log_004_export_report_is_written_whole_or_not_at_all_and_audited(
    qtbot: QtBot,
    trained_ctx: AppContext,
    synthetic_dataset: Path,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    dialogs: list[tuple[str, str]],
) -> None:
    """Export Report writes the PDF through AppContext.export_report: a good write is audited as export.report with the
    run, AI model and size; a folder that cannot be made, or a disk that fails mid-write, shows AOI-LOG-002, says no
    "Report saved", writes no entry and leaves an earlier report whole; an Operator is refused with AOI-USR-001."""
    win = _window(qtbot, trained_ctx)
    page = _tested_page(qtbot, win, synthetic_dataset / "test" / "ng")
    audited = lambda: trained_ctx.audit_entries(action="export.report")  # noqa: E731

    good = tmp_path / "report.pdf"
    _save_as(monkeypatch, good)
    page.export_report()
    entries = audited()
    print("export.report entries after a good export:", len(entries))
    assert good.read_bytes().startswith(b"%PDF") and dialogs == []
    assert len(entries) == 1 and entries[0]["object_uuid"] == page.rows[0]["run_uuid"]
    assert entries[0]["after"] == {
        "path": str(good),
        "board_model": BOARD,
        "run_uuid": page.rows[0]["run_uuid"],
        "model_version": page.rows[0]["model_version"],
        "bytes": good.stat().st_size,
    }
    assert win.statusBar().currentMessage() == f"Report saved: {good}"

    blocker = tmp_path / "blocker"
    blocker.write_text("a file where the folder should be")
    win.statusBar().clearMessage()
    _save_as(monkeypatch, blocker / "report.pdf")
    page.export_report()
    print("status after a failed export:", repr(win.statusBar().currentMessage()), "dialogs:", dialogs)
    assert [t for t, _ in dialogs] == ["AOI-LOG-002 Export not written"] and str(blocker) in dialogs[0][1]
    assert win.statusBar().currentMessage() == "" and len(audited()) == 1

    earlier = b"%PDF-1.4 the report exported earlier"
    good.write_bytes(earlier)
    fsync = atomic.os.fsync

    def disk_fails(fd: int) -> None:
        raise OSError(5, "Input/output error")

    monkeypatch.setattr(atomic.os, "fsync", disk_fails)  # the disk fails while the new report is being written
    _save_as(monkeypatch, good)
    page.export_report()
    monkeypatch.setattr(atomic.os, "fsync", fsync)
    print("earlier report after a write that failed:", good.read_bytes()[:40])
    assert good.read_bytes() == earlier and [p.name for p in tmp_path.iterdir() if p.name.endswith(".tmp")] == []
    assert [t for t, _ in dialogs][1:] == ["AOI-LOG-002 Export not written"] and len(audited()) == 1

    win.set_user("operator")
    refused = tmp_path / "operator.pdf"
    _save_as(monkeypatch, refused)
    page.export_report()
    assert not refused.exists() and dialogs[-1][0].startswith("AOI-USR-001") and len(audited()) == 1


def test_req_log_004_export_writes_that_fail_carry_a_code(trained_ctx: AppContext, tmp_path: Path) -> None:
    """A CSV or a report that cannot be written, and a report with no bytes, are refused with AOI-LOG-002 and are not
    audited as exported."""
    (tmp_path / "blocker").write_text("a file where the folder should be")
    with pytest.raises(AoiError) as csv_refused:
        trained_ctx.export_csv(tmp_path / "blocker" / "rows.csv", [{"a": 1}])
    with pytest.raises(AoiError) as empty:
        trained_ctx.export_report(tmp_path / "empty.pdf", b"", BOARD, None, None)
    assert csv_refused.value.code == empty.value.code == "AOI-LOG-002" and "blocker" in csv_refused.value.what
    assert not (tmp_path / "empty.pdf").exists()
    assert trained_ctx.audit_entries(action="export.csv") == trained_ctx.audit_entries(action="export.report") == []


AI_OFF_RUN = (  # the report's sentence under its head for a run judged with the AI check off (#246)
    "The recipe turned the AI check off for this run: no AI model judged the images, and the verdicts come from the"
    " Golden board comparison alone."
)


def test_req_tst_005_a_run_judged_with_the_ai_check_off_says_so(
    qtbot: QtBot, trained_ctx: AppContext, synthetic_dataset: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """AI Model Test under a recipe with the AI check off, on a board model with an active AI model: every image is
    judged by the Golden board comparison alone. The run names the AI model active then, as every run does
    (REQ-TST-005), and says the AI check was off: each row as stored and in the CSV (ai_check OFF), and the report
    under its head. With the AI check on again, the rows read RAN and the report has no such sentence. Before, the run,
    its CSV and its report named AI model v1.0 with nothing to say that it had not judged the images."""
    ctx = trained_ctx
    active = ctx.active_model(BOARD)
    assert active is not None
    folder = tmp_path / "validation"
    for label in ("ok", "ng"):
        (folder / label).mkdir(parents=True)
        board = sorted(synthetic_dataset.glob(f"test/{label}/*.png"))[0]
        shutil.copy(board, folder / label / board.name)
    recipe = copy.deepcopy(ctx.recipe(BOARD)[1])
    recipe.use_ai = False
    ctx.save_recipe(recipe)
    win = _window(qtbot, ctx)
    page = _tested_page(qtbot, win, folder)
    assert {(r["model_version"], r["model_uuid"]) for r in page.rows} == {(active["version"], str(active["uuid"]))}
    run = ctx.db.latest_test_run(BOARD)
    assert run is not None
    out = tmp_path / "model_test.csv"
    monkeypatch.setattr(QFileDialog, "getSaveFileName", staticmethod(lambda *a, **k: (str(out), "CSV (*.csv)")))
    page.export_csv()
    with out.open(encoding="utf-8-sig", newline="") as f:
        exported = list(csv.DictReader(f))
    report = page._report_html()
    said = [{r.get("ai_check") for r in rows} for rows in (page.rows, run["results"], exported)]
    assert (said, AI_OFF_RUN in report) == ([{"OFF"}] * 3, True), report
    assert f"AI model: {active['version']}" in report and {r["model_version"] for r in exported} == {active["version"]}
    recipe.use_ai = True
    ctx.save_recipe(recipe)
    page._clear_run()
    page = _tested_page(qtbot, win, folder)
    assert {r["ai_check"] for r in page.rows} == {"RAN"} and AI_OFF_RUN not in page._report_html()
