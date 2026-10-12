"""tests/dialog_watch.py, by which the demo-script tests and tests/startup_worker.py fail on any dialog (A8 of the
2026-10 business-readiness brief, F14): it lists a question, the app's own error dialog and a file picker, each as it
waits to be answered, and closes each as Esc does, so the code that showed it goes on."""

from __future__ import annotations

import pytest
from PySide6.QtWidgets import QFileDialog, QMessageBox
from pytestqt.qtbot import QtBot

from aoi.core.services import ErrorReport
from aoi.errors import AoiError
from aoi.ui.errors import dialog_text, show_error
from tests.dialog_watch import watched


def test_req_set_007_the_dialog_watch_lists_and_closes_every_dialog_shown(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A question, an error and a picker shown one after another in the watch: each listed by its kind and title in
    the order shown, and each closed without its yes, so the code after it runs."""
    monkeypatch.undo()  # the real dialogs, not the stand-ins tests/conftest.py puts in every test's place
    report = ErrorReport.of(AoiError("AOI-SET-019", path="C:/AOI_Workspace"))
    with watched() as shown:
        asked = QMessageBox.question(None, "Stop the running work?", "Stop it?")
        show_error(None, report)
        picked = QFileDialog.getSaveFileName(None, "Export CSV")
    title, _text = dialog_text(report)
    assert shown == ["QMessageBox: Stop the running work?", f"ErrorBox: {title}", "QFileDialog: Export CSV"]
    assert asked != QMessageBox.StandardButton.Yes and picked[0] == ""
