"""Every visible string goes through tr() and the translation file is current (REQ-SET-005; S19, S20).

S19 covers the Page base, Home, the frame (header, sidebar, dialogs), Inspection, Compare and Logs & Export; S20
Training, AI Model Test, Settings, 3D Profile, the Recipe Editor and the scan for untranslated literals. Korean
translations themselves are a later stage: the file lists the strings.
"""

from __future__ import annotations

import ast
import re
import subprocess
import xml.etree.ElementTree as ET
from pathlib import Path

from PySide6.QtCore import QCoreApplication, QTranslator
from PySide6.QtWidgets import QPushButton
from pytestqt.qtbot import QtBot

from aoi.core.inspector import Inspector
from aoi.core.recipe import Recipe
from aoi.core.services import AppContext
from aoi.hal import VIEWS
from aoi.ui.main_window import MainWindow
from aoi.ui.pages.base import VIEW_NAMES
from aoi.ui.pages.compare import CHECK_NAMES, MODE_AI, MODES, RULES, SOURCES
from tests.conftest import TrainedModel
from tools.update_translations import ROOT, TS_FILE, qt_tool, update

PLACEHOLDER = re.compile(r"\{(\w+)(?::[^}]*)?\}")
S19_CONTEXTS = {"Page", "Role", "View", "HomePage", "MainWindow", "InspectionPage", "ComparePage", "LogsPage"}
S20_CONTEXTS = {"TrainingPage", "NgDialog", "ModelTestPage", "SettingsPage", "Profile3DPage", "RecipeEditorPage"}

# The scan for untranslated literals (test_req_set_005_no_untranslated_literals).
TRANSLATORS = {"tr", "translate", "QT_TRANSLATE_NOOP", "page_text", "role_text", "view_text"}
TEXT_SETTERS = {  # Qt methods whose string arguments appear on screen, and this code's own helpers that show text
    "setText", "setWindowTitle", "setToolTip", "setStatusTip", "setWhatsThis", "setPlaceholderText", "setTitle",
    "setSpecialValueText", "setPrefix", "setSuffix", "addItem", "addItems", "insertItem", "addTab", "addRow",
    "setHtml", "setPlainText", "appendPlainText", "setHorizontalHeaderLabels", "setVerticalHeaderLabels",
    "showMessage", "setLabelText", "setInformativeText", "setDetailedText", "setTabText", "setItemText",
    "show_state", "status", "action", "fill_table",
}  # fmt: skip
OWNED_SETTERS = {  # static methods that show text when called on these classes (QMessageBox.warning, not log.warning)
    "QMessageBox": {"information", "warning", "critical", "question", "about"},
    "QInputDialog": {"getItem", "getText", "getInt", "getDouble", "getMultiLineText"},
    "QFileDialog": {"getOpenFileName", "getOpenFileNames", "getSaveFileName", "getExistingDirectory"},
}
TEXT_CONSTRUCTORS = {
    "QLabel", "QPushButton", "QCheckBox", "QRadioButton", "QGroupBox", "QAction", "QMenu", "QListWidgetItem",
    "QTableWidgetItem", "QMessageBox", "button", "make_table", "BusyOverlay", "ImageView", "MetricTile", "EmptyState",
    "AoiError",
}  # fmt: skip
# button(text, kind, slot), action(text, key, slot): text first; AoiError(code, detail, **values): the values (#198);
# QComboBox.addItem(text, data): the item's data is no text (#199)
TEXT_POSITIONS = {"button": 1, "action": 1, "AoiError": 0, "addItem": 1}
SKIP_KEYWORDS = {"kind", "slot", "parent", "over", "detail"}  # an error's detail goes to the log only
ALLOWED_LITERALS = {  # (file, literal): why it is not translated; a stale entry fails the test
    ("aoi/ui/pages/base.py", "Page"): "placeholder title of the base class; every page overrides it",
    ("aoi/ui/pages/settings.py", "auto"): "a torch device name, shown as the value the engine takes",
    ("aoi/ui/pages/settings.py", "cpu"): "a torch device name",
    ("aoi/ui/pages/settings.py", "cuda"): "a torch device name",
    ("aoi/ui/pages/settings.py", "English"): "a language is named in its own language in the language list",
    ("aoi/ui/pages/settings.py", "한국어"): "a language is named in its own language in the language list",
}
TAG_OR_ENTITY = re.compile(r"<[^>]*>|&\w+;")
FILE_NAME = re.compile(r"\S+\.[A-Za-z0-9]{1,5}")


def _messages(ts: Path) -> dict[tuple[str, str], str]:
    """{(context, source): translation} of a .ts file."""
    root = ET.parse(ts).getroot()
    return {
        (c.findtext("name") or "", m.findtext("source") or ""): m.findtext("translation") or ""
        for c in root.findall("context")
        for m in c.findall("message")
    }


def test_req_set_005_translation_file_is_generated_from_the_sources(tmp_path: Path) -> None:
    """aoi/i18n/aoi_ko.ts holds exactly the strings pyside6-lupdate finds today, so a changed string without a rerun
    of tools/update_translations.py fails the build; every placeholder is a named {field}, never an f-string, and a
    translation names the same placeholders as its source, since a misspelt one would stop the screen with a
    KeyError."""
    fresh = _messages(update(tmp_path / "fresh.ts"))
    committed = _messages(TS_FILE)
    assert set(fresh) == set(committed), "the file is stale: python tools/update_translations.py"
    assert S19_CONTEXTS | S20_CONTEXTS <= {context for context, _ in committed}
    for (context, source), translation in committed.items():
        assert "{self." not in source and "{len(" not in source, (context, source)
        assert all(name.isidentifier() for name in PLACEHOLDER.findall(source)), (context, source)
        named = set(PLACEHOLDER.findall(translation))
        assert not translation or named == set(PLACEHOLDER.findall(source)), (context, source, translation)
    assert ("Page", "Home") in committed and ("LogsPage", "Filter") in committed and ("Role", "Admin") in committed
    assert ("SettingsPage", "Version {version}") in committed and ("NgDialog", "Label NG images") in committed


def test_req_set_005_engine_names_and_camera_views_have_display_strings(tiny_model: TrainedModel) -> None:
    """The engine names checks, their sources, rules and camera views in English and stores them; the pages show
    each through a marked display string in the translation file, so a translation never changes a stored name."""
    assert set(VIEW_NAMES) == set(VIEWS)
    recipe = Recipe(board_model=tiny_model.board_model)  # Golden board comparison and the AI check, no ROI
    res = Inspector(recipe, tiny_model.model, tiny_model.reference).inspect(tiny_model.reference)
    assert {c.name for c in res.checks} == set(CHECK_NAMES)
    assert {c.source for c in res.checks} <= set(SOURCES) and {c.rule for c in res.checks} <= set(RULES)
    listed = {source for context, source in _messages(TS_FILE) if context == "ComparePage"}
    assert set(CHECK_NAMES.values()) | set(SOURCES.values()) | set(RULES.values()) | set(MODES) <= listed


def test_req_set_005_a_translation_changes_titles_sections_roles_and_page_strings(
    qtbot: QtBot, ctx: AppContext, tmp_path: Path
) -> None:
    """A .qm built from the generated file translates a page title (context Page), a sidebar section (MainWindow),
    a role name (Role), a page's own string (LogsPage), a Compare mode and a camera view; the English titles stay the
    navigation keys, the mode is still chosen by index and the view combo keeps the English key as its data."""
    wanted = {
        ("Page", "Home"): "홈",
        ("MainWindow", "DATA"): "데이터",
        ("Role", "Admin"): "관리자",
        ("LogsPage", "Filter"): "필터",
        ("ComparePage", "AI score heatmap"): "AI 점수 히트맵",
        ("View", "Top"): "상면",
    }
    tree = ET.parse(TS_FILE)
    for context in tree.getroot().findall("context"):
        for message in context.findall("message"):
            text = wanted.get((context.findtext("name"), message.findtext("source")))
            if text:
                translation = message.find("translation")
                translation.text = text
                translation.attrib.pop("type", None)  # no longer "unfinished"
    tree.write(tmp_path / "test.ts", encoding="utf-8", xml_declaration=True)
    qm = tmp_path / "test.qm"
    subprocess.run([qt_tool("pyside6-lrelease"), "-silent", str(tmp_path / "test.ts"), "-qm", str(qm)], check=True)
    translator = QTranslator()
    assert translator.load(str(qm))
    assert QCoreApplication.installTranslator(translator)
    try:
        win = MainWindow(ctx)  # an empty workspace opens as Admin
        qtbot.addWidget(win)
        texts = [win.nav.item(i).text() for i in range(win.nav.count())]
        assert "홈" in texts and "데이터" in texts and "Home" not in texts and "DATA" not in texts
        assert win.user_label.text() == "admin  ·  관리자"
        assert win.pages["Logs & Export"].findChild(QPushButton, "primary").text() == "필터"
        assert win.navigate("Logs & Export") and win.stack.currentWidget() is win.pages["Logs & Export"]
        mode = win.pages["Compare"].mode
        assert mode.itemText(MODE_AI) == "AI 점수 히트맵" and mode.count() == len(MODES)
        views = win.pages["Inspection"].view_combo
        assert views.itemText(0) == "상면" and views.itemData(0) == "Top" == VIEWS[0]
    finally:
        QCoreApplication.removeTranslator(translator)


def _visible(text: str) -> bool:
    """A literal a person would read: letters remain once markup and entities are gone, and it is not a file name."""
    plain = TAG_OR_ENTITY.sub("", text)
    return any(ch.isalpha() for ch in plain) and not FILE_NAME.fullmatch(plain)


def _literal_text(node: ast.AST) -> str | None:
    """The text of a string literal, of an f-string (its constant parts, 0 for each value) or of `literal.format()`."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.JoinedStr):
        return "".join(v.value if isinstance(v, ast.Constant) else "0" for v in node.values)
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "format":
        return _literal_text(node.func.value)
    return None


def _callee(node: ast.Call) -> tuple[str, str]:
    """(owner, name) of the call: ("QMessageBox", "warning"), ("", "button"), ("self.label", "setText")."""
    f = node.func
    if isinstance(f, ast.Attribute):
        return (f.value.id if isinstance(f.value, ast.Name) else ast.unparse(f.value)), f.attr
    return "", f.id if isinstance(f, ast.Name) else ""


def _is_translated(node: ast.AST) -> bool:
    if isinstance(node, ast.Call):
        _, name = _callee(node)
        return name in TRANSLATORS or (name == "format" and _is_translated(node.func.value))
    return False


def _shows_text(node: ast.Call) -> bool:
    owner, name = _callee(node)
    if name in OWNED_SETTERS.get(owner, ()):
        return True
    return name in TEXT_SETTERS or (owner == "" and name in TEXT_CONSTRUCTORS)


def _unpack(target: ast.AST, name: str) -> list[int] | None:
    """Where a loop target puts `name`: [] for the target itself, [1, 0] for `x` in `for i, (x, y) in …`, else None."""
    if isinstance(target, ast.Name):
        return [] if target.id == name else None
    for i, part in enumerate(target.elts if isinstance(target, (ast.Tuple, ast.List)) else []):
        if (where := _unpack(part, name)) is not None:
            return [i, *where]
    return None


def _joined(node: ast.AST) -> list[ast.AST]:
    """What `sep.join(parts)` shows: its argument, and the separator when it is a literal (#199 review); else []."""
    if not (isinstance(node, ast.Call) and isinstance(f := node.func, ast.Attribute) and f.attr == "join"):
        return []
    sep = [f.value] if _literal_text(f.value) is not None else []
    return [*node.args, *sep] if len(node.args) == 1 and not node.keywords else []


def _scan(path: Path) -> set[tuple[int, str]]:
    """(line, text) of every visible literal passed to something that shows text, outside tr(), also in a branch of a
    conditional, an operand, an `or`, a dict lookup (#199), a `str.join()` or a `+=` (#199 review); page titles too;
    and every literal tr(), translate() or QT_TRANSLATE_NOOP() gets other than as its literal argument (`self.tr(h) for
    h in headers`): pyside6-lupdate extracts a literal argument only, so such a string never reaches the translation
    file and stays English. A name is followed to the loop it runs over, else to its literal in the function, else in
    the module unless the function binds the name itself (#199), and `self.x` to its literal anywhere in the file (#199
    review): tr() lets through only a value no literal reaches, data marked elsewhere."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    parents = {child: node for node in ast.walk(tree) for child in ast.iter_child_nodes(node)}
    scopes = (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda, ast.Module)
    seqs = (ast.List, ast.Tuple, ast.Set)

    def scope_of(node: ast.AST) -> ast.AST:
        while not isinstance(node, scopes):
            node = parents[node]
        return node

    assigned: dict[ast.AST, dict[str, ast.AST]] = {}  # scope -> {name: literal it was assigned}; `self.x` in the module
    bound: dict[ast.AST, set[str]] = {}  # scope -> every name it binds (a parameter, a target)
    augmented: list[ast.AugAssign] = []

    def slot(target: ast.AST) -> tuple[dict[str, ast.AST], str] | None:
        """Where a target's literal is kept: a name in its scope, `self.x` for the whole file (#199 review)."""
        if isinstance(target, ast.Name):
            return assigned.setdefault(scope_of(target), {}), target.id
        if isinstance(target, ast.Attribute) and ast.unparse(target.value) == "self":
            return assigned.setdefault(tree, {}), f"self.{target.attr}"
        return None

    for node in ast.walk(tree):
        if isinstance(node, ast.arg) or (isinstance(node, ast.Name) and isinstance(node.ctx, ast.Store)):
            bound.setdefault(scope_of(node), set()).add(node.arg if isinstance(node, ast.arg) else node.id)
        if isinstance(node, ast.AugAssign):
            augmented.append(node)  # recorded below, once every plain assignment is
        if isinstance(node, ast.Assign) and len(node.targets) == 1:
            target, value = node.targets[0], node.value
        elif isinstance(node, ast.AnnAssign) and node.value is not None:  # `what: str = "…"` counts like `what = "…"`
            target, value = node.target, node.value
        else:
            continue
        literal = isinstance(value, (*seqs, ast.Dict, ast.IfExp, ast.BoolOp, ast.BinOp)) or (
            isinstance(value, ast.Subscript) and isinstance(value.value, ast.Dict)
        )  # check() reads these
        literal = literal or _literal_text(value) is not None or bool(_joined(value))
        if (kept := slot(target)) and literal and not _is_translated(value):
            kept[0][kept[1]] = value
    for node in augmented:  # `x += v` reads like `x = x + v`: the literal x held before, and v (#199 review)
        if kept := slot(node.target):
            table, key = kept
            table[key] = ast.BinOp(table[key], node.op, node.value) if key in table else node.value
    found: set[tuple[int, str]] = set()
    seen: set[ast.AST] = set()  # each node is read once: `x = x + "a"` does not loop

    def values(name: ast.Name) -> list[ast.AST]:
        """What a name holds: the items of the loop or comprehension it runs over (the matching part of each when the
        target unpacks them), else the literal its function, or the module, assigned it; nothing for any other value."""
        node: ast.AST = name
        while not isinstance(node, scopes):
            node = parents[node]
            for loop in getattr(node, "generators", None) or ([node] if isinstance(node, ast.For) else []):
                where = _unpack(loop.target, name.id)
                if where is not None and name not in ast.walk(loop.iter):
                    return items(loop.iter, where)
        here = scope_of(name)
        if name.id in assigned.get(here, {}):
            return [assigned[here][name.id]]
        if name.id not in bound.get(here, set()) and name.id in assigned.get(tree, {}):
            return [assigned[tree][name.id]]
        return []

    def one(node: ast.AST) -> ast.AST:
        held = values(node) if isinstance(node, ast.Name) else []
        return held[0] if len(held) == 1 else node

    def items(iterable: ast.AST, where: list[int]) -> list[ast.AST]:
        """Part `where` of every item of an iterable; for the whole item, the iterable itself (check() reads each)."""
        it = one(iterable)
        if isinstance(it, ast.Call) and _callee(it)[1] == "enumerate" and it.args:  # (index, item)
            return items(it.args[0], where[1:]) if where[:1] == [1] else []
        return [it] if not where else [p for e in (it.elts if isinstance(it, seqs) else []) for p in part(e, where)]

    def part(node: ast.AST, where: list[int]) -> list[ast.AST]:
        node = one(node)
        if where and isinstance(node, seqs) and len(node.elts) > where[0]:
            return part(node.elts[where[0]], where[1:])
        return [] if where else [node]

    def check(arg: ast.AST) -> None:
        if arg in seen:
            return
        seen.add(arg)
        if _is_translated(arg):
            return
        parts: list[ast.AST] = []  # where a literal can hide: each item, branch, operand, dict value or row (#199)
        if isinstance(arg, ast.Name):
            parts = values(arg)
        elif isinstance(arg, ast.Attribute) and ast.unparse(arg.value) == "self":  # self.x set elsewhere (#199 review)
            parts = [assigned[tree][key]] if (key := f"self.{arg.attr}") in assigned.get(tree, {}) else []
        elif isinstance(arg, ast.Starred):
            parts = [arg.value]
        elif isinstance(arg, seqs):
            parts = list(arg.elts)
        elif isinstance(arg, ast.IfExp):
            parts = [arg.body, arg.orelse]
        elif isinstance(arg, ast.BoolOp):
            parts = list(arg.values)
        elif isinstance(arg, ast.BinOp):
            parts = [arg.left, arg.right]
        elif isinstance(arg, ast.Subscript) and isinstance(table := one(arg.value), ast.Dict):
            parts = [v for v in table.values if v is not None]
        elif isinstance(arg, ast.Call) and _callee(arg)[1] == "get" and isinstance(f := arg.func, ast.Attribute):
            table = one(f.value)  # LABELS.get(key, default): every value and the default
            parts = [v for v in table.values if v is not None] if isinstance(table, ast.Dict) else []
            parts += arg.args[1:] if parts else []
        elif joined := _joined(arg):
            parts = joined
        elif isinstance(arg, (ast.ListComp, ast.GeneratorExp)):
            parts = [arg.elt]
        for p in parts:
            check(p)
        text = _literal_text(arg)
        if text is not None and _visible(text):
            found.add((arg.lineno, text))

    def hidden(call: ast.Call) -> ast.AST | None:
        """The text of this tr(), translate() or QT_TRANSLATE_NOOP() call when it is no literal, which pyside6-lupdate
        does not extract: check() then finds any literal behind it (a loop's items, a name, a branch, a dict value)."""
        name = _callee(call)[1]
        pos = 0 if name == "tr" else 1
        if name not in ("tr", "translate", "QT_TRANSLATE_NOOP") or len(call.args) <= pos:
            return None
        text = call.args[pos]
        return None if isinstance(text, ast.Constant) and isinstance(text.value, str) else text

    for node in ast.walk(tree):
        seq = hidden(node) if isinstance(node, ast.Call) else None
        if isinstance(node, ast.Call) and (seq is not None or _shows_text(node)):
            limit = TEXT_POSITIONS.get(_callee(node)[1], len(node.args))
            args = node.args[:limit] + [kw.value for kw in node.keywords if kw.arg not in SKIP_KEYWORDS]
            before = len(found)
            for arg in [seq] if seq is not None else args:
                check(arg)
            if seq is not None and _callee(node)[1] == "QT_TRANSLATE_NOOP" and len(found) == before:
                found.add((seq.lineno, f"QT_TRANSLATE_NOOP({ast.unparse(seq)})"))  # it marks nothing at all (#199)
        if isinstance(node, ast.ClassDef):
            for stmt in node.body:
                targets = [t.id for t in getattr(stmt, "targets", []) if isinstance(t, ast.Name)]
                if isinstance(stmt, ast.AnnAssign) and isinstance(stmt.target, ast.Name):
                    targets = [stmt.target.id]  # `title: str = "…"` counts like `title = "…"`
                if (
                    isinstance(stmt, (ast.Assign, ast.AnnAssign))
                    and stmt.value
                    and set(targets) & {"title", "subtitle"}
                ):
                    check(stmt.value)
    return found


def test_req_set_005_no_untranslated_literals() -> None:
    """An AST scan of aoi/ui and main.py: a string literal (an f-string, `literal.format()`, a name assigned one in
    the same function or the module, or a loop variable over literals count too, #199) passed to a Qt text setter, a
    text widget constructor, a message box, an input or file dialog, a table header, a tooltip, one of this code's own
    helpers (`button`, `make_table`, `fill_table`, `show_state`, `status`) or an AoiError as a value of its message
    (#198) is wrapped in tr(), QT_TRANSLATE_NOOP or a *_text helper, in every branch and operand (#199) and every part
    of a `str.join()` or a `+=` (#199 review), and every page title and subtitle is marked.
    Names the engine or the taxonomy supplies arrive as variables, so they are outside this scan (they stay English
    until a word list exists). ALLOWED_LITERALS lists what may stay a literal, each with its reason."""
    files = [*sorted((ROOT / "aoi" / "ui").rglob("*.py")), ROOT / "main.py"]
    hits = {(path.relative_to(ROOT).as_posix(), line, text) for path in files for line, text in _scan(path)}
    untranslated = sorted(hit for hit in hits if (hit[0], hit[2]) not in ALLOWED_LITERALS)
    assert not untranslated, "\n".join(
        f"{file}:{line}: {text!r} is not wrapped in tr()" for file, line, text in untranslated
    )
    stale = set(ALLOWED_LITERALS) - {(file, text) for file, _, text in hits}
    assert not stale, f"allow-list entries no longer needed: {sorted(stale)}"


ENGINE_ERRORS = {"AoiError", "ModelFileError", "WorkspaceError", "fill"}  # the errors and a phrase's fill (#198)
ENGINE_ALLOWED = {  # (file, literal): why it is not a phrase; a stale entry fails the test
    ("aoi/core/imaging.py", "0 MB"): "a number and a unit symbol, written the same in every language",
    ("aoi/core/imaging.py", "0 MP"): "a number and a unit symbol, written the same in every language",
    ("aoi/core/imaging.py", "0 MP (0 × 0)"): "numbers and a unit symbol, written the same in every language",
    # what a function returns (#198): names the same in every language, and keys a screen words itself
    ("aoi/config.py", "cpu"): "a torch device name",
    ("aoi/core/inspector.py", "RAN"): "an ai_check key the CSV exports write as it is, as pass_fail's (#246)",
    ("aoi/core/inspector.py", "OFF"): "an ai_check key the CSV exports write as it is, as pass_fail's (#246)",
    ("aoi/core/inspector.py", "NO_AI_MODEL"): "an ai_check key the CSV exports write as it is, as pass_fail's (#246)",
    ("aoi/config.py", "cuda"): "a torch device name",
    ("aoi/core/imaging.py", "PNG"): "an image format's name (AOI-INSP-006's {kind}), the same in every language",
    ("aoi/core/imaging.py", "BMP"): "an image format's name (AOI-INSP-006's {kind}), the same in every language",
    ("aoi/core/imaging.py", "JPEG"): "an image format's name (AOI-INSP-006's {kind}), the same in every language",
    ("aoi/core/imaging.py", "TIFF"): "an image format's name (AOI-INSP-006's {kind}), the same in every language",
    ("aoi/core/services.py", "operator"): "a user's name in the users table, which start_user returns",
    ("aoi/core/services.py", "user 0"): "a user's pseudonym in the log (REQ-LOG-004, #195)",
    ("aoi/core/services.py", "same"): "a Judged key Compare never words: it shows the Golden board then",
    ("aoi/core/services.py", "none"): "a Judged key; Compare words it (JUDGED in aoi/ui/pages/compare.py)",
    ("aoi/core/services.py", "unrecorded"): "a Judged key; Compare words it (JUDGED in aoi/ui/pages/compare.py)",
    ("aoi/core/services.py", "missing"): "a Judged key; Compare words it (JUDGED in aoi/ui/pages/compare.py)",
    ("aoi/core/services.py", "unreadable"): "a Judged key; Compare words it (JUDGED in aoi/ui/pages/compare.py)",
    ("aoi/core/services.py", "changed"): "a Judged key; Compare words it (JUDGED in aoi/ui/pages/compare.py)",
    ("aoi/core/datasets.py", "DS-0-0-0-v0"): "a dataset version's name (REQ-TRN-005), the same in every language",
}


def _engine_literals(path: Path) -> set[tuple[int, str]]:
    """(line, text) of every literal the engine fills an error's message with: a value of AoiError or a subclass, or
    of a phrase's fill(), that is a string literal, an f-string, `literal.format()`, a name assigned one in the same
    file (with or without an annotation), or one of them inside `a or b` or `a if c else b`; an error's detail goes to
    the log and is let through. A function's return value counts too, alone or in a tuple, since a helper's reason
    reaches an error through a call this scan does not follow (`reason=_unusable(...)` in anomaly.py, #198)."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    parents = {child: node for node in ast.walk(tree) for child in ast.iter_child_nodes(node)}

    def scope(node: ast.AST) -> ast.AST:  # a class body too: its names are not the module's, nor its methods'
        while not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda, ast.ClassDef, ast.Module)):
            node = parents[node]
        return node

    assigned: dict[tuple[ast.AST, str], list[ast.AST]] = {}  # (scope, name) -> the literals it is given
    for node in ast.walk(tree):
        if isinstance(node, (ast.Assign, ast.AnnAssign)) and node.value and _literal_text(node.value) is not None:
            for t in node.targets if isinstance(node, ast.Assign) else [node.target]:
                if isinstance(t, ast.Name):
                    assigned.setdefault((scope(node), t.id), []).append(node.value)
    found: set[tuple[int, str]] = set()

    def check(arg: ast.AST, where: ast.AST) -> None:
        if isinstance(arg, ast.BoolOp):
            for value in arg.values:
                check(value, where)
        elif isinstance(arg, ast.IfExp):
            check(arg.body, where)
            check(arg.orelse, where)
        elif isinstance(arg, ast.Tuple):
            for value in arg.elts:
                check(value, where)
        elif isinstance(arg, ast.Name):
            for value in assigned.get((where, arg.id), assigned.get((tree, arg.id), [])):
                check(value, where)
        elif (text := _literal_text(arg)) is not None and _visible(text):
            found.add((arg.lineno, text))

    for node in ast.walk(tree):
        if isinstance(node, ast.Return) and node.value is not None:
            check(node.value, scope(node))
        if isinstance(node, ast.Call) and _callee(node)[1] in ENGINE_ERRORS:
            for kw in node.keywords:
                if kw.arg not in SKIP_KEYWORDS:
                    check(kw.value, scope(node))
        if isinstance(node, ast.Call) and _callee(node)[1] == "QT_TRANSLATE_NOOP" and len(node.args) > 1:
            text = node.args[1]  # pyside6-lupdate extracts a literal only, so any other text is never translated (#199)
            if not (isinstance(text, ast.Constant) and isinstance(text.value, str)):
                found.add((text.lineno, f"QT_TRANSLATE_NOOP({ast.unparse(text)})"))
    return found


def test_req_set_005_the_engine_fills_errors_with_phrases_only(tmp_path: Path) -> None:
    """Outside aoi/ui (which the scan above covers), an error's message is filled with phrases and data, never with an
    English literal a screen could not translate, and no function returns one (#198), and every QT_TRANSLATE_NOOP marks
    a literal (#199): the sample shows what the scan flags and lets through. ENGINE_ALLOWED lists what may stay a
    literal, each with its reason."""
    files = sorted(p for p in (ROOT / "aoi").rglob("*.py") if "ui" not in p.relative_to(ROOT / "aoi").parts[:1])
    hits = {(p.relative_to(ROOT).as_posix(), line, text) for p in files for line, text in _engine_literals(p)}
    untranslated = sorted(f"{file}:{line}: {text!r}" for file, line, text in hits if (file, text) not in ENGINE_ALLOWED)
    assert not untranslated, 'fill these through QT_TRANSLATE_NOOP("Errors", …):\n' + "\n".join(untranslated)
    stale = set(ENGINE_ALLOWED) - {(file, text) for file, _, text in hits}
    assert not stale, f"allow-list entries no longer needed: {sorted(stale)}"
    sample = tmp_path / "sample.py"
    sample.write_text(
        'WHY = "a reason"\n'
        'raise AoiError("AOI-SET-008", detail="log only", name=name, expected="a number")\n'
        "def f(p):\n"
        '    why = QT_TRANSLATE_NOOP("Errors", "a phrase")\n'
        "    raise ModelFileError('AOI-TRN-001', path=p, reason=why)\n"
        "def g(p):\n"
        '    why = "bad"\n'
        "    raise ModelFileError('AOI-TRN-001', path=p, reason=WHY if p else why)\n"
        'raise AoiError("AOI-SET-010", path=p, reason=e.strerror or f"{kind} failed")\n'
        'raise AoiError("AOI-TRN-004", reason=QT_TRANSLATE_NOOP("Errors", "{n} bad").fill(n=n or "none"))\n'
        'raise AoiError("AOI-INSP-005", path="board.png", size=size if size else "huge")\n'
        "def _unusable(meta):\n"  # a helper whose return an error takes as its reason, as anomaly._unusable (#198)
        "    if meta:\n"
        '        return QT_TRANSLATE_NOOP("Errors", "a marked reason")\n'
        '    return "its weights hold numbers that are not finite"\n'
        "def h(p):\n"
        '    why: str = "noted"\n'
        '    return (None, why or "") if p else f"{p:.1f}"\n'
        "class C:\n"
        '    kind: str = "a field default"\n'
        "def k(kind):\n"
        "    return kind\n"
        'RULES = [QT_TRANSLATE_NOOP("Training", r) for r in ("first", "second")]\n',
        encoding="utf-8",
    )
    returned = {"its weights hold numbers that are not finite", "noted"}  # what a function returns (#198)
    found = {text for _, text in _engine_literals(sample)}
    assert found == {"a number", "a reason", "bad", "0 failed", "none", "huge", "QT_TRANSLATE_NOOP(r)", *returned}


def test_req_set_005_the_scan_catches_a_literal(tmp_path: Path) -> None:
    """The scan itself: it flags a literal, an f-string, a `.format()` on a literal, a name assigned a literal (with or
    without an annotation), a title (annotated or not), a dialog's words and a value an AoiError fills its message with
    (#198), a literal in a conditional, a concatenation, an `or`, a dict lookup or a fill_table row (#199), a part or
    the separator of a `str.join()` (a starred part and a `self.` attribute shown later too) and a literal added with
    `+=` (#199 review), and lets through tr(), markup-only text, a file name, a logger's warning and an AoiError's
    detail."""
    sample = tmp_path / "sample.py"
    sample.write_text(
        "class P(Page):\n"
        '    title = "Untitled page"\n'
        '    subtitle: str = "Annotated subtitle"\n'
        "    def f(self):\n"
        '        what = "Assigned text"\n'
        '        hint: str = "Annotated text"\n'
        '        self.label.setText("Plain text")\n'
        '        self.label.setText(f"{self.n} items")\n'
        '        self.label.setText("{count} rows".format(count=3))\n'
        '        self.empty.show_state(self.tr("Heading"), what)\n'
        "        self.label.setToolTip(hint)\n"
        '        QMessageBox.warning(self, "Title", "Body")\n'
        '        self.log.warning("settings.save_failed")\n'
        '        self.label.setText(f"<b>{self.n}</b>")\n'
        '        self.label.setText(self.tr("Fine {n}").format(n=1))\n'
        '        QFileDialog.getSaveFileName(self, self.tr("Save"), "board_0.png", self.tr("PNG (*.png)"))\n'
        '        bar.addWidget(button(self.tr("Go"), "primary"))\n'
        '        self.action(self.tr("Go"), "F5", self.go)\n'  # the key is not text
        '        self.action("Run", "F6", self.go)\n'
        '        raise AoiError("AOI-USR-001", detail="log", what="Changing recipes", roles=ROLES_FROM[role])\n'
        '        raise AoiError("AOI-RCP-002", quantity=QT_TRANSLATE_NOOP("Errors", "Height"), low=f"{low:g}")\n'
        '        self.a.setText("Ready" if ok else self.tr("Not ready"))\n'  # #199: a branch, an operand, a dict value
        '        self.b.setText(self.tr("Board") + " failed")\n'
        '        self.c.setText({"OK": "Passed"}[ok])\n'
        '        fill_table(self.t, [["Yes", 1]])\n'  # a row's cells; a number is no text
        '        state = self.name or "Unnamed"\n'
        "        self.d.setText(state)\n"
        '        self.e.setText(self.tr("Fine") if ok else self.tr("Also fine") + " · ")\n'
        '        self.f.setText(" and ".join(["Joined part", self.tr("Fine")]))\n'  # #199 review: a join's parts
        '        joined = "\\n".join([self.tr("Fine"), *("Starred part" for _ in rows)])\n'
        '        self.empty.show_state(self.tr("Heading"), joined)\n'
        '        self.pair = self.tr("Fine"), " ".join([self.n, "Kept part"])\n'  # an attribute shown later
        "        self.empty.show_state(*self.pair)\n"
        '        text = self.tr("Fine")\n'  # #199 review: `+=` reads like `text = text + …`
        '        text += "  ·  Appended part"\n'
        "        if ok:\n"
        '            text += self.tr("Also fine")\n'
        "        self.g.setText(text)\n"
        '        note = "Prior part"\n'
        '        note += self.tr("Fine")\n'
        "        self.h.setText(note)\n",
        encoding="utf-8",
    )
    assert {text for _, text in _scan(sample)} == {
        "Untitled page",
        "Annotated subtitle",
        "Plain text",
        "0 items",
        "{count} rows",
        "Assigned text",
        "Annotated text",
        "Title",
        "Body",
        "Run",
        "Changing recipes",
        "Ready",
        " failed",
        "Passed",
        "Yes",
        "Unnamed",
        " and ",
        "Joined part",
        "Starred part",
        "Kept part",
        "  ·  Appended part",
        "Prior part",
    }


def test_req_set_005_the_scan_catches_a_literal_reaching_tr_through_a_loop(tmp_path: Path) -> None:
    """pyside6-lupdate extracts tr()'s text only when it is a literal, so `self.tr(h) for h in headers` over literals
    leaves them out of the translation file and on screen in English: the Recipe Editor's ROI table headers (#173).
    The scan flags such literals, in a comprehension or a for loop, inline or through a name, and lets marked ones
    through; the ROI table's headers are now in the file under the Recipe Editor's context. QT_TRANSLATE_NOOP over a
    loop variable (Settings' "Stage 1" to "Stage 4", #199) or any other text that is not a literal is flagged, and so
    is tr() of a name assigned a literal or of a conditional of literals. A name is followed to the module too, and a
    loop variable to its loop's items, unpacked or enumerated: an unmarked module-level name, row, header tuple or dict
    value reaching tr() is flagged (#199 review); tr() of a value no literal reaches (a parameter) is not."""
    sample = tmp_path / "sample.py"
    sample.write_text(
        '_S9 = "Stage 9"\n'  # #199 review: an unmarked module-level name, row or header tuple reaching tr()
        'HW = [(QT_TRANSLATE_NOOP("P", "Camera"), _S9), ("Lamp", QT_TRANSLATE_NOOP("P", "Ready"))]\n'
        'HEADERS = ("Width", "Depth")\n'
        'LABELS = {"a": "Alpha", "b": QT_TRANSLATE_NOOP("P", "Beta")}\n'
        'PAIRS = [("en", "Gamma"), ("ko", QT_TRANSLATE_NOOP("P", "Fine"))]\n'
        "def g(self, k):\n"
        "    fill_table(self.hw, [[self.tr(c) for c in row] for row in HW])\n"
        "    self.t = make_table([self.tr(h) for h in HEADERS])\n"
        "    self.l.setText(self.tr(LABELS[k]))\n"
        '    self.l.setText(self.tr(LABELS.get(k, "Delta")))\n'
        "    for i, (code, name) in enumerate(PAIRS):\n"
        "        self.combo.addItem(self.tr(name), code)\n"  # the item's data is no text
        "def h(self, HEADERS):\n"
        "    self.t = make_table([self.tr(h) for h in HEADERS])\n"  # a parameter, not the module's tuple
        "def f(self):\n"
        '    headers = ["Kind", "Size"]\n'
        '    self.table = make_table([*(self.tr(h) for h in headers), self.tr("Score")])\n'
        '    for side in ("Left", "Right"):\n'
        "        self.combo.addItem(self.tr(side))\n"
        '    marked = [QT_TRANSLATE_NOOP("P", "Fine")]\n'
        "    self.combo.addItems([self.tr(m) for m in marked])\n"
        '    _S1, _S2 = (QT_TRANSLATE_NOOP("P", s) for s in ("Stage 1", "Stage 2"))\n'  # settings.py before #199
        '    why = "Busy"\n'
        "    self.label.setText(self.tr(why))\n"
        '    self.label.setText(self.tr("On" if on else "Off"))\n'
        '    NAME = QT_TRANSLATE_NOOP("P", name)\n'
        "    self.table.setItem(0, 0, QTableWidgetItem(self.tr(cell)))\n",  # a value passed through, marked elsewhere
        encoding="utf-8",
    )
    found = {text for _, text in _scan(sample)}
    assert found == {
        "Kind",
        "Size",
        "Left",
        "Right",
        "Stage 1",
        "Stage 2",
        "Busy",
        "On",
        "Off",
        "QT_TRANSLATE_NOOP(name)",
        "Stage 9",
        "Lamp",
        "Width",
        "Depth",
        "Alpha",
        "Delta",
        "Gamma",
    }
    headers = ("Name", "Type", "X", "Y", "W", "H", "AI score")
    assert {("RecipeEditorPage", h) for h in headers} <= set(_messages(TS_FILE))
