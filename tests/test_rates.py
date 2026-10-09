"""REQ-TST-002 and REQ-TST-007 (stage S45, part 1): every rate of a validation is n of N with an exact one-sided 95 %
Clopper-Pearson bound, missed defects and false calls first, and recall is given per defect type. Results on the
synthetic boards prove a code path; they are never quoted as accuracy."""

from __future__ import annotations

import pytest

from aoi.core import stats
from aoi.core.services import AppContext
from tests.test_req_done_in_v01 import BOARD
from tests.test_test_dataset import held_out


@pytest.mark.parametrize(
    ("x", "n", "bound", "percent"),
    [
        (0, 50, "upper", 5.8),  # 1 - 0.05 ** (1 / 50), the sketch's "95 % upper bound 5.8 %"
        (1, 50, "upper", 9.1),
        (0, 10, "upper", 25.9),
        (5, 100, "upper", 10.2),
        (2, 20, "upper", 28.3),
        (1, 1, "lower", 5.0),  # the sketch's recall "100 %, lower 5 %"
        (49, 50, "lower", 90.9),
        (50, 50, "lower", 94.2),
    ],
)
def test_req_tst_002_clopper_pearson_known_values(x: int, n: int, bound: str, percent: float) -> None:
    """The bounds equal the published exact values to 0.1 percentage point."""
    value = stats.upper_bound(x, n) if bound == "upper" else stats.lower_bound(x, n)
    assert value is not None and round(100 * value, 1) == percent


def test_req_tst_002_edges() -> None:
    """Nothing to count gives no bound; x = n has an upper bound of 1 and x = 0 a lower bound of 0; a count above its
    total is refused."""
    assert stats.upper_bound(0, 0) is None and stats.lower_bound(0, 0) is None
    assert stats.upper_bound(7, 7) == 1.0 and stats.lower_bound(0, 7) == 0.0
    with pytest.raises(ValueError):
        stats.rate(3, 2)


def test_req_tst_002_rates_show_counts(trained_ctx: AppContext) -> None:
    """A validation's rates are stored with the run, each as its count, total and bound, and read counts first."""
    version, labels = held_out(trained_ctx)
    metrics, rows, _ = trained_ctx.test_dataset(version)
    rates = metrics["rates"]
    ng, ok = sum(v == "NG" for v in labels.values()), sum(v == "OK" for v in labels.values())
    assert (rates["missed_defects"]["of"], rates["false_calls"]["of"]) == (ng, ok)
    c = rates["counts"]
    assert (c["tp"], c["fn"], c["fp"], c["tn"]) == (metrics["TP"], metrics["FN"], metrics["FP"], metrics["TN"])
    assert rates["missed_defects"]["n"] == c["fn"] and rates["false_calls"]["n"] == c["fp"]
    for key in ("missed_defects", "false_calls", "recall", "precision", "accuracy"):
        assert stats.text(rates[key]).startswith(f"{rates[key]['n']} of {rates[key]['of']}")
    assert stats.text(stats.rate(0, 50)) == "0 of 50, 95 % upper bound 5.8 %"
    run = trained_ctx.db.latest_test_run(BOARD)
    assert run is not None and run["metrics"]["rates"] == rates


def test_req_tst_007_recall_per_type(trained_ctx: AppContext) -> None:
    """Recall per defect type counts each NG image of the locked validation set under the type it was frozen with:
    found of all, with its lower bound."""
    version, _ = held_out(trained_ctx)
    metrics, rows, _ = trained_ctx.test_dataset(version)
    expected: dict[str, list[int]] = {}
    for r in rows:
        if r["gt"] == "NG":
            e = expected.setdefault(r["defect_type"], [0, 0])
            e[0] += r["ai_result"] in ("NG", "WARN")
            e[1] += 1
    per_type = metrics["rates"]["recall_per_type"]
    assert {t: [v["n"], v["of"]] for t, v in per_type.items()} == expected and expected
    assert all(v["bound"] == "lower" for v in per_type.values())
