"""The rule the G1 performance budget tests judge a budget by (tests/budgets.py): on a shared CI runner the median of
repeated tries, so a one-off stall does not fail a build while a page that is slow every time still does; anywhere
else, the reference PC's station check among them, every try."""

from __future__ import annotations

import pytest

from tests.budgets import LONG_TRIES, TRIES, judged, on_shared_runner


def test_budget_rule_on_a_shared_runner_passes_a_stall_and_fails_a_slow_page() -> None:
    assert judged([0.023, 0.323, 0.020, 0.021, 0.022], shared=True) < 0.3  # one try stalled
    assert judged([0.390, 0.530, 0.021, 0.020, 0.410], shared=True) >= 0.3  # slow in three tries of five
    assert judged([0.320, 0.310, 0.330, 0.300, 0.320], shared=True) >= 0.3  # slow every time
    assert judged([10.4, 0.8, 0.9], shared=True) < 10 and judged([10.4, 10.2, 0.9], shared=True) >= 10
    assert judged([0.5, 0.1, 0.3], shared=True) == 0.3 and judged([0.1, 0.5], shared=True) == 0.3


def test_budget_rule_elsewhere_holds_every_try() -> None:
    assert judged([0.023, 0.323, 0.020, 0.021, 0.022], shared=False) >= 0.3  # the one stalled try fails it
    assert judged([0.023, 0.299, 0.020], shared=False) < 0.3
    assert judged([3.3, 5.1, 3.3], shared=False) > 5


def test_budget_rule_reads_ci_from_the_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CI", "true")
    assert on_shared_runner() and judged([0.1, 0.9, 0.1]) == 0.1
    monkeypatch.delenv("CI")
    assert not on_shared_runner() and judged([0.1, 0.9, 0.1]) == 0.9
    assert (TRIES, LONG_TRIES) == (5, 3)
