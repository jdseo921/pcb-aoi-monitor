"""The synthetic regression set (stage S05): 20 OK and 20 NG boards drawn from a fixed seed, and the
verdict and metrics the golden-sample compare step gave each one when expected.json was last baselined.

    python tests/regression/make_regression_set.py --out <folder>       # write the images and manifest.json
    python tests/regression/make_regression_set.py --write-expected     # re-baseline expected.json (README.md)

The images are regenerated from the seed on every machine; neither they nor their hashes are committed,
because PNG bytes differ across OpenCV and zlib versions. test_regression_verdicts.py compares verdicts,
and metrics within the tolerances recorded here. The set pins behaviour so a change that alters a verdict
is seen in review (Engineering standard, "Change control"). It is never accuracy (Customers & Launch,
"Validation and accuracy claims"): the boards are drawings, not photographs.

Each NG board carries one defect of a known type at a known place: `defect_box` is the bounding box, in
golden-board pixels, of everything the defect changed before the simulated capture moved the board.
"""

from __future__ import annotations

import argparse
import json
import random
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:  # run as a script from any folder
    sys.path.insert(0, str(ROOT))

from aoi.core.inspector import InspectionResult, Inspector  # noqa: E402
from aoi.core.recipe import Recipe  # noqa: E402
from tools.make_synthetic_dataset import DEFECTS, capture, draw_board  # noqa: E402

SEED = 1001
N_OK = 20
N_NG = 20
BOARD_MODEL = "REGRESSION"
EXPECTED_PATH = Path(__file__).with_name("expected.json")
# The compare step alone: AI scores depend on trained weights, which differ from machine to machine, so the
# synthetic regression set pins the deterministic path. tests/test_pipeline.py bounds the AI model's behaviour.
RECIPE = Recipe(board_model=BOARD_MODEL, use_ai=False)
# Absolute tolerance per metric: room for last-bit differences between OpenCV builds, no room for a change
# in behaviour. `alignment_method` must match exactly. A blob a few pixels either side of the minimum defect
# area can appear or vanish between builds, hence one region and 30 px of play.
TOLERANCES: dict[str, float] = {
    "ssim": 0.005,
    "changed_pct": 0.02,
    "mean_abs_diff": 0.25,
    "max_diff": 4.0,
    "compare_regions": 1,
    "largest_region_px": 30,
    "alignment_inliers": 40,
}
# How far (px) a reported region may sit from the known defect box and still count as finding it.
HIT_MARGIN = 12


@dataclass(frozen=True)
class Board:
    name: str  # file name under the output folder
    label: str  # OK | NG
    defect_type: str | None
    defect_box: tuple[int, int, int, int] | None  # x, y, w, h in golden-board pixels


def _bounding_box(clean: np.ndarray, drawn: np.ndarray) -> tuple[int, int, int, int]:
    ys, xs = np.nonzero(np.any(clean != drawn, axis=2))
    return int(xs.min()), int(ys.min()), int(xs.max() - xs.min() + 1), int(ys.max() - ys.min() + 1)


def generate(out: Path) -> list[Board]:
    """Write golden.png, the 40 boards and manifest.json under `out`; return the boards in file order."""
    rng = random.Random(SEED)
    out.mkdir(parents=True, exist_ok=True)
    clean = draw_board(rng)  # the drawing uses no randomness without a defect: this is the golden board
    cv2.imwrite(str(out / "golden.png"), clean)
    boards: list[Board] = []
    for i in range(N_OK):
        name = f"ok_{i:02d}.png"
        cv2.imwrite(str(out / name), capture(draw_board(rng), rng))
        boards.append(Board(name, "OK", None, None))
    for i in range(N_NG):
        defect = DEFECTS[i % len(DEFECTS)]
        drawn = draw_board(rng, defect)
        name = f"ng_{i:02d}_{defect.replace(' ', '_').lower()}.png"
        cv2.imwrite(str(out / name), capture(drawn, rng))
        boards.append(Board(name, "NG", defect, _bounding_box(clean, drawn)))
    (out / "manifest.json").write_text(json.dumps([asdict(b) for b in boards], indent=1), encoding="utf-8")
    return boards


def inspect(img: np.ndarray, golden: np.ndarray) -> InspectionResult:
    return Inspector(RECIPE, model=None, reference=golden).inspect(img)


def region_hits(res: InspectionResult, box: tuple[int, int, int, int], margin: int = HIT_MARGIN) -> bool:
    """True when a difference region overlaps the known defect box grown by `margin` pixels."""
    x, y, w, h = box
    x0, y0, x1, y1 = x - margin, y - margin, x + w + margin, y + h + margin
    return (
        any(r.x < x1 and r.x + r.w > x0 and r.y < y1 and r.y + r.h > y0 for r in res.compare.regions)
        if res.compare
        else False
    )


def expected_entry(board: Board, res: InspectionResult) -> dict[str, Any]:
    metrics = (
        {k: (round(v, 4) if isinstance(v, float) else v) for k, v in res.compare.metrics.items()} if res.compare else {}
    )
    entry: dict[str, Any] = {**asdict(board), "verdict": res.verdict, "metrics": metrics}
    if board.defect_box is not None:
        entry["found"] = region_hits(res, board.defect_box)
    return entry


def write_expected(path: Path = EXPECTED_PATH, scratch: Path | None = None) -> dict[str, Any]:
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        out = scratch or Path(tmp)
        boards = generate(out)
        golden = cv2.imread(str(out / "golden.png"))
        entries = [expected_entry(b, inspect(cv2.imread(str(out / b.name)), golden)) for b in boards]
    doc = {
        "about": "Synthetic regression set: expected verdicts of the compare step. Never accuracy. See README.md.",
        "seed": SEED,
        "recipe": RECIPE.to_dict(),
        "tolerances": TOLERANCES,
        "hit_margin_px": HIT_MARGIN,
        "boards": entries,
    }
    # One line per board keeps the file reviewable in a diff; the header stays indented.
    head = json.dumps({k: v for k, v in doc.items() if k != "boards"}, indent=1).rstrip("}\n")
    rows = ",\n".join("  " + json.dumps(e, separators=(",", ": ")) for e in entries)
    path.write_text(f'{head},\n "boards": [\n{rows}\n ]\n}}\n', encoding="utf-8")
    return doc


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", help="write golden.png, the 40 boards and manifest.json here")
    ap.add_argument("--write-expected", action="store_true", help=f"re-baseline {EXPECTED_PATH.name}")
    a = ap.parse_args()
    if not a.out and not a.write_expected:
        ap.error("give --out and/or --write-expected")
    if a.out:
        boards = generate(Path(a.out))
        print(f"Wrote {len(boards)} boards to {Path(a.out).resolve()}")
    if a.write_expected:
        doc = write_expected(scratch=Path(a.out) if a.out else None)
        verdicts = [b["verdict"] for b in doc["boards"]]
        counts = ", ".join(f"{verdicts.count(v)} {v}" for v in ("NG", "WARN", "OK"))
        print(f"Baselined {EXPECTED_PATH}: {counts}")


if __name__ == "__main__":
    main()
