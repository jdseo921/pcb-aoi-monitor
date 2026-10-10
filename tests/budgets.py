"""How a test judges a G1 performance budget (Engineering standard, performance budgets).

A budget is a pass or fail number for the app on the reference PC. Its tests time several tries, each of which pays
the first-time cost again (a new process, a new window, a new folder), as `tests/test_compare_views.py` times five
openings of a stored result: TRIES for a budget under a second (a page switch, one click), LONG_TRIES for one of
seconds (a start, a demo load or reset). Off CI, on the reference PC in the station check
(`docs/tests/station-checks.md`) as on a developer's machine, every try must be within the budget. On a shared CI
runner, which sets CI=true, the median of the tries must be: such a runner stalls now and then for another tenant, and
on 2026-10-10 its Windows test job failed a budget on code that passed the same tests in other runs (in a pull
request's run, six page switches at 390 to 530 ms of 300 and Load Demo at 10.4 s of 10; in two runs of main, with
1,087 tests passing each time, Logs & Export opened in 323 ms after 23 ms the round before, then one click in 531 ms).
A stall is not the app's cost, and a try that is slow because the app is slow is slow every time, so the median still
fails it. Every try is printed with the test's output; the budgets themselves do not change."""

from __future__ import annotations

import os
from collections.abc import Sequence
from statistics import median

TRIES, LONG_TRIES = 5, 3


def on_shared_runner() -> bool:
    """True on a CI runner: GitHub Actions sets CI=true for every job."""
    return os.environ.get("CI", "").lower() == "true"


def judged(tries: Sequence[float], shared: bool | None = None) -> float:
    """The time a budget is held against, of `tries` measured in seconds: their median on a shared runner (`shared`,
    by default on_shared_runner()), else the slowest, so that off CI every try must be within the budget."""
    if shared is None:
        shared = on_shared_runner()
    return median(tries) if shared else max(tries)
