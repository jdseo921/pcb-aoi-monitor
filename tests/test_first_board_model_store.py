"""REQ-TRN-017 for B2 of the 2026-10 business-readiness brief (decision D2; ADR 0021): a customer's first board model
makes the customer's encrypted dataset store and puts the board model in it, in the New board model dialog, which shows
the store's recovery key once, with Save to File… and Print…, and a tick it cannot be left without. A system that keeps
keys in memory only makes no store (AOI-TRN-053). Settings › Dataset stores keeps the key ids, Restore Key… and Shred
Store… for an Admin under its Advanced tick."""

from __future__ import annotations

from pathlib import Path
from typing import Any, cast

import pytest
from PySide6.QtCore import Qt
from PySide6.QtGui import QTextDocument
from PySide6.QtPrintSupport import QPrintDialog
from PySide6.QtWidgets import QDialog, QFileDialog
from pytestqt.qtbot import QtBot

from aoi.config import Settings
from aoi.core import crypto
from aoi.core.services import AppContext
from aoi.data import credentials
from aoi.errors import AoiError
from aoi.ui.board_model_dialog import NewBoardModelDialog
from aoi.ui.main_window import MainWindow
from aoi.ui.pages.settings import SettingsPage
from tests.test_dataset_stores import as_admin, refusal

BETA = "Beta Boards"


def shell(qtbot: QtBot, ctx: AppContext, role: str = "admin") -> MainWindow:
    win = MainWindow(ctx)
    qtbot.addWidget(win)
    win.resize(1600, 900)
    win.show()
    qtbot.waitExposed(win)
    win.set_user(role)
    return win


def opened(qtbot: QtBot, win: MainWindow) -> NewBoardModelDialog:
    """The dialog + New opens, shown without its event loop, so a test presses its buttons."""
    dialog = NewBoardModelDialog(win)
    qtbot.addWidget(dialog)
    dialog.show()
    qtbot.waitExposed(dialog)
    return dialog


def test_req_trn_017_a_customers_first_board_model_makes_its_store(
    ctx: AppContext, keys: credentials.MemoryCredentials
) -> None:
    """In one transaction: the board model, the customer's new store and the board model in it, audited as
    board_model.create, store.create and store.move_in; the sheet is the key the key store holds. The customer's next
    board model, its name typed in another case, goes in the same store with no sheet; the same call again returns it
    as it is, writing nothing."""
    made = as_admin(ctx, ctx.create_customer_board_model, " BETA-1 ", f" {BETA} ")
    store = made["store"]
    assert (made["board_model"], store["customer"], store["board_models"]) == ("BETA-1", BETA, ["BETA-1"])
    assert crypto.key_from_sheet(made["sheet"]) == keys.read(credentials.STORE_PREFIX + store["uuid"])
    made_by = ["board_model.create", "recipe.default", "store.create", "store.move_in"]  # its default recipe too
    assert [e["action"] for e in reversed(ctx.audit_entries())][-4:] == made_by
    second = as_admin(ctx, ctx.create_customer_board_model, "BETA-2", "beta boards")
    assert second["sheet"] is None and second["store"]["uuid"] == store["uuid"]
    assert second["store"]["board_models"] == ["BETA-1", "BETA-2"] and len(ctx.stores()) == 1
    before = ctx.audit_entries()
    again = as_admin(ctx, ctx.create_customer_board_model, "BETA-2", BETA)
    assert again["sheet"] is None and again["store"]["uuid"] == store["uuid"] and ctx.audit_entries() == before


def test_req_trn_017_a_board_model_store_refusal_writes_nothing(
    ctx: AppContext, keys: credentials.MemoryCredentials, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Refused, nothing written: no customer; a board model that exists in no store (an Admin moves it in on Settings);
    one in another customer's store; an Engineer (Admin only). A move that fails leaves no store and no key behind."""
    ctx.ensure_board_model("PLAIN")
    assert refusal(as_admin, ctx, ctx.create_customer_board_model, "NEW", " ")[0] == "AOI-TRN-044"
    code, why = refusal(as_admin, ctx, ctx.create_customer_board_model, "PLAIN", BETA)
    assert (code, why) == ("AOI-TRN-044", "board model PLAIN exists already; an Admin moves it in on Settings")
    as_admin(ctx, ctx.create_customer_board_model, "ACME-1", "Acme")
    code, why = refusal(as_admin, ctx, ctx.create_customer_board_model, "ACME-1", BETA)
    assert (code, why) == ("AOI-TRN-044", "ACME-1 is in the store of Acme, and a board model never leaves it")
    assert refusal(ctx.create_customer_board_model, "BETA-1", BETA)[0] == "AOI-USR-001"
    monkeypatch.setattr(AppContext, "move_in", lambda *a, **k: (_ for _ in ()).throw(OSError("disk full")))
    with pytest.raises(OSError):
        as_admin(ctx, ctx.create_customer_board_model, "BETA-1", BETA)
    assert [s["customer"] for s in ctx.stores()] == ["Acme"] and "BETA-1" not in ctx.board_models()
    assert [n for n in keys._secrets if n.startswith(credentials.STORE_PREFIX)] == [
        credentials.STORE_PREFIX + ctx.stores()[0]["uuid"]
    ]


def test_req_trn_017_no_store_where_keys_live_in_memory_only(workspace: Settings) -> None:
    """On a system whose key store keeps keys in memory only (any but Windows: `credentials.MEMORY`), a store's key
    would be gone when the app closes: New Store… and a customer's first board model are refused with AOI-TRN-053,
    which says why, and nothing is made, the board model either. A board model with no customer is made as before."""
    ctx = AppContext(workspace, credentials.MemoryCredentials(forgets=True))
    assert credentials.forgets(credentials.MEMORY) and not credentials.forgets(credentials.MemoryCredentials())
    with pytest.raises(AoiError) as refused:
        as_admin(ctx, ctx.create_store, BETA)
    assert refused.value.code == "AOI-TRN-053" and "keeps a store's key in memory only" in str(refused.value.what)
    with pytest.raises(AoiError) as refused:
        as_admin(ctx, ctx.create_customer_board_model, "BETA-1", BETA)
    assert refused.value.code == "AOI-TRN-053"
    assert ctx.stores() == [] and ctx.board_models() == [] and ctx.audit_entries(action="store.create") == []
    ctx.ensure_board_model("IN-HOUSE")
    assert ctx.board_models() == ["IN-HOUSE"]
    ctx.close()


def test_req_trn_017_the_recovery_key_is_saved_whole_and_audited(ctx: AppContext, tmp_path: Path) -> None:
    """Save to File… writes the sheet whole and audits where it went, never the key; a file that cannot be written is
    AOI-LOG-002, the old file as it was, and so is a file in the workspace, whose backups hold the files it opens."""
    store = as_admin(ctx, ctx.create_store, BETA)
    dest = tmp_path / "usb" / "beta.txt"
    as_admin(ctx, ctx.save_recovery_sheet, store["uuid"], f"key {store['sheet']}\n", dest)
    assert dest.read_text(encoding="utf-8") == f"key {store['sheet']}\n"
    [entry] = ctx.audit_entries(action="store.sheet_saved")
    assert entry["object_uuid"] == store["uuid"] and store["sheet"] not in str(entry)
    blocked = tmp_path / "file"
    blocked.write_text("in the way")
    with pytest.raises(AoiError) as refused:
        as_admin(ctx, ctx.save_recovery_sheet, store["uuid"], "x", blocked / "beta.txt")
    assert refused.value.code == "AOI-LOG-002" and blocked.read_text() == "in the way"
    with pytest.raises(AoiError) as refused:
        as_admin(ctx, ctx.save_recovery_sheet, store["uuid"], "x", ctx.settings.root / "exports" / "beta.txt")
    assert refused.value.code == "AOI-LOG-002" and "never saved in the workspace" in str(refused.value.what)
    assert not (ctx.settings.root / "exports" / "beta.txt").exists()
    assert len(ctx.audit_entries(action="store.sheet_saved")) == 1


def test_req_trn_017_the_dialog_makes_the_store_and_shows_its_key_once(
    qtbot: QtBot,
    ctx: AppContext,
    keys: credentials.MemoryCredentials,
    dialogs: list[tuple[str, str]],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """An Admin names the board model and a new customer: the line says Create makes the store; Create makes both and
    shows the recovery key in the form's place. Done, Esc and Cancel do nothing until the tick, which waits for Save
    to File… or Print…; Save to File… writes the customer, the store, the key id and the key. Done closes it, the key
    forgotten, and the header selects the board model, saying which store holds it."""
    win = shell(qtbot, ctx)
    dialog = opened(qtbot, win)
    assert dialog.windowTitle() == "New board model" and not dialog.btn_create.isEnabled()
    assert dialog.customer.isEnabled() and dialog.customer.currentText() == ""
    assert dialog.what.text().startswith("No customer: its images stay unencrypted in the workspace")
    qtbot.keyClicks(dialog.board, "BETA-1")
    dialog.customer.setCurrentText(BETA)
    assert dialog.what.text().startswith(f"{BETA} has no dataset store yet: Create makes one")
    dialog.btn_create.click()
    store = ctx.store_of("BETA-1") or {}
    assert store["customer"] == BETA and dialog.made == "BETA-1"
    assert dialog.steps.currentWidget() is dialog.key_step and dialog.windowTitle() == f"Recovery key for {BETA}"
    lines = dialog.recovery.key.text().split("\n")
    assert crypto.key_from_sheet(" ".join(lines)) == keys.read(credentials.STORE_PREFIX + store["uuid"])
    assert not dialog.recovery.kept.isEnabled() and not dialog.btn_done.isEnabled()
    qtbot.keyClick(dialog, Qt.Key.Key_Escape)
    dialog.reject()
    assert dialog.isVisible() and dialog.steps.currentWidget() is dialog.key_step
    dest = tmp_path / "usb" / "beta.txt"
    monkeypatch.setattr(QFileDialog, "getSaveFileName", staticmethod(lambda *a: (str(dest), "")))
    dialog.recovery.btn_save.click()
    saved = dest.read_text(encoding="utf-8")
    for said in (f"Recovery key for {BETA}", store["uuid"], store["key_id"], *lines):
        assert said in saved, said
    assert dialog.recovery.kept.isEnabled() and not dialog.btn_done.isEnabled()
    dialog.recovery.kept.click()
    dialog.btn_done.click()
    assert dialog.result() == QDialog.DialogCode.Accepted and not dialog.isVisible()
    assert dialog.recovery.key.text() == "" and dialog.recovery.made is None and dialogs == []


def test_req_trn_017_new_board_model_from_the_header(
    qtbot: QtBot, ctx: AppContext, dialogs: list[tuple[str, str]], monkeypatch: pytest.MonkeyPatch
) -> None:
    """+ New: with Print… in place of Save to File…, the dialog's key step ends as above and the header selects the
    board model, its store named on the status bar; the customer's next board model goes in its store with no key shown;
    one with no customer is in no store; an existing board model in no store named with a customer is refused, the
    form kept as typed. An Engineer's customer list is greyed, saying an Admin names it, and Create makes a board model
    in no store."""
    win = shell(qtbot, ctx)
    printed: list[str] = []
    monkeypatch.setattr(QPrintDialog, "exec", lambda self: QDialog.DialogCode.Accepted)
    monkeypatch.setattr(QTextDocument, "print_", lambda self, printer: printed.append(self.toPlainText()))
    seen: list[NewBoardModelDialog] = []

    def answer(name: str, customer: str = "") -> None:
        def exec_(dialog: NewBoardModelDialog) -> int:
            seen.append(dialog)
            dialog.board.setText(name)
            dialog.customer.setCurrentText(customer)
            dialog.make()
            if dialog.steps.currentWidget() is dialog.key_step:
                dialog.recovery.btn_print.click()
                dialog.recovery.kept.click()
                dialog.btn_done.click()
            return dialog.result()

        monkeypatch.setattr(NewBoardModelDialog, "exec", exec_)

    answer("BETA-1", BETA)
    win.new_board_model()
    assert win.board_model == "BETA-1" and len(printed) == 1 and f"Recovery key for {BETA}" in printed[0]
    assert win.statusBar().currentMessage() == f"Board model BETA-1 is in the encrypted dataset store of {BETA}."
    answer("BETA-2", BETA.upper())
    win.new_board_model()
    assert seen[-1].steps.currentWidget() is seen[-1].form and len(printed) == 1
    assert (ctx.store_of("BETA-2") or {})["customer"] == BETA and win.board_model == "BETA-2"
    answer("IN-HOUSE")
    win.new_board_model()
    assert ctx.store_of("IN-HOUSE") is None and win.board_model == "IN-HOUSE"
    answer("IN-HOUSE", BETA)
    win.new_board_model()
    assert [d[0] for d in dialogs] == ["AOI-TRN-044 Dataset store not changed"]
    assert seen[-1].result() != QDialog.DialogCode.Accepted and seen[-1].board.text() == "IN-HOUSE"
    win.set_user("engineer")
    dialog = opened(qtbot, win)
    assert not dialog.customer.isEnabled()
    assert dialog.customer.toolTip() == "Creating a board model in a customer's dataset store needs the Admin role."
    assert "An Admin makes a customer's board model" in dialog.what.text()
    dialog.board.setText("ENG-1")
    dialog.btn_create.click()
    assert dialog.result() == QDialog.DialogCode.Accepted and ctx.store_of("ENG-1") is None


def test_req_trn_017_settings_keeps_the_advanced_steps_under_a_tick(
    qtbot: QtBot, ctx: AppContext, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Settings › Dataset stores shows the customer, created, board models and shredded columns and New Store… and
    Move Board Model In…; the Advanced tick shows the key id column, Restore Key… and Shred Store…, an Admin's still.
    A sign-in turns it off. New Store…'s recovery key has Save to File… and Print… as the dialog's has."""
    as_admin(ctx, ctx.create_customer_board_model, "BETA-1", BETA)
    win = shell(qtbot, ctx)
    assert win.navigate("Settings")
    panel = cast(SettingsPage, win.pages["Settings"]).stores
    assert panel.btn_new.isVisible() and panel.btn_move.isVisible() and panel.advanced.isVisible()
    assert panel.table.isColumnHidden(1) and not panel.btn_restore.isVisible() and not panel.btn_shred.isVisible()
    panel.advanced.click()
    assert not panel.table.isColumnHidden(1) and panel.btn_restore.isVisible() and panel.btn_shred.isVisible()
    win.set_user("engineer")
    win.set_user("admin")
    assert win.navigate("Settings")
    assert not panel.advanced.isChecked() and panel.table.isColumnHidden(1) and not panel.btn_shred.isVisible()
    panel.btn_new.click()
    panel.customer.setText("Gamma")
    panel.btn_create.click()
    recovery = panel.recovery
    assert panel.recovery_sheet.title() == "Recovery key for Gamma" and recovery.btn_save.isVisible()
    assert recovery.btn_print.isVisible() and not recovery.kept.isEnabled() and not panel.btn_done.isEnabled()
    printed: list[Any] = []
    monkeypatch.setattr(QPrintDialog, "exec", lambda self: QDialog.DialogCode.Accepted)
    monkeypatch.setattr(QTextDocument, "print_", lambda self, printer: printed.append(1))
    recovery.btn_print.click()
    recovery.kept.click()
    panel.btn_done.click()
    assert printed == [1] and not panel.recovery_sheet.isVisible() and recovery.key.text() == ""
