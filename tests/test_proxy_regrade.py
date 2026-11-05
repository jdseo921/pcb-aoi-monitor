"""The scenario tool's what-if grading (#459) on records made up here: no workspace or dataset runs in CI."""

from __future__ import annotations

from tools import proxy_regrade as rg


def test_459_checks_alone_grade_as_the_engine_does_before_its_defect_region_rule() -> None:
    assert rg.by_checks(["OK", "INFO", "WARN"]) == "WARN"
    assert rg.by_checks(["WARN", "NG"]) == "NG"
    assert rg.by_checks(["OK", "INFO"]) == "OK"
    assert rg.label_of("/d/pcb1/Data/Images/Anomaly/000.JPG") == "NG"
    assert rg.label_of("/x/S11-files/ng000_shot.JPG") == "NG"
    assert rg.label_of("/d/pcb1/Data/Images/Normal/0001.JPG") == "OK"


def test_459_regrade_counts_boards_made_warn_by_regions_alone_per_model_and_label() -> None:
    def rec(i: int, path: str, result: str, model: str = "v1.0") -> dict[str, object]:
        return {"id": i, "image_path": path, "result": result, "model_version": model}

    def chk(result: str, ai: float) -> list[dict[str, object]]:
        return [{"metric": "SSIM similarity", "result": result, "value": 0.5},
                {"metric": "AI anomaly score", "result": "OK", "value": ai}]  # fmt: skip

    records = [rec(1, "Normal/1.JPG", "WARN"), rec(2, "Normal/2.JPG", "WARN"), rec(3, "Anomaly/3.JPG", "NG")]
    records.append(rec(4, "Normal/4.JPG", "OK", "v1.1"))
    checks = {1: chk("OK", 2.0), 2: chk("WARN", 3.0), 3: chk("NG", 9.0), 4: chk("OK", 1.0)}
    got = rg.regrade(records, checks)
    good = got["v1.0"]["OK"]
    assert good["stored"] == {"WARN": 2} and good["by_checks"] == {"OK": 1, "WARN": 1}
    assert good["warn_by_regions_alone"] == 1
    assert good["ai"] == {"p5": 2.0, "p50": 3.0, "p95": 3.0}
    assert got["v1.0"]["NG"]["by_checks"] == {"NG": 1} and got["v1.1"]["OK"]["stored"] == {"OK": 1}
