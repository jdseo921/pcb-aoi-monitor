"""REQ-SET-006 and REQ-SET-028: the Korean UI. Every string has a finished translation that keeps its placeholders,
the compiled file the app loads is the one the translation source gives, Settings' language shows from the next
start, and no button, tab, column header or one-line label is cut in Korean where the window is 1366 x 768. A native
speaker has not reviewed the strings yet; the register says so."""

from __future__ import annotations

import re
import subprocess
import xml.etree.ElementTree as ET
from collections.abc import Iterator
from pathlib import Path

import pytest
from PySide6.QtCore import QCoreApplication, Qt
from PySide6.QtGui import QFontMetrics
from PySide6.QtWidgets import QAbstractButton, QApplication, QHeaderView, QLabel, QStyle, QStyleOptionButton, QTabBar
from pytestqt.qtbot import QtBot

from aoi.core.services import AppContext
from aoi.ui import language
from aoi.ui.main_window import MainWindow
from aoi.ui.sign_in_dialog import SignInDialog
from tests.test_first_board_model_store import shell
from tools.update_translations import TS_FILE, qt_tool, release

PLACEHOLDER = re.compile(r"\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}")
PAGES = ("Home", "Inspection", "Compare", "Training", "AI Model Test", "Recipe Editor", "Logs & Export", "Settings")


def messages() -> list[tuple[str, str, ET.Element]]:
    out = []
    for context in ET.parse(TS_FILE).getroot().findall("context"):
        for m in context.findall("message"):
            t = m.find("translation")
            assert t is not None
            out.append((str(context.findtext("name")), str(m.findtext("source")), t))
    return out


def test_req_set_028_every_string_has_a_finished_translation_that_keeps_its_placeholders() -> None:
    found = messages()
    assert len(found) > 2000
    for context, source, t in found:
        text = t.text or ""
        assert t.get("type") != "unfinished" and text.strip(), (context, source)
        assert sorted(PLACEHOLDER.findall(source)) == sorted(PLACEHOLDER.findall(text)), (context, source, text)
        lead, tail = len(source) - len(source.lstrip()), len(source) - len(source.rstrip())
        assert (len(text) - len(text.lstrip()), len(text) - len(text.rstrip())) == (lead, tail), (context, source)
        for mark in ("<b>", "</b>", "<br>", "›", "→"):
            assert source.count(mark) == text.count(mark), (context, source, mark)
        assert ("  " in source.strip()) == ("  " in text.strip()), (context, source)  # "Train  Enter": the key's gap


def test_req_set_028_the_compiled_file_is_the_one_the_source_gives(tmp_path: Path) -> None:
    built = release(TS_FILE, tmp_path / "fresh.qm")
    committed = language.qm_file("ko")
    assert committed.is_file(), "python tools/update_translations.py writes it"
    assert committed.read_bytes() == built.read_bytes(), "aoi_ko.qm is stale: python tools/update_translations.py"
    assert subprocess.run([qt_tool("pyside6-lrelease"), "-version"], capture_output=True).returncode == 0


@pytest.fixture
def korean(qapp: QApplication) -> Iterator[None]:
    assert language.install(qapp, "ko")
    yield
    assert language.install(qapp, "en")


def test_req_set_006_korean_shows_from_the_start_and_english_comes_back(qapp: QApplication) -> None:
    said = QCoreApplication.translate
    assert said("Page", "Inspection") == "Inspection"
    assert language.install(qapp, "ko")
    assert (said("Page", "Inspection"), said("Role", "Operator")) == ("검사", "작업자")
    assert said("InspectionPage", "Shift Check") == "교대 점검"
    assert language.install(qapp, "ko")  # a second call replaces the first: one translator, not two
    assert language.install(qapp, "en") and said("Page", "Inspection") == "Inspection"
    assert not language.install(qapp, "xx") and said("Page", "Inspection") == "Inspection"  # no such file: English


def cut(win: MainWindow) -> list[str]:
    """The texts of `win` that need more width than their widget gives them; data in tables is left out."""
    out = []
    for w in win.findChildren(QAbstractButton) + win.findChildren(QLabel) + win.findChildren(QTabBar):
        if not w.isVisible() or w.width() < 2:
            continue
        fm = QFontMetrics(w.font())
        if isinstance(w, QTabBar):
            out += [w.tabText(i) for i in range(w.count()) if fm.horizontalAdvance(w.tabText(i)) > w.tabRect(i).width()]
        elif isinstance(w, QLabel):
            lines = w.text().split("\n")
            if w.text() and not w.wordWrap() and "<" not in w.text() and w.pixmap().isNull():
                if max(fm.horizontalAdvance(line) for line in lines) > w.contentsRect().width() + 1:
                    out.append(w.text())
        elif w.text() and type(w).__name__ == "QPushButton":
            opt = QStyleOptionButton()
            opt.initFrom(w)
            room = w.style().subElementRect(QStyle.SubElement.SE_PushButtonContents, opt, w).width()
            if fm.horizontalAdvance(w.text().replace("&&", "&")) > room + 1:
                out.append(w.text())
    for h in win.findChildren(QHeaderView):
        if h.isVisible() and h.orientation() == Qt.Orientation.Horizontal and h.model() is not None:
            fm = QFontMetrics(h.font())
            for i in range(h.count()):
                text = str(h.model().headerData(i, Qt.Orientation.Horizontal) or "")
                if not h.isSectionHidden(i) and fm.horizontalAdvance(text) > h.sectionSize(i) - 6:
                    out.append(text)
    return out


@pytest.mark.parametrize("role", ["admin", "operator"])
def test_req_set_006_no_text_is_cut_in_korean_at_1366_by_768(
    qtbot: QtBot, ctx: AppContext, korean: None, role: str
) -> None:
    ctx.ensure_board_model("TBOX-A1")
    win = shell(qtbot, ctx, "admin")
    win.resize(1366, 768)
    win.select_board_model("TBOX-A1")
    win.set_user(role)
    assert win.pages["Inspection"].btn_load.text() == "이미지 불러오기…", "the window was not built in Korean"
    for page in PAGES:
        if page in win.pages and win.may_open(page) if hasattr(win, "may_open") else True:
            win.navigate(page)
            qtbot.wait(50)
            assert cut(win) == [], page


def test_req_set_006_the_sign_in_dialog_grows_to_hold_its_hint_whole(
    qtbot: QtBot, ctx: AppContext, korean: None
) -> None:
    box = SignInDialog(shell(qtbot, ctx, "admin"))
    qtbot.addWidget(box)
    box.show()
    qtbot.waitExposed(box)
    for i in range(box.user.count()):  # each user's hint, the longest two lines where the first was one
        box.user.setCurrentIndex(i)
        qtbot.wait(20)
        if box.hint.isVisible():
            fm = QFontMetrics(box.hint.font())
            need = fm.boundingRect(0, 0, box.hint.width(), 10000, int(Qt.TextFlag.TextWordWrap), box.hint.text())
            assert need.height() <= box.hint.height() + 2, box.hint.text()
