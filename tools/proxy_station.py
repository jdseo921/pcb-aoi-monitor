"""A VisA board model's station as shipped or as commissioned, for tools/proxy_scenario_runs.py (#459).

`build` takes one board model through the app's Stage 1 path:
- import, a Trial freeze, the locked validation set, training and activation, as tools/proxy_stage1.py does;
- AI Model Test on the locked set, and the shift check.

As commissioned, an applications engineer's day one is inserted, each step recorded with the screen path that does it:
- the most typical good board is made the Golden board before training;
- Learn From Labelled Boards sets the comparison's pair and alignment;
- the whole-board limits are set just past the worst of 60 good commissioning boards never imported;
- the AI score threshold is overridden with the cut that best separates the calibration scores.

`open_station` reopens a built workspace, and `copy_station` makes a copy for a scenario that adds records of its own;
tools/proxy_judge.py puts boards through it. Nothing here is under aoi/.
"""

from __future__ import annotations

import json
import os
import shutil
import time
from dataclasses import replace
from pathlib import Path
from typing import Any

import cv2
import numpy as np

from aoi import config
from aoi.config import Settings
from aoi.core.sample_import import folder_files
from aoi.core.services import AppContext
from aoi.data import credentials
from aoi.errors import AoiError
from tools.proxy_scenarios import best_cut
from tools.proxy_stage1 import CUSTOMER, REVISION, VIEW, code_of, peak_mb, reset_peak, stage
from tools.proxy_validation import Board, manifest

LIMIT_CHECKS = {
    "SSIM similarity": "ssim_min",
    "Changed area %": "changed_pct_max",
    "Difference regions": "max_diff_regions",
}


MISSING = {  # the day-one steps the app has no feature for, as commissioning met them
    "Don't-care regions": {
        "missing": "no ROI type excludes an area: an ROI names a defect type and adds an AI check"
        " inside it, and the comparison still judges the whole board"
    },
    "Inspection ROIs": {"drawn": 0, "why": "on VisA the whole board matters, and an ROI adds only a regional AI check"},
    "Master samples": {
        "missing": "the shift check takes the oldest OK and the oldest NG of each Critical type; an"
        " engineer cannot choose them"
    },
}


def typical(paths: list[Path], side: int = 128) -> int:
    """The index of the most typical board: the one whose small grey image lies closest, in median absolute
    difference, to the others, as an engineer picks the board that looks most like the rest."""
    small = [cv2.resize(cv2.imread(str(p), cv2.IMREAD_GRAYSCALE), (side, side)).astype(np.float32) for p in paths]
    stack = np.stack(small)
    cost = [float(np.median(np.abs(stack - s).mean(axis=(1, 2)))) for s in small]
    return int(np.argmin(cost))


def limits(values: dict[str, list[float]], warn_ratio: float) -> dict[str, float]:
    """The whole-board limits that leave the worst good commissioning board OK, outside the WARN band too, as an
    engineer sets them who wants good boards to pass: SSIM so that the lowest seen clears the band, the changed area
    5 % past the highest over the WARN ratio, the difference regions at the most seen. An SSIM so low that no limit
    above 0 clears the band leaves the limit at 0, and the worst board in WARN."""
    out: dict[str, float] = {}
    if v := values.get("SSIM similarity"):
        out["ssim_min"] = round(max(0.0, (min(v) - (1 - warn_ratio)) / warn_ratio - 0.01), 3)
    if v := values.get("Changed area %"):
        out["changed_pct_max"] = round(max(v) / warn_ratio * 1.05, 3)
    if v := values.get("Difference regions"):
        out["max_diff_regions"] = int(max(v))
    return out


def scores(model: dict[str, Any]) -> tuple[list[float], list[float]]:
    """The calibration scores an AI model's registry row holds: its good and its NG images'."""
    m = model["metrics"] if isinstance(model["metrics"], dict) else json.loads(model["metrics"] or "{}")
    return list(m.get("ok_scores") or []), list(m.get("ng_scores") or [])


def commission(ctx: AppContext, bm: str, boards: list[Board], seed: int) -> list[dict[str, Any]]:
    """An applications engineer's day one after training, on the app's own features: each step with its screen path,
    the call that does it and what it set. A step the app has no feature for is recorded as missing."""
    steps: list[dict[str, Any]] = []
    rev, recipe = ctx.recipe(bm)
    try:
        learned = ctx.learn_comparison(bm, seed=seed)
        recipe = replace(recipe, **learned["chosen"])
        steps.append(
            {
                "step": "Learn From Labelled Boards",
                "screen": "Recipe Editor › Learn From Labelled Boards… › Use Learned Values",
                "call": "learn_comparison",
                "set": learned["chosen"],
                "held_out": learned["held_out"],
            }
        )
    except AoiError as e:
        steps.append({"step": "Learn From Labelled Boards", "refused": code_of(e)})
    insp = ctx.inspector(bm, recipe=recipe)
    values: dict[str, list[float]] = {}
    for b in boards:  # good boards never imported, judged on Compare with the recipe being edited, nothing saved
        for c in insp.inspect(ctx.load_image(b.path)).checks:
            if c.name in LIMIT_CHECKS:
                values.setdefault(c.name, []).append(float(c.value))
    lim = limits(values, recipe.warn_ratio)
    recipe = replace(recipe, **lim)
    steps.append(
        {
            "step": "Whole-board limits",
            "screen": "Recipe Editor › Thresholds (SSIM, Changed area,"
            " Difference regions), read off Compare for each commissioning board",
            "call": "inspector().inspect",
            "boards": len(boards),
            "seen": {k: [min(v), max(v)] for k, v in values.items()},
            "set": lim,
        }
    )
    model = ctx.active_model(bm)
    ok, ng = scores(model) if model else ([], [])
    if ok and ng:
        cut = best_cut(ok, ng)  # flagged from warn_ratio of the threshold on: the threshold puts that point at the cut
        recipe = replace(recipe, anomaly_threshold=round(cut / recipe.warn_ratio, 4))
        steps.append(
            {
                "step": "AI threshold",
                "screen": "Recipe Editor › Thresholds › AI threshold override",
                "call": "save_recipe(anomaly_threshold)",
                "cut": round(cut, 4),
                "set": recipe.anomaly_threshold,
                "calibrated": ctx.calibrated_threshold(bm),
                "missing": "no screen shows the calibration scores"
                " or offers the cut that separates them: the tool computed it from the registry row",
            }
        )
    else:
        steps.append({"step": "AI threshold", "refused": "no NG calibration scores to separate"})
    ctx.save_recipe(recipe, reason="commissioning, #459")
    steps += [{"step": k, **v} for k, v in MISSING.items()]
    return steps


def golden(ctx: AppContext, bm: str, ok: list[Board]) -> dict[str, Any]:
    """The commissioning step that makes the most typical good board imported the Golden board, as an Engineer."""
    first = Path(ctx.db.reference(bm) or "").name
    ctx.set_user("engineer")
    i = typical([b.path for b in ok])
    sha = manifest([ok[i].path])[str(ok[i].path)]
    sample = next(s for s in ctx.db.samples(bm, "OK") if s["sha256"] == sha)
    ctx.set_reference(bm, int(sample["id"]))
    screen = "Training › samples › Set as Golden board"
    return {
        "step": "Golden board",
        "screen": screen,
        "call": "set_reference",
        "chose": ok[i].path.name,
        "instead_of": first,
    }


def build(
    out: Path,
    bm: str,
    ok: list[Board],
    ng: list[Board],
    held: list[Board],
    seed: int,
    setup: str,
    epochs: int | None = None,
) -> dict[str, Any]:
    """One board model's station in `out/ws`, as shipped or as commissioned (`setup`); `held` are the commissioning
    boards, good boards never imported. Returns the record, with the locked boards by path."""
    out = out.resolve()
    shutil.rmtree(out, ignore_errors=True)
    (out / "result_files").mkdir(parents=True)
    settings = Settings(workspace=str(out / "ws"), device="cpu", output_folder=str(out / "result_files"))
    keys = credentials.MemoryCredentials()
    r: dict[str, Any] = {"board_model": bm, "setup": setup, "seed": seed, "epochs": epochs}
    r["imported"] = {"ok": len(ok), "ng": len(ng)}
    ctx, before = None, config.use_workspace(out / "ws")
    try:
        ctx = AppContext(settings, keys)
        ctx.set_user("admin")
        ctx.create_customer_board_model(bm, CUSTOMER)
        with os.fdopen(os.open(out / "store-keys.json", os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600), "w") as f:
            f.write(json.dumps({k: v.hex() for k, v in keys._secrets.items()}))  # no owner-only mode on Windows
        links = stage(out / "picked", ok, ng)
        report = ctx.import_files(bm, folder_files(out / "picked"))
        r["import"] = {"added": len(report.added), "refused": len(report.refused)}
        r["golden_first"] = Path(ctx.db.reference(bm) or "").name
        if setup == "commissioned":
            r["steps"] = [golden(ctx, bm, ok)]
        ctx.set_user("admin")
        version = ctx.freeze_dataset(bm, VIEW, REVISION, CUSTOMER, trial=True)
        assert version is not None
        split = ctx.lock_validation_set(version["uuid"], seed=seed)
        items = {i["uuid"]: i for i in ctx.dataset_items(version["uuid"])}
        by_sha = {s: links[p] for p, s in manifest(Path(p) for p in links).items()}
        r["locked"] = [str(by_sha[items[u]["sha256"]].path) for u in split["validation"]]
        ctx.set_user("engineer")
        reset_peak()
        t0 = time.perf_counter()
        meta = ctx.train(version["uuid"], epochs)
        r["training"] = {"s": round(time.perf_counter() - t0, 1), "peak_mb": peak_mb(), "version": meta["version"]}
        model = next(m for m in ctx.models(bm) if m["version"] == meta["version"])
        if (active := ctx.active_model(bm)) is None or active["id"] != model["id"]:
            ctx.activate_model(int(model["id"]))
        r["calibrated"] = ctx.calibrated_threshold(bm)
        if setup == "commissioned":
            r["steps"] += commission(ctx, bm, held, seed)
        metrics, rows, _ = ctx.test_dataset(version["uuid"])
        r["model_test"] = {k: metrics[k] for k in ("samples", "TP", "FN", "FP", "TN")}
        ctx.set_user("operator")
        r["shift_check"] = shift_check(ctx, bm)
    except Exception as e:  # recorded as the run met it: a finding, never hidden
        r["error"] = code_of(e)
    finally:
        if ctx is not None:
            ctx.close()
        config.use_workspace(before)
    (out / "station.json").write_text(json.dumps(r, indent=1, default=str), encoding="utf-8")
    return r


def shift_check(ctx: AppContext, bm: str, turn_off: bool = True) -> dict[str, Any]:
    """The shift check as an Operator runs it; when it fails and `turn_off`, an Admin turns it off on Settings so the
    scenario can measure at all, and the record says so."""
    try:
        got = ctx.run_shift_check(bm)
        out: dict[str, Any] = {
            "state": got["state"],
            "rows": [(x["expected"], x["verdict"]) for x in got["check"]["rows"]],
        }
    except AoiError as e:
        out = {"state": "not run", **code_of(e)}
    if out["state"] not in ("passed", "off") and turn_off:
        user = ctx.user
        ctx.set_user("admin")
        ctx.save_settings({"shift_check_hours": 0})
        ctx.set_user(user)
        out["then"] = "turned off by an Admin on Settings (shift_check_hours 0)"
    return out


def open_station(folder: Path, output: bool = True) -> tuple[AppContext, Path]:
    """The station built in `folder` opened again, as the station's PC starts the app; the caller closes it and
    restores the workspace it is given back."""
    folder = folder.resolve()
    before = config.use_workspace(folder / "ws")
    settings = Settings.load()
    settings.device, settings.output_folder = "cpu", str(folder / "result_files") if output else ""
    settings.workspace = str(folder / "ws")  # settings.json names the folder it was built in: a copy is its own
    keys = credentials.MemoryCredentials()
    for name, key in json.loads((folder / "store-keys.json").read_text()).items():
        keys.write(name, bytes.fromhex(key))
    return AppContext(settings, keys), before


def copy_station(src: Path, dst: Path) -> Path:
    shutil.rmtree(dst, ignore_errors=True)
    shutil.copytree(src, dst, ignore=shutil.ignore_patterns("picked"), symlinks=True)
    shutil.rmtree(dst / "result_files", ignore_errors=True)
    (dst / "result_files").mkdir()
    return dst
