"""REQ-CMP-005: a result is judged again with other thresholds from the evidence it holds, without aligning, comparing
or running the AI model (S28a): the engine (`Inspector.judge`, `re_grade`) and the maps stored with a result, which
hold that evidence within one step (`aoi/core/maps.py`)."""

from __future__ import annotations

import copy
import json
from dataclasses import replace
from pathlib import Path

import numpy as np
import pytest
from torch import nn

from aoi.core import anomaly, explain, inspector, maps
from aoi.core.imaging import load_image, save_image
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
        {"anomaly_threshold": 50.0, "diff_threshold": 30, "min_defect_area": 20, "ssim_min": 0.9,
         "max_diff_regions": 1},  # an AI threshold far above the calibrated one, so a grade changes on any platform
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


def _as_stored(live: InspectionResult, pixel_threshold: float, folder: Path) -> InspectionResult:
    """`live` as the save stores it and Compare reads it back: its JSON, and its maps through their files."""
    stored = InspectionResult.from_dict(json.loads(json.dumps(live.to_dict())))
    return maps.load_maps(stored, *maps.save_maps(live, folder / "board", pixel_threshold=pixel_threshold))


def _unread(res: InspectionResult) -> InspectionResult:
    """`res` without the values read from its AI map: its AI defects' scores."""
    return replace(res, defects=[replace(d, score=0.0) if d.source == "ai" else d for d in res.defects])


def _assert_close(got: InspectionResult, want: InspectionResult, what: str) -> None:
    """As `_assert_same`, but an AI defect's score (its peak on the AI map over the AI threshold) may differ by one step
    of the stored map at that value, over the AI threshold; an ROI judged before keeps its value exactly."""
    thr = next((c.threshold for c in want.checks if c.source == "AI"), 1.0)
    pairs = [(g.score, w.score) for g, w in zip(got.defects, want.defects, strict=True) if g.source == "ai"]
    for g, w in pairs:
        assert abs(g - w) <= max(1 / maps.AI_SCALE, w * thr / maps.AI_LOG_STEPS) * 1.01 / thr, (what, g, w)
    _assert_same(_unread(got), _unread(want), what)


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


def test_req_cmp_005_a_stored_result_is_judged_again_as_the_live_one(
    tiny_model: TrainedModel, synthetic_dataset: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Every test board, stored as the save stores it and read back (its JSON, its two map files), judged again with the
    recipe and with each set of other thresholds: as the live result is, every check, defect box and verdict, but for an
    AI defect's score, within one step of the stored map over the AI threshold."""
    recipe = Recipe(board_model="TINY", rois=[ROI("R1", "Presence", 200, 150, 160, 120, ai_score=0.8)])
    model = tiny_model.model
    for path in sorted(synthetic_dataset.glob("test/*/*.png")):
        live = Inspector(recipe, model, tiny_model.reference).inspect(load_image(path))
        stored = _as_stored(live, model.pixel_threshold, tmp_path)
        ai = _evidence(stored, model)
        with monkeypatch.context() as m:
            _refuse_the_engine(m)
            for thresholds in [recipe, *_what_if(recipe)]:
                _assert_close(re_grade(stored, thresholds, ai), re_grade(live, thresholds, ai), path.name)


def test_req_cmp_005_a_stored_ai_map_holds_scores_far_above_65_sigma(tmp_path: Path) -> None:
    """An AI score of 100 sigma in an ROI, above the 65.535 sigma a format 1 file held (S25c to S27): stored, then
    judged again with an AI threshold of 50, the ROI is NG, as on the live map, and its value and the AI defect's
    score are within one step."""
    amap = np.zeros((300, 400), np.float32)
    amap[150:158, 200:208] = 100.0  # 64 px: an AI defect, too few to raise the AI score
    recipe = Recipe(board_model="X", use_compare=False, rois=[ROI("R1", "Presence", 190, 140, 30, 30, ai_score=1.5)])
    high = copy.deepcopy(recipe)
    high.anomaly_threshold = 50.0
    live = InspectionResult("OK", 0.0, image=np.zeros((300, 400, 3), np.uint8), anomaly_map=amap)
    ai = AiEvidence(float(np.percentile(amap, 99.9)), 4.0, 2.0, "test")
    Inspector(recipe).judge(live, ai)
    stored = _as_stored(live, ai.pixel_threshold, tmp_path)
    for thresholds in (recipe, high):
        _assert_close(re_grade(stored, thresholds, ai), re_grade(live, thresholds, ai), str(thresholds))
    again = re_grade(stored, high, ai)
    assert ([c.verdict for c in again.checks], again.verdict, len(again.defects)) == (["OK", "NG"], "NG", 1)
    assert isinstance(anomaly.ConvAutoencoder().decoder[-1], nn.Sigmoid), "errors of at most 1, so scores below 1000"
    assert 1 / anomaly.SPREAD_FLOOR < maps.AI_MAX, "a stored map holds every score a model this app trains gives"


def test_req_cmp_005_an_roi_keeps_the_peak_it_was_judged_by(tmp_path: Path) -> None:
    """An ROI's peak of 1.9995 sigma, 0.7998 of the AI threshold 2.5 and so WARN under the ROI's 0.8, stores as 2.000
    sigma, the nearest step, which the ROI would read as NG: judged again, the ROI keeps the peak it was judged by, so
    its value and the verdict are the live ones. An ROI moved, renamed or added since reads the stored map, a step from
    the live value."""
    amap = np.zeros((300, 400), np.float32)
    amap[150:158, 200:208] = 1.9995
    recipe = Recipe(board_model="X", use_compare=False, rois=[ROI("R1", "Presence", 190, 140, 30, 30, ai_score=0.8)])
    live = InspectionResult("OK", 0.0, image=np.zeros((300, 400, 3), np.uint8), anomaly_map=amap)
    ai = AiEvidence(float(np.percentile(amap, 99.9)), 2.5, 1.0, "test")
    Inspector(recipe).judge(live, ai)
    stored = _as_stored(live, ai.pixel_threshold, tmp_path)
    assert stored.anomaly_map is not None and float(stored.anomaly_map.max()) == pytest.approx(2.0, abs=1e-6)
    assert ([c.verdict for c in live.checks], live.verdict) == (["OK", "WARN"], "WARN")
    again = re_grade(stored, recipe, ai)
    _assert_close(again, live, "the ROI as judged")
    moved = copy.deepcopy(recipe)
    moved.rois = [ROI("R1", "Presence", 191, 140, 30, 30, ai_score=0.8), ROI("R2", "Polarity", 205, 152, 9, 9)]
    moved.rois.append(ROI("R3", "Presence", 190, 140, 30, 30, ai_score=0.8))  # R1's box under another name
    got, want = re_grade(stored, moved, ai), re_grade(live, moved, ai)
    assert [c.value for c in got.checks[1:]] == pytest.approx([2.0 / 2.5] * 3), "read from the stored map"
    assert [c.value for c in want.checks[1:]] == pytest.approx([1.9995 / 2.5] * 3), "and from the live one"


def test_req_cmp_005_the_stored_ai_map_keeps_each_pixel_on_its_side_of_the_pixel_threshold(tmp_path: Path) -> None:
    """Rounding to the stored steps could take a value across the AI model's pixel threshold, and judging the stored
    map again would then find an AI defect a pixel wider or narrower than the one judged: the encoder keeps every value
    on its side, for thresholds float32 holds and does not, below and above the log scale's knee, each within one step
    (0.001 sigma, then 1/8192 of the value). The codes rise with the value and read back as the format fixes them;
    from AI_MAX up, the top code. A format 1 file (S25c to S27) reads back in 0.001 sigma steps."""
    for threshold in (0.0001, 0.1, 0.5, 1.234, 1.2344, 2.001, 7.25, 40.0, 1000.0):
        step = max(1 / maps.AI_SCALE, threshold / maps.AI_LOG_STEPS) * 1.01
        amap = np.linspace(max(threshold - 3 * step, 0), threshold + 3 * step, 6001, dtype=np.float32)[np.newaxis]
        back = maps.decode_ai(maps.encode_ai(amap, threshold))
        assert np.array_equal(back >= threshold, amap >= threshold), threshold
        assert float(np.abs(back - amap).max()) <= step, threshold
        plain = maps.decode_ai(maps.encode_ai(amap))  # without the threshold: the nearest code
        assert float(np.abs(plain - amap).max()) <= step / 2, threshold
        assert not np.array_equal(plain >= threshold, amap >= threshold), "the grid crosses the threshold"
    assert (np.diff(maps.AI_VALUES) > 0).all()
    pinned = maps.decode_ai(np.array([1235, 32767, 32768, 40960, 49152, 65535]))  # the format, as files hold it
    assert pinned.tolist() == pytest.approx([1.235, 32.767, 32.768, 89.072659, 242.124590, 1788.853801], rel=1e-6)
    assert maps.encode_ai(np.array([[maps.AI_MAX, 2000.0, np.inf]], np.float32), 2.0).tolist() == [[65535] * 3]
    for outside in (0.0, 2000.0):  # a pixel threshold no code lies on either side of: the nearest codes, unmoved
        assert maps.encode_ai(np.array([[np.nan, 0.0, 1.0]], np.float32), outside).tolist() == [[0, 0, 1000]]
    old = tmp_path / ("board" + maps.AI_FILE_V1)
    save_image(old, np.array([[0, 1235, 65535]], np.uint16))
    res = maps.load_maps(InspectionResult("OK", 0.0), None, str(old))
    assert res.anomaly_map is not None and res.anomaly_map[0].tolist() == pytest.approx([0.0, 1.235, 65.535])
