"""REQ-INSP-018 (ADR 0015): on a bare board, a recipe that names copper defects names each difference outside an ROI as
Open Circuit, Short Circuit, Mousebite, Spur, Spurious Copper or Pin-hole / Missing Hole, from how the copper changed
against the Golden board; a recipe that names none, as every recipe before, keeps Anomaly, and no name changes a
verdict. The boards here are drawn: they show the rules work, never how often (counts on public scans are in
docs/tests/, never an accuracy claim)."""

from __future__ import annotations

from collections.abc import Callable

import cv2
import numpy as np
import pytest
from PySide6.QtWidgets import QMessageBox
from pytestqt.qtbot import QtBot

from aoi import defects
from aoi.core import copper
from aoi.core.inspector import Inspector
from aoi.core.recipe import ROI, Recipe
from aoi.core.services import AppContext
from tests.test_recipe_rois import _page
from tests.test_req_done_in_v01 import BOARD

SUBSTRATE, COPPER = 40, 200  # grey levels of a lit bare board: copper light on dark laminate
Draw = Callable[[np.ndarray], None]


def golden() -> np.ndarray:
    """A bare board: horizontal traces 8 px wide, 24 px apart, broken into segments, round pads with drilled holes, and
    a text-like scatter of small pads so that the board aligns on its features."""
    img = np.full((480, 640, 3), SUBSTRATE, np.uint8)
    for y in range(60, 440, 24):
        cv2.rectangle(img, (40, y), (300, y + 7), (COPPER,) * 3, -1)
    for x, y in ((420, 120), (520, 120), (420, 260), (520, 260)):
        cv2.circle(img, (x, y), 22, (COPPER,) * 3, -1)
        cv2.circle(img, (x, y), 8, (SUBSTRATE,) * 3, -1)
    rng = np.random.default_rng(7)
    for _ in range(60):
        x, y = int(rng.integers(340, 620)), int(rng.integers(320, 460))
        cv2.rectangle(img, (x, y), (x + int(rng.integers(4, 12)), y + int(rng.integers(4, 12))), (COPPER,) * 3, -1)
    return img


def cut(img: np.ndarray) -> None:  # a gap across the trace at y 156
    img[154:166, 150:158] = SUBSTRATE


def bridge(img: np.ndarray) -> None:  # copper across the gap between the traces at y 156 and y 180
    img[163:181, 150:158] = COPPER


def notch(img: np.ndarray) -> None:  # a bite out of the trace's lower edge
    img[161:164, 150:158] = SUBSTRATE


def spur(img: np.ndarray) -> None:  # a stub off the trace's lower edge, short of the next trace
    img[163:170, 150:155] = COPPER


def speck(img: np.ndarray) -> None:  # copper standing alone on bare laminate
    img[200:208, 340:348] = COPPER


def plugged(img: np.ndarray) -> None:  # a pad's hole not drilled
    cv2.circle(img, (420, 120), 9, (COPPER,) * 3, -1)


def pinhole(img: np.ndarray) -> None:  # a hole through a pad's copper ring
    img[103:108, 418:423] = SUBSTRATE


CASES = {  # each drawn defect, the box a region would put round it, and the name it gets
    "Open Circuit": (cut, (150, 154, 8, 12)),
    "Short Circuit": (bridge, (150, 163, 8, 18)),
    "Mousebite": (notch, (150, 161, 8, 3)),
    "Spur": (spur, (150, 163, 5, 7)),
    "Spurious Copper": (speck, (340, 200, 8, 8)),
    "Pin-hole / Missing Hole": (plugged, (411, 111, 18, 18)),
}


def board(draw: Draw) -> np.ndarray:
    img = golden()
    draw(img)
    return img


@pytest.mark.parametrize("name", list(CASES))
def test_req_insp_018_each_copper_change_is_named(name: str) -> None:
    """Copper lost that splits a trace is an Open Circuit, lost from its edge a Mousebite; copper added that joins two
    traces is a Short Circuit, off one trace a Spur, alone a Spurious Copper; a hole filled is a Pin-hole / Missing
    Hole. Copper dark on light laminate (the recipe's Dark copper) is named the same."""
    draw, box = CASES[name]
    gold, test = golden(), board(draw)
    level = copper.copper_level(gold)
    assert level is not None
    assert copper.copper_type(test, gold, *box, light=True, level=level) == name
    dark_gold, dark_test = 255 - gold, 255 - test
    assert copper.copper_type(dark_test, dark_gold, *box, light=False, level=copper.copper_level(dark_gold)) == name


def test_req_insp_018_a_hole_through_copper_is_a_pinhole() -> None:
    """Copper lost inside a pad, touching no edge of it, opens a hole: a Pin-hole / Missing Hole, not a Mousebite."""
    assert copper.copper_type(board(pinhole), golden(), 418, 103, 5, 5) == "Pin-hole / Missing Hole"


def test_req_insp_018_no_copper_change_or_no_copper_names_nothing() -> None:
    """A window where no copper changed, or one of plain laminate with no copper and substrate to tell apart, names
    nothing: the region stays an Anomaly. So does the wrong shade, which reads copper as laminate."""
    gold = golden()
    assert copper.copper_type(gold.copy(), gold, 150, 154, 8, 12) is None
    plain = np.full((200, 200, 3), SUBSTRATE, np.uint8)
    smudged = plain.copy()
    smudged[90:110, 90:110] = SUBSTRATE + 20  # a stain, not copper: too little contrast
    assert copper.copper_type(smudged, plain, 90, 90, 20, 20) is None
    assert copper.copper_level(plain) is None


def _defects(recipe: Recipe, draw: Draw) -> list[tuple[str, str]]:
    res = Inspector(recipe, reference=golden()).inspect(board(draw))
    return [(d.type, d.severity) for d in res.defects]


def test_req_insp_018_the_recipe_names_them_and_no_verdict_changes() -> None:
    """Inspected with a recipe set to Light copper, a board's difference outside every ROI carries the copper
    defect's name and the table's severity; with copper naming off, as every recipe before it, the same region is an
    Anomaly. The verdict, the checks and the boxes are the same either way; a region on an ROI keeps the ROI's type."""
    off = Recipe(board_model="BARE", use_ai=False, min_defect_area=20)
    named = Recipe(board_model="BARE", use_ai=False, min_defect_area=20, copper="light")
    gold, test = golden(), board(cut)
    plain, light = (Inspector(r, reference=gold).inspect(test) for r in (off, named))
    assert [d.type for d in plain.defects] == ["Anomaly"]
    assert [(d.type, d.severity) for d in light.defects] == [("Open Circuit", "Critical")]
    assert light.verdict == plain.verdict == "NG"
    assert [(c.name, c.verdict) for c in light.checks] == [(c.name, c.verdict) for c in plain.checks]
    assert [(d.x, d.y, d.w, d.h) for d in light.defects] == [(d.x, d.y, d.w, d.h) for d in plain.defects]
    named.rois = [ROI("U1", "Solder Bridge", 130, 140, 40, 40)]
    assert _defects(named, cut) == [("Solder Bridge", "Critical")]
    assert _defects(Recipe(board_model="BARE", use_ai=False, min_defect_area=20, copper="pink"), speck) == [
        ("Anomaly", "Major")
    ]


def test_req_insp_018_a_recipe_stores_copper_only_when_set() -> None:
    """A recipe that names no copper defect is stored as before, without the key, so stored recipes and the regression
    set's are unchanged; Light or Dark copper is stored and read back."""
    assert "copper" not in Recipe(board_model="B").to_dict()
    for shade in ("light", "dark"):
        stored = Recipe(board_model="B", copper=shade).to_dict()
        assert stored["copper"] == shade and Recipe.from_dict(stored).copper == shade


def test_req_insp_018_the_four_new_types_are_in_the_table() -> None:
    """Mousebite, Spur, Spurious Copper and Pin-hole / Missing Hole join Open Circuit and Short Circuit, which the table
    holds, as Bare Board types a labeller can pick: 37 types in all, each name the engine gives one of them."""
    added = [d for d in defects.DEFECT_TYPES if d.category == "Bare Board"]
    assert [d.name for d in added] == ["Mousebite", "Spur", "Spurious Copper", "Pin-hole / Missing Hole"]
    assert all(d.severity == "Major" for d in added) and len(defects.names()) == 37
    assert set(copper.TYPES) <= set(defects.names()) and "Bare Board" in defects.categories()


def test_req_insp_018_the_recipe_editor_sets_the_copper_shade(
    qtbot: QtBot, trained_ctx: AppContext, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Thresholds on the Recipe Editor offers Copper defect names: Off (assembled boards), Light copper or Dark copper,
    with a note on what it names; Save Recipe lists the change before → after, and the revision saved holds it."""
    monkeypatch.setattr(QMessageBox, "information", staticmethod(lambda *_: QMessageBox.StandardButton.Ok))
    page = _page(qtbot, trained_ctx)
    shown = [(page.copper.itemText(i), page.copper.itemData(i)) for i in range(page.copper.count())]
    assert shown == [("Off (assembled boards)", None), ("Light copper", "light"), ("Dark copper", "dark")]
    assert page.copper.currentData() is None
    page.copper.setCurrentIndex(page.copper.findData("dark"))
    page.ask_save()
    assert page.save_sheet.changes.text() == "Copper defect names: Off (assembled boards) → Dark copper"
    page.save_sheet.reason.setText("bare boards scanned with dark copper")
    page.save_sheet.btn_save.click()
    assert trained_ctx.recipe(BOARD)[1].copper == "dark" and page.copper.currentText() == "Dark copper"
