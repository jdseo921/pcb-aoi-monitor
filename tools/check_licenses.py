#!/usr/bin/env python
"""Check the license of every shipped dependency against the Legal & Compliance standard, and print the record.

    pip-licenses --with-system --format=json | python tools/check_licenses.py [--packages requirements.lock ...]

Reads pip-licenses' JSON from stdin and prints one line per installed package: its verdict from
tools/allowed_licenses.txt (allowed, exception pending J8, allowed as named package, or NOT ALLOWED), name, version
and the license text pip-licenses reports, so the CI log is the record of what was checked. With --packages, the
shipped set is the packages those requirements files name (CI: requirements.lock and the PyTorch lock installed with
it), and only they can fail the check; the other installed packages (development and CI tools) are listed apart with
their verdicts. A requirement whose environment marker is false here (`; sys_platform == "win32"` on Linux) is not
installed on this platform and is skipped. Exit 1, after listing every problem, when a shipped package's license is
not allowed or a package named in a --packages file is not installed, since the check cannot vouch for a package it
did not see. Exceptions in use are printed, so the pending decision (Stage 1 plan, J8) stays visible in every run.
pip-licenses needs --with-system: without it, it leaves out setuptools, which requirements.lock ships.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

from packaging.requirements import InvalidRequirement, Requirement

ROOT = Path(__file__).resolve().parents[1]
ALLOW_FILE = ROOT / "tools" / "allowed_licenses.txt"
ALLOWED, EXCEPTION, NAMED, NOT_ALLOWED = "allowed", "exception pending J8", "allowed as named package", "NOT ALLOWED"


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


def requirements(path: Path) -> tuple[dict[str, str], list[str]]:
    """The packages a requirements or lock file names for this platform, as {normalised name: "requirement (file)"},
    and the requirements it skips here because their environment marker is false. Option and hash lines are skipped
    without a word, since they name no package."""
    names: dict[str, str] = {}
    skipped: list[str] = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.split("#", 1)[0].strip().removesuffix("\\").strip()
        if not line or line.startswith("-"):
            continue
        try:
            req = Requirement(line)
        except InvalidRequirement as e:
            raise SystemExit(f"{path.name}: cannot read the requirement {line!r}: {e}") from e
        if req.marker is None or req.marker.evaluate():
            names[_norm_name(req.name)] = f"{req} ({path.name})"
        else:
            skipped.append(f"{req} ({path.name})")
    return names, skipped


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
    ap.add_argument(
        "--packages", type=Path, nargs="+", help="requirements files naming the packages to check (the shipped set)"
    )
    args = ap.parse_args()
    rows = sorted(json.load(sys.stdin), key=lambda r: str(r["Name"]).lower())
    allowed, exceptions, allowed_packages = load_allow_list()
    shipped: dict[str, str] | None = None  # None: no --packages, so every installed package is checked
    skipped: list[str] = []
    for path in args.packages or ():
        names, skips = requirements(path)
        shipped, skipped = (shipped or {}) | names, skipped + skips

    lines: dict[bool, list[str]] = {True: [], False: []}  # shipped or not: one line per package
    failures: list[str] = []
    used_exceptions: dict[str, list[str]] = {}
    for row in rows:
        name, version, license_text = str(row["Name"]), str(row["Version"]), str(row["License"])
        is_shipped = shipped is None or _norm_name(name) in shipped
        if _norm_name(name) in allowed_packages:
            ok, used, label = True, set(), NAMED
        else:
            ok, used = verdict(license_text, allowed, exceptions)
            label = EXCEPTION if ok and used else ALLOWED if ok else NOT_ALLOWED
        note = f" [{', '.join(sorted(used))}]" if used else ""
        lines[is_shipped].append(f"  {label:<24} {name} {version}: {license_text}{note}")
        if is_shipped and not ok:
            failures.append(f"{name} {version}: {license_text}")
        for term in used if is_shipped else ():
            used_exceptions.setdefault(term, []).append(name)
    installed = {_norm_name(str(row["Name"])) for row in rows}
    missing = [req for name, req in sorted((shipped or {}).items()) if name not in installed]

    files = ", ".join(path.name for path in args.packages or ())
    print(f"Shipped packages ({files or 'no --packages: every installed package'}), {len(lines[True])} checked:")
    print(*lines[True], sep="\n")
    if lines[False]:
        print(f"Development and CI packages, not shipped, {len(lines[False])} reported (they cannot fail the check):")
        print(*lines[False], sep="\n")
    for item in skipped:
        print(f"Skipped, its environment marker is false here: {item}")
    for term, users in sorted(used_exceptions.items()):
        print(f"exception in use (pending Jay, J8): {term} <- {', '.join(sorted(users))}")
    if missing:
        print("Named in --packages but not installed here, so the check cannot vouch for them:")
        print(*(f"  {req}" for req in missing), sep="\n")
    if failures:
        print("Licenses not allowed by the Legal & Compliance standard:")
        print(*(f"  {f}" for f in failures), sep="\n")
    if missing or failures:
        return 1
    print(f"License check passed for {len(lines[True])} shipped packages.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
