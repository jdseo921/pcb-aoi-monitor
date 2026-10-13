"""Settings › Dataset stores (REQ-TRN-017, ADR 0010; Datasets stage 3 of 4): the customers' encrypted dataset stores,
Admin only as the page is, and the steps on them, each an inline sheet in the table's place, never a dialog over the
page. New Store… shows the new store's recovery key this once (`RecoveryKey`: Save to File…, Print… and a tick it waits
for); Move Board Model In… encrypts a board model's files in a store, on the pool, and finishes a move that stopped. A
customer's first board model makes its store in the New board model dialog (ADR 0021), so these are the plain flow's
spare steps; the key ids, Restore Key…, which takes a key back on a new PC or Windows account, and Shred Store…, red,
which names what it deletes and waits for the customer's name typed, show under the Advanced tick (B2 of the 2026-10
business-readiness brief)."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from PySide6.QtCore import Qt
from PySide6.QtGui import QAction, QKeySequence
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QVBoxLayout,
    QWidget,
)

from ...errors import AoiError
from ...times import to_local
from .. import theme
from ..widgets.busy import BusyOverlay
from ..widgets.flow import FlowLayout
from .base import button, fill_table, make_table, size_class
from .recovery_key import RecoveryKey

if TYPE_CHECKING:
    from .settings import SettingsPage

KEY_LETTERS = 52  # a recovery sheet's base32 letters and digits, in 13 groups of four (aoi/core/crypto.py, sheet)
KEY_ID = 1  # the table's Key id column, shown under the Advanced tick


def typed_letters(text: str) -> int:
    """How many of a recovery sheet's letters and digits `text` holds, spaces and hyphens aside, as the key is read."""
    return sum(c not in " -\t\n" for c in text)


class StoresPanel(QGroupBox):
    """The stores, oldest first, and their steps. One sheet shows at a time, in the place of the table and the step
    buttons, its title naming the store, so the page fits a 1600 x 900 screen with any of them open; a sign-in closes
    it, so the recovery key never stays on screen for the next user, and turns Advanced off."""

    def __init__(self, page: SettingsPage) -> None:
        super().__init__()
        self.setTitle(self.tr("Dataset stores"))
        self.page, self.ctx = page, page.ctx
        self.rows: list[dict[str, Any]] = []
        self.left: dict[str, int] = {}  # by store UUID: the files a shred stopped part-way left (store_contents)
        lay = QVBoxLayout(self)
        heads = [self.tr("Customer"), self.tr("Key id"), self.tr("Created"), self.tr("Board models")]
        self.table = make_table([*heads, self.tr("Shredded")], sortable=False)
        self.table.itemSelectionChanged.connect(self._sync)
        lay.addWidget(self.table, 1)
        self.none = QLabel(
            self.tr(
                "No dataset store yet. A customer's first board model makes one: + New in the header, with the"
                " customer named. New Store… makes one here; a board model moved into it is encrypted under its key."
            )
        )
        self.none.setObjectName("muted")
        self.none.setWordWrap(True)
        lay.addWidget(self.none)
        # The plain steps, then the Advanced tick and the steps it shows: the key ids, Restore Key… and Shred Store…,
        # an Admin's still, out of the plain flow (B2 of the 2026-10 business-readiness brief). Two buttons a row: four
        # are wider than the column at the presenter theme's 18 pt (A4 of the brief).
        self.steps = QWidget()
        rows = QVBoxLayout(self.steps)
        rows.setContentsMargins(0, 0, 0, 0)
        self.btn_new = button(self.tr("New Store…"), slot=self._new)
        self.btn_move = button(self.tr("Move Board Model In…"), slot=self._move)
        self.advanced = size_class(QCheckBox(self.tr("Advanced: key ids, Restore Key… and Shred Store…")), "T")
        self.advanced.toggled.connect(self._show_advanced)
        self.btn_restore = button(self.tr("Restore Key…"), slot=self._restore)
        self.btn_shred = button(self.tr("Shred Store…"), "danger", self._shred)  # red, last, never the default
        self.advanced_steps = QWidget()
        plain, advanced = (FlowLayout(gap=theme.ROW_GAP, right=True) for _ in range(2))  # two lines if narrow (#104)
        for row, row_buttons in (plain, (self.btn_new, self.btn_move)), (advanced, (self.btn_restore,)):
            for b in row_buttons:
                row.addWidget(b)
            row.add_stretch()
        advanced.addWidget(self.btn_shred)  # last, apart from the others
        advanced.setContentsMargins(0, 0, 0, 0)
        self.advanced_steps.setLayout(advanced)
        rows.addLayout(plain)
        rows.addWidget(self.advanced)
        rows.addWidget(self.advanced_steps)
        lay.addWidget(self.steps)
        self.sheets: list[QGroupBox] = []
        self._new_sheet(lay)
        self._recovery_sheet(lay)
        self._restore_sheet(lay)
        self._move_sheet(lay)
        self._shred_sheet(lay)
        self.busy_move = BusyOverlay(self, self.tr("Moving the files in…"))
        self.busy_shred = BusyOverlay(self, self.tr("Shredding the store…"))
        self._show_advanced(False)
        self.close_sheet()

    def _show_advanced(self, on: bool) -> None:
        """The key ids, Restore Key… and Shred Store… shown or not."""
        self.table.setColumnHidden(KEY_ID, not on)
        self.advanced_steps.setVisible(on)

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
        """The new store's key, shown this once: Close waits for the tick, which waits for Save to File… or Print…, and
        Esc does nothing."""
        self.recovery_sheet, sl = self._sheet(lay, "", esc=False)
        self.recovery = RecoveryKey(self.ctx, self.page.error, lambda said: self.page.shell.status(said))
        self.recovery.changed.connect(self._sync)
        sl.addWidget(self.recovery)
        self.btn_done = button(self.tr("Close"), slot=self.close_sheet)
        self._buttons(sl, self.btn_done)

    def _restore_sheet(self, lay: QVBoxLayout) -> None:
        self.restore_sheet, sl = self._sheet(lay, "")
        how = QLabel(
            self.tr(
                "Type the 13 groups of four from its recovery sheet, in any case, with or without spaces or hyphens."
            )
        )
        how.setWordWrap(True)
        sl.addWidget(how)
        self.typed = QLineEdit()
        self.typed.textChanged.connect(self._sync)
        self.typed.returnPressed.connect(self._restore_key)
        sl.addWidget(self.typed)
        self.typed_count = QLabel()
        self.typed_count.setObjectName("muted")
        sl.addWidget(self.typed_count)
        self.btn_restore_key = button(self.tr("Restore"), slot=self._restore_key)
        self._buttons(sl, self.btn_restore_key, button(self.tr("Cancel"), slot=self.close_sheet))

    def _move_sheet(self, lay: QVBoxLayout) -> None:
        self.move_sheet, sl = self._sheet(lay, "")
        how = QLabel(
            self.tr(
                "Its images and its frozen versions' manifests are encrypted under the store's key where they are. A"
                " board model never leaves its store."
            )
        )
        how.setWordWrap(True)
        sl.addWidget(how)
        fields = QHBoxLayout()
        fields.addWidget(QLabel(self.tr("Board model")))
        self.board_box = QComboBox()  # those in no store, then the store's own, to finish a move that stopped
        self.board_box.currentIndexChanged.connect(self._sync)
        fields.addWidget(self.board_box, 1)
        sl.addLayout(fields)
        self.btn_move_in = button(self.tr("Move In"), slot=self._move_in)
        self._buttons(sl, self.btn_move_in, button(self.tr("Cancel"), slot=self.close_sheet))

    def _shred_sheet(self, lay: QVBoxLayout) -> None:
        self.shred_sheet, sl = self._sheet(lay, "")
        self.shred_what = QLabel()
        self.shred_what.setWordWrap(True)
        sl.addWidget(self.shred_what)
        fields = QHBoxLayout()
        fields.addWidget(QLabel(self.tr("Type the customer's name to shred it")))
        self.confirm = QLineEdit()
        self.confirm.textChanged.connect(self._sync)
        fields.addWidget(self.confirm, 1)
        sl.addLayout(fields)
        self.btn_shred_now = button(self.tr("Shred"), "danger", self._shred_now)
        self._buttons(sl, button(self.tr("Cancel"), slot=self.close_sheet), self.btn_shred_now)

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
        self.left = {}
        for s in self.rows:  # a shred that stopped part-way is finished by Shred Store… again
            if s["shredded_at"]:
                c = self.ctx.store_contents(s["uuid"])
                self.left[s["uuid"]] = c["files"] + c["models"]
        self._sync()

    def picked(self) -> dict[str, Any] | None:
        """The store selected in the table."""
        i = self.table.currentRow()
        return self.rows[i] if 0 <= i < len(self.rows) and self.table.selectionModel().hasSelection() else None

    def sync(self) -> None:
        self._sync()

    def _sync(self) -> None:
        store = self.picked()
        live = store is not None and not store["shredded_at"]
        idle = self.page.idle()
        for b in (self.btn_restore, self.btn_move):
            b.setEnabled(live and idle)
            b.setToolTip("" if live else self.tr("Pick a store that is not shredded"))
        left = store is not None and self.left.get(store["uuid"], 0) > 0
        self.btn_shred.setEnabled((live or left) and idle)
        gone = self.tr("Shredded; nothing of it is left")
        self.btn_shred.setToolTip(gone if store is not None and not live and not left else "")
        board = self.board_box.currentData()
        mine = store is not None and board in store["board_models"]
        self.btn_move_in.setText(self.tr("Finish Moving In") if mine else self.tr("Move In"))
        self.btn_move_in.setEnabled(board is not None and idle)
        self.btn_move_in.setToolTip("" if self.board_box.count() else self.tr("Every board model is in a store"))
        typed = self.confirm.text().strip()
        self.btn_shred_now.setEnabled(store is not None and typed == store["customer"] and idle)
        self.btn_create.setEnabled(bool(self.customer.text().strip()))
        self.btn_done.setEnabled(self.recovery.kept.isChecked())
        n = typed_letters(self.typed.text())
        self.typed_count.setText(self.tr("{n} of {all} characters").format(n=n, all=KEY_LETTERS))
        self.btn_restore_key.setEnabled(n == KEY_LETTERS)

    def _open(self, sheet: QGroupBox, focus: QWidget) -> None:
        """`sheet` in the table's place: the table hidden first, as a sheet shown beside it grew the window (923 px)."""
        for w in (self.table, self.none, self.steps, *self.sheets):
            w.setVisible(w is sheet)
        self._sync()
        focus.setFocus()

    def close_sheet(self) -> None:
        """Back to the step buttons, the recovery key and anything typed cleared."""
        self.recovery.clear()
        self.customer.clear()
        self.typed.clear()
        self.confirm.clear()
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
        self.recovery.show_key(store)
        self.recovery_sheet.setTitle(self.recovery.title())
        self._open(self.recovery_sheet, self.recovery.btn_save)

    def _restore(self) -> None:
        store = self.picked()
        if store is None:
            return
        title = self.tr("Restore the key for {customer}").format(customer=store["customer"])
        self.restore_sheet.setTitle(title)
        self._open(self.restore_sheet, self.typed)

    def _restore_key(self) -> None:
        store = self.picked()
        if store is None or not self.btn_restore_key.isEnabled():
            return
        try:
            self.ctx.restore_store_key(store["uuid"], self.typed.text())
        except AoiError as e:  # a key that is not the store's: the typed text stays, to check each group
            self.page.error(e)
            return
        self.close_sheet()
        said = self.tr("The key for {customer} is saved on this station again")
        self.page.shell.status(said.format(customer=store["customer"]))

    def _move(self) -> None:
        """The board models in no store, then the store's own, whose move Finish Moving In finishes."""
        store = self.picked()
        if store is None:
            return
        title = self.tr("Move a board model into the store for {customer}").format(customer=store["customer"])
        self.move_sheet.setTitle(title)
        self.board_box.blockSignals(True)
        self.board_box.clear()
        for b in self.ctx.board_models():
            if self.ctx.store_of(b) is None:
                self.board_box.addItem(b, b)
        for b in store["board_models"]:
            self.board_box.addItem(self.tr("{board} (finish moving in)").format(board=b), b)
        self.board_box.blockSignals(False)
        self._open(self.move_sheet, self.board_box)

    def _move_in(self) -> None:
        store, board = self.picked(), self.board_box.currentData()
        if store is None or board is None or not self.page.idle():
            return
        customer = store["customer"]

        def moved(n: dict[str, int] | None) -> None:
            self.refresh()
            if n is None:  # stopped before it began
                self._move()
            elif n["left"]:  # Cancel: the board model is in the store, the rest of its files plain until finished
                self._move()
                self.board_box.setCurrentIndex(self.board_box.findData(board))
                said = self.tr("Stopped with {moved} files of {board} moved; Finish Moving In moves the other {left}")
                self.page.shell.status(said.format(moved=n["moved"], board=board, left=n["left"]))
            else:
                self.close_sheet()
                said = self.tr("{moved} files of {board} moved into the store for {customer}, {already} there already")
                self.page.shell.status(said.format(board=board, customer=customer, **n))

        self.page.run_in_background(
            self.ctx.move_in, board, store["uuid"], with_progress=True, on_result=moved, on_cancel=moved,
            on_error=self._failed, busy=self.busy_move,
        )  # fmt: skip

    def _failed(self, _e: BaseException) -> None:
        """A move or shred refused part-way (AOI-TRN-044): the sheet closes on the table as the step left it, and the
        same step finishes it."""
        self.close_sheet()
        self.refresh()

    def _shred(self) -> None:
        """What the shred deletes, as `store_contents` counts it now, and the name to type."""
        store = self.picked()
        if store is None:
            return
        try:
            c = self.ctx.store_contents(store["uuid"])
        except AoiError as e:
            self.page.error(e)
            return
        self.shred_sheet.setTitle(self.tr("Shred the store for {customer}").format(customer=store["customer"]))
        boards = ", ".join(c["board_models"]) or self.tr("no board model")
        if store["shredded_at"]:
            what = self.tr(
                "The shred of this store stopped part-way: {files} file(s) of {boards} and {models} file(s) of their AI"
                " models are left. Shred deletes them."
            )
        else:
            what = self.tr(
                "Shred deletes this station's key, then {files} image and manifest file(s) of {boards} and {models}"
                " file(s) of their AI models and golden boards. Nothing of the store opens again, a backup's copies"
                " included, once whoever holds its recovery sheet destroys it. This cannot be undone."
            )
        self.shred_what.setText(what.format(files=c["files"], models=c["models"], boards=boards))
        self._open(self.shred_sheet, self.confirm)

    def _shred_now(self) -> None:
        store = self.picked()
        if store is None or not self.btn_shred_now.isEnabled():
            return
        customer = store["customer"]

        def shredded(n: dict[str, int] | None) -> None:  # Cancel hides the wait: the key is gone, the shred goes on
            self.close_sheet()
            self.refresh()
            if n is not None:
                said = self.tr(
                    "The store for {customer} is shredded: {files} file(s) and {models} AI model file(s) deleted."
                    " Whoever holds its recovery sheet destroys it now."
                )
                self.page.shell.status(said.format(customer=customer, **n), 0)

        self.page.run_in_background(
            self.ctx.shred_store, store["uuid"], on_result=shredded, on_cancel=shredded,
            on_error=self._failed, busy=self.busy_shred,
        )  # fmt: skip
