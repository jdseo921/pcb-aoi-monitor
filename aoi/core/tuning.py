"""Training the golden board comparison's two thresholds from labelled boards (REQ-TRN-018).

The comparison marks a pixel changed when its colour differs from the Golden board's by the Pixel difference or more,
and keeps a difference region of the Minimum defect area or more (`changed_regions`). Their defaults, 45 and 40 px,
are one setting for every board. `measure` counts, for one labelled board and every pair of THRESHOLDS and AREAS, what
the comparison would find on its difference map, and `choose` picks from the counts of a training set the pair with
the fewest false calls among those that miss at most `max_miss` of the boxed defects; a missed defect costs more than
a false call, so a pair is never picked for fewer false calls while it misses more than that.

The units counted: each boxed defect of an NG board, found when a difference region overlaps its box grown by MARGIN
px; and each WINDOW x WINDOW px window of a board that touches no grown box, a false call when a region that overlaps no
grown box lies in it. An OK board is all such windows, and is called NG as the recipe's region count, changed area and
SSIM decide. Boxes are in px of the difference map, the board as aligned onto the Golden board.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import astuple, dataclass

import cv2
import numpy as np

from .compare import changed_mask
from .recipe import Recipe

THRESHOLDS = (8, 10, 12, 15, 18, 20, 25, 30, 35, 40, 45, 50, 60, 70)  # Pixel difference values tried (0-255)
AREAS = (5, 10, 20, 40, 80, 160)  # Minimum defect areas tried, px of area
MARGIN = 10  # px a region may lie off a boxed defect and still find it, as tools/dataset_check.py counts
WINDOW = 512  # px: the side of the windows a board's defect-free area is counted in
MAX_MISS = 0.01  # the share of boxed defects a chosen pair may miss (proposed)

Box = tuple[int, int, int, int]  # x, y, w, h


@dataclass(frozen=True)
class Counts:
    """What one pair of thresholds found on one board or on a set of them."""

    defects: int = 0  # boxed defects on NG boards
    found: int = 0
    windows: int = 0  # windows that touch no boxed defect
    false_windows: int = 0  # of them, those a region on no box lies in
    ng_boards: int = 0
    ng_called_ng: int = 0
    ok_boards: int = 0
    ok_called_ng: int = 0

    def __add__(self, other: Counts) -> Counts:
        return Counts(*(a + b for a, b in zip(astuple(self), astuple(other), strict=True)))

    @property
    def missed(self) -> int:
        return self.defects - self.found

    @property
    def false_calls(self) -> int:
        """False windows, and OK boards called NG."""
        return self.false_windows + self.ok_called_ng

    @property
    def accuracy(self) -> float:
        """The share of units judged right: each boxed defect found and each defect-free window left clear."""
        units = self.defects + self.windows
        return (self.found + self.windows - self.false_windows) / units if units else 0.0

    @property
    def precision(self) -> float:
        called = self.found + self.false_windows
        return self.found / called if called else 0.0

    @property
    def recall(self) -> float:
        return self.found / self.defects if self.defects else 0.0

    @property
    def false_call_rate(self) -> float:
        return self.false_windows / self.windows if self.windows else 0.0


Table = dict[tuple[int, int], Counts]  # (Pixel difference, Minimum defect area) -> counts


def _overlaps(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    """For boxes a (n x 4) and b (m x 4) as x0, y0, x1, y1 (x1, y1 past the end), whether each pair overlaps (n x m)."""
    return (
        (a[:, None, 0] < b[None, :, 2])
        & (b[None, :, 0] < a[:, None, 2])
        & (a[:, None, 1] < b[None, :, 3])
        & (b[None, :, 1] < a[:, None, 3])
    )


def measure(
    diff: np.ndarray,
    boxes: Iterable[Box],
    ng: bool,
    recipe: Recipe,
    ssim: float = 1.0,
    thresholds: Iterable[int] = THRESHOLDS,
    areas: Iterable[int] = AREAS,
) -> Table:
    """The counts of one board, labelled NG (`ng`) with its defects boxed or OK, for each pair of thresholds, from its
    difference map `diff` and SSIM score; the recipe's other values (region count, changed area, SSIM floor) apply."""
    h, w = diff.shape[:2]
    grown = np.array([(x - MARGIN, y - MARGIN, x + bw + MARGIN, y + bh + MARGIN) for x, y, bw, bh in boxes], dtype=int)
    grown = grown.reshape(-1, 4)
    windows = np.array(
        [(x, y, min(x + WINDOW, w), min(y + WINDOW, h)) for y in range(0, h, WINDOW) for x in range(0, w, WINDOW)]
    )
    clear = windows[~_overlaps(windows, grown).any(axis=1)]
    table: Table = {}
    for thr in thresholds:
        mask = changed_mask(diff, thr)
        changed_pct = cv2.countNonZero(mask) / mask.size * 100.0
        _, _, stats, _ = cv2.connectedComponentsWithStats(mask, connectivity=8)
        for area in areas:
            kept = stats[1:][stats[1:, cv2.CC_STAT_AREA] >= area]
            regions = np.column_stack([kept[:, 0], kept[:, 1], kept[:, 0] + kept[:, 2], kept[:, 1] + kept[:, 3]])
            hits = _overlaps(grown, regions)
            false = regions[~hits.any(axis=0)]
            called = (
                len(kept) > recipe.max_diff_regions or changed_pct >= recipe.changed_pct_max or ssim < recipe.ssim_min
            )
            table[thr, area] = Counts(
                defects=len(grown) if ng else 0,
                found=int(hits.any(axis=1).sum()) if ng else 0,
                windows=len(clear),
                false_windows=int(_overlaps(clear, false).any(axis=1).sum()),
                ng_boards=int(ng),
                ng_called_ng=int(ng and called),
                ok_boards=int(not ng),
                ok_called_ng=int(not ng and called),
            )
    return table


def total(tables: Iterable[Table]) -> Table:
    """The counts of a set of boards: each pair's counts added up over the boards' tables."""
    out: Table = {}
    for table in tables:
        for key, counts in table.items():
            out[key] = out.get(key, Counts()) + counts
    return out


def choose(table: Table, max_miss: float = MAX_MISS) -> tuple[int, int]:
    """The pair with the fewest false calls among those that miss at most `max_miss` of the boxed defects (with none
    that does, among those that miss fewest), then the fewest missed, then the higher Pixel difference and Minimum
    defect area, which judge more like the defaults."""
    if not table:
        raise ValueError("no counts to choose from")
    fewest = min(c.missed for c in table.values())
    allowed = [k for k, c in table.items() if c.missed <= max(max_miss * c.defects, fewest)]
    return min(allowed, key=lambda k: (table[k].false_calls, table[k].missed, -k[0], -k[1]))
