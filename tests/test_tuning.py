"""The golden board comparison's thresholds trained from labelled boards (REQ-TRN-018, aoi/core/tuning.py): what is
counted at each pair, that the counts match the comparison's own regions, and which pair is chosen."""

from __future__ import annotations

import numpy as np
import pytest

from aoi.core import tuning
from aoi.core.compare import changed_regions
from aoi.core.recipe import Recipe

RECIPE = Recipe(board_model="T", use_ai=False)
DEFECT = (100, 100, 20, 20)  # x, y, w, h of the boxed defect


def _diff(faint: int = 30, noise: int = 20) -> np.ndarray:
    """A 1024 x 1024 difference map: a faint defect at DEFECT, and a small speck of noise far from it."""
    d = np.zeros((1024, 1024), np.float32)
    x, y, w, h = DEFECT
    d[y : y + h, x : x + w] = faint
    d[800:803, 800:803] = noise  # 9 px of area, in a window that touches no box
    return d


def test_req_trn_018_counts_each_defect_found_and_each_false_window() -> None:
    table = tuning.measure(_diff(), [DEFECT], True, RECIPE, thresholds=(15, 25, 45), areas=(5, 40))
    assert set(table) == {(t, a) for t in (15, 25, 45) for a in (5, 40)}
    low = table[15, 5]  # finds the defect and the speck
    assert (low.defects, low.found, low.false_windows, low.windows) == (1, 1, 1, 3)  # 4 windows, 1 touches the box
    assert table[25, 5].false_windows == 0 and table[25, 5].found == 1  # over the speck, under the defect
    assert table[45, 5].found == 0 and table[45, 5].ng_called_ng == 0  # the default misses the faint defect
    assert table[15, 40].false_windows == 0  # the speck is under 40 px of area
    assert low.ng_boards == 1 and low.ng_called_ng == 1 and low.ok_boards == 0


def test_req_trn_018_counts_agree_with_the_comparisons_regions() -> None:
    """A pair's regions are the ones `changed_regions` finds on the same map, so a chosen pair judges as counted."""
    diff = _diff()
    for thr, area in ((15, 5), (25, 5), (15, 40)):
        _, regions, _ = changed_regions(diff, thr, area)
        counts = tuning.measure(diff, [DEFECT], True, RECIPE, thresholds=(thr,), areas=(area,))[thr, area]
        assert counts.found + counts.false_windows == len(regions)


def test_req_trn_018_an_ok_board_called_ng_is_a_false_call() -> None:
    table = tuning.measure(_diff(faint=0), [], False, RECIPE, thresholds=(15, 25), areas=(5,))
    assert table[15, 5].ok_called_ng == 1 and table[15, 5].false_calls == 2  # the board and its window
    assert table[25, 5].ok_called_ng == 0 and table[25, 5].ok_boards == 1 and table[25, 5].windows == 4


def test_req_trn_018_chooses_fewest_false_calls_that_miss_at_most_max_miss() -> None:
    boards = [tuning.measure(_diff(), [DEFECT], True, RECIPE, thresholds=(15, 25, 45), areas=(5, 40))] * 3
    table = tuning.total(boards)
    assert table[15, 5].defects == 3 and table[15, 5].false_windows == 3
    assert tuning.choose(table) == (25, 40)  # every defect, no false call, the higher of the pairs that do it
    only_default = {k: v for k, v in table.items() if k[0] == 45}
    assert tuning.choose(only_default) == (45, 40)  # none finds the defect: fewest missed, then most like the default
    with pytest.raises(ValueError):
        tuning.choose({})


def test_req_trn_018_a_miss_costs_more_than_a_false_call() -> None:
    c = tuning.Counts
    table = {
        (20, 5): c(defects=100, found=100, windows=10, false_windows=5),
        (30, 5): c(defects=100, found=97, windows=10),
    }
    assert tuning.choose(table) == (20, 5)  # 3 % missed is over MAX_MISS, so the pair with false calls is chosen
    assert tuning.choose(table, max_miss=0.05) == (30, 5)


def test_req_trn_018_rates() -> None:
    c = tuning.Counts(defects=10, found=9, windows=90, false_windows=1)
    assert c.missed == 1 and c.recall == 0.9 and c.false_call_rate == pytest.approx(1 / 90)
    assert c.accuracy == pytest.approx(98 / 100) and c.precision == pytest.approx(0.9)
    assert tuning.Counts().accuracy == 0.0 and tuning.Counts().precision == 0.0
