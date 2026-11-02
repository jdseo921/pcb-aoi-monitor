"""The release kit (REQ-SET-027): what tools/release_kit.py puts in it, CI's assembly and check of it, and its two
scripts, which run on Windows only: verify.ps1 on a kit made here, inventory.ps1 on an uninstall entry made here."""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import sys
import uuid
from pathlib import Path

import pytest
import yaml

from aoi.config import APP_VERSION
from tools import release_kit

ROOT = Path(__file__).resolve().parents[1]
SETUP = f"AOI-PoC-Inspector-{APP_VERSION}-setup-x64-unsigned.exe"
windows = pytest.mark.skipif(sys.platform != "win32", reason="PowerShell's Authenticode and the registry: Windows CI")


def unsigned_exe() -> bytes:
    """An unsigned Windows program for Authenticode to read: pip's console-script launcher for pytest."""
    found = shutil.which("pytest")
    assert found is not None, "pytest's launcher is on PATH where the tests run"
    return Path(found).read_bytes()


def kit(tmp_path: Path, provenance: bool = False, exe: bytes = b"MZ an installer") -> Path:
    setup = tmp_path / SETUP
    setup.write_bytes(exe)
    bundle = tmp_path / "bundle.jsonl"
    bundle.write_text("{}\n", encoding="utf-8")
    out = tmp_path / "kit"
    release_kit.assemble(setup, out, bundle if provenance else None, bundle if provenance else None)
    return out


def test_req_set_027_the_kit_holds_the_installer_ca_note_scripts_and_the_hash_of_each(tmp_path: Path) -> None:
    out = kit(tmp_path, provenance=True)
    names = sorted(p.name for p in out.iterdir())
    note = f"release-note-{release_kit.note().stem}.md"
    assert names == sorted([SETUP, "pilot-ca.cer", note, "verify.ps1", "inventory.ps1", "SHA256SUMS.txt"] +
                           [release_kit.PROVENANCE, release_kit.TRUSTED_ROOT])  # fmt: skip
    sums = dict(reversed(line.split("  ")) for line in (out / "SHA256SUMS.txt").read_text("utf-8").splitlines())
    assert set(sums) == set(names) - {"SHA256SUMS.txt"}
    assert all(hashlib.sha256((out / n).read_bytes()).hexdigest() == h for n, h in sums.items())
    assert (out / "pilot-ca.cer").read_bytes() == (ROOT / "installer" / "pilot-ca.cer").read_bytes()
    assert release_kit.main(["--setup", str(tmp_path / "none.exe"), "--out", str(tmp_path / "k")]) == 2
    assert release_kit.note("9.9.9").name == "unreleased.md"


def test_req_set_027_ci_assembles_the_kit_checks_it_with_verify_ps1_and_keeps_it() -> None:
    flow = yaml.safe_load((ROOT / ".github" / "workflows" / "build.yml").read_text(encoding="utf-8"))
    steps = flow["jobs"]["windows"]["steps"]
    (provenance,) = [s for s in steps if s.get("id") == "provenance"]
    (assemble,) = [s for s in steps if "tools/release_kit.py" in s.get("run", "")]
    (kept,) = [s for s in steps if s.get("with", {}).get("name") == "${{ steps.info.outputs.name }}-kit"]
    assert steps.index(provenance) < steps.index(assemble) < steps.index(kept)
    assert assemble["env"]["BUNDLE"] == "${{ steps.provenance.outputs.bundle-path }}"
    assert (
        "gh attestation trusted-root" in assemble["run"] and "tools/release/verify.ps1 -Kit dist/kit" in assemble["run"]
    )
    assert kept["with"]["path"] == "dist/kit/" and kept["with"]["if-no-files-found"] == "error"
    runbook = (ROOT / "docs" / "release" / "runbook.md").read_text(encoding="utf-8")
    assert "docs/tests/station-checks.md" in runbook and "verify.ps1" in runbook and "inventory.ps1" in runbook


def powershell(script: str, *args: str) -> subprocess.CompletedProcess[str]:
    path = ROOT / "tools" / "release" / script
    cmd = ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(path), *args]
    return subprocess.run(cmd, capture_output=True, text=True, timeout=120, check=False)  # noqa: S603


@windows
def test_req_set_027_verify_ps1_passes_a_whole_kit_and_fails_a_changed_or_unsigned_one(tmp_path: Path) -> None:
    out = kit(tmp_path, exe=unsigned_exe())
    passed = powershell("verify.ps1", "-Kit", str(out), "-AllowUnsigned")
    assert passed.returncode == 0 and "All checks passed." in passed.stdout, passed.stdout + passed.stderr
    refused = powershell("verify.ps1", "-Kit", str(out))
    assert refused.returncode == 1 and "FAIL  Authenticode status of" in refused.stdout, refused.stdout
    assert "PASS  pilot-ca.cer is the pilot CA 3C45CCCB725E4611954743024C16E30F6E8483EF" in passed.stdout
    (out / SETUP).write_bytes(b"MZ another installer")
    (out / "extra.txt").write_text("x", encoding="utf-8")
    changed = powershell("verify.ps1", "-Kit", str(out), "-AllowUnsigned")
    assert changed.returncode == 1 and f"FAIL  SHA-256 of {SETUP}" in changed.stdout, changed.stdout
    assert "FAIL  extra.txt is in the kit but not in SHA256SUMS.txt" in changed.stdout


@windows
def test_req_set_027_inventory_ps1_reads_the_uninstall_entry_and_build_info(tmp_path: Path) -> None:
    import winreg

    base = rf"Software\AOI-test-{uuid.uuid4().hex}"
    entry = rf"{base}\{{7D122A0A-06CC-4538-A441-BD5D560E2255}}_is1"
    folder = tmp_path / "app"
    folder.mkdir()
    (folder / "BUILD-INFO.txt").write_text(f"AOI PoC Inspector {APP_VERSION}+7, pilot build g1234567\n", "utf-8")
    try:
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, entry) as key:
            winreg.SetValueEx(key, "DisplayName", 0, winreg.REG_SZ, f"AOI PoC Inspector {APP_VERSION} (pilot, signed)")
            winreg.SetValueEx(key, "DisplayVersion", 0, winreg.REG_SZ, APP_VERSION)
            winreg.SetValueEx(key, "InstallLocation", 0, winreg.REG_SZ, str(folder))
        found = powershell("inventory.ps1", "-Uninstall", rf"HKCU:\{base}", "-Json")
        assert found.returncode == 0, found.stdout + found.stderr
        shown = json.loads(found.stdout)
        assert shown["Name"].endswith("(pilot, signed)") and shown["Version"] == APP_VERSION
        assert shown["Build"].endswith("g1234567") and shown["ExeVersion"] is None
        gone = powershell("inventory.ps1", "-Uninstall", rf"HKCU:\{base}-none")
        assert gone.returncode == 1 and "is not installed" in gone.stdout
    finally:
        winreg.DeleteKey(winreg.HKEY_CURRENT_USER, entry)
        winreg.DeleteKey(winreg.HKEY_CURRENT_USER, base)
