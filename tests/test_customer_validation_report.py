"""REQ-TST-008 (stage S48): the customer validation report of a run on a frozen dataset version's locked validation set
follows the Customers & Launch validation steps: the data agreed, the targets agreed before testing beside the results,
the locked set and its manifest hash, results with counts and bounds, one page per missed defect and false call, the AI
model card, known limits and signature lines for the customer and the AI lead. Results on the synthetic boards prove a
code path; they are never quoted as accuracy."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, cast

import pytest
from PySide6.QtWidgets import QFileDialog
from pytestqt.qtbot import QtBot

from aoi.core import report
from aoi.core.services import AppContext
from aoi.data.db import new_uuid
from aoi.errors import AoiError
from aoi.ui.pages.model_test import ModelTestPage
from tests.test_req_done_in_v01 import BOARD, _window
from tests.test_test_dataset import held_out

SECTIONS = ("1. Data", "2. Targets agreed before testing", "3. Locked validation set", "4. Results",
            "5. AI model card", "6. Known limits", "7. Sign-off")  # fmt: skip


def with_agreement(ctx: AppContext) -> None:
    """A labeller agreement check stored for TINY, as Training's Datasets tab stores one (S34)."""
    ctx.db.insert("agreement_checks", {
        "uuid": new_uuid(), "set_uuid": new_uuid(), "board_model": BOARD, "labeller_a": "engineer",
        "labeller_b": "admin", "images": 100, "ok_ng_agree": 99, "both_ng": 40, "type_agree": 37, "ok_ng_target": 98,
        "type_target": 90, "agreed": 1, "run_by": str(ctx.db.user_uuid("engineer")),
        "at_utc": "2026-10-09T00:00:00+00:00",
    })  # fmt: skip


def validated(ctx: AppContext) -> tuple[str, dict[str, Any]]:
    """A validation run of TINY's locked validation set, with an agreement check, and the report's data."""
    version, _ = held_out(ctx)
    with_agreement(ctx)
    run_uuid = ctx.test_dataset(version)[1][0]["run_uuid"]
    return run_uuid, ctx.validation_report_data(run_uuid)


def page_html(qtbot: QtBot, ctx: AppContext, data: dict[str, Any]) -> str:
    win = _window(qtbot, ctx, "Engineer")
    assert win.navigate("AI Model Test")
    return cast(ModelTestPage, win.pages["AI Model Test"])._validation_html(data)


def test_req_tst_008_sections_present(qtbot: QtBot, trained_ctx: AppContext) -> None:
    """Every section is there, in order, each heading with its Korean draft, and the report names the dataset version,
    its manifest SHA-256, the agreement check and two signature lines."""
    _, data = validated(trained_ctx)
    html = page_html(qtbot, trained_ctx, data)
    at = [html.index(s) for s in SECTIONS]
    assert at == sorted(at) and "(draft)" in html
    assert data["dataset"]["name"] in html and data["dataset"]["manifest_sha256"] in html
    assert "OK or NG agree on 99 of 100 images" in html
    assert re.search(r"<td>Customer</td>(<td>&nbsp;</td>){3}", html) and re.search(r"<td>AI lead</td>", html)
    assert "names in the audit trail are picked, not signed in" in html


def test_req_tst_008_targets_compared_with_results(qtbot: QtBot, trained_ctx: AppContext) -> None:
    """Each agreed target stands beside its result on the run and says whether it is met: missed Critical defects,
    the false call rate with its count and bound, and the time per image at the 95th percentile."""
    _, data = validated(trained_ctx)
    rows = data["run"]["results"]
    targets = {t["target"]: t for t in data["targets"]}
    assert set(targets) == {"missed_critical", "false_call_rate", "seconds_per_image"}
    crit = [r for r in rows if r["gt"] == "NG" and report.critical(r["defect_type"])]
    missed = [r for r in crit if r["ai_result"] == "OK"]
    assert (targets["missed_critical"]["result"]["n"], targets["missed_critical"]["result"]["of"]) == (
        len(missed),
        len(crit),
    )
    assert targets["missed_critical"]["met"] == (len(missed) == 0)
    assert targets["seconds_per_image"]["result"] == report.p95([r["ms"] / 1000 for r in rows])
    html = page_html(qtbot, trained_ctx, data)
    for name in ("Missed Critical defects", "False call rate", "Time per image, 95th percentile"):
        assert re.search(rf"<td>{name}</td><td>[^<]+</td><td>[^<]+</td><td>(Met|Not met)</td>", html), name


def test_req_tst_008_every_miss_has_a_page(qtbot: QtBot, trained_ctx: AppContext) -> None:
    """Each missed defect and false call starts a page of its own with its row and its overlay."""
    _, data = validated(trained_ctx)
    rows = data["run"]["results"]
    rows[0]["gt"], rows[0]["ai_result"] = "NG", "OK"  # at least one of each, whatever the run judged
    rows[1]["gt"], rows[1]["ai_result"] = "OK", "NG"
    data["images"] = trained_ctx.report_images(rows)
    misses, false_calls = report.misses_and_false_calls(rows)
    html = page_html(qtbot, trained_ctx, data)
    pages = re.findall(
        r"<div style='page-break-before:always'><h3>(Missed defect|False call)</h3><p>(.*?)</p></div>", html
    )
    assert len(pages) == len(misses) + len(false_calls)
    assert all("<img src='data:image/png;base64," in body for _, body in pages)


def test_req_tst_008_refused_without_a_version_or_agreement(trained_ctx: AppContext, synthetic_dataset: Path) -> None:
    """A run on a folder, and a run on a version of a board model with no agreement check, are refused with
    AOI-TST-007."""
    ctx = trained_ctx
    folder_run = ctx.batch_test(BOARD, str(synthetic_dataset / "test"))[1][0]["run_uuid"]
    with pytest.raises(AoiError) as e:
        ctx.validation_report_data(folder_run)
    assert e.value.code == "AOI-TST-007" and "used a folder" in e.value.what
    version, _ = held_out(ctx)
    run_uuid = ctx.test_dataset(version)[1][0]["run_uuid"]
    with pytest.raises(AoiError) as e:
        ctx.validation_report_data(run_uuid)
    assert e.value.code == "AOI-TST-007" and "no labeller agreement check" in e.value.what


def test_req_tst_008_report_written_and_audited(
    qtbot: QtBot, trained_ctx: AppContext, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Validation Report… on History writes the PDF and audits it under the run."""
    run_uuid, _ = validated(trained_ctx)
    win = _window(qtbot, trained_ctx, "Admin")  # only an Admin exports (Q58, #151)
    assert win.navigate("AI Model Test")
    page = cast(ModelTestPage, win.pages["AI Model Test"])
    page.tabs.setCurrentIndex(1)
    page.history.selectRow(0)
    out = tmp_path / "validation.pdf"
    monkeypatch.setattr(QFileDialog, "getSaveFileName", staticmethod(lambda *a, **k: (str(out), "PDF (*.pdf)")))
    page.validation_report()
    qtbot.waitUntil(lambda: page._bg is None and out.exists(), timeout=30000)
    assert out.read_bytes().startswith(b"%PDF")
    assert trained_ctx.audit_entries(action="export.report")[0]["after"]["run_uuid"] == run_uuid
