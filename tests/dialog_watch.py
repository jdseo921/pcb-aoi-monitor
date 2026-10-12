"""Every dialog the app shows while it is watched (A8 of the 2026-10 business-readiness brief, F14): a demo script must
show none, so its tests and tests/startup_worker.py list each one by its kind and title, and print it with its text to
stderr. A dialog is closed again as Esc closes it as soon as it shows, so none waits offscreen for a click no one
makes, and the step after it fails instead. The questions a script answers itself (an export's, Reset Demo's), the
file and folder an export saves to and the user Switch User picks are patched static calls, which show no dialog; the
tests list them apart by title and require exactly the script's. Tests run offscreen on every system (CI included),
where Qt's own dialogs stand in for the system's file pickers, so a picker shows as a QDialog here too."""

from __future__ import annotations

import sys
from collections.abc import Iterator
from contextlib import contextmanager

from PySide6.QtCore import QCoreApplication, QEvent, QObject, QTimer
from PySide6.QtWidgets import QDialog, QMessageBox


class DialogWatch(QObject):
    """Lists in `shown` each top-level dialog shown, "<kind>: <title>", a message box and an error dialog included,
    and rejects it as Esc does."""

    def __init__(self) -> None:
        super().__init__()
        self.shown: list[str] = []

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:  # noqa: N802 (Qt's name)
        if event.type() == QEvent.Type.Show and isinstance(watched, QDialog) and watched.isWindow():
            self.shown.append(f"{type(watched).__name__}: {watched.windowTitle()}")
            text = f": {watched.text()}" if isinstance(watched, QMessageBox) else ""
            print(f"dialog shown, {self.shown[-1]}{text}", file=sys.stderr, flush=True)
            QTimer.singleShot(0, watched.reject)
        return False


@contextmanager
def watched() -> Iterator[list[str]]:
    """The dialogs shown in the block, as `DialogWatch.shown`."""
    app = QCoreApplication.instance()
    assert app is not None
    watch = DialogWatch()
    app.installEventFilter(watch)
    try:
        yield watch.shown
    finally:
        app.removeEventFilter(watch)
