"""#206: the error of a background job is never lost (REQ-LOG-005, REQ-INSP-006), and a folder import that stops
part-way always shows what it imported (REQ-SET-021). A job the user cancelled, or one a newer run replaced, shows no
dialog, but its error is logged with the trace and stored as an ERROR alarm like any other; a folder import that fails
part-way, cancelled or not, leaves the samples table as the database holds it and says how many files went in."""

from __future__ import annotations

import shutil
import sqlite3
import threading
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from PySide6.QtCore import QCoreApplication, QTranslator
from pytestqt.qtbot import QtBot

from aoi.core.imaging import list_images
from aoi.core.services import AppContext
from aoi.data import atomic
from aoi.errors import AoiError
from aoi.ui import theme, workers
from aoi.ui.main_window import MainWindow
from aoi.ui.pages.base import Page
from aoi.ui.pages.compare import NO_VERDICT, ComparePage
from aoi.ui.workers import Worker
from tests.test_alarms_and_errors import _log_rows
from tests.test_req_done_in_v01 import BOARD, _window


def _engineer_window(qtbot: QtBot, ctx: AppContext) -> MainWindow:
    win = MainWindow(ctx)
    qtbot.addWidget(win)
    win.set_user("engineer")
    win._on_board_model("NEWB")
    return win


def _settled(qtbot: QtBot, *ws: Worker) -> None:
    """Every slot the workers queued (result or error, then finished) has run on the UI thread."""
    qtbot.waitUntil(lambda: all(w.job.done and id(w) not in workers._live for w in ws), timeout=30000)


def _fails_after(started: threading.Event, gate: threading.Event) -> Callable[[], None]:
    def fails() -> None:
        started.set()  # running: a job cancelled while still queued never runs, so it raises nothing
        assert gate.wait(30)
        raise OSError("share went away mid-copy")

    return fails


@pytest.mark.parametrize("how", ["none", "cancel", "replace"])
def test_req_log_005_the_error_of_a_cancelled_or_replaced_job_is_logged_and_alarmed(
    qtbot: QtBot, ctx: AppContext, dialogs: list[tuple[str, str]], how: str
) -> None:
    """The issue's acceptance for defect 1: one error.shown line with the trace and one ERROR alarm for each failing
    job; a dialog only for the job that is neither cancelled nor replaced."""
    page: Page = _engineer_window(qtbot, ctx).pages["Training"]
    started, gate = threading.Event(), threading.Event()
    w = page.run_in_background(_fails_after(started, gate), on_result=lambda _v: None)
    qtbot.waitUntil(started.is_set, timeout=30000)
    later: list[Worker] = []
    if how == "cancel":
        w.stop()  # Cancel on the busy overlay
    elif how == "replace":
        later.append(page.run_in_background(lambda: "newer", on_result=lambda _v: None))
    gate.set()
    _settled(qtbot, w, *later)
    rows = _log_rows(ctx, "error.shown")
    assert len(rows) == 1 and "OSError: share went away mid-copy" in str(rows[0]["trace"]), rows
    assert [(a["level"], a["code"]) for a in ctx.alarms()] == [("ERROR", "AOI-SET-007")]
    assert [t for t, _ in dialogs] == (["AOI-SET-007 Unexpected error"] if how == "none" else [])


@pytest.mark.parametrize(("board_model", "how"), [("EMPTY", "cancel"), ("EMPTY", "replace"), ("GONE", "cancel")])
def test_req_log_005_a_compare_refusal_of_a_run_cancelled_or_replaced_is_logged_and_alarmed(
    qtbot: QtBot,
    trained_ctx: AppContext,
    ng_board: Path,
    synthetic_dataset: Path,
    dialogs: list[tuple[str, str]],
    monkeypatch: pytest.MonkeyPatch,
    board_model: str,
    how: str,
) -> None:
    """#247 review: Test Image... on Compare under a board model nothing can judge (EMPTY: AOI-INSP-010) or whose
    Golden board file is gone (GONE: AOI-INSP-009), then Cancel or Re-evaluate before the run ends. The refusal comes
    back as the run's result, which a run left drops, so it was neither logged nor alarmed. Now every run asked for
    logs and alarms its refusal on the pool thread, and only the run not left shows the dialog."""
    ctx, code = trained_ctx, "AOI-INSP-009" if board_model == "GONE" else "AOI-INSP-010"
    win = _window(qtbot, ctx)
    compare = win.pages["Compare"]
    win.navigate("Compare")
    ctx.ensure_board_model(board_model)
    if board_model == "GONE":
        ctx.import_samples(board_model, [str(p) for p in list_images(synthetic_dataset / "train" / "ok")[:3]], "OK")
        Path(str(ctx.reference_image(board_model))).unlink()
    win._reload_board_models(board_model)
    qtbot.waitUntil(lambda: ctx.jobs.idle() and compare._bg is None, timeout=20000)
    started, gate, real = threading.Event(), threading.Event(), AppContext.inspector

    def held(c: AppContext, *args: Any) -> Any:  # the first run waits inside, before its refusal is raised
        if not started.is_set():
            started.set()
            assert gate.wait(30)
        return real(c, *args)

    monkeypatch.setattr(AppContext, "inspector", held)
    compare.set_test(str(ng_board))  # Test Image...: asked for
    runs = [compare._bg]
    qtbot.waitUntil(started.is_set, timeout=20000)
    if how == "cancel":
        compare.busy.cancel_button.click()
    else:
        compare.run()  # Re-evaluate: the newer run wins
        runs.append(compare._bg)
    gate.set()
    _settled(qtbot, *[w for w in runs if w is not None])
    qtbot.waitUntil(lambda: ctx.jobs.idle() and compare._bg is None, timeout=20000)
    assert len(runs) == (1 if how == "cancel" else 2) and runs[0] is not None and runs[0].job.cancelled
    assert [a["code"] for a in ctx.alarms()].count(code) == len(runs), "one alarm for each run that was refused"
    assert [r["code"] for r in _log_rows(ctx, "error.shown")].count(code) == len(runs)
    assert [t.split()[0] for t, _ in dialogs] == ([code] if how == "replace" else [])


@pytest.mark.parametrize(("first", "then"), [(BOARD, "EMPTY"), ("GONE", BOARD)])
def test_req_insp_006_a_compare_run_in_flight_at_a_header_change_shows_nothing_under_the_new_board_model(
    qtbot: QtBot,
    trained_ctx: AppContext,
    ng_board: Path,
    synthetic_dataset: Path,
    dialogs: list[tuple[str, str]],
    monkeypatch: pytest.MonkeyPatch,
    first: str,
    then: str,
) -> None:
    """#247 review: Test Image... on Compare under `first`, still running when the user goes to Inspection and changes
    the header to `then`. The run went on, so the last board model's verdict, table and boxes, or its AOI-INSP-009
    dialog (GONE), arrived after the header had moved on, the dialog over Inspection. Now the header change stops it:
    nothing of it shows, Compare judges the board under `then` when shown, and a refusal is alarmed once (#206)."""
    ctx = trained_ctx
    win = _window(qtbot, ctx)
    compare = win.pages["Compare"]
    assert isinstance(compare, ComparePage)
    ctx.ensure_board_model("EMPTY")
    if first == "GONE":
        ctx.import_samples(first, [str(p) for p in list_images(synthetic_dataset / "train" / "ok")[:3]], "OK")
        Path(str(ctx.reference_image(first))).unlink()
    win._reload_board_models(first)
    win.navigate("Compare")
    qtbot.waitUntil(lambda: ctx.jobs.idle() and compare._bg is None, timeout=20000)
    started, gate, name = threading.Event(), threading.Event(), "inspector" if first == "GONE" else "inspect"
    real = getattr(AppContext, name)

    def held(c: AppContext, *args: Any, **kwargs: Any) -> Any:  # the run waits inside, until the header has changed
        if not started.is_set():
            started.set()
            assert gate.wait(30)
        return real(c, *args, **kwargs)

    monkeypatch.setattr(AppContext, name, held)
    compare.set_test(str(ng_board))  # Test Image...: asked for
    run = compare._bg
    assert run is not None
    qtbot.waitUntil(started.is_set, timeout=20000)
    win.navigate("Inspection")
    win.bm_combo.setCurrentText(then)
    gate.set()
    _settled(qtbot, run)
    qtbot.waitUntil(lambda: ctx.jobs.idle() and compare._bg is None, timeout=20000)
    assert win.board_model == then and win.stack.currentWidget() is win.pages["Inspection"] and dialogs == []
    assert compare.verdict.text() == NO_VERDICT and compare.metrics.rowCount() == 0, "the last board model's verdict"
    assert [a["code"] for a in ctx.alarms()].count("AOI-INSP-009") == int(first == "GONE"), "the refusal, alarmed once"
    win.navigate("Compare")  # judged under `then` now; until that run ends, nothing of `first` shows
    assert compare.verdict.text() == NO_VERDICT and compare.metrics.rowCount() == 0
    qtbot.waitUntil(lambda: ctx.jobs.idle() and compare._bg is None, timeout=20000)
    assert dialogs == []
    if then == "EMPTY":  # nothing can judge it: said on the test pane, quietly
        assert compare.res is None and compare.test_empty.sentence.text().startswith("AOI-INSP-010 ")
    else:
        assert compare.res is not None and compare.verdict.text() == theme.verdict_label("NG")


def _folder(root: Path, source: Path, names: list[str]) -> Path:
    (root / "ok").mkdir(parents=True)
    for name, p in zip(names, list_images(source), strict=False):
        shutil.copy(p, root / "ok" / name)
    return root


@pytest.mark.parametrize("how", ["cancel", "second"])
def test_req_log_005_an_import_stopped_while_a_copy_fails_logs_the_failure_and_shows_what_it_imported(
    qtbot: QtBot,
    ctx: AppContext,
    synthetic_dataset: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    dialogs: list[tuple[str, str]],
    how: str,
) -> None:
    """The issue's scenario: Import Folder of ok/a,b,c,d.png; the copy of c.png hangs on a share, the Engineer presses
    Cancel or Import Folder again, then the share drops. After Cancel no dialog opens for the import the user left, but
    its failure is logged with the trace and alarmed, and the status line says it was cancelled. A second Import Folder
    starts nothing while the first runs (#194), so the first one goes on and its failure opens its own coded dialog.
    Either way the table shows the files it imported."""
    source = synthetic_dataset / "train" / "ok"
    folder = _folder(tmp_path / "fold", source, ["a.png", "b.png", "c.png", "d.png"])
    second = _folder(tmp_path / "second", source, ["e.png"])
    reached, go = threading.Event(), threading.Event()
    copy = atomic.copy_file

    def hang_then_fail(src: str | Path, dst: str | Path) -> None:
        if Path(src).name == "c.png":
            reached.set()
            assert go.wait(30)
            raise FileNotFoundError(2, "No such file or directory", str(src))
        copy(src, dst)

    monkeypatch.setattr(atomic, "copy_file", hang_then_fail)
    win = _engineer_window(qtbot, ctx)
    page = win.pages["Training"]
    page.import_from(str(folder))
    first = page._bg
    assert first is not None
    qtbot.waitUntil(reached.is_set, timeout=30000)
    if how == "cancel":
        page.busy.cancel_button.click()
    else:
        page.import_from(str(second))
        assert page._bg is first, "a second import started while the first one ran"
    go.set()
    _settled(qtbot, first)
    assert [title for title, _ in dialogs] == (
        [] if how == "cancel" else ["AOI-TRN-009 Folder import stopped part-way"]
    )
    rows = _log_rows(ctx, "error.shown")
    assert [r["code"] for r in rows] == ["AOI-TRN-009"] and "FileNotFoundError" in str(rows[0]["trace"]), rows
    assert [(a["level"], a["code"]) for a in ctx.alarms()] == [("ERROR", "AOI-TRN-009")]
    assert page.samples.rowCount() == len(ctx.samples("NEWB")) == 2
    message = "Import cancelled: 2 OK and 0 NG images imported before it stopped" if how == "cancel" else "Imported 2"
    assert win.statusBar().currentMessage().startswith(message), win.statusBar().currentMessage()


def test_req_log_005_a_failing_on_error_hook_still_shows_the_jobs_error(
    qtbot: QtBot, ctx: AppContext, dialogs: list[tuple[str, str]]
) -> None:
    """on_error runs before the dialog; when it fails too (a refresh on a database that cannot be read), the job's own
    coded dialog still opens, and both errors are logged and alarmed."""
    page: Page = _engineer_window(qtbot, ctx).pages["Training"]

    def job() -> None:
        raise OSError("share went away")

    def hook(_e: BaseException) -> None:
        raise sqlite3.DatabaseError("database disk image is malformed")

    w = page.run_in_background(job, on_result=lambda _v: None, on_error=hook)
    _settled(qtbot, w)
    assert [t for t, _ in dialogs] == ["AOI-SET-007 Unexpected error"]
    traces = [str(r["trace"]) for r in _log_rows(ctx, "error.shown")]
    assert len(traces) == 2 and "malformed" in traces[0] and "share went away" in traces[1], traces
    assert [a["code"] for a in ctx.alarms()] == ["AOI-SET-007", "AOI-SET-007"]


class _BusyTitle(QTranslator):
    """Translates one error title only, as a filled aoi_ko.ts would (#198)."""

    def translate(self, context: str, source: str, disambiguation: str | None = None, n: int = -1) -> str:
        return "«busy»" if (context, source) == ("Errors", "Workspace database busy") else source


@pytest.mark.parametrize("cause", ["sqlite", "coded"])
def test_req_set_021_a_folder_import_that_fails_part_way_shows_the_files_it_imported(
    qtbot: QtBot,
    ctx: AppContext,
    synthetic_dataset: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    dialogs: list[tuple[str, str]],
    cause: str,
) -> None:
    """Defect 2: a failure other than a copy (here the database refuses c.png's row, in SQLite's words or with a code)
    after a.png and b.png went in. The table equals the database when the job ends, and the dialog names the file, the
    cause (a code with its title in the UI language, #198) and how many were imported."""
    folder = _folder(tmp_path / "fold", synthetic_dataset / "train" / "ok", ["a.png", "b.png", "c.png", "d.png"])
    add = ctx.db.add_sample

    def add_or_fail(board_model: str, path: str, *a: Any, **kw: Any) -> None:
        if Path(path).name.startswith("c_") and cause == "coded":
            raise AoiError("AOI-SET-013", "disk I/O error", path="aoi.sqlite", error="disk I/O error")
        if Path(path).name.startswith("c_"):
            raise sqlite3.OperationalError("disk I/O error")
        add(board_model, path, *a, **kw)

    monkeypatch.setattr(ctx.db, "add_sample", add_or_fail)
    win = _engineer_window(qtbot, ctx)
    page = win.pages["Training"]
    translator = _BusyTitle()
    assert QCoreApplication.installTranslator(translator)
    try:
        page.import_from(str(folder))
        w = page._bg
        assert w is not None
        _settled(qtbot, w)
    finally:
        QCoreApplication.removeTranslator(translator)
    assert page.samples.rowCount() == len(ctx.samples("NEWB")) == 2
    [(title, text)] = dialogs
    assert title == "AOI-TRN-010 Folder import stopped by an error", title
    named = "(OperationalError)" if cause == "sqlite" else "(AOI-SET-013 «busy»)"
    assert "c.png" in text and named in text and "image 3 of 4" in text, text
    assert "the 2 image(s) imported before it" in text and "would add those 2 a second time" in text, text
    assert "disk I/O error" not in text  # the raw text goes to the log only
    assert win.statusBar().currentMessage() == "Imported 2 OK and 0 NG images"
    (row,) = _log_rows(ctx, "error.shown")
    assert row["code"] == "AOI-TRN-010" and "disk I/O error" in str(row["trace"])
