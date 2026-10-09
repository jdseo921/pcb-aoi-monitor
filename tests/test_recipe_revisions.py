"""REQ-RCP-004 and REQ-RCP-005 (stage S50, part 1): a save never overwrites, makes revision n+1 whose audit entry holds
the recipe before and after, and lists what it changes before -> after; any revision can be read back; a save that
leaves a Stage 1 mandatory AOI check uncovered needs a reason, kept with the revision."""

from __future__ import annotations

import dataclasses

import pytest

from aoi.core.recipe import ROI, STAGE1_CHECKS, Recipe, changes
from aoi.core.services import AppContext
from aoi.defects import MANDATORY_AOI_SET, REQUIRES_3D_OR_SIDE
from aoi.errors import AoiError
from tests.test_req_done_in_v01 import BOARD


def test_req_rcp_005_stage2_checks_not_counted() -> None:
    """The 6 Stage 1 checks are the mandatory set without the 4 that need Stage 2 hardware; a recipe with the AI check
    or the Golden board comparison on covers them all, and with both off only its ROIs do."""
    assert STAGE1_CHECKS == [c for c in MANDATORY_AOI_SET if c not in REQUIRES_3D_OR_SIDE] and len(STAGE1_CHECKS) == 6
    assert Recipe(BOARD).uncovered_checks() == []
    assert Recipe(BOARD, use_ai=False).uncovered_checks() == []  # the comparison still covers the whole board
    bare = Recipe(BOARD, use_ai=False, use_compare=False)
    assert bare.uncovered_checks() == STAGE1_CHECKS
    bare.rois = [ROI("R1", "Presence"), ROI("R2", "Polarity", enabled=False)]  # a disabled ROI covers nothing
    assert "Missing Component" not in bare.uncovered_checks() and "Polarity Error" in bare.uncovered_checks()


def test_req_rcp_005_uncovered_check_needs_reason(trained_ctx: AppContext) -> None:
    """A save leaving a Stage 1 check uncovered is refused with AOI-RCP-013 naming the checks, nothing stored; with a
    reason it is saved and the reason is kept with the revision."""
    ctx = trained_ctx
    before = (ctx.recipe_history(BOARD), ctx.audit_entries())
    bare = dataclasses.replace(ctx.recipe(BOARD)[1], use_ai=False, use_compare=False, rois=[])
    for reason in (None, "", "   "):
        with pytest.raises(AoiError) as e:
            ctx.save_recipe(bare, reason)
        assert e.value.code == "AOI-RCP-013" and "Missing Component, Misalignment" in e.value.what
    assert (ctx.recipe_history(BOARD), ctx.audit_entries()) == before
    rev = ctx.save_recipe(bare, "ROIs follow once the fixture arrives")
    saved = ctx.recipe_revision(BOARD, rev)
    assert saved is not None and saved["reason"] == "ROIs follow once the fixture arrives"
    assert ctx.audit_entries(action="recipe.save")[0]["reason"] == "ROIs follow once the fixture arrives"


def test_req_rcp_004_save_creates_revision_with_diff(trained_ctx: AppContext) -> None:
    """Saving adds revision n+1 and leaves revision n as it was; its entry holds before and after, and changes() lists
    each changed setting and ROI before -> after."""
    ctx = trained_ctx
    rev, old = ctx.recipe(BOARD)
    new = dataclasses.replace(old, diff_threshold=old.diff_threshold + 5, rois=[*old.rois, ROI("R9", "Presence")])
    assert ctx.save_recipe(new) == rev + 1
    kept = ctx.recipe_revision(BOARD, rev)
    assert kept is not None and kept["recipe"].to_dict() == old.to_dict()
    entry = ctx.audit_entries(action="recipe.save")[0]
    assert (entry["before"], entry["after"]) == (old.to_dict(), new.to_dict())
    diff = changes(old.to_dict(), new.to_dict())
    assert ("diff_threshold", old.diff_threshold, old.diff_threshold + 5) in diff
    assert [d for d in diff if d[0] == "ROI R9"] == [("ROI R9", None, new.to_dict()["rois"][-1])]
    removed = changes(new.to_dict(), old.to_dict())
    assert ("ROI R9", new.to_dict()["rois"][-1], None) in removed


def test_req_rcp_004_old_revision_viewable(trained_ctx: AppContext) -> None:
    """Any revision reads back with its user, time and recipe; a revision that does not exist reads None."""
    ctx = trained_ctx
    first = ctx.recipe_revision(BOARD, 1)
    assert first is not None and first["revision"] == 1 and first["user"] and first["created_at"]
    assert isinstance(first["recipe"], Recipe) and first["recipe"].board_model == BOARD
    assert ctx.recipe_revision(BOARD, 999) is None
