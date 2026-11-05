"""Stage 1 industry scenarios on public data (#459, phase 2 of #452), for an internal test record, never an accuracy
claim.

    python tools/proxy_scenarios.py --scenario S1 --config shipped|commissioned --data <VisA root> --out <folder>

Each scenario of the record runs a station of a VisA board model in two configurations: as shipped (the defaults)
and as commissioned, set up on day one with the app's own features (tools/proxy_station.py). The scenario drivers are
in tools/proxy_scenario_runs.py. This module holds what they share and what is tested without a dataset:
- the shift a line sees in arrival order;
- the industry's counts (escapes in ppm, false calls per shift, first-pass yield, re-checks per hour);
- the queue a line forms and the spread of its times;
- the share of boards whose verdict flips, and the AI cut that best separates the calibration scores.
The ways a photo is changed (drift, placement, a re-shot board, bad images, variation, a revision) are in
tools/proxy_frames.py.

Jay approved on 2026-11-04 the use of the public datasets named in the test record for internal Stage 1 testing only:
no image, box, mask or trained model from them enters the repository or ships.
"""

from __future__ import annotations

import argparse
import json
import random
import sys
from collections import Counter
from pathlib import Path
from typing import Any

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:  # run as a script: the repository root holds the ``aoi`` and ``tools`` packages
    sys.path.insert(0, str(ROOT))

from tools.dataset_check import upper_95  # noqa: E402

NOT_ACCURACY = "Counts from an internal Stage 1 test on public data (#459); never an accuracy claim."
CONFIGS = ("shipped", "commissioned")
SCENARIOS = tuple(f"S{i}" for i in range(1, 12))
SHIFT_BOARDS = 2000
BOARD_EVERY_S = 10.0  # one board every 10 s, as Jay set the line rate
FLAGGED = ("WARN", "NG")  # what an operator re-checks


# --- S1: a shift in arrival order, and the line's counts ------------------------------------------------------------
def shift(n_good: int, n_defective: int, boards: int, rate: float, seed: int) -> list[dict[str, Any]]:
    """`boards` arrivals, round(boards * rate) of them defective, drawn from `n_defective` held-out defective boards
    and the rest from `n_good` good ones. Each pool is used up in a seeded order before any board comes again; `reuse`
    counts the earlier arrivals of the same image (0 for its first)."""
    k = round(boards * rate)
    if (k and n_defective < 1) or (boards > k and n_good < 1):
        raise ValueError("a shift needs a board in each pool it draws from")
    rng = random.Random(seed)

    def drawn(pool: int, count: int) -> list[int]:
        out: list[int] = []
        while len(out) < count:
            order = list(range(pool))
            rng.shuffle(order)
            out += order
        return out[:count]

    arrivals = [("NG", i) for i in drawn(n_defective, k)] + [("OK", i) for i in drawn(n_good, boards - k)]
    rng.shuffle(arrivals)
    seen: Counter[tuple[str, int]] = Counter()
    rows = []
    for label, i in arrivals:
        rows.append({"label": label, "index": i, "reuse": seen[(label, i)]})
        seen[(label, i)] += 1
    return rows


def line_counts(rows: list[dict[str, Any]], every_s: float = BOARD_EVERY_S) -> dict[str, Any]:
    """A shift's rows (label, verdict, found) in the industry's terms: escapes (a defective board judged OK, or flagged
    with no defect box on its defect) in parts per million of boards with the one-sided 95 % upper bound, false calls
    (a good board flagged), first-pass yield (boards judged OK), and the boards an operator re-checks per hour, a board
    refused (no verdict) among them: it never passes, so it is no escape, and it is counted on its own.

    The bounds per arrival hold for arrivals that are independent boards. When the same board comes again (S1 and S2
    draw a shift from a few hundred boards), rows that name their `board` also get the counts per distinct board with
    their bounds, which are the ones to quote: a distinct board escapes, or is called falsely, when any of its
    arrivals is."""
    n = len(rows)
    bad = [r for r in rows if r["label"] == "NG"]
    escapes = sum(r["verdict"] == "OK" or (r["verdict"] is not None and not r["found"]) for r in bad)
    false_calls = sum(r["label"] == "OK" and r["verdict"] in FLAGGED for r in rows)
    refused = sum(r["verdict"] is None for r in rows)
    flagged = sum(r["verdict"] in FLAGGED for r in rows) + refused
    per_hour = 3600 / every_s
    return {
        "boards": n,
        "defective": len(bad),
        "escapes": escapes,
        "escapes_ppm": round(escapes / n * 1e6) if n else None,
        "escapes_ppm_upper_95": round(upper_95(escapes, n) * 1e6) if n else None,
        "escapes_of_defective_upper_95": upper_95(escapes, len(bad)) if bad else None,
        "false_calls": false_calls,
        "false_call_rate": round(false_calls / (n - len(bad)), 4) if n > len(bad) else None,
        "false_call_rate_upper_95": upper_95(false_calls, n - len(bad)) if n > len(bad) else None,
        "refused": refused,
        "first_pass_yield": round(sum(r["verdict"] == "OK" for r in rows) / n, 4) if n else None,
        "rechecks_per_hour": round(flagged / n * per_hour, 1) if n else None,
    } | (distinct(rows) if any("board" in r for r in rows) else {})


def distinct(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """`line_counts` per distinct board (label and board name): how many, how many escaped or were called falsely on
    any of their arrivals, and the one-sided 95 % upper bound of each share."""
    boards: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for r in rows:
        boards.setdefault((r["label"], str(r.get("board"))), []).append(r)
    bad = [v for (label, _), v in boards.items() if label == "NG"]
    good = [v for (label, _), v in boards.items() if label == "OK"]
    esc = sum(any(r["verdict"] == "OK" or (r["verdict"] is not None and not r["found"]) for r in v) for v in bad)
    fc = sum(any(r["verdict"] in FLAGGED for r in v) for v in good)
    return {
        "distinct_defective": len(bad),
        "distinct_escapes": esc,
        "distinct_escapes_upper_95": upper_95(esc, len(bad)) if bad else None,
        "distinct_good": len(good),
        "distinct_false_calls": fc,
        "distinct_false_calls_upper_95": upper_95(fc, len(good)) if good else None,
    }


def backlog(service_s: list[float], every_s: list[float]) -> dict[str, Any]:
    """The queue a line forms (S9) when board i takes `service_s[i]` and board i+1 arrives `every_s[i]` after it: each
    board's wait before it is taken (Lindley's recursion), the longest, the last, and the boards that waited."""
    if len(every_s) != max(0, len(service_s) - 1):
        raise ValueError("one gap between each two boards")
    waits, w = [0.0], 0.0
    for s, gap in zip(service_s[:-1], every_s, strict=True):
        w = max(0.0, w + s - gap)
        waits.append(w)
    return {"max_wait_s": round(max(waits), 3), "last_wait_s": round(waits[-1], 3), "waited": sum(x > 0 for x in waits)}


def spread(values: list[float]) -> dict[str, float]:
    """p50, p95 and the maximum, as a per-board time is reported (S9)."""
    v = np.asarray(values, dtype=float)
    return {
        "p50": round(float(np.percentile(v, 50)), 1),
        "p95": round(float(np.percentile(v, 95)), 1),
        "max": round(float(v.max()), 1),
        "n": int(v.size),
    }


def flips(verdicts: dict[str, list[str]]) -> int:
    """The boards, of those given with each shot's verdict, whose verdict is not the same every time (S7)."""
    return sum(len(set(v)) > 1 for v in verdicts.values())


def best_cut(ok: list[float], ng: list[float]) -> float:
    """The AI score threshold that best separates the calibration scores: the cut, midway between two neighbouring
    scores, with the most NG at or above it less good at or above it (Youden's J), the lower cut on a tie, so that
    the fewer defects pass."""
    if not ok or not ng:
        raise ValueError("a cut needs good and NG scores to separate")
    scores = sorted(set(ok) | set(ng))
    cuts = [(a + b) / 2 for a, b in zip(scores, scores[1:], strict=False)] or scores

    def j(t: float) -> float:
        return sum(s >= t for s in ng) / max(1, len(ng)) - sum(s >= t for s in ok) / max(1, len(ok))

    return max(cuts, key=lambda t: (j(t), -t))


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=(__doc__ or "").split("\n\n")[0])
    p.add_argument("--scenario", required=True, choices=SCENARIOS)
    p.add_argument("--config", required=True, choices=CONFIGS)
    p.add_argument("--data", required=True, help="VisA's root folder")
    p.add_argument("--out", required=True, help="workspaces and results, outside the repository and the data")
    p.add_argument("--seed", type=int, default=0)
    p.add_argument("--categories", default="pcb1", help="the VisA categories the scenario runs on")
    p.add_argument("--epochs", type=int, help="a quicker run than the default settings' (a smoke test only)")
    p.add_argument("--pace", type=float, default=BOARD_EVERY_S, help="S9: seconds between boards (0: back to back)")
    p.add_argument("--hours", type=float, default=4.0, help="S9: the hours of the line run before its burst")
    return p


def main(argv: list[str] | None = None) -> int:
    from tools.proxy_scenario_runs import run  # imports PySide6 and PyTorch, which the counting does not need

    args = parser().parse_args(argv)
    result = {"claim": NOT_ACCURACY, **run(args)}
    out = Path(args.out) / f"{args.scenario}-{args.config}.json"
    out.write_text(json.dumps(result, indent=1, default=str), encoding="utf-8")
    print(json.dumps({k: v for k, v in result.items() if k not in ("rows", "runs")}, indent=1, default=str)[:4000])
    return 1 if failed(result) else 0


def failed(result: object) -> bool:
    """Whether any `error` in a scenario's result holds a value: S6 records `"error": null` for a station built well."""
    if isinstance(result, dict):
        return any((k == "error" and v is not None) or failed(v) for k, v in result.items())
    return isinstance(result, list) and any(failed(v) for v in result)


if __name__ == "__main__":
    raise SystemExit(main())
