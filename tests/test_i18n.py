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
    "show_state", "status", "action",
}  # fmt: skip
OWNED_SETTERS = {  # static methods that show text when called on these classes (QMessageBox.warning, not log.warning)
    "QMessageBox": {"information", "warning", "critical", "question", "about"},
    "QInputDialog": {"getItem", "getText", "getInt", "getDouble", "getMultiLineText"},
    "QFileDialog": {"getOpenFileName", "getOpenFileNames", "getSaveFileName", "getExistingDirectory"},
}
TEXT_CONSTRUCTORS = {
    "QLabel", "QPushButton", "QCheckBox", "QRadioButton", "QGroupBox", "QAction", "QMenu", "QListWidgetItem",
    "QTableWidgetItem", "QMessageBox", "button", "make_table", "BusyOverlay", "ImageView", "MetricTile", "EmptyState",
}  # fmt: skip
TEXT_POSITIONS = {"button": 1, "action": 1}  # button(text, kind, slot), action(text, key, slot): text first
SKIP_KEYWORDS = {"kind", "slot", "parent", "over"}
ALLOWED_LITERALS = {  # (file, literal): why it is not translated; a stale entry fails the test
    ("aoi/ui/pages/base.py", "Page"): "placeholder title of the base class; every page overrides it",
    ("aoi/ui/pages/settings.py", "auto"): "a torch device name, shown as the value the engine takes",
    ("aoi/ui/pages/settings.py", "cpu"): "a torch device name",
    ("aoi/ui/pages/settings.py", "cuda"): "a torch device name",
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


def _scan(path: Path) -> set[tuple[int, str]]:
    """(line, text) of every visible literal passed to something that shows text, outside tr(); page titles too; and
    every literal tr() gets only through a loop variable (`self.tr(h) for h in headers`): pyside6-lupdate extracts a
    literal argument only, so such a string never reaches the translation file and stays English on screen."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    parents = {child: node for node in ast.walk(tree) for child in ast.iter_child_nodes(node)}
    scopes = (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda, ast.Module)
    assigned: dict[ast.AST, dict[str, ast.AST]] = {}  # scope -> {name: literal it was assigned}
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and len(node.targets) == 1:
            target, value = node.targets[0], node.value
        elif isinstance(node, ast.AnnAssign) and node.value is not None:  # `what: str = "…"` counts like `what = "…"`
            target, value = node.target, node.value
        else:
            continue
        literal = isinstance(value, (ast.List, ast.Tuple)) or _literal_text(value) is not None  # check() reads a list
        if isinstance(target, ast.Name) and literal and not _is_translated(value):
            scope = node
            while not isinstance(scope, scopes):
                scope = parents[scope]
            assigned.setdefault(scope, {})[target.id] = value
    found: set[tuple[int, str]] = set()

    def check(arg: ast.AST, scope: ast.AST) -> None:
        if isinstance(arg, ast.Name) and arg.id in assigned.get(scope, {}):
            arg = assigned[scope][arg.id]
        if _is_translated(arg):
            return
        if isinstance(arg, (ast.List, ast.Tuple)):
            for elt in arg.elts:
                check(elt, scope)
            return
        text = _literal_text(arg)
        if text is not None and _visible(text):
            found.add((arg.lineno, text))

    def looped(call: ast.Call) -> ast.AST | None:
        """What the loop or comprehension runs over whose variable is the text of this tr() or translate() call."""
        pos = 1 if _callee(call)[1] == "translate" else 0
        if _callee(call)[1] not in ("tr", "translate") or len(call.args) <= pos:
            return None
        node, name = call, call.args[pos].id if isinstance(call.args[pos], ast.Name) else None
        while name and node in parents:
            node = parents[node]
            for loop in getattr(node, "generators", None) or ([node] if isinstance(node, ast.For) else []):
                if isinstance(loop.target, ast.Name) and loop.target.id == name:
                    return loop.iter
        return None

    for node in ast.walk(tree):
        seq = looped(node) if isinstance(node, ast.Call) else None
        if isinstance(node, ast.Call) and (seq is not None or _shows_text(node)):
            scope = node
            while not isinstance(scope, scopes):
                scope = parents[scope]
            limit = TEXT_POSITIONS.get(_callee(node)[1], len(node.args))
            args = node.args[:limit] + [kw.value for kw in node.keywords if kw.arg not in SKIP_KEYWORDS]
            for arg in [seq] if seq is not None else args:
                check(arg, scope)
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
                    check(stmt.value, tree)
    return found


def test_req_set_005_no_untranslated_literals() -> None:
    """An AST scan of aoi/ui and main.py: a string literal (an f-string, `literal.format()` or a name assigned one in
    the same function count too) passed to a Qt text setter, a text widget constructor, a message box, an input or
    file dialog, a table header, a tooltip or one of this code's own helpers (`button`, `make_table`, `show_state`,
    `status`) is wrapped in tr(), QT_TRANSLATE_NOOP or a *_text helper, and every page title and subtitle is marked.
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


def test_req_set_005_the_scan_catches_a_literal(tmp_path: Path) -> None:
    """The scan itself: it flags a literal, an f-string, a `.format()` on a literal, a name assigned a literal (with or
    without an annotation), a title (annotated or not) and a dialog's words, and lets through tr(), markup-only text, a
    file name and a logger's warning."""
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
        '        self.action("Run", "F6", self.go)\n',
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
    }


def test_req_set_005_the_scan_catches_a_literal_reaching_tr_through_a_loop(tmp_path: Path) -> None:
    """pyside6-lupdate extracts tr()'s text only when it is a literal, so `self.tr(h) for h in headers` over literals
    leaves them out of the translation file and on screen in English: the Recipe Editor's ROI table headers (#173).
    The scan flags such literals, in a comprehension or a for loop, inline or through a name, and lets marked ones
    through; the ROI table's headers are now in the file under the Recipe Editor's context."""
    sample = tmp_path / "sample.py"
    sample.write_text(
        "def f(self):\n"
        '    headers = ["Kind", "Size"]\n'
        '    self.table = make_table([*(self.tr(h) for h in headers), self.tr("Score")])\n'
        '    for side in ("Left", "Right"):\n'
        "        self.combo.addItem(self.tr(side))\n"
        '    marked = [QT_TRANSLATE_NOOP("P", "Fine")]\n'
        "    self.combo.addItems([self.tr(m) for m in marked])\n",
        encoding="utf-8",
    )
    assert {text for _, text in _scan(sample)} == {"Kind", "Size", "Left", "Right"}
    headers = ("Name", "Type", "X", "Y", "W", "H", "AI score")
    assert {("RecipeEditorPage", h) for h in headers} <= set(_messages(TS_FILE))
