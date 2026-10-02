"""REQ-CMP-005: a result is judged again with other thresholds from the evidence it holds, without aligning, comparing
or running the AI model (S28a, the engine: `Inspector.judge` and `re_grade`)."""

from __future__ import annotations

import copy
from pathlib import Path

import pytest

from aoi.core import anomaly, explain, inspector
from aoi.core.imaging import load_image
from aoi.core.inspector import (
    NO_AI_NOTE,
    NO_GOLDEN_NOTE,
    NOT_AI_JUDGED_NOTE,
    NOT_COMPARED_NOTE,
    AiEvidence,
    InspectionResult,
    Inspector,
    re_grade,
)
from aoi.core.recipe import ROI, Recipe
from tests.conftest import TrainedModel

AI, IN_R1, AREA, REGIONS = "AI anomaly score", "ROI R1 [Presence]", "Changed area %", "Difference regions"
WHAT_IF = [  # other thresholds, one change at a time and all at once, and checks each grades otherwise on a test board
    ({"anomaly_threshold": 0.5}, {AI, IN_R1}), ({"anomaly_threshold": 50.0}, {AI, IN_R1}),
    ({"diff_threshold": 20}, {REGIONS}), ({"diff_threshold": 90}, {AREA}),
    ({"min_defect_area": 5}, {REGIONS}), ({"min_defect_area": 400}, {REGIONS}),
    ({"ssim_min": 0.99}, {"SSIM similarity"}), ({"max_diff_regions": 3}, {REGIONS}),
    ({"changed_pct_max": 0.01}, {AREA}), ({"warn_ratio": 0.3}, {AI, IN_R1, "SSIM similarity"}),
    (
        {"anomaly_threshold": 3.0, "diff_threshold": 30, "min_defect_area": 20, "ssim_min": 0.9, "max_diff_regions": 1},
        {AI, REGIONS},
    ),
]  # fmt: skip


def _what_if(base: Recipe) -> list[Recipe]:
    """`base` with each set of other thresholds in WHAT_IF."""
    out = []
    for change, _ in WHAT_IF:
        r = copy.deepcopy(base)
        for k, v in change.items():
            setattr(r, k, v)
        out.append(r)
    return out


def _refuse_the_engine(monkeypatch: pytest.MonkeyPatch) -> None:
    """From here on, running the AI model, loading one, aligning or comparing with the golden board fails the test."""

    def refuse(*a: object, **k: object) -> None:
        raise AssertionError("the result was not judged again from its evidence: the engine ran")

    for owner, name in (
        (anomaly.AnomalyModel, "anomaly_map"), (anomaly.AnomalyModel, "score"), (anomaly.AnomalyModel, "load"),
        (inspector, "compare"), (inspector, "align_to_reference"),
    ):  # fmt: skip
        monkeypatch.setattr(owner, name, refuse)


def _evidence(res: InspectionResult, model: anomaly.AnomalyModel) -> AiEvidence:
    """The AI evidence of `res` as a re-evaluation finds it: its AI check's score, the AI model's calibration."""
    check = next(c for c in res.checks if c.source == "AI")
    return AiEvidence(check.value, model.image_threshold, model.pixel_threshold, check.explain)


def _assert_same(got: InspectionResult, want: InspectionResult, what: str) -> None:
    """Every field of every check and defect, the verdict, the score and the notes."""
    assert (got.verdict, got.checks, got.defects, got.score, got.notes) == (
        want.verdict, want.checks, want.defects, want.score, want.notes,
    ), what  # fmt: skip


def test_req_cmp_005_judging_again_equals_inspecting_with_those_thresholds(
    tiny_model: TrainedModel, synthetic_dataset: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Every test board, inspected under a recipe with an ROI, then judged again from the evidence it holds without the
    engine running: with the thresholds it was judged by it gets back its checks, defects and verdict, field for field,
    and with each of eleven other sets of thresholds what inspecting it with them gives; each set grades the checks it
    governs otherwise on some board, so a threshold the judging ignored would show. The result judged is not changed,
    and its inspection time, view and picture carry over."""
    recipe = Recipe(board_model="TINY", rois=[ROI("R1", "Presence", 200, 150, 160, 120, ai_score=0.8)])
    what_if, model = _what_if(recipe), tiny_model.model
    boards = sorted(synthetic_dataset.glob("test/*/*.png"))
    assert len(boards) > 20
    regraded: list[set[str]] = [set() for _ in what_if]
    for path in boards:
        img = load_image(path)
        live, *fresh = (Inspector(r, model, tiny_model.reference, side="Side").inspect(img) for r in [recipe, *what_if])
        grades = {c.name: c.verdict for c in live.checks}
        for seen, want in zip(regraded, fresh, strict=True):
            seen |= {c.name for c in want.checks if grades.get(c.name) != c.verdict}
        as_inspected, ai = live.to_dict(), _evidence(live, model)
        with monkeypatch.context() as m:
            _refuse_the_engine(m)
            again = re_grade(live, recipe, ai)
            _assert_same(again, live, f"{path.name} as judged")
            Inspector(recipe).judge(again, ai)  # judged twice: afresh each time, never added to
            _assert_same(again, live, f"{path.name} judged twice")
            for i, (thresholds, want) in enumerate(zip(what_if, fresh, strict=True)):
                _assert_same(re_grade(live, thresholds, ai), want, f"{path.name} what-if {i}")
        assert live.to_dict() == as_inspected, "the result judged again is not changed"
        assert (again.elapsed_ms, again.view, again.image, again.reference) == (
            live.elapsed_ms, "Side", live.image, live.reference,
        )  # fmt: skip
    for (change, governed), seen in zip(WHAT_IF, regraded, strict=True):
        assert governed <= seen, (change, seen)


def test_req_cmp_005_a_check_that_did_not_run_is_not_judged_again(tiny_model: TrainedModel, ng_board: Path) -> None:
    """A check the recipe turns on that did not run on the board is not judged, and its note (in inspect's order, never
    twice) says why, in plain words; a check turned off loses its check and its note. A check that ran needs its map and
    its AI evidence, unless the recipe turns it off."""
    on, off = Recipe(board_model="TINY"), Recipe(board_model="TINY", use_ai=False, use_compare=False)
    ai_off, compare_off = Recipe(board_model="TINY", use_ai=False), Recipe(board_model="TINY", use_compare=False)
    model, golden, img = tiny_model.model, tiny_model.reference, load_image(ng_board)
    bare = Inspector(off, model, golden).inspect(img)
    again = re_grade(bare, on, None)
    assert (again.checks, again.defects, again.verdict, again.compare, again.anomaly_map) == ([], [], "OK", None, None)
    assert again.notes == [NOT_COMPARED_NOTE, NOT_AI_JUDGED_NOTE] == re_grade(again, on, None).notes
    said = [explain.NOTES[NOT_COMPARED_NOTE], explain.NOTES[NOT_AI_JUDGED_NOTE]]
    assert [s.template for s in explain.explain(again)][1:] == said, "in plain words, after the verdict's sentence"
    assert re_grade(again, off, None).notes == []
    no_model = Inspector(compare_off, None, golden).inspect(img)
    assert re_grade(no_model, on, None).notes == [NOT_COMPARED_NOTE, NO_AI_NOTE], "the comparison's note first"

    full = Inspector(on, model, golden).inspect(img)
    ai = _evidence(full, model)
    assert full.verdict == "NG" and ai.rule == model.meta["threshold_rule"] != "", "the rule it was calibrated by"
    assert re_grade(full, on, ai).verdict == "NG"
    both_off = re_grade(full, off, ai)
    assert (both_off.checks, both_off.notes, both_off.compare, both_off.anomaly_map) == ([], [], None, None)
    as_stored = InspectionResult.from_dict(full.to_dict())  # its record, without the maps
    assert re_grade(as_stored, off, None).checks == [], "no map is needed for a check the recipe turns off"
    for maps_or_evidence_missing in ((full, on, None), (as_stored, on, ai), (as_stored, ai_off, None)):
        with pytest.raises(ValueError, match="needs the maps and the AI evidence"):
            re_grade(*maps_or_evidence_missing)

    unset = Inspector(on, None, None).inspect(img)  # neither a golden board nor an AI model
    assert re_grade(unset, on, None).notes == unset.notes == [NO_GOLDEN_NOTE, NO_AI_NOTE]
    assert re_grade(unset, off, None).notes == Inspector(off, None, None).inspect(img).notes == []
    assert re_grade(unset, ai_off, None).notes == Inspector(ai_off, None, None).inspect(img).notes == [NO_GOLDEN_NOTE]
