"""Time a base tree's and a head tree's Inspector.inspect on one machine in one run, and fail on a slowdown over 10 %
(stage S08, REQ-INSP-007 part; Engineering standard, "Measured in CI"). tests/perf/README.md has the measurements.

    python tools/perf_compare.py --base <folder or git ref> --head .

It times the regression set's 40 boards at 0.3 MP and 5 MP (default recipe, no AI model) and fails when the head's
median or 95th percentile at either size is over 1.10 times the base's. Exit codes: 0 within, 1 slower, 2 a usage
error, 3 the trees cannot be compared (a tree cannot run the harness, as after an Inspector API change).

Each tree runs in a process of its own with only its own aoi imported, under this one harness, on the same boards.
Noise on a shared runner only adds time, comes in bursts and differs from process to process, so: --rounds rounds
per tree, a fresh process each, in the order base, head, head, base, ...; each round shuffles the boards its own way,
the same for both trees; each board keeps its fastest time over the rounds (and at 0.3 MP over 3 passes per round)
before the median and the 95th percentile are taken (a real slowdown is in every one, a burst rarely is); and a
failure is judged again over twice the rounds before it counts. These numbers are never the product's speed: a
runner is not the reference PC and the boards are drawings.
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import random
import subprocess
import sys
import tempfile
import traceback
from datetime import UTC, datetime
from pathlib import Path
from time import perf_counter
from typing import Any

import cv2
import numpy as np

ALLOWED = 1.10  # the head may take at most 10 % longer than the base
SIZES: dict[str, tuple[int, int]] = {"0.3MP": (640, 480), "5MP": (2592, 1944)}  # width, height
PASSES = {"0.3MP": 3, "5MP": 1}  # passes per round; one 0.3 MP pass lasts about 1.5 s, short enough for a burst to skew
STATS = {"median_ms": "median", "p95_ms": "p95"}
EXIT_SLOWER, EXIT_USAGE, EXIT_HARNESS = 1, 2, 3
ROOT = Path(__file__).resolve().parents[1]  # the harness's repository: its regression set gives the boards


def cpu_model() -> str:
    if platform.system() == "Linux":
        for line in Path("/proc/cpuinfo").read_text(encoding="utf-8", errors="replace").splitlines():
            if line.lower().startswith("model name"):
                return line.split(":", 1)[1].strip()
    return platform.processor() or "unknown"


def fingerprint() -> str:
    return f"{platform.system()}-{platform.machine()}-{os.cpu_count()}cpu-{cpu_model()}"


def machine() -> dict[str, object]:
    versions = {"python": sys.version.split()[0], "opencv": cv2.__version__, "numpy": np.__version__}
    return {"fingerprint": fingerprint(), "platform": platform.platform(), "cpu_count": os.cpu_count(), **versions}


def stats(times: list[float]) -> dict[str, float]:
    return {"median_ms": round(float(np.median(times)), 1), "p95_ms": round(float(np.percentile(times, 95)), 1)}


def time_inspect(inspector: Any, images: list[np.ndarray]) -> list[float]:
    """Milliseconds of `inspector.inspect` per board, after one untimed warm-up board (first-call costs)."""
    inspector.inspect(images[0])
    times = []
    for img in images:
        t0 = perf_counter()
        inspector.inspect(img)
        times.append((perf_counter() - t0) * 1000)
    return times


def gate(base: dict[str, dict[str, float]], head: dict[str, dict[str, float]], allowed: float = ALLOWED) -> list[str]:
    """One line per size and statistic at which the head takes over `allowed` times the base: none passes, and so
    does exactly `allowed` times (the 1e-12 absorbs the rounding of the product)."""
    return [
        f"{size} {name}: head {head[size][key]} ms is {head[size][key] / base[size][key]:.3f} x base "
        f"{base[size][key]} ms, over {allowed:.2f}"
        for size in base
        for key, name in STATS.items()
        if head[size][key] > base[size][key] * allowed * (1 + 1e-12)
    ]


def run_worker(tree: Path, boards: Path, sizes: list[str], count: int, seed: int, out: Path) -> int:
    """Time `tree`'s Inspector in this process, which imports that tree's aoi and no other, in the board order `seed`
    gives: each round its own, the same for both trees, so a disturbance that recurs does not hit the same boards."""
    sys.path.insert(0, str(tree))
    try:
        import aoi.core.inspector as engine
        from aoi.core.recipe import Recipe

        if not Path(str(engine.__file__)).resolve().is_relative_to(tree.resolve()):
            raise ImportError(f"aoi came from {engine.__file__}, not from {tree}")
        manifest = json.loads((boards / "manifest.json").read_text(encoding="utf-8"))
        names = [b["name"] for b in manifest if b["label"] == "OK"][: count - count // 2]
        names += [b["name"] for b in manifest if b["label"] == "NG"][: count // 2]
        originals = [cv2.imread(str(boards / n)) for n in names]
        golden = cv2.imread(str(boards / "golden.png"))
        order = list(range(len(names)))
        random.Random(seed).shuffle(order)
        ms = {}
        for label in sizes:
            ref, *images = [cv2.resize(i, SIZES[label], interpolation=cv2.INTER_CUBIC) for i in [golden, *originals]]
            recipe = Recipe(board_model="REGRESSION", use_ai=False)  # the regression set's recipe
            inspector = engine.Inspector(recipe, model=None, reference=ref)
            times = np.min([time_inspect(inspector, [images[i] for i in order]) for _ in range(PASSES[label])], axis=0)
            ms[label] = [float(t) for _, t in sorted(zip(order, times, strict=True))]
    except Exception:
        traceback.print_exc()
        return EXIT_HARNESS
    out.write_text(json.dumps({"aoi": str(engine.__file__), "ms": ms}), encoding="utf-8")
    return 0


def run_tree(side: str, tree: Path, args: list[str], out: Path) -> dict[str, list[float]]:
    cmd = [sys.executable, str(Path(__file__).resolve()), "--worker", str(tree.resolve()), *args, "--out", str(out)]
    proc = subprocess.run(cmd, cwd=tree, capture_output=True, text=True)
    if proc.returncode != 0:
        last = (proc.stderr.strip().splitlines() or [f"exit code {proc.returncode}"])[-1]
        raise RuntimeError(f"the {side} tree {tree} cannot run the harness: {last}")
    return dict(json.loads(out.read_text(encoding="utf-8"))["ms"])


def base_tree(base: str, scratch: Path) -> Path:
    """`base` when it is a folder; otherwise the files of the git ref `base` in this tool's repository."""
    if Path(base).is_dir():
        return Path(base)
    archive = subprocess.run(["git", "-C", str(ROOT), "archive", "--format=tar", base], capture_output=True)
    if archive.returncode != 0:
        print(f"perf: {base} is neither a folder nor a git ref of {ROOT}", file=sys.stderr)
        sys.exit(EXIT_USAGE)
    (scratch / "base").mkdir()
    subprocess.run(["tar", "-xf", "-", "-C", str(scratch / "base")], input=archive.stdout, check=True)
    return scratch / "base"


def fastest(runs: list[dict[str, list[float]]]) -> dict[str, dict[str, float]]:
    """The median and the 95th percentile per size of each board's fastest time over `runs`."""
    return {size: stats(np.min([run[size] for run in runs], axis=0).tolist()) for size in runs[0]}


def report(runs: dict[str, list[dict[str, list[float]]]], count: int) -> list[str]:
    best = {side: fastest(runs[side]) for side in runs}
    print(f"perf: {count} boards per size, each board's fastest over {len(runs['base'])} round(s) per tree")
    for size, by_stat in best["base"].items():
        for key, name in STATS.items():
            b, h = by_stat[key], best["head"][size][key]
            print(f"perf: {size:>5} {name:<6} base {b:8.1f} ms  head {h:8.1f} ms  x{h / b:.3f}")
    return gate(best["base"], best["head"])


def compare(base: str, head: Path, rounds: int, count: int, sizes: list[str], out: Path) -> int:
    runs: dict[str, list[dict[str, list[float]]]] = {"base": [], "head": []}
    print(f"perf: {fingerprint()}; not the reference PC, so never the product's speed")
    with tempfile.TemporaryDirectory() as tmp:
        scratch, maker = Path(tmp), ROOT / "tests" / "regression" / "make_regression_set.py"
        boards = scratch / "boards"
        args = ["--boards-dir", str(boards), "--sizes", ",".join(sizes), "--boards", str(count)]
        try:
            trees = {"base": base_tree(base, scratch), "head": head}
            subprocess.run([sys.executable, str(maker), "--out", str(boards)], check=True, capture_output=True)
            for stage in range(2):  # a failure after `rounds` rounds is confirmed, or cleared, by as many again
                for r in range(stage * rounds, (stage + 1) * rounds):
                    for side in ("base", "head") if r % 2 == 0 else ("head", "base"):
                        runs[side].append(run_tree(side, trees[side], [*args, "--round", str(r)], scratch / "t.json"))
                failures = report(runs, count)
                if not failures or stage:
                    break
                print(f"perf: over {ALLOWED:.2f} x after {rounds} round(s); as many again confirm it or clear it")
        except (RuntimeError, subprocess.CalledProcessError) as e:
            print(f"perf: {e}")
            print("perf: the gate cannot compare the trees and fails (exit 3); tests/perf/README.md says what to do")
            return EXIT_HARNESS
    print("\n".join(f"perf: SLOWER {f}" for f in failures) or f"perf: PASS: within {ALLOWED:.2f} x the base")
    record = {"recorded": datetime.now(UTC).isoformat(timespec="seconds"), "machine": machine(), "allowed": ALLOWED}
    record |= {"base": base, "head": str(head), "boards": count, "failures": failures}
    record |= {f"{side}_ms": fastest(runs[side]) for side in runs} | {"runs": runs}
    out.write_text(json.dumps(record, indent=1), encoding="utf-8")
    return EXIT_SLOWER if failures else 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--base", help="the base: a source folder, or a git ref of this tool's repository")
    ap.add_argument("--head", type=Path, default=Path("."), help="the head source folder (default: .)")
    ap.add_argument("--rounds", type=int, default=3, help="timed runs of each tree, interleaved (default: 3)")
    ap.add_argument("--boards", type=int, default=40, help="regression boards per size, half OK (default: all 40)")
    ap.add_argument("--sizes", default=",".join(SIZES), help=f"comma-separated, of {', '.join(SIZES)} (default: both)")
    ap.add_argument("--out", type=Path, default=Path("perf-compare.json"), help="the JSON record of the run")
    ap.add_argument("--worker", type=Path, help=argparse.SUPPRESS)  # internal: time one tree in this process
    ap.add_argument("--boards-dir", type=Path, help=argparse.SUPPRESS)
    ap.add_argument("--round", type=int, default=0, help=argparse.SUPPRESS)
    a = ap.parse_args(argv)
    sizes = a.sizes.split(",")
    if a.worker:
        return run_worker(a.worker, a.boards_dir, sizes, a.boards, a.round, a.out)
    if not a.base or not a.head.is_dir() or not set(sizes) <= SIZES.keys() or a.rounds < 1 or not 2 <= a.boards <= 40:
        ap.error("give --base, a --head folder, sizes from 0.3MP and 5MP, --rounds of 1 or more, --boards from 2 to 40")
    return compare(a.base, a.head, a.rounds, a.boards, sizes, a.out)


if __name__ == "__main__":
    sys.exit(main())
