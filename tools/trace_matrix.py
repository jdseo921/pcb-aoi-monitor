"""Trace matrix: every requirement with the pull requests and tests that cite it and the last test result (S07).

    python tools/trace_matrix.py --junit test-results.xml --git-log --out trace-matrix [--gate G1]
    python tools/trace_matrix.py --collected collected.txt --out trace-matrix

Reads the requirement tables in docs/requirements/*.md, the test ids pytest ran (JUnit XML from --junitxml) or
collected (the output of `pytest --collect-only -q`), and, with --git-log, the changes on the first-parent history of
HEAD: each merged pull request by its number and title (a "Merge pull request #12 from …" commit, whose body holds the
title, or a squash commit ending "(#12)"), and each commit not merged through a pull request yet (a stacked branch
before Jay merges it) by its short hash and subject. A pull request's CI run checks out GitHub's merge of the pull
request into its base ("Merge <sha> into <sha>"), whose first parent is the base: the pull request's own commits, on
the second parent, are read too, and its number and title come from the environment (PR_NUMBER and PR_TITLE, which
the workflow sets). A title cites a requirement as `[REQ-TRN-014] fix: …`. Writes
trace-matrix.md and trace-matrix.csv, one row per requirement with the pull requests (or commits) and tests that cite
it. With --gate G1 it exits 1 when any MUST G1 row has no passing test or a failing one, when a test or change cites
a requirement ID the register does not know, or, on a pull request's run, when its title or one of its own commits
cites neither a requirement nor a bug (Engineering standard, "Traceability": "A requirement with no test, or code with
no requirement or bug ID, fails the release gate"). A title that cites only an issue, `[#5] …`, names no requirement
row, so it is neither listed nor checked against the register.
"""

from __future__ import annotations

import argparse
import csv
import os
import re
import subprocess
import sys
from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from pathlib import Path

import defusedxml.ElementTree as ET  # the JUnit file is our own, but parse it defensively (bandit B314)

ROOT = Path(__file__).resolve().parents[1]
REQ_ID = re.compile(r"REQ-[A-Z0-9]+-\d{3}")
TEST_REQ = re.compile(r"test_req_([a-z0-9]+)_(\d{3})")
SUBJECT_REF = re.compile(r"\[(REQ-[A-Z0-9]+-\d{3}|#\d+)\]")
MERGED_PR = re.compile(r"^Merge pull request #(\d+) ")  # GitHub's "Create a merge commit"; the title is the body
SQUASHED_PR = re.compile(r" \(#(\d+)\)$")  # GitHub's "Squash and merge": the title, then the number
PR_MERGE_REF = re.compile(r"^Merge [0-9a-f]{40} into [0-9a-f]{40}$")  # refs/pull/N/merge: what a PR's CI run tests
LOG_FORMAT = "--format=%H%x1f%s%x1f%b%x1e"


@dataclass
class Requirement:
    id: str
    text: str
    priority: str  # e.g. "MUST G1"
    v01: str
    source_file: str


@dataclass
class Change:
    """A change on the first-parent history: a merged pull request (`pr`, its number) or a commit not merged yet;
    `own` marks a commit of the pull request a CI run checks."""

    title: str
    pr: int | None = None
    sha: str = ""
    own: bool = False

    @property
    def label(self) -> str:
        return f"#{self.pr}" if self.pr else f"commit {self.sha[:7]}"


@dataclass
class Row:
    req: Requirement
    prs: list[str] = field(default_factory=list)  # "#84", or "commit 4367657" before it is merged
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


def parse_log(log: str) -> list[Change]:
    """Changes from `git log --first-parent --format=%H%x1f%s%x1f%b%x1e`: merged pull requests by number and title,
    other commits by hash and subject."""
    changes = []
    for record in log.split("\x1e"):
        if not record.strip():
            continue
        sha, subject, body = (record.strip("\n").split("\x1f") + ["", ""])[:3]
        if merged := MERGED_PR.match(subject):
            lines = [line for line in body.splitlines() if line.strip()]
            changes.append(Change(lines[0].strip() if lines else subject, int(merged.group(1)), sha))
        elif squashed := SQUASHED_PR.search(subject):
            changes.append(Change(subject[: squashed.start()], int(squashed.group(1)), sha))
        else:
            changes.append(Change(subject, None, sha))
    return changes


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(["git", *args], cwd=repo, capture_output=True, text=True, check=True, encoding="utf-8").stdout


def git_changes(ref: str = "HEAD", repo: Path = ROOT) -> list[Change]:
    """The changes on the first-parent history of `ref`; when `ref` is GitHub's merge of a pull request into its base,
    the pull request's own commits too (its second parent's commits that the base lacks), after the merge itself."""
    changes = parse_log(_git(repo, "log", "--first-parent", LOG_FORMAT, ref))
    parents = _git(repo, "rev-list", "--parents", "-n", "1", ref).split()[1:]
    if len(parents) == 2 and changes and PR_MERGE_REF.match(changes[0].title):
        own = parse_log(_git(repo, "log", LOG_FORMAT, f"{parents[0]}..{parents[1]}"))
        changes[1:1] = [replace(c, own=True) for c in own]
    return changes


def pr_change(env: Mapping[str, str]) -> Change | None:
    """The pull request a CI run checks, by the number and title the workflow passes in PR_NUMBER and PR_TITLE (through
    the environment, so a title is never read as shell code); None outside a pull request's run."""
    number, title = env.get("PR_NUMBER", "").strip(), env.get("PR_TITLE", "").strip()
    return Change(title, int(number)) if number.isdigit() and title else None


def build(
    reqs: dict[str, Requirement], tests: list[str], outcomes: dict[str, str], changes: list[Change]
) -> tuple[list[Row], list[str]]:
    """The matrix rows in register order, and the unknown requirement IDs that tests or changes cite."""
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
    for change in changes:
        for ref in dict.fromkeys(SUBJECT_REF.findall(change.title)):
            if ref.startswith("#"):
                continue
            if ref not in rows:
                unknown.append(f"{change.label} {change.title!r} cites {ref}")
            elif change.label not in rows[ref].prs:
                rows[ref].prs.append(change.label)
    return list(rows.values()), unknown


def write(rows: list[Row], out_dir: Path) -> tuple[Path, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    md, csv_path = out_dir / "trace-matrix.md", out_dir / "trace-matrix.csv"
    lines = [
        "# Trace matrix",
        "",
        "Generated by `tools/trace_matrix.py` from `docs/requirements/`; do not edit. One row per requirement with",
        "the pull requests (or, before they are merged, the commits) and tests that cite it and the last test result.",
        "",
        "| ID | Priority | v0.1 | PRs | Tests | Last result |",
        "|---|---|---|---|---|---|",
    ]
    with csv_path.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["id", "priority", "v01", "prs", "tests", "last_result"])
        for row in rows:
            prs, tests = "; ".join(row.prs), "; ".join(row.tests)
            w.writerow([row.req.id, row.req.priority, row.req.v01, prs, tests, row.result])
            lines.append(
                f"| {row.req.id} | {row.req.priority} | {row.req.v01.split(':')[0]} | "
                f"{prs or '—'} | {tests.replace('|', '/') or '—'} | {row.result} |"
            )
    md.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return md, csv_path


def gate(rows: list[Row], unknown: list[str], release: str) -> list[str]:
    """What stops `release`: each cited ID the register does not know, and each of its MUST rows with no passing test
    or a failing one. Rows of other priorities never stop it (a failing test fails CI's test job anyway)."""
    problems = list(unknown)
    for row in rows:
        if row.req.priority == f"MUST {release}" and (row.passed == 0 or row.failed):
            problems.append(f"{row.req.id} ({row.req.priority}): {row.result}")
    return problems


def uncited(changes: list[Change]) -> list[str]:
    """The changes whose title cites no requirement and no bug (an issue): code with no requirement or bug ID stops a
    release. A merge commit carries no code of its own and is left out."""
    return [
        f"{c.label} {c.title!r} cites no requirement or bug ID"
        for c in changes
        if not SUBJECT_REF.search(c.title) and not c.title.startswith("Merge ")
    ]


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
    changes = git_changes() if a.git_log else []
    if pr := pr_change(os.environ):
        changes.insert(0, pr)
    checked = [pr, *(c for c in changes if c.own)] if pr else []  # a pull request's own changes, not the history
    rows, unknown = build(reqs, tests, outcomes, changes)
    md, csv_path = write(rows, a.out)
    covered = sum(1 for r in rows if r.tests)
    print(
        f"{len(rows)} requirements, {covered} with tests, {sum(r.passed for r in rows)} passing tests: {md}, {csv_path}"
    )
    if a.gate:
        problems = gate(rows, unknown, a.gate) + uncited(checked)
        for p in problems:
            print(f"GATE {a.gate}: {p}")
        print(f"GATE {a.gate}: {'passed' if not problems else f'{len(problems)} problem(s)'}")
        return 1 if problems else 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
