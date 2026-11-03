"""Switch User's dialog (REQ-USR-002; ADR 0002, decision 1): an Operator picks their name; an Engineer or Admin types
their password, or at their first sign-in chooses one and types it again. A refusal (AOI-USR-004, -005) shows its coded
dialog and leaves this one open. The fields never echo and are cleared once the call returns or the dialog closes."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from PySide6.QtWidgets import QComboBox, QDialog, QHBoxLayout, QLabel, QLineEdit, QVBoxLayout

from ..core import passwords
from ..errors import AoiError
from . import theme
from .errors import show_error
from .pages.base import button, role_text, size_class

if TYPE_CHECKING:
    from .main_window import MainWindow


class SignInDialog(QDialog):
    """`signed_in` names the user signed in once the dialog is accepted."""

    def __init__(self, shell: MainWindow) -> None:
        super().__init__(shell)
        self.shell, self.ctx = shell, shell.ctx
        self.setWindowTitle(self.tr("Switch user"))
        self.setMinimumWidth(theme.CARD_W)
        self.signed_in: str | None = None
        self.users: list[dict[str, Any]] = self.ctx.users()
        self.pins = self.ctx.users_with_pins()  # Operators with a PIN, where the station asks for one (REQ-USR-003)
        lay = QVBoxLayout(self)
        lay.addWidget(QLabel(self.tr("User")))
        self.user = size_class(QComboBox(), "T")
        for u in self.users:
            self.user.addItem(self.tr("{user} ({role})").format(user=u["name"], role=role_text(u["role"])))
        self.user.setCurrentIndex(next((i for i, u in enumerate(self.users) if u["name"] == self.ctx.user), 0))
        self.user.currentIndexChanged.connect(self._sync)
        lay.addWidget(self.user)
        self.hint = QLabel()  # what the fields below ask for this user
        self.hint.setObjectName("muted")
        self.hint.setWordWrap(True)
        lay.addWidget(self.hint)
        self.password, self.again = self._field(), self._field()
        lay.addWidget(self.password)
        lay.addWidget(self.again)
        row = QHBoxLayout()
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

    def _sync(self) -> None:
        """The fields this user needs, and Sign In on once they are filled (and agree, for a secret chosen)."""
        user, needs = self.chosen(), self.needs()
        pin = user["role"] == "Operator"
        setup = needs and (user["name"] not in self.pins if pin else user["status"] == "setup")
        self.password.setVisible(needs)
        self.again.setVisible(setup)
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
            if setup:
                hint = self.tr(
                    "{user} has no password yet: choose one of {low} to {high} characters, such as a few words."
                )
                self.hint.setText(hint.format(user=user["name"], low=passwords.MIN_LENGTH, high=passwords.MAX_LENGTH))
            else:
                self.hint.setText(self.tr("Type the password of {user}.").format(user=user["name"]))
        self.hint.setVisible(needs)
        typed = self.password.text()
        self.btn_sign_in.setEnabled(not needs or (bool(typed) and (not setup or typed == self.again.text())))

    def done(self, result: int) -> None:
        self.password.clear()  # Cancel too: no typed secret outlives the dialog
        self.again.clear()
        super().done(result)

    def sign_in(self) -> None:
        if not self.btn_sign_in.isEnabled():  # Enter in a field before the button is on
            return
        name = str(self.chosen()["name"])
        password = self.password.text() if self.needs() else None
        self.password.clear()
        self.again.clear()
        try:
            self.ctx.sign_in(name, password=password)  # audited, and the station's next start signs them in again
        except AoiError as e:
            show_error(self, self.ctx.report_error(e, "Switch user"))
            return
        self.signed_in = name
        self.accept()
