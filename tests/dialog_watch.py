"""Every dialog the app shows while it is watched (A8 of the 2026-10 business-readiness brief, F14): a demo script must
show none, so its tests and tests/startup_worker.py list each one by its kind and title, and print it with its text to
stderr. The watch looks at the app's windows every POLL_MS ms, in whichever event loop runs, a dialog's own included,
and not at every event: an event filter on the application, in Python, made each start of the app about 0.8 s slower,
which REQ-SET-020's 5 s budget would count. Each dialog the app shows waits to be answered (a message box, an error, a
file, folder, user or printer picker), so none closes before the watch looks. A dialog found is closed again as Esc
closes it, so none waits offscreen for a click no one makes, and the step after it fails instead. The questions a
script answers itself (an export's, Reset Demo's), the file and folder an export saves to and the user Switch User
picks are patched static calls, which show no dialog; the tests list them apart by title and require exactly the
script's. Tests run offscreen on every system (CI included), where Qt's own dialogs stand in for the system's file
pickers, so a picker shows as a QDialog here too."""

from __future__ import annotations

import sys
from collections.abc import Iterator
from contextlib import contextmanager

from PySide6.QtCore import QObject, QTimer
from PySide6.QtWidgets import QApplication, QDialog, QMessageBox

POLL_MS = 20


class DialogWatch(QObject):
    """Lists in `shown` each top-level dialog open while it runs (`start` to `stop`), "<kind>: <title>", a message box
    and an error dialog included, and rejects it as Esc does."""

    def __init__(self) -> None:
        super().__init__()
        self.shown: list[str] = []
        self._timer: QTimer | None = None

    def start(self) -> None:
        """Look every POLL_MS ms from now on; the application must exist."""
        self._timer = QTimer(self)
        self._timer.setInterval(POLL_MS)
        self._timer.timeout.connect(self.look)
        self._timer.start()

    def stop(self) -> None:
        """Look once more, then no longer."""
        self.look()
        if self._timer is not None:
            self._timer.stop()

    def look(self) -> None:
        """Each dialog open now: listed, printed and rejected."""
        for widget in QApplication.topLevelWidgets():
            if isinstance(widget, QDialog) and widget.isVisible():
                self.shown.append(f"{type(widget).__name__}: {widget.windowTitle()}")
                text = f": {widget.text()}" if isinstance(widget, QMessageBox) else ""
                print(f"dialog shown, {self.shown[-1]}{text}", file=sys.stderr, flush=True)
                widget.reject()


@contextmanager
def watched() -> Iterator[list[str]]:
    """The dialogs shown in the block, as `DialogWatch.shown`."""
    assert QApplication.instance() is not None
    watch = DialogWatch()
    watch.start()
    try:
        yield watch.shown
    finally:
        watch.stop()
