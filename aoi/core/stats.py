"""Rates with their counts and exact one-sided 95 % bounds (REQ-TST-002, REQ-TST-007; Customers & Launch, "Claims carry
counts"): every rate the app reports is "n of N" with a Clopper-Pearson bound, so 0 missed defects of 50 reads "95 %
upper bound 5.8 %", never "0 %" alone. No Qt and no new dependency: the bound is the binomial CDF solved by bisection.

The rates a validation reports lead with missed defects and false calls, the two a customer's line pays for; recall,
precision and accuracy follow (sketch Q45)."""

from __future__ import annotations

import math
from collections.abc import Callable, Iterable
from typing import Any

from ..errors import QT_TRANSLATE_NOOP, Phrase

CONFIDENCE = 0.95
_STEPS = 200  # bisection steps: far below a float's resolution
# A rate in words (REQ-TST-002), shown in the UI language and written in the reports
COUNT_ONLY = QT_TRANSLATE_NOOP("Rates", "{n} of {of}")
UPPER = QT_TRANSLATE_NOOP("Rates", "{n} of {of}, 95 % upper bound {limit} %")
LOWER = QT_TRANSLATE_NOOP("Rates", "{n} of {of}, 95 % lower bound {limit} %")


def _binom_cdf(k: int, n: int, p: float) -> float:
    """P(X <= k) for X ~ Binomial(n, p), summed in log space so that n in the thousands does not overflow."""
    if p <= 0.0:
        return 1.0
    if p >= 1.0:
        return 1.0 if k >= n else 0.0
    lp, lq = math.log(p), math.log1p(-p)
    lc = math.lgamma(n + 1)
    return min(1.0, sum(math.exp(lc - math.lgamma(i + 1) - math.lgamma(n - i + 1) + i * lp + (n - i) * lq)
                        for i in range(k + 1)))  # fmt: skip


def _solve(f: Callable[[float], float], target: float) -> float:
    """The p in [0, 1] where the decreasing function f(p) crosses `target`."""
    lo, hi = 0.0, 1.0
    for _ in range(_STEPS):
        mid = (lo + hi) / 2
        if f(mid) > target:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2


def upper_bound(x: int, n: int, confidence: float = CONFIDENCE) -> float | None:
    """The exact one-sided upper bound of a rate of x in n (Clopper-Pearson): the p at which seeing x or fewer has
    probability 1 - confidence. None for n = 0; 1 when x = n."""
    _check(x, n)
    if n == 0:
        return None
    if x >= n:
        return 1.0
    return _solve(lambda p: _binom_cdf(x, n, p), 1 - confidence)


def lower_bound(x: int, n: int, confidence: float = CONFIDENCE) -> float | None:
    """The exact one-sided lower bound of a rate of x in n: the p at which seeing x or more has probability
    1 - confidence. None for n = 0; 0 when x = 0."""
    _check(x, n)
    if n == 0:
        return None
    if x == 0:
        return 0.0
    return _solve(lambda p: _binom_cdf(x - 1, n, p), confidence)


def _check(x: int, n: int) -> None:
    if not (0 <= x <= n):
        raise ValueError(f"a count of {x} in {n} is not a rate")


def rate(x: int, n: int, bound: str = "upper") -> dict[str, Any]:
    """A rate as the app stores and shows it: its count, its total, the rate and its one-sided 95 % bound ("upper" for
    a rate that should be low, such as missed defects; "lower" for one that should be high, such as recall)."""
    value = x / n if n else None
    limit = upper_bound(x, n) if bound == "upper" else lower_bound(x, n)
    return {"n": x, "of": n, "rate": value, "bound": bound, "limit": limit}


def text(r: dict[str, Any]) -> Phrase:
    """A rate in words, counts first, as a phrase a screen shows in the UI language: "0 of 50, 95 % upper bound 5.8 %";
    "0 of 0" when there is nothing to count."""
    if not r["of"]:
        return COUNT_ONLY.fill(n=r["n"], of=r["of"])
    phrase = UPPER if r["bound"] == "upper" else LOWER
    return phrase.fill(n=r["n"], of=r["of"], limit=round(100 * r["limit"], 1))


def validation_rates(rows: Iterable[dict[str, Any]]) -> dict[str, Any]:
    """The rates of a run's labelled rows (gt OK or NG; WARN counts as NG): missed defects (NG boards called OK, of the
    NG boards), false calls (OK boards called NG, of the OK boards), recall, precision and accuracy, each with its
    count and bound, and recall per defect type for rows that carry one (REQ-TST-007)."""
    labelled = [r for r in rows if r.get("gt") in ("OK", "NG")]
    called_ng = [r for r in labelled if r["ai_result"] in ("NG", "WARN")]
    ng = [r for r in labelled if r["gt"] == "NG"]
    ok = [r for r in labelled if r["gt"] == "OK"]
    tp = sum(r["gt"] == "NG" for r in called_ng)
    fp = len(called_ng) - tp
    fn = len(ng) - tp
    tn = len(ok) - fp
    per_type: dict[str, list[int]] = {}
    for r in ng:
        if r.get("defect_type"):
            found = per_type.setdefault(str(r["defect_type"]), [0, 0])
            found[0] += r["ai_result"] in ("NG", "WARN")
            found[1] += 1
    return {
        "missed_defects": rate(fn, len(ng)),
        "false_calls": rate(fp, len(ok)),
        "recall": rate(tp, len(ng), "lower"),
        "precision": rate(tp, tp + fp, "lower"),
        "accuracy": rate(tp + tn, len(labelled), "lower"),
        "recall_per_type": {t: rate(f, n, "lower") for t, (f, n) in sorted(per_type.items())},
        "counts": {"tp": tp, "fn": fn, "fp": fp, "tn": tn, "labelled": len(labelled)},
    }
