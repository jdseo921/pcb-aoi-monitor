"""Version discipline (REQ-SET-023): the version moves with what ships.

CI fails a migration or a register status change since the last v* tag without a new APP_VERSION
(tools/check_version_bump.py).
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest
import yaml

from tools import check_version_bump

ROOT = Path(__file__).resolve().parents[1]
HEADER = (
    "| ID | The app shall… | Acceptance criteria | Source | Priority | v0.1 | Impacts |\n"
    "|---|---|---|---|---|---|---|\n"
)


def workflow(name: str) -> dict[Any, Any]:
    return dict(yaml.safe_load((ROOT / ".github" / "workflows" / name).read_text(encoding="utf-8")))


def write(repo: Path, version: str, migrations: list[str], rows: dict[str, str]) -> None:
    shutil.rmtree(repo / "aoi" / "data" / "migrations", ignore_errors=True)
    (repo / "aoi" / "data" / "migrations").mkdir(parents=True)
    (repo / "docs" / "requirements").mkdir(parents=True, exist_ok=True)
    (repo / "aoi" / "config.py").write_text(f'APP_VERSION = "{version}"\n', encoding="utf-8")
    for name in migrations:
        (repo / "aoi" / "data" / "migrations" / name).write_text("SELECT 1;\n", encoding="utf-8")
    table = "".join(f"| {req} | do a\\|b | x | ENG | MUST G1 | {status} | none |\n" for req, status in rows.items())
    (repo / "docs" / "requirements" / "stage1.md").write_text(HEADER + table, encoding="utf-8")
    (repo / "docs" / "requirements" / "README.md").write_text("| ID | v0.1 |\n| REQ-X-001 | Done |\n", encoding="utf-8")


def git(repo: Path, *args: str) -> None:
    subprocess.run(
        ["git", "-c", "user.name=t", "-c", "user.email=t@t", *args], cwd=repo, check=True, capture_output=True
    )


def test_req_set_023_ci_fails_a_migration_or_status_change_without_a_new_version(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    git(tmp_path, "init", "-q")
    write(tmp_path, "0.3.0", ["0001_a.sql"], {"REQ-SET-001": "Partial: x", "REQ-SET-002": "No"})
    git(tmp_path, "add", "-A")
    git(tmp_path, "commit", "-qm", "base")
    assert check_version_bump.main(tmp_path) == 0 and "No v* tag yet" in capsys.readouterr().out
    git(tmp_path, "tag", "v0.3.0")
    assert check_version_bump.main(tmp_path) == 0  # nothing changed

    write(tmp_path, "0.3.0", ["0001_a.sql"], {"REQ-SET-001": "Partial: y", "REQ-SET-002": "No", "REQ-SET-003": "No"})
    assert check_version_bump.main(tmp_path) == 0  # wording, and a row added as No, ship nothing
    write(tmp_path, "0.3.0", ["0001_a.sql", "0002_b.sql"], {"REQ-SET-001": "Done", "REQ-SET-002": "No"})
    assert check_version_bump.main(tmp_path) == 1
    said = capsys.readouterr().err
    assert "APP_VERSION is 0.3.0, as at v0.3.0" in said
    assert "aoi/data/migrations/0002_b.sql is new" in said and "REQ-SET-001 went from Partial to Done" in said
    write(tmp_path, "0.3.0", ["0001_a.sql"], {"REQ-SET-001": "Partial", "REQ-SET-002": "No", "REQ-SET-004": "Done"})
    assert check_version_bump.main(tmp_path) == 1 and "REQ-SET-004 went from No to Done" in capsys.readouterr().err
    write(tmp_path, "0.4.0.dev0", ["0001_a.sql", "0002_b.sql"], {"REQ-SET-001": "Done", "REQ-SET-002": "No"})
    assert check_version_bump.main(tmp_path) == 0  # the version moved


def test_req_set_023_the_check_runs_in_ci_with_the_tags_and_passes_here() -> None:
    (job,) = [job for job in workflow("ci.yml")["jobs"].values() if job["name"] == "Version moves with what ships"]
    assert job["steps"][0]["with"] == {"fetch-depth": 0}  # the tags, for git describe
    assert job["steps"][-1]["run"] == "python tools/check_version_bump.py"
    assert check_version_bump.main() == 0
