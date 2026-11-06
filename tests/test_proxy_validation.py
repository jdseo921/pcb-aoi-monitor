"""The proxy validation tool's own logic (#452), on images drawn here: no dataset runs in CI; the tool's runs on public
data are in docs/tests/2026-11-04-stage1-proxy-validation.md."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest

from aoi import defects
from tools import proxy_validation as pv


def test_452_every_visa_name_maps_to_a_type_of_the_classification_table() -> None:
    assert set(pv.VISA_TYPES.values()) <= set(defects.names())
    with pytest.raises(KeyError):
        _ = pv.Board(Path("a.jpg"), "NG", ("smudge",)).defect_type  # a name not mapped stops the run
    assert pv.Board(Path("a.png"), "NG", ("Missing Component",)).defect_type == "Missing Component"  # drawn boards


def test_452_visa_index_reads_labels_kinds_and_masks(tmp_path: Path) -> None:
    (tmp_path / "pcb9").mkdir()
    rows = "image,label,mask\npcb9/Data/Images/Normal/0000.JPG,normal,\n"
    rows += 'pcb9/Data/Images/Anomaly/000.JPG,"melt,scratch",pcb9/Data/Masks/Anomaly/000.png\n'
    (tmp_path / "pcb9" / "image_anno.csv").write_text(rows, encoding="utf-8")
    ok, ng = pv.visa_index(tmp_path, "pcb9")
    assert (ok.label, ok.kinds, ok.mask, ok.defect_type) == ("OK", (), None, None)
    assert (ng.label, ng.kinds, ng.defect_type) == ("NG", ("melt", "scratch"), "Damaged Component")
    assert ng.mask == tmp_path / "pcb9/Data/Masks/Anomaly/000.png"


def test_452_mask_boxes_are_one_per_blob_and_leave_specks_out() -> None:
    mask = np.zeros((50, 60), np.uint8)
    mask[5:10, 7:20] = 255  # 13 x 5
    mask[30:40, 40:42] = 255  # 2 x 10
    mask[45, 1] = 255  # one pixel: JPEG noise, under MIN_MASK_PX
    assert sorted(pv.mask_boxes(mask)) == [(7, 5, 13, 5), (40, 30, 2, 10)]
    assert pv.mask_boxes(np.dstack([mask] * 3)) == pv.mask_boxes(mask)


def boards(n_ok: int, n_ng: int) -> list[pv.Board]:
    return [pv.Board(Path(f"ok/{i:03d}.jpg"), "OK") for i in range(n_ok)] + [
        pv.Board(Path(f"ng/{i:03d}.jpg"), "NG", ("melt",)) for i in range(n_ng)
    ]


def test_452_pools_are_seeded_disjoint_and_independent_of_input_order() -> None:
    every = boards(30, 4)
    extra, pool, ng = pv.pools(every, seed=3, extra_ok=10)
    assert (len(extra), len(pool), len(ng)) == (10, 20, 4)
    assert not {b.path for b in extra} & {b.path for b in pool}
    assert pv.pools(list(reversed(every)), seed=3, extra_ok=10) == (extra, pool, ng)
    assert pv.pools(every, seed=4, extra_ok=10)[0] != extra
    with pytest.raises(ValueError):
        pv.pools(every, seed=3, extra_ok=30)


def test_452_a_defect_is_found_only_when_a_box_overlaps_its_mask() -> None:
    mask = np.zeros((40, 40), bool)
    mask[10:12, 10:12] = True
    assert pv.found([(0, 0, 5, 5), (11, 11, 1, 1)], mask)
    assert not pv.found([(12, 12, 5, 5)], mask)  # touching the corner from outside is not an overlap
    assert not pv.found([], mask)
    assert pv.overlaps((-5, -5, 16, 16), mask) and not pv.overlaps((-5, -5, 3, 3), mask)


def test_452_tally_counts_misses_false_calls_and_their_upper_bounds() -> None:
    rows = [{"label": "OK", "verdict": v} for v in ["OK"] * 48 + ["WARN", "NG"]]
    rows += [{"label": "NG", "verdict": "NG", "found": True, "kind": "melt"} for _ in range(8)]
    rows += [{"label": "NG", "verdict": "OK", "found": False, "kind": "melt"}]
    rows += [{"label": "NG", "verdict": "WARN", "found": False, "kind": "bent"}]  # flagged, off the mask: missed
    t = pv.tally(rows)
    assert t["good"] == {"boards": 50, "OK": 48, "WARN": 1, "NG": 1} and t["false_calls"] == 2
    assert t["defective"] == {"boards": 10, "OK": 1, "WARN": 1, "NG": 8}
    assert (t["missed"], t["flagged_off_mask"]) == (2, 1)
    assert t["by_kind"]["melt"]["boards"] == 9 and t["by_kind"]["bent"]["missed"] == 1
    assert t["false_calls_upper_95"] == pytest.approx(0.1206, abs=1e-3)  # 2 of 50, one-sided Clopper-Pearson
    assert pv.tally([{"label": "NG", "verdict": "NG", "found": True}] * 30)["missed_upper_95"] == pytest.approx(
        0.0950, abs=1e-3
    )  # 0 of 30: the handover plan's 9.5 %


def test_452_each_photo_change_keeps_or_moves_the_mask_with_the_image() -> None:
    img = np.full((100, 120, 3), 100, np.uint8)
    img[40:60, 50:70] = 200
    mask = np.zeros((100, 120), np.uint8)
    mask[40:60, 50:70] = 255
    for name in pv.CHANGES:
        out, moved = pv.change(name, img, mask)
        assert moved is not None and out.shape[:2] == moved.shape[:2]
    big, big_mask = pv.change("5mp", img, mask)
    assert big.shape[0] * big.shape[1] == pytest.approx(pv.MP5, rel=0.01) and big_mask is not None
    _, shifted = pv.change("shift20", img, mask)
    assert shifted is not None and pv.mask_boxes(shifted) == [(70, 60, 20, 20)]
    edge = np.zeros((100, 120), np.uint8)
    edge[0:10, 50:60] = 255  # a defect at the image's edge does not spread into the border the shift opens
    _, moved_edge = pv.change("shift20", img, edge)
    assert moved_edge is not None and pv.mask_boxes(moved_edge) == [(70, 20, 10, 10)]
    _, turned = pv.change("rot+2", img, edge)
    assert turned is not None and int(turned[60:, :].max()) == 0
    bright, same = pv.change("bright+15", img, mask)
    assert int(bright[0, 0, 0]) == 115 and same is mask
    assert int(pv.change("bright-15", img, None)[0][0, 0, 0]) == 85
    assert all(not np.array_equal(pv.change(n, img, mask)[0], img) for n in ("blur", "jpeg70"))  # not a no-op
    with pytest.raises(ValueError):
        pv.change("sepia", img, mask)


def test_452_result_files_are_checked_against_the_schema(tmp_path: Path) -> None:
    doc = {
        "schema_version": 1,
        "board_id": "b1",
        "board_model": "PCB1",
        "view": "Top",
        "verdict": "NG",
        "time": "2026-11-04T00:00:00+00:00",
        "model_version": "v1.0 (Trial)",
        "recipe_rev": 1,
        "defects": [
            {"no": 1, "type": "Anomaly", "severity": "Major", "score": 1.2, "box": {"x": 1, "y": 2, "w": 3, "h": 4}}
        ],
        "evidence": "png",
        "record_uuid": "0" * 8 + "-0000-0000-0000-" + "0" * 12,
    }
    uid = doc["record_uuid"]
    (tmp_path / f"b1_{uid}.json").write_text(json.dumps(doc), encoding="utf-8")
    (tmp_path / f"b1_{uid}.csv").write_text("b1\n", encoding="utf-8")
    bad = doc | {"verdict": "MAYBE", "view": "", "board_id": ""}  # three problems, one file
    (tmp_path / f"b2_{uid}.json").write_text(json.dumps(bad), encoding="utf-8")
    (tmp_path / "visa.json").write_text("{}", encoding="utf-8")  # the tool's own output is not a result file
    found = pv.check_result_files(tmp_path)
    assert (found["json"], found["invalid"], found["without_csv"]) == (2, 1, [f"b2_{uid}.json"])
    assert len(found["errors"]) == 3


def test_452_out_must_lie_outside_the_repository_and_the_data(tmp_path: Path) -> None:
    with pytest.raises(SystemExit):
        pv.guard(pv.ROOT / "scratch", [])
    with pytest.raises(SystemExit):
        pv.guard(tmp_path / "data" / "out", [tmp_path / "data"])
    pv.guard(tmp_path / "out", [tmp_path / "data"])
