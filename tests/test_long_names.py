"""#251: a name of 240 characters never widens the window, which fits a 1920 px screen on CI's fonts: AI Model Test's
folder line and its note, a file name with no _ or - on Compare, and Inspection's summary line. Each wraps where it
may, and a line that has to cut a name keeps the whole text in its tooltip."""

from __future__ import annotations

from collections.abc import Callable

import pytest
from PySide6.QtWidgets import QApplication, QLabel
from pytestqt.qtbot import QtBot

from aoi.core.services import AppContext
from aoi.ui.main_window import MainWindow
from aoi.ui.pages.base import ZWSP, breakable
from tests.conftest import wrapped
from tests.test_req_done_in_v01 import _window

LONG = "x" * 240  # no space, _ or -: before #251 one word, as wide as it is long


def _folder(win: MainWindow) -> QLabel:
    label = win.pages["AI Model Test"].folder_label
    label.setText(f"C:/boards/{LONG}")
    return label


def _note(win: MainWindow) -> QLabel:
    label = win.pages["AI Model Test"].run_note
    label.setText(f"These results were judged by AI model v1.0; {LONG} now uses AI model v1.1.")
    label.show()
    return label


def _compare(win: MainWindow) -> QLabel:
    label = win.pages["Compare"].test_label
    label.setText(f"Test board: {breakable(LONG + '.png')}")
    return label


def _summary(win: MainWindow) -> QLabel:
    label = win.pages["Inspection"].summary
    label.setText(f"{LONG}.png  ·  not inspected")
    return label


CASES: dict[str, tuple[str, Callable[[MainWindow], QLabel]]] = {
    "folder": ("AI Model Test", _folder),
    "note": ("AI Model Test", _note),
    "compare": ("Compare", _compare),
    "summary": ("Inspection", _summary),
}


@pytest.mark.parametrize("case", list(CASES))
def test_req_set_004_a_long_name_never_widens_the_window(qtbot: QtBot, trained_ctx: AppContext, case: str) -> None:
    page, fill = CASES[case]
    win = _window(qtbot, trained_ctx)
    win.navigate(page)
    QApplication.processEvents()
    before = win.minimumSizeHint().width()  # 1886 px on CI's fonts (#351)
    label = fill(win)
    QApplication.processEvents()
    after = win.minimumSizeHint().width()
    assert after <= before, (case, before, after)  # the name adds nothing: the window fits wherever it fitted
    if label.toolTip():  # a WrappedLine: the whole text, for a line that cuts it
        assert label.toolTip() == label.text()


def test_req_set_004_breakable_breaks_a_long_run() -> None:
    """After each _ and -, and after 24 characters with neither nor a space; short names as before (#245)."""
    assert breakable("board_0042.png") == "board_\u200b0042.png"
    shown = breakable(LONG + ".png")
    assert shown.replace(ZWSP, "") == LONG + ".png" and max(len(w) for w in shown.split(ZWSP)) <= 24
    assert shown == wrapped(LONG + ".png")
