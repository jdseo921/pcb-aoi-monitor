"""Screen rules of the Engineering standard, "Look", "Sizes" and "Empty state" (REQ-SET-004, REQ-SET-018, REQ-INSP-002,
REQ-SET-019, REQ-P3D-001; S18a, S18b, S18c).

Static scans keep every colour and point size in aoi/ui/theme.py. Widget checks open the shell offscreen and look at
the one frame every page sits in, the one blue primary button per page, the red destructive buttons, the verdict
banner with its shape and word, and the empty state of every page, list and image area with its next step.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

from PySide6.QtCore import QMetaObject, Qt, Signal, SignalInstance
from PySide6.QtWidgets import QApplication, QBoxLayout, QFrame, QPushButton, QTableWidget, QWidget
from pytestqt.qtbot import QtBot

from aoi.core.services import AppContext
from aoi.ui import theme
from aoi.ui.main_window import MainWindow
from aoi.ui.pages.compare import MODE_DIFF
from aoi.ui.widgets.empty_state import EmptyState
from tests.test_req_done_in_v01 import BOARD, _inspect_one, _window

ROOT = Path(__file__).resolve().parents[1]
UI_DIR = ROOT / "aoi" / "ui"
THEME = UI_DIR / "theme.py"
COLOUR_LITERAL = re.compile(r"#[0-9a-fA-F]{3,8}\b|\brgba?\(")
POINT_SIZE = re.compile(r"font-size:\s*(\d+)\s*pt")
QT_COLOURS = {"white", "black", "red", "green", "blue", "yellow", "gray", "darkGray", "lightGray", "cyan", "magenta"}
COLOUR_CALLS = {"QColor", "QBrush", "QPen"}
DESTRUCTIVE = re.compile(r"^(Delete|Remove|Reset Demo|Clear)\b")  # Reset Filters only changes a view
QT_OVERRIDES = re.compile(r"Event$|^event$|^eventFilter$|[sS]izeHint$|^paintEngine$")  # Qt virtuals defined on purpose
QT_INSTALLED = (Signal, SignalInstance, QMetaObject)


def _docstrings(tree: ast.AST) -> set[ast.AST]:
    out: set[ast.AST] = set()
    for node in ast.walk(tree):
        body = getattr(node, "body", None)
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef)) and body and isinstance(body[0], ast.Expr):
            out.add(body[0].value)
    return out


def test_req_set_004_no_colour_literals_outside_theme() -> None:
    """Pages and widgets take colours from the theme tokens: no hex or rgb() string, Qt colour name or QColor("…")."""
    found: list[str] = []
    for path in sorted(UI_DIR.rglob("*.py")):
        if path == THEME:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        docstrings = _docstrings(tree)
        for node in ast.walk(tree):
            where = f"{path.relative_to(ROOT)}:{getattr(node, 'lineno', 0)}"
            if isinstance(node, ast.Constant) and isinstance(node.value, str) and node not in docstrings:
                if COLOUR_LITERAL.search(node.value):
                    found.append(f"{where} {node.value!r}")
            elif isinstance(node, ast.Attribute) and node.attr in QT_COLOURS:
                if isinstance(node.value, ast.Name) and node.value.id == "Qt":
                    found.append(f"{where} Qt.{node.attr}")
            elif isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in COLOUR_CALLS:
                if node.args and isinstance(node.args[0], ast.Constant):
                    found.append(f"{where} {node.func.id}({node.args[0].value!r})")
    assert not found, "colour literals outside aoi/ui/theme.py: " + ", ".join(found)


def test_req_set_004_text_is_14pt_or_more_and_the_verdict_40pt() -> None:
    """Every point size written anywhere under aoi/ui, in the built stylesheet and in the tokens is 14 pt or more."""
    sources = [p.read_text(encoding="utf-8") for p in UI_DIR.rglob("*.py")]
    styles = [theme.QSS, theme.verdict_style("NG"), theme.verdict_style("OK", big=False)]
    sizes = [int(m) for text in sources + styles for m in POINT_SIZE.findall(text)]
    tokens = {k: v for k, v in vars(theme).items() if k.startswith("FONT_") and k.endswith("_PT")}
    assert sizes and min(sizes) >= theme.FONT_PT >= 14, sorted(set(sizes))
    assert min(tokens.values()) >= 14, tokens
    assert theme.FONT_VERDICT_PT == 40 and "font-size:40pt" in theme.verdict_style("NG")
    assert f"font-size: {theme.FONT_PT}pt" in theme.QSS and "12pt" not in theme.QSS
    assert theme.BUTTON_W >= 120 and theme.BUTTON_H >= 40 and theme.TARGET_H >= 48 and theme.FIELD_H >= 40
    assert f"min-width: {theme.BUTTON_W}px; min-height: {theme.BUTTON_H}px" in theme.QSS


def test_req_set_018_frame_header_and_sidebar_groups(qtbot: QtBot, trained_ctx: AppContext) -> None:
    """Every page sits in the one frame: header with board model, user and role; the four sidebar groups; status bar."""
    win = _window(qtbot, trained_ctx, "Admin")
    header = win.findChild(QFrame, "header")
    assert header is not None and header.height() == theme.HEADER_H
    assert win.bm_combo.currentText() == BOARD and win.user_label.text() == "admin  ·  Admin"
    items = [win.nav.item(i) for i in range(win.nav.count())]
    assert [it.text() for it in items if not it.data(Qt.UserRole)] == ["PRODUCTION", "ENGINEERING", "DATA", "SYSTEM"]
    for it in items:
        if it.data(Qt.UserRole):
            assert win.nav.visualItemRect(it).height() >= theme.TARGET_H, f"{it.text()}: not an operator target"
    assert win.nav.width() == theme.NAV_W
    for title in win.pages:
        win.navigate(title)
        assert header.isVisible() and win.nav.isVisible() and win.statusBar().isVisible(), title


def test_req_insp_002_verdict_has_shape_and_word(qtbot: QtBot, trained_ctx: AppContext, ng_board: Path) -> None:
    """A verdict is its colour with a shape and the word: Inspection (40 pt), Compare, the AI Model Test preview."""
    assert [theme.verdict_label(v) for v in ("OK", "NG", "WARN")] == ["✓ OK", "✗ NG", "▲ WARN"]
    assert len(set(theme.VERDICT_SHAPES.values())) == len(theme.VERDICT_SHAPES), "each verdict has its own shape"
    win = _window(qtbot, trained_ctx, "Engineer")
    page = _inspect_one(qtbot, win, ng_board)
    res = page.last
    assert page.verdict.text() == theme.verdict_label(res.verdict) == "✗ NG"
    assert theme.NG_COLOR in page.verdict.styleSheet() and "font-size:40pt" in page.verdict.styleSheet()
    assert page.verdict.height() >= theme.BANNER_H
    compare = win.pages["Compare"]
    win.open_compare(str(ng_board))
    qtbot.waitUntil(lambda: compare.res is not None, timeout=30000)
    assert compare.verdict.text() == theme.verdict_label(compare.res.verdict) == "✗ NG"
    assert theme.NG_COLOR in compare.verdict.styleSheet()
    before = compare.test_view._pix
    compare.mode.setCurrentIndex(MODE_DIFF)  # the "Show:" switch redraws (#5: it bound QWidget.render until S22a)
    assert compare.test_view._pix is not before, "the mode switch did not redraw the test view"
    test_page = win.pages["AI Model Test"]
    test_page.run_board_model = win.board_model  # a run's row, previewed under the board model of that run (#180)
    test_page._show_preview(str(ng_board), res, test_page.run_board_model)
    assert test_page.preview_verdict.text() == "✗ NG" and theme.NG_COLOR in test_page.preview_verdict.styleSheet()


def test_req_set_018_one_primary_button(qtbot: QtBot, trained_ctx: AppContext) -> None:
    """Exactly one blue primary button per page, the action the page is for; none of them is checkable."""
    win = _window(qtbot, trained_ctx, "Admin")
    for title, page in win.pages.items():
        primaries = [b for b in page.findChildren(QPushButton) if b.objectName() == "primary"]
        assert len(primaries) == 1, (title, [b.text() for b in primaries])
        assert not any(b.isCheckable() for b in primaries), title
    assert f"QPushButton#primary {{ background: {theme.ACCENT};" in theme.QSS


def _row_of(page: QWidget, b: QPushButton) -> list[QWidget]:
    """The widgets of the box layout that holds `b`, in order."""
    for lay in page.findChildren(QBoxLayout):
        if lay.indexOf(b) >= 0:
            return [w for w in (lay.itemAt(i).widget() for i in range(lay.count())) if w is not None]
    raise AssertionError(f"{b.text()} is not in a box layout")


def test_req_set_018_destructive_buttons_red_not_default(qtbot: QtBot, trained_ctx: AppContext) -> None:
    """Delete and Remove are red "danger" buttons, last in their row, never the default and never focused on open."""
    assert re.search(r"QPushButton#danger \{ background: " + theme.NG_COLOR, theme.QSS)
    win = _window(qtbot, trained_ctx, "Admin")
    red: list[str] = []
    for title, page in win.pages.items():
        win.navigate(title)
        QApplication.processEvents()
        for b in page.findChildren(QPushButton):
            if DESTRUCTIVE.match(b.text()):
                assert b.objectName() == "danger", f"{title}: '{b.text()}' removes data and must be a red danger button"
            if b.objectName() in ("danger", "stop"):
                red.append(f"{title}: {b.text()}")
                assert not b.isDefault() and not b.autoDefault(), red[-1]
                assert QApplication.focusWidget() is not b, f"{red[-1]} has the focus when the page opens"
            if b.objectName() == "danger":
                assert _row_of(page, b)[-1] is b, f"{red[-1]} is not the last button in its row"
    assert {"Training: Remove", "Recipe Editor: Delete", "Inspection: ■  Stop  F6"} <= set(red), red


def _empties(page: QWidget) -> list[EmptyState]:
    return [e for e in page.findChildren(EmptyState) if e.isVisibleTo(page)]


def test_req_set_019_empty_states_link_next_step(
    qtbot: QtBot, ctx: AppContext, trained_ctx: AppContext, ng_board: Path
) -> None:
    """Every empty page, list and image area says what is missing, what to do and links there; a role that cannot
    open the linked page is told to ask an Engineer; a filtered-out history offers Reset Filters."""
    win = MainWindow(ctx)  # an empty workspace, opened as Admin
    qtbot.addWidget(win)
    win.resize(1600, 900)
    win.show()
    qtbot.waitExposed(win)
    seen: dict[str, EmptyState] = {}
    for title in (
        "Home",
        "Inspection",
        "Compare",
        "Training",
        "AI Model Test",
        "Recipe Editor",
        "3D Profile",
        "Logs & Export",
    ):
        win.navigate(title)
        empties = _empties(win.pages[title])
        assert empties, f"{title}: nothing says what to do in an empty workspace"
        for e in empties:
            assert e.heading.text() and e.sentence.text().endswith("."), (title, e.heading.text(), e.sentence.text())
        seen[title] = empties[0]
    assert seen["Home"].link.isVisibleTo(win.pages["Home"]) and seen["Home"].link.text() == "+ New board model"
    assert seen["3D Profile"].link.objectName() == "primary"
    seen["3D Profile"].link.click()
    assert win.stack.currentWidget() is win.pages["Recipe Editor"]
    assert (
        seen["Logs & Export"].heading.text() == "No inspections yet"
        and seen["Logs & Export"].link.text() == "Open Inspection ›"
    )
    seen["Logs & Export"].link.click()
    assert win.stack.currentWidget() is win.pages["Inspection"]
    # An Operator is told to ask an Engineer, with no link, when the next step is on a page that is not theirs.
    win.set_user("operator")
    win.navigate("Home")
    assert seen["Home"].sentence.text() == "Ask an Engineer to create one." and not seen["Home"].link.isVisibleTo(
        win.pages["Home"]
    )
    win.set_user("admin")  # creating a board model is Engineer or Admin work (REQ-USR-001)
    ctx.ensure_board_model("TBOX-X")
    win._reload_board_models("TBOX-X")
    win.set_user("operator")
    win.navigate("Compare")
    compare = win.pages["Compare"]
    compare.on_board_model_changed("TBOX-X")  # evaluate again as the Operator; the newest run wins
    ask = "Ask an Engineer to do this on Training."
    qtbot.waitUntil(lambda: compare.ref_empty.sentence.text() == ask, timeout=30000)
    assert compare.ref_empty.isVisibleTo(compare)
    assert compare.ref_empty.heading.text() == "No Golden board for TBOX-X yet"
    assert not compare.ref_empty.link.isVisibleTo(compare)
    # A history with records but a filter that matches none offers Reset Filters, which brings the rows back.
    win2 = _window(qtbot, trained_ctx, "Engineer")
    _inspect_one(qtbot, win2, ng_board)
    logs = win2.pages["Logs & Export"]
    win2.navigate("Logs & Export")
    assert logs.table.rowCount() == 1 and not _empties(logs)
    logs.d_to.setDate(logs.d_from.date().addDays(-1))
    logs.refresh()
    assert logs.table.rowCount() == 0 and logs.empty.heading.text() == "No records match"
    logs.empty.link.click()
    assert logs.table.rowCount() == 1 and not _empties(logs)


def test_req_set_019_empty_state_shows_every_line_in_a_narrow_area(qtbot: QtBot) -> None:
    """In an area narrower than its text would like (Compare's two panes side by side), the empty state wraps its text
    to the area and shows every line, at every width as the area narrows to 120 px and widens again, also when a word
    is wider than the area (a long golden board file name runs past the edge): each label is as tall as its text at
    its width and inside the area, and so is the link wherever the area has room for it. In an area too short for
    every line, the sentence gives way: the heading and the link still show whole."""
    host = QWidget()
    qtbot.addWidget(host)
    host.resize(400, 800)
    empty = EmptyState(host)
    sentence = (
        "The Golden board this result was judged against{name} has changed since; press Re-evaluate to inspect the"
        " board again with today's Golden board."
    )
    host.show()
    qtbot.waitExposed(host)
    layout = empty.layout()
    assert layout is not None
    margins = layout.contentsMargins()
    for name in ("", ", MAINBOARD_REV_C_TOP_v1.0_golden.png,"):
        empty.show_state("Golden board not available", sentence.format(name=name), "Re-evaluate ›", lambda: None)
        for width in [*range(400, 119, -3), *range(120, 401, 3)]:
            host.resize(width, 800)
            QApplication.sendPostedEvents()  # every layout request the resize set off
            for label in (empty.heading, empty.sentence):
                assert label.height() >= label.heightForWidth(label.width()), (width, label.text())
                assert host.rect().contains(label.geometry()), (width, label.text())
            if width >= empty.link.width() + margins.left() + margins.right():
                assert host.rect().contains(empty.link.geometry()), width
    host.resize(400, 160)
    QApplication.sendPostedEvents()
    assert empty.heading.height() >= empty.heading.heightForWidth(empty.heading.width())
    assert host.rect().contains(empty.heading.geometry()) and host.rect().contains(empty.link.geometry())


def test_req_p3d_001_profile_page_is_a_stage_2_card(qtbot: QtBot, trained_ctx: AppContext) -> None:
    """Until 3D data exists the 3D Profile page is one card that says so and leads to the Recipe Editor, where the
    height and volume limits already live; nothing on it looks like a working 3D control (sketch profile3d-card.md)."""
    win = _window(qtbot, trained_ctx, "Engineer")
    win.navigate("3D Profile")
    page = win.pages["3D Profile"]
    assert page.card.isVisibleTo(page) and "Stage 2" in page.card.heading.text()
    QApplication.sendPostedEvents()
    for label in (page.card.heading, page.card.sentence):  # the card is as tall as its text at the card's width
        assert label.height() >= label.heightForWidth(label.width()), label.text()
    assert not page.findChildren(QTableWidget), "no empty height table"
    buttons = [b for b in page.findChildren(QPushButton) if b.isVisibleTo(page)]
    assert sorted(b.text() for b in buttons) == ["Back to Home", "Open Recipe Editor ›"]
    assert all(b.isEnabled() for b in buttons)
    page.card.link.click()
    assert win.stack.currentWidget() is win.pages["Recipe Editor"]
    win.navigate("3D Profile")
    next(b for b in buttons if b.text() == "Back to Home").click()
    assert win.stack.currentWidget() is win.pages["Home"]


def test_issue_5_no_page_attribute_shadows_a_qt_member(qtbot: QtBot, trained_ctx: AppContext) -> None:
    """An attribute or method named after a Qt member (`size`, `pos`, `render`) hides it from every caller and from the
    type checker: `self.size = QComboBox()` shipped on two pages and `self.pos = -1` on one until S22a (#5). Checked on
    the shell, every page and every widget of ours in the window, against each one's own Qt base class."""
    win = MainWindow(trained_ctx)
    qtbot.addWidget(win)
    shadowed = []
    for widget in (win, *win.findChildren(QWidget)):
        if not type(widget).__module__.startswith("aoi."):
            continue  # Qt's own widgets define nothing in Python
        qt_base = next(c for c in type(widget).__mro__ if c.__module__.startswith("PySide6"))
        own = {n for n, v in vars(widget).items() if not isinstance(v, QT_INSTALLED)} | {
            n
            for cls in type(widget).__mro__
            if cls not in qt_base.__mro__
            for n, v in vars(cls).items()
            if not isinstance(v, QT_INSTALLED)
        }  # what the Python code defines: PySide6 installs a signal instance per object and a meta-object per class
        shadowed += [
            f"{type(widget).__name__}.{n}"
            for n in sorted(own)
            if not n.startswith("_") and hasattr(qt_base, n) and not QT_OVERRIDES.search(n)
        ]
    assert not shadowed, shadowed
