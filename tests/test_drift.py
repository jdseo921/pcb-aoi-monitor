"""REQ-INSP-019 (Engineering standard, "Watch and retrain"): each board model and view is watched for drift, its newest
boards against the boards judged before them by the same AI model and recipe revision, and a measure that moves beyond
its control limit raises one WARN alarm, AOI-INSP-018, as it crosses. The rows below are written through the data
layer with made-up verdicts, scores and features, so nothing here is an accuracy."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from pytestqt.qtbot import QtBot

from aoi.core import drift
from aoi.core.services import DEFECT, FALSE_CALL, AppContext
from aoi.ui.errors import alarm_text
from tests.test_req_done_in_v01 import BOARD, _inspect_one, _window


def _rows(results: str, score: float = 0.5, inliers: int = 300, engine: str = "m1") -> list[dict[str, Any]]:
    """Rows newest first, one per letter of `results` (O OK, N NG, W WARN), the OK boards' scores and features
    alternating a little around `score` and `inliers`."""
    verdict = {"O": "OK", "N": "NG", "W": "WARN"}
    return [{"view": "Top", "model_uuid": engine, "recipe_uuid": "r1", "result": verdict[c],
             "score": score + (0.05 if i % 2 else -0.05), "alignment_inliers": inliers + (10 if i % 2 else -10)}
            for i, c in enumerate(results)]  # fmt: skip


def test_req_insp_019_control_limits_count_from_the_baseline() -> None:
    """A rate moves when its count in the window is less likely than 0.135 % at the baseline's rate: with no NG board
    in 500, 3 of 50 moves and 2 do not; with 10 in 500, 6 do. A mean moves beyond three standard errors."""
    clean, some = [False] * 500, [True] * 10 + [False] * 490
    assert not drift.rate_moved([True] * 2 + [False] * 48, clean)
    assert drift.rate_moved([True] * 3 + [False] * 47, clean)
    assert not drift.rate_moved([True] * 5 + [False] * 45, some) and drift.rate_moved([True] * 6 + [False] * 44, some)
    before = [0.45, 0.55] * 100  # mean 0.5, standard deviation about 0.05: three standard errors of 20 are 0.034
    assert drift.mean_moved([0.54] * 20, before, rising=True) and not drift.mean_moved([0.53] * 20, before, rising=True)
    assert drift.mean_moved([0.46] * 20, before, rising=False) and not drift.mean_moved([0.54] * 20, before, False)


def test_req_insp_019_each_measure_moves_on_its_own_and_only_on_a_full_baseline() -> None:
    """NG rate, WARN rate, the OK boards' AI score (up) and their matched features (down) each move alone; a baseline
    under 200 boards judges nothing; a new AI model starts a new baseline; and a measure alarms only as it crosses."""
    baseline = _rows("O" * 500)
    assert drift.board_drift(_rows("N" * 5 + "O" * 45) + baseline) == [drift.Drift(drift.NG_RATE, 0.1, 0.0, 5, 50, 500)]
    assert [d.measure for d in drift.board_drift(_rows("W" * 5 + "O" * 45) + baseline)] == [drift.WARN_RATE]
    assert [d.measure for d in drift.board_drift(_rows("O" * 50, score=0.6) + baseline)] == [drift.OK_SCORE]
    assert [d.measure for d in drift.board_drift(_rows("O" * 50, inliers=250) + baseline)] == [drift.ALIGNMENT]
    assert drift.board_drift(_rows("N" * 50) + _rows("O" * 199)) == []  # 199 boards before: too few to judge
    rows = _rows("N" * 5 + "O" * 45, engine="m2") + baseline  # the baseline is the AI model before
    assert drift.board_drift(drift.same_engine(rows, "Top")) == [] and drift.same_engine(rows, "Bottom") == []

    now = drift.board_drift(_rows("N" * 3 + "O" * 47) + baseline)
    earlier = drift.board_drift(_rows("N" * 2 + "O" * 47) + baseline)
    assert [d.measure for d in drift.crossed(now, earlier)] == [drift.NG_RATE]  # the third NG board crosses
    assert drift.crossed(now, now) == []  # the fourth does not alarm again
    fc = [True] * 5 + [False] * 210 + [True] * 5  # newest first: 5 of the last 20, 5 of the 200 before
    assert drift.review_drift(fc) == drift.Drift(drift.FALSE_CALLS, 0.25, 0.025, 5, 20, 200)
    assert drift.review_drift(fc[1:]) is None and drift.review_drift(fc[:69]) is None  # 4 of 20; 49 reviews before


def _seed(ctx: AppContext, results: str, engine: tuple[str | None, str | None]) -> None:
    """Records of TINY in the Top view judged by `engine` (AI model and recipe UUIDs), oldest first, as `_rows`."""
    for r in reversed(_rows(results[::-1])):
        rec = {"board_model": BOARD, "view": "Top", "model_uuid": engine[0], "recipe_uuid": engine[1],
               "result": r["result"], "score": r["score"], "metrics": {"alignment_inliers": r["alignment_inliers"]},
               "operator": "kim"}  # fmt: skip
        ctx.db.add_inspection(rec, [])


def _drift_alarms(ctx: AppContext) -> list[dict[str, Any]]:
    return [a for a in ctx.alarms() if a["code"] == "AOI-INSP-018"]


def test_req_insp_019_the_board_that_crosses_the_ng_limit_alarms_once_on_inspection_and_home(
    qtbot: QtBot, trained_ctx: AppContext, ng_board: Path
) -> None:
    """With 500 OK boards and then 2 NG boards among the last 49 judged by the active AI model and recipe, the NG board
    inspected next is the third NG of 50: its save stores one drift alarm, the Inspection page's alarm log shows it,
    and Home's Inspect card names the drift; the next NG board raises none, as the measure is out already."""
    engine = trained_ctx.inspector(BOARD)
    _seed(trained_ctx, "O" * 500 + "N" * 2 + "O" * 47, (engine.model_uuid, engine.recipe_uuid))
    win = _window(qtbot, trained_ctx, "Operator")
    page = _inspect_one(qtbot, win, ng_board)
    assert page.last is not None and page.last.verdict == "NG"
    (alarm,) = _drift_alarms(trained_ctx)
    said = f"Drift on {BOARD} (Top): 3 of the last 50 boards called NG; 0.0 % of the 500 before"
    assert (alarm["level"], alarm_text(alarm)) == ("WARN", said)
    assert any(said in page.alarms.item(i).text() for i in range(page.alarms.count()))
    assert trained_ctx.board_status(BOARD).drifted == (drift.NG_RATE,)
    win.navigate("Home")
    assert "Drift: NG rate up. See the alarm log on Inspection." in win.pages["Home"].status_labels["Inspect"].text()

    page = _inspect_one(qtbot, win, ng_board)
    qtbot.waitUntil(lambda: len(trained_ctx.inspections(board_model=BOARD)) == 551, timeout=30000)
    assert len(_drift_alarms(trained_ctx)) == 1


def test_req_insp_019_a_drift_check_that_fails_leaves_the_board_saved(
    trained_ctx: AppContext, ng_board: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def broken(rows: object) -> list[drift.Drift]:
        raise ValueError("a bug in the drift check")

    monkeypatch.setattr(drift, "board_drift", broken)
    assert trained_ctx.inspect_file(BOARD, str(ng_board)).verdict == "NG"
    assert len(trained_ctx.inspections(board_model=BOARD)) == 1 and _drift_alarms(trained_ctx) == []


def test_req_insp_019_the_review_that_crosses_the_false_call_limit_alarms_once(ctx: AppContext) -> None:
    """With 5 False calls among the oldest reviews and 4 among the newest, a Real defect review raises nothing and the
    next False call is the fifth of the last 20: one drift alarm names the share; the next False call raises none."""
    ctx.ensure_board_model("B")
    start = datetime(2026, 1, 1, tzinfo=UTC)
    reviews = [FALSE_CALL] * 5 + [DEFECT] * 210 + [FALSE_CALL] * 4  # oldest first
    for n, review in enumerate(reviews):
        rec = {"board_model": "B", "view": "Top", "result": "NG", "operator": "kim"}
        iid = ctx.db.add_inspection(rec, [])
        when = (start + timedelta(minutes=n)).isoformat(timespec="seconds")
        ctx.db.set_review(iid, review, "Dust on the board" if review == FALSE_CALL else None, "kim", when)
    ids = [ctx.db.add_inspection({"board_model": "B", "view": "Top", "result": "NG"}, []) for _ in range(3)]
    ctx.review_result(ids[0], DEFECT)
    assert _drift_alarms(ctx) == []
    ctx.review_result(ids[1], FALSE_CALL, "Dust on the board")
    (alarm,) = _drift_alarms(ctx)
    assert alarm_text(alarm) == (
        "Drift on B (Top): 5 of the last 20 reviewed calls were False calls; 2.0 % of the 200 reviews before"
    )
    assert ctx.board_status("B").drifted == (drift.FALSE_CALLS,)
    ctx.review_result(ids[2], FALSE_CALL, "Glare")
    assert len(_drift_alarms(ctx)) == 1
