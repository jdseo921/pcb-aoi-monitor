"""Sizes and contrast of every page for every role, measured on the rendered widgets (REQ-SET-004; S21b).

Engineering standard, "Sizes" (MUST): text at least 14 pt, buttons at least 120×40 px, operator touch targets at
least 48 px tall, text contrast at least 4.5:1. The walk opens the shell at 1920×1080 on the synthetic workspace, puts
every page in the state the screenshots show (`tools/render_screens.py`) and, for every role that may open it, reads
each visible widget: its resolved font, its size, whether its text fits, and the colours of its pixels in the window
grab. Contrast is the WCAG 2.1 ratio between a widget's background (its most common colour) and its text (the colour
farthest from the background in luminance); bold or 18 pt text may read at 3:1 (WCAG 1.4.3, large text) and a disabled
control is exempt, but a disabled button must show the disabled fill, so it never looks ready to press. A progress bar's
percentage is measured in its centred text, and the prepared states hold a selected row (Inspection) and a bar past
half (Training). Text drawn on an image (QGraphics items) is measured against the image area's background. The walk
runs on Linux and Windows: sizes and colours do not depend on the font file.
"""

from __future__ import annotations

import sys
from collections import Counter
from pathlib import Path

import numpy as np
from PySide6.QtCore import QRect, Qt
from PySide6.QtGui import QColor, QFont, QFontDatabase, QFontInfo, QImage
from PySide6.QtWidgets import (
    QAbstractButton,
    QAbstractItemView,
    QAbstractSpinBox,
    QApplication,
    QComboBox,
    QFrame,
    QGraphicsSimpleTextItem,
    QGraphicsView,
    QGroupBox,
    QHeaderView,
    QLabel,
    QLineEdit,
    QListWidget,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QStatusBar,
    QTabBar,
    QTableWidget,
    QTextEdit,
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
        for it in items:
            if it is not None and it.text() and it.flags() & Qt.ItemFlag.ItemIsEnabled:
                rect = w.visualItemRect(it) & w.viewport().rect()
                font = it.font() if it.data(Qt.ItemDataRole.FontRole) is not None else w.font()
                out += _check_contrast(_region(shot, win, w.viewport(), rect), font, f"{name} item '{it.text()}'", seen)
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
                findings += _check_targets(where, win, title, seen)
        win.close()
    enough = {"pages": 21, "text": 500, "buttons": 100, "contrast": 500, "targets": 200, "image_text": 2}
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
    bold_only = {(theme.ON_DARK, theme.OK_COLOR), (theme.ON_DARK, theme.NG_COLOR), (theme.ON_DARK, theme.ACCENT)}
    low = {(t, s): round(_ratio(t, s), 2) for t, s in normal if _ratio(t, s) < MIN_RATIO}
    assert not low, low
    low = {(t, s): round(_ratio(t, s), 2) for t, s in bold_only if _ratio(t, s) < LARGE_RATIO}
    assert not low, low
    for fill in (theme.WARN_COLOR, theme.INFO_COLOR, theme.MAJOR_COLOR):
        assert theme.on_color(fill) == theme.ON_LIGHT, fill
