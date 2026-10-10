"""The 10 mandatory AOI checks of the defect classification table (section 4) and how a recipe covers each
(REQ-RCP-005, recipe-editor sketch's AOI checks tab). No Qt: the Recipe Editor words the marks."""

from __future__ import annotations

from dataclasses import dataclass

from ..defects import MANDATORY_AOI_SET, REQUIRES_3D_OR_SIDE
from .recipe import Recipe

ROI_FOR = {"Missing Component": "Presence", "Polarity Error": "Polarity", "Solder Bridge": "Solder Bridge"}
ROI, WHOLE_BOARD, NOT_COVERED, STAGE_2 = "roi", "whole board", "not covered", "stage 2"


@dataclass(frozen=True)
class Cover:
    """How a recipe covers one mandatory check: by its enabled ROIs of the check's type (`rois`, ROI), by the whole
    board (the AI model or the Golden board comparison, WHOLE_BOARD), not at all (NOT_COVERED), or never on a Stage 1
    station, as the check needs a 3D or side camera (STAGE_2)."""

    check: str
    how: str
    rois: tuple[str, ...] = ()


def coverage(recipe: Recipe) -> list[Cover]:
    """Each mandatory check, in the table's order, with how `recipe` covers it. A check judged in an ROI (ROI_FOR) is
    covered only by an enabled ROI of its type; the others a Stage 1 station judges are covered by the whole board
    while the recipe runs the AI check or the Golden board comparison."""
    out = []
    for check in MANDATORY_AOI_SET:
        if check in REQUIRES_3D_OR_SIDE:
            out.append(Cover(check, STAGE_2))
        elif check in ROI_FOR:
            names = tuple(r.name for r in recipe.rois if r.enabled and r.type == ROI_FOR[check])
            out.append(Cover(check, ROI if names else NOT_COVERED, names))
        else:
            out.append(Cover(check, WHOLE_BOARD if recipe.use_ai or recipe.use_compare else NOT_COVERED))
    return out


def uncovered(recipe: Recipe) -> list[str]:
    """The Stage 1 checks `recipe` does not cover: saving it asks for a reason, kept with the revision."""
    return [c.check for c in coverage(recipe) if c.how == NOT_COVERED]
