"""The industry-scenario tool's counting (#459): a shift, the line's counts, the queue, verdict flips and the AI cut.
No dataset runs in CI; the tool's runs on public data are in docs/tests/2026-11-05-stage1-industry-scenarios.md."""

from __future__ import annotations

from collections import Counter

import pytest

from tools import proxy_scenarios as ps


def test_459_a_shift_has_its_defective_share_and_uses_each_board_before_any_again() -> None:
    rows = ps.shift(50, 30, 2000, 0.01, seed=7)
    assert len(rows) == 2000
    assert Counter(r["label"] for r in rows) == {"OK": 1980, "NG": 20}
    good = Counter(r["index"] for r in rows if r["label"] == "OK")
    assert max(good.values()) - min(good.values()) <= 1  # each pool used up before a board comes again
    assert {r["index"] for r in rows if r["label"] == "NG"} <= set(range(30))
    first = [r for r in rows if r["label"] == "OK" and r["index"] == 3]
    assert [r["reuse"] for r in first] == list(range(len(first)))
    assert ps.shift(50, 30, 2000, 0.01, seed=7) == rows  # seeded
    assert Counter(r["label"] for r in ps.shift(50, 30, 2000, 0.002, seed=7))["NG"] == 4


def test_459_line_counts_count_escapes_false_calls_and_refusals() -> None:
    def r(label: str, verdict: str | None, found: bool = True) -> dict[str, object]:
        return {"label": label, "verdict": verdict, "found": found}

    rows = [r("OK", "OK")] * 6 + [r("OK", "WARN"), r("OK", None), r("NG", "OK"), r("NG", "NG", found=False)]
    rows += [r("NG", "NG"), r("NG", None, found=False)]
    c = ps.line_counts(rows, every_s=10.0)
    assert (c["boards"], c["defective"], c["escapes"], c["false_calls"], c["refused"]) == (12, 4, 2, 1, 2)
    assert c["escapes_ppm"] == round(2 / 12 * 1e6)
    assert c["escapes_ppm_upper_95"] > c["escapes_ppm"]
    assert c["first_pass_yield"] == round(7 / 12, 4)
    assert c["rechecks_per_hour"] == round(5 / 12 * 360, 1)  # flagged and refused, at 360 boards an hour
    assert ps.line_counts([])["escapes_ppm"] is None


def test_459_backlog_follows_the_queue_and_spread_gives_the_percentiles() -> None:
    assert ps.backlog([1.0, 1.0, 1.0], [10.0, 10.0])["max_wait_s"] == 0.0
    q = ps.backlog([3.0, 3.0, 3.0, 0.5], [2.0, 2.0, 2.0])
    assert (q["max_wait_s"], q["last_wait_s"], q["waited"]) == (3.0, 3.0, 3)
    s = ps.spread([float(v) for v in range(1, 101)])
    assert (s["p50"], s["max"], s["n"]) == (50.5, 100.0, 100)
    assert 95.0 <= s["p95"] <= 96.0


def test_459_flips_counts_boards_whose_shots_disagree_not_shots() -> None:
    assert ps.flips({"x": ["OK"] * 10, "y": ["OK"] * 9 + ["WARN"], "z": ["NG", "WARN"]}) == 2


def test_459_best_cut_separates_the_scores_and_takes_the_lower_cut_on_a_tie() -> None:
    assert ps.best_cut([1.0, 2.0, 3.0], [5.0, 6.0]) == 4.0
    cut = ps.best_cut([1.0, 2.0, 4.0], [3.0, 5.0, 6.0])
    assert cut == 2.5  # J of 2.5 and 4.5 tie at 2/3: the lower lets fewer defects pass
    assert ps.best_cut([2.0], [2.0]) == 2.0


def test_459_a_shift_refuses_an_empty_pool_it_must_draw_from() -> None:
    with pytest.raises(ValueError):
        ps.shift(50, 0, 100, 0.01, seed=1)
    with pytest.raises(ValueError):
        ps.shift(0, 30, 100, 0.01, seed=1)
    assert len(ps.shift(50, 0, 100, 0.0, seed=1)) == 100  # no defective board drawn: none needed


def test_459_repeated_boards_are_bounded_per_distinct_board() -> None:
    def r(board: str, label: str, verdict: str) -> dict[str, object]:
        return {"board": board, "label": label, "verdict": verdict, "found": True}

    rows = [r("g1", "OK", "OK"), r("g1", "OK", "WARN"), r("g2", "OK", "OK"), r("d1", "NG", "OK"), r("d1", "NG", "NG")]
    c = ps.line_counts(rows)
    assert (c["false_calls"], c["escapes"]) == (1, 1)  # per arrival
    assert (c["distinct_good"], c["distinct_false_calls"], c["distinct_defective"], c["distinct_escapes"]) == (
        2,
        1,
        1,
        1,
    )
    assert c["distinct_escapes_upper_95"] == 1.0 and c["false_call_rate_upper_95"] < c["distinct_false_calls_upper_95"]
    assert "distinct_good" not in ps.line_counts([{"label": "OK", "verdict": "OK", "found": True}])


def test_459_guards_and_the_exit_code_read_only_errors_that_hold_a_value() -> None:
    with pytest.raises(ValueError):
        ps.backlog([1.0, 1.0, 1.0], [10.0])
    with pytest.raises(ValueError):
        ps.best_cut([], [1.0])
    assert not ps.failed({"ng0": {"error": None, "line": [1, {"error": None}]}})
    assert ps.failed({"ng3": {"error": None}, "ng10": [{"error": {"code": "AOI-RCP-013"}}]})
    args = ps.parser().parse_args(["--scenario", "S9", "--config", "commissioned", "--data", "d", "--out", "o"])
    assert (args.pace, args.hours, args.seed, args.categories, args.epochs) == (10.0, 4.0, 0, "pcb1", None)
