"""The base-vs-head performance gate, tools/perf_compare.py (stage S08, REQ-INSP-007 part): exactly 10 % slower
passes and 0.1 ms more fails, at each size and statistic; run end to end on 4 boards at 0.3 MP (seconds; CI's job
"Performance (base vs head)" runs the real comparison), it fails a copy of this tree whose Inspector.inspect sleeps
50 ms per board, naming the size and statistic, and fails with its own exit code when a tree's Inspector API changed.
"""

from __future__ import annotations

import copy
import subprocess
import sys
from pathlib import Path

import pytest

from tools.perf_compare import EXIT_HARNESS, EXIT_SLOWER, SIZES, STATS, gate

ROOT = Path(__file__).resolve().parents[2]
BASE = {"0.3MP": {"median_ms": 37.0, "p95_ms": 45.0}, "5MP": {"median_ms": 475.0, "p95_ms": 801.0}}
INSPECT = "    def inspect(self, img: np.ndarray) -> InspectionResult:\n"


@pytest.mark.parametrize("size", SIZES)
@pytest.mark.parametrize("key", STATS)
def test_req_insp_007_gate_passes_10_percent_and_fails_over(size: str, key: str) -> None:
    head = copy.deepcopy(BASE)
    head[size][key] = round(BASE[size][key] * 1.10, 1)  # 40.7, 49.5, 522.5 or 881.1 ms: exactly 10 % slower
    assert gate(BASE, head) == []
    head[size][key] = round(head[size][key] + 0.1, 1)  # the step every timing is rounded to
    (failure,) = gate(BASE, head)
    assert failure.startswith(f"{size} {STATS[key]}: head {head[size][key]} ms is 1.10")
    assert gate(BASE, BASE) == []


def tree_with(tmp_path: Path, old: str, new: str) -> Path:
    """A copy of this tree, made as CI checks one out, with `old` replaced by `new` in aoi/core/inspector.py."""
    (tree := tmp_path / "tree").mkdir()
    excludes = [f"--exclude={p}" for p in (".git", "__pycache__", ".venv", "*_cache", "perf*.json")]
    pack = subprocess.run(["tar", *excludes, "-cf", "-", "."], cwd=ROOT, capture_output=True, check=True)
    subprocess.run(["tar", "-xf", "-"], cwd=tree, input=pack.stdout, check=True)
    source = tree / "aoi" / "core" / "inspector.py"
    text = source.read_text(encoding="utf-8")
    assert text.count(old) == 1, "the injection point moved; update this test"
    source.write_text(text.replace(old, new), encoding="utf-8")
    return tree


def run_gate(tmp_path: Path, base: Path, head: Path) -> subprocess.CompletedProcess[str]:
    cmd = [sys.executable, str(ROOT / "tools" / "perf_compare.py"), "--base", str(base), "--head", str(head)]
    cmd += ["--sizes", "0.3MP", "--boards", "4", "--rounds", "1", "--out", str(tmp_path / "perf-compare.json")]
    return subprocess.run(cmd, capture_output=True, text=True, timeout=120)


def test_req_insp_007_gate_fails_an_injected_slowdown(tmp_path: Path) -> None:
    slow = tree_with(tmp_path, INSPECT, INSPECT + "        time.sleep(0.05)  # injected: 50 ms per board\n")
    run = run_gate(tmp_path, ROOT, slow)
    assert run.returncode == EXIT_SLOWER, run.stdout + run.stderr
    assert "perf: SLOWER 0.3MP median: head" in run.stdout and "perf: SLOWER 0.3MP p95: head" in run.stdout


def test_req_insp_007_gate_fails_when_a_tree_cannot_run_the_harness(tmp_path: Path) -> None:
    changed = tree_with(tmp_path, INSPECT, INSPECT.replace("img: np.ndarray", "img: np.ndarray, view: str"))
    run = run_gate(tmp_path, changed, ROOT)
    assert run.returncode == EXIT_HARNESS, run.stdout + run.stderr
    assert f"perf: the base tree {changed} cannot run the harness: TypeError" in run.stdout
