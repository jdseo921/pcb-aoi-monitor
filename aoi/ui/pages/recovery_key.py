"""A dataset store's recovery key, shown once (REQ-TRN-017; ADR 0010, ADR 0021): the key as its recovery sheet gives it,
Save to File… and Print…, and a tick that says it is kept, which the step showing it waits for. The tick is off until
the key was saved or printed. The New board model dialog shows it for a customer's first board model, and Settings ›
Dataset stores for New Store…. The key is in a label that cannot be selected, so never on the clipboard, and `clear`
forgets it."""

from __future__ import annotations

import html
import re
from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING, Any

from PySide6.QtCore import QStandardPaths, Signal
from PySide6.QtGui import QTextDocument
from PySide6.QtPrintSupport import QPrintDialog, QPrinter
from PySide6.QtWidgets import QCheckBox, QDialog, QFileDialog, QHBoxLayout, QLabel, QVBoxLayout, QWidget

from ...errors import AoiError
from ...times import to_local
from .base import button, size_class

if TYPE_CHECKING:
    from ...core.services import AppContext


class RecoveryKey(QWidget):
    """The key of the store `show_key` was given, until `clear`; `changed` follows the tick."""

    changed = Signal()

    def __init__(self, ctx: AppContext, error: Callable[[AoiError], object], status: Callable[[str], object]) -> None:
        super().__init__()
        self.ctx, self.error, self.status = ctx, error, status
        self.made: dict[str, str] | None = None  # uuid, customer, key_id, sheet and created_at of the store shown
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        note = QLabel(
            self.tr(
                "Shown this once. Save it to a USB drive or print it, and keep it apart from the station: with it, an"
                " Admin opens the store on another PC, and anyone who holds it and a copy of the files can read them."
            )
        )
        note.setWordWrap(True)
        self.ids = QLabel()
        self.ids.setObjectName("muted")
        self.ids.setWordWrap(True)  # the store's UUID and the key id are wider than the New board model dialog
        self.key = QLabel()  # 13 groups of four on two lines; not selectable, so never on the clipboard
        self.key.setObjectName("recoveryKey")
        self.btn_save = size_class(button(self.tr("Save to File…"), slot=self.save_file), "T")
        self.btn_print = size_class(button(self.tr("Print…"), slot=self.print_sheet), "T")
        row = QHBoxLayout()
        for b in (self.btn_save, self.btn_print):
            row.addWidget(b)
        row.addStretch(1)
        self.kept = size_class(
            QCheckBox(self.tr("I have saved or printed the key and will keep it apart from the station")), "T"
        )
        self.kept.toggled.connect(self.changed)
        for w in (note, self.ids, self.key):
            lay.addWidget(w)
        lay.addLayout(row)
        lay.addWidget(self.kept)
        self.clear()

    def title(self) -> str:
        return self.tr("Recovery key for {customer}").format(customer=self.made["customer"] if self.made else "")

    def show_key(self, store: dict[str, Any]) -> None:
        """`store`'s key, as `create_store` returned it with its `sheet`; the tick off until it is saved or printed."""
        self.made = {k: str(store[k]) for k in ("uuid", "customer", "key_id", "sheet", "created_at")}
        self.ids.setText(self.tr("Store {uuid} · key id {key_id}").format(**self.made))
        groups = self.made["sheet"].split()
        self.key.setText(" ".join(groups[:7]) + "\n" + " ".join(groups[7:]))
        self._keepable(False)

    def clear(self) -> None:
        """The key forgotten: the labels empty, the tick off."""
        self.made = None
        self.key.clear()
        self.ids.clear()
        self._keepable(False)

    def _keepable(self, on: bool) -> None:
        self.kept.setChecked(False)
        self.kept.setEnabled(on)
        self.kept.setToolTip("" if on else self.tr("Save the key to a file or print it first"))

    def _kept_away(self) -> None:
        """Saved or printed: the tick may be ticked now."""
        if not self.kept.isEnabled():
            self._keepable(True)

    def _paragraph(self) -> str:
        return self.tr(
            "Keep this sheet locked away, apart from the station. With it, an Admin types the key into Restore Key… on"
            " another PC or Windows account. Anyone who holds it and a copy of the store's files can read them. Destroy"
            " it when the store is shredded."
        )

    def text(self) -> str:
        """The recovery sheet as Save to File… writes it: the customer, the store, the key id, the day and the key."""
        assert self.made is not None
        groups = self.made["sheet"].split()
        lines = [self.title(), f"{self.ids.text()} · {to_local(self.made['created_at'])}", ""]
        return "\n".join([*lines, " ".join(groups[:7]), " ".join(groups[7:]), "", self._paragraph(), ""])

    def document(self) -> QTextDocument:
        """The recovery sheet as Print… prints it, as `text` words it."""
        assert self.made is not None
        groups = self.made["sheet"].split()
        lines = [
            f"<h2>{html.escape(self.title())}</h2>",
            f"<p>{html.escape(self.ids.text())} · {html.escape(to_local(self.made['created_at']))}</p>",
            f'<p style="font-family: monospace; font-size: 20pt">{" ".join(groups[:7])}<br>{" ".join(groups[7:])}</p>',
            f"<p>{html.escape(self._paragraph())}</p>",
        ]
        doc = QTextDocument()
        doc.setHtml("".join(lines))
        return doc

    def save_file(self) -> None:
        """The sheet as UTF-8 text in a file the user names, offered in Documents under the customer's name; written
        and audited by `AppContext.save_recovery_sheet`, whose refusal (AOI-LOG-002) is shown."""
        if self.made is None:
            return
        stem = re.sub(r"[^A-Za-z0-9]+", "-", self.made["customer"]).strip("-") or "store"
        start = Path(QStandardPaths.writableLocation(QStandardPaths.StandardLocation.DocumentsLocation))
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
        self._kept_away()

    def print_sheet(self) -> None:
        printer = QPrinter(QPrinter.PrinterMode.HighResolution)
        if self.made is not None and QPrintDialog(printer, self).exec() == QDialog.DialogCode.Accepted:
            self.document().print_(printer)
            self._kept_away()
