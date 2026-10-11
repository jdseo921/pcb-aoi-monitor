"""Naming a bare-board copper defect from the Golden board comparison (REQ-INSP-018, ADR 0015).

A region the comparison or the AI model found is compared again as copper and substrate, in a window around it on the
Golden board and on the board aligned to it. Copper is the lighter or the darker class of the Golden board's window, as
the recipe's `copper` says (taking the smaller class of the board as copper was right on only 693 of DeepPCB's 1,000
boards), and the board is cut at the same level. What changed and how the copper's shape changed name the
defect, as bare-board AOI does by rule:

- copper missing that splits a conductor in two: Open Circuit; that opens a hole in copper: Pin-hole / Missing Hole;
  otherwise a notch in a conductor's edge: Mousebite;
- copper added that joins two conductors: Short Circuit; that fills a hole: Pin-hole / Missing Hole; that stands
  alone: Spurious Copper; otherwise a projection from a conductor: Spur.

A window with no clear copper and substrate (too little contrast, or one class all but empty) names nothing, and the
region stays an Anomaly. No Qt here: the engine imports this module.
"""

from __future__ import annotations

import cv2
import numpy as np

OPEN, SHORT, MOUSEBITE, SPUR, SPURIOUS, HOLE = (
    "Open Circuit",
    "Short Circuit",
    "Mousebite",
    "Spur",
    "Spurious Copper",
    "Pin-hole / Missing Hole",
)
TYPES = (OPEN, SHORT, MOUSEBITE, SPUR, SPURIOUS, HOLE)
MARGIN = 0.75  # the window around a region, as a share of its larger side on each side, so whole conductors show
MIN_MARGIN = 12  # px: the least margin, so a small region still shows the copper around it
MIN_CONTRAST = 40  # grey levels between the copper and substrate means of the Golden board's window
MIN_SHARE = 0.03  # each class covers at least this share of the window
MIN_CHANGE = 4  # px changed, after the cut, for the change to be read at all


def _gray(img: np.ndarray) -> np.ndarray:
    return img if img.ndim == 2 else cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)


def _window(shape: tuple[int, ...], x: int, y: int, w: int, h: int) -> tuple[int, int, int, int]:
    m = max(MIN_MARGIN, int(MARGIN * max(w, h)))
    return max(0, x - m), max(0, y - m), min(shape[1], x + w + m), min(shape[0], y + h + m)


def _parts(mask: np.ndarray, least: int = MIN_CHANGE) -> int:
    """Connected copper parts (8-connected) of at least `least` px."""
    n, _, stats, _ = cv2.connectedComponentsWithStats(mask, connectivity=8)
    return int(np.sum(stats[1:, cv2.CC_STAT_AREA] >= least))


def _holes(mask: np.ndarray) -> int:
    """Substrate parts (4-connected) inside copper, touching no edge of the window, of at least MIN_CHANGE px."""
    n, labels, stats, _ = cv2.connectedComponentsWithStats(cv2.bitwise_not(mask), connectivity=4)
    edge = set(np.unique(np.concatenate([labels[0], labels[-1], labels[:, 0], labels[:, -1]])).tolist())
    return sum(1 for i in range(1, n) if i not in edge and stats[i, cv2.CC_STAT_AREA] >= MIN_CHANGE)


def copper_type(
    board: np.ndarray,
    golden: np.ndarray,
    x: int,
    y: int,
    w: int,
    h: int,
    light: bool = True,
    level: float | None = None,
) -> str | None:
    """The copper defect a region at (x, y, w, h) shows, `board` aligned to `golden` (same size, BGR or grey), copper
    the lighter class when `light`, else the darker. The window is cut at its own Otsu level where it shows clear copper
    and substrate, else at `level`, the whole Golden board's (`copper_level`). None when the window has neither or no
    copper changed there."""
    x0, y0, x1, y1 = _window(golden.shape, x, y, w, h)
    ref, test = _gray(golden)[y0:y1, x0:x1], _gray(board)[y0:y1, x0:x1]
    if ref.size == 0:
        return None
    if not light:
        ref, test = cv2.bitwise_not(ref), cv2.bitwise_not(test)
        level = None if level is None else 254 - level  # copper at or below the level is above it inverted
    own, ref_cu = cv2.threshold(ref, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    share = np.count_nonzero(ref_cu) / ref_cu.size
    clear = (
        MIN_SHARE <= share <= 1 - MIN_SHARE
        and float(ref[ref_cu > 0].mean()) - float(ref[ref_cu == 0].mean()) >= MIN_CONTRAST
    )
    if clear or level is None:  # the window's own level where it shows both classes, else the board's
        level = own
    _, ref_cu = cv2.threshold(ref, level, 255, cv2.THRESH_BINARY)
    _, test_cu = cv2.threshold(test, level, 255, cv2.THRESH_BINARY)
    kernel = np.ones((3, 3), np.uint8)  # a pixel of misregistration along an edge is no change
    ref_cu, test_cu = (
        cv2.morphologyEx(ref_cu, cv2.MORPH_OPEN, kernel),
        cv2.morphologyEx(test_cu, cv2.MORPH_OPEN, kernel),
    )
    missing = cv2.morphologyEx(cv2.bitwise_and(ref_cu, cv2.bitwise_not(test_cu)), cv2.MORPH_OPEN, kernel)
    extra = cv2.morphologyEx(cv2.bitwise_and(test_cu, cv2.bitwise_not(ref_cu)), cv2.MORPH_OPEN, kernel)
    lost, added = int(np.count_nonzero(missing)), int(np.count_nonzero(extra))
    if max(lost, added) < MIN_CHANGE:
        return None
    if lost >= added:
        least = max(MIN_CHANGE, lost)  # a split-off piece smaller than the copper lost is a sliver the window cut
        if _parts(test_cu, least) > _parts(ref_cu, least):
            return OPEN
        return HOLE if _holes(test_cu) > _holes(ref_cu) else MOUSEBITE
    if _parts(test_cu) < _parts(ref_cu):
        return SHORT
    if _holes(test_cu) < _holes(ref_cu):
        return HOLE
    return SPURIOUS if _parts(test_cu) > _parts(ref_cu) else SPUR


def copper_level(golden: np.ndarray) -> float | None:
    """The grey level between copper and substrate on the whole Golden board (Otsu), or None when the two classes are
    less than MIN_CONTRAST apart or one covers under MIN_SHARE of the board: then no region is named."""
    g = _gray(golden)
    level, cu = cv2.threshold(g, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    share = np.count_nonzero(cu) / cu.size
    if not MIN_SHARE <= share <= 1 - MIN_SHARE or float(g[cu > 0].mean()) - float(g[cu == 0].mean()) < MIN_CONTRAST:
        return None
    return float(level)
