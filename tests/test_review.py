"""REQ-INSP-013 (ADR 0013): an NG or WARN board is reviewed on the line as Real defect or False call; the verdict stays
as it was given, the review stands beside it with who, when and why, and every review is an audit entry."""

from __future__ import annotations

import csv
from pathlib import Path

import pytest
from PySide6.QtWidgets import QFileDialog, QInputDialog
from pytestqt.qtbot import QtBot

from aoi.core.services import DEFECT, FALSE_CALL, AppContext
from aoi.errors import AoiError
from aoi.ui.pages.base import cell_text
from aoi.ui.pages.logs import REVIEW_COLUMN
from aoi.ui.pages.review import FALSE_CALL_REASONS
from tests.conftest import listed
from tests.test_req_done_in_v01 import BOARD, _inspect_one, _window


def _ng_record(qtbot: QtBot, ctx: AppContext, ng_board: Path, role: str = "Operator") -> tuple[int, object]:
    win = _window(qtbot, ctx, role)
    page = _inspect_one(qtbot, win, ng_board)
    assert page.last is not None and page.last.verdict == "NG"
    (row,) = ctx.inspections(board_model=BOARD)
    return int(row["id"]), win


def test_req_insp_013_a_false_call_keeps_the_verdict_and_is_audited(
    qtbot: QtBot, trained_ctx: AppContext, ng_board: Path
) -> None:
    """An Operator marks the NG board a False call with a reason: the record keeps NG, carries the review with who
    reviewed it, and the audit trail holds the review with the verdict; changing it to Real defect is a second entry
    whose `before` is the first review. Home's Inspect card counts the false call."""
    iid, win = _ng_record(qtbot, trained_ctx, ng_board)
    saved = trained_ctx.review_result(iid, FALSE_CALL, "  Dust on the board  ")
    (row,) = trained_ctx.inspections(board_model=BOARD)
    assert row["result"] == "NG"  # never changed
    assert (row["review"], row["review_reason"], row["review_by"]) == (FALSE_CALL, "Dust on the board", "operator")
    assert row["review_time"] and saved["review"] == FALSE_CALL
    st = trained_ctx.board_status(BOARD)
    assert (st.reviewed, st.false_calls) == (1, 1)
    trained_ctx.review_result(iid, DEFECT)
    first, second = reversed(trained_ctx.audit_entries(action="inspection.review"))
    assert first["before"] is None and first["after"]["review"] == FALSE_CALL and first["after"]["verdict"] == "NG"
    assert first["reason"] == "Dust on the board" and first["role"] == "Operator"
    assert second["before"]["review"] == FALSE_CALL and second["after"]["review"] == DEFECT
    assert (trained_ctx.board_status(BOARD).reviewed, trained_ctx.board_status(BOARD).false_calls) == (1, 0)
    home = win.pages["Home"]
    trained_ctx.review_result(iid, FALSE_CALL, "Glare")
    win.navigate("Home")
    assert "False calls 1 of 1 reviewed" in home.status_labels["Inspect"].text()


@pytest.mark.parametrize(
    ("review", "reason", "why"),
    [
        (FALSE_CALL, "", "a False call needs a reason"),
        (FALSE_CALL, "   ", "a False call needs a reason"),
        ("MAYBE", None, "the review is neither Real defect nor False call"),
    ],
)
def test_req_insp_013_a_review_that_cannot_stand_changes_nothing(
    qtbot: QtBot, trained_ctx: AppContext, ng_board: Path, review: str, reason: str | None, why: str
) -> None:
    iid, _win = _ng_record(qtbot, trained_ctx, ng_board)
    with pytest.raises(AoiError) as e:
        trained_ctx.review_result(iid, review, reason)
    assert e.value.code == "AOI-INSP-015" and why in str(e.value)
    (row,) = trained_ctx.inspections(board_model=BOARD)
    assert row["review"] is None and not trained_ctx.audit_entries(action="inspection.review")


def test_req_insp_013_an_unknown_record_is_refused(trained_ctx: AppContext) -> None:
    trained_ctx.set_user("operator")
    with pytest.raises(AoiError) as e:
        trained_ctx.review_result(987654, DEFECT)
    assert e.value.code == "AOI-INSP-015" and "no such record" in str(e.value)


def test_req_insp_013_f11_on_inspection_asks_a_reason_and_saves_the_false_call(
    qtbot: QtBot, trained_ctx: AppContext, ng_board: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """F11 on Inspection after an NG board: the reason list opens with the common causes first, the pick is saved on
    the pool thread, and the bar then says who reviewed it. Cancel saves nothing. F10 then turns it into Real defect."""
    iid, win = _ng_record(qtbot, trained_ctx, ng_board)
    page = win.pages["Inspection"]
    bar = page.review
    assert bar.act_defect.isEnabled() and bar.act_false.isEnabled()
    assert bar.act_defect.shortcut().toString() == "F10" and bar.act_false.shortcut().toString() == "F11"
    asked: list[list[str]] = []

    def cancel(*a: object, **k: object) -> tuple[str, bool]:
        asked.append(list(a[3]))  # type: ignore[call-overload]
        return "", False

    monkeypatch.setattr(QInputDialog, "getItem", staticmethod(cancel))
    bar.act_false.trigger()
    assert asked == [list(FALSE_CALL_REASONS)]
    assert trained_ctx.inspections(board_model=BOARD)[0]["review"] is None
    pick = FALSE_CALL_REASONS[1]
    monkeypatch.setattr(QInputDialog, "getItem", staticmethod(lambda *a, **k: (pick, True)))
    bar.act_false.trigger()
    qtbot.waitUntil(lambda: bar.saving is None and bar.record is not None and bar.record.get("review") == FALSE_CALL)
    assert "False call" in bar.line.text() and pick in bar.line.text() and "operator" in bar.line.text()
    (row,) = trained_ctx.inspections(board_model=BOARD)
    assert (row["id"], row["review"], row["review_reason"]) == (iid, FALSE_CALL, pick)
    bar.act_defect.trigger()
    qtbot.waitUntil(lambda: bar.saving is None and bar.record is not None and bar.record.get("review") == DEFECT)
    assert trained_ctx.inspections(board_model=BOARD)[0]["review"] == DEFECT


def test_req_insp_013_no_review_without_an_ng_or_warn_record(
    qtbot: QtBot, trained_ctx: AppContext, synthetic_dataset: Path
) -> None:
    """Before any board, and after an OK board, the review keys do nothing and the bar says nothing."""
    win = _window(qtbot, trained_ctx, "Operator")
    bar = win.pages["Inspection"].review
    assert not bar.act_defect.isEnabled() and not bar.act_false.isEnabled() and bar.line.text() == ""
    ok = sorted(synthetic_dataset.glob("test/ok/*.png"))[0]
    page = _inspect_one(qtbot, win, ok)
    assert page.last is not None
    if page.last.verdict == "OK":
        assert not bar.act_defect.isEnabled() and bar.line.text() == ""


def test_req_insp_013_logs_review_column_summary_and_csv(
    qtbot: QtBot, trained_ctx: AppContext, ng_board: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Logs & Export shows the review in its Review column and the summary line, reviews the selected record with the
    same keys, and the CSV export carries the four review columns after the others."""
    iid, win = _ng_record(qtbot, trained_ctx, ng_board, role="Admin")  # only an Admin exports (Q58, #151)
    logs = win.pages["Logs & Export"]
    win.navigate("Logs & Export")
    listed(qtbot, logs)
    assert logs.table.horizontalHeaderItem(REVIEW_COLUMN).text() == "Review"
    assert cell_text(logs.table, 0, REVIEW_COLUMN) == ""
    logs.table.selectRow(0)
    assert logs.review.act_false.isEnabled()
    monkeypatch.setattr(QInputDialog, "getItem", staticmethod(lambda *a, **k: ("Glare or lighting in the image", True)))
    logs.review.act_false.trigger()
    qtbot.waitUntil(lambda: cell_text(logs.table, 0, REVIEW_COLUMN) == "False call")
    logs.refresh()
    assert "reviewed 1, false calls 1" in logs.summary.text()
    out = tmp_path / "inspections.csv"
    monkeypatch.setattr(QFileDialog, "getSaveFileName", staticmethod(lambda *a, **k: (str(out), "CSV (*.csv)")))
    logs.export_csv()
    qtbot.waitUntil(lambda: out.exists(), timeout=30000)
    with out.open(encoding="utf-8-sig", newline="") as fh:
        reader = csv.DictReader(fh)
        assert reader.fieldnames is not None
        assert reader.fieldnames[-5:] == ["ai_check", "review", "review_reason", "review_by", "review_time"]
        (row,) = list(reader)
    assert (int(row["id"]), row["review"], row["review_reason"]) == (iid, FALSE_CALL, "Glare or lighting in the image")
