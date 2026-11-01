"""Version discipline (REQ-SET-023): the version moves with what ships, and every build says which one it is.

CI fails a migration or a register status change since the last v* tag without a new APP_VERSION
(tools/check_version_bump.py); the Windows build carries CI's run number in BUILD-INFO.txt, the log's app_version and
the .exe's VERSIONINFO; a pilot-signed build is named and labelled so (tests/test_installer.py and
tests/test_windows_build.py, `test_req_set_023_*`). The .exe's resource is read on Windows CI only.
"""

from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest
import yaml

from aoi import config, logging_setup
from aoi.config import APP_NAME, build_number, version_label
from tools import check_version_bump, version_info

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
    write(tmp_path, "0.3.0", ["0001_a.sql"], {"REQ-SET-001": "Partial", "REQ-SET-002": "No", "REQ-P3D-001": "Done"})
    assert check_version_bump.main(tmp_path) == 1 and "REQ-P3D-001 went from No to Done" in capsys.readouterr().err
    write(tmp_path, "0.4.0", ["0001_a.sql", "0002_b.sql"], {"REQ-SET-001": "Done", "REQ-SET-002": "No"})
    assert check_version_bump.main(tmp_path) == 0  # the version moved
    git(tmp_path, "add", "-A")
    git(tmp_path, "commit", "-qm", "0.4.0")
    git(tmp_path, "tag", "v0.4.0-rc.1")
    write(tmp_path, "0.4.0", ["0001_a.sql", "0002_b.sql", "0003_c.sql"], {"REQ-SET-001": "Done", "REQ-SET-002": "Done"})
    assert check_version_bump.main(tmp_path) == 0  # a fix after a release candidate ships as the version it names
    assert "v0.4.0-rc.1 is a pre-release of 0.4.0" in capsys.readouterr().out


def test_req_set_023_the_check_runs_in_ci_with_the_tags_and_passes_here() -> None:
    (job,) = [job for job in workflow("ci.yml")["jobs"].values() if job["name"] == "Version moves with what ships"]
    assert job["steps"][0]["with"] == {"fetch-depth": 0}  # the tags, for git describe
    assert job["steps"][-1]["run"] == "python tools/check_version_bump.py"
    assert check_version_bump.main() == 0


def test_req_set_023_the_log_carries_the_build_number_of_a_ci_build(tmp_path: Path) -> None:
    assert build_number() is None and config.APP_LABEL == config.APP_VERSION  # from source
    (tmp_path / "BUILD").write_text("57\n", encoding="ascii")
    assert build_number(tmp_path) == 57 and version_label(57) == f"{config.APP_VERSION}+build.57"
    (tmp_path / "BUILD").write_text("", encoding="ascii")  # a build made by hand
    assert build_number(tmp_path) is None and build_number(tmp_path / "none") is None
    assert re.search(r'"app_version": APP_LABEL,', (ROOT / "aoi" / "logging_setup.py").read_text(encoding="utf-8"))
    assert logging_setup.APP_LABEL is config.APP_LABEL
    spec = (ROOT / "installer" / "aoi.spec").read_text(encoding="utf-8")
    assert '(str(Path(workpath) / "BUILD"), "."),' in spec and 'os.environ["AOI_BUILD_NUMBER"]' in spec
    assert workflow("build.yml")["jobs"]["windows"]["env"]["AOI_BUILD_NUMBER"] == "${{ github.run_number }}"


def test_req_set_023_the_exe_carries_a_versioninfo_resource() -> None:
    assert version_info.numbers("0.4.0.dev0", 57) == (0, 4, 0, 57) and version_info.numbers("1.2.3", None) == (
        1,
        2,
        3,
        0,
    )
    assert version_info.flags("0.4.0.dev0") == version_info.flags("1.0.0rc1") == version_info.PRERELEASE
    assert version_info.flags("1.0.0") == 0
    with pytest.raises(ValueError):
        version_info.numbers("0.4.0", 70000)
    fields = version_info.strings(APP_NAME, version_label(57), "0.4.0.dev0", 57)
    assert fields["ProductVersion"] == f"{config.APP_VERSION}+build.57" and fields["FileVersion"] == "0.4.0.57"
    assert fields["OriginalFilename"] == "AOI-PoC-Inspector.exe" and fields["ProductName"] == APP_NAME
    spec = (ROOT / "installer" / "aoi.spec").read_text(encoding="utf-8")
    assert "version_info.resource(APP_NAME, version_label(BUILD), APP_VERSION, BUILD)" in spec
    assert "upx=False, version=version)" in spec
    steps = workflow("build.yml")["jobs"]["windows"]["steps"]
    ids = [step.get("id") for step in steps]
    assert ids.index("build") < ids.index("versioninfo") < ids.index("smoke")
    assert ").VersionInfo.ProductVersion" in steps[ids.index("versioninfo")]["run"]


def test_req_set_023_one_value_says_whether_a_build_is_signed_and_by_whose_certificate() -> None:
    job = workflow("build.yml")["jobs"]["windows"]
    signed = "${{ github.event_name != 'pull_request' && secrets.PILOT_SIGNING_PFX != '' && 'true' || 'false' }}"
    assert job["env"]["SIGNED"] == signed
    signing = [step for step in job["steps"] if "pilot_sign.ps1" in str(step.get("run"))]
    assert len(signing) == 2 and all(step["if"] == "env.SIGNED == 'true'" for step in signing)
    # The name the installer and BUILD-INFO.txt give is the one in the committed pilot CA: "CN=<name> pilot root CA"
    der = (ROOT / "installer" / "pilot-ca.cer").read_bytes()
    at = der.index(b"\x55\x04\x03") + 3  # the commonName attribute, then its string's tag and length
    assert der[at + 2 : at + 2 + der[at + 1]].decode() == f"{job['env']['PILOT_SIGNER']} pilot root CA"
