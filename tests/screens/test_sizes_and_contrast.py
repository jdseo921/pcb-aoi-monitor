"""Sizes and contrast of every page for every role, measured on the rendered widgets (REQ-SET-004; S21b).

Engineering standard, "Sizes" (MUST): text at least 14 pt, buttons at least 120×40 px, operator touch targets at
least 48 px tall, text contrast at least 4.5:1. The walk opens the shell at 1920×1080 on the synthetic workspace, puts
every page in the state the screenshots show (`tools/render_screens.py`) and, for every role that may open it, reads
each visible widget: its resolved font, its size, whether its text fits, and the colours of its pixels in the window
grab. Contrast is the WCAG 2.1 ratio between a widget's background (its most common colour) and its text (the colour
farthest from the background in luminance); bold or 18 pt text may read at 3:1 (WCAG 1.4.3, large text) and a disabled
control is exempt, but a disabled button must show the disabled fill, so it never looks ready to press. A progress bar's
percentage is measured in its centred text, and the prepared states hold a selected row (Inspection) and a bar past
half (Training). Text drawn on an image (QGraphics items) is measured against the image area's background. Every list
item with text is measured, the sidebar's section headings too; only a sidebar entry of a page the role may not open
is exempt, as a disabled control, and it must be drawn in the disabled grey. The walk opens every drop-down list and
every date field's calendar on the page, and one text field's right-click menu, which are windows of their own and not
in the page grab, and measures each entry, day and weekday name, the month and year (at rest and under the pointer) and
the month list; the calendar's previous and next month arrows, a control's graphic, need 3:1 (WCAG 1.4.11) (#239). The
walk runs on Linux and Windows: sizes and colours do not depend on the font file.
"""

from __future__ import annotations

import sys
from collections import Counter
from pathlib import Path

import numpy as np
from PySide6.QtCore import QPoint, QRect, Qt
from PySide6.QtGui import QColor, QFont, QFontDatabase, QFontInfo, QImage
from PySide6.QtTest import QTest
from PySide6.QtWidgets import (
    QAbstractButton,
    QAbstractItemView,
    QAbstractSpinBox,
    QApplication,
    QComboBox,
    QDateEdit,
    QFrame,
    QGraphicsSimpleTextItem,
    QGraphicsView,
    QGroupBox,
    QHeaderView,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QStatusBar,
    QTabBar,
    QTableView,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QToolButton,
    QWidget,
)
from pytestqt.qtbot import QtBot

from aoi.core.services import AppContext
from aoi.ui import theme
from aoi.ui.main_window import MainWindow
from aoi.ui.pages.base import ROLES
from tools import render_screens

LINUX = sys.platform == "linux"
LARGE_PT = 18  # WCAG 2.1: large text is 18 pt, or 14 pt bold
MIN_RATIO, LARGE_RATIO = 4.5, 3.0
GRAPHIC_RATIO = 3.0  # WCAG 2.1 1.4.11: the graphic that identifies a control, such as an arrow, against its ground
TEXT_WIDGETS = (
    QLabel, QAbstractButton, QComboBox, QLineEdit, QAbstractSpinBox, QGroupBox, QTabBar, QHeaderView, QAbstractItemView,
    QProgressBar, QPlainTextEdit, QTextEdit, QStatusBar,
)  # fmt: skip
PLAIN_TEXT = (
    QLabel,
    QAbstractButton,
    QComboBox,
    QLineEdit,
    QAbstractSpinBox,
    QGroupBox,
    QPlainTextEdit,
    QTextEdit,
    QStatusBar,
)


def _pixels(image: QImage) -> np.ndarray:
    """The grab as an (h, w, 3) RGB array."""
    img = image.convertToFormat(QImage.Format.Format_RGB888)
    h, w, stride = img.height(), img.width(), img.bytesPerLine()
    flat = np.frombuffer(img.constBits(), dtype=np.uint8, count=stride * h)
    return flat.reshape(h, stride)[:, : w * 3].reshape(h, w, 3).copy()


def _luminance(rgb: np.ndarray) -> np.ndarray:
    c = rgb.astype(np.float64) / 255
    linear = np.where(c <= 0.03928, c / 12.92, ((c + 0.055) / 1.055) ** 2.4)
    return linear @ np.array([0.2126, 0.7152, 0.0722])


def _ratio(a: str, b: str) -> float:
    lum = _luminance(np.array([[int(h[i : i + 2], 16) for i in (1, 3, 5)] for h in (a, b)]))
    return float((lum.max() + 0.05) / (lum.min() + 0.05))


def _contrast(region: np.ndarray) -> tuple[float, str, str] | None:
    """(ratio, background, text) of a region of the grab, or None when it holds no second colour (no text)."""
    packed = (region[..., 0].astype(np.int64) << 16) | (region[..., 1].astype(np.int64) << 8) | region[..., 2]
    values, counts = np.unique(packed, return_counts=True)
    colours = np.stack([(values >> 16) & 255, (values >> 8) & 255, values & 255], axis=1)
    lum = _luminance(colours)
    bg = int(np.argmax(counts))
    distance = np.abs(lum - lum[bg])  # the farthest colour is a glyph's core; anti-aliased edges lie between
    fg = int(np.argmax(distance))
    if distance[fg] < 0.02:
        return None
    hexes = ["#" + "".join(f"{int(v):02x}" for v in colours[i]) for i in (bg, fg)]
    return float((max(lum[bg], lum[fg]) + 0.05) / (min(lum[bg], lum[fg]) + 0.05)), hexes[0], hexes[1]


def _fill(region: np.ndarray | None) -> str | None:
    """The most common colour of a region of the grab: a button's fill."""
    if region is None:
        return None
    values, counts = np.unique(region.reshape(-1, 3), axis=0, return_counts=True)
    return "#" + "".join(f"{int(v):02x}" for v in values[int(np.argmax(counts))])


def _region(shot: np.ndarray, win: QWidget, w: QWidget, rect: QRect | None = None) -> np.ndarray | None:
    """The pixels of `rect` (in `w`'s coordinates; default: all of `w`) in the window grab."""
    rect = rect if rect is not None else w.rect()
    r = QRect(w.mapTo(win, rect.topLeft()), rect.size()) & QRect(0, 0, shot.shape[1], shot.shape[0])
    return None if r.isEmpty() else shot[r.top() : r.bottom() + 1, r.left() : r.right() + 1]


def _text(w: QWidget) -> str:
    for attr in ("text", "currentText", "title", "currentMessage", "toPlainText"):
        f = getattr(w, attr, None)
        if callable(f) and isinstance(t := f(), str):
            return t.replace("&&", "&").strip()
    return ""


def _large(font: QFont) -> bool:
    info = QFontInfo(font)
    return info.pointSizeF() >= LARGE_PT or (info.bold() and info.pointSizeF() >= theme.FONT_PT)


def _needs(ratio: float, font: QFont) -> float | None:
    """The ratio the text needs when `ratio` falls short, else None."""
    need = LARGE_RATIO if _large(font) else MIN_RATIO
    return need if ratio < need else None


def _check_contrast(region: np.ndarray | None, font: QFont, name: str, seen: Counter) -> list[str]:
    measured = _contrast(region) if region is not None else None
    if measured is None:
        return []
    seen["contrast"] += 1
    ratio, bg, fg = measured
    need = _needs(ratio, font)
    return [f"{name}: {fg} on {bg} reads at {ratio:.1f}:1, needs {need}:1"] if need else []


def _check_graphic(region: np.ndarray | None, name: str, seen: Counter) -> list[str]:
    """A control drawn with no text, such as an arrow: its graphic reads at 3:1 or more on its ground (#239)."""
    seen["contrast"] += 1
    measured = _contrast(region) if region is not None else None
    if measured is None:
        return [f"{name}: no graphic to see"]
    ratio, bg, fg = measured
    return [f"{name}: {fg} on {bg} reads at {ratio:.1f}:1, needs {GRAPHIC_RATIO}:1"] if ratio < GRAPHIC_RATIO else []


def _covered(win: QWidget, w: QWidget) -> bool:
    """Another widget (an empty state, a busy overlay) is drawn over the middle of `w`: the pixels are not its own."""
    top = win.childAt(w.mapTo(win, w.rect().center()))
    return top is not None and top is not w and not w.isAncestorOf(top)


def _check_widget(where: str, win: QWidget, shot: np.ndarray, w: QWidget, seen: Counter) -> list[str]:
    out: list[str] = []
    name = f"{where}: {type(w).__name__} '{_text(w)[:40]}'"
    if isinstance(w, TEXT_WIDGETS):
        seen["text"] += 1
        pt = QFontInfo(w.font()).pointSizeF()
        if pt < theme.FONT_PT:
            out.append(f"{name}: {pt:.1f} pt text")
    if isinstance(w, QPushButton):
        seen["buttons"] += 1
        if w.width() < theme.BUTTON_W or w.height() < theme.BUTTON_H:
            out.append(f"{name}: {w.width()}x{w.height()} px button")
        needed = w.fontMetrics().horizontalAdvance(_text(w)) + 2 * theme.SPACE + 2
        if w.width() < needed:
            out.append(f"{name}: {w.width()} px wide; its text needs {needed} px")
    if isinstance(w, QLabel) and w.text() and not w.wordWrap() and "<" not in w.text():  # plain text clips
        needed = w.fontMetrics().horizontalAdvance(w.text()) + 2 * w.margin()
        if w.width() < needed:
            out.append(f"{name}: {w.width()} px wide; its text needs {needed} px")
    if _covered(win, w):
        return out  # a covered widget shows another's pixels
    if not w.isEnabled():  # exempt from contrast (WCAG 1.4.3), but it must look disabled (#203)
        if isinstance(w, QPushButton) and (fill := _fill(_region(shot, win, w))) not in (None, theme.BG_RAISED):
            out.append(f"{name}: disabled, but drawn on {fill}, not the disabled fill {theme.BG_RAISED}")
        return out
    if (isinstance(w, PLAIN_TEXT) and _text(w)) or (isinstance(w, QHeaderView) and w.count()):
        out += _check_contrast(_region(shot, win, w), w.font(), name, seen)
    elif isinstance(w, QProgressBar) and w.isTextVisible() and w.text():
        fm = w.fontMetrics()
        rect = QRect(0, 0, fm.horizontalAdvance(w.text()), fm.height())
        rect.moveCenter(w.rect().center())  # the theme centres the percentage
        out += _check_contrast(_region(shot, win, w, rect), w.font(), name, seen)
    elif isinstance(w, QTabBar):
        for i in range(w.count()):
            out += _check_contrast(_region(shot, win, w, w.tabRect(i)), w.font(), f"{name} tab '{w.tabText(i)}'", seen)
    elif isinstance(w, (QListWidget, QTableWidget)):
        items = [w.item(i) for i in range(w.count())] if isinstance(w, QListWidget) else [
            w.item(r, c) for r in range(w.rowCount()) for c in range(w.columnCount())
        ]  # fmt: skip
        for it in (it for it in items if it is not None and it.text()):
            region = _region(shot, win, w.viewport(), w.visualItemRect(it) & w.viewport().rect())
            font = it.font() if it.data(Qt.ItemDataRole.FontRole) is not None else w.font()
            if not _locked_page(w, it):
                out += _check_contrast(region, font, f"{name} item '{it.text()}'", seen)
            elif (measured := _contrast(region) if region is not None else None) and measured[2] != theme.TEXT_DISABLED:
                out.append(f"{name} item '{it.text()}': locked, but drawn in {measured[2]}, not {theme.TEXT_DISABLED}")
    elif isinstance(w, QGraphicsView):
        bg = w.backgroundBrush().color().name()
        for item in w.scene().items():
            if isinstance(item, QGraphicsSimpleTextItem) and item.isVisible():
                seen["image_text"] += 1
                label = f"{where}: text on the image '{item.text()[:40]}'"
                if item.font().pointSizeF() < theme.FONT_PT:
                    out.append(f"{label}: {item.font().pointSizeF():.1f} pt")
                colour = QColor(item.brush().color()).name()
                if (need := _needs(_ratio(colour, bg), item.font())) is not None:
                    out.append(f"{label}: {colour} on {bg} reads at {_ratio(colour, bg):.1f}:1, needs {need}:1")
    return out


def _locked_page(w: QWidget, it: QListWidgetItem | QTableWidgetItem) -> bool:
    """A sidebar entry of a page the role may not open: an inactive control, so exempt from contrast (WCAG 1.4.3), but
    it must look disabled. Every other item with text is measured, the sidebar's section headings included (#239)."""
    page = it.data(Qt.ItemDataRole.UserRole)
    return w.objectName() == "nav" and bool(page) and not it.flags() & Qt.ItemFlag.ItemIsEnabled


def check_popup(where: str, combo: QComboBox, seen: Counter) -> list[str]:
    """Every entry of the list a drop-down opens. The list is a window of its own, so it is not in the page grab: the
    walk opens it, scrolls each entry into view and grabs it, and closes it again (#239)."""
    combo.showPopup()
    QApplication.processEvents()
    view = combo.view()
    port = view.viewport()
    out: list[str] = []
    for r in range(combo.count()):
        index = combo.model().index(r, combo.modelColumn())
        view.scrollTo(index)  # an entry below a long list's fold is measured too, never only counted
        region = _region(_pixels(port.grab().toImage()), port, port, view.visualRect(index))
        seen["popup_rows"] += 1
        name = f"{where}: drop-down '{_text(combo)}' entry '{combo.itemText(r)}'"
        out += _check_contrast(region, view.font(), name, seen) if region is not None else [f"{name}: not shown"]
    combo.hidePopup()
    return out


def check_calendar(where: str, edit: QDateEdit, seen: Counter) -> list[str]:
    """Every day and weekday name, the month and year at rest and under the pointer, the previous and next month arrows
    and the month menu of the calendar a date field opens, clicked open on its arrow as a user does (#239)."""
    arrow = QPoint(edit.width() - 4, edit.height() // 2)  # the drop-down arrow at the right edge; no key opens it
    QTest.mouseClick(edit, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, arrow)
    cal = edit.calendarWidget()
    QApplication.processEvents()
    assert cal.isVisible(), f"{where}: the calendar did not open"
    out: list[str] = []
    table = cal.findChild(QTableView, "qt_calendar_calendarview")
    shot, model = _pixels(table.viewport().grab().toImage()), table.model()
    for r in range(model.rowCount()):
        for c in range(model.columnCount()):
            seen["calendar_cells"] += 1
            index = model.index(r, c)
            name = f"{where}: calendar cell '{index.data()}' (row {r})"
            region = _region(shot, table.viewport(), table.viewport(), table.visualRect(index))
            out += _check_contrast(region, table.font(), name, seen)
    bar = cal.findChild(QWidget, "qt_calendar_navigationbar")
    for b in (b for b in bar.findChildren(QToolButton) if b.isVisible()):
        for hover in (False, True):  # a mouse user's pointer rests on the month or year just before the click
            b.setAttribute(Qt.WidgetAttribute.WA_UnderMouse, hover)  # what Qt sets on Enter: State_MouseOver, :hover
            rect = b.geometry().adjusted(4, 4, -4, -4)  # inside a hover panel's frame, which is not the text's ground
            region = _region(_pixels(bar.grab().toImage()), bar, bar, rect)
            name = f"{where}: calendar '{b.text() or b.objectName()}'" + (" under the pointer" if hover else "")
            if b.text():
                seen["calendar_hover" if hover else "calendar_cells"] += 1
                out += _check_contrast(region, b.font(), name, seen)
            else:
                seen["calendar_arrows"] += 1
                out += _check_graphic(region, name, seen)
        b.setAttribute(Qt.WidgetAttribute.WA_UnderMouse, False)
    month = cal.findChild(QToolButton, "qt_calendar_monthbutton")
    out += check_menu(f"{where}: calendar month", month.menu(), month.mapToGlobal(QPoint(0, month.height())), seen)
    cal.window().hide()
    return out


def check_field_menu(where: str, win: QWidget, seen: Counter) -> list[str]:
    """The right-click menu of the page's first text field: a QMenu, themed for the whole app like the calendar's month
    list, so one field's menu is measured on every page that has a field (#239)."""
    fields = [w for w in win.findChildren(QLineEdit) if w.isVisible() and w.isEnabled() and not _covered(win, w)]
    if not fields:
        return []
    seen["field_menus"] += 1
    menu = fields[0].createStandardContextMenu()
    out = check_menu(f"{where}: field '{fields[0].text()}'", menu, fields[0].mapToGlobal(QPoint()), seen)
    menu.deleteLater()
    return out


def check_menu(where: str, menu: QMenu, at: QPoint, seen: Counter) -> list[str]:
    """Every entry of `menu`, popped up at `at`: an enabled entry reads at 4.5:1 or more, a disabled one is drawn in
    TEXT_DISABLED, so it never looks ready to pick (#239)."""
    menu.popup(at)
    QApplication.processEvents()
    shot = _pixels(menu.grab().toImage())
    out: list[str] = []
    for a in (a for a in menu.actions() if a.isVisible() and not a.isSeparator()):
        seen["menu_entries"] += 1
        region, name = _region(shot, menu, menu, menu.actionGeometry(a)), f"{where} menu entry '{a.text()}'"
        if a.isEnabled():
            out += _check_contrast(region, menu.font(), name, seen)
        elif (measured := _contrast(region) if region is not None else None) and measured[2] != theme.TEXT_DISABLED:
            out.append(f"{name}: disabled, but drawn in {measured[2]}, not {theme.TEXT_DISABLED}")
    menu.hide()
    return out


def _check_targets(where: str, win: MainWindow, title: str, seen: Counter) -> list[str]:
    """Operator targets (sketch size classes T and T+): sidebar entries, header controls, defect and history rows,
    run controls."""
    out: list[str] = []
    page = win.pages[title]
    targets: list[tuple[str, int, int]] = []
    for it in (win.nav.item(i) for i in range(win.nav.count())):
        if it.flags() & Qt.ItemFlag.ItemIsEnabled:
            targets.append((f"sidebar entry '{it.text()}'", win.nav.visualItemRect(it).height(), theme.TARGET_H))
    for w in [win.bm_combo, *win.findChild(QFrame, "header").findChildren(QPushButton)]:
        targets.append((f"header control '{_text(w)}'", w.height(), theme.TARGET_H))
    if title in ("Inspection", "Logs & Export"):
        table = page.table
        targets += [(f"{title} row {r + 1}", table.rowHeight(r), theme.TARGET_H) for r in range(table.rowCount())]
    if title == "Inspection":
        for b in (page.btn_start, page.btn_stop, page.btn_next, page.btn_save):
            targets.append((f"run control '{_text(b)}'", b.height(), theme.RUN_CONTROL_H))
    for what, height, need in targets:
        seen["targets"] += 1
        if height < need:
            out.append(f"{where}: {what} is {height} px tall, needs {need}")
    return out


def test_req_set_004_sizes_and_contrast_on_every_page(
    screens: tuple[AppContext, Path], qtbot: QtBot, qapp: QApplication
) -> None:
    """Every visible widget of every page, for every role: the font, the size and the contrast rules above."""
    assert QFontDatabase.families(), "no fonts loaded, so no text to measure (Windows offscreen: set QT_QPA_FONTDIR)"
    ctx, dataset = screens
    findings: list[str] = []
    seen: Counter = Counter()
    font = render_screens.TEST_FONT if LINUX else ""  # the screenshots' font on Linux, the theme's on Windows
    with render_screens.pinned_rendering(qapp, font):  # grey anti-aliasing: RGB fringes would read as text colours
        win = MainWindow(ctx)
        qtbot.addWidget(win)
        win.resize(1920, 1080)
        win.show()
        qtbot.waitExposed(win)
        for role in ROLES:
            win.set_user(role.lower())
            for title, page in win.pages.items():
                if role not in page.roles:
                    continue
                assert win.navigate(title), title
                render_screens.prepare(win, title, dataset)
                QApplication.processEvents()
                seen["pages"] += 1
                shot = _pixels(win.grab().toImage())
                where = f"{title} ({role})"
                for w in win.findChildren(QWidget):
                    if w.isVisible() and w.width() > 0:
                        findings += _check_widget(where, win, shot, w, seen)
                for w in win.findChildren(QWidget):  # the lists and calendars they open, after the page grab
                    if isinstance(w, QComboBox) and w.isVisible() and w.isEnabled() and not _covered(win, w):
                        findings += check_popup(where, w, seen)
                    elif isinstance(w, QDateEdit) and w.isVisible() and w.calendarPopup() and w.isEnabled():
                        findings += check_calendar(where, w, seen)
                findings += check_field_menu(where, win, seen)
                findings += _check_targets(where, win, title, seen)
        win.close()
    enough = {"pages": 21, "text": 500, "buttons": 100, "contrast": 500, "targets": 200, "image_text": 2}
    enough |= {"popup_rows": 80, "calendar_cells": 300, "calendar_hover": 12}  # 6 calendars: Logs From and To, 3 roles
    enough |= {"calendar_arrows": 24, "field_menus": 11, "menu_entries": 72 + 11 * 7}  # 12 months; 7 entries a field
    assert all(seen[k] >= n for k, n in enough.items()), seen
    assert not findings, f"{len(findings)} findings:\n" + "\n".join(sorted(set(findings)))


def test_req_set_004_theme_token_pairs_read() -> None:
    """Every text colour on every surface the stylesheet composes: 4.5:1, or 3:1 where the text is bold or 40 pt
    (white on the standard's OK green, NG red and accent blue; open with Jay, see the theme's docstring)."""
    normal = {
        (theme.TEXT, s)
        for s in (theme.BG, theme.BG_DEEP, theme.BG_ALT, theme.BG_RAISED, theme.BG_BUTTON, theme.NG_TINT)
    }
    normal |= {(theme.TEXT_MUTED, s) for s in (theme.BG, theme.BG_DEEP, theme.BG_RAISED)}
    normal |= {
        (theme.ON_DARK, theme.BG_SELECTED),
        (theme.ON_LIGHT, theme.WARN_COLOR),
        (theme.ON_LIGHT, theme.INFO_COLOR),
    }
    normal |= {(theme.ON_LIGHT, theme.MAJOR_COLOR), (theme.TEXT, theme.BG_IMAGE), (theme.TEXT_MUTED, theme.BG_IMAGE)}
    normal |= {(theme.TEXT, theme.BG_BUTTON_HOVER), (theme.ON_DARK, theme.BG_BUTTON_HOVER)}  # a calendar's month (#239)
    bold_only = {(theme.ON_DARK, theme.OK_COLOR), (theme.ON_DARK, theme.NG_COLOR), (theme.ON_DARK, theme.ACCENT)}
    low = {(t, s): round(_ratio(t, s), 2) for t, s in normal if _ratio(t, s) < MIN_RATIO}
    assert not low, low
    low = {(t, s): round(_ratio(t, s), 2) for t, s in bold_only if _ratio(t, s) < LARGE_RATIO}
    assert not low, low
    for fill in (theme.WARN_COLOR, theme.INFO_COLOR, theme.MAJOR_COLOR):
        assert theme.on_color(fill) == theme.ON_LIGHT, fill
