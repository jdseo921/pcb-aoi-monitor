"""Stage 1 proxy validation on public datasets (#452), for an internal test record, never an accuracy claim.

    python tools/proxy_validation.py --set visa|robust|deeppcb|pku|control --data <folder> --out <folder> [--seed 0]

Stage 1 runs end to end on public PCB images through the app's own path (tools/proxy_stage1.py, called by the sets
in tools/proxy_sets.py), never through tools/trainable.py. This module holds what the sets share: VisA's index and
masks, the seeded pools, set B's photo changes, a defect found when a defect box overlaps its mask, counts with
one-sided 95 % upper bounds, and the result-file check. Sets: visa (A, VisA pcb1 to pcb4, CC BY 4.0), robust (B),
deeppcb (C, DeepPCB's PCBData, MIT), pku (D, skipped: no licence stated) and control (E, drawn boards only).

Jay approved on 2026-11-04 the use of the public datasets named in the test record for internal Stage 1 testing only:
no image, box, mask or trained model from them enters the repository or ships. --out must lie outside the repository
and the data; every source file is hashed before and after, and the run fails when one changed.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import random
import sys
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:  # run as a script: the repository root holds the ``aoi`` and ``tools`` packages
    sys.path.insert(0, str(ROOT))

from aoi import defects as taxonomy  # noqa: E402
from tools.dataset_check import outside, sha256, upper_95  # noqa: E402

NOT_ACCURACY = "Counts from an internal Stage 1 test on public data (#452); never an accuracy claim."
SETS = ("visa", "robust", "deeppcb", "pku", "control")
VISA_CATEGORIES = ("pcb1", "pcb2", "pcb3", "pcb4")
# VisA's anomaly names as the classification table (aoi/defects.py) names the nearest type; the table has no "extra
# component", so an extra part and dirt are Contamination. A board takes its first listed name's type.
VISA_TYPES = {
    "bent": "Bent Lead",
    "burnt": "Damaged Component",
    "damage": "Damaged Component",
    "dirt": "Contamination",
    "extra": "Contamination",
    "melt": "Damaged Component",
    "missing": "Missing Component",
    "scratch": "Scratch",
    "wrong place": "Misalignment",
}
LEARNING_CURVE = (70, 150, 400)  # OK images trained on; the 50 a validation set locks are imported on top
EXTRA_OK = 200  # normal boards never imported, inspected besides the locked set, for a tighter false-call bound
MIN_MASK_PX = 4  # a mask blob smaller than this is JPEG noise around the mask, not a defect
MP5 = 5_000_000  # pixels of a 5 MP photo
CHANGES = ("5mp", "jpeg70", "rot+2", "rot-2", "shift20", "bright+15", "bright-15", "blur")


@dataclass(frozen=True)
class Board:
    """One image with its truth: label OK or NG, its source anomaly names, its mask (None for OK) and its boxes."""

    path: Path
    label: str
    kinds: tuple[str, ...] = ()
    mask: Path | None = None
    boxes: tuple[tuple[int, int, int, int], ...] = field(default=())

    @property
    def defect_type(self) -> str | None:  # a table type (drawn boards) or a VisA name; one not mapped stops the run
        kind = self.kinds[0] if self.kinds else None
        return kind if kind is None or kind in taxonomy.names() else VISA_TYPES[kind]


def visa_index(root: Path, category: str) -> list[Board]:
    """A VisA category's boards from its image_anno.csv: normal as OK, anomalous as NG with its names and mask."""
    out = []
    with open(root / category / "image_anno.csv", newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            kinds = () if row["label"] == "normal" else tuple(k.strip() for k in row["label"].split(","))
            mask = root / row["mask"] if row.get("mask") else None
            out.append(Board(root / row["image"], "NG" if kinds else "OK", kinds, mask))
    return out


def mask_boxes(mask: np.ndarray, min_px: int = MIN_MASK_PX) -> list[tuple[int, int, int, int]]:
    """The bounding box (x, y, w, h) of each 8-connected blob of a mask's non-zero pixels of at least `min_px`."""
    grey = mask if mask.ndim == 2 else mask.max(axis=2)
    n, _, stats, _ = cv2.connectedComponentsWithStats((grey > 0).astype(np.uint8), connectivity=8)
    return [tuple(int(v) for v in stats[i, :4]) for i in range(1, n) if stats[i, 4] >= min_px]  # type: ignore[misc]


def pools(boards: list[Board], seed: int, extra_ok: int = EXTRA_OK) -> tuple[list[Board], list[Board], list[Board]]:
    """(extra OK boards never imported, OK boards to import in order, NG boards), drawn by `seed` from the sorted list:
    each learning-curve run imports a prefix of one order and is judged on the same extra boards."""
    ok = sorted((b for b in boards if b.label == "OK"), key=lambda b: str(b.path))
    ng = sorted((b for b in boards if b.label == "NG"), key=lambda b: str(b.path))
    if len(ok) <= extra_ok:
        raise ValueError(f"{len(ok)} OK boards leave none to import beside {extra_ok} extra ones")
    random.Random(seed).shuffle(ok)
    return ok[:extra_ok], ok[extra_ok:], ng


def overlaps(box: tuple[int, int, int, int], mask: np.ndarray) -> bool:
    """True when the box (x, y, w, h) holds at least one non-zero pixel of `mask`."""
    x, y, w, h = box
    x0, y0 = max(0, x), max(0, y)
    return bool(np.any(mask[y0 : max(y0, y + h), x0 : max(x0, x + w)]))


def found(defects: Iterable[tuple[int, int, int, int]], mask: np.ndarray) -> bool:
    """A defect counts as found when a defect box the board was given overlaps its mask (Jay, 2026-11-04)."""
    return any(overlaps(d, mask) for d in defects)


def tally(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Counts of `rows` (each: label, verdict, found; optional kind): verdicts of good and defective boards, missed
    defects (an NG board judged OK, or flagged with no defect box on its mask) and false calls (an OK board judged
    WARN or NG), each with its one-sided 95 % upper bound, and missed defects per kind."""
    good, bad = ([r for r in rows if r["label"] == label] for label in ("OK", "NG"))

    def verdicts(rs: list[dict[str, Any]]) -> dict[str, int]:
        return {v: sum(r["verdict"] == v for r in rs) for v in ("OK", "WARN", "NG")}

    missed_at = {i for i, r in enumerate(bad) if r["verdict"] == "OK" or not r["found"]}
    false_calls = sum(r["verdict"] != "OK" for r in good)
    kinds: dict[str, dict[str, int]] = {}
    for i, r in enumerate(bad):
        k = kinds.setdefault(r.get("kind") or "?", {"boards": 0, "missed": 0})
        k["boards"] += 1
        k["missed"] += i in missed_at
    for k in kinds.values():
        k["missed_upper_95"] = round(upper_95(k["missed"], k["boards"]), 4)  # type: ignore[assignment]
    return {
        "good": {"boards": len(good), **verdicts(good)},
        "defective": {"boards": len(bad), **verdicts(bad)},
        "false_calls": false_calls,
        "false_calls_upper_95": round(upper_95(false_calls, len(good)), 4),
        "missed": len(missed_at),
        "flagged_off_mask": sum(r["verdict"] != "OK" and not r["found"] for r in bad),
        "missed_upper_95": round(upper_95(len(missed_at), len(bad)), 4),
        "by_kind": dict(sorted(kinds.items())),
    }


def timing(values: list[float]) -> dict[str, float] | None:
    if not values:
        return None
    a = np.array(values)
    return {"n": len(values), "median": round(float(np.median(a)), 1), "p95": round(float(np.percentile(a, 95)), 1)}


# --- set B: the photo changes, each applied to the image and, where it moves pixels, to its mask -------------------
def _affine(img: np.ndarray, m: np.ndarray, is_mask: bool) -> np.ndarray:
    """An image warped with its edge repeated into the border, as a camera sees more board; a mask with none there."""
    flags, border = (cv2.INTER_NEAREST, cv2.BORDER_CONSTANT) if is_mask else (cv2.INTER_LINEAR, cv2.BORDER_REPLICATE)
    return cv2.warpAffine(img, m, (img.shape[1], img.shape[0]), flags=flags, borderMode=border, borderValue=0)


def change(name: str, img: np.ndarray, mask: np.ndarray | None) -> tuple[np.ndarray, np.ndarray | None]:
    """`img` and its mask under one of CHANGES: resized to 5 MP, JPEG quality 70, rotated by 2 degrees either way about
    the centre, shifted 20 px right and down, 15 % brighter or darker, or a 5 x 5 Gaussian blur (sigma 1)."""
    h, w = img.shape[:2]
    if name == "5mp":
        f = math.sqrt(MP5 / (w * h))
        size = (round(w * f), round(h * f))
        small = cv2.resize(mask, size, interpolation=cv2.INTER_NEAREST) if mask is not None else None
        return cv2.resize(img, size, interpolation=cv2.INTER_CUBIC), small
    if name == "jpeg70":
        ok, buf = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, 70])
        assert ok
        return cv2.imdecode(buf, cv2.IMREAD_COLOR), mask
    if name in ("rot+2", "rot-2", "shift20"):
        m = (
            np.float32([[1, 0, 20], [0, 1, 20]])
            if name == "shift20"
            else cv2.getRotationMatrix2D((w / 2, h / 2), 2.0 if name == "rot+2" else -2.0, 1.0)
        )
        return _affine(img, m, False), _affine(mask, m, True) if mask is not None else None
    if name in ("bright+15", "bright-15"):
        gain = 1.15 if name == "bright+15" else 0.85
        return np.clip(np.rint(img.astype(np.float32) * gain), 0, 255).astype(np.uint8), mask
    if name == "blur":
        return cv2.GaussianBlur(img, (5, 5), 1.0), mask
    raise ValueError(f"no such change: {name}")


# --- result files (REQ-INSP-021) -------------------------------------------------------------------------------------
def check_result_files(
    folder: Path, schema: Path = ROOT / "docs" / "schemas" / "result-file.schema.json"
) -> dict[str, Any]:
    """Each `<board ID>_<record UUID>.json` under `folder` checked against the schema by the repository's own checker
    (tests/test_result_files.py, as no validator is a dependency), and whether each has its one-line CSV beside it:
    counts, and the first few problems."""
    from tests.test_result_files import problems

    rules = json.loads(schema.read_text(encoding="utf-8"))
    files = sorted(p for p in folder.rglob("*_*-*-*-*-*.json"))  # <board ID>_<record UUID>.json only
    issues = {p.name: problems(json.loads(p.read_text(encoding="utf-8")), rules) for p in files}
    errors = [f"{name}: {e}" for name, es in issues.items() for e in es]
    no_csv = [p.name for p in files if not p.with_suffix(".csv").is_file()]
    return {
        "json": len(files),
        "invalid": sum(bool(es) for es in issues.values()),
        "errors": errors[:5],
        "without_csv": no_csv[:5],
        "shift": sorted(p.name for p in folder.rglob("shift_*.csv")),
    }


def manifest(paths: Iterable[Path]) -> dict[str, str]:
    return {str(p): sha256(p) for p in sorted(set(paths))}


def guard(out: Path, roots: list[Path]) -> None:
    if not outside(out, [ROOT, *roots]):
        raise SystemExit("--out must lie outside the repository and the data")


def run(args: argparse.Namespace, sets: dict[str, Callable[[argparse.Namespace], dict[str, Any]]]) -> dict[str, Any]:
    """One set; writes <out>/<set>.json and returns it. Each set that reads public data hashes it before and after
    (`manifest`) and says so in `sources_unchanged`; the controls draw their own boards and read none."""
    out, data = Path(args.out), [Path(p) for p in args.data or []]
    guard(out, data)
    out.mkdir(parents=True, exist_ok=True)
    result = {"claim": NOT_ACCURACY, **sets[args.set](args)}
    (out / f"{args.set}.json").write_text(json.dumps(result, indent=1, default=str), encoding="utf-8")
    return result


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=(__doc__ or "").split("\n\n")[0])
    p.add_argument("--set", required=True, choices=SETS)
    p.add_argument("--data", action="append", help="the set's data folder (VisA's root, DeepPCB's PCBData)")
    p.add_argument("--out", required=True, help="workspaces and results, outside the repository and the data")
    p.add_argument("--seed", type=int, default=0)
    p.add_argument("--categories", default=",".join(VISA_CATEGORIES))
    p.add_argument("--curve", default=",".join(map(str, LEARNING_CURVE)), help="OK images trained on, per run")
    p.add_argument("--size-category", default="pcb1", help="the category trained at 640 px too (set A), changed (B)")
    p.add_argument("--extra-ok", type=int, default=EXTRA_OK)
    p.add_argument("--epochs", type=int, help="a quicker run than the default settings' (a smoke test only)")
    return p


def main(argv: list[str] | None = None) -> int:
    from tools.proxy_sets import SETS as DRIVERS  # imports PySide6 and PyTorch, which the counting does not need

    result = run(parser().parse_args(argv), DRIVERS)
    print(json.dumps({k: v for k, v in result.items() if k != "runs"}, indent=1, default=str)[:4000])
    return 1 if result.get("sources_unchanged") is False or "error" in result else 0


if __name__ == "__main__":
    raise SystemExit(main())
