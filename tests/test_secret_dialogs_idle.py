"""REQ-USR-004, #499 (SEC-6, found reviewing the senior review's UI-1 fix): a dialog that shows a secret this once and
will not close until it is kept, the New board model dialog's key step, Settings' New Store… and an Admin's recovery
code, no longer keeps an Admin's session open with no time limit. Past `idle_minutes` the session ends under it as at
any other time; the dialog takes the secret off the screen, kept, hides its buttons, says why and offers Sign In as
Admin…; an Engineer signed in sees it hidden still, and the Admin it is for sees it again, to save and keep."""

from __future__ import annotations

import time
from collections.abc import Iterator
from pathlib import Path

import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QFileDialog, QWidget
from pytestqt.qtbot import QtBot

from aoi.core.services import AppContext
from aoi.ui.board_model_dialog import NewBoardModelDialog
from aoi.ui.held_secret import HeldSecretDialog
from aoi.ui.main_window import MainWindow
from aoi.ui.pages.recovery_key import RecoveryKeyDialog
from aoi.ui.recovery_code_dialog import RecoveryCodeDialog
from tests.test_dataset_stores import as_admin
from tests.test_first_board_model_store import BETA, shell

CODE = "AAAAA BBBBB CCCCC DDDDD EEEEE"


@pytest.fixture(autouse=True)
def none_left_open() -> Iterator[None]:
    """A dialog still holding its secret refuses the close qtbot gives it, so it is hidden here, or it would stay the
    active modal widget for the next test."""
    yield
    for w in QApplication.topLevelWidgets():
        if isinstance(w, HeldSecretDialog):
            w.hide()
            w.deleteLater()


def modal(qtbot: QtBot, dialog: HeldSecretDialog) -> HeldSecretDialog:
    """`dialog` shown modal as exec() shows it, without its event loop, so the test drives the idle end under it."""
    qtbot.addWidget(dialog)
    dialog.setWindowModality(Qt.WindowModality.ApplicationModal)
    dialog.show()
    qtbot.waitExposed(dialog)
    assert QApplication.activeModalWidget() is dialog
    return dialog


def idle_end(win: MainWindow, ctx: AppContext) -> None:
    win.input.last = time.monotonic() - ctx.settings.idle_minutes * 60
    assert win.check_idle() and ctx.role == "Operator"
    assert [e["before"]["user"] for e in ctx.audit_entries(action="user.idle_end")] == ["admin"]


def signs_in(monkeypatch: pytest.MonkeyPatch, win: MainWindow, *users: str) -> list[str | None]:
    """Switch User answered by `users` in turn; the names it was opened with are returned as they come."""
    asked: list[str | None] = []
    who = iter(users)
    monkeypatch.setattr(win, "switch_user", lambda name=None: asked.append(name) or win.set_user(next(who)))
    return asked


def hidden(dialog: HeldSecretDialog, *secret: QWidget) -> bool:
    """The secret's widgets off the screen, the reason and Sign In as Admin… on it, focused."""
    return (
        dialog.isVisible()
        and dialog.holding()
        and not any(w.isVisible() for w in secret)
        and dialog.away.isVisible()
        and dialog.btn_admin.isVisible()
        and QWidget.focusWidget(dialog) is dialog.btn_admin
    )


def test_req_usr_004_an_idle_end_hides_a_new_board_models_recovery_key(
    qtbot: QtBot, ctx: AppContext, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The Admin made a customer's first board model and walked away from its key: the session ends, the key is
    hidden and kept, Esc does not close the dialog; an Engineer may not see it, the Admin sees it again, saves it and
    closes."""
    win = shell(qtbot, ctx)
    asked = signs_in(monkeypatch, win, "engineer", "admin")
    dialog = NewBoardModelDialog(win)
    modal(qtbot, dialog)
    dialog.board.setText("BETA-1")
    dialog.customer.setCurrentText(BETA)
    dialog.make()
    key = dialog.recovery.key.text()
    assert dialog.holding() and len(key.split()) == 13
    idle_end(win, ctx)
    assert hidden(dialog, dialog.recovery, dialog.recovery.key, dialog.btn_done) and dialog.recovery.key.text() == ""
    assert dialog.away.text() == (
        "The session of admin ended, so the recovery key of Beta Boards is hidden, kept until an Admin signs in to"
        " save it. The station does nothing else until then."
    )
    dialog.reject()  # Esc, or the window's close
    assert dialog.isVisible() and QWidget.focusWidget(dialog) is dialog.btn_admin
    dialog.btn_admin.click()
    assert ctx.role == "Engineer" and hidden(dialog, dialog.recovery, dialog.btn_done)
    dialog.btn_admin.click()
    assert asked == ["admin", "admin"] and ctx.role == "Admin"
    assert dialog.recovery.key.text() == key and dialog.recovery.isVisible() and not dialog.away.isVisible()
    assert not dialog.btn_admin.isVisible() and QWidget.focusWidget(dialog) is dialog.recovery.btn_save
    dest = tmp_path / "key.txt"
    monkeypatch.setattr(QFileDialog, "getSaveFileName", staticmethod(lambda *a: (str(dest), "")))
    dialog.recovery.btn_save.click()
    dialog.recovery.kept.setChecked(True)
    dialog.btn_done.click()
    assert not dialog.isVisible() and key.split()[0] in dest.read_text(encoding="utf-8")


def test_req_usr_004_an_idle_end_hides_a_new_stores_recovery_key(
    qtbot: QtBot, ctx: AppContext, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Settings' New Store… key, left open: hidden at the idle end, shown again to an Admin."""
    win = shell(qtbot, ctx)
    store = as_admin(ctx, ctx.create_store, BETA)
    win.set_user("admin")
    signs_in(monkeypatch, win, "admin")
    dialog = RecoveryKeyDialog(win, ctx, store, lambda e: None, win.status)
    modal(qtbot, dialog)
    key = dialog.recovery.key.text()
    idle_end(win, ctx)
    assert hidden(dialog, dialog.recovery, dialog.btn_done) and dialog.recovery.key.text() == ""
    assert dialog.away.text().startswith("The session of admin ended, so the recovery key of Beta Boards is hidden")
    dialog.btn_admin.click()
    assert dialog.recovery.key.text() == key and dialog.btn_done.isVisible() and not dialog.btn_admin.isVisible()


def test_req_usr_004_an_idle_end_hides_an_admins_recovery_code_from_all_but_that_admin(
    qtbot: QtBot, ctx: AppContext, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The recovery code is the Admin's own: hidden at the idle end and from an Engineer, shown again to that Admin."""
    win = shell(qtbot, ctx)
    asked = signs_in(monkeypatch, win, "engineer", "admin")
    dialog = RecoveryCodeDialog(win, CODE)
    modal(qtbot, dialog)
    idle_end(win, ctx)
    secret = (dialog.code_label, dialog.btn_save, dialog.btn_print, dialog.btn_done)
    assert hidden(dialog, *secret) and dialog.code_label.text() == ""
    assert dialog.away.text() == (
        "The session of admin ended, so their recovery code is hidden, kept until admin signs in again to save it. The"
        " station does nothing else until then."
    )
    dialog.reject()
    assert dialog.isVisible()
    dialog.btn_admin.click()
    assert hidden(dialog, *secret)
    dialog.btn_admin.click()
    assert asked == ["admin", "admin"] and dialog.code_label.text() == CODE and dialog.btn_save.isVisible()
    assert not dialog.btn_admin.isVisible()


def test_req_usr_004_a_kept_secret_or_another_dialog_is_closed_as_before(qtbot: QtBot, ctx: AppContext) -> None:
    """A recovery code already saved closes at the idle end as Cancel would; the session ends with no dialog left."""
    win = shell(qtbot, ctx)
    dialog = RecoveryCodeDialog(win, CODE)
    modal(qtbot, dialog)
    dialog._kept("✓ Saved to E:\\code.txt")
    idle_end(win, ctx)
    assert not dialog.isVisible() and QApplication.activeModalWidget() is None


def test_req_usr_004_another_admin_may_close_a_hidden_recovery_code_without_it(
    qtbot: QtBot, ctx: AppContext, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An Admin who never comes back does not hold the station: another Admin signed in at Sign In as Admin… still sees
    no code, but may press Close Without the Code, which forgets it; the Admin it was for gets a new one after Reset
    Password. Neither the Operator nor an Engineer sees that button (review of #499)."""
    win = shell(qtbot, ctx)
    ctx.add_user("kim", "Admin")
    asked = signs_in(monkeypatch, win, "engineer", "kim")
    dialog = RecoveryCodeDialog(win, CODE)
    modal(qtbot, dialog)
    idle_end(win, ctx)
    assert not dialog.btn_drop.isVisible()
    dialog.btn_admin.click()
    assert ctx.role == "Engineer" and not dialog.btn_drop.isVisible()
    dialog.btn_admin.click()
    assert asked == ["admin", "admin"] and ctx.user == "kim" and dialog.code_label.text() == ""
    assert dialog.btn_drop.isVisible() and not dialog.btn_save.isVisible()
    assert dialog.away.text().startswith("Only admin may see this recovery code. Close Without the Code")
    dialog.btn_drop.click()
    assert not dialog.isVisible() and dialog.code == "" and QApplication.activeModalWidget() is None
