"""The sets of tools/proxy_validation.py (#452): A (VisA through Stage 1), B (set A's held-out boards changed a little),
C (DeepPCB through tools/dataset_check.py, beside the 2026-10-08 record), D (PKU-Market-PCB, skipped for its licence)
and E (the controls: the regression set, the demo bundle and drawn boards through the same path)."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import cv2

from aoi import config
from aoi.config import Settings
from aoi.core import demo
from aoi.core.services import AppContext
from aoi.data import credentials
from tools.dataset_check import machine
from tools.proxy_stage1 import check_result_files, code_of, inspect_all, stage1, ui_exports
from tools.proxy_validation import CHANGES, ROOT, Board, manifest, pools, visa_index


def visa_runs(args: argparse.Namespace, root: Path, out: Path) -> Iterator[tuple[str, dict[str, Any]]]:
    curve = [int(n) for n in args.curve.split(",")]
    for cat in args.categories.split(","):
        boards = visa_index(root, cat)
        extra, pool, ng = pools(boards, args.seed, args.extra_ok)
        sizes = [(n, 256) for n in curve] + ([(150, 640)] if cat == args.size_category else [])
        for n, size in sizes:
            name = f"{cat}-{n}-{size}"
            yield name, stage1(out / name, cat.upper(), pool[: n + 50], ng, extra, args.seed, size, args.epochs)


def set_visa(args: argparse.Namespace) -> dict[str, Any]:
    root, out = Path(args.data[0]), Path(args.out) / "visa"
    sources = [p for c in args.categories.split(",") for b in visa_index(root, c) for p in (b.path, b.mask) if p]
    before = manifest(sources)
    runs: dict[str, Any] = {}
    for name, r in visa_runs(args, root, out):
        runs[name] = r
        (out / f"{name}.json").write_text(json.dumps(r, indent=1, default=str), encoding="utf-8")
    return {
        "machine": machine(),
        "seed": args.seed,
        "runs": runs,
        "sources": len(before),
        "sources_unchanged": manifest(sources) == before,
    }


def set_robust(args: argparse.Namespace) -> dict[str, Any]:
    """Set B: the model trained on the unaltered images of --size-category (set A's 150 OK run, trained again when its
    workspace is gone), judging the same held-out boards under each photo change."""
    root, cat = Path(args.data[0]), args.size_category
    run_dir = Path(args.out) / "visa" / f"{cat}-150-256"
    boards = visa_index(root, cat)
    extra, pool, ng = pools(boards, args.seed, args.extra_ok)
    sources = [p for b in boards for p in (b.path, b.mask) if p]
    before = manifest(sources)
    record = run_dir.with_suffix(".json")
    if not (run_dir / "ws" / "aoi.sqlite").is_file():
        a = stage1(run_dir, cat.upper(), pool[:200], ng, extra, args.seed, 256, args.epochs, ui=False)
        record.write_text(json.dumps(a, default=str), encoding="utf-8")
    a = json.loads(record.read_text(encoding="utf-8")) if record.is_file() else {"error": "no record of set A's run"}
    if (
        "error" in a
        or "training" not in a
        or (a.get("seed", args.seed), a["held_out"]["extra_ok"])
        != (
            args.seed,
            args.extra_ok,
        )
    ):  # another seed or extra count would judge boards that run trained on, or a model it never made
        raise SystemExit(f"{run_dir.name}: set A's run failed or drew its boards otherwise; run set A again")
    config.use_workspace(run_dir / "ws")  # set A's settings.json: a shift check turned off there stays off
    settings = Settings.load()
    settings.device, settings.output_folder = "cpu", ""  # records stay in the workspace
    keys = credentials.MemoryCredentials()
    for name, key in json.loads((run_dir / "store-keys.json").read_text()).items():
        keys.write(name, bytes.fromhex(key))
    ctx = AppContext(settings, keys)
    try:
        ctx.set_user("operator")
        if ctx.shift_check(cat.upper())["state"] not in ("passed", "off"):  # a new shift: its check first
            ctx.run_shift_check(cat.upper())
        version = ctx.datasets(cat.upper())[0]
        items = {i["uuid"]: i for i in ctx.dataset_items(version["uuid"])}
        split = ctx.validation_split(version["uuid"]) or {}
        by_sha = {s: b for b in pool[:200] + ng for s in [manifest([b.path])[str(b.path)]]}
        held = [by_sha[items[u]["sha256"]] for u in split["validation"]] + extra
        runs = {"none": inspect_all(ctx, cat.upper(), held)}
        for c in CHANGES:
            runs[c] = inspect_all(ctx, cat.upper(), held, c)
    finally:
        ctx.close()
    return {"category": cat, "runs": runs, "sources_unchanged": manifest(sources) == before}


DEEPPCB_2026_10_08 = {  # the counts docs/tests/2026-10-08-public-dataset-check.md records for the cloud run
    "golden": {
        "boards": 500,
        "NG": 500,
        "boxes": 3140,
        "missed": 324,
        "regions_on_no_box": 786,
        "by_type_missed": {"open": 176, "mousebite": 66, "short": 46, "spur": 27, "copper": 5, "pin-hole": 4},
    },
    "ai": {
        "ok": 168,
        "ok_called_ng": 1,
        "ok_called_warning": 9,
        "ng": 168,
        "ng_called_ok": 115,
        "ng_called_warning": 31,
    },
}


def set_deeppcb(args: argparse.Namespace) -> dict[str, Any]:
    """Set C: tools/dataset_check.py --deeppcb --ai with its defaults, as run on 2026-10-08, beside its counts."""
    out = Path(args.out) / "deeppcb"
    env = os.environ | {"OMP_NUM_THREADS": "2", "MKL_NUM_THREADS": "2"}  # the 2026-10-08 run's thread settings
    cmd = [
        sys.executable,
        str(ROOT / "tools" / "dataset_check.py"),
        "--out",
        str(out),
        "--deeppcb",
        args.data[0],
        "--ai",
        *("--min-area", "40", "--ok-train", "20", "--epochs", "60", "--steps", "8", "--size", "256", "--seed", "0"),
    ]  # the 2026-10-08 arguments, stated, so a later default does not change the rerun
    shutil.rmtree(out, ignore_errors=True)  # never compare a results.json an earlier run left
    t0 = time.perf_counter()
    done = subprocess.run(cmd, env=env, capture_output=True, text=True, check=False)
    res = json.loads((out / "results.json").read_text(encoding="utf-8")) if (out / "results.json").is_file() else {}
    g = res.get("deeppcb", {}).get("golden", {})
    now = {
        "boards": g.get("boards"),
        "NG": g.get("verdicts", {}).get("NG"),
        "boxes": g.get("boxes"),
        "missed": g.get("boxes_missed"),
        "regions_on_no_box": g.get("regions_on_no_box"),
        "by_type_missed": {t: v["missed"] for t, v in g.get("by_type", {}).items()},
    }
    ai = {k: res.get("deeppcb", {}).get("ai", {}).get(k) for k in DEEPPCB_2026_10_08["ai"]}
    return ({"error": f"dataset_check.py exited {done.returncode}"} if done.returncode else {}) | {
        "command": cmd[1:],
        "exit": done.returncode,
        "stderr": done.stderr[-2000:],
        "s": round(time.perf_counter() - t0),
        "golden": now,
        "ai": ai,
        "record": DEEPPCB_2026_10_08,
        "golden_same": now == DEEPPCB_2026_10_08["golden"] if done.returncode == 0 else None,
        "ai_same": ai == DEEPPCB_2026_10_08["ai"] if done.returncode == 0 else None,
        "ai_note": "the 2026-10-09 laptop run did not repeat the cloud run's AI counts: a difference is to be traced,"
        " not by itself a regression",
        "results": res,
        "sources_unchanged": res.get("sources_unchanged"),
    }


def set_pku(args: argparse.Namespace) -> dict[str, Any]:
    return {
        "skipped": "PKU-Market-PCB states no licence (Legal & Compliance: no licence stated is not allowed), and its"
        " only download is a Baidu Netdisk link (https://pan.baidu.com/s/1hoPNd7_SAxOWa2XbBZZuTg) or a torrent"
    }


def set_control(args: argparse.Namespace) -> dict[str, Any]:
    """Set E: (1) the synthetic regression set through InspectionCycle against its expected.json, AI check with no AI
    model; (2) the demo bundle as the build makes it: AI Model Test on its locked set, its scripted boards through
    InspectionCycle, the exports; (3) regression-style drawn boards, with their boxes, through the whole stage1 path."""
    import random

    from tests.regression.make_regression_set import DEFECTS, HIT_MARGIN, _bounding_box, capture, draw_board, generate
    from tools.make_demo_bundle import build

    out = Path(args.out) / "control"
    shutil.rmtree(out, ignore_errors=True)
    pinned = ROOT / "tests" / "regression" / "expected.json"  # no public data is read: the baseline is hashed instead
    result: dict[str, Any] = {"expected_json_sha256": manifest([pinned])[str(pinned)]}

    def grown(box: tuple[int, int, int, int]) -> tuple[int, int, int, int]:
        """A box drawn in Golden-board pixels, grown by the regression set's own HIT_MARGIN: capture() then moves the
        board a few px, as the regression baseline allows for."""
        x, y, w, h = box
        return (max(0, x - HIT_MARGIN), max(0, y - HIT_MARGIN), w + 2 * HIT_MARGIN, h + 2 * HIT_MARGIN)

    reg = generate(out / "regression")
    expected = json.loads((ROOT / "tests" / "regression" / "expected.json").read_text(encoding="utf-8"))["boards"]
    config.use_workspace(out / "regression-ws")
    ctx = AppContext(
        Settings(workspace=str(out / "regression-ws"), device="cpu", shift_check_hours=0),
        credentials.MemoryCredentials(),
    )
    try:
        ctx.set_user("admin")
        ctx.import_samples("REGRESSION", [str(out / "regression" / "golden.png")], "OK")  # the Golden board
        boards = [
            Board(
                out / "regression" / b.name,
                b.label,
                (b.defect_type,) if b.defect_type else (),
                None,
                (grown(b.defect_box),) if b.defect_box else (),
            )
            for b in reg
        ]
        got = inspect_all(ctx, "REGRESSION", boards)
        want = {e["name"]: e["verdict"] for e in expected}
        same = [r["verdict"] == want.get(r["board"]) for r in got["rows"]]
        result["regression"] = got | {"verdicts_as_expected": sum(same), "of": len(want), "judged": len(same)}
    finally:
        ctx.close()
    try:
        bundle = out / "demo-bundle"
        build(bundle, **({"epochs": args.epochs} if args.epochs else {}))
        keys = credentials.MemoryCredentials()
        m = demo.load(bundle, out / "demo-ws", {"device": "cpu"}, keys)
        config.use_workspace(out / "demo-ws")
        (out / "demo-results").mkdir()
        ctx = AppContext(
            Settings(workspace=str(out / "demo-ws"), device="cpu", output_folder=str(out / "demo-results")), keys
        )
    except (Exception, SystemExit) as e:  # the bundle not built or not loaded: the drawn boards still run
        result["demo"] = {"error": code_of(e) if isinstance(e, Exception) else {"code": "SystemExit", "text": str(e)}}
        ctx = None
    try:
        if ctx is None:
            raise LookupError("no demo workspace")
        ctx.set_user("admin")
        bm = m["board_model"]
        version = next(v for v in ctx.datasets(bm) if ctx.validation_split(v["uuid"]))
        metrics, rows, _ = ctx.test_dataset(version["uuid"])
        ctx.run_shift_check(bm)
        scripted = [Board(out / "demo-ws" / demo.BOARDS / Path(b["file"]).name, b["verdict"]) for b in m["boards"]]
        result["demo"] = {
            "model_test": {k: metrics[k] for k in ("samples", "TP", "FN", "FP", "TN")},
            "scripted": inspect_all(ctx, bm, scripted),
            "result_files": check_result_files(out / "demo-results"),
            "exports": ui_exports(ctx, bm, rows[0]["run_uuid"], out / "demo-exports"),
        }
    except LookupError:
        pass
    except Exception as e:
        result["demo"] = {"error": code_of(e)}
    finally:
        if ctx is not None:
            ctx.close()
        config.use_workspace(None)
    rng, drawn = random.Random(args.seed), out / "drawn"
    drawn.mkdir()
    clean = draw_board(rng)
    ok, ng = [], []
    for i in range(120 + args.extra_ok // 2):
        cv2.imwrite(str(drawn / f"ok_{i:03d}.png"), capture(draw_board(rng), rng))
        ok.append(Board(drawn / f"ok_{i:03d}.png", "OK"))
    for i in range(40):
        d = DEFECTS[i % len(DEFECTS)]
        img = draw_board(rng, d)
        cv2.imwrite(str(drawn / f"ng_{i:03d}.png"), capture(img, rng))
        ng.append(Board(drawn / f"ng_{i:03d}.png", "NG", (d,), None, (grown(_bounding_box(clean, img)),)))
    result["drawn"] = stage1(out / "drawn-run", "DRAWN", ok[:120], ng, ok[120:], args.seed, 256, args.epochs)
    result["sources_unchanged"] = manifest([pinned])[str(pinned)] == result["expected_json_sha256"]
    return result


SETS: dict[str, Callable[[argparse.Namespace], dict[str, Any]]] = {
    "visa": set_visa,
    "robust": set_robust,
    "deeppcb": set_deeppcb,
    "pku": set_pku,
    "control": set_control,
}
