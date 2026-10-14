"""The first-run guide on Home (REQ-TRN-021; B5 of the 2026-10 business-readiness brief, D4;
docs/sketches/first-run-guide.md): one person sets a board model up in three screens, Board model, Images and Train,
then inspects on Inspection. The guide is a part of Home, not a window of its own: the header and the sidebar stay, and
Show All Steps › shows Home without it: its six cards, or with no board model yet its empty state.

Screen 1 takes the board model's name, checked as it is typed by the rule every new board model meets (ADR 0023), and
its customer, whose encrypted dataset store the board model goes in (`AppContext.create_customer_board_model`, ADR
0021). A customer's first board model makes the store, and its recovery key shows on the screen itself, this once,
with Save to File… and Print…; until I Have Saved the Key, which waits for the key to be saved or printed, the frame
holds still: the sidebar, the header's controls, Switch User and the window's close do nothing (`holding`; Q67, in
place of the New board model dialog's modal key step, its tick and Done). A refusal is said under the control that
raised it, with its code; the guide shows no dialog of its own. An Engineer sees the screen greyed with the role it
needs, as a customer's store is an Admin's; an Operator, who sets nothing up, gets Home's empty state instead."""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from PySide6.QtCore import QEvent, QObject, QStringListModel, Qt, Signal
from PySide6.QtGui import QAction, QKeyEvent, QKeySequence
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCompleter,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QVBoxLayout,
    QWidget,
)

from ...core.services import REQUIRED_ROLE
from ...errors import AoiError
from .. import theme
from ..errors import phrase_text
from .base import QT_TRANSLATE_NOOP, button, role_text, size_class
from .recovery_key import RecoveryKey

if TYPE_CHECKING:
    from .base import Page

STEP_NAMES = (  # the guide's three screens, as its line of steps names them
    QT_TRANSLATE_NOOP("FirstRunGuide", "Board model"),
    QT_TRANSLATE_NOOP("FirstRunGuide", "Images"),
    QT_TRANSLATE_NOOP("FirstRunGuide", "Train"),
)
STORE_CALL = "create_customer_board_model"  # screen 1's call: an Admin's, as a customer's store is (ADR 0021)
ENTER = (Qt.Key.Key_Return, Qt.Key.Key_Enter)


class _PickOnly(QObject):
    """Enter on a row picked in the customers' list picks the name and does nothing else: Qt's completer passes the key
    on to the field, whose Enter is Create's, so picking a customer made the board model at once. With no row picked,
    as when the whole name was typed, Enter is the field's: Create."""

    def __init__(self, field: QLineEdit, popup: QAbstractItemView) -> None:
        super().__init__(field)
        self.field = field
        popup.installEventFilter(self)  # after the completer's own filter, so it runs first

    def eventFilter(self, watched: QObject, e: QEvent) -> bool:  # noqa: N802 (Qt's name)
        if isinstance(e, QKeyEvent) and e.type() == QEvent.Type.KeyPress and e.key() in ENTER:
            if isinstance(watched, QAbstractItemView) and watched.currentIndex().isValid():
                self.field.setText(str(watched.currentIndex().data()))
                watched.hide()
                return True
        return False


class _PressSays(QObject):
    """A press on `control` while it is off says `why()` on the status bar: a touch screen shows no tooltip."""

    def __init__(self, control: QWidget, why: Callable[[], str], status: Callable[[str], object]) -> None:
        super().__init__(control)
        self.control, self.why, self.status = control, why, status
        control.installEventFilter(self)

    def eventFilter(self, watched: QObject, e: QEvent) -> bool:  # noqa: N802 (Qt's name)
        if e.type() == QEvent.Type.MouseButtonPress and not self.control.isEnabled():
            self.status(self.why())
        return False


class FirstRunGuide(QFrame):
    """The guide for the board model in the header, or for none yet (`show_for`). `holding_changed` follows the
    recovery key on screen 1, `made` names a board model made, or found as it was, for the header to select, and
    `cards_wanted` is Show All Steps ›."""

    holding_changed = Signal(bool)
    made = Signal(str)
    cards_wanted = Signal()

    def __init__(self, page: Page) -> None:
        super().__init__()
        self.setObjectName("card")
        self.page, self.ctx = page, page.ctx
        self.status = page.shell.status
        self.shown = 1  # the screen shown: 1 Board model, 2 Images, 3 Train
        self.made_board_model = self.made_customer = ""  # the board model whose recovery key shows, its customer
        lay = QVBoxLayout(self)
        top = QHBoxLayout()
        self.heading = QLabel()
        self.heading.setObjectName("h1")
        self.heading.setWordWrap(True)
        top.addWidget(self.heading, 1)
        self.btn_cards = button(self.tr("Show All Steps ›"), slot=self.cards_wanted.emit)
        _PressSays(self.btn_cards, page.shell.held_text, self.status)  # off only while the frame is held
        top.addWidget(self.btn_cards, 0, Qt.AlignmentFlag.AlignTop)
        lay.addLayout(top)
        self.steps = QLabel()  # ● the screen shown, ✓ a screen done, ○ one to come
        self.steps.setObjectName("guideSteps")
        lay.addWidget(self.steps)
        self._form_step()
        self._key_step()
        lay.addWidget(self.form)
        lay.addWidget(self.key_step)

    # --- screen 1: the board model and its customer --------------------------------------------------------------
    def _form_step(self) -> None:
        self.form = QWidget()
        lay = QVBoxLayout(self.form)
        lay.setContentsMargins(0, 0, 0, 0)
        grid = QGridLayout()
        grid.setColumnStretch(2, 1)
        self.name = QLineEdit()
        self.name.setMinimumWidth(theme.FIELD_W)
        self.name.textChanged.connect(self._typed)
        self.name.returnPressed.connect(self.make_board_model)
        self.name_line = QLabel()  # the name's live check (ADR 0023): its code first when refused
        self.name_line.setObjectName("muted")
        self.name_line.setWordWrap(True)
        self.customer = QLineEdit()
        self.customer.setMinimumWidth(theme.FIELD_W)
        self.customer.textChanged.connect(self._typed)
        self.customer.returnPressed.connect(self.make_board_model)
        self.customer_names = QStringListModel(self)  # the customers with a store, to pick from, never filled in
        self.customers = QCompleter(self.customer_names, self.customer)
        self.customers.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        self.customer.setCompleter(self.customers)
        popup = self.customers.popup()
        assert popup is not None
        _PickOnly(self.customer, popup)
        hints = (
            self.tr("as on the board or its drawing, such as TBOX-A1"),
            self.tr("whose boards these are; your company's name for your own"),
        )
        for n, (label, field, hint) in enumerate(
            ((self.tr("Board model name"), self.name, hints[0]), (self.tr("Customer"), self.customer, hints[1]))
        ):
            muted = QLabel(hint)
            muted.setObjectName("muted")
            muted.setWordWrap(True)
            grid.addWidget(QLabel(label), 2 * n, 0)
            grid.addWidget(field, 2 * n, 1)
            grid.addWidget(muted, 2 * n, 2)
        grid.addWidget(self.name_line, 1, 1, 1, 2)
        lay.addLayout(grid)
        apart = QLabel(
            self.tr("Each customer's images are kept encrypted on this station, apart from every other customer's.")
        )
        apart.setWordWrap(True)
        lay.addWidget(apart)
        self.role_line = QLabel()  # for a role that may not make a customer's board model, the role it needs
        self.role_line.setWordWrap(True)
        lay.addWidget(self.role_line)
        self.refused = QLabel()  # Create's refusal, under it: its code, what happened and what to do
        self.refused.setWordWrap(True)
        self.refused.hide()
        lay.addWidget(self.refused)
        self.btn_create = size_class(button(self.tr("Create  Enter"), "primary", self.make_board_model), "T")
        _PressSays(self.btn_create, self._not_ready, self.status)  # a role's refusal is RoleGates' to say
        row = QHBoxLayout()
        row.addStretch(1)
        row.addWidget(self.btn_create)
        lay.addLayout(row)

    def _key_step(self) -> None:
        self.key_step = QWidget()
        lay = QVBoxLayout(self.key_step)
        lay.setContentsMargins(0, 0, 0, 0)
        self.made_line = QLabel()  # "✓ TBOX-A1 · for Hanil Electronics"
        self.made_line.setWordWrap(True)
        self.key_title = QLabel()
        self.key_title.setObjectName("guideSteps")
        self.key_note = QLabel()
        self.key_note.setWordWrap(True)
        self.recovery = RecoveryKey(self.ctx, self._key_refused, self.status, tick=False)
        self.recovery.note.hide()  # the guide's own sentence, which names the customer, stands above it
        self.recovery.changed.connect(self._key_kept_away)
        for b, key, slot in (
            (self.recovery.btn_save, "Ctrl+S", self.recovery.save_file),
            (self.recovery.btn_print, "Ctrl+P", self.recovery.print_sheet),
        ):
            shortcut = QAction(b.text(), self.key_step)  # its text for F1's list (`keys`)
            b.setText(self.tr("{action}  {key}").format(action=b.text(), key=key))
            shortcut.setShortcut(QKeySequence(key))
            shortcut.triggered.connect(slot)
            self.key_step.addAction(shortcut)  # while the key step shows
        away = QLabel(
            self.tr(
                "Save it on a USB drive that stays away from this station, not the one that brings the images, or"
                " print it."
            )
        )
        away.setWordWrap(True)
        self.key_refused = QLabel()  # a save or print refused (AOI-LOG-002): its code, what happened and what to do
        self.key_refused.setWordWrap(True)
        self.key_refused.hide()
        kept = QAction(self.tr("I Have Saved the Key"), self.key_step)
        kept.setShortcuts([QKeySequence("Enter"), QKeySequence("Return")])  # F1 names the first, "Enter", as the button
        kept.triggered.connect(self.key_kept)
        self.key_step.addAction(kept)
        self.btn_kept = size_class(button(self.tr("I Have Saved the Key  Enter"), "primary", self.key_kept), "T")
        _PressSays(self.btn_kept, self.recovery.unsaved, self.status)
        for w in (self.made_line, self.key_title, self.key_note, self.recovery, away, self.key_refused):
            lay.addWidget(w)
        row = QHBoxLayout()
        row.addStretch(1)
        row.addWidget(self.btn_kept)
        lay.addLayout(row)
        self.key_step.hide()

    def keys(self) -> list[QAction]:
        """The keys of the screen shown, for F1's list of Home's keys."""
        return self.key_step.actions() if not self.key_step.isHidden() else []

    def holding(self) -> bool:
        """The recovery key shows and I Have Saved the Key was not pressed: the frame holds still."""
        return self.recovery.holding()

    def show_for(self, board_model: str | None) -> None:
        """Screen 1 for a workspace with no board model, or with the recovery key of the one just made."""
        self.shown = 1
        holding = self.holding()
        if board_model is None or holding:
            self.heading.setText(self.tr("Set up your first board model"))
        else:
            self.heading.setText(self.tr("Set up {board_model}").format(board_model=board_model))
        marks = ["✓" if holding else "●", "○", "○"]
        self.steps.setText(
            "  ───  ".join(
                f"{mark} {n} {self.tr(name)}" for n, (mark, name) in enumerate(zip(marks, STEP_NAMES, strict=True), 1)
            )
        )
        self.btn_cards.setEnabled(not holding)
        self.form.setVisible(not holding)
        self.key_step.setVisible(holding)
        if not holding:
            self.customer_names.setStringList([s["customer"] for s in self.ctx.stores() if not s["shredded_at"]])
        self._sync()

    def _typed(self) -> None:
        """A name or a customer typed: a refusal of Create said before goes, as it was of what was typed then."""
        self.refused.clear()
        self.refused.hide()
        self._sync()

    def _sync(self) -> None:
        """Create on while a name a new board model may have and a customer are typed, for an Admin; the line under the
        name says why one is refused, with its code, or that it can be used; I Have Saved the Key on once the key was
        saved or printed."""
        name, customer = self.name.text().strip(), self.customer.text().strip()
        allowed = self.page.gates.may(STORE_CALL)
        refused = self.ctx.board_model_name_refusal(name) if name else None
        if refused is not None:
            self.name_line.setText(" ".join([refused.code, phrase_text(refused.what), phrase_text(refused.action)]))
        else:
            self.name_line.setText(self.tr("✓ {name} can be used.").format(name=name) if name else "")
        self.name_line.setVisible(bool(name))  # empty for a role that may not type one: a sign-in clears the fields
        role = self.tr("Setting up a board model for a customer needs the {role} role.")  # the guide's words (sketch)
        role = role.format(role=role_text(REQUIRED_ROLE[STORE_CALL]))
        for field in (self.name, self.customer):
            self.page.gates.gate(field, STORE_CALL, why=role)
        self.role_line.setText(role)
        self.role_line.setVisible(not allowed)
        ready = bool(name) and bool(customer) and refused is None
        self.page.gates.own_tip(self.btn_create, "" if ready else self.tr("Type a board model name and its customer"))
        self.page.gates.gate(self.btn_create, STORE_CALL, ready, why=role)
        self.btn_kept.setEnabled(self.recovery.saved)

    def _not_ready(self) -> str:
        """Why Create is off, said on a press on it or on Enter: the role it needs, the name's refusal with its code, or
        what is still to type."""
        if self.btn_create in self.page.gates.why:
            return self.page.gates.why[self.btn_create]
        name = self.name.text().strip()
        refused = self.ctx.board_model_name_refusal(name) if name else None
        if refused is not None:
            return " ".join([refused.code, phrase_text(refused.what), phrase_text(refused.action)])
        return self.tr("Type a board model name and its customer")

    def make_board_model(self) -> None:
        """Make the board model in the customer's store, the store first for a customer with none; then the new store's
        recovery key, or, for a customer with a store, the board model at once. A refusal is said under Create."""
        name, customer = self.name.text().strip(), self.customer.text().strip()
        if not self.btn_create.isEnabled() or not name or not customer:  # Enter in a field: why, and the field to fix
            self.status(self._not_ready())
            refused = bool(name) and self.ctx.board_model_name_refusal(name) is not None
            (self.customer if name and not refused else self.name).setFocus()
            return
        try:
            made = self.ctx.create_customer_board_model(name, customer)
        except AoiError as e:
            report = self.ctx.report_error(e, "Home")
            self.refused.setText(" ".join([report.code, phrase_text(report.what), phrase_text(report.action)]))
            self.refused.show()
            return
        self.refused.clear()
        self.refused.hide()
        if made["sheet"] is None:
            said = self.tr("Board model {name} is set up for {customer}.")  # the guide's words: no "store" (sketch)
            self.status(said.format(name=made["board_model"], customer=made["store"]["customer"]))
            self.reset()
            self.made.emit(made["board_model"])
            return
        store = {**made["store"], "sheet": made["sheet"]}
        self.show_key(made["board_model"], store)

    def show_key(self, board_model: str, store: dict[str, Any]) -> None:
        """The new store's recovery key on screen 1, this once, the frame held until I Have Saved the Key."""
        customer = str(store["customer"])
        self.made_board_model, self.made_customer = board_model, customer
        self.recovery.show_key(store)
        self.made_line.setText(self.tr("✓ {name} · for {customer}").format(name=board_model, customer=customer))
        self.key_title.setText(self.recovery.title())
        self.key_note.setText(
            self.tr(
                "If this station's own key is ever lost, this key opens the images of {customer} again. It is shown"
                " only now."
            ).format(customer=customer)
        )
        self.key_refused.hide()
        self.show_for(None)
        self.recovery.btn_save.setFocus()
        self.holding_changed.emit(True)

    def key_kept(self) -> None:
        """I Have Saved the Key: the key forgotten, the frame free, the board model selected; while the key was neither
        saved nor printed, the status bar says so and nothing else happens."""
        if not self.holding():
            return
        if not self.recovery.saved:
            self.status(self.recovery.unsaved())
            return
        board_model, customer = self.made_board_model, self.made_customer
        self.recovery.clear()
        self.reset()
        self.holding_changed.emit(False)
        said = self.tr("Board model {name} is set up for {customer}.")
        self.status(said.format(name=board_model, customer=customer))
        self.made.emit(board_model)

    def _key_kept_away(self) -> None:
        """The key saved or printed: a refusal of a save or print before it is past."""
        if self.recovery.saved:
            self.key_refused.clear()
            self.key_refused.hide()
        self._sync()

    def _key_refused(self, e: AoiError) -> None:
        """A save or print of the key refused (AOI-LOG-002), said under its buttons, logged and alarmed."""
        report = self.ctx.report_error(e, "Home")
        self.key_refused.setText(" ".join([report.code, phrase_text(report.what), phrase_text(report.action)]))
        self.key_refused.show()

    def reset(self) -> None:
        """Screen 1's fields empty again, for the next board model or the next user signed in, with no refusal left from
        what was typed or saved before."""
        for field in (self.name, self.customer):
            field.blockSignals(True)
            field.clear()
            field.blockSignals(False)
        for line in (self.refused, self.key_refused):
            line.clear()
            line.hide()
        self.made_board_model = self.made_customer = ""
        self._sync()
