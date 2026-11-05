"""The scenario drivers of tools/proxy_scenarios.py (#459): S1 to S6 here, S7, S8 and S11 in
tools/proxy_scenario_ops.py, S9 and S10 in tools/proxy_scenario_line.py.

Every scenario runs on stations built once per category and setup (`station`): VisA's good boards are shuffled with
the seed; the first 200 are never imported (held out), the next 200 are imported with all 100 anomalous boards, and
the 60 after them are the commissioning boards. A scenario judges a copy of the station, so no scenario's records
reach another's. The held-out boards are the 50 good and 30 defective boards the station locked, and the 200 good
boards never imported.
"""

from __future__ import annotations

import argparse
import math
import random
import shutil
from collections import Counter
from pathlib import Path
from typing import Any

import cv2

from aoi import config
from tools.proxy_frames import bad_frames, drift, drifted, placed, placement, variations
from tools.proxy_judge import judge
from tools.proxy_scenarios import line_counts, shift
from tools.proxy_stage1 import code_of
from tools.proxy_station import build, copy_station, open_station, shift_check
from tools.proxy_validation import Board, pools, upper_95, visa_index

EXTRA, IMPORTED, COMMISSIONING = 200, 200, 60
S6_IMPORTS = {0: 0, 3: 5, 10: 15, 30: 43}  # NG imported for 0, 3, 10 and 30 to calibrate on, the lock taking 30 %


def data(args: argparse.Namespace, cat: str) -> tuple[list[Board], list[Board], list[Board]]:
    extra, pool, ng = pools(visa_index(Path(args.data), cat), args.seed, EXTRA)
    return extra, pool, ng


def station(
    args: argparse.Namespace, cat: str, ng: list[Board] | None = None, name: str | None = None
) -> tuple[Path, dict[str, Any]]:
    """The category's station in this setup, built when no good one of this seed is there yet."""
    import json

    folder = Path(args.out).resolve() / "stations" / (name or f"{cat}-{args.config}")
    extra, pool, all_ng = data(args, cat)
    rec_path = folder / "station.json"
    if rec_path.is_file():
        rec = json.loads(rec_path.read_text(encoding="utf-8"))
        if "error" not in rec and (rec.get("seed"), rec.get("epochs")) == (args.seed, args.epochs):
            return folder, rec
    held = pool[IMPORTED : IMPORTED + COMMISSIONING]
    rec = build(
        folder, cat.upper(), pool[:IMPORTED], all_ng if ng is None else ng, held, args.seed, args.config, args.epochs
    )
    return folder, rec


def held(args: argparse.Namespace, cat: str, rec: dict[str, Any]) -> tuple[list[Board], list[Board]]:
    """The station's held-out boards: (good, defective)."""
    extra, pool, ng = data(args, cat)
    locked = set(rec["locked"])
    good = [b for b in pool[:IMPORTED] if str(b.path) in locked] + extra
    return good, [b for b in ng if str(b.path) in locked]


class Scenario:
    """A copy of a station opened as the line's PC opens it, signed in as the Operator; closed on exit."""

    def __init__(self, args: argparse.Namespace, cat: str, tag: str, output: bool = True) -> None:
        self.folder, self.rec = station(args, cat)
        self.dir = copy_station(
            self.folder, Path(args.out).resolve() / "runs" / f"{args.scenario}-{args.config}-{cat}-{tag}"
        )
        self.ctx, self.before = open_station(self.dir, output)
        self.ctx.set_user("operator")
        self.bm = cat.upper()

    def __enter__(self) -> Scenario:
        return self

    def prune(self, i: int, _: object = None) -> None:
        """Every 200 boards, the evidence files saved so far deleted, as a long run would fill the VM's disk; the
        records stay, and no scenario that prunes reads the evidence."""
        if (i + 1) % 200 == 0:
            for day in (self.dir / "ws" / "results").glob("20*"):
                shutil.rmtree(day, ignore_errors=True)

    def __exit__(self, *_: object) -> None:
        self.ctx.close()
        config.use_workspace(self.before)
        shutil.rmtree(self.dir / "ws" / "results", ignore_errors=True)  # the evidence: GBs a run, counted already


def verdicts(rows: list[dict[str, Any]]) -> dict[str, int]:
    return dict(Counter(str(r["verdict"]) if r["verdict"] else f"refused {r['refused']['code']}" for r in rows))


def s1(args: argparse.Namespace) -> dict[str, Any]:
    """S1: each held-out board judged once; the shift of 2,000 at 1 % and at 0.2 % defective composed from those
    verdicts, the engine being deterministic; on the first category the 1 % shift also runs board by board, to show
    the composition gives the same verdicts."""
    out: dict[str, Any] = {}
    for n, cat in enumerate(args.categories.split(",")):
        with Scenario(args, cat, "baseline") as sc:
            good, bad = held(args, cat, sc.rec)
            rows = judge(sc.ctx, sc.bm, [(b, None, "") for b in good + bad])
        by = {("OK", i): r for i, r in enumerate(rows[: len(good)])} | {
            ("NG", i): r for i, r in enumerate(rows[len(good) :])
        }
        res: dict[str, Any] = {
            "station": {k: sc.rec.get(k) for k in ("training", "calibrated", "model_test", "shift_check", "steps")},
            "held_out": {"good": verdicts(rows[: len(good)]), "defective": verdicts(rows[len(good) :])},
        }
        for rate in (0.01, 0.002):
            arrivals = shift(len(good), len(bad), 2000, rate, args.seed)
            line = [by[(a["label"], a["index"])] | {"reuse": a["reuse"]} for a in arrivals]
            res[f"shift_{rate}"] = line_counts(line) | {"reused": sum(a["reuse"] > 0 for a in arrivals)}
        if n == 0:  # the 1 % shift board by board, in arrival order
            arrivals = shift(len(good), len(bad), 2000, 0.01, args.seed)
            with Scenario(args, cat, "shift") as sc:
                items = [((good if a["label"] == "OK" else bad)[a["index"]], None, "") for a in arrivals]
                real = judge(sc.ctx, sc.bm, items, sc.prune)
            res["shift_0.01_board_by_board"] = line_counts(real) | {
                "same_verdicts": sum(
                    r["verdict"] == by[(a["label"], a["index"])]["verdict"] for r, a in zip(real, arrivals, strict=True)
                )
            }
        out[cat] = res
    return out


def s2(args: argparse.Namespace) -> dict[str, Any]:
    """S2: 2,000 boards at 1 % defective while the camera drifts (`drift`), the shift check run at the start, at board
    1,440 (4 h at 10 s a board) and at the end, and the drift monitor's alarms placed by board."""
    cat = args.categories.split(",")[0]
    with Scenario(args, cat, "drift") as sc:
        good, bad = held(args, cat, sc.rec)
        arrivals = shift(len(good), len(bad), 2000, 0.01, args.seed)
        checks: dict[int, Any] = {0: shift_check(sc.ctx, sc.bm, turn_off=False)}
        seen, alarmed = drift_alarms(sc.ctx), list[dict[str, Any]]()

        def at(i: int, _: dict[str, Any]) -> None:  # an alarm names no record: it is placed by the board it followed
            nonlocal seen
            if len(now := drift_alarms(sc.ctx)) > len(seen):
                alarmed.extend({"board": i, "text": str(a.get("message", ""))[:300]} for a in now[len(seen) :])
                seen = now
            if i + 1 in (1440, 2000):
                checks[i + 1] = shift_check(sc.ctx, sc.bm, turn_off=False)
            sc.prune(i)

        items = [
            (
                (good if a["label"] == "OK" else bad)[a["index"]],
                (lambda im, m, i=i: drifted(im, m, drift(i, 2000))),
                f"d{i}",
            )
            for i, a in enumerate(arrivals)
        ]
        rows = judge(sc.ctx, sc.bm, items, at)
    windows = [line_counts(rows[i : i + 200]) for i in range(0, 2000, 200)]
    first_fc = next((i for i, r in enumerate(rows) if r["label"] == "OK" and r["verdict"] in ("WARN", "NG")), None)
    return {
        "windows": windows,
        "first_false_call": first_fc,
        "shift_checks": checks,
        "line": line_counts(rows),
        "drift_alarms": alarmed,
    }


def drift_alarms(ctx: Any) -> list[dict[str, Any]]:
    """The drift monitor's alarms (AOI-INSP-018, REQ-INSP-019) so far, oldest first: read from the table, as the
    alarm list keeps only the newest and a shift's NG alarms push them out."""
    return list(ctx.db.query("SELECT id, message FROM alarms WHERE code = ? ORDER BY id", ("AOI-INSP-018",)))


def s3(args: argparse.Namespace) -> dict[str, Any]:
    """S3: every held-out board placed at random (`placement`, 1 in 200 backwards), then 20 good and 10 defective
    boards loaded backwards on purpose; a backwards board must never be OK."""
    cat = args.categories.split(",")[0]
    rng = random.Random(args.seed)
    with Scenario(args, cat, "placement") as sc:
        good, bad = held(args, cat, sc.rec)
        items, where = [], []
        for b in good + bad:
            p = placement(rng)
            items.append((b, lambda im, m, p=p: placed(im, m, p["angle"], p["dx"], p["dy"]), "placed"))
            where.append(p)
        for b in good[:20] + bad[:10]:
            p = {"angle": 180 + rng.uniform(-5, 5), "dx": rng.uniform(-60, 60), "dy": rng.uniform(-60, 60)}
            items.append((b, lambda im, m, p=p: placed(im, m, p["angle"], p["dx"], p["dy"]), "backwards"))
            where.append(p)
        rows = judge(sc.ctx, sc.bm, items)
    for r, p in zip(rows, where, strict=True):
        r["placement"] = p
        r["backwards"] = abs(math.remainder(p["angle"], 360)) > 90
    groups = {"placed": [r for r in rows if not r["backwards"]], "backwards": [r for r in rows if r["backwards"]]}

    def aligned(r: dict[str, Any]) -> bool:
        return r.get("checks", {}).get("Alignment inliers", ("INFO",))[0] == "INFO"

    return {
        k: {
            "good": verdicts([r for r in g if r["label"] == "OK"]),
            "defective": verdicts([r for r in g if r["label"] == "NG"]),
            "counts": line_counts(g),
            "alignment_failed": sum(not aligned(r) for r in g),
            "alignment_failed_verdicts": verdicts([r for r in g if not aligned(r)]),
            "inliers": sorted(
                r["checks"]["Alignment inliers"][1] for r in g if "Alignment inliers" in r.get("checks", {})
            )[:: max(1, len(g) // 10)],
            "ok": sum(r["verdict"] == "OK" for r in g),
        }
        for k, g in groups.items()
    }


def s4(args: argparse.Namespace) -> dict[str, Any]:
    """S4: images that are not a proper photo of the right board, each case on five held-out good boards: made in
    memory (`bad_frames`), or written as files the cycle reads itself. The rule: never OK."""
    from PIL import Image

    cat = args.categories.split(",")[0]
    files = Path(args.out).resolve() / "S4-files" / args.config
    shutil.rmtree(files, ignore_errors=True)
    files.mkdir(parents=True)
    other = "pcb2" if cat != "pcb2" else "pcb3"
    with Scenario(args, cat, "bad") as sc:
        good, _ = held(args, cat, sc.rec)
        five = good[:5]
        items: list[Any] = [
            (b, (lambda im, m, f=f: (f(im), m)), name) for name, f in bad_frames().items() for b in five
        ]
        for i, b in enumerate(five):
            raw = b.path.read_bytes()
            made = {
                "truncated file": files / f"trunc{i}.jpg",
                "zero-byte file": files / f"zero{i}.jpg",
                "duplicate file": files / f"dup{i}.jpg",
                "16-bit TIFF": files / f"tiff16_{i}.tif",
                "CMYK JPEG": files / f"cmyk{i}.jpg",
                "EXIF rotation": files / f"exif{i}.jpg",
            }
            made["truncated file"].write_bytes(raw[: len(raw) * 2 // 5])
            made["zero-byte file"].write_bytes(b"")
            made["duplicate file"].write_bytes(raw)
            img = cv2.imread(str(b.path), cv2.IMREAD_COLOR)
            cv2.imwrite(str(made["16-bit TIFF"]), img.astype("uint16") * 257)
            with Image.open(b.path) as pil:
                pil.convert("CMYK").save(made["CMYK JPEG"], quality=95)
                exif = pil.getexif()
                exif[0x0112] = 6  # shown turned 90 degrees clockwise: the pixels lie a quarter turn the other way
                pil.transpose(Image.Transpose.ROTATE_90).save(made["EXIF rotation"], exif=exif, quality=95)
            items += [(Board(p, "OK"), None, name) for name, p in made.items()]
        items += [(b, None, f"a {other} board shown to the {cat} model") for b in data(args, other)[0][:5]]
        rows = judge(sc.ctx, sc.bm, items)
    cases: dict[str, Any] = {}
    for r in rows:
        c = cases.setdefault(r["tag"], {"verdicts": Counter(), "ok": 0})
        c["verdicts"][r["verdict"] or r["refused"]["code"]] += 1
        c["ok"] += r["verdict"] == "OK"
        if r.get("refused"):
            c.setdefault("refusal", r["refused"]["text"][:300])
    return {
        "cases": {k: v | {"verdicts": dict(v["verdicts"])} for k, v in cases.items()},
        "came_out_ok": {k: v["ok"] for k, v in cases.items() if v["ok"]},
    }


def s5(args: argparse.Namespace) -> dict[str, Any]:
    """S5: 50 held-out good boards, each changed the ways a good board varies (`variations`), against the same 50
    unchanged."""
    cat = args.categories.split(",")[0]
    with Scenario(args, cat, "variation") as sc:
        good, _ = held(args, cat, sc.rec)
        fifty = good[:50]
        items: list[Any] = [(b, None, "unchanged") for b in fifty]
        for name, f in variations().items():
            items += [
                (b, (lambda im, m, f=f, s=args.seed * 1000 + i: (f(im, random.Random(s)), m)), name)
                for i, b in enumerate(fifty)
            ]
        rows = judge(sc.ctx, sc.bm, items)
    out: dict[str, Any] = {}
    for tag in ["unchanged", *variations()]:
        g = [r for r in rows if r["tag"] == tag]
        fc = sum(r["verdict"] in ("WARN", "NG") for r in g)
        out[tag] = {
            "boards": len(g),
            "verdicts": verdicts(g),
            "false_calls": fc,
            "false_calls_upper_95": upper_95(fc, len(g)),
        }
    return out


def s6(args: argparse.Namespace) -> dict[str, Any]:
    """S6: a station per number of NG boards to calibrate on (0, 3, 10, 30), each built from the 200 good boards and
    NG boards the main station never locked; judged on the 200 good boards never imported and the main station's 30
    locked defective boards, which none of these stations saw."""
    cat = args.categories.split(",")[0]
    main, rec = station(args, cat)
    extra, _, ng = data(args, cat)
    locked = set(rec["locked"])
    spare = [b for b in ng if str(b.path) not in locked]
    bad = [b for b in ng if str(b.path) in locked]
    out: dict[str, Any] = {}
    for n, m in S6_IMPORTS.items():
        folder, r = station(args, cat, spare[:m], f"{cat}-{args.config}-ng{n}")
        res: dict[str, Any] = {
            "imported_ng": m,
            **{k: r.get(k) for k in ("error", "calibrated", "steps", "shift_check")},
        }
        if "error" not in r:
            dst = copy_station(folder, Path(args.out).resolve() / "runs" / f"S6-{args.config}-{cat}-ng{n}")
            ctx, before = open_station(dst)
            try:
                ctx.set_user("operator")
                cal = sum(1 for s in ctx.db.samples(cat.upper(), "NG")) - sum(
                    1 for p in r["locked"] if Path(p).parent.name == "Anomaly"
                )
                rows = judge(ctx, cat.upper(), [(b, None, "") for b in extra + bad])
                res |= {
                    "calibration_ng": cal,
                    "line": line_counts(rows),
                    "good": verdicts(rows[: len(extra)]),
                    "defective": verdicts(rows[len(extra) :]),
                }
            except Exception as e:  # recorded, never hidden
                res["error"] = code_of(e)
            finally:
                ctx.close()
                config.use_workspace(before)
                shutil.rmtree(dst / "ws" / "results", ignore_errors=True)
        out[f"ng{n}"] = res
    return out


def run(args: argparse.Namespace) -> dict[str, Any]:
    from tools.proxy_scenario_line import LINE
    from tools.proxy_scenario_ops import OPS

    drivers = {"S1": s1, "S2": s2, "S3": s3, "S4": s4, "S5": s5, "S6": s6, **OPS, **LINE}
    try:
        return {"scenario": args.scenario, "config": args.config, "seed": args.seed, **drivers[args.scenario](args)}
    except Exception as e:  # recorded as the run met it: a finding, never hidden
        return {"scenario": args.scenario, "config": args.config, "error": code_of(e)}
