"""A workspace at the scale REQ-SET-020 is measured on: 50 board models and 100,000 inspection records (stage S55).

    python tools/seed_workspace.py <new workspace folder> [--board-models 50] [--records 100000] [--days 100]

The board models are created through AppContext, as + New creates them: each with its default recipe revision and its
audit entry. The records are written straight into the database in one transaction, as many as a station stores in
months, rather than inspected one by one: each as AppContext.log_result stores one, with the row, the whole result as
JSON, its checks, an NG or WARN record's defects and an NG record's alarm, but with no image, overlay or map file
behind it, so a page that opens one finds its files missing. They are spread over the last `days` days, oldest first;
those older than the retention setting are archived and the OK ones older than the map retention name no map, as the
start-up archive and sweep leave them, so the next start has nothing of either to do.

Their verdicts are drawn at random: nothing here is an accuracy. The records name an AI model version "v1" that no
AI model file holds, and each board model's default recipe revision. The folder must not hold a database yet: the tool
never writes into a station's workspace.
"""

from __future__ import annotations

import argparse
import json
import random
import sqlite3
import sys
import uuid
from contextlib import closing
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

if __package__ in (None, ""):  # run as a script: the repository root on the path, so `aoi` imports
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from aoi.config import Settings  # noqa: E402
from aoi.core.compare import CompareResult, Region  # noqa: E402
from aoi.core.inspector import Check, Defect, InspectionResult  # noqa: E402
from aoi.core.services import AppContext  # noqa: E402
from aoi.data import credentials  # noqa: E402
from aoi.errors import QT_TRANSLATE_NOOP  # noqa: E402

BOARD_MODELS, RECORDS, DAYS, SEED = 50, 100_000, 100, 55
VERDICTS = {"OK": 90, "WARN": 3, "NG": 7}  # percent of the records drawn
TEMPLATES = 32  # results drawn per verdict; each record takes one, so the JSON is built 96 times, not 100,000
OPERATORS = ("operator", "engineer")  # users the database seeds
DEFECT_TYPES = ("Missing Component", "Solder Bridge", "Misalignment", "Scratch")
INSPECTION_COLUMNS = (
    "id, uuid, time, board_model, model_version, model_uuid, recipe_rev, recipe_uuid, image_path, overlay_path,"
    " diff_map_path, ai_map_path, reference_path, reference_sha256, view, result, score, metrics, result_json,"
    " operator, archived"
)


@dataclass(frozen=True)
class Seeded:
    """What the tool wrote: the board model names, and the counts of each table's rows."""

    board_models: list[str]
    records: int
    archived: int
    checks: int
    defects: int
    alarms: int


def _uuid(rng: random.Random) -> str:
    """A version 4 UUID drawn from `rng`, so a seed writes the same workspace each time."""
    return str(uuid.UUID(int=rng.getrandbits(128), version=4))


def _result(rng: random.Random, verdict: str) -> InspectionResult:
    """A result of `verdict` with the five checks a board judged by the comparison and the AI model gets, and one to
    three defects with their regions for an NG or WARN one."""
    bad = verdict != "OK"
    regions = [
        Region(rng.randrange(600), rng.randrange(440), w, h, w * h, rng.uniform(40, 200), "compare")
        for w, h in [(rng.randint(8, 40), rng.randint(8, 40)) for _ in range(rng.randint(1, 3) if bad else 0)]
    ]
    ssim, score = (rng.uniform(0.6, 0.85), rng.uniform(0.9, 2.5)) if bad else (rng.uniform(0.9, 0.99), rng.random())
    ai = "NG" if verdict == "NG" else "WARN" if bad else "OK"
    metrics = {"alignment_method": "orb", "alignment_inliers": rng.randint(40, 400), "ssim": ssim,
               "mean_abs_diff": rng.uniform(0.5, 6), "max_diff": rng.uniform(60, 255),
               "changed_pct": rng.uniform(0, 0.4), "compare_regions": len(regions),
               "largest_region_px": max((r.area for r in regions), default=0)}  # fmt: skip
    checks = [
        Check("SSIM similarity", ssim, 0.8, "< thr → NG", "OK", "Compare", "1.0 = identical to the golden board"),
        Check("Changed area %", metrics["changed_pct"], 0.5, "≥ thr → NG", "OK", "Compare", "pixels whose colour"),
        Check("Difference regions", len(regions), 0, "> thr → NG", "OK", "Compare", "blobs ≥ 40 px"),
        Check("Alignment inliers", metrics["alignment_inliers"], 12, "info only", "INFO", "Compare", "orb"),
        Check("AI anomaly score", score * 3.1, 3.1, "≥ thr → NG", ai, "AI", "AI score of the board"),
    ]
    defects = [
        Defect(n, rng.choice(DEFECT_TYPES), score, "Top", r.x, r.y, r.w, r.h, "compare+ai")
        for n, r in enumerate(regions, 1)
    ]
    return InspectionResult(verdict, score, checks, defects, compare=CompareResult(regions=regions, metrics=metrics),
                            elapsed_ms=rng.uniform(300, 700))  # fmt: skip


def seed(
    root: Path,
    board_models: int = BOARD_MODELS,
    records: int = RECORDS,
    days: int = DAYS,
    rng_seed: int = SEED,
    now: datetime | None = None,
) -> Seeded:
    """Write the workspace at `root`, which must hold no database yet (FileExistsError), and say what it holds."""
    settings = Settings(workspace=str(root), device="cpu")
    if settings.db_path.exists():
        raise FileExistsError(f"{settings.db_path} exists: the tool seeds a new workspace only")
    rng, now = random.Random(rng_seed), now or datetime.now(UTC)
    names = [f"PERF-{i:03d}" for i in range(1, board_models + 1)]
    ctx = AppContext(settings, credentials.MemoryCredentials())  # migrated, users seeded, as a first start leaves it
    try:
        ctx.set_user("engineer")
        for name in names:
            ctx.ensure_board_model(name)  # with its default recipe revision and audit entry, as + New
        recipes: dict[str, tuple[int, str]] = {}
        for name in names:
            rev, _body, recipe_uuid = ctx.db.latest_recipe(name) or (0, {}, "")
            recipes[name] = rev, recipe_uuid
    finally:
        ctx.close()
    stored: dict[str, list[tuple[InspectionResult, str, str]]] = {}  # each verdict's results, with their JSON
    for v in VERDICTS:
        results = [_result(rng, v) for _ in range(TEMPLATES)]
        stored[v] = [(r, json.dumps(r.metrics_dict()), json.dumps(r.to_dict())) for r in results]
    models = {name: _uuid(rng) for name in names}
    archive_before = now - timedelta(days=settings.log_retention_days)
    maps_before = now - timedelta(days=settings.map_retention_days_ok)
    times = sorted(now - timedelta(seconds=rng.uniform(0, days * 86400)) for _ in range(records))
    rows, checks, defects, alarms = [], [], [], []
    for i, t in enumerate(times, 1):
        verdict = rng.choices(list(VERDICTS), list(VERDICTS.values()))[0]
        res, metrics, doc = rng.choice(stored[verdict])
        bm, uid, at = rng.choice(names), _uuid(rng), t.isoformat("T", "seconds")
        stem = f"board_{i:06d}"
        overlay = f"results/{t.astimezone().strftime('%Y-%m-%d')}/{stem}_{uid}_{verdict}"
        maps = (None, None) if verdict == "OK" and t < maps_before else (f"{overlay}_diff.png", f"{overlay}_ai2.png")
        rows.append((i, uid, at, bm, "v1", models[bm], *recipes[bm], f"images/{bm}/{stem}.png", f"{overlay}.png", *maps,
                     f"models/{bm}/golden.png", "0" * 64, "Top", verdict, res.score, metrics, doc,
                     rng.choice(OPERATORS), int(t < archive_before)))  # fmt: skip
        checks += [(i, n, c.region, c.name, c.source, c.value, c.threshold, c.rule, c.verdict, c.explain)
                   for n, c in enumerate(res.checks, 1)]  # fmt: skip
        defects += [(i, d.no, d.type, d.score, d.side, d.x, d.y, d.w, d.h) for d in res.defects]
        if verdict == "NG":  # in the record's transaction, as log_result stores it (REQ-INSP-006)
            text = QT_TRANSLATE_NOOP("Errors", "{file}: {defects} defect(s)").fill(
                file=f"{stem}.png", defects=len(res.defects)
            )
            phrase = json.dumps(text.to_json(), ensure_ascii=False)
            alarms.append((_uuid(rng), at, "NG", "AOI-INSP-003", str(text), phrase))
    with closing(sqlite3.connect(settings.db_path)) as c, c:  # the inner `with` commits once, at the end
        c.executemany(f"INSERT INTO inspections({INSPECTION_COLUMNS}) VALUES({','.join('?' * 21)})", rows)
        c.executemany(
            "INSERT INTO checks(inspection_id, no, region, metric, source, value, threshold, rule, result, explain)"
            " VALUES(?,?,?,?,?,?,?,?,?,?)",
            checks,
        )
        c.executemany("INSERT INTO defects(inspection_id, no, type, score, side, x, y, w, h) VALUES(?,?,?,?,?,?,?,?,?)",
                      defects)  # fmt: skip
        c.executemany("INSERT INTO alarms(uuid, time, level, code, message, phrase) VALUES(?,?,?,?,?,?)", alarms)
    archived = sum(r[-1] for r in rows)
    return Seeded(names, len(rows), archived, len(checks), len(defects), len(alarms))


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("workspace", type=Path, help="a new folder, or one that holds no aoi.sqlite yet")
    ap.add_argument("--board-models", type=int, default=BOARD_MODELS)
    ap.add_argument("--records", type=int, default=RECORDS)
    ap.add_argument("--days", type=int, default=DAYS, help="the records are spread over the last DAYS days")
    ap.add_argument("--seed", type=int, default=SEED)
    a = ap.parse_args(argv)
    try:
        s = seed(a.workspace.resolve(), a.board_models, a.records, a.days, a.seed)
    except FileExistsError as e:
        print(e, file=sys.stderr)
        return 2
    print(f"{a.workspace}: {len(s.board_models)} board models, {s.records} records ({s.archived} archived),"
          f" {s.checks} checks, {s.defects} defects, {s.alarms} alarms")  # fmt: skip
    return 0


if __name__ == "__main__":
    sys.exit(main())
