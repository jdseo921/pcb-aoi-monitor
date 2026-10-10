#!/usr/bin/env python
"""Write the boards the built app's self-test inspects (REQ-SET-012; aoi/selftest.py, installer/aoi.spec).

    python tools/make_selftest_data.py <folder>
    python main.py --self-test <new workspace folder> <folder>

Two boards of the synthetic regression set (tests/regression/, drawn from its fixed seed): its golden board and BOARD,
with `selftest.json`, which names them, the recipe the set is judged with and the verdict expected.json records for
BOARD. installer/aoi.spec runs this for every build and ships the folder as the app's `selftest` folder, so the .exe
can inspect a board with nothing else installed. Only these drawings go in, never a photograph or a customer's image,
and a self-test result is never accuracy (Customers & Launch, "Validation and accuracy claims").
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
import tempfile
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:  # run as a script from any folder, as the spec does
    sys.path.insert(0, str(ROOT))

from tests.regression import make_regression_set as rs  # noqa: E402

BOARD = "ng_00_missing_component.png"  # a missing part, found as one large region: NG in expected.json, never close


def write(out: Path) -> dict[str, Any]:
    """Write golden.png, BOARD and selftest.json into `out`; return what selftest.json holds."""
    expected = json.loads(rs.EXPECTED_PATH.read_text(encoding="utf-8"))
    entry = next(b for b in expected["boards"] if b["name"] == BOARD)
    out.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:  # the boards are drawn in order from one seed: all 40, then two kept
        rs.generate(Path(tmp))
        for name in ("golden.png", BOARD):
            shutil.copyfile(Path(tmp) / name, out / name)
    doc = {
        "about": "Self-test of a build: one board of the synthetic regression set. Never accuracy.",
        "seed": expected["seed"],
        "recipe": expected["recipe"],
        "golden": "golden.png",
        "board": BOARD,
        "expected": entry["verdict"],
    }
    (out / "selftest.json").write_text(json.dumps(doc, indent=1) + "\n", encoding="utf-8")
    return doc


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n", 1)[0])
    ap.add_argument("out", type=Path, help="the folder to write the boards and selftest.json into")
    doc = write(ap.parse_args().out)
    print(f"Wrote {doc['golden']}, {doc['board']} (expected {doc['expected']}) and selftest.json")


if __name__ == "__main__":
    main()
