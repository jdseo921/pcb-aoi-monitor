"""tools/check_licenses.py: the CI license gate (Charter checklist line 8; Legal standard, "Licenses"), and the Qt
modules the code may import (only those PySide6_Essentials ships: no Qt Charts, Legal standard, "Packaging")."""

from __future__ import annotations

import ast
import json
import subprocess
import sys
from importlib import metadata
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "tools" / "check_licenses.py"
GPL = "GPL-3.0-only"


def _run(rows: list[dict[str, str]], *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args], input=json.dumps(rows), capture_output=True, text=True, check=False
    )


def test_license_gate_passes_allowed_and_fails_gpl(tmp_path: Path) -> None:
    ok_rows = [
        {"Name": "numpy", "Version": "2.4.6", "License": "BSD-3-Clause AND 0BSD AND MIT AND Zlib AND CC0-1.0"},
        {"Name": "packaging", "Version": "26.3", "License": "Apache-2.0 OR BSD-2-Clause"},
        {"Name": "PySide6_Essentials", "Version": "6.11.2", "License": "LGPL-3.0-only OR GPL-2.0-only OR GPL-3.0-only"},
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


def _lock(tmp_path: Path, text: str) -> Path:
    lock = tmp_path / "requirements.lock"
    lock.write_text(text, encoding="utf-8")
    return lock


def test_license_gate_fails_a_gpl_package_named_in_packages_and_names_it(tmp_path: Path) -> None:
    lock = _lock(tmp_path, "numpy==2.4.6 \\\n    --hash=sha256:00\ngpl-lib==1.0 \\\n    --hash=sha256:11\n")
    rows = [{"Name": "numpy", "Version": "2.4.6", "License": "BSD-3-Clause"}]
    res = _run([*rows, {"Name": "gpl-lib", "Version": "1.0", "License": GPL}], "--packages", str(lock))
    assert res.returncode == 1, res.stdout
    assert f"  NOT ALLOWED              gpl-lib 1.0: {GPL}" in res.stdout.splitlines(), res.stdout
    assert res.stdout.endswith(f"Licenses not allowed by the Legal & Compliance standard:\n  gpl-lib 1.0: {GPL}\n")


def test_license_gate_reports_a_gpl_dev_only_package_but_does_not_fail(tmp_path: Path) -> None:
    rows = [{"Name": "numpy", "Version": "2.4.6", "License": "BSD-3-Clause"}]
    res = _run(
        [*rows, {"Name": "gpl-dev-tool", "Version": "2.0", "License": GPL}],
        "--packages",
        str(_lock(tmp_path, "numpy==2.4.6\n")),
    )
    assert res.returncode == 0, res.stdout
    shipped, dev = res.stdout.split("Development and CI packages, not shipped, 1 reported")
    assert "gpl-dev-tool" not in shipped
    assert f"  NOT ALLOWED              gpl-dev-tool 2.0: {GPL}" in dev.splitlines(), res.stdout


def test_license_gate_fails_a_package_named_in_packages_that_is_not_installed(tmp_path: Path) -> None:
    """The gate cannot vouch for a package it did not see: pip-licenses run without --with-system leaves out
    setuptools, and a PyTorch lock checked in an environment without PyTorch leaves out torch."""
    lock = _lock(tmp_path, "numpy==2.4.6\nsetuptools==84.0.0 \\\n    --hash=sha256:00\n")
    res = _run([{"Name": "numpy", "Version": "2.4.6", "License": "BSD-3-Clause"}], "--packages", str(lock))
    assert res.returncode == 1, res.stdout
    assert "not installed here" in res.stdout
    assert "  setuptools==84.0.0 (requirements.lock)" in res.stdout.splitlines(), res.stdout


def test_license_gate_skips_a_requirement_whose_marker_is_false_here(tmp_path: Path) -> None:
    """A requirement for another platform is neither checked nor missing here; one whose marker is true is checked."""
    old = 'old-python-gpl==1.0 ; python_version < "3.0" \\\n    --hash=sha256:00\n'
    rows = [
        {"Name": "numpy", "Version": "2.4.6", "License": "BSD-3-Clause"},
        {"Name": "old-python-gpl", "Version": "1.0", "License": GPL},  # installed all the same: reported, not failed
    ]
    res = _run(rows, "--packages", str(_lock(tmp_path, f"numpy==2.4.6\n{old}")))
    assert res.returncode == 0, res.stdout
    assert 'Skipped, its environment marker is false here: old-python-gpl==1.0; python_version < "3.0" ' in res.stdout
    now = 'new-python-gpl==1.0 ; python_version >= "3.0"\n'
    rows.append({"Name": "new-python-gpl", "Version": "1.0", "License": GPL})
    res = _run(rows, "--packages", str(_lock(tmp_path, f"numpy==2.4.6\n{old}{now}")))
    assert res.returncode == 1 and f"  new-python-gpl 1.0: {GPL}" in res.stdout.splitlines(), res.stdout


def test_license_gate_prints_every_shipped_package_with_its_verdict_and_counts_those_checked(tmp_path: Path) -> None:
    lock = _lock(
        tmp_path,
        "--index-url https://example.invalid\nnumpy==2.4.6\ntyping-extensions==4.16.0\npyside6-essentials==6.11.2\n"
        'colorama==0.4.6 ; python_version < "3.0"\n',
    )
    rows = [
        {"Name": "numpy", "Version": "2.4.6", "License": "BSD-3-Clause"},
        {"Name": "typing_extensions", "Version": "4.16.0", "License": "PSF-2.0"},
        {"Name": "PySide6_Essentials", "Version": "6.11.2", "License": "LGPL-3.0-only OR GPL-3.0-only"},
        {"Name": "pytest", "Version": "9.1.1", "License": "MIT"},
    ]
    res = _run(rows, "--packages", str(lock))
    assert res.returncode == 0, res.stdout
    assert res.stdout.splitlines() == [
        "Shipped packages (requirements.lock), 3 checked:",
        "  allowed                  numpy 2.4.6: BSD-3-Clause",
        "  allowed as named package PySide6_Essentials 6.11.2: LGPL-3.0-only OR GPL-3.0-only",
        "  exception pending J8     typing_extensions 4.16.0: PSF-2.0 [psf-2.0]",
        "Development and CI packages, not shipped, 1 reported (they cannot fail the check):",
        "  allowed                  pytest 9.1.1: MIT",
        'Skipped, its environment marker is false here: colorama==0.4.6; python_version < "3.0" (requirements.lock)',
        "exception in use (pending Jay, J8): psf-2.0 <- typing_extensions",
        "License check passed for 3 shipped packages.",
    ]


def essentials_modules() -> set[str]:
    """The modules the PySide6_Essentials distribution installs, read from its own file list: the compiled modules
    (.pyd on Windows, .so elsewhere) and the Python modules and packages right under PySide6/. Not its .pyi stubs:
    6.11.2 ships a stub for every Qt module, QtCharts.pyi of the Addons included."""
    shipped = set()
    for file in metadata.files("PySide6_Essentials") or ():
        parts = file.parts
        if len(parts) == 2 and parts[0] == "PySide6" and file.suffix in (".pyd", ".so", ".py"):
            shipped.add(parts[1].split(".", 1)[0])
        elif len(parts) == 3 and parts[0] == "PySide6" and parts[2] == "__init__.py":
            shipped.add(parts[1])
    return shipped


def qt_imports_outside(source: str, shipped: set[str]) -> list[str]:
    """Each import in `source` of a PySide6 module that `shipped` does not hold, as "line: module"; a star import
    counts, since it could bring in any of them, and so does importlib.import_module or __import__ with a literal."""
    found = []
    for node in ast.walk(ast.parse(source)):
        modules: list[str] = []
        if isinstance(node, ast.Import):
            modules = [alias.name for alias in node.names]
        elif isinstance(node, ast.ImportFrom) and node.module == "PySide6":
            modules = [f"PySide6.{alias.name}" for alias in node.names if not alias.name.startswith("__")]
        elif isinstance(node, ast.ImportFrom) and node.module:
            modules = [node.module]
        elif isinstance(node, ast.Call) and node.args and isinstance(node.args[0], ast.Constant):
            func = node.func
            called = func.attr if isinstance(func, ast.Attribute) else func.id if isinstance(func, ast.Name) else ""
            modules = [str(node.args[0].value)] if called in ("import_module", "__import__") else []
        for module in modules:
            top, _, sub = module.partition(".")
            if top == "PySide6" and sub and sub.split(".")[0] not in shipped:
                found.append(f"{node.lineno}: {module}")
    return found


def test_issue_17_qt_modules_come_only_from_pyside6_essentials() -> None:
    """Every PySide6 module the app, its tools and its tests import is one PySide6_Essentials ships, since the
    PySide6-Addons wheel holds GPL-only Qt modules (Qt Charts, Qt Graphs, Qt Data Visualization; Legal standard,
    "Packaging") and is no longer installed. Read from the syntax tree, and from Essentials' own file list, so it
    holds where the Addons are installed too."""
    shipped = essentials_modules()
    assert {"QtCore", "QtGui", "QtWidgets", "QtTest"} <= shipped, sorted(shipped)
    assert not {"QtCharts", "QtGraphs", "QtDataVisualization"} & shipped, sorted(shipped)
    files = sorted({*(ROOT / "aoi").rglob("*.py"), *(ROOT / "tools").rglob("*.py"), *(ROOT / "tests").rglob("*.py")})
    offenders = {
        str(path.relative_to(ROOT)): found
        for path in [*files, ROOT / "main.py"]
        if (found := qt_imports_outside(path.read_text(encoding="utf-8"), shipped))
    }
    assert offenders == {}, f"Qt modules that only PySide6-Addons ships: {offenders}"
    assert qt_imports_outside("from PySide6.QtWidgets import QWidget\nimport PySide6.QtCore\n", shipped) == []
    assert qt_imports_outside("from PySide6 import QtGui, __version__", shipped) == []
    for addon in (
        "from PySide6 import QtCharts",
        "import PySide6.QtGraphs",
        "from PySide6 import QtCore, QtCharts",
        "from PySide6.QtDataVisualization import Q3DBars",
        "import PySide6.QtCharts as charts",
        "from PySide6 import *",
        'importlib.import_module("PySide6.QtCharts")',
    ):
        assert qt_imports_outside(addon, shipped), f"not caught: {addon}"
