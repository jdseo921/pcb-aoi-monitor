"""The first Admin's recovery code, shown once (REQ-USR-005; ADR 0002, decision 6), as a store's recovery key is: the
code, Save to File… and Print…, and Done, which waits until it was saved or printed. Esc, the window's close and a
sign-in do nothing until then. The code is in a label that cannot be selected, so never on the clipboard, and is
forgotten as the dialog closes. With it, the Admin signs in with Use Recovery Code… after losing their password."""

from __future__ import annotations

import html
from pathlib import Path
from typing import TYPE_CHECKING

from PySide6.QtCore import QStandardPaths
from PySide6.QtGui import QTextDocument
from PySide6.QtPrintSupport import QPrintDialog, QPrinter
from PySide6.QtWidgets import QDialog, QFileDialog, QHBoxLayout, QLabel, QVBoxLayout

from ..errors import AoiError
from . import theme
from .errors import show_error
from .pages.base import button, size_class

if TYPE_CHECKING:
    from .main_window import MainWindow


class RecoveryCodeDialog(QDialog):
    def __init__(self, shell: MainWindow, code: str) -> None:
        super().__init__(shell)
        self.shell, self.ctx, self.code = shell, shell.ctx, code
        self.setWindowTitle(self.tr("Recovery code for {user}").format(user=self.ctx.user))
        self.setMinimumWidth(theme.CARD_W)
        lay = QVBoxLayout(self)
        note = QLabel(
            self.tr(
                "Shown this once. Save it to a USB drive or print it, and keep it apart from the station: with it,"
                " {user} signs in and chooses a new password after losing theirs. It works once, then a new one shows."
            ).format(user=self.ctx.user)
        )
        note.setWordWrap(True)
        lay.addWidget(note)
        self.code_label = QLabel(code)  # not selectable, so never on the clipboard
        self.code_label.setObjectName("recoveryKey")
        lay.addWidget(self.code_label)
        row = QHBoxLayout()
        self.btn_save = size_class(button(self.tr("Save to File…"), slot=self.save_file), "T")
        self.btn_print = size_class(button(self.tr("Print…"), slot=self.print_sheet), "T")
        self.saved_line = QLabel()
        self.saved_line.setWordWrap(True)
        for w in (self.btn_save, self.btn_print):
            row.addWidget(w)
        row.addWidget(self.saved_line, 1)
        self.btn_done = size_class(button(self.tr("Done"), "primary", self.accept), "T")
        self.btn_done.setEnabled(False)
        row.addWidget(self.btn_done)
        lay.addLayout(row)
        self.btn_save.setFocus()

    def text(self) -> str:
        """The sheet as Save to File… writes it and Print… prints it."""
        return "\n".join(
            [
                self.windowTitle(),
                "",
                self.code,
                "",
                self.tr(
                    "Keep this sheet locked away, apart from the station. At Switch User, {user} presses Use Recovery"
                    " Code…, types it and chooses a new password. It works once."
                ).format(user=self.ctx.user),
                "",
            ]
        )

    def _kept(self, said: str) -> None:
        self.saved_line.setText(said)
        self.btn_done.setEnabled(True)

    def save_file(self) -> None:
        """The sheet as UTF-8 text, offered on the USB drive plugged in last, else in the home folder; written and
        audited by `AppContext.save_code_sheet`, whose refusal (AOI-LOG-002) is shown."""
        home = Path(QStandardPaths.writableLocation(QStandardPaths.StandardLocation.HomeLocation))
        start = self.ctx.usb_drive() or home
        f, _ = QFileDialog.getSaveFileName(
            self, self.tr("Save Recovery Code"), str(start / "recovery-code-admin.txt"), self.tr("Text (*.txt)")
        )
        if not f:
            return
        try:
            self.ctx.save_code_sheet(self.text(), f)
        except AoiError as e:
            show_error(self, self.ctx.report_error(e, "Save recovery code"))
            return
        self._kept(self.tr("✓ Saved to {file}").format(file=f))

    def print_sheet(self) -> None:
        """The sheet on the printer picked, audited first by `AppContext.print_code_sheet`."""
        printer = QPrinter(QPrinter.PrinterMode.HighResolution)
        if QPrintDialog(printer, self).exec() != QDialog.DialogCode.Accepted:
            return
        try:
            self.ctx.print_code_sheet(printer.printerName(), printer.outputFileName() or None)
        except AoiError as e:
            show_error(self, self.ctx.report_error(e, "Print recovery code"))
            return
        doc = QTextDocument()
        doc.setHtml("".join(f"<p>{html.escape(line)}</p>" for line in self.text().splitlines() if line))
        doc.print_(printer)
        self._kept(self.tr("✓ Sent to {printer}").format(printer=printer.printerName() or printer.outputFileName()))

    def reject(self) -> None:
        """Esc or the window's close: refused until the code was saved or printed."""
        if self.btn_done.isEnabled():
            super().reject()

    def done(self, result: int) -> None:
        if not self.btn_done.isEnabled():
            return
        self.code = ""
        self.code_label.clear()
        super().done(result)
