"""REQ-RCP-005 (S50): the Recipe Editor's AOI checks tab marks how the recipe covers each of the 10 mandatory AOI
checks of the defect classification table (section 4): by an ROI, by the whole board, not at all, or only with Stage 2
hardware (recipe-editor sketch)."""

from __future__ import annotations

from dataclasses import replace

from PySide6.QtCore import QRectF
from PySide6.QtWidgets import QTabWidget
from pytestqt.qtbot import QtBot

from aoi.core import checklist
from aoi.core.checklist import NOT_COVERED, ROI, STAGE_2, WHOLE_BOARD
from aoi.core.recipe import ROI as Roi
from aoi.core.recipe import Recipe
from aoi.core.services import AppContext
from aoi.defects import MANDATORY_AOI_SET
from tests.test_recipe_rois import _page

STAGE_2_CHECKS = {"Shield Can Gap", "Connector Pin Height", "3D Coplanarity", "Solder Volume"}


def test_req_rcp_005_each_mandatory_check_is_covered_by_an_roi_the_whole_board_or_stage_2() -> None:
    """A check judged in an ROI is covered by an enabled ROI of its type alone; the whole-board checks by the AI check
    or the Golden board comparison; the 4 that need a 3D or side camera are Stage 2 whatever the recipe holds."""
    r = Recipe("B", rois=[Roi("R1", "Presence"), Roi("R2", "Polarity", enabled=False), Roi("R3", "Height")])
    got = {c.check: (c.how, c.rois) for c in checklist.coverage(r)}
    assert list(got) == MANDATORY_AOI_SET
    assert got["Missing Component"] == (ROI, ("R1",))
    assert got["Polarity Error"] == got["Solder Bridge"] == (NOT_COVERED, ()), "a disabled ROI covers nothing"
    assert {check for check, (how, _) in got.items() if how == STAGE_2} == STAGE_2_CHECKS
    assert {got[c][0] for c in ("Misalignment", "Tombstone", "Cold Joint")} == {WHOLE_BOARD}
    whole = ["Misalignment", "Tombstone", "Cold Joint"]
    assert checklist.uncovered(replace(r, use_ai=False)) == ["Polarity Error", "Solder Bridge"]
    assert checklist.uncovered(replace(r, use_compare=False)) == ["Polarity Error", "Solder Bridge"]
    off = checklist.uncovered(replace(r, use_ai=False, use_compare=False))
    assert off == [c for c in MANDATORY_AOI_SET if c in whole or c in ("Polarity Error", "Solder Bridge")]


def test_req_rcp_005_the_aoi_checks_tab_marks_each_check_as_the_recipe_is_edited(
    qtbot: QtBot, trained_ctx: AppContext
) -> None:
    """The tab, named AOI checks, lists the 10 checks in the table's order; an ROI drawn names itself beside the check
    it covers, and with the AI check and the Golden board comparison both off, the whole-board checks are not
    covered. Nothing is saved for the marks to change."""
    page = _page(qtbot, trained_ctx)
    tabs = page.findChild(QTabWidget)
    assert tabs is not None and "AOI checks" in [tabs.tabText(i) for i in range(tabs.count())]

    def marks() -> dict[str, str]:
        rows = [page.mand_list.item(i).text() for i in range(page.mand_list.count())]
        return {row[:24].strip(): row[24:].strip() for row in rows}

    page.edited_recipe.rois.clear()
    page.roi_type.setCurrentIndex(page.roi_type.findData("Presence"))
    page.view.roiDrawn.emit(QRectF(100, 100, 80, 60))
    shown = marks()
    assert list(shown) == MANDATORY_AOI_SET
    assert shown["Missing Component"] == "✓  ROI R1" and shown["Solder Bridge"] == "○  not covered"
    assert shown["Misalignment"] == "•  whole board"
    assert {c for c, mark in shown.items() if "Stage 2" in mark} == STAGE_2_CHECKS
    page.use_ai.setChecked(False)
    assert marks()["Tombstone"] == "•  whole board", "the comparison alone covers it"
    page.use_cmp.setChecked(False)
    assert marks()["Tombstone"] == marks()["Cold Joint"] == "○  not covered"
    assert trained_ctx.recipe(page.board_model or "")[0] == page.rev, "nothing saved"
