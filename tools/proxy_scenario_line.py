"""The scenario drivers S9 and S10 of tools/proxy_scenarios.py (#459): the line's rate and endurance with the result
files on, and the faults a station meets on it (the drive at 95 %, the output folder unwritable, a kill mid-save and a
restart). Each judges a copy of a station that tools/proxy_scenario_runs.py builds; the kill runs the station in a child
process (`child`, this module run as a script). Linux only: the kill is SIGKILL, the folder is made unwritable with
chattr (as root, on ext2/3/4), and memory is read from /proc.
"""

from __future__ import annotations

import argparse
import itertools
import json
import os
import random
import shutil
import signal
import subprocess
import sys
import threading
import time
from collections import Counter
from pathlib import Path
from typing import Any

from aoi import config
from aoi.core import disk
from aoi.core.services import AppContext
from tools.proxy_judge import Frames, Item, judge
from tools.proxy_scenario_ops import first
from tools.proxy_scenario_runs import Scenario, held, station, verdicts
from tools.proxy_scenarios import BOARD_EVERY_S, backlog, shift, spread
from tools.proxy_station import copy_station, open_station
from tools.proxy_validation import Board

SAMPLE_EVERY = 360  # boards: an hour of the line at one every 10 s
CHILD_TIMEOUT_S = 600


class Paced(Frames):
    """Frames that arrive on the line's schedule: frame i is grabbed no sooner than `at[i]` seconds after the first;
    how late each is grabbed is its wait in the queue."""

    def __init__(self, items: list[Item], at: list[float]) -> None:
        super().__init__(items)
        self.at, self.start, self.late = at, 0.0, list[float]()

    def grab(self) -> Any:
        if not self.todo:
            return None
        now = time.perf_counter()
        if not self.late:
            self.start = now
        due = self.start + self.at[len(self.late)]
        if due > now:
            time.sleep(due - now)
        self.late.append(max(0.0, now - due))
        return super().grab()


def rss_mb() -> float | None:
    try:
        line = next(x for x in Path("/proc/self/status").read_text().splitlines() if x.startswith("VmRSS"))
        return round(int(line.split()[1]) / 1024, 1)
    except (OSError, StopIteration):
        return None


def load() -> float:
    """The machine's load over the last minute: other work on it slows the boards (os.getloadavg, not on Windows)."""
    return round(os.getloadavg()[0], 2)


def du_mb(folder: Path) -> float:
    return round(sum(p.stat().st_size for p in folder.rglob("*") if p.is_file()) / 1e6, 1)


def alerts(ws: Path, skip: int = 0) -> list[dict[str, Any]]:
    path = ws / "logs" / "alerts.jsonl"
    lines = path.read_text(encoding="utf-8").splitlines() if path.is_file() else []
    return [json.loads(x) for x in lines[skip:] if x.strip()]


def one_each(ctx: AppContext, folder: Path, rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Whether each board saved has exactly one record and one result file of each kind, and nothing else is there."""
    ids = [r["record_id"] for r in rows if r.get("record_id")]
    uuids = [str((ctx.inspection(i) or {}).get("uuid")) for i in ids]
    docs = [json.loads(p.read_text(encoding="utf-8")) for p in folder.glob("*.json")]
    named = Counter(str(d.get("record_uuid")) for d in docs)
    shift_rows = sum(max(0, len(p.read_text(encoding="utf-8").splitlines()) - 1) for p in folder.glob("shift_*.csv"))
    return {
        "boards": len(rows),
        "records": len(ids),
        "distinct_records": len(set(uuids)),
        "json": len(docs),
        "csv": len(list(folder.glob("*.csv"))) - len(list(folder.glob("shift_*.csv"))),
        "shift_csv_rows": shift_rows,
        "records_without_json": sum(u not in named for u in uuids),
        "json_twice": sum(v > 1 for v in named.values()),
        "json_without_record": len(set(named) - set(uuids)),
        "save_errors": sum(bool(r.get("save_error")) for r in rows),
    }


def s9(args: argparse.Namespace) -> dict[str, Any]:
    """S9: the line for `--hours` at one board every `--pace` seconds, then a burst of 100 at a fifth of that, with
    the result files on; times per board including the save, the queue, memory, disk, the heartbeat and alerts files,
    retention, and one record and one result file per board."""
    cat = first(args)
    every = (
        args.pace or BOARD_EVERY_S
    )  # the line's interval; with no pace the boards go back to back, the queue modelled
    n = round(args.hours * 3600 / every)
    with Scenario(args, cat, "line") as sc:
        good, bad = held(args, cat, sc.rec)
        arrivals = shift(len(good), len(bad), n, 0.01, args.seed) + shift(len(good), len(bad), 100, 0.01, args.seed + 1)
        boards = [(good if a["label"] == "OK" else bad)[a["index"]] for a in arrivals]
        gaps = [args.pace] * n + [args.pace / 5] * 99
        at = [0.0, *itertools.accumulate(gaps)]
        src, ws, files = Paced([(b, None, "") for b in boards], at), sc.dir / "ws", sc.dir / "result_files"
        skip, t0 = len(alerts(ws)), time.perf_counter()
        samples = [
            {"board": 0, "s": 0.0, "rss_mb": rss_mb(), "ws_mb": du_mb(ws), "files_mb": du_mb(files), "load": load()}
        ]

        def on(i: int, _: dict[str, Any]) -> None:
            if (i + 1) % SAMPLE_EVERY == 0 or i + 1 in (n, n + 100):
                samples.append(
                    {
                        "board": i + 1,
                        "s": round(time.perf_counter() - t0, 1),
                        "rss_mb": rss_mb(),
                        "ws_mb": du_mb(ws),
                        "files_mb": du_mb(files),
                        "load": load(),
                    }
                )

        rows = judge(sc.ctx, sc.bm, [], on, src=src)
        sc.ctx.set_user("admin")
        sweep = sc.ctx.sweep_retention()
        beat = (
            json.loads((ws / "heartbeat.json").read_text(encoding="utf-8"))
            if (ws / "heartbeat.json").is_file()
            else None
        )
        res: dict[str, Any] = {
            "boards": len(rows),
            "pace_s": args.pace,
            "hours": args.hours,
            "wall_s": round(time.perf_counter() - t0, 1),
            "line": {
                "ms": spread([r["wall_ms"] for r in rows[:n] if r.get("wall_ms")]),
                "engine_ms": spread([r["ms"] for r in rows[:n] if r.get("ms")]),
            },
            "burst": {"ms": spread([r["wall_ms"] for r in rows[n:] if r.get("wall_ms")])},
            "queue": {
                "every_s": every,
                "line": backlog([r.get("wall_ms", 0) / 1000 for r in rows[:n]], [every] * (len(rows[:n]) - 1)),
                "burst": backlog([r.get("wall_ms", 0) / 1000 for r in rows[n:]], [every / 5] * (len(rows[n:]) - 1)),
                "grabbed_late_s": spread(src.late) if src.late else None,
            },
            "samples": samples,
            "verdicts": verdicts(rows),
            "one_each": one_each(sc.ctx, files, rows),
            "retention": {
                "confirmed": sc.ctx.retention_confirmed() is not None,
                "sweep_at_end": sweep,
                "ok_evidence": sc.ctx.settings.ok_evidence,
            },
            "heartbeat": beat,
            "alerts": dict(Counter(str(a.get("code")) for a in alerts(ws, skip))),
        }
        base = samples[1] if len(samples) > 3 else samples[0]  # after the first hour: the AI model loaded, warm
        hours = max(1e-9, (samples[-1]["board"] - base["board"]) / SAMPLE_EVERY)
        res["per_360_boards"] = {"from_board": base["board"]} | {  # an hour of the line at one board every 10 s
            k: round((samples[-1][k] - base[k]) / hours, 1)
            for k in ("rss_mb", "ws_mb", "files_mb")
            if samples[-1][k] is not None
        }
    return res


def s10(args: argparse.Namespace) -> dict[str, Any]:
    """S10: the drive at 95 %, the output folder made unwritable mid-shift, and the station killed while it saves a
    board and started again; what was lost or kept twice, what the operator saw, and the time to inspect again."""
    cat = first(args)
    out: dict[str, Any] = {}
    with Scenario(args, cat, "faults") as sc:
        good, bad = held(args, cat, sc.rec)
        ws, files = sc.dir / "ws", sc.dir / "result_files"
        skip, real = len(alerts(ws)), disk.usage
        disk.usage = lambda folder: disk.Usage(1000, 950, 50)  # the drive at 95 % used, as tests put it there
        try:
            rows = judge(sc.ctx, sc.bm, [(b, None, "") for b in good[:40] + bad[:10]])
        finally:
            disk.usage = real
        recs = [sc.ctx.inspection(r["record_id"]) or {} for r in rows if r.get("record_id")]
        out["disk_95"] = {
            "verdicts": verdicts(rows),
            "records": len(recs),
            "one_each": one_each(sc.ctx, files, rows),
            "ok_without_overlay": sum(r.get("result") == "OK" and not r.get("overlay_path") for r in recs),
            "flagged_with_overlay": sum(r.get("result") != "OK" and bool(r.get("overlay_path")) for r in recs),
            "flagged": sum(r.get("result") != "OK" for r in recs),
            "alerts": not_ng(alerts(ws, skip)),
        }
        skip = len(alerts(ws))
        phases: dict[str, Any] = {}
        for name, boards in (("before", good[40:50]), ("unwritable", good[50:70] + bad[10:15]), ("after", good[70:80])):
            before = {p.name for p in files.glob("*.json")}
            if name == "unwritable" and not immutable(files, True):  # Linux, as root, on ext2/3/4
                phases[name] = {"skipped": "chattr +i refused: the folder cannot be made unwritable here"}
                continue
            try:
                rows = judge(sc.ctx, sc.bm, [(b, None, "") for b in boards])
            finally:
                if name == "unwritable" and immutable(files, False):
                    raise RuntimeError(f"{files} is still immutable: run chattr -i on it")
            phases[name] = {
                "boards": len(rows),
                "records": sum(bool(r.get("record_id")) for r in rows),
                "json_written": len({p.name for p in files.glob("*.json")} - before),
                "save_errors": sum(bool(r.get("save_error")) for r in rows),
            }
        out["output_unwritable"] = phases | {"alerts": not_ng(alerts(ws, skip))}
    out["kill"] = kills(args, cat)
    return out


def immutable(folder: Path, on: bool) -> bool:
    """Make `folder` immutable (`on`) or not with chattr; True when it is immutable afterwards."""
    subprocess.run(["chattr", "+i" if on else "-i", str(folder)], check=False, capture_output=True)
    try:
        (folder / ".probe").touch()
        (folder / ".probe").unlink()
        return False
    except OSError:
        return True


def not_ng(lines: list[dict[str, Any]]) -> list[tuple[str, str]]:
    """The alerts other than a board's NG (AOI-INSP-003, one a board), each code with its text."""
    return [(str(a["code"]), str(a["text"])[:200]) for a in lines if a.get("code") != "AOI-INSP-003"]


def kills(args: argparse.Namespace, cat: str) -> dict[str, Any]:
    """Three times: a child station judges boards and is killed (SIGKILL) a moment after it starts saving its fifth;
    a new child starts on the same workspace and judges the board in hand again and four more, as the operator puts
    the board back. Then the workspace is read: records lost or kept twice, files no record names, the heartbeat."""
    folder, rec = station(args, cat)
    dst = copy_station(folder, Path(args.out).resolve() / "runs" / f"S10-{args.config}-{cat}-kill")
    good, bad = held(args, cat, rec)
    boards = good[:24] + bad[:6]
    random.Random(args.seed).shuffle(boards)
    plan = dst / "boards.json"
    plan.write_text(json.dumps([[str(b.path), b.label, str(b.mask) if b.mask else None] for b in boards]))
    ctx, before_ws = open_station(dst)
    known = {r["id"] for r in ctx.inspections(board_model=cat.upper())}  # the station's own, from its build
    ctx.close()
    config.use_workspace(before_ws)
    trials = []
    for j, delay in enumerate((0.0, 0.05, 0.2)):
        start = j * 10
        killed = child(dst, cat.upper(), plan, start, start + 10, kill_at=start + 4, delay=delay)
        again = child(dst, cat.upper(), plan, killed["in_hand"], start + 10)
        trials.append({"delay_s": delay, "killed": killed, "restart": again})
    ctx, before_ws = open_station(dst)
    try:
        paths = {str(b.path.resolve()) for b in boards}
        recs = [r for r in ctx.inspections(board_model=cat.upper()) if r["id"] not in known]
        recs = [r for r in recs if str(Path(r["image_path"]).resolve()) in paths]
        per = Counter(str(Path(r["image_path"]).resolve()) for r in recs)
        named = ctx.db.evidence_paths()
        results = [
            p.resolve() for p in (dst / "ws" / "results").rglob("*") if p.is_file() and "test_runs" not in p.parts
        ]
        prev = {p for p in results if p.name.endswith("_prev.jpg")}
        docs = [json.loads(p.read_text(encoding="utf-8")) for p in (dst / "result_files").glob("*.json")]
        uuids = {r["uuid"] for r in recs}
        res = {
            "trials": trials,
            "boards": len(boards),
            "records": len(recs),
            "lost": sum(str(b.path.resolve()) not in per for b in boards),
            "kept_twice": sum(v > 1 for v in per.values()),
            "orphan_evidence": len(orphans := [p for p in results if p not in named and p not in prev]),
            "orphan_examples": [str(p.relative_to(dst)) for p in orphans[:5]],
            "json_without_record": sum(d.get("record_uuid") not in uuids for d in docs),
            "records_without_json": len(uuids - {d.get("record_uuid") for d in docs}),
            "temp_files": [
                p.name for p in dst.rglob("*") if p.is_file() and (".tmp" in p.name or p.name.startswith("~"))
            ][:10],
            "alarms_after": [(a["code"], str(a["message"])[:160]) for a in ctx.alarms()[:5]],
        }
    finally:
        ctx.close()
        config.use_workspace(before_ws)
    shutil.rmtree(dst / "ws" / "results", ignore_errors=True)
    return res


def child(
    dst: Path, bm: str, plan: Path, start: int, stop: int, kill_at: int | None = None, delay: float = 0.0
) -> dict[str, Any]:
    """Run boards[start:stop] in a child station on `dst`; with `kill_at`, SIGKILL it `delay` s after it starts saving
    that board. Returns what the child said: when it judged its first board, and the board in hand when it died."""
    t0 = time.perf_counter()
    cmd = [sys.executable, "-m", "tools.proxy_scenario_line", str(dst), bm, str(plan), str(start), str(stop)]
    log = dst / f"child-{start}-{kill_at}.log"  # its stderr, kept for a run that goes wrong
    with open(log, "w", encoding="utf-8") as err:
        p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=err, text=True, cwd=Path(__file__).parents[1])
    said: dict[str, Any] = {"start": start, "in_hand": start, "saved": []}
    timer = threading.Timer(CHILD_TIMEOUT_S, p.kill)  # a child stuck short of `kill_at` is ended, and says so
    timer.start()
    assert p.stdout is not None
    for line in p.stdout:
        if not line.startswith("@@ "):
            continue
        kind, *rest = line.split()[1:]
        if kind == "OPEN":
            said["s_to_open"] = round(time.perf_counter() - t0, 2)
        elif kind == "SAVING":
            said["in_hand"] = int(rest[0])
            if kill_at is not None and int(rest[0]) == kill_at:
                time.sleep(delay)
                p.send_signal(signal.SIGKILL)
                said["killed_at"] = kill_at
        elif kind == "SAVED":
            said["saved"].append(int(rest[0]))
            said.setdefault("s_to_first_verdict", round(time.perf_counter() - t0, 2))
        elif kind == "REFUSED":
            said.setdefault("refused", []).append(" ".join(rest)[:200])
    said["exit"] = p.wait()
    timer.cancel()
    if kill_at is not None and "killed_at" not in said:  # the kill never came: the trial measures nothing
        raise RuntimeError(f"the child stopped before board {kill_at} (exit {said['exit']}); see {log}")
    return said


def _child(argv: list[str]) -> None:
    """The child station: open the workspace, judge boards[start:stop], and say each step on stdout, flushed."""
    dst, bm, plan, start, stop = Path(argv[0]), argv[1], Path(argv[2]), int(argv[3]), int(argv[4])
    boards = [Board(Path(p), lab, (), Path(m) if m else None) for p, lab, m in json.loads(plan.read_text())]
    ctx, _ = open_station(dst)
    ctx.set_user("operator")
    print("@@ OPEN", flush=True)
    real, index = ctx.log_result, {str(b.path): i for i, b in enumerate(boards)}

    def log_result(board_model: str, path: str, *a: Any, **k: Any) -> int:  # the board's place, by its file
        print(f"@@ SAVING {index[path]}", flush=True)
        iid = real(board_model, path, *a, **k)
        print(f"@@ SAVED {index[path]} {iid}", flush=True)
        return iid

    ctx.log_result = log_result  # type: ignore[method-assign]
    for r in judge(ctx, bm, [(b, None, "") for b in boards[start:stop]]):
        if r.get("refused"):
            print(f"@@ REFUSED {r['refused']}", flush=True)
    ctx.close()


LINE = {"S9": s9, "S10": s10}

if __name__ == "__main__":
    _child(sys.argv[1:])
