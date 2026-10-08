"""Each test starts with no key held (tests/conftest.py, _no_key_held). QTest's click with Ctrl leaves Qt reading Ctrl
as held until the next key event, and a later test's selectRow() then added a row to the selection instead of
selecting it alone."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import QLineEdit
from pytestqt.qtbot import QtBot

from tests.conftest import let_go_of_keys


def test_a_ctrl_left_held_by_a_click_is_let_go_of(qtbot: QtBot) -> None:
    """The cause, as Qt has it, and the step each test starts with that undoes it."""
    edit = QLineEdit()
    qtbot.addWidget(edit)
    edit.show()
    qtbot.waitExposed(edit)
    assert QGuiApplication.keyboardModifiers() == Qt.KeyboardModifier.NoModifier
    qtbot.keyClick(edit, Qt.Key.Key_N, Qt.KeyboardModifier.ControlModifier)
    assert QGuiApplication.keyboardModifiers() == Qt.KeyboardModifier.ControlModifier  # read as held after the click
    let_go_of_keys()
    assert QGuiApplication.keyboardModifiers() == Qt.KeyboardModifier.NoModifier
