"""The pull request template carries the change-note checklist (handover plan PR 0.5, #5).

The change note is a pull request's description (CLAUDE.md, "Checklist for every change"), so the template starts
every description with the checklist, line for line as CLAUDE.md and the Charter give it; CLAUDE.md summarises the
working rules that hold until v0.5.0.
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def checklist(text: str) -> list[str]:
    """The "Checklist for every change" section's boxes, each joined onto one line."""
    section = text.split("## Checklist for every change", 1)[1].split("\n## ", 1)[0]
    boxes = re.split(r"\n- \[ \] ", "\n" + section.split("\n- [ ] ", 1)[1].strip())
    return [" ".join(box.split()) for box in boxes if box.strip()]


def test_the_pr_template_carries_the_checklist_claude_md_and_the_charter_give() -> None:
    template = (ROOT / ".github" / "pull_request_template.md").read_text(encoding="utf-8")
    claude_md = (ROOT / "CLAUDE.md").read_text(encoding="utf-8")
    charter = (ROOT / "docs" / "standards" / "charter.md").read_text(encoding="utf-8")
    assert len(checklist(claude_md)) == 10
    assert checklist(template) == checklist(claude_md) == checklist(charter)
    said = " ".join(claude_md.split())
    assert "pull_request_template.md" in said and "a commit message needs no checklist" in said
    assert "its subject still cites the requirement or issue" in said
    assert "## Working rules until v0.5.0" in template and "expected.json` unchanged" in template


def test_claude_md_summarises_the_working_rules_until_v0_5_0() -> None:
    claude_md = (ROOT / "CLAUDE.md").read_text(encoding="utf-8")
    rules = claude_md.split("## Working rules until v0.5.0", 1)[1].split("\n## ", 1)[0]
    progress = (ROOT / "docs" / "plans" / "2026-11-handover-progress.md").read_text(encoding="utf-8")
    held = progress.split("## Working rules", 1)[1].split("\n## ", 1)[0]
    assert len(re.findall(r"^\d+\. \*\*", held, re.MULTILINE)) == len(re.findall(r"^- \*\*", rules, re.MULTILINE)) == 7
    rules = " ".join(rules.split())
    held = (
        "400 changed lines",
        "Feature freeze",
        "ends on a tag",
        "subagent",
        "Jay reads the diff and the review, and merges",
    )
    for words in (*held, "byte-identical", "stops and asks", "Chat is for instructions", "ADR 0024"):
        assert words in rules, words
