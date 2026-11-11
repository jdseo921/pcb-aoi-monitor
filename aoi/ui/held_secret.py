"""A dialog that shows a secret this once and will not close until it is kept (#499): the idle end (REQ-USR-004) ends
the session under it, and while someone who may not see the secret is signed in, the dialog hides it, kept, says why
and offers Sign In as Admin…, as the first-run guide's key step does since UI-1 (senior review 2026-11-06)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtWidgets import QDialog, QLabel, QWidget

from .pages.base import button, size_class

if TYPE_CHECKING:
    from ..core.services import AppContext


class HeldSecretDialog(QDialog):
    """`holding`, `may_see`, `show_secret` and `away_text` are the dialog's own; `user_changed`, which the window calls
    after every sign-in and idle end, hides or shows the secret by them. `away` and `btn_admin` go in its layout."""

    def __init__(self, parent: QWidget, ctx: AppContext) -> None:
        super().__init__(parent)
        self.ctx = ctx
        self.owner = ctx.user  # the Admin who saw it, picked first at Sign In as Admin…
        self.away = QLabel()  # why the secret is hidden; empty and hidden while it shows
        self.away.setWordWrap(True)
        self.away.hide()
        self.btn_admin = size_class(button(self.tr("Sign In as Admin…"), "primary", self._sign_in), "T")
        self.btn_admin.hide()

    def holding(self) -> bool:  # the secret is not kept yet: the dialog will not close
        raise NotImplementedError

    def may_see(self) -> bool:  # the user signed in may see the secret: an Admin
        return self.ctx.role == "Admin"

    def show_secret(self, on: bool) -> None:  # the secret and its buttons on the screen, or off it, kept
        raise NotImplementedError

    def away_text(self) -> str:  # what the dialog says while the secret is hidden
        raise NotImplementedError

    def user_changed(self) -> None:
        """After a sign-in or the idle end: the secret off the screen, kept, for one who may not see it, or on it again
        for one who may."""
        if not self.holding():
            return
        hide = not self.may_see()
        self.show_secret(not hide)
        self.away.setText(self.away_text() if hide else "")
        self.away.setVisible(hide)
        self.btn_admin.setVisible(hide)
        self.btn_admin.setDefault(hide)
        if hide:
            self.btn_admin.setFocus()

    def _sign_in(self) -> None:
        """Sign In as Admin…: the window's Switch User over the dialog, the Admin who saw the secret picked first."""
        parent = self.parentWidget()
        switch_user = getattr(parent.window(), "switch_user", None) if parent is not None else None
        if switch_user is not None:
            switch_user(self.owner or None)
