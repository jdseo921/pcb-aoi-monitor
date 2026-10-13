"""tests/dialog_watch.py, by which the demo-script tests and tests/startup_worker.py fail on any dialog (A8 of the
2026-10 business-readiness brief, F14): it lists a question, the app's own error dialog and a file picker, each as it
waits to be answered, and closes each as Esc does, so the code that showed it goes on. It sees a dialog visible at one
of its looks, so the app may show a dialog only in a way that waits to be answered, which the rule test here holds."""

from __future__ import annotations

import ast
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import pytest
from PySide6.QtCore import QSettings, QTimer
from PySide6.QtWidgets import QApplication, QDialog, QFileDialog, QMessageBox
from pytestqt.qtbot import QtBot

from aoi.core.services import ErrorReport
from aoi.errors import AoiError
from aoi.ui.errors import ErrorBox, dialog_text, show_error
from tests.dialog_watch import watched

ROOT = Path(__file__).resolve().parent.parent
REAL_QUESTION = QMessageBox.__dict__["question"]  # read as this file is collected, before any test's stand-in
QT_DIALOGS = {"QDialog", "QMessageBox", "QFileDialog", "QInputDialog", "QPrintDialog", "QPageSetupDialog"}
QT_DIALOGS |= {"QProgressDialog", "QErrorMessage", "QColorDialog", "QFontDialog", "QPrintPreviewDialog", "QWizard"}
# shown and gone on their own, or shown without waiting: a dialog the watch could miss between two looks
NEVER = {"QProgressDialog", "QErrorMessage", "setModal", "setWindowModality"}


@contextmanager
def qt_settings_in(folder: Path) -> Iterator[bool]:
    """Qt's own settings, where a file picker keeps its last folder and view (in Qt's native format), in `folder` and
    not in the user's; whether they moved. On Windows they are in the registry, which Qt cannot move, and they stay
    there, under HKEY_CURRENT_USER\\Software\\QtProject, as any Qt app's file picker keeps them."""
    native, user = QSettings.Format.NativeFormat, QSettings.Scope.UserScope
    if sys.platform == "win32":
        yield False
        return
    before = Path(QSettings(native, user, "aoi-test").fileName()).parent
    QSettings.setPath(native, user, str(folder))
    try:
        yield True
    finally:
        QSettings.setPath(native, user, str(before))


@contextmanager
def none_left_open() -> Iterator[list[str]]:
    """Every 5 s, any dialog still open is closed and listed: a watch that misses one fails its test, not hangs it."""
    stuck: list[str] = []

    def close_any() -> None:
        for widget in QApplication.topLevelWidgets():
            if isinstance(widget, QDialog) and widget.isVisible():
                stuck.append(widget.windowTitle())
                widget.reject()

    timer = QTimer()
    timer.setInterval(5000)
    timer.timeout.connect(close_any)
    timer.start()
    try:
        yield stuck
    finally:
        timer.stop()


def test_req_set_007_the_dialog_watch_lists_and_closes_every_dialog_shown(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A question, an error and a picker shown one after another in the watch: each listed by its kind and title in
    the order shown, and each closed without its yes, so the code after it runs. A question an error dialog opens as it
    closes, as a handler might, is listed and closed too (review of A8: closed from within the watch's look, it was
    not seen, and waited for a click)."""
    monkeypatch.setattr(QMessageBox, "question", REAL_QUESTION)  # the real dialogs for tests/conftest.py's stand-ins
    monkeypatch.delattr(ErrorBox, "exec")
    report = ErrorReport.of(AoiError("AOI-SET-019", path="C:/AOI_Workspace"))
    title, _text = dialog_text(report)
    then: list[QMessageBox.StandardButton] = []
    with qt_settings_in(tmp_path) as moved, none_left_open() as stuck, watched() as shown:
        asked = QMessageBox.question(None, "Stop the running work?", "Stop it?")
        show_error(None, report)
        picked = QFileDialog.getSaveFileName(None, "Export CSV")
        box = ErrorBox(None, report)
        box.rejected.connect(lambda: then.append(QMessageBox.question(None, "And then?", "Again?")))
        box.exec()
    assert not stuck, stuck
    assert shown == [
        "QMessageBox: Stop the running work?",
        f"ErrorBox: {title}",
        "QFileDialog: Export CSV",
        f"ErrorBox: {title}",
        "QMessageBox: And then?",
    ]
    yes = QMessageBox.StandardButton.Yes
    assert asked != yes and picked[0] == "" and len(then) == 1 and then[0] != yes, (asked, picked, then)
    assert not moved or list(tmp_path.glob("QtProject.*")), "the picker kept its settings in the user's own"


def _name(node: ast.AST) -> str:
    return node.id if isinstance(node, ast.Name) else node.attr if isinstance(node, ast.Attribute) else ""


def unanswered(sources: dict[str, str]) -> list[str]:
    """Each place in `sources` (name: Python source) that shows a dialog the watch could miss, in order: a progress
    dialog or an error-message box, a modality set, or a dialog, Qt's or a class of the sources' own built on one,
    shown with show(), open() or setVisible() (on the call that made it, or on the name it was given in the file)."""
    trees = {name: ast.parse(source) for name, source in sources.items()}
    dialogs, grew = set(QT_DIALOGS), True
    while grew:  # the sources' own dialog classes, and theirs
        grew = False
        for tree in trees.values():
            for node in ast.walk(tree):
                if isinstance(node, ast.ClassDef) and node.name not in dialogs:
                    if any(_name(base) in dialogs for base in node.bases):
                        dialogs.add(node.name)
                        grew = True
    found: list[tuple[str, int, str]] = []
    for name, tree in trees.items():
        made = {
            ast.unparse(target)
            for node in ast.walk(tree)
            if isinstance(node, ast.Assign) and isinstance(node.value, ast.Call) and _name(node.value.func) in dialogs
            for target in node.targets
        }
        for node in ast.walk(tree):
            if isinstance(node, (ast.Name, ast.Attribute)) and _name(node) in NEVER:
                found.append((name, node.lineno, _name(node)))
            elif isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                if node.func.attr in ("show", "open", "setVisible"):
                    shown = node.func.value
                    if (isinstance(shown, ast.Call) and _name(shown.func) in dialogs) or ast.unparse(shown) in made:
                        found.append((name, node.lineno, ast.unparse(node)))
    return [f"{name}:{line}: {what}" for name, line, what in sorted(found)]


def test_req_set_007_every_dialog_the_app_shows_waits_to_be_answered() -> None:
    """The watch sees a dialog visible at one of its looks, POLL_MS apart, and a dialog that waits to be answered
    always is: so the app shows its dialogs only by exec() or a static call, never one that shows and goes on its own
    or does not wait (review of A8: one shown and closed between two looks was not listed). The check finds each way
    in a sample, then none in the app."""
    sample = (
        "class Box(QMessageBox): ...\nclass Sheet(Box): ...\n"
        "def f(self):\n    box = Sheet(self)\n    box.show()\n    self.wait = QDialog(self)\n    self.wait.open()\n"
        "    QFileDialog(self).setVisible(True)\n    QProgressDialog('Copying', 'Cancel', 0, 9, self)\n"
        "    self.panel.show()\n    other = Box(self)\n    other.exec()\n"
    )
    assert unanswered({"sample": sample}) == [
        "sample:5: box.show()",
        "sample:7: self.wait.open()",
        "sample:8: QFileDialog(self).setVisible(True)",
        "sample:9: QProgressDialog",
    ]
    app = [*sorted((ROOT / "aoi").rglob("*.py")), ROOT / "main.py"]
    assert not unanswered({str(p.relative_to(ROOT)): p.read_text(encoding="utf-8") for p in app})
