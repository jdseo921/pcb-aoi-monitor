"""REQ-TST-004 (stage S47, part 1): AI Model Test's report holds the rates with counts and bounds, recall per defect
type, every missed defect and false call with its overlay, and the AI model card; exporting it asks first, naming the
counts, and is audited; the CSV is UTF-8 with a BOM and keeps Korean text. Results on the synthetic boards prove a code
path; they are never quoted as accuracy."""

from __future__ import annotations

import csv
import re
from pathlib import Path
from typing import Any, cast

import pytest
from PySide6.QtWidgets import QFileDialog, QMessageBox
from pytestqt.qtbot import QtBot

from aoi.core import report
from aoi.core.services import AppContext
from aoi.ui.pages.model_test import ModelTestPage
from tests.test_req_done_in_v01 import BOARD, _window


def run_page(qtbot: QtBot, ctx: AppContext, folder: Path) -> ModelTestPage:
    win = _window(qtbot, ctx, "Engineer")
    assert win.navigate("AI Model Test")
    page = cast(ModelTestPage, win.pages["AI Model Test"])
    page.source.setCurrentIndex(page.source.count() - 1)
    page.folder = str(folder)
    page.run()
    qtbot.waitUntil(lambda: page.btn_run.isEnabled() and bool(page.rows), timeout=120000)
    return page


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
    out = tmp_path / "report.pdf"
    monkeypatch.setattr(QFileDialog, "getSaveFileName", staticmethod(lambda *a, **k: (str(out), "PDF (*.pdf)")))
    asked: list[str] = []

    def answer(reply: QMessageBox.StandardButton) -> Any:
        return staticmethod(lambda _p, _t, text, *_a: asked.append(text) or reply)

    monkeypatch.setattr(QMessageBox, "question", answer(QMessageBox.StandardButton.No))
    page.export_report()
    qtbot.waitUntil(lambda: page._bg is None, timeout=30000)
    misses, false_calls = report.misses_and_false_calls(page.rows)
    assert asked == [
        f"Export the validation report of {len(page.rows)} images? It shows each of its {len(misses)} missed defects"
        f" and {len(false_calls)} false calls with its overlay, and the AI model card."
    ]
    assert not out.exists() and trained_ctx.audit_entries(action="export.report") == []
    monkeypatch.setattr(QMessageBox, "question", answer(QMessageBox.StandardButton.Yes))
    page.export_report()
    qtbot.waitUntil(lambda: page._bg is None and out.exists(), timeout=30000)
    assert out.read_bytes().startswith(b"%PDF")
    [entry] = trained_ctx.audit_entries(action="export.report")
    assert entry["after"]["run_uuid"] == page.rows[0]["run_uuid"]


def test_req_tst_004_csv_bom_and_korean_round_trip(trained_ctx: AppContext, tmp_path: Path) -> None:
    """The CSV starts with a UTF-8 BOM, so Excel opens Korean text intact, and reads back row for row."""
    rows = [{"image": "보드_001.png", "gt": "NG", "ai_result": "NG", "defect_type": "솔더 브리지"},
            {"image": "보드_002.png", "gt": "OK", "ai_result": "OK", "defect_type": ""}]  # fmt: skip
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
    out = tmp_path / "results.csv"
    trained_ctx.export_csv(out, rows, "test results")
    with out.open(encoding="utf-8-sig", newline="") as f:
        read = list(csv.DictReader(f))
    assert [r["image"] for r in read] == [f"'{text}" for text in risky]
    assert {r["score"] for r in read} == {"-0.5"} and {r["operator"] for r in read} == {"op=1"}
    assert {r["shown"] for r in read} == {"-0.250"}
