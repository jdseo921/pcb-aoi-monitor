"""A dataset store's recovery key, shown once (REQ-TRN-017; ADR 0010, ADR 0021): the key as its recovery sheet gives it,
Save to File… and Print…, and a tick that says it is kept, which the step showing it waits for. The tick is off until
the key was saved or printed. The New board model dialog shows it for a customer's first board model, and
`RecoveryKeyDialog` for Settings' New Store…: neither can be left until the tick, by Esc, Cancel, the window's close or
a sign-in, which exec(), showing it modal, keeps from the window behind it. The key is in a label that cannot be
selected, so never on the clipboard, and `clear` forgets it. The store's UUID and key id, an Admin's advanced detail,
are on the sheet saved or printed, not on screen (B2 of the 2026-10 business-readiness brief). The first-run guide shows
it with no tick (`tick=False`, B5, Q67): a line beside the buttons says where the key went, and the guide's own button,
I Have Saved the Key, waits for `saved`. Its save dialog opens on the USB drive plugged in last (`usb=True`, Q68)."""

from __future__ import annotations

import html
import re
from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING, Any

from PySide6.QtCore import QEvent, QObject, QStandardPaths, Signal
from PySide6.QtGui import QTextDocument
from PySide6.QtPrintSupport import QPrintDialog, QPrinter
from PySide6.QtWidgets import QCheckBox, QDialog, QFileDialog, QHBoxLayout, QLabel, QVBoxLayout, QWidget

from ...errors import AoiError
from ...times import to_local
from .. import theme
from .base import button, size_class

if TYPE_CHECKING:
    from ...core.services import AppContext


class RecoveryKey(QWidget):
    """The key of the store `show_key` was given, until `clear`; `changed` follows the tick, and `saved`."""

    changed = Signal()

    def __init__(
        self,
        ctx: AppContext,
        error: Callable[[AoiError], object],
        status: Callable[[str], object],
        tick: bool = True,
        usb: bool = False,
    ) -> None:
        super().__init__()
        self.ctx, self.error, self.status, self.usb = ctx, error, status, usb
        self.made: dict[str, str] | None = None  # uuid, customer, key_id, sheet and created_at of the store shown
        self.saved = False  # the key shown was saved to a file or printed
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        self.note = note = QLabel(
            self.tr(
                "Shown this once. Save it to a USB drive or print it, and keep it apart from the station: with it, an"
                " Admin opens the store on another PC, and anyone who holds it and a copy of the files can read them."
            )
        )
        note.setWordWrap(True)
        self.key = QLabel()  # 13 groups of four on two lines; not selectable, so never on the clipboard
        self.key.setObjectName("recoveryKey")
        self.btn_save = size_class(button(self.tr("Save to File…"), slot=self.save_file), "T")
        self.btn_print = size_class(button(self.tr("Print…"), slot=self.print_sheet), "T")
        row = QHBoxLayout()
        for b in (self.btn_save, self.btn_print):
            row.addWidget(b)
        self.saved_line = QLabel()  # without a tick, where the key went: "✓ Saved to F:\\recovery-key-Acme.txt"
        self.saved_line.setWordWrap(True)
        row.addWidget(self.saved_line, 1)
        self.kept = size_class(
            QCheckBox(self.tr("I have saved or printed the key and will keep it apart from the station")), "T"
        )
        self.kept.toggled.connect(self.changed)
        self.kept.installEventFilter(self)  # a press while it is off says why on the status bar: touch has no tooltip
        self.kept.setVisible(tick)
        self.tick = tick
        for w in (note, self.key):
            lay.addWidget(w)
        lay.addLayout(row)
        lay.addWidget(self.kept)
        self.clear()

    def title(self) -> str:
        return self.tr("Recovery key for {customer}").format(customer=self.made["customer"] if self.made else "")

    def show_key(self, store: dict[str, Any]) -> None:
        """`store`'s key, as `create_store` returned it with its `sheet`; the tick off until it is saved or printed."""
        self.made = {k: str(store[k]) for k in ("uuid", "customer", "key_id", "sheet", "created_at")}
        groups = self.made["sheet"].split()
        self.key.setText(" ".join(groups[:7]) + "\n" + " ".join(groups[7:]))
        self._keepable(False)

    def clear(self) -> None:
        """The key forgotten: the label empty, the tick off."""
        self.made = None
        self.key.clear()
        self._keepable(False)

    def holding(self) -> bool:
        """A key is shown and its tick is not ticked, or, with no tick, it is not cleared yet: the step showing it may
        not be left."""
        return self.made is not None and (not self.tick or not self.kept.isChecked())

    def _keepable(self, on: bool) -> None:
        self.saved = on
        if not on:
            self.saved_line.clear()
        self.kept.setChecked(False)
        self.kept.setEnabled(on)
        self.kept.setToolTip("" if on else self.unsaved())

    def unsaved(self) -> str:
        """What a step waiting for the key says while the key was neither saved nor printed."""
        return self.tr("Save the key to a file or print it first")

    def _kept_away(self, said: str) -> None:
        """Saved or printed, `said` beside the buttons with no tick: the tick may be ticked now, and `saved` holds."""
        if not self.tick:
            self.saved_line.setText(said)
        if not self.kept.isEnabled():
            self._keepable(True)
        if not self.tick:  # a tick says so through its own toggled
            self.changed.emit()

    def eventFilter(self, watched: QObject, e: QEvent) -> bool:
        if watched is self.kept and e.type() == QEvent.Type.MouseButtonPress and not self.kept.isEnabled():
            self.status(self.kept.toolTip())
        return False

    def _ids(self) -> str:
        assert self.made is not None
        return self.tr("Store {uuid} · key id {key_id}").format(uuid=self.made["uuid"], key_id=self.made["key_id"])

    def _paragraph(self) -> str:
        return self.tr(
            "Keep this sheet locked away, apart from the station. With it, an Admin types the key into Settings ›"
            " Dataset stores › Advanced › Restore Key… on another PC or Windows account. Anyone who holds it and a copy"
            " of the store's files can read them. Destroy it when the store is shredded."
        )

    def text(self) -> str:
        """The recovery sheet as Save to File… writes it: the customer, the store, the key id, the day and the key."""
        assert self.made is not None
        groups = self.made["sheet"].split()
        lines = [self.title(), f"{self._ids()} · {to_local(self.made['created_at'])}", ""]
        return "\n".join([*lines, " ".join(groups[:7]), " ".join(groups[7:]), "", self._paragraph(), ""])

    def document(self) -> QTextDocument:
        """The recovery sheet as Print… prints it, as `text` words it."""
        assert self.made is not None
        groups = self.made["sheet"].split()
        lines = [
            f"<h2>{html.escape(self.title())}</h2>",
            f"<p>{html.escape(self._ids())} · {html.escape(to_local(self.made['created_at']))}</p>",
            f'<p style="font-family: monospace; font-size: 20pt">{" ".join(groups[:7])}<br>{" ".join(groups[7:])}</p>',
            f"<p>{html.escape(self._paragraph())}</p>",
        ]
        doc = QTextDocument()
        doc.setHtml("".join(lines))
        return doc

    def save_file(self) -> None:
        """The sheet as UTF-8 text in a file the user names, offered under the customer's name in the home folder (not
        Documents, which OneDrive may copy off the station), or with `usb` on the USB drive plugged in last, if any;
        written and audited by `AppContext.save_recovery_sheet`, whose refusal (AOI-LOG-002) is shown."""
        if self.made is None:
            return
        stem = re.sub(r"[^A-Za-z0-9]+", "-", self.made["customer"]).strip("-") or "store"
        drive = self.ctx.usb_drive() if self.usb else None
        start = drive or Path(QStandardPaths.writableLocation(QStandardPaths.StandardLocation.HomeLocation))
        f, _ = QFileDialog.getSaveFileName(
            self, self.tr("Save Recovery Key"), str(start / f"recovery-key-{stem}.txt"), self.tr("Text (*.txt)")
        )
        if not f:
            return
        try:
            self.ctx.save_recovery_sheet(self.made["uuid"], self.text(), f)
        except AoiError as e:
            self.error(e)
            return
        self.status(self.tr("Saved the recovery key to {file}").format(file=f))
        self._kept_away(self.tr("✓ Saved to {file}").format(file=f))

    def print_sheet(self) -> None:
        """The sheet on the printer picked, audited first by `AppContext.print_recovery_sheet` with the printer and any
        file Qt prints it to, which is refused in the workspace or a OneDrive folder (AOI-LOG-002)."""
        printer = QPrinter(QPrinter.PrinterMode.HighResolution)
        if self.made is None or QPrintDialog(printer, self).exec() != QDialog.DialogCode.Accepted:
            return
        try:
            self.ctx.print_recovery_sheet(self.made["uuid"], printer.printerName(), printer.outputFileName() or None)
        except AoiError as e:
            self.error(e)
            return
        self.document().print_(printer)
        self._kept_away(
            self.tr("✓ Sent to {printer}").format(printer=printer.printerName() or printer.outputFileName())
        )


class RecoveryKeyDialog(QDialog):
    """A new store's recovery key over the page, this once (Settings › Dataset stores, New Store…; ADR 0021), as the
    New board model dialog shows it for a customer's first board model: Done waits for the tick, and Esc, the window's
    close and a sign-in, which exec(), showing it modal, keeps from the window behind it, do nothing until then."""

    def __init__(
        self,
        parent: QWidget,
        ctx: AppContext,
        store: dict[str, Any],
        error: Callable[[AoiError], object],
        status: Callable[[str], object],
    ) -> None:
        super().__init__(parent)
        self.setMinimumWidth(theme.CARD_W)
        self.recovery = RecoveryKey(ctx, error, status)
        self.recovery.show_key(store)
        self.setWindowTitle(self.recovery.title())
        lay = QVBoxLayout(self)
        lay.addWidget(self.recovery)
        self.btn_done = size_class(button(self.tr("Done"), "primary", self.accept), "T")
        self.recovery.changed.connect(lambda: self.btn_done.setEnabled(self.recovery.kept.isChecked()))
        self.btn_done.setEnabled(False)
        row = QHBoxLayout()
        row.addStretch(1)
        row.addWidget(self.btn_done)
        lay.addStretch(1)
        lay.addLayout(row)
        self.recovery.btn_save.setFocus()

    def reject(self) -> None:
        """Esc or the window's close: refused while the key waits for its tick."""
        if self.recovery.holding():
            self.recovery.kept.setFocus()
            return
        super().reject()

    def done(self, result: int) -> None:
        """The key is forgotten as the dialog closes, whichever way."""
        if self.recovery.holding():
            return
        self.recovery.clear()
        super().done(result)
