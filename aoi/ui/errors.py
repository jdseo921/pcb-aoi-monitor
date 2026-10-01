"""Errors a user sees: one dialog format and one hook for unhandled errors (REQ-LOG-005, REQ-SET-019).

Every dialog shows the code and title, what happened and what to do, and never a stack trace; the trace
goes to the log through ``AppContext.report_error``.
"""

from __future__ import annotations

import sys
from types import TracebackType

from PySide6.QtWidgets import QMessageBox, QWidget

from ..core.services import AppContext, ErrorReport


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
