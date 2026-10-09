"""Settings › Dataset stores (REQ-TRN-017, ADR 0010; Datasets stage 3 of 4): the customers' encrypted dataset stores,
Admin only as the page is, and the steps on them, each an inline sheet in the table's place, never a dialog over the
page. New Store… shows the new store's recovery sheet this once, with Print Sheet…."""

from __future__ import annotations

import html
from typing import TYPE_CHECKING, Any

from PySide6.QtCore import Qt
from PySide6.QtGui import QAction, QKeySequence, QTextDocument
from PySide6.QtPrintSupport import QPrintDialog, QPrinter
from PySide6.QtWidgets import QCheckBox, QDialog, QGroupBox, QHBoxLayout, QLabel, QLineEdit, QVBoxLayout, QWidget

from ...errors import AoiError
from ...times import to_local
from .base import button, fill_table, make_table

if TYPE_CHECKING:
    from .settings import SettingsPage


class StoresPanel(QGroupBox):
    """The stores, oldest first, and their steps. One sheet shows at a time, in the place of the table and the step
    buttons, its title naming the store, so the page fits a 1600 x 900 screen with any of them open; a sign-in closes
    it, so the recovery sheet never stays on screen for the next user."""

    def __init__(self, page: SettingsPage) -> None:
        super().__init__()
        self.setTitle(self.tr("Dataset stores"))
        self.page, self.ctx = page, page.ctx
        self.rows: list[dict[str, Any]] = []
        self.made: dict[str, str] | None = None  # the store New Store… made, with its sheet, until Close
        lay = QVBoxLayout(self)
        heads = [self.tr("Customer"), self.tr("Key id"), self.tr("Created"), self.tr("Board models")]
        self.table = make_table([*heads, self.tr("Shredded")], sortable=False)
        self.table.itemSelectionChanged.connect(self._sync)
        lay.addWidget(self.table, 1)
        self.none = QLabel(
            self.tr(
                "No dataset store yet. New Store… makes one for a customer; a board model moved into it is encrypted"
                " under its key."
            )
        )
        self.none.setObjectName("muted")
        self.none.setWordWrap(True)
        lay.addWidget(self.none)
        self.steps = QWidget()
        row = QHBoxLayout(self.steps)
        row.setContentsMargins(0, 0, 0, 0)
        self.btn_new = button(self.tr("New Store…"), slot=self._new)
        row.addWidget(self.btn_new)
        row.addStretch(1)
        lay.addWidget(self.steps)
        self.sheets: list[QGroupBox] = []
        self._new_sheet(lay)
        self._recovery_sheet(lay)
        self.close_sheet()

    def _sheet(self, lay: QVBoxLayout, title: str, esc: bool = True) -> tuple[QGroupBox, QVBoxLayout]:
        """An inline sheet in the table's place; Esc closes it unless `esc` is off."""
        g = QGroupBox(title)
        if esc:
            a = QAction(self, shortcut=QKeySequence(Qt.Key.Key_Escape))
            a.setShortcutContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
            a.triggered.connect(self.close_sheet)
            g.addAction(a)
        lay.addWidget(g)
        self.sheets.append(g)
        return g, QVBoxLayout(g)

    def _buttons(self, sl: QVBoxLayout, *buttons: QWidget) -> None:
        """A sheet's last row: its buttons, then the room left below them, so the sheet reads from the top."""
        row = QHBoxLayout()
        for b in buttons:
            row.addWidget(b)
        row.addStretch(1)
        sl.addLayout(row)
        sl.addStretch(1)

    def _new_sheet(self, lay: QVBoxLayout) -> None:
        self.new_sheet, sl = self._sheet(lay, self.tr("New dataset store"))
        fields = QHBoxLayout()
        fields.addWidget(QLabel(self.tr("Customer")))
        self.customer = QLineEdit()
        self.customer.textChanged.connect(self._sync)
        self.customer.returnPressed.connect(self._create)
        fields.addWidget(self.customer, 1)
        sl.addLayout(fields)
        self.btn_create = button(self.tr("Create"), slot=self._create)
        self._buttons(sl, self.btn_create, button(self.tr("Cancel"), slot=self.close_sheet))

    def _recovery_sheet(self, lay: QVBoxLayout) -> None:
        """The key as the recovery sheet prints it, shown this once: Close waits for the tick, and Esc does nothing."""
        self.recovery_sheet, sl = self._sheet(lay, "", esc=False)
        note = QLabel(
            self.tr(
                "Shown this once. Print it and keep it apart from the station: with it, Restore Key… opens the store on"
                " another PC, and anyone who holds it and a copy of the files can read them."
            )
        )
        note.setWordWrap(True)
        self.recovery_ids = QLabel()
        self.recovery_ids.setObjectName("muted")
        self.recovery_key = QLabel()  # 13 groups of four on two lines; not selectable, so never on the clipboard
        self.recovery_key.setObjectName("recoveryKey")
        self.kept = QCheckBox(self.tr("I have printed it and will keep it apart from the station"))
        self.kept.toggled.connect(self._sync)
        for w in (note, self.recovery_ids, self.recovery_key, self.kept):
            sl.addWidget(w)
        self.btn_done = button(self.tr("Close"), slot=self.close_sheet)
        self._buttons(sl, button(self.tr("Print Sheet…"), slot=self._print), self.btn_done)

    def refresh(self) -> None:
        """The table again, the same store selected; the first when none was."""
        picked = self.picked()
        self.rows = self.ctx.stores()
        shown = [
            [s["customer"], s["key_id"][:8], to_local(s["created_at"]), ", ".join(s["board_models"])]
            + [to_local(s["shredded_at"]) if s["shredded_at"] else ""]
            for s in self.rows
        ]
        self.table.blockSignals(True)
        fill_table(self.table, shown)
        uuids = [s["uuid"] for s in self.rows]
        if uuids:
            self.table.selectRow(uuids.index(picked["uuid"]) if picked and picked["uuid"] in uuids else 0)
        self.table.blockSignals(False)
        self.none.setVisible(not self.rows)
        self._sync()

    def picked(self) -> dict[str, Any] | None:
        """The store selected in the table."""
        i = self.table.currentRow()
        return self.rows[i] if 0 <= i < len(self.rows) and self.table.selectionModel().hasSelection() else None

    def _sync(self) -> None:
        self.btn_create.setEnabled(bool(self.customer.text().strip()))
        self.btn_done.setEnabled(self.kept.isChecked())

    def _open(self, sheet: QGroupBox, focus: QWidget) -> None:
        """`sheet` in the table's place: the table hidden first, as a sheet shown beside it grew the window (923 px)."""
        for w in (self.table, self.none, self.steps, *self.sheets):
            w.setVisible(w is sheet)
        self._sync()
        focus.setFocus()

    def close_sheet(self) -> None:
        """Back to the step buttons, the recovery sheet and anything typed cleared."""
        self.made = None
        self.recovery_key.clear()
        self.recovery_ids.clear()
        self.kept.setChecked(False)
        self.customer.clear()
        for g in self.sheets:
            g.hide()
        self.table.show()
        self.none.setVisible(not self.rows)
        self.steps.show()
        self._sync()

    def _new(self) -> None:
        self._open(self.new_sheet, self.customer)

    def _create(self) -> None:
        """Make the store, then show its recovery sheet in the sheet's place."""
        if not self.btn_create.isEnabled():
            return
        try:
            store = self.ctx.create_store(self.customer.text())
        except AoiError as e:
            self.page.error(e)
            return
        self.refresh()
        self.table.selectRow([s["uuid"] for s in self.rows].index(store["uuid"]))
        self.made = {k: str(store[k]) for k in ("uuid", "customer", "key_id", "sheet", "created_at")}
        title = self.tr("Recovery sheet for {customer}").format(customer=store["customer"])
        self.recovery_sheet.setTitle(title)
        self.recovery_ids.setText(self.tr("Store {uuid} · key id {key_id}").format(**self.made))
        groups = store["sheet"].split()
        self.recovery_key.setText(" ".join(groups[:7]) + "\n" + " ".join(groups[7:]))
        self._open(self.recovery_sheet, self.kept)

    def recovery_document(self, made: dict[str, str]) -> QTextDocument:
        """The recovery sheet as Print Sheet… prints it: the customer, the store, the key id, the day and the key."""
        groups = made["sheet"].split()
        lines = [
            f"<h2>{html.escape(self.recovery_sheet.title())}</h2>",
            f"<p>{html.escape(self.recovery_ids.text())} · {html.escape(to_local(made['created_at']))}</p>",
            f'<p style="font-family: monospace; font-size: 20pt">{" ".join(groups[:7])}<br>{" ".join(groups[7:])}</p>',
            "<p>{}</p>".format(
                html.escape(
                    self.tr(
                        "Keep this sheet locked away, apart from the station. With it, an Admin types the key into"
                        " Restore Key… on another PC or Windows account. Anyone who holds it and a copy of the store's"
                        " files can read them. Destroy it when the store is shredded."
                    )
                )
            ),
        ]
        doc = QTextDocument()
        doc.setHtml("".join(lines))
        return doc

    def _print(self) -> None:
        printer = QPrinter(QPrinter.PrinterMode.HighResolution)
        if self.made is not None and QPrintDialog(printer, self).exec() == QDialog.DialogCode.Accepted:
            self.recovery_document(self.made).print_(printer)
