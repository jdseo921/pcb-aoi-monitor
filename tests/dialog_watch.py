"""Every dialog the app shows while it is watched (A8 of the 2026-10 business-readiness brief, F14): a demo script must
show none, so its tests and tests/startup_worker.py list each one by its kind and title, and print it with its text to
stderr. The watch looks at the app's windows every POLL_MS ms, in any event loop that runs, a dialog's own included, and
not at every event: an event filter on the application, in Python, made each start of the app slower (about 0.8 s in one
timing, 0.3 s in another), which REQ-SET-020's 5 s budget would count. So it sees a dialog visible at one of its looks:
the app shows each of its dialogs by exec() or a static call (a message box, an error, a file, folder or user picker),
which waits to be answered, and tests/test_dialog_watch.py fails on one shown any other way. A dialog found is closed
again as Esc closes it, from the event loop rather than from the look, so a dialog its closing opens is seen too; none
waits offscreen for a click no one makes, and the step after it fails instead. A system's own dialog, such as Windows'
printer picker, is not a Qt window and is not seen; the demo scripts open none. The questions a script answers itself
(an export's, Reset Demo's), the file and folder an export saves to and the user Switch User picks are patched static
calls, which show no dialog; the tests list them apart by title and require exactly the script's. Tests run offscreen on
every system (CI included), where Qt's own dialogs stand in for the system's file pickers, so a picker shows as a
QDialog here too."""

from __future__ import annotations

import sys
from collections.abc import Iterator
from contextlib import contextmanager

from PySide6.QtCore import QObject, QTimer
from PySide6.QtWidgets import QApplication, QDialog, QMessageBox

POLL_MS = 20
SEEN = "aoiDialogWatchSeen"  # a dynamic property: a dialog listed, its rejection on its way


class DialogWatch(QObject):
    """Lists in `shown` each top-level dialog visible at one of its looks (`start` to `stop`), once, as
    "<kind>: <title>", a message box and an error dialog included, and rejects it as Esc does."""

    def __init__(self) -> None:
        super().__init__()
        self.shown: list[str] = []
        self._timer: QTimer | None = None

    def start(self) -> None:
        """Look every POLL_MS ms from now on; the application must exist. A second call changes nothing."""
        if self._timer is not None:
            return
        self._timer = QTimer(self)
        self._timer.setInterval(POLL_MS)
        self._timer.timeout.connect(self.look)
        self._timer.start()

    def stop(self) -> None:
        """Look once more, then no longer; a dialog still open is rejected at once, as no event loop may run after."""
        self.look()
        if self._timer is not None:
            self._timer.stop()
        for widget in QApplication.topLevelWidgets():
            if isinstance(widget, QDialog) and widget.isVisible():
                widget.reject()

    def look(self) -> None:
        """Each dialog open now and not yet seen: listed, printed and rejected once this look has ended, so a dialog
        its rejection opens runs its event loop outside this timer's slot, where the timer goes on firing (review of
        A8)."""
        for widget in QApplication.topLevelWidgets():
            if isinstance(widget, QDialog) and widget.isVisible() and not widget.property(SEEN):
                widget.setProperty(SEEN, True)
                self.shown.append(f"{type(widget).__name__}: {widget.windowTitle()}")
                text = f": {widget.text()}" if isinstance(widget, QMessageBox) else ""
                print(f"dialog shown, {self.shown[-1]}{text}", file=sys.stderr, flush=True)
                QTimer.singleShot(0, widget, widget.reject)


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
