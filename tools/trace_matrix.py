"""Trace matrix: every requirement with the pull requests and tests that cite it and the last test result (S07).

    python tools/trace_matrix.py --junit test-results.xml --git-log --out trace-matrix [--gate G1]
    python tools/trace_matrix.py --collected collected.txt --out trace-matrix

Reads the requirement tables in docs/requirements/*.md, the test ids pytest ran (JUnit XML from --junitxml) or
collected (the output of `pytest --collect-only -q`), and the commit subjects that cite a requirement, such as
`[REQ-TRN-014] fix: …`, or an issue, `[#12] …`. Writes trace-matrix.md and trace-matrix.csv, one row per
requirement. With --gate G1 it exits 1 when any MUST G1 row has no passing test, or a test or commit cites a
requirement ID the register does not know (Engineering standard, "Traceability"). Issue citations are listed
but not checked against the register.
"""

from __future__ import annotations

import argparse
import csv
import re
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

import defusedxml.ElementTree as ET  # the JUnit file is our own, but parse it defensively (bandit B314)

ROOT = Path(__file__).resolve().parents[1]
REQ_ID = re.compile(r"REQ-[A-Z0-9]+-\d{3}")
TEST_REQ = re.compile(r"test_req_([a-z0-9]+)_(\d{3})")
SUBJECT_REF = re.compile(r"\[(REQ-[A-Z0-9]+-\d{3}|#\d+)\]")


@dataclass
class Requirement:
    id: str
    text: str
    priority: str  # e.g. "MUST G1"
    v01: str
    source_file: str


@dataclass
class Row:
    req: Requirement
    commits: list[str] = field(default_factory=list)
    tests: list[str] = field(default_factory=list)
    passed: int = 0
    failed: int = 0
    not_run: int = 0

    @property
    def result(self) -> str:
        if not self.tests:
            return "no test"
        if self.failed:
            return f"FAIL ({self.failed} of {len(self.tests)} failing)"
        if self.not_run:
            return f"not run ({self.not_run} of {len(self.tests)})"
        return f"pass ({self.passed})"


def read_register(folder: Path) -> dict[str, Requirement]:
    """Rows of every pipe table whose first cell is a requirement ID, from every Markdown file in `folder`."""
    reqs: dict[str, Requirement] = {}
    for md in sorted(folder.glob("*.md")):
        for line in md.read_text(encoding="utf-8").splitlines():
            if not line.startswith("| REQ-"):
                continue
            cells = [c.strip() for c in line.strip().strip("|").split("|")]
            if len(cells) < 6 or not REQ_ID.fullmatch(cells[0]):
                raise ValueError(f"{md.name}: malformed requirement row: {line[:60]}")
            if cells[0] in reqs:
                raise ValueError(f"{md.name}: duplicate requirement {cells[0]}")
            reqs[cells[0]] = Requirement(cells[0], cells[1], cells[4], cells[5], md.name)
    return reqs


def test_function(test_id: str) -> str:
    """`tests/test_x.py::test_req_insp_003_boxes[param]` -> `test_x.py::test_req_insp_003_boxes`."""
    name = test_id.split("[", 1)[0]
    if "::" in name:
        path, _, func = name.partition("::")
        return f"{Path(path).name}::{func}"
    return name


def cited_requirement(test_name: str) -> str | None:
    m = TEST_REQ.search(test_name)
    return f"REQ-{m.group(1).upper()}-{m.group(2)}" if m else None


def read_collected(path: Path) -> list[str]:
    return [line.strip() for line in path.read_text(encoding="utf-8").splitlines() if "::" in line]


def read_junit(path: Path) -> dict[str, str]:
    """Test function -> 'passed' | 'failed' | 'skipped'; a function with any failing parameter case is failed."""
    outcome: dict[str, str] = {}
    for case in ET.parse(path).getroot().iter("testcase"):
        module = (case.get("classname") or "").split(".")[-1]
        func = test_function(f"{module}.py::{case.get('name', '')}")
        if case.find("failure") is not None or case.find("error") is not None:
            state = "failed"
        elif case.find("skipped") is not None:
            state = "skipped"
        else:
            state = "passed"
        if outcome.get(func) != "failed":
            outcome[func] = "failed" if state == "failed" else state if outcome.get(func) != "passed" else "passed"
    return outcome


def git_subjects(ref: str = "HEAD") -> list[str]:
    out = subprocess.run(
        ["git", "log", "--format=%s", ref], cwd=ROOT, capture_output=True, text=True, check=True, encoding="utf-8"
    )
    return [s for s in out.stdout.splitlines() if s.strip()]


def build(
    reqs: dict[str, Requirement], tests: list[str], outcomes: dict[str, str], subjects: list[str]
) -> tuple[list[Row], list[str]]:
    """The matrix rows in register order, and the unknown requirement IDs that tests or commits cite."""
    rows = {rid: Row(r) for rid, r in reqs.items()}
    unknown: list[str] = []
    for func in sorted({test_function(t) for t in tests} | set(outcomes)):
        rid = cited_requirement(func)
        if rid is None:
            continue
        if rid not in rows:
            unknown.append(f"test {func} cites {rid}")
            continue
        row = rows[rid]
        row.tests.append(func)
        state = outcomes.get(func)
        if state == "passed":
            row.passed += 1
        elif state == "failed":
            row.failed += 1
        else:
            row.not_run += 1
    seen: set[str] = set()
    for subject in subjects:
        if subject in seen:
            continue
        seen.add(subject)
        for ref in SUBJECT_REF.findall(subject):
            if ref.startswith("#"):
                continue
            if ref not in rows:
                unknown.append(f"commit {subject!r} cites {ref}")
            elif subject not in rows[ref].commits:
                rows[ref].commits.append(subject)
    return list(rows.values()), unknown


def write(rows: list[Row], out_dir: Path) -> tuple[Path, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    md, csv_path = out_dir / "trace-matrix.md", out_dir / "trace-matrix.csv"
    lines = [
        "# Trace matrix",
        "",
        "Generated by `tools/trace_matrix.py` from `docs/requirements/`; do not edit. One row per requirement with",
        "the commits and tests that cite it and the last test result.",
        "",
        "| ID | Priority | v0.1 | Commits | Tests | Last result |",
        "|---|---|---|---|---|---|",
    ]
    with csv_path.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["id", "priority", "v01", "commits", "tests", "last_result"])
        for row in rows:
            commits, tests = "; ".join(row.commits), "; ".join(row.tests)
            w.writerow([row.req.id, row.req.priority, row.req.v01, commits, tests, row.result])
            lines.append(
                f"| {row.req.id} | {row.req.priority} | {row.req.v01.split(':')[0]} | "
                f"{commits.replace('|', '/') or '—'} | {tests.replace('|', '/') or '—'} | {row.result} |"
            )
    md.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return md, csv_path


def gate(rows: list[Row], unknown: list[str], release: str) -> list[str]:
    problems = list(unknown)
    for row in rows:
        if row.req.priority == f"MUST {release}" and row.passed == 0 or row.failed:
            problems.append(f"{row.req.id} ({row.req.priority}): {row.result}")
    return problems


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--register", type=Path, default=ROOT / "docs" / "requirements")
    ap.add_argument("--junit", type=Path, help="JUnit XML written by pytest --junitxml")
    ap.add_argument("--collected", type=Path, help="output of pytest --collect-only -q")
    ap.add_argument("--git-log", action="store_true", help="read commit subjects from git log")
    ap.add_argument("--out", type=Path, default=ROOT, help="folder for trace-matrix.md and .csv")
    ap.add_argument("--gate", metavar="RELEASE", help="exit 1 unless every MUST row of this release passes")
    a = ap.parse_args(argv)
    if not a.junit and not a.collected:
        ap.error("give --junit and/or --collected")
    reqs = read_register(a.register)
    tests = read_collected(a.collected) if a.collected else []
    outcomes = read_junit(a.junit) if a.junit else {}
    rows, unknown = build(reqs, tests, outcomes, git_subjects() if a.git_log else [])
    md, csv_path = write(rows, a.out)
    covered = sum(1 for r in rows if r.tests)
    print(
        f"{len(rows)} requirements, {covered} with tests, {sum(r.passed for r in rows)} passing tests: {md}, {csv_path}"
    )
    if a.gate:
        problems = gate(rows, unknown, a.gate)
        for p in problems:
            print(f"GATE {a.gate}: {p}")
        print(f"GATE {a.gate}: {'passed' if not problems else f'{len(problems)} problem(s)'}")
        return 1 if problems else 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
