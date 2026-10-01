"""Architecture rule from the Engineering standard ("Layers"): aoi/core and aoi/data never import Qt.

The engine has to run headless (tests, a future CLI, the robot cycle, an MES service), so a Qt
import anywhere in these packages, direct, inside a function or pulled in through another
module, fails the build.
"""

import ast
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ENGINE_DIRS = (ROOT / "aoi" / "core", ROOT / "aoi" / "data")
QT_PACKAGES = {"PySide6", "PySide2", "PyQt5", "PyQt6", "shiboken6", "shiboken2"}


def engine_files() -> list[Path]:
    return sorted(p for d in ENGINE_DIRS for p in d.rglob("*.py"))


def module_name(path: Path) -> str:
    parts = path.relative_to(ROOT).with_suffix("").parts
    return ".".join(parts[:-1] if parts[-1] == "__init__" else parts)


def test_engine_source_has_no_qt_import() -> None:
    found = []
    for path in engine_files():
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"), filename=str(path))):
            if isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                names = [node.module]
            else:
                continue
            found += [f"{path.relative_to(ROOT)}:{node.lineno} {n}" for n in names if n.split(".")[0] in QT_PACKAGES]
    assert not found, "Qt imported in the engine or data layer: " + ", ".join(found)


def test_importing_the_engine_loads_no_qt() -> None:
    # A fresh interpreter, so nothing imported by pytest or other tests can hide or fake a result.
    code = (
        "import importlib, sys\n"
        f"for name in {[module_name(p) for p in engine_files()]!r}:\n"
        "    importlib.import_module(name)\n"
        f"print(' '.join(sorted(m for m in sys.modules if m.split('.')[0] in {sorted(QT_PACKAGES)!r})))\n"
    )
    result = subprocess.run([sys.executable, "-c", code], cwd=ROOT, capture_output=True, text=True, check=True)
    assert result.stdout.strip() == "", "importing aoi/core and aoi/data loaded Qt: " + result.stdout.strip()
