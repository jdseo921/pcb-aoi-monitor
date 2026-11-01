"""Version discipline (REQ-SET-023): what ships changed, so the version moved.

Fails when, since the last `v*` tag, `aoi/data/migrations/` gained a file or a row of the requirements register
changed its status (the first word of its v0.1 column: Done, Partial or No), while `APP_VERSION` in aoi/config.py
is the one the tag carries. CI runs it on every pull request and push to main (.github/workflows/ci.yml):

    python tools/check_version_bump.py

It needs the tags in the checkout (`fetch-depth: 0`). With no `v*` tag there is nothing to compare, and it passes.
After a release candidate (`v0.4.0-rc.1` while `APP_VERSION` is still 0.4.0) it passes too: the fixes on the way to
`v0.4.0` ship under that version, which the final tag must name. Only what ships is checked: a migration removed or
edited, or a register row removed, is left to review.
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CONFIG = "aoi/config.py"
MIGRATIONS = "aoi/data/migrations"
REGISTERS = "docs/requirements"
REQ_ID = re.compile(r"REQ-[A-Z0-9]+-\d{3}")  # as tools/trace_matrix.py reads them
VERSION = re.compile(r'^APP_VERSION = "([^"]+)"$', re.MULTILINE)


def git(repo: Path, *args: str) -> str:
    return subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True, text=True).stdout


def last_tag(repo: Path) -> str | None:
    found = subprocess.run(
        ["git", "describe", "--tags", "--abbrev=0", "--match", "v*", "HEAD"], cwd=repo, capture_output=True, text=True
    )
    return found.stdout.strip() if found.returncode == 0 else None


def app_version(config: str) -> str:
    found = VERSION.search(config)
    if not found:
        raise SystemExit(f'{CONFIG} has no line APP_VERSION = "..."')
    return found.group(1)


def statuses(register: str) -> dict[str, str]:
    """Each REQ ID's status, the first word of its v0.1 column, in every table of a register file."""
    found: dict[str, str] = {}
    column = None
    for line in register.splitlines():
        cells = [cell.strip() for cell in re.split(r"(?<!\\)\|", line.strip())[1:-1]]
        if cells[:1] == ["ID"]:
            column = cells.index("v0.1") if "v0.1" in cells else None
        elif column is not None and cells and re.fullmatch(REQ_ID, cells[0]) and len(cells) > column:
            found[cells[0]] = re.split(r"[\s:]", cells[column], maxsplit=1)[0]
    return found


def at_tag(repo: Path, tag: str) -> tuple[str, set[str], dict[str, str]]:
    """The version, the migration files and the register statuses at the tag."""
    where = ["git", "ls-tree", "--name-only", f"{tag}:{MIGRATIONS}"]
    listed = subprocess.run(where, cwd=repo, capture_output=True, text=True)
    files = set(listed.stdout.split())  # none when the tag has no migrations folder
    names = git(repo, "ls-tree", "--name-only", f"{tag}:{REGISTERS}").split()
    registers = [p for p in names if p.endswith(".md") and p != "README.md"]
    found: dict[str, str] = {}
    for name in registers:
        found |= statuses(git(repo, "show", f"{tag}:{REGISTERS}/{name}"))
    return app_version(git(repo, "show", f"{tag}:{CONFIG}")), files, found


def at_head(repo: Path) -> tuple[str, set[str], dict[str, str]]:
    """The same, in the working tree."""
    files = {p.name for p in (repo / MIGRATIONS).iterdir() if p.is_file()}
    found: dict[str, str] = {}
    for register in sorted((repo / REGISTERS).glob("*.md")):
        if register.name != "README.md":
            found |= statuses(register.read_text(encoding="utf-8"))
    return app_version((repo / CONFIG).read_text(encoding="utf-8")), files, found


def changes(repo: Path) -> tuple[str | None, str, str, list[str]]:
    """The last tag, its version, the version now, and what changed since the tag that needs the version to move."""
    tag = last_tag(repo)
    version, files, now = at_head(repo)
    if tag is None:
        return None, version, version, []
    tagged, files_then, then = at_tag(repo, tag)
    moved = [f"{MIGRATIONS}/{name} is new" for name in sorted(files - files_then)]
    for req, status in sorted(now.items()):
        before = then.get(req, "No")  # a row added since the tag counts once it is more than No
        if status != before:
            moved.append(f"{req} went from {before} to {status}")
    return tag, tagged, version, moved


def main(repo: Path = ROOT) -> int:
    tag, tagged, version, moved = changes(repo)
    if tag is None:
        print("No v* tag yet: nothing to compare.")
        return 0
    if tag.startswith(f"v{version}-"):
        print(f"{tag} is a pre-release of {version}: fixes on the way to v{version} keep that version.")
        return 0
    if moved and version == tagged:
        print(f"APP_VERSION is {version}, as at {tag}, but since {tag}:", file=sys.stderr)
        print("  " + "\n  ".join(moved), file=sys.stderr)
        print(f"Move APP_VERSION in {CONFIG} (REQ-SET-023).", file=sys.stderr)
        return 1
    print(f"{tag} carries {tagged}; now {version}; {len(moved)} change(s) since the tag that need a new version.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
