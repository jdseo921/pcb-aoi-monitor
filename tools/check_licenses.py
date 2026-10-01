#!/usr/bin/env python
"""Fail when an installed dependency carries a license the Legal & Compliance standard does not allow.

    pip-licenses --format=json | python tools/check_licenses.py [--packages requirements.lock]

Reads pip-licenses' JSON from stdin, compares every package against tools/allowed_licenses.txt
and exits 1 on the first package whose license is not allowed, listed by name. With --packages
only the packages named in that requirements file (the shipped set) are checked; the rest are
reported. Licenses marked "exception:" count as allowed but are printed, so the pending decision
(Stage 1 plan, J8) stays visible in every CI run.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ALLOW_FILE = ROOT / "tools" / "allowed_licenses.txt"


def load_allow_list(path: Path = ALLOW_FILE) -> tuple[set[str], set[str], set[str]]:
    """Return (allowed licenses, exception licenses, allowed package names), all lower-cased."""
    allowed: set[str] = set()
    exceptions: set[str] = set()
    packages: set[str] = set()
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.split("#", 1)[0].strip()
        if not line:
            continue
        if line.startswith("package:"):
            packages.add(_norm_name(line[len("package:") :]))
        elif line.startswith("exception:"):
            exceptions.add(line[len("exception:") :].strip().lower())
        else:
            allowed.add(line.lower())
    return allowed, exceptions, packages


def _norm_name(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name.strip()).lower()


def requirement_names(path: Path) -> set[str]:
    names: set[str] = set()
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.split("#", 1)[0].strip()
        if not line or line.startswith("-"):
            continue
        m = re.match(r"([A-Za-z0-9][A-Za-z0-9._-]*)", line)
        if m:
            names.add(_norm_name(m.group(1)))
    return names


def terms(expression: str) -> list[list[str]]:
    """Split a license expression into OR-alternatives of AND-terms, each lower-cased."""
    expr = expression.strip()
    if expr.startswith("(") and expr.endswith(")") and expr.count("(") == 1:
        expr = expr[1:-1]
    return [[t.strip().lower() for t in alt.split(" AND ")] for alt in expr.split(" OR ")]


def verdict(license_text: str, allowed: set[str], exceptions: set[str]) -> tuple[bool, set[str]]:
    """Whether the license is acceptable, and which exceptions it relies on."""
    best_used: set[str] | None = None
    for alternative in terms(license_text):
        used: set[str] = set()
        ok = True
        for term in alternative:
            if term in allowed:
                continue
            if term in exceptions:
                used.add(term)
                continue
            ok = False
            break
        if ok and (best_used is None or len(used) < len(best_used)):
            best_used = used
    return (best_used is not None), (best_used or set())


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--packages", type=Path, help="requirements file naming the packages to check (the shipped set)")
    args = ap.parse_args()
    rows = json.load(sys.stdin)
    allowed, exceptions, allowed_packages = load_allow_list()
    shipped = requirement_names(args.packages) if args.packages else None

    failures: list[str] = []
    used_exceptions: dict[str, list[str]] = {}
    for row in sorted(rows, key=lambda r: str(r["Name"]).lower()):
        name = _norm_name(str(row["Name"]))
        if shipped is not None and name not in shipped:
            continue
        if name in allowed_packages:
            continue
        ok, used = verdict(str(row["License"]), allowed, exceptions)
        if not ok:
            failures.append(f"{row['Name']} {row['Version']}: {row['License']}")
        for term in used:
            used_exceptions.setdefault(term, []).append(str(row["Name"]))

    for term, names in sorted(used_exceptions.items()):
        print(f"exception in use (pending Jay, J8): {term} <- {', '.join(sorted(names))}")
    if failures:
        print("Licenses not allowed by the Legal & Compliance standard:")
        for f in failures:
            print("  " + f)
        return 1
    print(f"License check passed for {len(rows) if shipped is None else len(shipped)} packages.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
