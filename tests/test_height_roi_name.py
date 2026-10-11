"""REQ-RCP-002: a Height ROI's region is named Anomaly until the Stage 2 3D camera measures height (Jay, 2026-10-11).
A 2D comparison finds a difference there, not a pin height, so it no longer records Pin Height Error, a defect it cannot
measure. Both names are Major, so the verdict is the same as before; Pin Height Error stays in the defect table for
labellers and for Stage 2. The board is drawn: it shows the rule, never how often it holds."""

from __future__ import annotations

from aoi import defects
from aoi.core.inspector import Inspector
from aoi.core.recipe import ROI, ROI_DEFECT, Recipe
from tests.test_copper_types import board, cut, golden


def test_req_rcp_002_a_height_roi_names_its_2d_find_anomaly_and_keeps_the_verdict() -> None:
    """The same cut trace under a Height ROI is an Anomaly, Major, as it is under an Anomaly ROI and outside every
    ROI, with the same verdict and checks; a Presence ROI still names it Missing Component."""
    results = {}
    for kind in ("Height", "Anomaly", "Presence", None):
        recipe = Recipe(board_model="BARE", use_ai=False, min_defect_area=20)
        recipe.rois = [ROI("U1", kind, 130, 140, 40, 40)] if kind else []
        results[kind] = Inspector(recipe, reference=golden()).inspect(board(cut))
    named = {kind: [(d.type, d.severity) for d in r.defects] for kind, r in results.items()}
    assert named == {
        "Height": [("Anomaly", "Major")],
        "Anomaly": [("Anomaly", "Major")],
        "Presence": [("Missing Component", "Critical")],
        None: [("Anomaly", "Major")],
    }
    assert results["Height"].verdict == results[None].verdict == "NG"
    checks = {kind: [(c.name, c.verdict) for c in results[kind].checks] for kind in ("Height", None)}
    assert checks["Height"] == checks[None]
    assert ROI_DEFECT["Height"] == "Anomaly"
    assert defects.BY_NAME["Pin Height Error"].severity == defects.ANOMALY.severity == "Major"  # the verdict holds
    assert "Pin Height Error" in defects.REQUIRES_3D_OR_SIDE  # a labeller's type for Stage 2, still in the table
