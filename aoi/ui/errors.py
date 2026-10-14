"""Errors a user sees: one dialog format, one hook for unhandled errors (REQ-LOG-005, REQ-SET-019) and the start-up
that offers another workspace when one is refused (REQ-SET-016).

Every dialog shows the code and title, what happened and what to do, and never a stack trace; the trace
goes to the log through ``AppContext.report_error``, or at start-up, before a workspace is open, to the log in the
default workspace folder.
"""

from __future__ import annotations

import json
import sys
import traceback
from collections.abc import Callable
from pathlib import Path
from types import TracebackType
from typing import Any

from PySide6.QtCore import QCoreApplication
from PySide6.QtWidgets import QFileDialog, QMessageBox, QWidget

from .. import logging_setup
from ..config import Settings, default_workspace
from ..core.services import UNHANDLED, AppContext, ErrorReport, RunningCopy, running_copy, workspace_in_use
from ..errors import QT_TRANSLATE_NOOP, AoiError, Phrase, system_detail
from . import front

# Refusals another workspace folder cures: a v0.1 or newer database, a changed migration, a folder without WAL, a
# folder or database that cannot be opened, a database another program holds (the same folder, once it lets go).
ANOTHER_WORKSPACE = {"AOI-SET-001", "AOI-SET-002", "AOI-SET-003", "AOI-SET-005", "AOI-SET-011", "AOI-SET-012"}
# The workspace is open in another copy of the app: that copy comes to the front, never a folder picker (F12)
ALREADY_OPEN = "AOI-SET-019"
# A Trial version refused by the go-live gate or the customer validation report: the dialog's Start the Checks button
# opens them (B1 of the 2026-10 business-readiness brief, decision D1; ADR 0020)
START_CHECKS = {"AOI-TRN-052", "AOI-TST-009"}


def phrase_text(text: str) -> str:
    """`text` in the UI language: a phrase (an error's title, what happened and what to do, an alarm, and the phrases
    that fill them) translated under its context, then filled with its values, themselves shown the same way; any
    other text as it is; a template not yet filled, translated with its {placeholders}. A translation that names
    other placeholders than its source, or uses one in a way its value does not allow, leaves the English (#198)."""
    if not isinstance(text, Phrase):
        return text
    translated = QCoreApplication.translate(text.context, text.source)
    if not text.filled:
        return translated
    values = {k: phrase_text(v) if isinstance(v, str) else v for k, v in text.values.items()}
    try:
        return translated.format(**values)
    except (KeyError, IndexError, ValueError, AttributeError, TypeError):
        return text.source.format(**values)


def alarm_text(alarm: dict[str, Any]) -> str:
    """An alarm's message in the UI language: its stored phrase, or the message stored before migration 0011 or in
    the UI language a page wrote it in."""
    try:
        return phrase_text(Phrase.from_json(json.loads(alarm["phrase"]))) if alarm.get("phrase") else alarm["message"]
    except (ValueError, KeyError, TypeError, AttributeError):  # a phrase that cannot be read: the English stands
        return str(alarm["message"])


def dialog_text(report: ErrorReport) -> tuple[str, str]:
    """(title, text) of the dialog: "<code> <title>", then what happened and what to do, in the UI language."""
    return f"{report.code} {phrase_text(report.title)}", f"{phrase_text(report.what)}\n\n{phrase_text(report.action)}"


class ErrorBox(QMessageBox):
    """The one error dialog: "<code> <title>", what happened and what to do in plain words, and one OK. The error's
    technical words, the exception's class and text or the system's own text, are behind Show Details…, as the log
    holds them, and never in the message (A5 of the 2026-10 business-readiness brief, F8); a stack trace only in the
    log (REQ-SET-019). With `act`, a button named by its text beside OK, which stays the default and Esc's: the step
    the action names, such as Start the Checks (ADR 0020); `acted` says whether it closed the dialog. A Trial version
    refused (START_CHECKS), a step taken as approved, shows the information icon rather than the error's."""

    def __init__(self, parent: QWidget | None, report: ErrorReport, act: str | None = None) -> None:
        title, text = dialog_text(report)
        icon = QMessageBox.Icon.Information if report.code in START_CHECKS else QMessageBox.Icon.Critical
        super().__init__(icon, title, text, QMessageBox.StandardButton.Ok, parent)
        if report.detail:
            self.setDetailedText(report.detail)
        self.act = self.addButton(act, QMessageBox.ButtonRole.ActionRole) if act else None
        if self.act is not None:
            self.act.setProperty("sizeClass", "T")  # the 48 px operator target, as pages.base.size_class marks one
        self.setDefaultButton(QMessageBox.StandardButton.Ok)
        self.setEscapeButton(QMessageBox.StandardButton.Ok)  # Qt picks none beside a second button: Esc is OK

    def acted(self) -> bool:
        return self.act is not None and self.clickedButton() is self.act


def show_error(
    parent: QWidget | None, report: ErrorReport, act: tuple[str, Callable[[], object]] | None = None
) -> None:
    """The error's dialog, and with `act` (its button's text, what the button does) the button that takes the step the
    dialog names, done once the dialog is closed with it."""
    box = ErrorBox(parent, report, act[0] if act else None)
    box.exec()
    if act is not None and box.acted():
        act[1]()


class AlreadyOpenBox(QMessageBox):
    """AOI-SET-019 when the copy already open cannot be brought to the front: its code and title, one sentence that
    says what to do, and one OK (A6 of the 2026-10 business-readiness brief, F12)."""

    def __init__(self, report: ErrorReport, parent: QWidget | None = None) -> None:
        title = f"{report.code} {phrase_text(report.title)}"
        what, ok = phrase_text(report.what), QMessageBox.StandardButton.Ok
        super().__init__(QMessageBox.Icon.Information, title, what, ok, parent)


def show_already_open(
    error: AoiError, folder: Path, parent: QWidget | None = None, retry: bool = False, wait: bool = True
) -> bool:
    """A start, or a switch of workspace (`parent` the window switching), on a workspace another copy of the app has
    open: that copy's window comes to the front, once it has one when `wait` (a copy still starting), and nothing more
    is said; where the system cannot do that (any but Windows, another user's session or PC, a copy that does not
    answer, a refusal), one sentence and one OK say so. Never a folder picker: another folder would only open a second
    copy elsewhere. True when that is done; False, when `retry`, if the other copy closed meanwhile, so the caller
    opens the workspace after all."""

    def held() -> RunningCopy | None:  # the copy that holds the workspace now, as it noted itself
        return running_copy(folder) if workspace_in_use(folder) else None

    if front.bring_to_front(held, wait=None if wait else 0.0):
        return True
    if retry and not workspace_in_use(folder):
        return False
    AlreadyOpenBox(ErrorReport.of(error), parent).exec()
    return True


def install_excepthook(ctx: AppContext, parent: QWidget | None) -> None:
    """Route every unhandled error to the log (build version and stack trace) and to a plain dialog, which does not
    say "unhandled": the log does (`UNHANDLED`)."""

    def hook(exc_type: type[BaseException], exc: BaseException, tb: TracebackType | None) -> None:
        try:
            show_error(parent, ctx.report_error(exc.with_traceback(tb), UNHANDLED))
        except Exception:  # the handler itself must never take the app down
            sys.__excepthook__(exc_type, exc, tb)

    sys.excepthook = hook


def open_workspace() -> AppContext | None:
    """The AppContext the app starts with, on the workspace settings.json names, or None to close the app.

    A refused workspace is shown with its coded message before any window opens, so the Settings page cannot be reached;
    for a refusal another folder cures, a folder picker follows. A workspace another copy of the app has open brings
    that copy to the front instead, or says so in one sentence (`show_already_open`), and the app closes. The folder
    chosen is opened in turn and, once open, saved to settings.json as the Settings page saves it; a settings.json that
    cannot be written is logged, and the folder still serves this session. Cancel closes the app. Any other coded error
    is shown and closes the app. An error without a code is shown as AOI-SET-007 and its trace goes to the default
    workspace's log (REQ-SET-019: stack traces go only to the log), since the excepthook logs to an open workspace's
    log: it is installed once the workspace is open, before the window is built (``main_window.build_window``, #205)."""
    try:
        return _open_workspace()
    except Exception as e:
        log_start_failure(e)
        show_error(None, ErrorReport.of(e, QT_TRANSLATE_NOOP("Errors", "start-up")))
        return None


def log_start_failure(exc: Exception) -> None:
    """Write an error at start-up to the log in the default workspace folder, where settings.json is, and close the
    file again: a coded refusal as `app.start_refused` with its code and its detail, the technical words its dialog's
    Show Details holds; any other error as `app.start_failed` with its trace. The console is the last resort when that
    folder cannot be written either."""
    try:
        log = logging_setup.setup(default_workspace())
        try:
            if isinstance(exc, AoiError):
                detail = exc.detail or system_detail(exc.__cause__)
                log.warning("app.start_refused", extra={"code": exc.code, "what": str(exc.what), "detail": detail})
            else:
                log.error("app.start_failed", exc_info=exc)
        finally:
            logging_setup.close(log)
    except Exception:
        traceback.print_exception(exc)


def _open_workspace() -> AppContext | None:
    try:
        settings = Settings.load()
    except AoiError as e:  # settings.json cannot be read (AOI-SET-010) or holds a wrong value (AOI-SET-008)
        log_start_failure(e)  # no workspace yet: the default workspace's log, as for an error without a code
        show_error(None, ErrorReport.of(e))
        return None
    chosen, retried = False, False
    while True:
        try:
            ctx = AppContext(settings)
        except AoiError as e:
            if e.code == ALREADY_OPEN:
                if show_already_open(e, settings.root, retry=not retried):
                    return None
                retried = True  # the other copy closed while this start asked: open the workspace now
                continue
            log_start_failure(e)
            show_error(None, ErrorReport.of(e))
            if e.code not in ANOTHER_WORKSPACE:
                return None
        else:
            if chosen:  # saved once it opened (#171): settings.json never names a folder that was refused
                try:  # that key alone: the rest of the file stays as written (#170)
                    settings.save_keys({"workspace": settings.workspace})
                except (OSError, AoiError):  # settings.json cannot be read or written: the session keeps the folder
                    ctx.log.warning("settings.save_failed", exc_info=True, extra={"workspace": settings.workspace})
            return ctx
        title = QCoreApplication.translate("Startup", "Choose another workspace folder")
        folder = QFileDialog.getExistingDirectory(None, title, settings.workspace)
        if not folder:
            return None
        settings.workspace, chosen = folder, True
