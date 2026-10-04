"""Screen rules of the Engineering standard, "Look", "Sizes" and "Empty state" (REQ-SET-004, REQ-SET-018, REQ-INSP-002,
REQ-SET-019, REQ-P3D-001; S18a, S18b, S18c).

Static scans keep every colour and point size in aoi/ui/theme.py. Widget checks open the shell offscreen and look at
the one frame every page sits in, the one blue primary button per page, the red destructive buttons, the verdict
banner with its shape and word, and the empty state of every page, list and image area with its next step.
"""

from __future__ import annotations

import ast
import re
import sqlite3
from collections import Counter
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path

import numpy as np
import pytest
from PySide6.QtCore import QMetaObject, QPoint, QRect, Qt, Signal, SignalInstance
from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import (
    QApplication,
    QBoxLayout,
    QComboBox,
    QFileDialog,
    QFrame,
    QInputDialog,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPlainTextEdit,
    QPushButton,
    QTableWidget,
    QWidget,
)
from pytestqt.qtbot import QtBot

from aoi.core.services import AppContext
from aoi.ui import theme
from aoi.ui.main_window import MainWindow
from aoi.ui.pages.base import button
from aoi.ui.pages.compare import MODE_DIFF
from aoi.ui.widgets.empty_state import EmptyState
from tests.conftest import engineer
from tests.screens.test_sizes_and_contrast import (
    MIN_RATIO,
    _check_widget,
    _contrast,
    _pixels,
    _region,
    check_calendar,
    check_menu,
    check_popup,
)
from tests.test_req_done_in_v01 import BOARD, _inspect_one, _window

ROOT = Path(__file__).resolve().parents[1]
UI_DIR = ROOT / "aoi" / "ui"
THEME = UI_DIR / "theme.py"
COLOUR_LITERAL = re.compile(r"#[0-9a-f]{3,8}\b|\b(?:rgb|hsv|hsl)a?\(", re.IGNORECASE)  # Qt reads RGB( and hsv( too
POINT_SIZE = re.compile(r"font-size:\s*(\d+)\s*pt")
QT_COLOURS = {m.name for m in Qt.GlobalColor}  # white, red, darkGreen, transparent, color0, …
COLOUR_CALLS = {"QColor", "QBrush", "QPen", "setNamedColor"}
COLOUR_FACTORIES = {
    f"from{s}" for s in ("Rgb", "RgbF", "Rgba64", "Hsv", "HsvF", "Hsl", "HslF", "Cmyk", "CmykF", "String")
}
CSS_COLOUR = re.compile(  # Qt takes "Background: Green" as it takes "background: green"
    r"(?<![\w-])([a-z-]*(?:color|background|border)[a-z-]*)\s*:\s*([^;{}'\"]*)", re.IGNORECASE
)
CSS_NAMES = {n.lower() for n in QColor.colorNames()}  # green, white, darkred, transparent, …
DESTRUCTIVE = re.compile(r"^(Delete|Remove|Reset Demo|Clear)\b")  # Reset Filters only changes a view
QT_OVERRIDES = re.compile(r"Event$|^event$|^eventFilter$|[sS]izeHint$|^paintEngine$")  # Qt virtuals defined on purpose
QT_INSTALLED = (Signal, SignalInstance, QMetaObject)
NO_BOARD_MODEL_PAGES = ("Inspection", "Training", "AI Model Test", "Recipe Editor")  # Page.no_board_model()


def _docstrings(tree: ast.AST) -> set[ast.AST]:
    out: set[ast.AST] = set()
    for node in ast.walk(tree):
        body = getattr(node, "body", None)
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef)) and body and isinstance(body[0], ast.Expr):
            out.add(body[0].value)
    return out


def _dotted(node: ast.AST) -> str:
    """The dotted name of an attribute chain, such as "Qt.GlobalColor"; "" for anything else."""
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute) and (head := _dotted(node.value)):
        return f"{head}.{node.attr}"
    return ""


def colour_literals(source: str, name: str) -> list[str]:
    """Every colour written in `source` other than through a theme token: "name:line spelling" for each. A string
    with a hex or rgb() colour or a CSS colour property with a colour name; a Qt.GlobalColor member, in full or as
    Qt.red; QColor, QBrush or QPen built from a constant; a QColor.from…() factory with a constant. Colour names and
    property names match in any case, as Qt reads them."""
    tree = ast.parse(source, filename=name)
    docstrings = _docstrings(tree)
    found: list[str] = []
    inner: set[ast.AST] = set()
    for node in ast.walk(tree):  # breadth first: Qt.GlobalColor.red comes before its Qt.GlobalColor
        where = f"{name}:{getattr(node, 'lineno', 0)}"
        if isinstance(node, ast.Constant) and isinstance(node.value, str) and node not in docstrings:
            named = [v for _, v in CSS_COLOUR.findall(node.value) if set(re.findall(r"[a-z]+", v.lower())) & CSS_NAMES]
            if COLOUR_LITERAL.search(node.value) or named:
                found.append(f"{where} {node.value!r}")
        elif isinstance(node, ast.Attribute) and node not in inner:
            dotted = _dotted(node)
            if node.attr in QT_COLOURS and ({"Qt", "GlobalColor"} & set(dotted.split(".")[:-1])):
                inner.add(node.value)  # Qt.GlobalColor.red is one finding, not two
                found.append(f"{where} {dotted}")
            elif node.attr == "GlobalColor":  # Qt.GlobalColor(7), or the enum passed on
                found.append(f"{where} {dotted}")
        elif isinstance(node, ast.Call):
            first = [*node.args, *(k.value for k in node.keywords)][:1]  # QColor(200, 0, 0) or QColor(name="red")
            func = node.func.attr if isinstance(node.func, ast.Attribute) else _dotted(node.func)
            owner = _dotted(node.func.value).split(".")[-1] if isinstance(node.func, ast.Attribute) else ""
            factory = func in COLOUR_FACTORIES and owner == "QColor"  # not QDate.fromString("2025-01-01", …)
            if first and isinstance(first[0], ast.Constant) and (func in COLOUR_CALLS or factory):
                found.append(f"{where} {func}({first[0].value!r})")
    return found


def test_req_set_004_no_colour_literals_outside_theme() -> None:
    """Pages and widgets take colours from the theme tokens: none of the spellings `colour_literals` reports."""
    found: list[str] = []
    for path in sorted(UI_DIR.rglob("*.py")):
        if path != THEME:
            found += colour_literals(path.read_text(encoding="utf-8"), str(path.relative_to(ROOT)))
    assert not found, "colour literals outside aoi/ui/theme.py: " + ", ".join(found)


# Each spelling of a colour the scan must report (#203), and token-built code it must leave alone
COLOUR_SPELLINGS = {
    "hex": 'w.setStyleSheet("color: #ff0000")',
    "rgb()": 'w.setStyleSheet("background: rgb(200, 0, 0)")',
    "CSS colour keyword": 'w.setStyleSheet("background: green; color: white; font-size: 40pt")',
    "CSS keyword in an HTML style": "label.setText(\"<span style='color:red'>NG</span>\")",
    "CSS keyword on a border": 'w.setStyleSheet("border: 2px solid darkred")',
    "CSS keyword capitalised": 'w.setStyleSheet("background: Green; color: White; font-size: 40pt")',
    "CSS keyword in capitals": 'w.setStyleSheet("BACKGROUND-COLOR: RED")',
    "RGB() in capitals": 'w.setStyleSheet("color: RGB(200, 0, 0)")',
    "hsv()": 'w.setStyleSheet("border: 2px solid hsv(0, 255, 230)")',
    "hsla()": 'w.setStyleSheet("background: hsla(120, 255, 100, 255)")',
    "QtCore.Qt.red": "QColor(QtCore.Qt.red)",
    "QtCore.Qt.GlobalColor.red": "QColor(QtCore.Qt.GlobalColor.red)",
    'QColor(name="…")': 'QColor(name="red")',
    "setNamedColor": 'c.setNamedColor("red")',
    "Qt.red": "QColor(Qt.red)",
    "Qt.GlobalColor.red": "c = QColor(Qt.GlobalColor.red)",
    "QPen(Qt.GlobalColor.red)": "pen = QPen(Qt.GlobalColor.red, width)",
    "GlobalColor imported": "brush = QBrush(GlobalColor.darkGreen)",
    "Qt.GlobalColor(int)": "QColor(Qt.GlobalColor(7))",
    "QColor(int)": "QColor(200, 0, 0)",
    'QColor("…")': 'QColor("red")',
    "QtGui.QColor(int)": "QtGui.QColor(200, 0, 0)",
    "QColor.fromRgb": "c = QColor.fromRgb(200, 0, 0).name()",
    "QColor.fromRgbF": "QColor.fromRgbF(0.8, 0, 0)",
    "QColor.fromHsv": "QColor.fromHsv(0, 255, 200)",
    "QColor.fromHsl": "QColor.fromHsl(0, 255, 100)",
    "QColor.fromCmyk": "QColor.fromCmyk(0, 255, 255, 50)",
    "QColor.fromString": 'QColor.fromString("red")',
}
TOKEN_BUILT = """
\"\"\"A docstring may name #ff0000 and color: red.\"\"\"
w.setStyleSheet(f"background:{theme.BG}; color:{on_color(c)}; border: 1px solid {theme.LINE}")
label.setText(f"<span style='font-size:{theme.FONT_PT}pt;color:{theme.ACCENT}'>{n}</span>")
pen = QPen(QColor(theme.NG_COLOR), width)
pen.setStyle(Qt.PenStyle.DashLine)
label.setAlignment(Qt.AlignmentFlag.AlignCenter)
c = QColor.fromString(theme.OK_COLOR)
day = QDate.fromString("2025-01-01", "yyyy-MM-dd")
keys = QKeySequence.fromString("Ctrl+S")
w.setToolTip(self.tr("Border: the board's edge, background: the bare board"))
"""


def test_req_set_004_colour_scan_reports_every_spelling() -> None:
    """The scan above reports each way of writing a colour, as a page would write it, and leaves token-built strings,
    docstrings and other Qt enums alone (#203: named CSS colours, Qt.GlobalColor.red and QColor.fromRgb() passed)."""
    missed = [what for what, code in COLOUR_SPELLINGS.items() if not colour_literals(code, what)]
    assert not missed, f"the colour scan does not report: {missed}"
    assert colour_literals(TOKEN_BUILT, "token-built") == []


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
    test_page._show_preview(str(ng_board), res, test_page.run_board_model, test_page.run_judged)
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


def _fill(win: QWidget, shot: np.ndarray, w: QWidget) -> str:
    """The colour of `w` in the window grab just inside its left edge, half way down: a button's fill."""
    p = w.mapTo(win, w.rect().center())
    x, y = w.mapTo(win, w.rect().topLeft()).x() + 2 * theme.RADIUS, p.y()
    return "#" + "".join(f"{int(v):02x}" for v in shot[y, x])


def test_req_set_004_a_disabled_coloured_button_looks_disabled(qtbot: QtBot, trained_ctx: AppContext) -> None:
    """A disabled primary, Start, Stop or red Delete button greys out like a plain one (#203: the ID rules outranked
    QPushButton:disabled, so Start, Stop and Next Board looked live on an idle Inspection page)."""
    fills = {"": theme.BG_BUTTON, "primary": theme.ACCENT, "start": theme.OK_COLOR, "stop": theme.NG_COLOR}
    fills["danger"] = theme.NG_COLOR
    for kind, fill in fills.items():
        grabs = []
        for enabled in (True, False):
            b = button("Delete", kind)
            qtbot.addWidget(b)
            b.resize(200, theme.RUN_CONTROL_H)
            b.setEnabled(enabled)
            b.show()
            QApplication.processEvents()
            grabs.append(shot := _pixels(b.grab().toImage()))
            measured = _contrast(shot)
            assert measured is not None, kind
            want = (fill, theme.ON_DARK if kind else theme.TEXT) if enabled else (theme.BG_RAISED, theme.TEXT_DISABLED)
            assert measured[1:] == want, (kind or "plain", enabled, measured)
        assert not np.array_equal(*grabs), f"a disabled {kind or 'plain'} button looks like an enabled one"
    win = _window(qtbot, trained_ctx, "Engineer")
    insp, recipe = win.pages["Inspection"], win.pages["Recipe Editor"]
    win.navigate("Inspection")  # nothing queued: Start, Stop and Next Board are off
    QApplication.processEvents()
    shot = _pixels(win.grab().toImage())
    for b in (insp.btn_start, insp.btn_stop, insp.btn_next, insp.btn_save):
        assert not b.isEnabled() and _fill(win, shot, b) == theme.BG_RAISED, (b.text(), _fill(win, shot, b))
    win.navigate("Recipe Editor")  # no ROI selected: Apply and the red Delete are off
    QApplication.processEvents()
    shot = _pixels(win.grab().toImage())
    for b in (recipe.apply_btn, recipe.delete_btn):
        assert not b.isEnabled() and _fill(win, shot, b) == theme.BG_RAISED, (b.text(), _fill(win, shot, b))


def test_req_set_004_a_selected_row_reads_at_4_5_to_1(qtbot: QtBot, trained_ctx: AppContext, ng_board: Path) -> None:
    """An Operator selects a defect row to zoom to it: the row is drawn in the theme's selection colours, 14 pt white
    on BG_SELECTED at 4.5:1 or more, the focused cell too (#203: Qt's default highlight, 3.7:1 and 3.4:1); fields,
    lists, text areas and combo popups select in the same colours."""
    win = _window(qtbot, trained_ctx, "Operator")
    page = _inspect_one(qtbot, win, ng_board)
    table = page.table
    assert table.rowCount() >= 1
    table.selectRow(0)
    for focused in (False, True):
        if focused:
            win.activateWindow()
            table.setFocus()
            qtbot.waitUntil(table.hasFocus)
        QApplication.processEvents()
        shot = _pixels(win.grab().toImage())
        for c in range(table.columnCount()):
            it = table.item(0, c)
            assert it is not None and it.isSelected()
            measured = _contrast(_region(shot, win, table.viewport(), table.visualItemRect(it)))
            assert measured is not None and measured[0] >= MIN_RATIO, (focused, it.text(), measured)
            if c == table.columnCount() - 1:  # not the current cell, which carries the focus frame
                assert measured[1:] == (theme.BG_SELECTED, theme.ON_DARK), (focused, it.text(), measured)
    views = [win.bm_combo.view()] + [
        next(w for w in win.findChildren(cls)) for cls in (QLineEdit, QListWidget, QPlainTextEdit, QTableWidget)
    ]
    for v in views:
        v.ensurePolished()
        colours = (
            v.palette().color(r).name() for r in (QPalette.ColorRole.Highlight, QPalette.ColorRole.HighlightedText)
        )
        assert tuple(colours) == (theme.BG_SELECTED, theme.ON_DARK), type(v).__name__
    roles = (QPalette.ColorRole.Base, QPalette.ColorRole.Text)  # and the entries not highlighted read on it (#239)
    assert tuple(win.bm_combo.view().palette().color(r).name() for r in roles) == (theme.BG_DEEP, theme.TEXT)


@contextmanager
def _app_style(qapp: QApplication, name: str) -> Iterator[None]:
    """The application in the style `name` with the theme's stylesheet; the style before is put back."""
    sheet = qapp.styleSheet()
    qapp.setStyleSheet("")  # with a stylesheet, style() is the stylesheet's own and has no name
    before = qapp.style().name()
    qapp.setStyle(name)
    qapp.setStyleSheet(sheet)
    try:
        yield
    finally:
        qapp.setStyleSheet("")
        qapp.setStyle(before)
        qapp.setStyleSheet(sheet)


@pytest.mark.parametrize("style", ["Fusion", "Windows"])
def test_req_set_004_drop_down_entries_and_calendar_days_read_at_4_5_to_1(
    qtbot: QtBot, qapp: QApplication, trained_ctx: AppContext, style: str
) -> None:
    """An Operator with two board models opens the header Board model drop-down, then the Logs From calendar: every
    entry, day, weekday name, month and year reads at 4.5:1 or more, the month and year also under the pointer, and the
    previous and next month arrows at 3:1, under Fusion (the screenshots' style) and the Windows style. Before #239
    only the highlighted entry and day read: the others were TEXT on the style's light Base (1.03:1 under Fusion,
    1.18:1 under Windows), the weekday names 1.10:1 and the weekend days Qt's red (4.0:1); under the pointer the month
    and year were TEXT on the style's light hover panel (1.03 to 1.15:1)."""
    with _app_style(qapp, style):
        win = _window(qtbot, trained_ctx, "Operator")
        engineer(trained_ctx).ensure_board_model("TBOX-A1 Rev2")
        win._reload_board_models(BOARD)
        win.set_user("operator")
        seen: Counter = Counter()
        findings = check_popup("header", win.bm_combo, seen)
        assert seen["popup_rows"] == 2 and win.bm_combo.currentText() == BOARD, seen
        dialog = QInputDialog(win)  # Switch User asks with a fixed list, which Qt shows as a drop-down
        dialog.setComboBoxItems(["operator (Operator)", "admin (Admin)"])
        dialog.show()
        findings += check_popup("Switch User", dialog.findChild(QComboBox), seen)
        dialog.reject()
        assert win.navigate("Logs & Export")
        d_from = win.pages["Logs & Export"].d_from
        findings += check_calendar("Logs From", d_from, seen)
        assert seen["calendar_cells"] >= 7 * 7 + 2 and seen["menu_entries"] == 12, seen
        assert seen["calendar_hover"] == 2 and seen["calendar_arrows"] == 2 * 2, seen  # at rest and under the pointer
        kinds = ("popup_rows", "calendar_cells", "calendar_hover", "calendar_arrows", "menu_entries")
        assert seen["contrast"] == sum(seen[k] for k in kinds), seen
        edit = d_from.findChild(QLineEdit)  # a text field's right-click menu is a menu of the same kind
        menu = edit.createStandardContextMenu()
        findings += check_menu("From field", menu, edit.mapToGlobal(QPoint()), seen)
        menu.deleteLater()
        assert not findings, "\n".join(findings)


@pytest.mark.parametrize("role", ["Operator", "Admin"])
def test_req_set_004_sidebar_headings_read_at_4_5_to_1(qtbot: QtBot, trained_ctx: AppContext, role: str) -> None:
    """The sidebar headings PRODUCTION, ENGINEERING, DATA and SYSTEM are TEXT_MUTED on BG_DEEP (7.4:1) for every role,
    a page the role may not open (Training for an Operator) stays TEXT_DISABLED, and Up and Down never stop on a
    heading. Before #239 the stylesheet's colour for a disabled item drew the headings in TEXT_DISABLED, 3.85:1."""
    win = _window(qtbot, trained_ctx, role)
    nav = win.nav
    shot = _pixels(win.grab().toImage())
    items = [nav.item(i) for i in range(nav.count())]

    def measured(it: QListWidgetItem) -> tuple[float, str, str] | None:
        return _contrast(_region(shot, win, nav.viewport(), nav.visualItemRect(it) & nav.viewport().rect()))

    headings = {it.text(): measured(it) for it in items if not it.data(Qt.ItemDataRole.UserRole)}
    assert list(headings) == ["PRODUCTION", "ENGINEERING", "DATA", "SYSTEM"]
    for text, m in headings.items():
        assert m is not None and m[0] >= MIN_RATIO and m[1:] == (theme.BG_DEEP, theme.TEXT_MUTED), (text, m)
    if role == "Operator":
        m = measured(win._items["Training"])
        assert m is not None and m[1:] == (theme.BG_DEEP, theme.TEXT_DISABLED), m
    nav.setFocus()
    for key in [Qt.Key.Key_Down] * len(items) + [Qt.Key.Key_Up] * len(items):
        qtbot.keyClick(nav, key)
        assert nav.currentItem().data(Qt.ItemDataRole.UserRole), (key, nav.currentItem().text())


def test_req_set_004_a_progress_bar_past_half_reads_and_is_measured(qtbot: QtBot, trained_ctx: AppContext) -> None:
    """A finished training run leaves the bar at 100 %: its percentage on the accent chunk is bold white, 3:1 or more
    for large text, and the size and contrast walk measures it and fails on the look before #203 (regular TEXT at
    3.1:1, which the walk never measured)."""
    win = _window(qtbot, trained_ctx, "Engineer")
    win.navigate("Training")
    bar = win.pages["Training"].bar
    bar.setRange(0, 10)
    bar.setValue(10)
    QApplication.processEvents()
    seen: Counter = Counter()
    shot = _pixels(win.grab().toImage())
    assert _check_widget("Training", win, shot, bar, seen) == [] and seen["contrast"] == 1, seen
    text = QRect(0, 0, bar.fontMetrics().horizontalAdvance(bar.text()), bar.fontMetrics().height())
    text.moveCenter(bar.rect().center())
    measured = _contrast(_region(shot, win, bar, text))
    assert measured is not None and measured[1:] == (theme.ACCENT, theme.ON_DARK) and bar.font().bold(), measured
    bar.setStyleSheet(f"QProgressBar {{ color: {theme.TEXT}; font-weight: 400; }}")  # the look before #203
    QApplication.processEvents()
    findings = _check_widget("Training", win, _pixels(win.grab().toImage()), bar, seen)
    assert len(findings) == 1 and "reads at 3.1:1, needs 4.5:1" in findings[0], findings


def _empties(page: QWidget) -> list[EmptyState]:
    return [e for e in page.findChildren(EmptyState) if e.isVisibleTo(page)]


def test_req_set_019_empty_states_link_next_step(
    qtbot: QtBot, ctx: AppContext, trained_ctx: AppContext, ng_board: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Every empty page, list and image area says what is missing, what to do and links there; a role that cannot
    open the linked page is told to ask an Engineer; with no board model the step is "+ New board model", or for an
    Operator to ask an Engineer; a filtered-out history offers Reset Filters."""
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
    # With no board model the header list is empty, so there is nothing to pick: an Engineer or Admin is offered
    # "+ New board model" as on Home, and an Operator is told to ask an Engineer (#200).
    asked: list[str] = []

    def get_text(parent: QWidget, title: str, *args: object, **kwargs: object) -> tuple[str, bool]:
        asked.append(title)
        return "", False

    monkeypatch.setattr(QInputDialog, "getText", staticmethod(get_text))
    for role in ("Admin", "Engineer"):
        win.set_user(role.lower())
        for title in NO_BOARD_MODEL_PAGES:
            win.navigate(title)
            e = _empties(win.pages[title])[0]
            got = (e.heading.text(), e.sentence.text(), e.link.text(), e.link.isVisibleTo(win.pages[title]))
            assert got == ("No board model yet", "Create one to begin.", "+ New board model", True), (role, title)
            e.link.click()
            assert asked.pop() == "New board model", (role, title)
    win.set_user("operator")
    win.navigate("Inspection")
    e = _empties(win.pages["Inspection"])[0]
    assert (e.sentence.text(), e.link.isVisibleTo(win.pages["Inspection"])) == ("Ask an Engineer to create one.", False)
    win.set_user("admin")
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
    compare.run()  # as Golden Board does for the Operator; the newest run wins
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


@pytest.mark.parametrize("history", ["old", "archived"])
def test_req_set_019_logs_link_brings_back_old_or_archived_records(
    qtbot: QtBot, trained_ctx: AppContext, ng_board: Path, history: str
) -> None:
    """When every record is older than the 7 days Reset Filters shows, or archived, the "No records match" link is not
    Reset Filters, which ran the same empty query again (#200): it shows every record and the rows come back."""
    win = _window(qtbot, trained_ctx, "Engineer")
    _inspect_one(qtbot, win, ng_board)
    with sqlite3.connect(trained_ctx.settings.db_path) as db:
        if history == "old":
            db.execute("UPDATE inspections SET time=?", ((datetime.now(UTC) - timedelta(days=30)).isoformat(),))
        else:
            db.execute("UPDATE inspections SET archived=1")
    db.close()
    logs = win.pages["Logs & Export"]
    win.navigate("Logs & Export")
    assert logs.table.rowCount() == 0 and logs.empty.heading.text() == "No records match"
    assert logs.empty.link.isVisibleTo(logs)
    logs.empty.link.click()
    assert logs.table.rowCount() == 1 and not _empties(logs), (logs.empty.sentence.text(), logs.empty.link.text())
    assert logs.archived.isChecked() == (history == "archived")


def test_req_set_019_next_step_links_with_a_board_model(
    qtbot: QtBot, trained_ctx: AppContext, monkeypatch: pytest.MonkeyPatch
) -> None:
    """With a board model chosen, each page's own empty state shows its link and the link does its step: Inspection
    asks for images, Training for a folder of samples, AI Model Test for a validation folder, and Compare opens
    Inspection (#200: removing any of these links passed the stage test)."""
    opened: list[str] = []

    def open_files(*args: object, **kwargs: object) -> tuple[list[str], str]:
        opened.append("files")
        return [], ""

    def open_folder(*args: object, **kwargs: object) -> str:
        opened.append("folder")
        return ""

    monkeypatch.setattr(QFileDialog, "getOpenFileNames", staticmethod(open_files))
    monkeypatch.setattr(QFileDialog, "getExistingDirectory", staticmethod(open_folder))
    win = _window(qtbot, trained_ctx, "Engineer")
    trained_ctx.ensure_board_model("NO-SAMPLES")
    steps = (  # page, its empty state, the board model, heading, link, then the file dialog opened or the page shown
        ("Inspection", "empty", BOARD, "No images loaded", "Load Images…", "files"),
        ("AI Model Test", "empty", BOARD, f"No validation run for {BOARD} yet", "Select Test Folder…", "folder"),
        ("Compare", "test_empty", BOARD, "No board to compare yet", "Open Inspection ›", "Inspection"),
        ("Training", "samples_empty", "NO-SAMPLES", "No samples for NO-SAMPLES yet", "Import Folder…", "folder"),
    )
    for title, name, board_model, heading, link, then in steps:
        win._reload_board_models(board_model)
        win.navigate(title)
        page = win.pages[title]
        empty = getattr(page, name)
        qtbot.waitUntil(lambda e=empty, h=heading: e.heading.text() == h, timeout=30000)
        assert empty.isVisibleTo(page) and empty.link.isVisibleTo(page) and empty.link.text() == link, title
        empty.link.click()
        if then in ("files", "folder"):
            assert opened.pop() == then and not opened, title
        else:
            assert win.stack.currentWidget() is win.pages[then], title


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
    sentence = (  # Compare's Golden board pane, with and without the file's name
        "The Golden board this result was judged against{name} has changed since. The verdict and the decision table"
        " are the stored ones; press Re-evaluate › to inspect the board again with today's Golden board."
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
    height and volume thresholds live; nothing on it looks like a working 3D control (sketch profile3d-card.md)."""
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
