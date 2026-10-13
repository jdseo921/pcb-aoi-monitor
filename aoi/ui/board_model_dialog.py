"""The New board model dialog: the header's + New, and + New board model on Home and the empty pages (B2 of the 2026-10
business-readiness brief, decision D2; ADR 0021). It takes a board model's name and, for an Admin, the customer whose
boards it is. A customer's first board model makes that customer's encrypted dataset store and puts the board model in
it, in this dialog (`AppContext.create_customer_board_model`), then shows the store's recovery key this once
(`RecoveryKey`) with Save to File… and Print…: Done waits for its tick, and Esc and the window's close do nothing until
then. A customer with a store gets the board model in it; no customer makes a board model in no store, as + New did
before, for in-house and demo boards. The name is checked as it is typed, by the rule every call that makes a board
model applies (`AppContext.board_model_name_refusal`; B4 of the brief, D4 part, F9; ADR 0023): a line under it says
why a name is refused, and Create and Enter do nothing until it is one a new board model may have."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from PySide6.QtCore import Qt
from PySide6.QtGui import QKeyEvent
from PySide6.QtWidgets import (
    QComboBox,
    QCompleter,
    QDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from ..errors import AoiError
from . import theme
from .errors import phrase_text, show_error
from .pages.base import RoleGates, button, size_class
from .pages.recovery_key import RecoveryKey

if TYPE_CHECKING:
    from .main_window import MainWindow

STORE_CALL = "create_customer_board_model"  # the call a customer's board model takes: an Admin's


class NewBoardModelDialog(QDialog):
    """The name and the customer, then, for a customer's first board model, its store's recovery key. `made` names the
    board model made, or found as it was, once Create succeeds, and `store` the customer's store it is in, if any."""

    def __init__(self, shell: MainWindow) -> None:
        super().__init__(shell)
        self.shell, self.ctx = shell, shell.ctx
        self.setWindowTitle(self.tr("New board model"))
        self.setMinimumWidth(theme.CARD_W)
        self.made: str | None = None
        self.store: dict[str, Any] | None = None
        self.gates = RoleGates(self, self.ctx, shell.status)
        self.steps = QStackedWidget()
        QVBoxLayout(self).addWidget(self.steps)
        self._form()
        self._key_step()
        self._sync()
        self.board.setFocus()

    def _form(self) -> None:
        self.form = QWidget()
        lay = QVBoxLayout(self.form)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(QLabel(self.tr("Board model name (e.g. TBOX-A1 Rev2)")))
        self.board = QLineEdit()
        self.board.textChanged.connect(self._sync)
        self.board.returnPressed.connect(self.make)
        lay.addWidget(self.board)
        self.name_refusal = QLabel()  # why the name typed is refused, in the refusal's words; hidden for a name allowed
        self.name_refusal.setObjectName("muted")
        self.name_refusal.setWordWrap(True)
        self.name_refusal.hide()
        lay.addWidget(self.name_refusal)
        lay.addWidget(QLabel(self.tr("Customer")))
        self.customer = size_class(QComboBox(), "T")  # a store's customer, or a new one typed; none by default
        self.customer.setEditable(True)
        completer = self.customer.completer()  # a list to pick from, never filled in: "Acme" typed stays "Acme"
        assert completer is not None
        completer.setCompletionMode(QCompleter.CompletionMode.PopupCompletion)
        self.customer.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        for s in self.ctx.stores():
            if not s["shredded_at"]:
                self.customer.addItem(s["customer"])
        self.customer.setCurrentIndex(-1)  # empty, with the placeholder saying what that makes
        line = self.customer.lineEdit()
        assert line is not None
        line.setPlaceholderText(self.tr("None: an in-house or demo board model"))
        line.setClearButtonEnabled(True)  # back to none by touch, once a customer was picked
        line.returnPressed.connect(self.make)
        self.customer.currentTextChanged.connect(self._sync)
        lay.addWidget(self.customer)
        self.gates.gate(self.customer, STORE_CALL)  # greyed for an Engineer, saying an Admin may
        self.what = QLabel()  # what Create does with the customer named, or with none
        self.what.setObjectName("muted")
        self.what.setWordWrap(True)
        lay.addWidget(self.what)
        self.btn_create = size_class(button(self.tr("Create"), "primary", self.make), "T")
        self.btn_create.setDefault(True)
        row = QHBoxLayout()
        row.addStretch(1)
        row.addWidget(size_class(button(self.tr("Cancel"), slot=self.reject), "T"))
        row.addWidget(self.btn_create)
        lay.addStretch(1)
        lay.addLayout(row)
        self.steps.addWidget(self.form)

    def _key_step(self) -> None:
        self.key_step = QWidget()
        lay = QVBoxLayout(self.key_step)
        lay.setContentsMargins(0, 0, 0, 0)
        self.made_line = QLabel()
        self.made_line.setWordWrap(True)
        lay.addWidget(self.made_line)
        self.recovery = RecoveryKey(self.ctx, self._error, self.shell.status)
        self.recovery.changed.connect(self._sync)
        lay.addWidget(self.recovery)
        self.btn_done = size_class(button(self.tr("Done"), "primary", self.accept), "T")
        row = QHBoxLayout()
        row.addStretch(1)
        row.addWidget(self.btn_done)
        lay.addStretch(1)
        lay.addLayout(row)
        self.steps.addWidget(self.key_step)

    def _error(self, e: AoiError) -> None:
        show_error(self, self.ctx.report_error(e, "Board model"))

    def _sync(self) -> None:
        """Create on while a name is typed that a new board model may have; the line under the name says why one is
        refused, with its code, what happened and what to do; the line under the customer says what Create does; Done
        waits for the tick."""
        name, customer = self.board.text().strip(), self.customer.currentText().strip()
        refused = self.ctx.board_model_name_refusal(name) if name else None
        self.btn_create.setEnabled(bool(name) and refused is None)
        if refused is not None:
            self.name_refusal.setText(" ".join([refused.code, phrase_text(refused.what), phrase_text(refused.action)]))
        self.name_refusal.setVisible(refused is not None)
        found = next(
            (s for s in self.ctx.stores() if s["customer"].casefold() == customer.casefold() and not s["shredded_at"]),
            None,
        )
        if not self.gates.may(STORE_CALL):
            said = self.tr(
                "Its images stay unencrypted in the workspace, as for in-house and demo boards. {refusal} An Admin"
                " makes a customer's board model, in the customer's encrypted dataset store."
            ).format(refusal=self.gates.why.get(self.customer, ""))
        elif not customer:
            said = self.tr(
                "No customer: its images stay unencrypted in the workspace, as for in-house and demo boards. Name the"
                " customer for a customer's boards, which go in the customer's encrypted dataset store."
            )
        elif found is not None:
            said = self.tr("It goes in the encrypted dataset store of {customer}.").format(customer=found["customer"])
        else:
            said = self.tr(
                "{customer} has no dataset store yet: Create makes one, puts the board model in it and shows its"
                " recovery key once, to save or print and keep apart from the station."
            ).format(customer=customer)
        self.what.setText(said)
        self.btn_done.setEnabled(self.recovery.kept.isChecked())

    def make(self) -> None:
        """Make the board model, in the customer's store when one is named, the store first for a customer with none;
        a refusal shows its dialog and keeps what was typed. A name the line under it refuses makes nothing, Enter
        included, and shows no dialog: the line says why."""
        name, customer = self.board.text().strip(), self.customer.currentText().strip()
        if not name or self.steps.currentWidget() is not self.form:
            return
        if self.ctx.board_model_name_refusal(name) is not None:
            self._sync()
            return
        try:
            if customer and self.gates.may(STORE_CALL):
                made = self.ctx.create_customer_board_model(name, customer)
            else:
                self.ctx.ensure_board_model(name)  # the service layer refuses an Operator, naming the role it needs
                made = {"board_model": name, "store": None, "sheet": None}
        except AoiError as e:
            self._error(e)
            return
        self.made, self.store = made["board_model"], made["store"]
        if made["sheet"] is None:
            self.accept()
        else:
            self.show_key({**made["store"], "sheet": made["sheet"]})

    def keyPressEvent(self, e: QKeyEvent) -> None:
        """Enter in the form is its fields' own, which Create takes through `make`: it makes nothing for a name the line
        under it refuses, and no default button is pressed after it. Qt made Cancel the default as the dialog opened,
        Create being off, so Enter on an empty or refused name closed the form, and after a refusal's dialog closed it
        too. A focused button takes Enter itself, as do the key step's."""
        if e.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter) and self.steps.currentWidget() is self.form:
            e.accept()
            return
        super().keyPressEvent(e)

    def show_key(self, store: dict[str, Any]) -> None:
        """The new store's recovery key in the form's place, this once."""
        self.recovery.show_key(store)
        self.setWindowTitle(self.recovery.title())
        said = self.tr(
            "Board model {board} is made, in the new encrypted dataset store of {customer}. Its recovery key opens the"
            " store on another PC: this station keeps the key, but a new PC or a reinstalled Windows needs this copy."
        )
        self.made_line.setText(said.format(board=self.made or "", customer=store["customer"]))
        self.steps.setCurrentWidget(self.key_step)
        self.recovery.btn_save.setFocus()
        self._sync()

    def reject(self) -> None:
        """Cancel, Esc or the window's close: refused while the recovery key waits for its tick, which it must not leave
        unread."""
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
