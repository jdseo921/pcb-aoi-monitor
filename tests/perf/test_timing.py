"""Timing of Inspector.inspect over the synthetic regression set at 0.3 MP and 5 MP (stage S08, REQ-INSP-007 part).

Writes perf.json (median and 95th percentile per size, with the machine) and compares the medians with the entry
for the same machine in tests/perf/baseline.json: a slowdown over 10 % fails. A machine without an entry records
only. On any machine the 0.3 MP 95th percentile must stay under 1 s, the REQ-INSP-007 budget, as a smoke test.
CI runners are not the reference PC: these numbers are never quoted as the product's speed
(docs/tests/2026-10-01-resolution-test.md).

    AOI_PERF_BASELINE=update pytest tests/perf      # record this machine's numbers as its baseline
    AOI_PERF_OUT=somewhere/perf.json pytest tests/perf
"""

from __future__ import annotations

import json
import os
import platform
import sys
from datetime import UTC, datetime
from pathlib import Path
from time import perf_counter

import cv2
import numpy as np
import pytest

from aoi.core.inspector import Inspector
from tests.regression import make_regression_set as rs

BASELINE = Path(__file__).with_name("baseline.json")
SLOWDOWN_ALLOWED = 1.10
BUDGET_MS = 1000.0  # REQ-INSP-007: verdict within 1 s, checked at 0.3 MP on every machine
SIZES = {"0.3MP": ((640, 480), rs.N_OK + rs.N_NG), "5MP": ((2592, 1944), 8)}  # 5 MP: 4 OK and 4 NG boards


def cpu_model() -> str:
    if platform.system() == "Linux":
        for line in Path("/proc/cpuinfo").read_text(encoding="utf-8", errors="replace").splitlines():
            if line.lower().startswith("model name"):
                return line.split(":", 1)[1].strip()
    return platform.processor() or "unknown"


def fingerprint() -> str:
    return f"{platform.system()}-{platform.machine()}-{os.cpu_count()}cpu-{cpu_model()}"


def machine() -> dict[str, object]:
    return {
        "fingerprint": fingerprint(),
        "platform": platform.platform(),
        "cpu_count": os.cpu_count(),
        "python": sys.version.split()[0],
        "opencv": cv2.__version__,
        "numpy": np.__version__,
    }


def time_boards(images: list[np.ndarray], golden: np.ndarray) -> dict[str, float]:
    inspector = Inspector(rs.RECIPE, model=None, reference=golden)
    inspector.inspect(images[0])  # warm-up: first-call costs are not the product's speed either
    times = []
    for img in images:
        t0 = perf_counter()
        inspector.inspect(img)
        times.append((perf_counter() - t0) * 1000)
    return {"median_ms": round(float(np.median(times)), 1), "p95_ms": round(float(np.percentile(times, 95)), 1)}


@pytest.fixture(scope="module")
def regression(tmp_path_factory: pytest.TempPathFactory) -> tuple[list[np.ndarray], list[np.ndarray], np.ndarray]:
    out = tmp_path_factory.mktemp("regression")
    boards = rs.generate(out)
    ok = [cv2.imread(str(out / b.name)) for b in boards if b.label == "OK"]
    ng = [cv2.imread(str(out / b.name)) for b in boards if b.label == "NG"]
    return ok, ng, cv2.imread(str(out / "golden.png"))


def test_req_insp_007_inspect_timing_against_the_baseline(regression) -> None:
    ok, ng, golden = regression
    report: dict[str, object] = {"recorded": datetime.now(UTC).isoformat(timespec="seconds"), "machine": machine()}
    for label, ((w, h), count) in SIZES.items():
        half = count // 2
        images = ok[:half] + ng[:half]
        if (w, h) != golden.shape[1::-1]:
            images = [cv2.resize(i, (w, h), interpolation=cv2.INTER_CUBIC) for i in images]
            ref = cv2.resize(golden, (w, h), interpolation=cv2.INTER_CUBIC)
        else:
            ref = golden
        report[label] = {"boards": len(images), **time_boards(images, ref)}
    out = Path(os.environ.get("AOI_PERF_OUT", "perf.json"))
    out.write_text(json.dumps(report, indent=1), encoding="utf-8")
    print(f"\nperf: {out}: " + "; ".join(f"{k} {v}" for k, v in report.items() if k in SIZES))

    baselines = json.loads(BASELINE.read_text(encoding="utf-8")) if BASELINE.exists() else {}
    key = fingerprint()
    if os.environ.get("AOI_PERF_BASELINE") == "update":
        baselines[key] = {k: v for k, v in report.items() if k != "machine"} | {
            "platform": report["machine"]["platform"]
        }
        BASELINE.write_text(json.dumps(baselines, indent=1, sort_keys=True) + "\n", encoding="utf-8")
        pytest.skip(f"baseline recorded for {key}")
    smoke = report["0.3MP"]["p95_ms"]
    assert smoke < BUDGET_MS, f"0.3 MP 95th percentile {smoke} ms is over the {BUDGET_MS:.0f} ms budget"
    if key not in baselines:
        print(f"perf: no baseline for {key}; recorded only")
        return
    for label in SIZES:
        base, now = baselines[key][label]["median_ms"], report[label]["median_ms"]
        assert now <= base * SLOWDOWN_ALLOWED, (
            f"{label}: median {now} ms is over {SLOWDOWN_ALLOWED:.0%} of the baseline {base} ms"
        )
