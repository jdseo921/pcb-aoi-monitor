"""The synthetic regression set gives the verdicts and metrics recorded in expected.json (stage S05).

A failure here means the compare step's behaviour changed. If the change is intended, re-baseline with
`python tests/regression/make_regression_set.py --write-expected`, put the before/after counts in the
"Changes that can alter verdicts" section of the release note, and say so in the pull request (README.md).
"""

from __future__ import annotations

import json
from pathlib import Path

import cv2
import numpy as np
import pytest

from tests.regression import make_regression_set as rs

EXPECTED = json.loads(rs.EXPECTED_PATH.read_text(encoding="utf-8"))
BOARDS = {b["name"]: b for b in EXPECTED["boards"]}


@pytest.fixture(scope="module")
def regression_set(tmp_path_factory: pytest.TempPathFactory) -> tuple[Path, list[rs.Board], np.ndarray]:
    out = tmp_path_factory.mktemp("regression")
    boards = rs.generate(out)
    return out, boards, cv2.imread(str(out / "golden.png"))


def test_regression_set_is_the_baselined_one(regression_set: tuple[Path, list[rs.Board], np.ndarray]) -> None:
    """Same seed, same boards: names, labels, defect types and defect boxes match expected.json."""
    _, boards, golden = regression_set
    assert EXPECTED["seed"] == rs.SEED
    assert EXPECTED["recipe"] == rs.RECIPE.to_dict()
    assert EXPECTED["tolerances"] == rs.TOLERANCES
    assert golden.shape == (480, 640, 3)
    assert [b.name for b in boards] == list(BOARDS)
    for b in boards:
        exp = BOARDS[b.name]
        assert (b.label, b.defect_type) == (exp["label"], exp["defect_type"])
        assert b.defect_box == (tuple(exp["defect_box"]) if exp["defect_box"] else None)
    assert sum(b.label == "OK" for b in boards) == rs.N_OK
    assert sum(b.label == "NG" for b in boards) == rs.N_NG


@pytest.mark.parametrize("name", list(BOARDS))
def test_regression_verdicts(name: str, regression_set: tuple[Path, list[rs.Board], np.ndarray]) -> None:
    """Every board gets its expected verdict, every metric is within tolerance, and a defect is found
    where expected.json says it was (or not found, where the default recipe did not see it)."""
    out, boards, golden = regression_set
    board = next(b for b in boards if b.name == name)
    exp = BOARDS[name]
    res = rs.inspect(cv2.imread(str(out / name)), golden)

    assert res.verdict == exp["verdict"], f"{name}: verdict {res.verdict}, expected {exp['verdict']}"
    assert res.compare is not None
    got = res.compare.metrics
    assert got["alignment_method"] == exp["metrics"]["alignment_method"]
    for metric, tol in rs.TOLERANCES.items():
        assert abs(got[metric] - exp["metrics"][metric]) <= tol, (
            f"{name}: {metric} = {got[metric]:.4f}, expected {exp['metrics'][metric]} ± {tol}"
        )
    if board.defect_box is not None:
        assert rs.region_hits(res, board.defect_box) == exp["found"], f"{name}: defect box {board.defect_box}"
