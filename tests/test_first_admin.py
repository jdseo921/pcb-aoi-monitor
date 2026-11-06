"""The first Admin and their recovery code (REQ-USR-005; ADR 0002, decision 6): the station's first Admin chooses their
password from the first-run guide and is shown a one-time recovery code, stored only as a hash, until it is saved or
printed; with it the Admin signs in and chooses a new password after losing theirs; and the demo workspace's Admin
has a known password (docs/demo/README.md), so the demo scripts run unattended."""

from __future__ import annotations

import json
import sqlite3
import zipfile
from pathlib import Path
from typing import Any

import pytest
from PySide6.QtWidgets import QDialog, QFileDialog
from pytestqt.qtbot import QtBot

from aoi.config import Settings
from aoi.core import demo, passwords
from aoi.core.services import AppContext
from aoi.errors import AoiError
from aoi.ui.main_window import MainWindow
from aoi.ui.recovery_code_dialog import RecoveryCodeDialog
from aoi.ui.sign_in_dialog import SignInDialog
from tests.conftest import PASSPHRASE, answer_sign_in

NEW = "a different passphrase for later"


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
    ctx.sign_in("kim", password=PASSPHRASE)  # handed over by the first Admin: a code of their own (SEC-2)
    theirs = ctx.take_recovery_code()
    assert theirs not in (None, code) and ctx.db.recovery_hash(str(ctx.db.user_uuid("kim"))) is not None
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
    """The review's case: a sign-in refused after the password is stored never shows the code to anyone, nor stores
    one no one saw; the next sign-in makes it (senior review 2026-11-06, SEC-2)."""
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
    assert ctx.db.recovery_hash(str(ctx.db.user_uuid("admin"))) is None
    monkeypatch.undo()
    ctx.sign_in("admin", password=PASSPHRASE)  # the password chosen before the refusal
    assert ctx.take_recovery_code() is not None


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


def test_req_usr_005_the_recovery_code_signs_in_once(ctx: AppContext) -> None:
    ctx.sign_in("admin", password=PASSPHRASE)
    code = ctx.take_recovery_code()
    assert code is not None
    ctx.sign_in("operator")
    with pytest.raises(AoiError, match="AOI-USR-015"):
        ctx.recover("admin", "AAAAA BBBBB CCCCC DDDDD EEEEE", NEW)
    (failed,) = ctx.audit_entries(action="user.sign_in_failed")
    assert failed["after"] == {"user": "admin", "start": False, "recovery": True}
    with pytest.raises(AoiError, match="AOI-USR-015"):
        ctx.recover("engineer", code, NEW)  # an Engineer has no code
    with pytest.raises(AoiError, match="AOI-USR-005"):
        ctx.recover("admin", code, "short")
    ctx.recover("admin", code.lower(), NEW)
    assert ctx.user == "admin" and [e["action"] for e in ctx.audit_entries()][:3] == [
        "user.sign_in",
        "user.recovery_code_made",
        "user.recovered",
    ]
    again = ctx.take_recovery_code()
    assert again is not None and again != code
    with pytest.raises(AoiError, match="AOI-USR-015"):
        ctx.recover("admin", code, NEW)  # used once
    ctx.sign_in("operator")
    ctx.sign_in("admin", password=NEW)
    ctx.add_user("kim", "Admin")
    ctx.sign_in("kim", password=PASSPHRASE)
    ctx.reset_secret("admin")
    assert ctx.db.recovery_hash(str(ctx.db.user_uuid("admin"))) is None  # a reset drops it with the password


def test_req_usr_005_an_admin_handed_over_sees_their_code_offered_under_their_name(
    qtbot: QtBot, ctx: AppContext, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Every Admin's code shows at Switch User, and Save to File… offers a file named for them, so a second Admin's
    sheet on the same USB drive is never offered over the first's (senior review 2026-11-06, SEC-2)."""
    win = MainWindow(ctx)
    qtbot.addWidget(win)
    ctx.sign_in("admin", password=PASSPHRASE)  # the Admin who hands kim's account over
    assert ctx.take_recovery_code() is not None
    ctx.add_user("kim", "Admin")
    titles = answer_sign_in(monkeypatch, "kim")
    win.switch_user()
    assert ctx.user == "kim" and titles == ["Switch user", "Recovery code for kim"]
    offered: list[str] = []
    monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda _p, _t, path, _f: offered.append(path) or ("", ""))
    sheet = RecoveryCodeDialog(win, "AAAAA BBBBB CCCCC DDDDD EEEEE")
    sheet.save_file()
    assert [Path(p).name for p in offered] == ["recovery-code-kim.txt"]
    names = []
    for user in ("kim.a", "kim_a", "kim a", "Kim", "KIM", "김민"):
        monkeypatch.setattr(type(ctx), "user", property(lambda _c, u=user: u))
        names.append(sheet.file_name())
    assert len({n.casefold() for n in names}) == 6 and names[-1] == "recovery-code-김민.txt"  # apart, ignoring case
    assert names[0].startswith("recovery-code-kim-a-") and names[3].startswith("recovery-code-Kim-")


def test_req_usr_005_the_sign_in_dialog_takes_the_recovery_code(qtbot: QtBot, ctx: AppContext) -> None:
    ctx.sign_in("admin", password=PASSPHRASE)
    code = ctx.take_recovery_code()
    assert code is not None
    ctx.sign_in("operator")
    win = MainWindow(ctx)
    qtbot.addWidget(win)
    box = SignInDialog(win, "admin")
    assert box.chosen()["name"] == "admin" and not box.btn_recover.isHidden() and box.code.isHidden()
    box.btn_recover.click()
    assert not box.code.isHidden() and not box.again.isHidden() and not box.btn_sign_in.isEnabled()
    box.code.setText(code)
    box.password.setText(NEW)
    box.again.setText(NEW)
    assert box.btn_sign_in.isEnabled()
    box.sign_in()
    assert box.signed_in == "admin" and box.code.text() == "" and ctx.take_recovery_code() not in (None, code)
    box.user.setCurrentIndex(0)  # another user: the code's field goes
    assert box.code.isHidden() and not box.recovering


def test_req_usr_005_the_demo_opens_as_its_admin_whose_password_is_known(workspace: Settings) -> None:
    workspace.root.mkdir(parents=True)
    (workspace.root / demo.MARKER).write_text("{}", encoding="utf-8")
    first = AppContext(workspace)
    try:
        assert first.user == "admin" and first.take_recovery_code() is None
        (made,) = first.audit_entries(action="user.password_set")
        assert made["after"] == {"user": "admin", "demo": True}
        first.sign_in("operator")
        first.sign_in("admin", password=demo.ADMIN_PASSWORD)  # docs/demo/README.md
    finally:
        first.close()
    again = AppContext(workspace)  # opened again: the password is kept, the Admin started
    try:
        assert again.user == "admin" and len(again.audit_entries(action="user.password_set")) == 1
        again.add_user("kim", "Admin")
        again.sign_in("kim", password=PASSPHRASE)  # an Admin handed over in the demo: no code, its workspace reset
        assert again.take_recovery_code() is None and again.db.recovery_hash(str(again.db.user_uuid("kim"))) is None
    finally:
        again.close()


def test_req_usr_005_a_demo_marker_dropped_into_a_workspace_gives_nothing(workspace: Settings) -> None:
    """The review's case: a demo.json dropped into a workspace whose Admin has a password neither starts that Admin nor
    gives anyone the published password; and a workspace that stops being a demo puts its demo Admin back in set-up."""
    first = AppContext(workspace)
    try:
        first.sign_in("admin", password=PASSPHRASE)
        first.add_user("kim", "Admin")  # waiting for a hand-over
    finally:
        first.close()
    (workspace.root / demo.MARKER).write_text("{}", encoding="utf-8")
    dropped = AppContext(workspace)
    try:
        assert dropped.user == "operator" and not dropped.audit_entries(action="user.password_set")[0]["after"].get(
            "demo"
        )
        assert next(u for u in dropped.users() if u["name"] == "kim")["status"] == "setup"
        with pytest.raises(AoiError, match="AOI-USR-004"):
            dropped.sign_in("admin", start=True)
    finally:
        dropped.close()
    folder = workspace.root.parent / "demo-ws"
    folder.mkdir()
    (folder / demo.MARKER).write_text("{}", encoding="utf-8")
    shown = Settings(workspace=str(folder), device="cpu")
    AppContext(shown).close()  # the demo's Admin gets the published password
    (folder / demo.MARKER).unlink()  # no demo any more
    after = AppContext(shown)
    try:
        assert next(u for u in after.users() if u["name"] == "admin")["status"] == "setup"
        (reset,) = after.audit_entries(action="user.reset")
        assert reset["after"] == {"user": "admin", "demo": True}
    finally:
        after.close()


def test_req_usr_002_the_demos_published_password_is_never_chosen(ctx: AppContext) -> None:
    """Anyone may read the demo's Admin password (docs/demo/README.md), and a start outside the demo puts an Admin who
    has it back in set-up, which on a station with no other Admin leaves its password to whoever claims it next. So
    no one chooses it, at a first sign-in or a recovery, whatever its case, width, spaces or marks, and the station's
    Admin keeps a password across starts (senior review 2026-11-06, SEC-1)."""
    ctx.set_user("operator")
    full_width = "ｓｈｏｗ　ｔｈｅ　ｄｅｍｏ　ｔｏ　ｔｈｅ　ｃｕｓｔｏｍｅｒ"  # NFKC: the same password at a sign-in
    for typed in (demo.ADMIN_PASSWORD, "Show the Demo to the Customer", full_width, "show-the-demo-to-the-customer."):
        with pytest.raises(AoiError, match="AOI-USR-005") as refused:
            ctx.sign_in("admin", password=typed)
        assert "The password chosen for admin is the demo workspace's published password." in str(refused.value)
    assert ctx.user == "operator" and not ctx.audit_entries(action="user.password_set")
    assert next(u for u in ctx.users() if u["name"] == "admin")["status"] == "setup"
    ctx.sign_in("admin", password=PASSPHRASE)
    code = ctx.take_recovery_code()
    assert code is not None
    ctx.sign_in("operator")
    with pytest.raises(AoiError, match="AOI-USR-005"):
        ctx.recover("admin", code, demo.ADMIN_PASSWORD)
    assert not ctx.audit_entries(action="user.recovered")
    workspace = ctx.settings
    ctx.close()
    again = AppContext(workspace)  # the next start: the Admin keeps the password, and nothing is reset
    try:
        assert next(u for u in again.users() if u["name"] == "admin")["status"] == "active"
        assert not again.audit_entries(action="user.reset")
        again.sign_in("admin", password=PASSPHRASE)
    finally:
        again.close()


def test_req_usr_005_a_locked_admin_recovers_and_a_disabled_one_does_not(ctx: AppContext) -> None:
    ctx.sign_in("admin", password=PASSPHRASE)
    code = ctx.take_recovery_code()
    assert code is not None
    uuid = str(ctx.db.user_uuid("admin"))
    ctx.db.execute(
        "UPDATE users SET failed_attempts=100, locked_until=? WHERE uuid=?", (passwords.UNTIL_UNLOCKED, uuid)
    )
    ctx.sign_in("operator")
    with pytest.raises(AoiError, match="AOI-USR-015"):
        ctx.recover("admin", "AAAAA BBBBB CCCCC DDDDD EEEEE", NEW)
    assert next(u for u in ctx.users() if u["uuid"] == uuid)["failed_attempts"] == 100  # a wrong code counts no guess
    ctx.recover("admin", code, NEW)  # the lock does not stop it, and it ends
    row = next(u for u in ctx.users() if u["uuid"] == uuid)
    assert (row["failed_attempts"], row["locked_until"]) == (0, None)
    (recovered,) = ctx.audit_entries(action="user.recovered")
    assert recovered["before"] == {"failed_attempts": 100, "locked_until": passwords.UNTIL_UNLOCKED}
    again = ctx.take_recovery_code()
    assert again is not None
    ctx.add_user("kim", "Admin")
    ctx.sign_in("kim", password=PASSPHRASE)
    ctx.set_user_enabled("admin", False)
    with pytest.raises(AoiError, match="AOI-USR-010"):
        ctx.recover("admin", again, NEW)
