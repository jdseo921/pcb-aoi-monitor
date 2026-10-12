"""Drift on the line (REQ-INSP-019; Engineering standard, "Watch and retrain"): for each board model and view, the
newest boards judged are compared with the boards judged before them by the same AI model and recipe revision, and a
measure that has moved further than chance explains raises one alarm, when it crosses. No Qt: the service reads the
rows and stores the alarm.

The measures are the ones the standard names, each in the direction that costs the line:

- NG rate and WARN rate: the share of boards called NG, or WARN, rising (an attribute control chart: the newest
  `WINDOW` boards against the `BASELINE` before them);
- OK score: the mean AI anomaly score of the boards judged OK rising, so the AI model sees good boards as less normal
  (lighting, camera, a new board revision or parts supplier) before they start to be called NG;
- alignment: the mean number of matched features of the boards judged OK, by which each board is aligned to the Golden
  board, falling;
- false calls: the share of the reviewed calls reviewed as a False call rising (REQ-INSP-013), checked on each review
  over the newest `REVIEW_WINDOW` reviews against the `REVIEW_BASELINE` before them.

A rate has moved when seeing as many calls in the window is less likely than `ALPHA` (one-sided, as a 3-sigma control
limit) at the baseline's rate, counted exactly from the binomial distribution; the baseline's rate is (x + 1) / (n + 2),
so a baseline with no call at all still allows the odd one. A mean has moved when it lies more than three standard
errors past the baseline's mean. A measure is judged only on a baseline of at least `MIN_BASELINE` boards (or
`MIN_REVIEW_BASELINE` reviews) and, for a mean, `MIN_OK` OK boards in the window and in the baseline; a new AI model or
recipe revision starts a new baseline, as it changes what the line should call.

These are signals for an Engineer to look at the line, never a verdict and never an accuracy.
"""

from __future__ import annotations

import math
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any

from .stats import at_least

WINDOW = 50  # the newest boards judged
BASELINE = 500  # the boards judged before them
MIN_BASELINE = 200
MIN_OK = 20  # OK boards in the window, and in the baseline, for an OK board's mean
REVIEW_WINDOW = 20  # the newest reviews
REVIEW_BASELINE = 200
MIN_REVIEW_BASELINE = 50
ALPHA = 0.00135  # the one-sided chance beyond a 3-sigma control limit
SIGMAS = 3.0

SCAN = 4 * (WINDOW + BASELINE)  # the newest records of a board model read, every view's: room for up to four views
REVIEW_SCAN = 4 * (REVIEW_WINDOW + REVIEW_BASELINE)

NG_RATE, WARN_RATE, OK_SCORE, ALIGNMENT, FALSE_CALLS = "ng_rate", "warn_rate", "ok_score", "alignment", "false_calls"
BOARD_MEASURES = (NG_RATE, WARN_RATE, OK_SCORE, ALIGNMENT)


@dataclass(frozen=True)
class Drift:
    """A measure that has moved: its value in the window and in the baseline (a share from 0 to 1, or a mean), the
    count it is of (`count` of `of` for a rate; the boards it is the mean of for a mean), and the baseline's size."""

    measure: str
    recent: float
    before: float
    count: int
    of: int
    baseline: int


def same_engine(rows: Sequence[dict[str, Any]], view: str | None) -> list[dict[str, Any]]:
    """The rows of `view`, newest first, judged by the AI model and recipe revision (`model_uuid`, `recipe_uuid`) that
    judged the newest of them: a new AI model or recipe revision starts a new baseline."""
    mine = [r for r in rows if r["view"] == view]
    engine = (mine[0]["model_uuid"], mine[0]["recipe_uuid"]) if mine else None
    return [r for r in mine if (r["model_uuid"], r["recipe_uuid"]) == engine]


def rate_moved(recent: Sequence[bool], before: Sequence[bool]) -> bool:
    """True when as many of `recent` are true, at the rate of `before`, is less likely than ALPHA."""
    x = sum(recent)
    return x > 0 and at_least(x, len(recent), (sum(before) + 1) / (len(before) + 2)) < ALPHA


def mean_moved(recent: Sequence[float], before: Sequence[float], rising: bool) -> bool:
    """True when the mean of `recent` lies more than SIGMAS standard errors above (`rising`) or below the mean of
    `before`, the standard error taken from `before`'s spread."""
    m_b = sum(before) / len(before)
    sd = math.sqrt(sum((v - m_b) ** 2 for v in before) / (len(before) - 1))
    limit = SIGMAS * sd / math.sqrt(len(recent))
    m_r = sum(recent) / len(recent)
    return m_r > m_b + limit if rising else m_r < m_b - limit


def _rate(measure: str, rows: Sequence[dict[str, Any]], called: Callable[[dict[str, Any]], bool]) -> Drift | None:
    recent, before = [called(r) for r in rows[:WINDOW]], [called(r) for r in rows[WINDOW : WINDOW + BASELINE]]
    if len(recent) < WINDOW or len(before) < MIN_BASELINE or not rate_moved(recent, before):
        return None
    return Drift(measure, sum(recent) / len(recent), sum(before) / len(before), sum(recent), len(recent), len(before))


def _mean(measure: str, rows: Sequence[dict[str, Any]], key: str, rising: bool) -> Drift | None:
    """The mean of `key` over the OK boards of the window against the baseline's; rows without a number are skipped."""

    def values(part: Sequence[dict[str, Any]]) -> list[float]:
        return [float(r[key]) for r in part if r["result"] == "OK" and isinstance(r.get(key), int | float)]

    recent, before = values(rows[:WINDOW]), values(rows[WINDOW : WINDOW + BASELINE])
    if len(rows) < WINDOW + MIN_BASELINE or len(recent) < MIN_OK or len(before) < MIN_OK:
        return None
    if not mean_moved(recent, before, rising):
        return None
    return Drift(measure, sum(recent) / len(recent), sum(before) / len(before), len(recent), len(recent), len(before))


def board_drift(rows: Sequence[dict[str, Any]]) -> list[Drift]:
    """The measures that have moved over `rows`, one board model's boards of one view judged by one AI model and
    recipe revision, newest first, each with `result`, `score` and `alignment_inliers`."""
    found = (
        _rate(NG_RATE, rows, lambda r: r["result"] == "NG"),
        _rate(WARN_RATE, rows, lambda r: r["result"] == "WARN"),
        _mean(OK_SCORE, rows, "score", rising=True),
        _mean(ALIGNMENT, rows, "alignment_inliers", rising=False),
    )
    return [d for d in found if d is not None]


def review_drift(reviews: Sequence[bool]) -> Drift | None:
    """False calls moved: `reviews` are one board model's reviewed calls of one view, newest first, true for a False
    call."""
    recent, before = reviews[:REVIEW_WINDOW], reviews[REVIEW_WINDOW : REVIEW_WINDOW + REVIEW_BASELINE]
    if len(recent) < REVIEW_WINDOW or len(before) < MIN_REVIEW_BASELINE or not rate_moved(recent, before):
        return None
    return Drift(FALSE_CALLS, sum(recent) / len(recent), sum(before) / len(before), sum(recent), len(recent),
                 len(before))  # fmt: skip


def crossed(now: Sequence[Drift], earlier: Sequence[Drift]) -> list[Drift]:
    """The measures moved now that had not moved one board (or review) earlier: each alarms once as it crosses, not
    on every board while it stays out."""
    was = {d.measure for d in earlier}
    return [d for d in now if d.measure not in was]
