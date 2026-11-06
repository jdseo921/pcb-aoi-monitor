"""The scenario drivers S7, S8 and S11 of tools/proxy_scenarios.py (#459): repeatability, changeover and the
operator's review loop. Each judges a copy of a station that tools/proxy_scenario_runs.py builds; the line's rate and
faults (S9, S10) are in tools/proxy_scenario_line.py."""

from __future__ import annotations

import argparse
import random
import time
from collections import Counter
from pathlib import Path
from typing import Any

import cv2

from aoi.core.sample_import import folder_files
from aoi.core.services import AppContext
from tools.proxy_frames import reshot, revised
from tools.proxy_judge import Item, judge
from tools.proxy_scenario_runs import COMMISSIONING, IMPORTED, Scenario, data, held, verdicts
from tools.proxy_scenarios import flips, line_counts
from tools.proxy_stage1 import CUSTOMER, REVISION, VIEW, code_of, stage
from tools.proxy_station import commission, golden, shift_check
from tools.proxy_validation import Board, upper_95

GUIDE_ACTIONS = 24  # tests/test_guide_click_count.py: an empty workspace to the first verdict, on 4 screens


def first(args: argparse.Namespace) -> str:
    return str(args.categories.split(",")[0])


def s7(args: argparse.Namespace) -> dict[str, Any]:
    """S7: 30 held-out good and 30 defective boards, each shot 10 times (`reshot`); a board flips when its shots do not
    all get the same verdict."""
    cat = first(args)
    with Scenario(args, cat, "repeat") as sc:
        good, bad = held(args, cat, sc.rec)
        boards = good[:30] + bad[:30]
        items: list[Item] = [
            (b, (lambda im, m, s=args.seed * 100_000 + i * 10 + k: reshot(im, m, random.Random(s))), f"r{k}")
            for i, b in enumerate(boards)
            for k in range(10)
        ]
        rows = judge(sc.ctx, sc.bm, items)
    out: dict[str, Any] = {}
    for label in ("OK", "NG"):
        shots: dict[str, list[str]] = {}
        for r in rows:
            if r["label"] == label:
                shots.setdefault(r["board"], []).append(str(r["verdict"] or r["refused"]["code"]))
        n = flips(shots)
        out["good" if label == "OK" else "defective"] = {
            "boards": len(shots),
            "flipped": n,
            "flipped_upper_95": upper_95(n, len(shots)),
            "shots": verdicts([r for r in rows if r["label"] == label]),
            "patterns": dict(
                Counter("/".join(f"{k}{v}" for k, v in sorted(Counter(s).items())) for s in shots.values())
            ),
        }
    return out


def add_model(
    ctx: AppContext,
    folder: Path,
    bm: str,
    ok: list[Board],
    ng: list[Board],
    args: argparse.Namespace,
    commissioning: list[Board],
) -> dict[str, Any]:
    """A new board model made in a running station from its images, as the first-run guide's one press makes it,
    commissioned as `build` commissions one when the setup is; timed from the import to a station that judges."""
    t0, r = time.perf_counter(), {"board_model": bm, "imported": {"ok": len(ok), "ng": len(ng)}}
    try:
        ctx.set_user("admin")
        ctx.create_customer_board_model(bm, CUSTOMER)
        stage(folder / f"picked-{bm}", ok, ng)
        rep = ctx.import_files(bm, folder_files(folder / f"picked-{bm}"))
        r["import"] = {"added": len(rep.added), "refused": len(rep.refused)}
        if args.config == "commissioned":
            r["steps"] = [golden(ctx, bm, ok)]
        ctx.set_user("engineer")
        g = ctx.guide_train(bm, VIEW, REVISION, args.epochs)
        r["guide"] = {
            "held": g["held"],
            "trained": g["trained"],
            "not_run": g["not_run"],
            "shift": (g["shift"] or {}).get("state"),
            "model": g["model"]["version"],
        }
        if args.config == "commissioned":
            r["steps"] += commission(ctx, bm, commissioning, args.seed)
        ctx.set_user("operator")
        r["shift_check"] = shift_check(ctx, bm)
    except Exception as e:  # recorded as the run met it: a finding, never hidden
        r["error"] = code_of(e)
    r["s_to_working"] = round(time.perf_counter() - t0, 1)
    r["actions"] = f"{GUIDE_ACTIONS} on 4 screens as tests/test_guide_click_count.py counts the guide's path"
    return r


def write_revised(boards: list[Board], folder: Path) -> list[Board]:
    """Each board's photo as its next revision (`revised`), written as a file the station imports or reads."""
    folder.mkdir(parents=True, exist_ok=True)
    out = []
    for b in boards:
        p = folder / f"{b.label.lower()}{b.path.stem}_rev{b.path.suffix}"  # good and NG names may meet
        cv2.imwrite(str(p), revised(cv2.imread(str(b.path), cv2.IMREAD_COLOR)), [cv2.IMWRITE_JPEG_QUALITY, 95])
        out.append(Board(p, b.label, b.kinds, b.mask, b.boxes))
    return out


def write_reshot(boards: list[Board], folder: Path, seed: int) -> list[Board]:
    """Each board photographed again (`reshot`), written as a new file, so its image is one the station never held."""
    folder.mkdir(parents=True, exist_ok=True)
    out = []
    for i, b in enumerate(boards):
        p = folder / f"{b.label.lower()}{b.path.stem}_shot{b.path.suffix}"
        img, _ = reshot(cv2.imread(str(b.path), cv2.IMREAD_COLOR), None, random.Random(seed * 1000 + i))
        cv2.imwrite(str(p), img, [cv2.IMWRITE_JPEG_QUALITY, 95])
        out.append(Board(p, b.label, b.kinds, b.mask, b.boxes))
    return out


def s8(args: argparse.Namespace) -> dict[str, Any]:
    """S8: in one station, the other category's boards judged with this one's board model picked by mistake; that
    board model made in the same station and the line changed over to it and back; and the board's next revision made
    as a new board model from 70 good images, timed, then each board model shown the other's boards."""
    cat = first(args)
    other = "pcb2" if cat != "pcb2" else "pcb3"
    out: dict[str, Any] = {}
    with Scenario(args, cat, "changeover") as sc:
        good, bad = held(args, cat, sc.rec)
        o_extra, o_pool, o_ng = data(args, other)
        files = sc.dir / "S8-files"
        # the other board model as its station was built, but 10 defective boards kept back to show it unseen
        out[f"add_{other}"] = add_model(sc.ctx, sc.dir, other.upper(), o_pool[:200], o_ng[10:], args, o_pool[200:260])
        rev_bm = f"{sc.bm}R2"
        extra, _, ng = data(args, cat)
        locked = set(sc.rec["locked"])
        spare = [b for b in ng if str(b.path) not in locked]
        rev_ok = write_revised(extra[:150], files / "rev")  # 70 imported, 30 to commission on, 50 never seen
        rev_ng = write_revised(spare[:10] + bad, files / "rev")  # 10 imported, the 30 locked never seen
        out["revision"] = add_model(sc.ctx, sc.dir, rev_bm, rev_ok[:70], rev_ng[:10], args, rev_ok[70:100])
        sc.ctx.set_user("operator")
        cycle = sc.ctx.inspection_cycle()  # the page's own, as the operator changes the board model on it
        o_good = [(b, None, "") for b in o_extra[:20]]
        o_bad = [(b, None, "") for b in o_ng[:10]]
        steps = [
            (f"{other} boards, {sc.bm} picked by mistake", sc.bm, o_good + o_bad),
            (f"changed over to {other.upper()}", other.upper(), o_good + o_bad),
            (f"changed back to {sc.bm}", sc.bm, [(b, None, "") for b in good[:20] + bad[:10]]),
            (f"revision boards, {sc.bm} picked", sc.bm, [(b, None, "") for b in rev_ok[100:120] + rev_ng[10:20]]),
            (f"changed over to {rev_bm}", rev_bm, [(b, None, "") for b in rev_ok[100:150] + rev_ng[10:]]),
            (f"{sc.bm} boards, {rev_bm} picked by mistake", rev_bm, [(b, None, "") for b in good[:20] + bad[:10]]),
        ]
        out["sequence"] = []
        for name, bm, items in steps:
            t0 = time.perf_counter()
            rows = judge(sc.ctx, bm, items, cycle=cycle)
            first_ms = rows[0].get("wall_ms") if rows else None
            out["sequence"].append(
                {
                    "step": name,
                    "picked": bm,
                    "good": verdicts([r for r in rows if r.get("label") == "OK"]),
                    "defective": verdicts([r for r in rows if r.get("label") == "NG"]),
                    "ok": sum(r["verdict"] == "OK" for r in rows),
                    "counts": line_counts(rows),
                    "first_board_ms": first_ms,
                    "s": round(time.perf_counter() - t0, 1),
                    "refused": [r["refused"] for r in rows if r.get("refused")][:3],
                }
            )
    return out


def s11(args: argparse.Namespace) -> dict[str, Any]:
    """S11: a shift of 100 good boards never imported and 15 locked defective boards; every NG and WARN reviewed by
    its truth, the false calls added to Training as good, a new Trial version trained and activated, then a second
    one with five real defects wrongly added as good, as a hurried review does; each new AI model judged on the old
    locked set and on 100 more good and the other 15 defective boards, against the old one."""
    cat = first(args)
    with Scenario(args, cat, "review") as sc:
        good, bad = held(args, cat, sc.rec)
        extra = good[-200:]  # the 200 never imported
        # the defective boards photographed again on this shift, as new files: every NG image VisA has is imported
        shot = write_reshot(bad[:15], sc.dir / "S11-files", args.seed)
        shift_items = [(b, None, "") for b in extra[:100] + shot]
        later = [(b, None, "") for b in extra[100:] + bad[15:]]
        ctx, out = sc.ctx, {"old": {"model_test": sc.rec.get("model_test")}}
        rows = judge(ctx, sc.bm, shift_items)
        out["old"]["later"] = line_counts(judge(ctx, sc.bm, later))
        reviewed = Counter()
        for r in rows:
            if r["verdict"] in ("NG", "WARN") and r.get("record_id"):
                real = r["label"] == "NG"
                ctx.review_result(
                    r["record_id"], "DEFECT" if real else "FALSE_CALL", None if real else "good by its truth"
                )
                reviewed["DEFECT" if real else "FALSE_CALL"] += 1
        out["shift"] = line_counts(rows) | {"reviewed": dict(reviewed)}
        hurried = [r for r in rows if r["label"] == "NG" and r["verdict"] in ("NG", "WARN") and r.get("record_id")][:5]
        first_model = ctx.active_model(sc.bm)
        old_version = ctx.trial_version(first_model) if first_model else None  # the locked set both are tested on
        for name, wrong in (("retrained", []), ("retrained_with_5_defects_as_good", hurried)):
            ctx.set_user("operator")
            for r in wrong:
                ctx.review_result(r["record_id"], "FALSE_CALL", "hurried review")
            calls = [r for r in rows if r["label"] == "OK" and r["verdict"] in ("NG", "WARN")] + wrong
            commissioning = data(args, cat)[1][IMPORTED : IMPORTED + COMMISSIONING]
            out[name] = retrain(ctx, sc, args, calls, later, commissioning, old_version)
    return out


def retrain(
    ctx: AppContext,
    sc: Scenario,
    args: argparse.Namespace,
    calls: list[dict[str, Any]],
    later: list[Item],
    commissioning: list[Board],
    old_version: dict[str, Any] | None,
) -> dict[str, Any]:
    """The false calls added to Training as good, a new Trial version frozen, locked, trained and activated; the new
    AI model tested on the first version's locked set and judged on the later boards."""
    res: dict[str, Any] = {}
    try:
        ctx.set_user("engineer")
        res["added"] = sum(ctx.add_false_call_sample(r["record_id"])["added"] for r in calls if r.get("record_id"))
        ctx.set_user("admin")
        version = ctx.freeze_dataset(sc.bm, VIEW, REVISION, CUSTOMER, trial=True)
        assert version is not None
        ctx.lock_validation_set(version["uuid"], seed=args.seed)
        ctx.set_user("engineer")
        meta = ctx.train(version["uuid"], args.epochs)
        model = next(m for m in ctx.models(sc.bm) if m["version"] == meta["version"])
        try:
            if (ctx.active_model(sc.bm) or {}).get("id") != model["id"]:
                ctx.activate_model(int(model["id"]))
            now = (ctx.active_model(sc.bm) or {}).get("version")
            res["activation"] = {"active_after": now, "accepted": now == meta["version"]}
        except Exception as e:  # the gate refusing it is what S11 looks for
            res["activation"] = {"refused": code_of(e)}
        res["model"] = meta["version"]
        if args.config == "commissioned":  # the override was cut for the old AI model's scores: cut again
            res["steps"] = commission(ctx, sc.bm, commissioning, args.seed)
        if old_version is not None:
            m, _, _ = ctx.test_dataset(old_version["uuid"])
            res["old_locked_set"] = {k: m[k] for k in ("samples", "TP", "FN", "FP", "TN")}
        ctx.set_user("operator")
        res["later"] = line_counts(judge(ctx, sc.bm, later))
    except Exception as e:  # recorded as the run met it: a finding, never hidden
        res["error"] = code_of(e)
    return res


OPS = {"S7": s7, "S8": s8, "S11": s11}
