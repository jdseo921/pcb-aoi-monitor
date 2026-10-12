"""REQ-TST-008 (Customers & Launch, "Validation", step 2: agree on targets before testing): an Engineer records the
targets a customer agreed for a board model's validation, and with whom; the next validation run keeps them, a run made
before keeps the targets it started with, and the customer validation report holds each run to its own. The runs below
are on the synthetic TINY boards: they prove the code path, never an accuracy."""

from __future__ import annotations

from typing import Any, cast

import pytest
from PySide6.QtCore import Qt
from pytestqt.qtbot import QtBot

from aoi.core import report
from aoi.core.services import AppContext
from aoi.errors import AoiError
from aoi.ui.pages.model_test import ModelTestPage
from tests.test_customer_validation_report import page_html, with_agreement
from tests.test_req_done_in_v01 import BOARD, _window
from tests.test_test_dataset import held_out

ACME = "ACME Korea, J. Kim (quality lead), email of 2026-10-10"


def _held_to(data: dict[str, Any]) -> dict[str, float]:
    return {t["target"]: t["agreed"] for t in data["targets"]}


def test_req_tst_008_agreed_targets_hold_the_next_run_and_never_one_made_before(
    qtbot: QtBot, trained_ctx: AppContext
) -> None:
    """With none agreed, a run is held to the proposed defaults and its report says so; targets recorded then are in
    force for the next run, kept with it and audited with the targets before; the run made before keeps the defaults,
    and targets recorded after the second run leave its report as it was."""
    ctx = trained_ctx
    version, _ = held_out(ctx)
    with_agreement(ctx)
    assert ctx.validation_targets(BOARD) is None
    before = ctx.test_dataset(version)[1][0]["run_uuid"]

    row = ctx.set_validation_targets(BOARD, 1, 0.1, 2.5, f"  {ACME} ")
    assert (row["missed_critical"], row["false_call_rate"], row["seconds_per_image"]) == (1, 0.1, 2.5)
    assert (row["agreed_with"], row["user"]) == (ACME, "engineer") and ctx.validation_targets(BOARD) == row
    (entry,) = ctx.audit_entries(action="validation.targets")
    assert entry["before"] is None and entry["object_uuid"] == BOARD
    assert entry["after"] == {"uuid": row["uuid"], "missed_critical": 1, "false_call_rate": 0.1,
                              "seconds_per_image": 2.5, "agreed_with": ACME}  # fmt: skip

    after = ctx.test_dataset(version)[1][0]["run_uuid"]
    ctx.set_validation_targets(BOARD, 0, 0.02, 0.5, "ACME Korea, another meeting")  # after both runs
    assert ctx.audit_entries(action="validation.targets")[0]["before"] == row

    old, new = ctx.validation_report_data(before), ctx.validation_report_data(after)
    assert old["agreed"] is None and _held_to(old) == report.DEFAULT_TARGETS
    assert new["agreed"] == row and _held_to(new) == {"missed_critical": 1, "false_call_rate": 0.1,
                                                      "seconds_per_image": 2.5}  # fmt: skip
    rows = new["run"]["results"]
    fc = [r for r in rows if r["gt"] == "OK" and r["ai_result"] in ("NG", "WARN")]
    ok = [r for r in rows if r["gt"] == "OK"]
    (rate,) = [t for t in new["targets"] if t["target"] == "false_call_rate"]
    assert rate["met"] == (len(fc) / len(ok) <= 0.1)  # judged against the agreed 10 %, not the default 5 %
    assert ctx.audit_entries(action="test.run")[0]["after"]["targets"] == row  # the run's entry names them too

    html_old, html_new = page_html(qtbot, ctx, old), page_html(qtbot, ctx, new)
    assert f"No targets were agreed for {BOARD} before this run started" in html_old and "<th>Proposed</th>" in html_old
    assert f"Agreed with {ACME} before testing: recorded by engineer on" in html_new and "<th>Agreed</th>" in html_new
    assert "<td>10 %</td>" in html_new and "<td>2.50 s</td>" in html_new and "<td>5 %</td>" in html_old


@pytest.mark.parametrize(
    ("values", "why"),
    [
        ((-1, 0.05, 1.0, ACME), "a whole number from 0 to 100"),
        ((101, 0.05, 1.0, ACME), "a whole number from 0 to 100"),
        ((1.5, 0.05, 1.0, ACME), "a whole number from 0 to 100"),
        ((0, -0.01, 1.0, ACME), "from 0 % to 100 %"),
        ((0, 1.01, 1.0, ACME), "from 0 % to 100 %"),
        ((0, float("nan"), 1.0, ACME), "from 0 % to 100 %"),
        ((0, 0.05, 0.0, ACME), "from 0.01 s to 60 s"),
        ((0, 0.05, 61.0, ACME), "from 0.01 s to 60 s"),
        ((0, 0.05, 1.0, "   "), "who at the customer agreed them is not given"),
        ((0, 0.05, 1.0, "x" * 201), "longer than 200 characters"),
    ],
)
def test_req_tst_008_targets_out_of_range_or_agreed_by_no_one_are_refused(
    ctx: AppContext, values: tuple[Any, ...], why: str
) -> None:
    """AOI-TST-008 names what is wrong, and nothing is stored or audited."""
    ctx.ensure_board_model("B")
    with pytest.raises(AoiError) as e:
        ctx.set_validation_targets("B", *values)
    assert e.value.code == "AOI-TST-008" and why in e.value.what and "Nothing was changed" in e.value.what
    assert ctx.validation_targets("B") is None and ctx.audit_entries(action="validation.targets") == []


def test_req_tst_008_targets_of_no_board_model_or_by_an_operator_are_refused(ctx: AppContext) -> None:
    with pytest.raises(AoiError) as e:
        ctx.set_validation_targets("NOPE", 0, 0.05, 1.0, ACME)
    assert e.value.code == "AOI-TST-008" and "no such board model" in e.value.what
    ctx.ensure_board_model("B")
    ctx.set_user("operator")
    with pytest.raises(AoiError) as e:
        ctx.set_validation_targets("B", 0, 0.05, 1.0, ACME)
    assert e.value.code == "AOI-USR-001" and ctx.validation_targets("B") is None


def test_req_tst_008_agreed_targets_sheet_on_ai_model_test(qtbot: QtBot, trained_ctx: AppContext) -> None:
    """The line under Source names the targets the next run is held to; Agreed Targets… opens the sheet with them,
    Save Targets stays off until someone is named, Esc closes it unsaved, and saving records the sheet's values in
    percent and seconds and names who agreed them on the line."""
    win = _window(qtbot, trained_ctx, "Engineer")
    with qtbot.waitActive(win):
        win.activateWindow()  # so the sheet takes the focus
    assert win.navigate("AI Model Test")
    page = cast(ModelTestPage, win.pages["AI Model Test"])
    sheet = page.targets_sheet
    assert page.targets_line.text() == (
        "Targets for the next run: no missed Critical defect, a false call rate of 5 % or less, 1.00 s or less per"
        " image. These are the proposed defaults: none were agreed for TINY."
    )
    qtbot.mouseClick(page.btn_targets, Qt.MouseButton.LeftButton)
    assert sheet.isVisible() and not sheet.btn_save.isEnabled() and (win.width(), win.height()) == (1600, 900)
    assert (sheet.missed.value(), sheet.false_calls.value(), sheet.seconds.value()) == (0, 5.0, 1.0)
    assert sheet.missed.hasFocus()
    qtbot.keyClicks(sheet.agreed_with, "ACME")
    qtbot.keyClick(sheet.agreed_with, Qt.Key.Key_Escape)
    assert not sheet.isVisible() and trained_ctx.validation_targets(BOARD) is None

    page.open_targets()
    sheet.missed.setValue(2)
    sheet.false_calls.setValue(7.5)
    sheet.seconds.setValue(0.8)
    qtbot.keyClicks(sheet.agreed_with, ACME)
    assert sheet.btn_save.isEnabled()
    qtbot.mouseClick(sheet.btn_save, Qt.MouseButton.LeftButton)
    row = trained_ctx.validation_targets(BOARD)
    assert row is not None and not sheet.isVisible()
    assert (row["missed_critical"], row["false_call_rate"], row["seconds_per_image"]) == (2, 0.075, 0.8)
    line = page.targets_line.text()
    assert "at most 2 missed Critical defects, a false call rate of 7.5 % or less, 0.80 s or less per image." in line
    assert f"Agreed with {ACME}; recorded by engineer on" in line
    page.open_targets()  # opens on the targets in force, and asks again who agreed a change
    assert (sheet.false_calls.value(), sheet.agreed_with.text()) == (7.5, "")
