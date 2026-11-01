"""The AOI Standards are in the repository (handover plan PR 0.2, #5): what CLAUDE.md cites is in docs/standards/.

CLAUDE.md binds every change to four Standards that Jay edits as Claude Docs. docs/standards/ holds a copy of each,
exported whole, with its source link and revision (docs/standards/README.md). These checks fail when CLAUDE.md
cites a Standard, by file or by its Claude Docs link, that has no copy here; when a copy lost its source link; and
when an ADR or the register names a Standard without linking its copy.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
STANDARDS = ROOT / "docs" / "standards"
SOURCE_LINK = re.compile(r"https://claude\.ai/code/artifact/[0-9a-f-]{36}")
# How a document names each Standard, and the copy that name must link to
NAMES = {
    "charter.md": re.compile(r"\bCharter\b"),
    "engineering.md": re.compile(r"\bEngineering\s+standard"),
    "customers-and-launch.md": re.compile(r"\bCustomers\s+&\s+Launch\b"),
    "legal-and-compliance.md": re.compile(r"\bLegal\s+&\s+Compliance\b"),
}


def copies() -> list[Path]:
    return sorted(p for p in STANDARDS.glob("*.md") if p.name != "README.md")


def source_of(copy: Path) -> str:
    """The Claude Docs link in the copy's provenance line, the first quoted line under its title."""
    lines = copy.read_text(encoding="utf-8").splitlines()
    quoted = next((line for line in lines[1:6] if line.startswith("> ")), "")
    found = SOURCE_LINK.search(quoted)
    assert found, f"{copy.name} has no provenance line with its Claude Docs source under its title"
    return found.group(0)


def test_the_four_standards_have_a_copy_each() -> None:
    assert [p.name for p in copies()] == sorted(NAMES), "docs/standards/ should hold exactly the four Standards"
    readme = (STANDARDS / "README.md").read_text(encoding="utf-8")
    for copy in copies():
        assert f"]({copy.name})" in readme, f"docs/standards/README.md does not list {copy.name}"
        assert source_of(copy) in readme, f"docs/standards/README.md does not give {copy.name}'s source"


def read_first_rows() -> list[list[str]]:
    """The cells of each row of CLAUDE.md's Read first table, the one place it cites the Standards."""
    text = (ROOT / "CLAUDE.md").read_text(encoding="utf-8")
    section = text.split("## Read first", 1)[1].split("\n## ", 1)[0]
    table = [line for line in section.splitlines() if line.startswith("|")]
    assert len(table) > 2, "CLAUDE.md has no Read first table"
    return [[cell.strip() for cell in row.strip("|").split("|")] for row in table[2:]]


def test_every_standard_claude_md_cites_is_in_docs_standards() -> None:
    sources = {copy.name: source_of(copy) for copy in copies()}
    cited = []
    for name, *_, source in read_first_rows():
        linked = re.fullmatch(r"\[[^\]]+\]\(docs/standards/([\w.-]+\.md)\)", name)
        assert linked, f"CLAUDE.md cites the Standard {name!r} without linking its copy in docs/standards/"
        copy = linked.group(1)
        assert copy in sources, f"CLAUDE.md cites docs/standards/{copy}, which is not in the repository"
        assert source == sources[copy], f"CLAUDE.md gives {copy} the source {source}, its copy says {sources[copy]}"
        cited.append(copy)
    assert sorted(cited) == sorted(sources), "CLAUDE.md's Read first table should cite each copy once"


@pytest.mark.parametrize(
    "doc", sorted((ROOT / "docs" / "adr").glob("*.md")), ids=lambda p: p.name if isinstance(p, Path) else str(p)
)
def test_an_adr_that_names_a_standard_links_its_copy(doc: Path) -> None:
    """The first mention of each Standard in an ADR is the link to its copy."""
    text = doc.read_text(encoding="utf-8")
    for copy, name in NAMES.items():
        first = name.search(text)
        if first:
            links = re.finditer(r"\[[^\]]*\]\(\.\./standards/" + re.escape(copy) + r"[^)]*\)", text)
            assert any(link.start() < first.start() < link.end() for link in links), (
                f"{doc.name}: the first mention of {copy[:-3]} is not a link to docs/standards/{copy}"
            )


def test_the_register_resolves_every_standard_it_cites() -> None:
    """Register rows cite the Standards by abbreviation (ENG, C&L, LEG, Charter), defined and linked in its README."""
    readme = (ROOT / "docs" / "requirements" / "README.md").read_text(encoding="utf-8")
    for copy in NAMES:
        assert f"](../standards/{copy})" in readme, f"docs/requirements/README.md does not link docs/standards/{copy}"
    for register in sorted((ROOT / "docs" / "requirements").glob("*.md")):
        if register.name != "README.md":
            text = register.read_text(encoding="utf-8")
            assert "](README.md)" in text, f"{register.name} does not point to the README that resolves its sources"
