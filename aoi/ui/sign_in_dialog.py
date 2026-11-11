"""Switch User's dialog (REQ-USR-002; ADR 0002, decision 1): an Operator picks their name; an Engineer or Admin types
their password, or at their first sign-in chooses one and types it again. A refusal (AOI-USR-004, -005) shows its coded
dialog and leaves this one open. The fields never echo and are cleared once the call returns or the dialog closes.
An Admin who lost their password presses Use Recovery Code…, types the code and chooses a new one (REQ-USR-005)."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from PySide6.QtWidgets import QComboBox, QDialog, QHBoxLayout, QLabel, QLineEdit, QVBoxLayout

from ..core import passwords
from ..errors import AoiError
from . import theme
from .errors import phrase_text, show_error
from .pages.base import button, role_text, size_class

if TYPE_CHECKING:
    from .main_window import MainWindow


class SignInDialog(QDialog):
    """`signed_in` names the user signed in once the dialog is accepted."""

    def __init__(self, shell: MainWindow, name: str | None = None) -> None:
        super().__init__(shell)
        self.shell, self.ctx = shell, shell.ctx
        self.setWindowTitle(self.tr("Switch user"))
        self.setMinimumWidth(theme.CARD_W)
        self.signed_in: str | None = None
        self.recovering = False  # Use Recovery Code… pressed: the code, then a new password twice
        self.users: list[dict[str, Any]] = self.ctx.users()
        self.pins = self.ctx.users_with_pins()  # Operators with a PIN, where the station asks for one (REQ-USR-003)
        lay = QVBoxLayout(self)
        lay.addWidget(QLabel(self.tr("User")))
        self.user = size_class(QComboBox(), "T")
        for u in self.users:
            self.user.addItem(self.tr("{user} ({role})").format(user=u["name"], role=role_text(u["role"])))
        picked = name or self.ctx.user  # the first Admin, from the first-run guide; else who is signed in
        self.user.setCurrentIndex(next((i for i, u in enumerate(self.users) if u["name"] == picked), 0))
        self.user.currentIndexChanged.connect(self._leave_recovery)
        lay.addWidget(self.user)
        self.hint = QLabel()  # what the fields below ask for this user
        self.hint.setObjectName("muted")
        self.hint.setWordWrap(True)
        lay.addWidget(self.hint)
        self.code = size_class(QLineEdit(), "T")  # a standing secret until used: never echoed, as a password
        self.code.setEchoMode(QLineEdit.EchoMode.Password)
        self.code.setPlaceholderText(self.tr("Recovery code"))
        self.code.textChanged.connect(self._sync)
        lay.addWidget(self.code)
        self.password, self.again = self._field(), self._field()
        lay.addWidget(self.password)
        lay.addWidget(self.again)
        row = QHBoxLayout()
        self.btn_recover = size_class(button(self.tr("Use Recovery Code…"), slot=self.use_code), "T")
        row.addWidget(self.btn_recover)
        row.addStretch(1)
        row.addWidget(size_class(button(self.tr("Cancel"), slot=self.reject), "T"))
        self.btn_sign_in = size_class(button(self.tr("Sign In"), "primary", self.sign_in), "T")
        self.btn_sign_in.setDefault(True)
        row.addWidget(self.btn_sign_in)
        lay.addLayout(row)
        self._sync()

    def _field(self) -> QLineEdit:
        field = size_class(QLineEdit(), "T")
        field.setEchoMode(QLineEdit.EchoMode.Password)
        field.setMaxLength(passwords.MAX_LENGTH * 2)  # longer is refused with its reason, not cut off unseen
        field.textChanged.connect(self._sync)
        return field

    def chosen(self) -> dict[str, Any]:
        return self.users[max(self.user.currentIndex(), 0)]

    def needs(self) -> bool:
        """Whether the user chosen types a secret: an Engineer or Admin always, an Operator where the station asks."""
        return self.chosen()["role"] != "Operator" or self.ctx.settings.operator_pin

    def use_code(self) -> None:
        self.recovering = True
        self._sync()
        self.code.setFocus()

    def _leave_recovery(self) -> None:
        self.recovering = False
        self.code.clear()
        self._sync()

    def _sync(self) -> None:
        """The fields this user needs, and Sign In on once they are filled (and agree, for a secret chosen)."""
        user, needs = self.chosen(), self.needs()
        pin = user["role"] == "Operator"
        setup = needs and (user["name"] not in self.pins if pin else user["status"] == "setup" or self.recovering)
        # an account in set-up whose password only an Admin's sign-in hands over: said now, not after typing (M3)
        held = setup and not pin and not self.recovering and not self.ctx.may_set_up(str(user["role"]))
        self.btn_recover.setVisible(user["role"] == "Admin" and user["status"] == "active" and not self.recovering)
        self.code.setVisible(self.recovering)
        self.password.setVisible(needs and not held)
        self.again.setVisible(setup and not held)
        if pin:
            self.password.setPlaceholderText(self.tr("New PIN") if setup else self.tr("PIN"))
            self.again.setPlaceholderText(self.tr("Type the new PIN again"))
            hint = (
                self.tr("{user} has no PIN yet: choose 4 to 6 digits.") if setup else self.tr("Type the PIN of {user}.")
            )
            self.hint.setText(hint.format(user=user["name"]))
        else:
            self.password.setPlaceholderText(self.tr("New password") if setup else self.tr("Password"))
            self.again.setPlaceholderText(self.tr("Type the new password again"))
            if held:
                refused = AoiError("AOI-USR-009", name=user["name"])
                self.hint.setText(" ".join([phrase_text(refused.what), phrase_text(refused.action)]))
            elif self.recovering:
                hint = self.tr("Type the recovery code of {user}, then choose a new password and type it again.")
                self.hint.setText(hint.format(user=user["name"]))
            elif setup:
                hint = self.tr(
                    "{user} has no password yet: choose one of {low} to {high} characters, such as a few words."
                )
                self.hint.setText(hint.format(user=user["name"], low=passwords.MIN_LENGTH, high=passwords.MAX_LENGTH))
            else:
                self.hint.setText(self.tr("Type the password of {user}.").format(user=user["name"]))
        self.hint.setVisible(needs)
        typed, again = self.password.text(), self.again.text()
        short = not pin and len(passwords.normal(typed)) < passwords.MIN_LENGTH  # counted as the service counts
        if setup and not held and typed:  # a new secret: what still stops Sign In, as it is typed (M2)
            if short:
                said = self.tr("{count} of at least {low} characters.")
                self.hint.setText(said.format(count=len(passwords.normal(typed)), low=passwords.MIN_LENGTH))
            elif again and typed != again:
                self.hint.setText(self.tr("The two PINs differ.") if pin else self.tr("The two passwords differ."))
        ready = not held and (not needs or (bool(typed) and (not setup or (typed == again and not short))))
        self.btn_sign_in.setEnabled(ready and (not self.recovering or bool(self.code.text().strip())))
        self._fit()

    def _fit(self) -> None:
        """The dialog grown to hold the hint whole: another user's hint, a larger font or another language can need a
        line more than the one it opened with, and a wrapped label cut at its foot hides what to type (REQ-SET-006)."""
        lay = self.layout()
        if lay is None or not self.isVisible():
            return
        lay.activate()
        need = lay.totalHeightForWidth(self.width()) if lay.hasHeightForWidth() else lay.sizeHint().height()
        if need > self.height():
            self.resize(self.width(), need)

    def done(self, result: int) -> None:
        self.code.clear()
        self.password.clear()  # Cancel too: no typed secret outlives the dialog
        self.again.clear()
        super().done(result)

    def sign_in(self) -> None:
        if not self.btn_sign_in.isEnabled():  # Enter in a field before the button is on
            return
        name = str(self.chosen()["name"])
        password = self.password.text() if self.needs() else None
        code = self.code.text()
        self.password.clear()
        self.again.clear()
        self.code.clear()
        try:
            if self.recovering:
                self.ctx.recover(name, code, password or "")  # audited, a new code made to show once
            else:
                self.ctx.sign_in(name, password=password)  # audited, and the station's next start signs them in again
        except AoiError as e:
            show_error(self, self.ctx.report_error(e, "Switch user"))
            return
        self.signed_in = name
        self.accept()
