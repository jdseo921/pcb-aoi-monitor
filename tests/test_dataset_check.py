"""tools/dataset_check.py on tiny datasets laid out as DeepPCB and PKU-Market-PCB are (plan stage S30, REQ-INSP-014):
what it counts, that it never changes a source file, and that its output stays out of the repository and datasets."""

from __future__ import annotations

import json
import random
from pathlib import Path

import cv2
import numpy as np
import pytest

from tools import dataset_check as dc
from tools.make_synthetic_dataset import draw_board

BOX = (300, 200, 30, 24)  # x, y, w, h of the defect drawn on each defective board


def _defective(good: np.ndarray) -> np.ndarray:
    bad = good.copy()
    x, y, w, h = BOX
    cv2.rectangle(bad, (x, y), (x + w - 1, y + h - 1), (0, 0, 0), -1)
    return bad


def _deeppcb(root: Path, boards: int = 3) -> Path:
    data = root / "PCBData"
    folder, notes = data / "groupA" / "A", data / "groupA" / "A_not"
    folder.mkdir(parents=True)
    notes.mkdir()
    lines = []
    for i in range(boards):
        good = draw_board(random.Random(i))
        cv2.circle(good, (60 + 20 * i, 420), 6, (255, 255, 255), -1)  # each board its own, as no two templates match
        cv2.imwrite(str(folder / f"A{i:03d}_temp.jpg"), good)
        cv2.imwrite(str(folder / f"A{i:03d}_test.jpg"), _defective(good))
        x, y, w, h = BOX
        (notes / f"A{i:03d}.txt").write_text(f"{x} {y} {x + w} {y + h} 2\n", encoding="utf-8")
        lines.append(f"groupA/A/A{i:03d}.jpg groupA/A_not/A{i:03d}.txt")
    (data / "test.txt").write_text(lines[0] + "\n", encoding="utf-8")
    (data / "trainval.txt").write_text("\n".join(lines[1:]) + "\n", encoding="utf-8")
    return data


def _pku(root: Path) -> Path:
    data = root / "PCB_DATASET"
    for sub in ("PCB_USED", "images/Short", "Annotations/Short", "rotation/Short_rotation"):
        (data / sub).mkdir(parents=True)
    good = draw_board(random.Random(7))
    cv2.imwrite(str(data / "PCB_USED" / "01.JPG"), good)
    cv2.imwrite(str(data / "images" / "Short" / "01_short_01.jpg"), _defective(good))
    cv2.imwrite(str(data / "rotation" / "Short_rotation" / "01_short_01.jpg"), _defective(good))
    x, y, w, h = BOX
    box = f"<bndbox><xmin>{x}</xmin><ymin>{y}</ymin><xmax>{x + w}</xmax><ymax>{y + h}</ymax></bndbox>"
    xml = f"<annotation><object><name>short</name>{box}</object></annotation>"
    (data / "Annotations" / "Short" / "01_short_01.xml").write_text(xml, encoding="utf-8")
    return data


def _files(root: Path) -> dict[str, bytes]:
    return {str(p): p.read_bytes() for p in sorted(root.rglob("*")) if p.is_file()}


def test_req_insp_014_counts_each_labelled_box_found_and_leaves_the_sources_unchanged(tmp_path: Path) -> None:
    deeppcb, pku = _deeppcb(tmp_path / "d"), _pku(tmp_path / "p")
    before = {**_files(deeppcb), **_files(pku)}
    out = tmp_path / "out"
    assert dc.main(["--out", str(out), "--deeppcb", str(deeppcb), "--pku", str(pku)]) == 0
    results = json.loads((out / "results.json").read_text(encoding="utf-8"))
    for name, kind in (("deeppcb", "short"), ("pku", "short")):
        golden = results[name]["golden"]
        assert golden["boards"] == 1 and golden["verdicts"] == {"NG": 1}, (name, golden)
        assert golden["by_type"][kind]["found"] == 1 and golden["boxes_missed"] == 0, (name, golden)
        assert golden["smallest_box_found_px"] == [BOX[2], BOX[3]]
    assert results["sources_unchanged"] is True and results["settings"]["min_defect_area_px"] == 40  # the default
    assert {"threads", "env", "numpy", "opencv", "torch"} <= results[
        "machine"
    ].keys()  # what the record cites, recorded
    assert {**_files(deeppcb), **_files(pku)} == before  # nothing written into either dataset
    rows = (out / "manifest.csv").read_text(encoding="utf-8").splitlines()
    assert rows[0] == "file,sha256" and len(rows) == 1 + 4  # one DeepPCB pair, one PKU pair; rotation/ is left out
    assert "not validated accuracy" in (out / "summary.md").read_text(encoding="utf-8")


def test_req_insp_014_a_source_file_the_run_changes_is_reported(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The files are hashed before the checks read them, so a change made while they run is caught: hashed only after
    the checks, the run reported its own change as none."""
    deeppcb = _deeppcb(tmp_path / "d")
    check = dc.golden_check

    def changing(items: list[dc.Item], min_area: int) -> dict[str, object]:
        with open(items[0].good, "ab") as f:
            f.write(b"x")
        return check(items, min_area)

    monkeypatch.setattr(dc, "golden_check", changing)
    out = tmp_path / "out"
    assert dc.main(["--out", str(out), "--deeppcb", str(deeppcb)]) == 1
    results = json.loads((out / "results.json").read_text(encoding="utf-8"))
    assert results["sources_unchanged"] is False


def test_req_insp_014_min_area_judges_with_another_minimum_defect_area(tmp_path: Path) -> None:
    """--min-area runs the comparison again with only the Minimum defect area changed, as ADR 0008 asks of the check on
    customer photos: above the drawn defect's area, its box is missed."""
    deeppcb = _deeppcb(tmp_path / "d")
    out = tmp_path / "out"
    area = BOX[2] * BOX[3] + 1
    assert dc.main(["--out", str(out), "--deeppcb", str(deeppcb), "--min-area", str(area)]) == 0
    results = json.loads((out / "results.json").read_text(encoding="utf-8"))
    assert results["settings"]["min_defect_area_px"] == area and results["arguments"]["min_area"] == area
    assert results["deeppcb"]["golden"]["boxes_missed"] == 1
    assert f"default except Minimum defect area {area} px" in (out / "summary.md").read_text(encoding="utf-8")


@pytest.mark.parametrize("area", ["0", "-5"])
def test_req_insp_014_min_area_under_one_px_is_refused(tmp_path: Path, area: str) -> None:
    deeppcb = _deeppcb(tmp_path / "d")
    out = tmp_path / "out"
    with pytest.raises(SystemExit, match="1 px or more"):
        dc.main(["--out", str(out), "--deeppcb", str(deeppcb), "--min-area", area])
    assert not out.exists()


def test_req_insp_014_a_box_no_region_reaches_is_missed() -> None:
    box = (100, 100, 10, 10, "spur")
    assert dc.found(box, [(115, 100, 5, 5)])  # within MARGIN of the box
    assert not dc.found(box, [(100 + 10 + dc.MARGIN, 100, 5, 5)])


@pytest.mark.parametrize("inside", ["repo", "dataset"])
def test_req_insp_014_output_inside_the_repository_or_a_dataset_is_refused(tmp_path: Path, inside: str) -> None:
    deeppcb = _deeppcb(tmp_path / "d")
    out = dc.ROOT / "dataset-check-out" if inside == "repo" else deeppcb / "out"
    with pytest.raises(SystemExit, match="outside"):
        dc.main(["--out", str(out), "--deeppcb", str(deeppcb)])
    assert not out.exists()


def test_req_insp_014_upper_bound_of_a_rate() -> None:
    assert dc.upper_95(0, 10) == pytest.approx(1 - 0.05 ** (1 / 10), abs=1e-6)
    assert dc.upper_95(0, 500) == pytest.approx(1 - 0.05 ** (1 / 500), abs=1e-6)
    assert dc.upper_95(3, 100) == pytest.approx(0.075711, abs=1e-5)  # Beta(4, 97) at 0.95, as SciPy gives it
    assert dc.upper_95(5, 5) == 1.0 and dc.upper_95(0, 0) == 1.0


def test_req_trn_007_peak_memory_is_read() -> None:
    """Windows CI runs this too: there the read failed, and the summary said 0.0 MB, until the handle had its type."""
    peak = dc.peak_memory_mb()
    assert peak is not None and peak > 0


def test_req_trn_007_summary_says_when_peak_memory_was_not_read() -> None:
    r = {"when_utc": "t", "note": "n", "machine": {}, "settings": {"recipe": "r"}, "arguments": []}
    assert "Peak memory not read;" in dc.summary({**r, "peak_memory_mb": None, "sources_unchanged": True})
    assert "Peak memory 12.5 MB;" in dc.summary({**r, "peak_memory_mb": 12.5, "sources_unchanged": True})


def test_req_insp_014_ai_model_trained_per_group_and_scored_on_the_test_split(tmp_path: Path) -> None:
    deeppcb = _deeppcb(tmp_path / "d", boards=4)
    out = tmp_path / "out"
    args = ["--out", str(out), "--deeppcb", str(deeppcb), "--ai", "--epochs", "1", "--steps", "1", "--size", "64"]
    assert dc.main(args) == 0
    ai = json.loads((out / "results.json").read_text(encoding="utf-8"))["deeppcb"]["ai"]
    assert ai["ok"] == 1 and ai["ng"] == 1  # the test split's template and its defective board
    assert ai["groups"]["groupA"]["ok_trained"] == 3 and ai["groups"]["groupA"]["ng_calibrated"] == 0
    assert ai["train_s"]["n"] == 1 and ai["ms"]["n"] == 2


def test_req_trn_018_tune_chooses_the_comparisons_thresholds_on_pku(tmp_path: Path) -> None:
    """--tune trains the Pixel difference and Minimum defect area on PKU-Market-PCB's photos not held out and counts
    the held-out ones at the chosen pair and at the default; with none held out, those counts are zero."""
    pku = _pku(tmp_path / "p")
    out = tmp_path / "out"
    assert dc.main(["--out", str(out), "--pku", str(pku), "--tune", "--held-out", "0"]) == 0
    tune = json.loads((out / "results.json").read_text(encoding="utf-8"))["pku"]["tune"]
    assert tune["boards"] == {"train": 1, "held_out": 0}
    assert tune["train"]["chosen"]["found"] == 1 and tune["train"]["chosen"]["false_windows"] == 0
    assert tune["held_out"]["chosen"]["defects"] == 0
    assert tune["held_out_by"].startswith("a seeded share")
    assert "pku comparison thresholds trained" in (out / "summary.md").read_text(encoding="utf-8")


def test_req_trn_018_tune_on_deeppcb_holds_out_the_datasets_test_split(tmp_path: Path) -> None:
    """--tune with --deeppcb chooses the pair on the trainval split and counts the test split at the chosen pair and
    at the default, with no seeded share: the dataset's authors drew the split."""
    deeppcb = _deeppcb(tmp_path / "d", boards=4)
    out = tmp_path / "out"
    assert dc.main(["--out", str(out), "--deeppcb", str(deeppcb), "--tune"]) == 0
    tune = json.loads((out / "results.json").read_text(encoding="utf-8"))["deeppcb"]["tune"]
    assert tune["boards"] == {"train": 3, "held_out": 1} and tune["held_out_by"].startswith("the dataset's test split")
    assert tune["train"]["chosen"]["found"] == 3 and tune["held_out"]["chosen"]["found"] == 1
    assert tune["held_out"]["chosen"]["defects"] == 1 and tune["held_out"]["chosen"]["false_windows"] == 0
    assert "deeppcb comparison thresholds trained" in (out / "summary.md").read_text(encoding="utf-8")


def test_req_trn_018_held_out_photos_are_a_seeded_share_of_each_board_and_type(tmp_path: Path) -> None:
    items = [
        dc.Item("PKU-Market-PCB", board, tmp_path / kind / f"{board}_{i}.jpg", tmp_path / f"{board}.JPG")
        for board in ("01", "04")
        for kind in ("Short", "Spur")
        for i in range(10)
    ]
    test = dc.held_out(items, 0.3, 0)
    assert len(test) == 12 and test == dc.held_out(items, 0.3, 0)
    assert all(
        sum(p.parent.name == k and p.stem[:2] == b for p in test) == 3 for b in ("01", "04") for k in ("Short", "Spur")
    )
