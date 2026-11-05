"""What the industry scenarios' stations stored, graded again (#459): for each scenario run folder, the verdicts its
records hold, and the verdict their stored checks alone would give, without the engine's rule that an OK board with any
defect region not Minor is WARN (aoi/core/inspector.py, step 5). The second is a what-if on stored values: it estimates
what a change to that rule could do, and is never a verdict the app gave. Counts from an internal test on public data,
never an accuracy claim.

    python tools/proxy_regrade.py <runs folder>/S1-commissioned-pcb1-baseline ...
"""

from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:  # run as a script: the repository root holds the ``aoi`` and ``tools`` packages
    sys.path.insert(0, str(ROOT))

FLAGS = ("NG", "WARN")


def by_checks(results: list[str]) -> str:
    """The verdict the checks alone give: NG on any NG, else WARN on any WARN, else OK (an INFO check is neither)."""
    return "NG" if "NG" in results else "WARN" if "WARN" in results else "OK"


def label_of(image_path: str) -> str:
    """A board's truth from its file: VisA keeps defective boards under Anomaly/, and the scenarios name the files
    they write after the label (ng…, ok…)."""
    p = Path(image_path)
    return "NG" if p.parent.name == "Anomaly" or p.name.startswith("ng") else "OK"


def quantiles(values: list[float]) -> dict[str, float | None]:
    v = sorted(values)
    return {f"p{q}": (v[int(q / 100 * (len(v) - 1) + 0.5)] if v else None) for q in (5, 50, 95)}  # nearest rank


def regrade(records: list[dict[str, Any]], checks: dict[int, list[dict[str, Any]]]) -> dict[str, Any]:
    """Per AI model version and label: the stored verdicts, the verdicts by checks alone, the boards WARN by defect
    regions alone (no check WARN or NG), and the AI score's quantiles."""
    out: dict[str, Any] = {}
    for r in records:
        got = out.setdefault(str(r["model_version"]), {}).setdefault(label_of(r["image_path"]), {
            "stored": Counter(), "by_checks": Counter(), "warn_by_regions_alone": 0, "ai": []})  # fmt: skip
        results = [c["result"] for c in checks.get(r["id"], [])]
        got["stored"][r["result"]] += 1
        got["by_checks"][by_checks(results)] += 1
        got["warn_by_regions_alone"] += r["result"] == "WARN" and not any(x in FLAGS for x in results)
        got["ai"] += [float(c["value"]) for c in checks.get(r["id"], []) if c["metric"] == "AI anomaly score"]
    for model in out.values():
        for g in model.values():
            g.update(stored=dict(g["stored"]), by_checks=dict(g["by_checks"]), ai=quantiles(g["ai"]))
    return out


def main(folders: list[str]) -> int:
    from aoi import config
    from tools.proxy_station import open_station

    out = {}
    for f in folders:
        ctx, before = open_station(Path(f), output=False)
        try:
            recs = [r for r in ctx.inspections(include_archived=True) if r["result"] in ("OK", "WARN", "NG")]
            out[Path(f).name] = regrade(recs, ctx.checks_for_many([r["id"] for r in recs]))
        finally:
            ctx.close()
            config.use_workspace(before)
    print(json.dumps(out, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
