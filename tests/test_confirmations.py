"""A question that can remove or overwrite data never has Yes as the Enter answer (REQ-SET-018, #182): the real
QMessageBox is shown and Enter is pressed on it, as a user in a hurry would."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from PySide6.QtCore import Qt, QTimer
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QFileDialog, QMessageBox
from pytestqt.qtbot import QtBot

from aoi.core.services import AppContext
from aoi.ui.pages.logs import LogsPage
from aoi.ui.pages.training import TrainingPage
from tests.test_req_done_in_v01 import BOARD, _window

REAL_QUESTION = QMessageBox.__dict__["question"]  # before the autouse fixture answers every question with Yes


def _answer(monkeypatch: pytest.MonkeyPatch, keys: list[str], act: Callable[[], object]) -> list[dict[str, Any]]:
    """Run `act` with the real question box; each box that opens gets the next of `keys` ("enter" presses Return,
    "yes" clicks Yes). Returns what each box showed: its text, its default button and the button with the focus."""
    seen: list[dict[str, Any]] = []
    done: list[bool] = []  # set once `act` returns: no box of a later test is answered

    def poll() -> None:
        if done:
            return
        box = QApplication.activeModalWidget()
        if not isinstance(box, QMessageBox) or not box.isVisible():
            QTimer.singleShot(20, poll)
            return
        default, focus = box.defaultButton(), box.focusWidget()
        seen.append(
            {"text": box.text(), "default": default.text() if default else None, "focus": getattr(focus, "text", str)()}
        )
        key = keys[len(seen) - 1]
        if key == "enter":
            QTest.keyClick(box, Qt.Key.Key_Return)
        else:
            box.button(QMessageBox.StandardButton.Yes).click()
        QTimer.singleShot(1000, box, lambda: box.reject() if box.isVisible() else None)  # never hang on a box left open
        if len(seen) < len(keys):
            QTimer.singleShot(20, poll)

    monkeypatch.setattr(QMessageBox, "question", REAL_QUESTION)
    QTimer.singleShot(0, poll)
    try:
        act()
    finally:  # the window closed at the test's end must not show a real box
        done.append(True)
        monkeypatch.setattr(QMessageBox, "question", staticmethod(lambda *_: QMessageBox.StandardButton.Yes))
    return seen


def test_req_set_018_enter_on_remove_samples_keeps_them(
    qtbot: QtBot, trained_ctx: AppContext, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Training, a sample that is not the reference selected, Remove, then Enter on "Remove 1 sample(s) from the
    dataset?": No is the default and has the focus, and the sample stays."""
    win = _window(qtbot, trained_ctx, "Admin")  # only an Admin removes a sample (REQ-LOG-003)
    win.navigate("Training")
    page = win.pages["Training"]
    assert isinstance(page, TrainingPage)
    reference = trained_ctx.reference_image(BOARD)
    before = trained_ctx.samples(BOARD)
    row = next(i for i in range(page.samples.rowCount()) if page.samples.item(i, 4).toolTip() != reference)
    page.samples.selectRow(row)
    seen = _answer(monkeypatch, ["enter"], page._remove)
    print(seen, "samples after", len(trained_ctx.samples(BOARD)))
    assert trained_ctx.samples(BOARD) == before, "Enter removed a sample"
    assert [s["text"] for s in seen] == ["Remove 1 sample(s) from the dataset?"]
    assert seen[0]["default"] == "&No" and seen[0]["focus"] == "&No"


def test_req_set_018_enter_on_replace_checks_file_keeps_it(
    qtbot: QtBot, trained_ctx: AppContext, ng_board: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Logs & Export, Export CSV answered Yes, a file whose _checks.csv is already there, then Enter on "… exists.
    Replace it?": No is the default, nothing is written and the earlier _checks.csv is left as it was. The first
    question writes new files only, so Yes stays its default."""
    trained_ctx.inspect_file(BOARD, str(ng_board))  # one record to export
    win = _window(qtbot, trained_ctx, "Engineer")
    win.navigate("Logs & Export")
    page = win.pages["Logs & Export"]
    assert isinstance(page, LogsPage)
    page.refresh()
    assert page.rows
    target, checks = tmp_path / "out" / "inspections.csv", tmp_path / "out" / "inspections_checks.csv"
    checks.parent.mkdir()
    checks.write_text("an earlier export\n", encoding="utf-8")
    monkeypatch.setattr(QFileDialog, "getSaveFileName", staticmethod(lambda *a, **k: (str(target), "CSV (*.csv)")))
    seen = _answer(monkeypatch, ["yes", "enter"], page.export_csv)
    print(seen)
    assert checks.read_text(encoding="utf-8") == "an earlier export\n", "Enter replaced the earlier export"
    assert not target.exists()
    assert [s["text"] for s in seen] == [
        "Export CSV for 1 record(s)? Two files are written: the records, and a second file ending in _checks.csv"
        " with one row per check.",
        "inspections_checks.csv exists. Replace it?",
    ]
    assert seen[0]["default"] == "&Yes"
    assert seen[1]["default"] == "&No" and seen[1]["focus"] == "&No"
