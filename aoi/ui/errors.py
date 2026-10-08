"""Errors a user sees: one dialog format, one hook for unhandled errors (REQ-LOG-005, REQ-SET-019) and the start-up
that offers another workspace when one is refused (REQ-SET-016).

Every dialog shows the code and title, what happened and what to do, and never a stack trace; the trace
goes to the log through ``AppContext.report_error``, or at start-up, before a workspace is open, to the log in the
default workspace folder.
"""

from __future__ import annotations

import sys
import traceback
from types import TracebackType

from PySide6.QtCore import QCoreApplication
from PySide6.QtWidgets import QFileDialog, QMessageBox, QWidget

from .. import logging_setup
from ..config import Settings, default_workspace
from ..core.services import AppContext, ErrorReport
from ..errors import AoiError

# Refusals another workspace folder cures: a v0.1 or newer database, a changed migration, a folder without WAL, a
# folder or database that cannot be opened.
ANOTHER_WORKSPACE = {"AOI-SET-001", "AOI-SET-002", "AOI-SET-003", "AOI-SET-005", "AOI-SET-011"}


def dialog_text(report: ErrorReport) -> tuple[str, str]:
    """(title, text) of the dialog: "<code> <title>", then what happened and what to do."""
    return f"{report.code} {report.title}", f"{report.what}\n\n{report.action}"


def show_error(parent: QWidget | None, report: ErrorReport) -> None:
    title, text = dialog_text(report)
    QMessageBox.critical(parent, title, text)


def install_excepthook(ctx: AppContext, parent: QWidget | None) -> None:
    """Route every unhandled error to the log (build version and stack trace) and to a plain dialog."""

    def hook(exc_type: type[BaseException], exc: BaseException, tb: TracebackType | None) -> None:
        try:
            show_error(parent, ctx.report_error(exc.with_traceback(tb), "unhandled"))
        except Exception:  # the handler itself must never take the app down
            sys.__excepthook__(exc_type, exc, tb)

    sys.excepthook = hook


def open_workspace() -> AppContext | None:
    """The AppContext the app starts with, on the workspace settings.json names, or None to close the app.

    A refused workspace is shown with its coded message before any window opens, so the Settings page cannot be reached;
    for a refusal another folder cures, a folder picker follows. The folder chosen is saved to settings.json, as the
    Settings page saves it, and opened in turn; Cancel closes the app. Any other coded error is shown and closes the
    app. An error without a code is shown as AOI-SET-007 and its trace goes to the default workspace's log
    (REQ-SET-019: stack traces go only to the log), since the excepthook is installed only once the window exists."""
    try:
        return _open_workspace()
    except Exception as e:
        _log_start_failure(e)
        show_error(None, ErrorReport.of(e, "start-up"))
        return None


def _log_start_failure(exc: Exception) -> None:
    """Write the trace of an error at start-up to the log in the default workspace folder, where settings.json is,
    and close the file again; the console is the last resort when that folder cannot be written either."""
    try:
        log = logging_setup.setup(default_workspace())
        try:
            log.error("app.start_failed", exc_info=exc)
        finally:
            logging_setup.close(log)
    except Exception:
        traceback.print_exception(exc)


def _open_workspace() -> AppContext | None:
    try:
        settings = Settings.load()
    except AoiError as e:  # settings.json cannot be read (AOI-SET-010) or holds a wrong value (AOI-SET-008)
        show_error(None, ErrorReport.of(e))  # no workspace yet, so no log: the dialog carries the code
        return None
    while True:
        try:
            return AppContext(settings)
        except AoiError as e:
            show_error(None, ErrorReport.of(e))
            if e.code not in ANOTHER_WORKSPACE:
                return None
        title = QCoreApplication.translate("Startup", "Choose another workspace folder")
        folder = QFileDialog.getExistingDirectory(None, title, settings.workspace)
        if not folder:
            return None
        settings.workspace = folder
        settings.save()
