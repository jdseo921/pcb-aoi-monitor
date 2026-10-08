"""Sizes and contrast of every page for every role, measured on the rendered widgets (REQ-SET-004; S21b).

Engineering standard, "Sizes" (MUST): text at least 14 pt, buttons at least 120×40 px, operator touch targets at
least 48 px tall, text contrast at least 4.5:1. The walk opens the shell at 1920×1080 on the synthetic workspace, puts
every page in the state the screenshots show (`tools/render_screens.py`) and, for every role that may open it, reads
each visible widget: its resolved font, its size, whether its text fits, and the colours of its pixels in the window
grab. The operator targets are named (the Inspection source bar among them), and every visible control marked with
size class T or T+ is held to 48 or 56 px too (#240). Contrast is the WCAG 2.1 ratio between a widget's background
(its most common colour) and its text (the colour farthest from the background in luminance); a label is also measured
line by line, and each colour its rich text sets at that text's own size, on the text's own background where it sets
one (a chip), so a second colour beside a stronger one is read too (#240). Bold or 18 pt text may read at 3:1 (WCAG
1.4.3, large text) and a disabled control is exempt, but a disabled button must show the disabled fill, so it never
looks ready to press. A progress bar's percentage is measured in its centred text, and the prepared states hold a
selected row (Inspection) and a bar past half (Training). Text drawn on an image (QGraphics items) is measured in its
own colour against the pixels under its glyphs, found by drawing it in two far-apart colours, so text in its ground's
own colour is found too: its backing, or the board where none is drawn; the 10th percentile of their ratios decides
(#240). Every list item with text is measured, the sidebar's section headings too; only a sidebar entry of a page the
role may not open is exempt, as a disabled control, and it must be drawn in the disabled grey. The walk opens every
drop-down list and every date field's calendar on the page, and one text field's right-click menu, which are windows of
their own and not in the page grab, and measures each entry, day and weekday name, the month and year (at rest and under
the pointer) and the month list; the calendar's previous and next month arrows, a control's graphic, need 3:1 (WCAG
1.4.11) (#239). The walk runs on Linux and Windows: sizes and colours do not depend on the font file.
"""

from __future__ import annotations

import re
import sys
from collections import Counter
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any
from unittest import mock

import numpy as np
from PySide6.QtCore import QPoint, QRect, Qt
from PySide6.QtGui import (
    QBrush,
    QColor,
    QFont,
    QFontDatabase,
    QFontInfo,
    QFontMetrics,
    QImage,
    QPalette,
    QTextDocument,
    QTextFormat,
)
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
from aoi.ui.pages.base import ROLES, size_class
from aoi.ui.pages.model_test import MetricTile
from aoi.ui.widgets.image_view import ImageView
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


def _rgb(colour: str) -> list[int]:
    return [int(colour[i : i + 2], 16) for i in (1, 3, 5)]


def _ratio(a: str, b: str) -> float:
    lum = _luminance(np.array([_rgb(h) for h in (a, b)]))
    return float((lum.max() + 0.05) / (lum.min() + 0.05))


def _near(a: str, b: str, by: int) -> bool:
    """Colour `a` lies within `by` of colour `b` in every channel."""
    return max(abs(x - y) for x, y in zip(_rgb(a), _rgb(b), strict=True)) <= by


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
        out += _check_contrast(region := _region(shot, win, w), w.font(), name, seen)
        if isinstance(w, QLabel) and region is not None:
            out += _check_label_colours(w, region, name, seen)
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
        for item in w.scene().items():
            if isinstance(item, QGraphicsSimpleTextItem) and item.isVisible():
                label = f"{where}: text on the image '{item.text()[:40]}'"
                if item.font().pointSizeF() < theme.FONT_PT:
                    out.append(f"{label}: {item.font().pointSizeF():.1f} pt")
                if (measured := _behind_glyphs(win, w, item)) is not None:  # counted only once its ground is read
                    seen["image_text"] += 1
                    seen["contrast"] += 1
                    ratio, colour, ground = measured
                    if (need := _needs(ratio, item.font())) is not None:
                        out.append(f"{label}: {colour} on {ground} reads at {ratio:.1f}:1, needs {need}:1")
    return out


def _behind_glyphs(win: QWidget, view: QGraphicsView, item: QGraphicsSimpleTextItem) -> tuple[float, str, str] | None:
    """(ratio, text, ground) of a text item drawn on an image, read under its glyphs, not on the view's background: a
    defect label over a bright board reads only on its backing (#240). Its box is grabbed with its brush in two
    far-apart colours (BG_IMAGE, TEXT) and with no brush: the pixels that differ between the first two are its glyphs,
    whatever its own colour, so text drawn in its ground's own colour (a hint in BG_IMAGE) is found too, and the third
    grab holds the ground behind them: its backing (a child item, which still draws) or the board. Each glyph pixel's
    ground gives a ratio with the item's own colour; the 10th percentile decides, so a label partly over a bright part
    of a board is read there, and a few pixels of a highlight do not decide it. None when no glyph of it is in view."""
    port = view.viewport()
    box = item.deviceTransform(view.viewportTransform()).mapRect(item.boundingRect()).toAlignedRect() & port.rect()
    if box.isEmpty():
        return None
    rect, brush, grabs = QRect(port.mapTo(win, box.topLeft()), box.size()), item.brush(), []
    for b in (QBrush(QColor(theme.BG_IMAGE)), QBrush(QColor(theme.TEXT)), QBrush(Qt.BrushStyle.NoBrush)):
        item.setBrush(b)
        QApplication.processEvents()
        grabs.append(_pixels(win.grab(rect).toImage()))
    item.setBrush(brush)
    QApplication.processEvents()
    ground = grabs[2][np.any(grabs[0] != grabs[1], axis=2)]
    if not len(ground):
        return None
    colour = QColor(brush.color()).name()
    lum, text = _luminance(ground), float(_luminance(np.array(_rgb(colour))))
    ratios = (np.maximum(lum, text) + 0.05) / (np.minimum(lum, text) + 0.05)
    k = int(np.argsort(ratios, kind="stable")[(len(ratios) - 1) // 10])
    return float(ratios[k]), colour, "#" + "".join(f"{int(v):02x}" for v in ground[k])


def _check_label_colours(label: QLabel, region: np.ndarray, name: str, seen: Counter) -> list[str]:
    """Every text colour of a label, not only the one farthest from its background (#240). Each colour its rich text
    sets is held, against the label's background or the fragment's own (a chip's), to what its own size and weight
    need (a metric tile's caption, a Home card's number), and so is the label's own colour on a chip that sets only its
    background; and each text line is measured on its own, so a second colour that comes from a stylesheet or the
    palette is read too when it has a line of its own. A line drawn in a colour the rich text sets is left to that
    colour's check, which knows its size."""
    out: list[str] = []
    bg = str(_fill(region))  # the background _contrast takes: the most common colour
    inline: set[str] = set()
    if "<" in label.text():
        doc = QTextDocument()
        doc.setHtml(label.text())
        block = doc.begin()
        while block.isValid():
            it = block.begin()
            while not it.atEnd():
                fmt, text = it.fragment().charFormat(), it.fragment().text().strip()
                it += 1
                own = fmt.hasProperty(QTextFormat.Property.ForegroundBrush)
                chip = fmt.hasProperty(QTextFormat.Property.BackgroundBrush)  # text on its own colour
                if text and (own or chip):  # a chip that sets no text colour shows the label's own
                    brush = fmt.foreground() if own else label.palette().brush(QPalette.ColorRole.WindowText)
                    colour, font = brush.color().name(), fmt.font().resolve(label.font())
                    if own:
                        inline.add(colour)
                    seen["contrast"] += 1
                    ground = fmt.background().color().name() if chip else bg
                    if need := _needs(ratio := _ratio(colour, ground), font):
                        out.append(
                            f"{name} text '{text[:40]}': {colour} on {ground} reads at {ratio:.1f}:1, needs {need}:1"
                        )
            block = block.next()
    lines = _lines(region, QFontMetrics(label.font()).xHeight())
    for i, line in enumerate(lines if len(lines) > 1 else []):
        if (measured := _contrast(line)) is not None and measured[2] not in inline:
            out += _check_contrast(line, label.font(), f"{name} line {i + 1}", seen)
    return out


def _lines(region: np.ndarray, shortest: int) -> list[np.ndarray]:
    """The text lines of a label's region, full width: runs of rows that hold a pixel 0.02 or more from the background
    in luminance. The RADIUS_L columns at each side are not read for that, where a rounded corner shows the surface
    behind the label. A run under `shortest` rows (the label's x-height: an i's dot, a dash) is no line of letters and
    joins its neighbour across the smaller gap."""
    inner = region[:, theme.RADIUS_L : -theme.RADIUS_L]
    if inner.size == 0:
        return []
    off = np.abs(_luminance(inner) - _luminance(np.array(_rgb(str(_fill(inner)))))) >= 0.02
    rows = np.flatnonzero(off.any(axis=1))
    runs = [[int(r[0]), int(r[-1])] for r in np.split(rows, np.flatnonzero(np.diff(rows) > 1) + 1) if r.size]
    while len(runs) > 1:
        i = min(range(len(runs)), key=lambda k: runs[k][1] - runs[k][0])
        if runs[i][1] - runs[i][0] + 1 >= shortest:
            break
        above = runs[i][0] - runs[i - 1][1] if i > 0 else None
        below = runs[i + 1][0] - runs[i][1] if i + 1 < len(runs) else None
        j = i - 1 if below is None or (above is not None and above <= below) else i + 1
        a, b = min(i, j), max(i, j)
        runs[a : b + 1] = [[runs[a][0], runs[b][1]]]
    return [region[a : b + 1] for a, b in runs]


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
    """Operator targets (sketch size classes T, 48 px, and T+, 56 px): sidebar entries, header controls, defect and
    history rows, the Inspection source bar (Load Images…, Load Folder…, View) and run controls, each named, so one
    whose size class a change drops is still measured, and held to its size class where that asks more; then every
    visible widget marked T or T+, so one marked later is measured before anyone names it, whatever its type: the
    stylesheet sizes only buttons and drop-downs (#240)."""
    out: list[str] = []
    page: Any = win.pages[title]
    targets: list[tuple[str, int, int]] = []
    for it in (win.nav.item(i) for i in range(win.nav.count())):
        if it.flags() & Qt.ItemFlag.ItemIsEnabled:
            targets.append((f"sidebar entry '{it.text()}'", win.nav.visualItemRect(it).height(), theme.TARGET_H))
    if title in ("Inspection", "Logs & Export"):
        table = page.table
        targets += [(f"{title} row {r + 1}", table.rowHeight(r), theme.TARGET_H) for r in range(table.rowCount())]
    named = [
        ("header control", w, theme.TARGET_H)
        for w in [win.bm_combo, *win.findChild(QFrame, "header").findChildren(QPushButton)]
    ]
    if title == "Inspection":
        named += [("source bar control", w, theme.TARGET_H) for w in (page.btn_load, page.btn_folder, page.view_combo)]
        named += [
            ("run control", b, theme.RUN_CONTROL_H)
            for b in (page.btn_start, page.btn_stop, page.btn_next, page.btn_save)
        ]
    need = {"T": theme.TARGET_H, "T+": theme.RUN_CONTROL_H}
    named = [(what, w, max(h, need.get(str(w.property("sizeClass")), 0))) for what, w, h in named]
    for w in win.findChildren(QWidget):
        if w.isVisible() and (cls := w.property("sizeClass")) in need and all(w is not n for _, n, _ in named):
            named.append((f"{type(w).__name__} of size class {cls}", w, need[cls]))
    targets += [(f"{what} '{_text(w)}'", w.height(), h) for what, w, h in named]
    for what, height, h in targets:
        seen["targets"] += 1
        if height < h:
            out.append(f"{where}: {what} is {height} px tall, needs {h}")
    return out


@contextmanager
def _shell(ctx: AppContext, qtbot: QtBot, qapp: QApplication) -> Iterator[MainWindow]:
    """The shell at 1920×1080 in the screenshots' font on Linux, the theme's on Windows, with grey anti-aliasing (RGB
    fringes would read as text colours). Closing it closes its workspace, which the module's next test opens again, so
    that close is held off here and the `screens` fixture closes the workspace."""
    with render_screens.pinned_rendering(qapp, render_screens.TEST_FONT if LINUX else ""):
        win = MainWindow(ctx)
        win.resize(1920, 1080)
        win.show()
        qtbot.waitExposed(win)
        try:
            yield win
        finally:
            with mock.patch.object(ctx, "close"):
                win.close()
            win.deleteLater()


def _show(win: MainWindow, title: str, dataset: Path) -> None:
    """`title` in the state the screenshots show."""
    assert win.navigate(title), title
    render_screens.prepare(win, title, dataset)
    QApplication.processEvents()


def test_req_set_004_sizes_and_contrast_on_every_page(
    screens: tuple[AppContext, Path], qtbot: QtBot, qapp: QApplication
) -> None:
    """Every visible widget of every page, for every role: the font, the size and the contrast rules above."""
    assert QFontDatabase.families(), "no fonts loaded, so no text to measure (Windows offscreen: set QT_QPA_FONTDIR)"
    ctx, dataset = screens
    findings: list[str] = []
    seen: Counter = Counter()
    with _shell(ctx, qtbot, qapp) as win:
        for role in ROLES:
            win.set_user(role.lower())
            for title, page in win.pages.items():
                if role not in page.roles:
                    continue
                _show(win, title, dataset)
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
    enough = {"pages": 21, "text": 500, "buttons": 100, "contrast": 500, "targets": 200, "image_text": 2}
    enough |= {"popup_rows": 80, "calendar_cells": 300, "calendar_hover": 12}  # 6 calendars: Logs From and To, 3 roles
    enough |= {"calendar_arrows": 24, "field_menus": 11, "menu_entries": 72 + 11 * 7}  # 12 months; 7 entries a field
    assert all(seen[k] >= n for k, n in enough.items()), seen
    assert not findings, f"{len(findings)} findings:\n" + "\n".join(sorted(set(findings)))


def test_req_set_004_theme_token_pairs_read() -> None:
    """Every text colour on every surface the stylesheet composes: 4.5:1, or 3:1 where the text is bold or 40 pt
    (white on the standard's OK green, NG red and accent blue, accent blue on a card; open with Jay, see the theme's
    docstring)."""
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
    bold_only |= {(theme.ACCENT, theme.BG_RAISED)}  # the 22 pt bold number on a Home card (#240)
    low = {(t, s): round(_ratio(t, s), 2) for t, s in normal if _ratio(t, s) < MIN_RATIO}
    assert not low, low
    low = {(t, s): round(_ratio(t, s), 2) for t, s in bold_only if _ratio(t, s) < LARGE_RATIO}
    assert not low, low
    for fill in (theme.WARN_COLOR, theme.INFO_COLOR, theme.MAJOR_COLOR):
        assert theme.on_color(fill) == theme.ON_LIGHT, fill


def test_req_set_004_the_walk_holds_every_size_class_t_control_to_48_px(
    screens: tuple[AppContext, Path], qtbot: QtBot, qapp: QApplication
) -> None:
    """Load Folder with its size class cleared at run time, as a change that drops its size_class() leaves it (42 px),
    a field marked T that no list names, and the header's Board model marked T+ (56 px) where the list names it at 48:
    the walk's target check reports all three. Before #240 it measured a fixed list without the Inspection source bar
    and never read sizeClass, so it reported none."""
    ctx, dataset = screens
    with _shell(ctx, qtbot, qapp) as win:
        win.set_user("engineer")
        _show(win, "Inspection", dataset)
        page: Any = win.pages["Inspection"]
        assert not _check_targets("Inspection", win, "Inspection", Counter())
        folder = page.btn_folder
        folder.setProperty("sizeClass", None)
        folder.style().unpolish(folder)
        folder.style().polish(folder)
        field = size_class(QLineEdit("a field marked T"), "T")  # the stylesheet sizes no field to 48 px
        page.root.addWidget(field)
        win.bm_combo.setProperty("sizeClass", "T+")  # not polished again: it stays at the 48 px the list names
        QApplication.processEvents()
        assert folder.height() < theme.TARGET_H and field.height() < theme.TARGET_H, (folder.height(), field.height())
        found = _check_targets("Inspection", win, "Inspection", Counter())
    assert any("Load Folder" in f for f in found) and any("a field marked T" in f for f in found), found
    assert any(f.startswith("Inspection: header control") and f.endswith("needs 56") for f in found), found


def test_req_set_004_the_walk_measures_every_text_colour_of_a_label(
    screens: tuple[AppContext, Path], qtbot: QtBot, qapp: QApplication
) -> None:
    """A metric tile whose caption is drawn in LINE_STRONG (1.8:1 on the tile), inline or through the label's own
    stylesheet, is reported, and so is a value drawn as a chip, TEXT on its own WARN_COLOR background (1.2:1), whether
    the chip sets TEXT or shows the tile's own colour; the real tiles and the Home card headings (an ACCENT number
    beside a TEXT name) are not. Before #240 the walk measured only the colour farthest from the background, the value's
    TEXT at 11:1: no finding."""
    ctx, dataset = screens
    found: dict[str, list[str]] = {}
    with _shell(ctx, qtbot, qapp) as win:
        win.set_user("engineer")
        _show(win, "Home", dataset)
        headings = [w for w in win.pages["Home"].findChildren(QLabel) if w.isVisible() and theme.ACCENT in w.text()]
        shot = _pixels(win.grab().toImage())
        assert len(headings) == 6 and not [f for w in headings for f in _check_widget("Home", win, shot, w, Counter())]
        _show(win, "AI Model Test", dataset)
        tile = win.pages["AI Model Test"].findChildren(MetricTile)[0]
        tile.set(0.5)
        QApplication.processEvents()
        assert not _check_widget("tile", win, _pixels(win.grab().toImage()), tile, Counter())
        tile.setText(tile.text().replace(theme.TEXT_MUTED, theme.LINE_STRONG))  # MetricTile.set with another caption
        QApplication.processEvents()
        found["inline"] = _check_widget("tile", win, _pixels(win.grab().toImage()), tile, Counter())
        tile.setText(f"<div>{tile.name}</div><div style='font-size:26pt;color:{theme.TEXT}'>50.0%</div>")
        tile.setStyleSheet(f"color: {theme.LINE_STRONG};")  # the caption's colour from a stylesheet, not the HTML
        QApplication.processEvents()
        found["stylesheet"] = _check_widget("tile", win, _pixels(win.grab().toImage()), tile, Counter())
        tile.setStyleSheet("")
        for how, colour in (("chip", f";color:{theme.TEXT}"), ("chip, background only", "")):  # the tile's own: TEXT
            chip = f"background-color:{theme.WARN_COLOR}{colour}"  # the fragment's own ground, not the tile's
            tile.setText(f"<div>{tile.name}</div><div style='font-size:26pt'><span style='{chip}'>50.0%</span></div>")
            QApplication.processEvents()
            found[how] = _check_widget("tile", win, _pixels(win.grab().toImage()), tile, Counter())
    expected = {how: f"{theme.LINE_STRONG} on {theme.BG_RAISED} reads at 1.8:1" for how in ("inline", "stylesheet")}
    expected["chip"] = expected["chip, background only"] = f"{theme.TEXT} on {theme.WARN_COLOR} reads at 1.2:1"
    missed = [how for how, findings in found.items() if not any(expected[how] in f for f in findings)]
    assert not missed, found


def test_req_set_004_text_on_an_image_is_measured_against_the_pixels_behind_it(
    qtbot: QtBot, qapp: QApplication
) -> None:
    """A defect label on a bright board (WARN_COLOR, on which TEXT reads at 1.2:1): one flat colour, running 14 px past
    the image's right edge as a label near a board's edge does, and a camera-like board (WARN_COLOR +-12 per channel),
    fully on it and a quarter over the view's dark margin past its edge. On each, the walk passes the label on its dark
    backing and, once the backing is clear, reports it at the board's colour under its glyphs. Before #240 the walk
    compared the label's colour with the view's own background (BG_IMAGE, 15.4:1), so it reported nothing either way.
    On the noisy board no pixel value is common, so the colour most of the label's box shows is the text's own or the
    margin's: a measure of that passes the label a quarter over the margin. The view's "No image" hint drawn in its
    ground's own colour (BG_IMAGE) is reported at 1.0:1: the glyphs are found whatever colour the text is drawn in."""
    bright = QColor(theme.WARN_COLOR)
    flat = np.full((600, 400, 3), (bright.blue(), bright.green(), bright.red()), np.int16)  # BGR
    noisy = flat + np.random.default_rng(240).integers(-12, 13, flat.shape)
    boards = {"flat, past the edge": (flat, 200), "noisy": (noisy, 100), "noisy, over the margin": (noisy, 250)}
    found: dict[tuple[str, bool], list[str]] = {}
    with render_screens.pinned_rendering(qapp, render_screens.TEST_FONT if LINUX else ""):
        win = QWidget()
        qtbot.addWidget(win)
        win.resize(800, 600)
        view = ImageView(win)
        view.resize(800, 600)
        win.show()
        qtbot.waitExposed(win)
        hint = next(i for i in view.scene().items() if isinstance(i, QGraphicsSimpleTextItem) and i.isVisible())
        hint.setBrush(QBrush(QColor(theme.BG_IMAGE)))  # no pixel of the box changes when this brush is cleared
        QApplication.processEvents()
        unseen = _check_widget("image", win, _pixels(win.grab().toImage()), view, Counter())
        for board, (image, x) in boards.items():
            view.set_image(np.clip(image, 0, 255).astype(np.uint8))  # fitted to the shown view: 400 px, centred
            view.add_box(x, 200, 60, 40, theme.NG_COLOR, "1 missing_component")
            label = next(i for i in view.scene().items() if isinstance(i, QGraphicsSimpleTextItem) and i.isVisible())
            for backing in (True, False):
                if not backing:  # the backing is the label's child, drawn behind it (image_view.py)
                    label.childItems()[0].setBrush(QBrush(Qt.BrushStyle.NoBrush))
                QApplication.processEvents()
                seen: Counter = Counter()
                found[board, backing] = _check_widget("image", win, _pixels(win.grab().toImage()), view, seen)
                assert seen["image_text"] == 1, (board, seen)
    assert not [f for (_, backing), findings in found.items() if backing for f in findings], found
    read = {b: [re.search(r"(#\w{6}) on (#\w{6}) reads at ([\d.]+):1", f) for f in found[b, False]] for b in boards}
    missed = {  # each board needs TEXT reported on a board pixel (WARN_COLOR +-12), well under 4.5:1
        b: found[b, False]
        for b, ms in read.items()
        if not [m for m in ms if m and m[1] == theme.TEXT and _near(m[2], theme.WARN_COLOR, 12) and float(m[3]) < 1.5]
    }
    assert not missed, missed
    assert any(f"on {theme.WARN_COLOR} reads at 1.2:1" in f for f in found["flat, past the edge", False]), found
    assert [f for f in unseen if f"'No image': {theme.BG_IMAGE} on {theme.BG_IMAGE} reads at 1.0:1" in f], unseen
