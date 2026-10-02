"""The heat views of a result on Compare (REQ-CMP-002): the board under its difference map or its AI score map, each
coloured up to the value it shows in full colour. No Qt here; the page keeps what it drew while the result is shown."""

from __future__ import annotations

import numpy as np

from .imaging import heat_overlay
from .inspector import InspectionResult


def difference_view(res: InspectionResult, pixel_difference: int) -> np.ndarray | None:
    """The board under its difference map, in full colour at 1.5 × the recipe's pixel difference (at least 1); None
    without a picture or a difference map."""
    if res.image is None or res.compare is None or res.compare.diff_map is None:
        return None
    return heat_overlay(res.image, res.compare.diff_map, max(1.0, 1.5 * pixel_difference))


def ai_view(res: InspectionResult) -> np.ndarray | None:
    """The board under its AI score map, in full colour at 1.5 × the AI threshold it was judged with (1.5 × the map's
    highest value without one); None without a picture or an AI score map."""
    if res.image is None or res.anomaly_map is None:
        return None
    thr = next((c.threshold for c in res.checks if c.source == "AI"), None)
    return heat_overlay(res.image, res.anomaly_map, (thr or float(np.max(res.anomaly_map))) * 1.5)
