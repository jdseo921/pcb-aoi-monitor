"""tools/check_licenses.py: the CI license gate (Charter checklist line 8; Legal standard, "Licenses")."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "tools" / "check_licenses.py"


def _run(rows: list[dict[str, str]], *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args], input=json.dumps(rows), capture_output=True, text=True, check=False
    )


def test_license_gate_passes_allowed_and_fails_gpl(tmp_path: Path) -> None:
    ok_rows = [
        {"Name": "numpy", "Version": "2.4.6", "License": "BSD-3-Clause AND 0BSD AND MIT AND Zlib AND CC0-1.0"},
        {"Name": "packaging", "Version": "26.3", "License": "Apache-2.0 OR BSD-2-Clause"},
        {"Name": "PySide6", "Version": "6.11.2", "License": "LGPL-3.0-only OR GPL-2.0-only OR GPL-3.0-only"},
    ]
    res = _run(ok_rows)
    assert res.returncode == 0, res.stdout + res.stderr
    assert "exception in use" in res.stdout  # numpy's Zlib and CC0 parts are pending exceptions

    gpl = ok_rows + [{"Name": "fake-gpl-lib", "Version": "1.0", "License": "GPL-3.0-only"}]
    res = _run(gpl)
    assert res.returncode == 1
    assert "fake-gpl-lib 1.0: GPL-3.0-only" in res.stdout

    unknown = ok_rows + [{"Name": "mystery", "Version": "0.1", "License": "UNKNOWN"}]
    assert _run(unknown).returncode == 1


def test_license_gate_checks_only_shipped_packages(tmp_path: Path) -> None:
    lock = tmp_path / "requirements.lock"
    lock.write_text("numpy==2.4.6\n# comment\n", encoding="utf-8")
    rows = [
        {"Name": "numpy", "Version": "2.4.6", "License": "BSD-3-Clause"},
        {"Name": "dev-only-gpl", "Version": "1.0", "License": "GPL-3.0-only"},
    ]
    res = _run(rows, "--packages", str(lock))
    assert res.returncode == 0, res.stdout + res.stderr


def test_license_gate_reads_every_package_file(tmp_path: Path) -> None:
    """CI names requirements.lock and the PyTorch lock: a package in the second file is checked too."""
    lock = tmp_path / "requirements.lock"
    lock.write_text("numpy==2.4.6 \\\n    --hash=sha256:00\n", encoding="utf-8")
    torch_lock = tmp_path / "requirements-torch-cpu.lock"
    torch_lock.write_text(
        "--index-url https://example.invalid/cpu\ntorch==2.14.1+cpu \\\n    --hash=sha256:11\n", encoding="utf-8"
    )
    rows = [
        {"Name": "numpy", "Version": "2.4.6", "License": "BSD-3-Clause"},
        {"Name": "torch", "Version": "2.14.1+cpu", "License": "GPL-3.0-only"},
    ]
    res = _run(rows, "--packages", str(lock))
    assert res.returncode == 0, res.stdout + res.stderr
    res = _run(rows, "--packages", str(lock), str(torch_lock))
    assert res.returncode == 1
    assert "torch 2.14.1+cpu: GPL-3.0-only" in res.stdout
