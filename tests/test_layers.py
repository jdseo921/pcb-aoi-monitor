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
UI_DIR = ROOT / "aoi" / "ui"
FORBIDDEN_IN_UI = ("sqlite3", "aoi.data")  # the data layer is reached only through AppContext (REQ-USR-001)
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


def imported_names(node: ast.AST, package: str) -> list[str]:
    """The absolute names an import statement brings in; a relative import is resolved against `package`."""
    if isinstance(node, ast.Import):
        return [alias.name for alias in node.names]
    if isinstance(node, ast.ImportFrom):
        base = node.module or ""
        if node.level:
            parts = package.split(".")
            base = ".".join(parts[: len(parts) - node.level + 1] + ([base] if base else []))
        return [base] + [f"{base}.{alias.name}" for alias in node.names]
    return []


def test_req_usr_001_pages_use_appcontext_only() -> None:
    """Screens reach data and the engine only through AppContext (stage S15): no sqlite3 or aoi.data import, no `.db`
    on the context, no SQL `.execute(` and no Inspector built in a page."""
    found: list[str] = []
    for path in sorted(UI_DIR.rglob("*.py")):
        package = module_name(path) if path.name == "__init__.py" else module_name(path).rpartition(".")[0]
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"), filename=str(path))):
            where = f"{path.relative_to(ROOT)}:{getattr(node, 'lineno', 0)}"
            for name in imported_names(node, package):
                if name in FORBIDDEN_IN_UI or name.startswith("aoi.data.") or name.endswith(".Inspector"):
                    found.append(f"{where} imports {name}")
            if isinstance(node, ast.Attribute) and node.attr == "db":
                found.append(f"{where} reaches .db")
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "execute":
                found.append(f"{where} calls .execute(")
    assert not found, "screens must go through AppContext: " + ", ".join(found)
