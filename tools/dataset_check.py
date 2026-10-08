"""Check the engine on public PCB defect datasets, for an internal test record (plan stage S30, issue #10).

    python tools/dataset_check.py --out <folder> [--deeppcb <PCBData folder>] [--pku <PCB_DATASET folder>]
        [--min-area <px>] [--ai]

DeepPCB (PCBData: `*_temp.jpg` defect-free, `*_test.jpg` defective, boxes in `*_not/*.txt`, splits in test.txt and
trainval.txt) and PKU-Market-PCB (PCB_DATASET: `PCB_USED/<board>.JPG` defect-free, `images/<type>/` defective, VOC boxes
in `Annotations/<type>/`; `rotation/` is left out, as its copies have no boxes) are public research datasets. Jay
approved them in writing on 2026-10-08 for internal training and checks only: nothing they hold, and no model trained on
them, enters the repository or ships, and their results are counts on public boards, never an accuracy claim.

It runs the golden-board comparison with the AI check off (each defective board against its own defect-free board, the
default recipe) and, with --ai, the AI model alone on DeepPCB's test split (one model per group, trained on --ok-train
seeded templates of the group's trainval split). A labelled box counts as found when a difference region overlaps
it grown by MARGIN px. It writes manifest.csv (SHA-256 of every file read), results.json and summary.md to --out, which
must lie outside the repository and the datasets, and checks that no source file changed.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import os
import platform
import random
import sys
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from time import perf_counter
from typing import Any

import cv2
import numpy as np
import torch

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:  # run as a script: the repository root holds the ``aoi`` package
    sys.path.insert(0, str(ROOT))

from aoi.core import anomaly  # noqa: E402
from aoi.core.imaging import load_image  # noqa: E402
from aoi.core.inspector import Inspector  # noqa: E402
from aoi.core.recipe import Recipe  # noqa: E402

MARGIN = 10  # px a region may lie off a labelled box and still find it
DEEPPCB_TYPES = {1: "open", 2: "short", 3: "mousebite", 4: "spur", 5: "copper", 6: "pin-hole"}
DEEPPCB_PX_PER_MM = 48.0  # "around 48 pixels per 1 millimetre" (the dataset's README)


@dataclass
class Item:
    """One defective board with its defect-free board and labelled boxes (x, y, w, h, type)."""

    dataset: str
    group: str
    test: Path
    good: Path
    boxes: list[tuple[int, int, int, int, str]] = field(default_factory=list)


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def upper_95(k: int, n: int) -> float:
    """One-sided 95 % Clopper-Pearson upper bound of a rate seen k times in n (bisection, no SciPy)."""
    if n == 0:
        return 1.0
    if k >= n:
        return 1.0

    def cdf(p: float) -> float:  # P(X <= k) for X ~ Binomial(n, p)
        logs = [math.lgamma(n + 1) - math.lgamma(i + 1) - math.lgamma(n - i + 1) for i in range(k + 1)]
        return sum(math.exp(c + i * math.log(p) + (n - i) * math.log1p(-p)) for i, c in enumerate(logs))

    lo, hi = k / n, 1.0
    for _ in range(60):
        mid = (lo + hi) / 2
        lo, hi = (mid, hi) if cdf(mid) > 0.05 else (lo, mid)
    return hi


def outside(out: Path, roots: list[Path]) -> bool:
    """True when `out` lies inside none of `roots` and none of them lies inside `out`."""
    o = out.resolve()
    return not any(o == r or r in o.parents or o in r.parents for r in (p.resolve() for p in roots))


def deeppcb_items(root: Path, split: str) -> list[Item]:
    items = []
    for line in (root / f"{split}.txt").read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        image, note = line.split()
        stem = Path(image)
        boxes = []
        for row in (root / note).read_text(encoding="utf-8").splitlines():
            parts = row.replace(",", " ").split()
            if len(parts) == 5:
                x1, y1, x2, y2, kind = (int(float(v)) for v in parts)
                boxes.append((x1, y1, x2 - x1, y2 - y1, DEEPPCB_TYPES.get(kind, str(kind))))
        folder = root / stem.parent
        test, good = folder / f"{stem.stem}_test.jpg", folder / f"{stem.stem}_temp.jpg"
        items.append(Item("DeepPCB", stem.parts[0], test, good, boxes))
    return items


def pku_items(root: Path) -> list[Item]:
    used = {p.stem: p for p in (root / "PCB_USED").iterdir() if p.is_file()}
    items = []
    for xml_path in sorted((root / "Annotations").glob("*/*.xml")):
        tree = ET.parse(xml_path)  # the dataset's own annotation files, read locally
        name = xml_path.stem
        image = root / "images" / xml_path.parent.name / f"{name}.jpg"
        board = name.split("_")[0]
        if board not in used or not image.is_file():
            continue
        boxes = []
        for obj in tree.getroot().iter("object"):
            b = obj.find("bndbox")
            if b is None:
                continue
            x1, y1, x2, y2 = (int(float(b.findtext(k, "0"))) for k in ("xmin", "ymin", "xmax", "ymax"))
            boxes.append((x1, y1, x2 - x1, y2 - y1, (obj.findtext("name") or xml_path.parent.name).lower()))
        items.append(Item("PKU-Market-PCB", board, image, used[board], boxes))
    return items


def found(box: tuple[int, int, int, int, str], regions: list[tuple[int, int, int, int]]) -> bool:
    x, y, w, h, _ = box
    return any(
        rx < x + w + MARGIN and x - MARGIN < rx + rw and ry < y + h + MARGIN and y - MARGIN < ry + rh
        for rx, ry, rw, rh in regions
    )


def golden_check(items: list[Item], min_area: int = Recipe.min_defect_area) -> dict[str, Any]:
    """Each board judged against its own defect-free board by the default recipe with the AI check off, its Minimum
    defect area min_area px."""
    verdicts: dict[str, int] = {}
    per_type: dict[str, dict[str, int]] = {}
    ms: list[float] = []
    false_regions = smallest = 0
    smallest_box: tuple[int, int] | None = None
    for item in items:
        good, test = load_image(item.good), load_image(item.test)
        t0 = perf_counter()
        recipe = Recipe(board_model=item.group, use_ai=False, min_defect_area=min_area)
        result = Inspector(recipe, reference=good).inspect(test)
        ms.append((perf_counter() - t0) * 1000)
        verdicts[result.verdict] = verdicts.get(result.verdict, 0) + 1
        regions = [(d.x, d.y, d.w, d.h) for d in result.defects]
        for box in item.boxes:
            hit = found(box, regions)
            row = per_type.setdefault(box[4], {"boxes": 0, "found": 0})
            row["boxes"] += 1
            row["found"] += hit
            side = max(box[2], box[3])
            if hit and (smallest_box is None or side < max(smallest_box)):
                smallest_box, smallest = (box[2], box[3]), side
        false_regions += sum(not any(found(b, [r]) for b in item.boxes) for r in regions)
    boxes = sum(r["boxes"] for r in per_type.values())
    missed = boxes - sum(r["found"] for r in per_type.values())
    for row in per_type.values():
        row["missed"] = row["boxes"] - row["found"]
        row["missed_upper_95"] = round(upper_95(row["missed"], row["boxes"]), 4)
    return {
        "boards": len(items),
        "verdicts": verdicts,
        "boards_not_ng": len(items) - verdicts.get("NG", 0),
        "boards_not_ng_upper_95": round(upper_95(len(items) - verdicts.get("NG", 0), len(items)), 4),
        "boxes": boxes,
        "boxes_missed": missed,
        "boxes_missed_upper_95": round(upper_95(missed, boxes), 4),
        "by_type": dict(sorted(per_type.items())),
        "regions_on_no_box": false_regions,
        "smallest_box_found_px": list(smallest_box) if smallest_box else None,
        "smallest_side_found_px": smallest if smallest_box else None,
        "ms": timing(ms),
    }


def ai_check(train: list[Item], test: list[Item], ok_train: int, cfg: anomaly.TrainConfig) -> dict[str, Any]:
    """Per DeepPCB group: train on `ok_train` seeded templates of its trainval split (and calibrate on a few of its
    defective boards), then score the group's test split, templates as OK and defective boards as NG."""
    counts = {"ok": 0, "ok_called_ng": 0, "ok_called_warning": 0, "ng": 0, "ng_called_ok": 0, "ng_called_warning": 0}
    train_s: list[float] = []
    ms: list[float] = []
    groups: dict[str, Any] = {}
    for group in sorted({i.group for i in test}):
        pool = [i for i in train if i.group == group]
        seen, ok_items = set(), []
        for item in random.Random(cfg.seed).sample(pool, len(pool)):
            digest = sha256(item.good)
            if digest not in seen:  # some templates are byte-identical
                seen.add(digest)
                ok_items.append(item)
        ok_items = ok_items[:ok_train]
        ng_items = [i for i in pool if i not in ok_items][: max(2, ok_train // 4)]
        if len(ok_items) < 2:
            groups[group] = {"skipped": "fewer than 2 distinct defect-free templates in trainval"}
            continue
        t0 = perf_counter()
        model = anomaly.train([load_image(i.good) for i in ok_items], [load_image(i.test) for i in ng_items], cfg)
        train_s.append(perf_counter() - t0)
        thr, warn = model.image_threshold, Recipe(board_model=group).warn_ratio * model.image_threshold
        g = dict.fromkeys(counts, 0)
        for item in (i for i in test if i.group == group):
            for path, kind in ((item.good, "ok"), (item.test, "ng")):
                img = load_image(path)
                t1 = perf_counter()
                score = model.score(model.anomaly_map(img))
                ms.append((perf_counter() - t1) * 1000)
                called = "ng" if score >= thr else "warning" if score >= warn else "ok"
                g[kind] += 1
                if called != kind:
                    g[f"{kind}_called_{called}"] += 1
        groups[group] = {**g, "ok_trained": len(ok_items), "ng_calibrated": len(ng_items), "threshold": round(thr, 4)}
        for k in counts:
            counts[k] += g[k]
    return {
        **counts,
        "ok_called_ng_upper_95": round(upper_95(counts["ok_called_ng"], counts["ok"]), 4),
        "ng_called_ok_upper_95": round(upper_95(counts["ng_called_ok"], counts["ng"]), 4),
        "groups": groups,
        "train_s": timing([s * 1000 for s in train_s], scale=1000),
        "ms": timing(ms),
    }


def timing(ms: list[float], scale: float = 1.0) -> dict[str, float] | None:
    if not ms:
        return None
    a = np.array(ms) / scale
    return {"n": len(ms), "median": round(float(np.median(a)), 1), "p95": round(float(np.percentile(a, 95)), 1)}


def peak_memory_mb() -> float | None:
    """The process's peak resident memory in MB (Windows: peak working set), or None where it cannot be read."""
    try:
        if sys.platform == "win32":
            import ctypes
            from ctypes import wintypes

            class Counters(ctypes.Structure):
                _fields_ = [("cb", wintypes.DWORD), ("faults", wintypes.DWORD)] + [
                    (n, ctypes.c_size_t) for n in ("peak", "now", "qpp", "qp", "qpn", "qn", "pf", "ppf")
                ]

            c = Counters()
            c.cb = ctypes.sizeof(c)
            k32, psapi = ctypes.WinDLL("kernel32"), ctypes.WinDLL("psapi")
            psapi.GetProcessMemoryInfo(k32.GetCurrentProcess(), ctypes.byref(c), c.cb)
            return round(c.peak / 2**20, 1)
        import resource

        return round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024, 1)  # KB on Linux
    except (OSError, AttributeError, ImportError):
        return None


def manifest(items: list[Item]) -> dict[str, str]:
    return {str(p): sha256(p) for p in sorted({p for i in items for p in (i.test, i.good)})}


def run(args: argparse.Namespace) -> dict[str, Any]:
    roots = [Path(p) for p in (args.deeppcb, args.pku) if p]
    out = Path(args.out)
    if not roots:
        raise SystemExit("give --deeppcb, --pku or both")
    if not outside(out, [ROOT, *roots]):
        raise SystemExit("--out must lie outside the repository and the datasets")
    out.mkdir(parents=True, exist_ok=True)
    cfg = anomaly.TrainConfig(epochs=args.epochs, steps_per_epoch=args.steps, image_size=args.size, seed=args.seed)
    results: dict[str, Any] = {
        "when_utc": datetime.now(UTC).isoformat(timespec="seconds"),
        "machine": machine(),
        "settings": {
            "margin_px": MARGIN,
            "recipe": "default, AI check off",
            "min_defect_area_px": args.min_area,
            "ok_train": args.ok_train,
            **vars(cfg),
        },
        "note": "Counts on public research datasets for an internal check; not validated accuracy.",
    }
    test = deeppcb_items(Path(args.deeppcb), "test") if args.deeppcb else []
    train = deeppcb_items(Path(args.deeppcb), "trainval") if args.deeppcb and args.ai else []
    items = pku_items(Path(args.pku)) if args.pku else []
    used = test + train + items
    before = manifest(used)  # before any check reads them, so a change made while they run is caught
    with open(out / "manifest.csv", "w", newline="", encoding="utf-8") as f:
        csv.writer(f).writerows([("file", "sha256"), *before.items()])
    if args.deeppcb:
        results["deeppcb"] = {"golden": golden_check(test, args.min_area), "px_per_mm": DEEPPCB_PX_PER_MM}
        if args.ai:
            results["deeppcb"]["ai"] = ai_check(train, test, args.ok_train, cfg)
    if args.pku:
        results["pku"] = {"golden": golden_check(items, args.min_area)}
    results["peak_memory_mb"] = peak_memory_mb()
    results["sources_unchanged"] = manifest(used) == before
    (out / "results.json").write_text(json.dumps(results, indent=2), encoding="utf-8")
    (out / "summary.md").write_text(summary(results), encoding="utf-8")
    return results


def summary(r: dict[str, Any]) -> str:
    lines = [f"# Public dataset check, {r['when_utc']}", "", r["note"], "", f"Machine: {r['machine']}", ""]
    for name in ("deeppcb", "pku"):
        if name in r:
            g = r[name]["golden"]
            lines += [f"## {name} golden board, AI check off", f"Boards {g['boards']}, verdicts {g['verdicts']}."]
            lines += [f"Boxes {g['boxes']}, missed {g['boxes_missed']} (95 % upper {g['boxes_missed_upper_95']})."]
            lines += [f"- {t}: {v['found']} of {v['boxes']} found" for t, v in g["by_type"].items()]
            lines += [f"Regions on no box {g['regions_on_no_box']}; time per board {g['ms']}.", ""]
    if "ai" in r.get("deeppcb", {}):
        a = r["deeppcb"]["ai"]
        lines += [
            "## deeppcb AI model alone",
            f"OK {a['ok']}: {a['ok_called_ng']} NG, {a['ok_called_warning']} Warning.",
        ]
        lines += [
            f"NG {a['ng']}: {a['ng_called_ok']} OK, {a['ng_called_warning']} Warning; training {a['train_s']} s.",
            "",
        ]
    lines += [f"Peak memory {r['peak_memory_mb']} MB; sources unchanged: {r['sources_unchanged']}.", ""]
    return "\n".join(lines)


def machine() -> dict[str, Any]:
    """The machine and libraries the counts and times come from, with the threads each library computes on."""
    return {
        "system": platform.platform(),
        "cpu": platform.processor(),
        "cpus": os.cpu_count(),
        "python": platform.python_version(),
        "numpy": np.__version__,
        "opencv": cv2.__version__,
        "torch": torch.__version__,
        "threads": {"torch": torch.get_num_threads(), "opencv": cv2.getNumThreads()},
    }


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("--out", required=True)
    p.add_argument("--deeppcb", help="DeepPCB's PCBData folder")
    p.add_argument("--pku", help="PKU-Market-PCB's PCB_DATASET folder")
    p.add_argument("--min-area", type=int, default=Recipe.min_defect_area, help="Minimum defect area in px (a what-if)")
    p.add_argument("--ai", action="store_true", help="also train and test the AI model on DeepPCB")
    p.add_argument("--ok-train", type=int, default=20)
    p.add_argument("--epochs", type=int, default=anomaly.TrainConfig.epochs)
    p.add_argument("--steps", type=int, default=anomaly.TrainConfig.steps_per_epoch)
    p.add_argument("--size", type=int, default=anomaly.TrainConfig.image_size)
    p.add_argument("--seed", type=int, default=0)
    results = run(p.parse_args(argv))
    print(summary(results))
    return 0 if results["sources_unchanged"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
