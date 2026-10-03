"""REQ-CMP-004 (S27): the "why" box on Compare holds one plain-word sentence per NG or WARN check, the NG ones first,
naming the check, its value and its threshold with units, in the Charter's words only; the sentences are templates the
screen translates, so a Korean screen reads them in Korean once they are translated."""

from __future__ import annotations

import re
import subprocess
import xml.etree.ElementTree as ET
from pathlib import Path

import cv2
import numpy as np
from PySide6.QtCore import QCoreApplication, QTranslator
from pytestqt.qtbot import QtBot

from aoi.core import explain as ex
from aoi.core.inspector import NG, NO_AI_NOTE, NO_GOLDEN_NOTE, OK, WARN, Check, Defect, InspectionResult, Inspector
from aoi.core.recipe import ROI, Recipe
from aoi.core.services import AppContext
from aoi.ui.main_window import MainWindow
from aoi.ui.pages.compare import CHECK_NAMES, JUDGED, MODES, RULES, SOURCES, ComparePage
from aoi.ui.pages.inspection import InspectionPage
from tests.conftest import TrainedModel
from tests.regression import make_regression_set as rs
from tools.update_translations import TS_FILE, qt_tool

# The Charter's "Words we use": the "Not" column of each term, and the words its plain-words rule bans.
BANNED = [
    "product type", "part number", "master image", "test image", "program", "job", "zone", "window", "pass", "fail",
    "warning", "priority", "error", "false alarm", "overkill", "escape", "false OK", "limit", "cut-off", "cutoff",
    "learning", "test run", "machine", "cell", "project", "z-score", "fatal", "illegal", "invalid",
]  # fmt: skip
JARGON = ["SSIM", "inlier"]  # engineering words an Operator's sentence never uses (Charter, "Plain words")
LONE_MODEL = re.compile(r"(?<!AI )(?<!board )\bmodels?\b", re.IGNORECASE)  # "model" alone: AI model or board model
CHECK_TEMPLATES = {*ex.CHECKS.values(), *ex.ROI_CHECK.values(), ex.OTHER_CHECK}
FAILING = {"< thr → NG": {NG, WARN}, "≥ thr → NG": {NG, WARN}, "> thr → NG": {NG}, "info only": {WARN}}  # by rule
CASES = [  # (name, value, threshold, rule, verdict, source): the sentence it gets, word for word
    (("SSIM similarity", 0.7123, 0.8, "< thr → NG", NG, "Compare"),
     "Similarity to the Golden board is 0.71, below its threshold of 0.80."),
    (("SSIM similarity", 0.8123, 0.8, "< thr → NG", WARN, "Compare"),
     "Similarity to the Golden board is 0.81, at or just above its threshold of 0.80."),
    (("SSIM similarity", 0.79996, 0.8, "< thr → NG", NG, "Compare"),  # four decimals still tie: five
     "Similarity to the Golden board is 0.79996, below its threshold of 0.80000."),
    (("Changed area %", 0.75, 0.5, "≥ thr → NG", NG, "Compare"),
     "The changed area is 0.75 % of the board, at or above its threshold of 0.50 %."),
    (("Changed area %", 0.5, 0.5, "≥ thr → NG", NG, "Compare"),  # equal: two decimals
     "The changed area is 0.50 % of the board, at or above its threshold of 0.50 %."),
    (("Changed area %", 0.4996, 0.5, "≥ thr → NG", WARN, "Compare"),
     "The changed area is 0.4996 % of the board, close to its threshold of 0.5000 %."),
    (("Difference regions", 3, 0, "> thr → NG", NG, "Compare"),
     "The number of difference regions is 3, more than the threshold of 0."),
    (("Alignment inliers", 7, 12, "info only", WARN, "Compare"),
     "The number of alignment points is 7, fewer than the threshold of 12, so the other checks may be off: check that"
     " the board lies flat, then inspect it again."),
    (("AI anomaly score", 3.25, 2.5, "≥ thr → NG", NG, "AI"),
     "The AI score is 3.25, at or above its threshold of 2.50."),
    (("AI anomaly score", 2.31, 2.5, "≥ thr → NG", WARN, "AI"),
     "The AI score is 2.31, close to its threshold of 2.50."),
    (("ROI R1 [Presence]", 1.4, 1.0, "≥ thr → NG", NG, "ROI"),
     "In ROI R1 [Presence], the AI score is 1.40 × the AI model's threshold, at or above the ROI's threshold of"
     " 1.00 ×."),
    (("ROI R2 [Polarity]", 0.93, 1.0, "≥ thr → NG", WARN, "ROI"),
     "In ROI R2 [Polarity], the AI score is 0.93 × the AI model's threshold, close to the ROI's threshold of 1.00 ×."),
    (("Board flatness", 2.0, 1.0, "≥ thr → NG", NG, "Compare"),  # a name this build does not know (stored data)
     "Board flatness is 2.00, against its threshold of 1.00."),
]  # fmt: skip
NOTE_TEXTS = [
    "No Golden board is set for this board model, so the board was not compared with one: an Engineer makes one by"
    " training an AI model on Training.",
    "No AI model is trained for this board model, so the AI check did not run: an Engineer trains one on Training.",
]


def _check(name: str, value: float, thr: float, rule: str, verdict: str, source: str) -> Check:
    return Check(name, value, thr, rule, verdict, source, "", region="R @ 0,0 8x8" if source == "ROI" else "Board")


def _defect(no: int, severity: str) -> Defect:
    return Defect(no, "Anomaly", 1.2, "Top", 10 * no, 20, 30, 40, "ai", severity=severity)


def _sentences(res: InspectionResult) -> list[str]:
    return [s.text() for s in ex.explain(res) if s.template in CHECK_TEMPLATES]


def test_req_cmp_004_sentence_per_failing_check(tmp_path: Path) -> None:
    """Every kind of NG and WARN check gets its own sentence, word for word, naming it with its value and threshold and
    their unit, and passing checks get none; NG sentences come before WARN ones; then, over the 40 boards of the
    synthetic regression set as the engine judged them, exactly one sentence per failing check, each with that check's
    numbers."""
    passing = _check("SSIM similarity", 0.95, 0.8, "< thr → NG", OK, "Compare")
    for case, sentence in CASES:
        assert _sentences(InspectionResult(case[4], 0.0, checks=[passing, _check(*case)])) == [sentence]
    order = [CASES[1][0], CASES[3][0], CASES[7][0], CASES[8][0]]  # SSIM WARN, changed area NG, alignment, AI NG
    assert _sentences(InspectionResult(NG, 0.0, checks=[_check(*c) for c in order])) == [
        CASES[3][1], CASES[8][1], CASES[1][1], CASES[7][1]
    ]  # fmt: skip
    out = tmp_path / "regression"
    boards = rs.generate(out)
    golden = cv2.imread(str(out / "golden.png"))
    verdicts = set()
    for board in boards:
        res = rs.inspect(cv2.imread(str(out / board.name)), golden)
        failing = [c for c in res.checks if c.verdict == NG] + [c for c in res.checks if c.verdict == WARN]
        sentences = _sentences(res)
        assert len(sentences) == len(failing), (board.name, sentences)
        for c, sentence in zip(failing, sentences, strict=True):
            assert all(n in sentence for n in ex.numbers(c)), (board.name, sentence)
        assert res.verdict == OK or sentences, f"{board.name}: a {res.verdict} with no check named"
        verdicts.add(res.verdict)
    assert {OK, NG} <= verdicts


def test_req_cmp_004_every_engine_check_has_its_sentences(tiny_model: TrainedModel) -> None:
    """Each check the engine makes, with each failing verdict its rule can give, has a sentence of its own: a check
    added to the engine without one fails here, not on an Operator's screen."""
    recipe = Recipe(board_model=tiny_model.board_model, rois=[ROI("R1", "Presence", 0, 0, 40, 40)])
    res = Inspector(recipe, tiny_model.model, tiny_model.reference).inspect(tiny_model.reference)
    assert {(c.name, v) for c in res.checks if c.source != "ROI" for v in FAILING[c.rule]} == set(ex.CHECKS)
    assert {v for c in res.checks if c.source == "ROI" for v in FAILING[c.rule]} == set(ex.ROI_CHECK)


def test_req_cmp_004_why_without_a_failing_check() -> None:
    """With no failing check: why the board is a WARN when defects above Minor severity make it one (one or several,
    Minor ones not counted), that every deciding check is inside its threshold for an OK, and that the stored checks
    do not show why for anything else, an OK that no check judged (stored before #169) included; then one sentence per
    check that did not run, with what to do."""

    def why(verdict: str, defects: list[Defect], notes: list[str] | None = None, checked: bool = True) -> list[str]:
        checks = [_check("SSIM similarity", 0.99, 0.8, "< thr → NG", OK, "Compare")] if checked else []
        res = InspectionResult(verdict, 0.0, checks=checks, defects=defects, notes=notes or [])
        return [s.text() for s in ex.explain(res)]

    one = "No check failed, but a defect above Minor severity is marked on the board, so a person needs to look."
    assert (
        why(WARN, [_defect(1, "Critical")]) == why(WARN, [_defect(1, "Critical"), *[_defect(2, "Minor")] * 2]) == [one]
    )
    assert why(WARN, [_defect(1, "Major"), _defect(2, "Major")]) == [
        "No check failed, but 2 defects above Minor severity are marked on the board, so a person needs to look."
    ]
    assert (
        why(OK, [])
        == why(OK, [_defect(1, "Minor")])
        == ["Every check that decides the verdict is inside its threshold."]
    )
    assert why(NG, []) == why(OK, [], checked=False) == ["The stored checks do not show why; inspect the board again."]
    assert why(OK, [], [NO_GOLDEN_NOTE, NO_AI_NOTE, "Other"]) == [
        "Every check that decides the verdict is inside its threshold.", *NOTE_TEXTS, "Note: Other"
    ]  # fmt: skip
    golden = np.zeros((64, 64, 3), np.uint8)  # with neither a Golden board nor an AI model a board is refused (#169)
    compared = Inspector(Recipe(board_model="B"), reference=golden).inspect(golden)  # a Golden board, no AI model
    assert [s.text() for s in ex.notes(compared)] == NOTE_TEXTS[1:]
    assert (NO_GOLDEN_NOTE, NO_AI_NOTE) == (  # results stored by earlier builds hold these words: they never change
        "No golden reference image set for this board model; comparison skipped.",
        "No trained model for this board model; AI check skipped.",
    )


def test_req_cmp_004_uses_only_glossary_terms() -> None:
    """Every sentence template (all of them: the list is the one pyside6-lupdate extracts under "Explain"), and every
    name, source, rule and view the Compare page shows, uses the Charter's terms: no word from the glossary's "Not"
    column, "model" only as AI model or board model; the sentences and the check names use no engineering jargon (a
    name may give the method in brackets after the plain words), and every check's sentence gives its value and
    threshold."""
    contexts = ET.parse(TS_FILE).getroot().findall("context")
    marked = {m.findtext("source") for c in contexts if c.findtext("name") == "Explain" for m in c.findall("message")}
    assert set(ex.TEMPLATES) == marked
    texts = [*ex.TEMPLATES, *CHECK_NAMES.values(), *SOURCES.values(), *RULES.values(), *MODES, *JUDGED.values()]
    for text in texts:
        for word in BANNED:
            assert not re.search(rf"\b{re.escape(word)}s?\b", text, re.IGNORECASE), (word, text)
        assert not LONE_MODEL.search(text), text
    for text in ex.TEMPLATES:
        assert not any(word.lower() in text.lower() for word in JARGON), text
    for text in CHECK_NAMES.values():  # "Similarity (SSIM)": the plain words first, the method only in brackets
        assert not any(word.lower() in re.sub(r"\(.*?\)", "", text).lower() for word in JARGON), text
    for template in CHECK_TEMPLATES:
        assert "{value}" in template and "{threshold}" in template, template


def test_req_cmp_004_the_sentences_reach_the_screens(qtbot: QtBot, ctx: AppContext, tmp_path: Path) -> None:
    """Compare's box shows the heading and every sentence of `explain`, a value as text and never as markup, and a
    translated template in the UI language with its values in place; the Inspection page words the checks that did
    not run the same way."""
    win = MainWindow(ctx)
    qtbot.addWidget(win)
    page, inspection = win.pages["Compare"], win.pages["Inspection"]
    assert isinstance(page, ComparePage) and isinstance(inspection, InspectionPage)
    checks = [_check(*CASES[1][0]), _check(*CASES[8][0]), _check(*CASES[10][0])]
    res = InspectionResult(
        NG, 1.3, checks=checks, notes=[NO_AI_NOTE, "<b>1 & 2</b>"], image=np.zeros((8, 8, 3), np.uint8)
    )
    page._show_result(res)
    assert page.why.toPlainText().split("\n") == ["Why this board is NG:", *(f"• {s.text()}" for s in ex.explain(res))]
    assert page.why.toPlainText().endswith("Note: <b>1 & 2</b>"), "a value is shown as text, never as markup"
    inspection._on_result((tmp_path / "b.png", res, None, None, None))
    assert inspection.summary.text().split("\n")[1:] == [NOTE_TEXTS[1], "Note: <b>1 & 2</b>"]
    korean = "AI 점수가 {value}로 임계값 {threshold} 이상입니다."
    tree = ET.parse(TS_FILE)
    for context in tree.getroot().findall("context"):
        for message in context.findall("message"):
            if (context.findtext("name"), message.findtext("source")) == (
                "Explain",
                ex.CHECKS[("AI anomaly score", NG)],
            ):
                translation = message.find("translation")
                assert translation is not None
                translation.text = korean
                translation.attrib.pop("type", None)
    tree.write(tmp_path / "test.ts", encoding="utf-8", xml_declaration=True)
    qm = tmp_path / "test.qm"
    subprocess.run([qt_tool("pyside6-lrelease"), "-silent", str(tmp_path / "test.ts"), "-qm", str(qm)], check=True)
    translator = QTranslator()
    assert translator.load(str(qm)) and QCoreApplication.installTranslator(translator)
    try:
        page._show_result(res)
        assert "AI 점수가 3.25로 임계값 2.50 이상입니다." in page.why.toPlainText(), page.why.toPlainText()
    finally:
        QCoreApplication.removeTranslator(translator)
