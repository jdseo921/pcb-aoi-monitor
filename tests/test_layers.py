"""Architecture rule from the Engineering standard ("Layers"): aoi/core and aoi/data never import Qt.

The engine has to run headless (tests, a future CLI, the robot cycle, an MES service), so a Qt
import anywhere in these packages, direct, inside a function or pulled in through another
module, fails the build.
"""

import ast
import importlib
import inspect
import sqlite3
import subprocess
import sys
from pathlib import Path

import cv2

from aoi.core import imaging

ROOT = Path(__file__).resolve().parents[1]
ENGINE_DIRS = (ROOT / "aoi" / "core", ROOT / "aoi" / "data")
UI_DIR = ROOT / "aoi" / "ui"
# The data layer is reached only through AppContext (REQ-USR-001), and so is an image file: `AppContext.load_image`
# applies the size limits from Settings, which a page reading the file itself would skip (REQ-INSP-001).
FORBIDDEN_IN_UI = ("sqlite3", "aoi.data", "cv2.imread", "cv2.imdecode")
# Forbidden whatever module they are imported through: services imports both readers and Database for its own use, so
# they resolve there too (#202).
FORBIDDEN_NAMES = (".load_image", ".load_image_sha256", ".Database")
IMAGE_READERS = ("load_image", "load_image_sha256", "imread", "imdecode")
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


def callee_name(func: ast.expr) -> str:
    """The name a call is made through: `Inspector(...)` or `inspector.Inspector(...)` both give "Inspector"."""
    if isinstance(func, ast.Attribute):
        return func.attr
    return func.id if isinstance(func, ast.Name) else ""


def through_context(value: ast.expr) -> bool:
    """`ctx.load_image` or `self.ctx.load_image`: the context's own reader, the one place the size limits apply."""
    if isinstance(value, ast.Name):
        return value.id == "ctx"
    return isinstance(value, ast.Attribute) and value.attr == "ctx"


def appcontext_violations(path: Path, package: str) -> list[str]:
    """What a screen module does outside AppContext, each as "file:line what": a sqlite3 or aoi.data import, `Database`,
    `load_image` or `load_image_sha256` imported from any module, `load_image` or `load_image_sha256` called by its bare
    name or on anything but the context, `cv2.imread` or `cv2.imdecode`, an `Inspector` imported outside
    `if TYPE_CHECKING:` or built by its bare or dotted name, `.db`, or SQL `.execute(`, `.executemany(` or
    `.executescript(`."""
    found: list[str] = []
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    type_only = {
        inner
        for node in ast.walk(tree)
        if isinstance(node, ast.If) and isinstance(node.test, ast.Name) and node.test.id == "TYPE_CHECKING"
        for stmt in node.body
        for inner in ast.walk(stmt)
    }
    shown = path.relative_to(ROOT) if path.is_relative_to(ROOT) else path.name
    for node in ast.walk(tree):
        where = f"{shown}:{getattr(node, 'lineno', 0)}"
        for name in imported_names(node, package):
            forbidden = name in FORBIDDEN_IN_UI or name.startswith("aoi.data.") or name.endswith(FORBIDDEN_NAMES)
            forbidden = forbidden or name.endswith(".Inspector")
            if forbidden and not (name.endswith(".Inspector") and node in type_only):
                found.append(f"{where} imports {name}")
        if isinstance(node, ast.Call) and callee_name(node.func) == "Inspector":
            found.append(f"{where} builds an Inspector")
        if isinstance(node, ast.Attribute) and node.attr == "db":
            found.append(f"{where} reaches .db")
        if isinstance(node, ast.Attribute) and node.attr in IMAGE_READERS and not through_context(node.value):
            found.append(f"{where} reads an image outside AppContext")
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in IMAGE_READERS:
            found.append(f"{where} reads an image outside AppContext")
        sql = ("execute", "executemany", "executescript")
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr in sql:
            found.append(f"{where} calls .{node.func.attr}(")
    return found


def test_req_usr_001_pages_use_appcontext_only() -> None:
    """Screens reach data and the engine only through AppContext (stage S15): no sqlite3 or aoi.data import, no `.db`
    on the context, no SQL `.execute(` (nor `.executemany(` or `.executescript(`, #202) and no Inspector built in a page
    (the `Inspector` name may be imported under `if TYPE_CHECKING:` for a type hint, since S22b), and no `load_image`
    imported or called on a module: the settings' size limits apply only through `AppContext.load_image`
    (REQ-INSP-001, since S23c). Since #202 that holds through any module (`Database` and `load_image` resolve on
    services too), for a bare `load_image(p)` call and for `cv2.imread` and `cv2.imdecode`."""
    found: list[str] = []
    for path in sorted(UI_DIR.rglob("*.py")):
        package = module_name(path) if path.name == "__init__.py" else module_name(path).rpartition(".")[0]
        found += appcontext_violations(path, package)
    assert not found, "screens must go through AppContext: " + ", ".join(found)


def test_req_usr_001_the_scan_catches_a_built_inspector(tmp_path: Path) -> None:
    """The scan itself: a runtime import of Inspector, an Inspector built by its bare or dotted name, `.db`,
    `.execute(` and `load_image` imported or called on a module are flagged, and so are (#202) `Database` and both
    readers imported through services, a bare `load_image(p)`, `cv2.imread`, `cv2.imdecode`, `.executemany(` and
    `.executescript(`; the import under `if TYPE_CHECKING:`, `load_image` on the context and other cv2 calls are not."""
    sample = tmp_path / "sample.py"
    sample.write_text(
        "from typing import TYPE_CHECKING\n"
        "from ...core.inspector import Inspector\n"
        "from ...core import imaging, inspector\n"
        "from ...core.imaging import IMAGE_EXTS, load_image\n"
        "if TYPE_CHECKING:\n"
        "    from ...core.inspector import Inspector\n"
        "def f(ctx, recipe, path):\n"
        "    a = Inspector(recipe)\n"
        "    b = inspector.Inspector(recipe)\n"
        "    ctx.db.execute('DELETE FROM inspections')\n"
        "    return a, b, imaging.load_image(path), ctx.load_image(path), self.ctx.load_image(path)\n"
        "from ...core.services import AppContext, Database, load_image, load_image_sha256\n"
        "import cv2\n"
        "def g(ctx, path, conn):\n"
        "    load_image(path), load_image_sha256(path), cv2.imread(path), cv2.imdecode(path, 1)\n"
        "    conn.executescript('DELETE FROM inspections'), conn.executemany('DELETE FROM alarms', [])\n"
        "    return cv2.cvtColor(ctx.load_image(path), cv2.COLOR_BGR2RGB)\n",
        encoding="utf-8",
    )
    assert sorted(appcontext_violations(sample, "aoi.ui.pages")) == [
        "sample.py:10 calls .execute(",
        "sample.py:10 reaches .db",
        "sample.py:11 reads an image outside AppContext",
        "sample.py:12 imports aoi.core.services.Database",
        "sample.py:12 imports aoi.core.services.load_image",
        "sample.py:12 imports aoi.core.services.load_image_sha256",
        "sample.py:15 reads an image outside AppContext",
        "sample.py:15 reads an image outside AppContext",
        "sample.py:15 reads an image outside AppContext",
        "sample.py:15 reads an image outside AppContext",
        "sample.py:16 calls .executemany(",
        "sample.py:16 calls .executescript(",
        "sample.py:2 imports aoi.core.inspector.Inspector",
        "sample.py:4 imports aoi.core.imaging.load_image",
        "sample.py:8 builds an Inspector",
        "sample.py:9 builds an Inspector",
    ]


def test_req_usr_001_no_screen_module_holds_the_data_layer_or_an_image_reader() -> None:
    """What every screen module holds once imported, whatever name or module it came through (#202): no sqlite3, nothing
    from aoi.data (`Database` re-exported by services included) and no reader that skips the settings' size limits."""
    readers = (imaging.load_image, imaging.load_image_sha256, cv2.imread, cv2.imdecode)
    found = []
    for path in sorted(UI_DIR.rglob("*.py")):
        module = importlib.import_module(module_name(path))
        for name, value in vars(module).items():
            origin = str(getattr(value, "__name__" if inspect.ismodule(value) else "__module__", "") or "")
            if value is sqlite3 or any(value is r for r in readers) or origin.split(".")[:2] == ["aoi", "data"]:
                found.append(f"{module.__name__}.{name}")
    assert not found, "screens must go through AppContext: " + ", ".join(found)
