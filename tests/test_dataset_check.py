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
    assert results["sources_unchanged"] is True
    assert {**_files(deeppcb), **_files(pku)} == before  # nothing written into either dataset
    rows = (out / "manifest.csv").read_text(encoding="utf-8").splitlines()
    assert rows[0] == "file,sha256" and len(rows) == 1 + 4  # one DeepPCB pair, one PKU pair; rotation/ is left out
    assert "not validated accuracy" in (out / "summary.md").read_text(encoding="utf-8")


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


def test_req_insp_014_ai_model_trained_per_group_and_scored_on_the_test_split(tmp_path: Path) -> None:
    deeppcb = _deeppcb(tmp_path / "d", boards=4)
    out = tmp_path / "out"
    args = ["--out", str(out), "--deeppcb", str(deeppcb), "--ai", "--epochs", "1", "--steps", "1", "--size", "64"]
    assert dc.main(args) == 0
    ai = json.loads((out / "results.json").read_text(encoding="utf-8"))["deeppcb"]["ai"]
    assert ai["ok"] == 1 and ai["ng"] == 1  # the test split's template and its defective board
    assert ai["groups"]["groupA"]["ok_trained"] == 3 and ai["groups"]["groupA"]["ng_calibrated"] == 0
    assert ai["train_s"]["n"] == 1 and ai["ms"]["n"] == 2
