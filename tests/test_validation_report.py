"""REQ-TST-004 (stage S47, part 1): AI Model Test's report holds the rates with counts and bounds, recall per defect
type, every missed defect and false call with its overlay, and the AI model card; exporting it asks first, naming the
counts, and is audited; the CSV is UTF-8 with a BOM and keeps Korean text. Results on the synthetic boards prove a code
path; they are never quoted as accuracy."""

from __future__ import annotations

import csv
import re
import threading
from collections.abc import Callable
from pathlib import Path
from time import sleep
from typing import Any, cast

import pytest
from PySide6.QtCore import QBuffer, QIODevice, QMarginsF
from PySide6.QtGui import QPagedPaintDevice, QPageLayout, QPageSize, QPdfWriter, QTextDocument
from PySide6.QtWidgets import QFileDialog, QMessageBox, QPushButton
from pytestqt.qtbot import QtBot

from aoi.core import report
from aoi.core.services import AppContext
from aoi.ui.pages import model_test
from aoi.ui.pages.model_test import ModelTestPage
from tests.test_no_freeze import BUDGET_S, STALL_S, gap_meter
from tests.test_req_done_in_v01 import BOARD, _window
from tests.test_role_gates import _press


def run_page(qtbot: QtBot, ctx: AppContext, folder: Path) -> ModelTestPage:
    win = _window(qtbot, ctx, "Engineer")
    assert win.navigate("AI Model Test")
    page = cast(ModelTestPage, win.pages["AI Model Test"])
    page.source.setCurrentIndex(page.source.count() - 1)
    page.folder = str(folder)
    page.run()
    qtbot.waitUntil(lambda: page.btn_run.isEnabled() and bool(page.rows), timeout=120000)
    return page


def ui_thread_pdf(html_text: str) -> bytes:
    """`html_text` rendered on the UI thread, line for line as AI Model Test rendered a report before UI-3."""
    doc = QTextDocument()
    doc.setHtml(html_text)
    buf = QBuffer()
    buf.open(QIODevice.OpenModeFlag.WriteOnly)
    w = QPdfWriter(buf)
    margins = QMarginsF(15, 15, 15, 15)
    w.setPageLayout(QPageLayout(QPageSize(QPageSize.PageSizeId.A4), QPageLayout.Orientation.Portrait, margins))
    doc.print_(w)
    del w
    return bytes(buf.data().data())


def pdf_content(pdf: bytes) -> bytes:
    """`pdf` without what QPdfWriter writes anew into every PDF: its times and its document ID."""
    return re.sub(rb"\(D:[^)]*\)|\d{4}-\d\d-\d\dT[\d:]{8}([+-]\d\d:\d\d|Z)?|uuid:[\da-f-]{36}|<[\da-f]{72}>", b"", pdf)


def renders_off_the_ui_thread(
    qtbot: QtBot, page: ModelTestPage, press: Callable[[], None], btn: QPushButton, folder: Path, saved: str
) -> str:
    """Press `press` (Export Report or Validation Report…, its button `btn`), answered Yes into `folder`, printing held
    STALL_S longer (48 rows or 50 overlays took 2.5 s to 6 s, UI-3): the UI thread keeps ticking within 2 s; both report
    buttons are greyed with the reason, said on a finger's press too, the status bar says a report is being written, a
    second press or leaving the page does nothing; the end says `saved`, and the PDF, written and audited once, holds
    what the UI thread rendered. A second report stopped as the window closes leaves no file and no temporary file."""
    win, status = page.shell, page.shell.statusBar().currentMessage
    out, asked, htmls, handed, on_ui, rendering = [folder / "report.pdf"], [], [], [], [], threading.Event()
    saved, writing = saved.format(file=out[0]), f"Writing the report to {out[0]}…"
    reason = f"A report is being written to {out[0]}; wait until it is saved."
    real_set, real_print, real_render = QTextDocument.setHtml, QTextDocument.print_, model_test.render_pdf

    def render(text: str) -> bytes:
        return htmls.append(text) or real_render(text)

    def set_html(doc: QTextDocument, text: str) -> None:
        handed.append(text)
        real_set(doc, text)

    def slow_print(doc: QTextDocument, device: QPagedPaintDevice) -> None:
        on_ui.append(threading.current_thread() is threading.main_thread())
        rendering.set()
        sleep(STALL_S)
        real_print(doc, device)

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(QFileDialog, "getSaveFileName", staticmethod(lambda *a, **k: asked.append(a) or (str(out[0]), "")))
        yes = QMessageBox.StandardButton.Yes  # to the question naming the counts, and to "Stop the running work?"
        mp.setattr(QMessageBox, "question", staticmethod(lambda *a, **k: asked.append(a) or yes))
        mp.setattr(model_test, "render_pdf", render)
        mp.setattr(QTextDocument, "setHtml", set_html)
        mp.setattr(QTextDocument, "print_", slow_print)
        with gap_meter(qtbot) as g:
            press()
            qtbot.waitUntil(rendering.is_set, timeout=30000)
            during = (page.btn_report.isEnabled(), page.btn_validation.isEnabled(), btn.toolTip(), status())
            before = len(asked)
            press()  # a second press while it renders
            _press(win, btn)  # and a finger on the greyed button
            said, again = status(), len(asked)
            win.navigate("Home")  # the page left while it renders
            qtbot.waitUntil(lambda: status() == saved, timeout=60000)
        assert g["longest_s"] < BUDGET_S, f"the window stopped for {g['longest_s']:.1f} s while the report rendered"
        assert on_ui == [False] and during == (False, False, reason, writing) and (said, again) == (reason, before)
        qtbot.waitUntil(lambda: page.writing is None, timeout=30000)
        assert page.btn_report.isEnabled() and page.btn_validation.isEnabled() and btn.toolTip() == ""
        [entry] = page.ctx.audit_entries(action="export.report")
        assert entry["after"]["bytes"] == out[0].stat().st_size and len(htmls) == 1
        # its overlays reach Qt as images: 44 MB of HTML at 50 overlays held the window 0.8 s (review of UI-3)
        assert len(handed[0]) < 100_000 and "data:image" not in handed[0], len(handed[0])
        win.navigate("AI Model Test")
        out[0] = folder / "stopped.pdf"
        rendering.clear()
        press()
        qtbot.waitUntil(rendering.is_set, timeout=30000)
        assert win.close()  # Yes to "Stop the running work?": the job stops after its render and writes nothing
        assert not out[0].exists() and not [p.name for p in folder.iterdir() if p.name.endswith(".tmp")]
    assert pdf_content((folder / "report.pdf").read_bytes()) == pdf_content(ui_thread_pdf(htmls[0]))
    return htmls[0]


def test_req_tst_004_pdf_contains_every_miss_and_false_call(
    qtbot: QtBot, trained_ctx: AppContext, synthetic_dataset: Path
) -> None:
    """Every missed defect and false call of the run is named in the report with its own overlay, and the report holds
    each rate with its count and the AI model card."""
    page = run_page(qtbot, trained_ctx, synthetic_dataset / "test")
    rows = page.rows
    for r in rows[:2]:  # make sure both kinds are there: a missed defect and a false call, as the run might have none
        r["gt"], r["ai_result"] = ("NG", "OK") if r is rows[0] else ("OK", "NG")
    misses, false_calls = report.misses_and_false_calls(rows)
    assert misses and false_calls
    images = trained_ctx.report_images(rows)
    assert set(images) == {str(r["image"]) for r in misses + false_calls}
    html = page._report_html(images)
    for r in misses + false_calls:
        name = Path(r["image"]).name
        assert re.search(rf"{re.escape(name)}: labelled {r['gt']}.*?<img src='data:image/png;base64,", html), name
    assert f"Missed defects: {len(misses)}" in html and f"False calls: {len(false_calls)}" in html
    assert " of " in html and "95 % upper bound" in html
    assert "AI model card" in html and f"# Model card: {BOARD}" in html


def test_req_tst_004_export_asks_first_and_is_audited(
    qtbot: QtBot, trained_ctx: AppContext, synthetic_dataset: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Export Report asks first, naming the images, missed defects and false calls; No writes and audits nothing, Yes
    writes the PDF and audits it under the run."""
    page = run_page(qtbot, trained_ctx, synthetic_dataset / "test")
    page.shell.set_user("admin")  # only an Admin exports (Q58, #151)
    out = tmp_path / "report.pdf"
    monkeypatch.setattr(QFileDialog, "getSaveFileName", staticmethod(lambda *a, **k: (str(out), "PDF (*.pdf)")))
    asked: list[str] = []

    def answer(reply: QMessageBox.StandardButton) -> Any:
        return staticmethod(lambda _p, _t, text, *_a: asked.append(text) or reply)

    monkeypatch.setattr(QMessageBox, "question", answer(QMessageBox.StandardButton.No))
    page.export_report()
    qtbot.waitUntil(lambda: page.writing is None, timeout=30000)
    misses, false_calls = report.misses_and_false_calls(page.rows)
    assert asked == [
        f"Export the validation report of {len(page.rows)} images? It shows each of its {len(misses)} missed defects"
        f" and {len(false_calls)} false calls with its overlay, and the AI model card."
    ]
    assert not out.exists() and trained_ctx.audit_entries(action="export.report") == []
    monkeypatch.setattr(QMessageBox, "question", answer(QMessageBox.StandardButton.Yes))
    page.export_report()
    qtbot.waitUntil(lambda: page.writing is None, timeout=30000)
    assert out.read_bytes().startswith(b"%PDF")
    [entry] = trained_ctx.audit_entries(action="export.report")
    assert entry["after"]["run_uuid"] == page.rows[0]["run_uuid"]


def test_req_tst_004_export_report_renders_off_the_ui_thread(
    qtbot: QtBot, trained_ctx: AppContext, synthetic_dataset: Path, tmp_path: Path, dialogs: list[tuple[str, str]]
) -> None:
    """UI-3: Export Report rendered its PDF on the UI thread, which froze the window 2.5 s for 48 rows; now the overlays
    are read and the PDF rendered and written on the pool, the page saying so and taking no second press meanwhile
    (`renders_off_the_ui_thread`), with a missed defect and a false call among the rows, so the PDF holds overlays."""
    page = run_page(qtbot, trained_ctx, synthetic_dataset / "test")
    page.shell.set_user("admin")  # only an Admin exports (Q58, #151)
    rows = page.rows
    for r in rows[:2]:
        r["gt"], r["ai_result"] = ("NG", "OK") if r is rows[0] else ("OK", "NG")
    assert len(trained_ctx.report_images(rows)) >= 2
    saved = "Report saved: {file}"
    rendered = renders_off_the_ui_thread(qtbot, page, page.export_report, page.btn_report, tmp_path, saved)
    assert dialogs == [] and rendered.count("data:image/png;base64,") >= 2  # its overlays, handed to Qt as images


def test_req_tst_008_a_refused_report_says_why_and_turns_the_report_buttons_on_again(
    qtbot: QtBot, trained_ctx: AppContext, synthetic_dataset: Path, tmp_path: Path, dialogs: list[tuple[str, str]]
) -> None:
    """Validation Report… on a run of a folder is refused as its data is read on the pool (AOI-TST-007): its dialog
    shows, both buttons come on again and the status bar no longer says a report is being written; Export Report for a
    run no longer shown when its overlays are read writes nothing and says so (review of UI-3)."""
    page = run_page(qtbot, trained_ctx, synthetic_dataset / "test")
    page.shell.set_user("admin")  # only an Admin exports (Q58, #151)
    page.tabs.setCurrentIndex(1)
    page.history.selectRow(0)
    out = tmp_path / "validation.pdf"
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(QFileDialog, "getSaveFileName", staticmethod(lambda *a, **k: (str(out), "")))
        mp.setattr(QMessageBox, "question", staticmethod(lambda *a, **k: QMessageBox.StandardButton.Yes))
        page.validation_report()
        assert page.writing == str(out)
        qtbot.waitUntil(lambda: page.writing is None, timeout=30000)
        assert len(dialogs) == 1 and dialogs[0][0].startswith("AOI-TST-007") and not out.exists(), dialogs
        assert page.btn_report.isEnabled() and page.btn_validation.isEnabled()
        assert not page.shell.statusBar().currentMessage().startswith("Writing the report")
        page.export_report()
        page.rows = []  # another run, or none, shown before its overlays are read
        qtbot.waitUntil(lambda: page.writing is None, timeout=30000)
    assert not out.exists() and page.shell.statusBar().currentMessage().endswith("the run is no longer shown")


def test_req_tst_004_csv_bom_and_korean_round_trip(trained_ctx: AppContext, tmp_path: Path) -> None:
    """The CSV starts with a UTF-8 BOM, so Excel opens Korean text intact, and reads back row for row."""
    rows = [{"image": "보드_001.png", "gt": "NG", "ai_result": "NG", "defect_type": "솔더 브리지"},
            {"image": "보드_002.png", "gt": "OK", "ai_result": "OK", "defect_type": ""}]  # fmt: skip
    trained_ctx.set_user("admin")  # only an Admin exports (Q58, #151)
    out = tmp_path / "결과.csv"
    trained_ctx.export_csv(out, rows, "test results")
    data = out.read_bytes()
    assert data.startswith(b"\xef\xbb\xbf")
    with out.open(encoding="utf-8-sig", newline="") as f:
        assert list(csv.DictReader(f)) == rows


def test_req_tst_004_no_csv_cell_runs_as_a_formula(trained_ctx: AppContext, tmp_path: Path) -> None:
    """#113: a text cell that starts with =, +, -, @, a tab or a carriage return is written with a ' before it, so a
    spreadsheet opens it as the text it is and runs nothing; numbers, a number written as text among them, and other
    text are written as they are."""
    risky = ['=HYPERLINK("http://x")', "+1+1", "-2+3", "@SUM(A1)", "\tx", "\rx"]
    rows = [{"image": text, "score": -0.5, "shown": "-0.250", "operator": "op=1"} for text in risky]
    trained_ctx.set_user("admin")  # only an Admin exports (Q58, #151)
    out = tmp_path / "results.csv"
    trained_ctx.export_csv(out, rows, "test results")
    with out.open(encoding="utf-8-sig", newline="") as f:
        read = list(csv.DictReader(f))
    assert [r["image"] for r in read] == [f"'{text}" for text in risky]
    assert {r["score"] for r in read} == {"-0.5"} and {r["operator"] for r in read} == {"op=1"}
    assert {r["shown"] for r in read} == {"-0.250"}
