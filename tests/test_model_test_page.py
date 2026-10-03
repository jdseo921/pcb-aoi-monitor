"""AI Model Test (#180): a run's results stay with the board model they were run for, and Export Report writes the PDF
through the service layer: whole or not at all, role-checked and audited (REQ-TST-004, REQ-LOG-004)."""

from __future__ import annotations

import threading
from pathlib import Path
from typing import Any

import pytest
from PySide6.QtWidgets import QFileDialog
from pytestqt.qtbot import QtBot

from aoi.core.services import AppContext
from aoi.data import atomic
from aoi.errors import AoiError
from aoi.ui.main_window import MainWindow
from aoi.ui.pages.model_test import ModelTestPage
from tests.test_req_done_in_v01 import BOARD, _window


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
