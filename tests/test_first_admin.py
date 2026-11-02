"""The first Admin and their recovery code (REQ-USR-005; ADR 0002, decision 6): the station's first Admin chooses their
password from the first-run guide and is shown a one-time recovery code, stored only as a hash, until it is saved or
printed."""

from __future__ import annotations

import json
import sqlite3
import zipfile
from pathlib import Path
from typing import Any

import pytest
from PySide6.QtWidgets import QDialog, QFileDialog
from pytestqt.qtbot import QtBot

from aoi.core import passwords
from aoi.core.services import AppContext
from aoi.errors import AoiError
from aoi.ui.main_window import MainWindow
from aoi.ui.recovery_code_dialog import RecoveryCodeDialog
from tests.conftest import PASSPHRASE, answer_sign_in


def test_req_usr_005_the_first_admin_gets_a_recovery_code_stored_only_as_a_hash(
    ctx: AppContext, tmp_path: Path
) -> None:
    ctx.set_user("operator")
    ctx.sign_in("admin", password=PASSPHRASE)  # the station's first Admin
    code = ctx.take_recovery_code()
    assert code is not None and len(code.replace(" ", "")) == 25 and ctx.take_recovery_code() is None  # shown once
    uuid = str(ctx.db.user_uuid("admin"))
    stored = ctx.db.recovery_hash(uuid)
    assert stored is not None and stored.startswith("$argon2id$") and code not in stored
    assert passwords.verify(stored, passwords.code_text(code.lower().replace(" ", "-")))  # as typed from the sheet
    assert all("recovery_hash" not in u for u in ctx.users())
    (made,) = ctx.audit_entries(action="user.recovery_code_made")
    assert made["after"] == {"user": "admin"} and code not in json.dumps(made)
    ctx.add_user("kim", "Admin")
    ctx.sign_in("kim", password=PASSPHRASE)  # handed over by the first Admin: no code of their own
    assert ctx.take_recovery_code() is None and ctx.db.recovery_hash(str(ctx.db.user_uuid("kim"))) is None
    with sqlite3.connect(ctx.settings.db_path) as raw:  # nowhere in the database as typed
        dump = "\n".join(raw.iterdump())
    assert code not in dump and code.replace(" ", "") not in dump
    ctx.sign_in("kim", password=PASSPHRASE)
    bundle = ctx.support_bundle(tmp_path / "support.zip") and tmp_path / "support.zip"
    with zipfile.ZipFile(bundle) as z:  # nor in a log, the audit or anything else the bundle carries
        text = "\n".join(z.read(n).decode("utf-8", "replace") for n in z.namelist())
    assert code not in text and code.replace(" ", "") not in text
    ctx.add_user("admin", "Engineer")  # moved off the Admin role: the code goes
    assert ctx.db.recovery_hash(uuid) is None
    ctx.add_user("admin", "Admin")
    ctx.db.set_recovery_hash(uuid, stored)
    ctx.reset_secret("admin")
    assert ctx.db.recovery_hash(uuid) is None  # a reset drops it with the password


def test_req_usr_005_a_code_is_held_only_for_the_admin_signed_in(
    ctx: AppContext, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The review's case: a sign-in refused after the password is stored never shows the code to anyone."""
    ctx.set_user("operator")
    real = ctx.audit

    def refuse_sign_in(action: str, *args: object, **kwargs: object) -> str:
        if action == "user.sign_in":
            raise OSError("disk full")
        return real(action, *args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(ctx, "audit", refuse_sign_in)
    with pytest.raises(OSError):
        ctx.sign_in("admin", password=PASSPHRASE)
    assert ctx.user == "operator" and ctx.take_recovery_code() is None


def test_req_usr_005_the_guide_makes_the_first_admin_and_shows_the_code_until_it_is_saved(
    qtbot: QtBot, ctx: AppContext, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    ctx.set_user("admin")  # a station's first start: the Admin in set-up
    win = MainWindow(ctx)
    qtbot.addWidget(win)
    guide: Any = win.pages["Home"].guide  # type: ignore[attr-defined]
    guide.show_for(None)
    assert not guide.btn_admin.isHidden()
    answer_sign_in(monkeypatch, "admin")
    shown: list[RecoveryCodeDialog] = []

    def exec_(dialog: RecoveryCodeDialog) -> int:
        shown.append(dialog)
        assert not dialog.btn_done.isEnabled()
        dialog.reject()  # Esc: refused until it is saved
        sheet = tmp_path / "code.txt"  # outside the workspace
        monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *a, **k: (str(sheet), ""))
        dialog.save_file()
        assert dialog.code in sheet.read_text(encoding="utf-8") and dialog.btn_done.isEnabled()
        dialog.accept()
        return int(QDialog.DialogCode.Accepted)

    monkeypatch.setattr(RecoveryCodeDialog, "exec", exec_)
    guide.btn_admin.click()
    assert ctx.user == "admin" and len(shown) == 1 and guide.btn_admin.isHidden()
    (saved,) = ctx.audit_entries(action="user.code_saved")
    assert saved["after"]["path"].endswith("code.txt")
    with pytest.raises(AoiError, match="AOI-LOG-002"):
        ctx.save_code_sheet("the sheet", ctx.settings.root / "code.txt")  # never in the workspace
