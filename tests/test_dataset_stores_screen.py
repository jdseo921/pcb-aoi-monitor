"""REQ-TRN-017 on screen (Datasets stage, 3 of 4): Settings › Dataset stores, Admin only as the page is, lists the
customers' encrypted dataset stores and takes the steps on them in inline sheets in the table's place (ADR 0010): New
Store… shows the new store's recovery sheet this once, Restore Key… takes the key back from it on a new PC, Move
Board Model In… encrypts a board model's files on the pool and finishes a move that stopped, and Shred Store… names what
it deletes before it does."""

from __future__ import annotations

from pathlib import Path
from typing import Any, cast

import pytest
from PySide6.QtCore import Qt
from PySide6.QtGui import QTextDocument
from PySide6.QtPrintSupport import QPrintDialog
from PySide6.QtWidgets import QApplication, QDialog, QTableWidget
from pytestqt.qtbot import QtBot

from aoi.core import crypto, stores
from aoi.core.services import AppContext
from aoi.data import credentials
from aoi.times import to_local
from aoi.ui.pages.base import cell_text
from aoi.ui.pages.settings import SettingsPage
from tests.test_dataset_stores import board
from tests.test_req_done_in_v01 import _window


def _settings(qtbot: QtBot, ctx: AppContext) -> SettingsPage:
    """Settings as the seeded Admin opens it, at 1600 x 900, the window active so a sheet's field takes the focus."""
    win = _window(qtbot, ctx, "Admin")
    win.navigate("Settings")
    win.activateWindow()
    qtbot.waitUntil(lambda: QApplication.activeWindow() is win, timeout=5000)
    return cast(SettingsPage, win.pages["Settings"])


def _fits(page: SettingsPage) -> None:
    """The window still 1600 x 900 with the sheet open: a sheet shown before the table hides grew it to 923 px."""
    QApplication.processEvents()
    assert (page.shell.width(), page.shell.height()) == (1600, 900)


def _rows(table: QTableWidget) -> list[list[str]]:
    return [[cell_text(table, r, c) for c in range(table.columnCount())] for r in range(table.rowCount())]


def test_req_trn_017_new_store_shows_its_recovery_sheet_once(
    qtbot: QtBot,
    trained_ctx: AppContext,
    keys: credentials.MemoryCredentials,
    dialogs: list[tuple[str, str]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The table lists the store TINY's frozen version is in. New Store… opens a sheet in the step buttons' place, its
    Create off until a customer is typed; Enter makes the store, selects it and shows its recovery sheet in the sheet's
    place: the store, its key id and the key the key store holds, 13 groups on two lines. Neither Esc nor Close (until
    the tick) leaves it, and Print Sheet… prints the customer, the store, the day and the key. Close clears it; a
    customer with a store already is refused (AOI-TRN-044), nothing made; a sign-in closes the sheet, its key gone."""
    page = _settings(qtbot, trained_ctx)
    panel = page.stores
    [acme] = trained_ctx.stores()
    assert _rows(panel.table) == [["Acme Electronics", acme["key_id"][:8], to_local(acme["created_at"]), "TINY", ""]]
    assert not panel.none.isVisible() and panel.btn_restore.isEnabled() and not panel.recovery_sheet.isVisible()
    panel.btn_new.click()
    assert panel.new_sheet.isVisible() and not panel.steps.isVisible() and QApplication.focusWidget() is panel.customer
    assert not panel.btn_create.isEnabled()
    qtbot.keyClicks(panel.customer, "Beta Boards")
    qtbot.keyClick(panel.customer, Qt.Key.Key_Return)
    beta = next(s for s in trained_ctx.stores() if s["customer"] == "Beta Boards")
    assert (panel.picked() or {})["uuid"] == beta["uuid"]
    assert _rows(panel.table)[1][:2] == ["Beta Boards", beta["key_id"][:8]]
    assert panel.recovery_sheet.isVisible() and not panel.new_sheet.isVisible() and not panel.steps.isVisible()
    assert not panel.table.isVisible()
    _fits(page)
    assert panel.recovery_sheet.title() == "Recovery sheet for Beta Boards"
    assert panel.recovery_ids.text() == f"Store {beta['uuid']} · key id {beta['key_id']}"
    lines = panel.recovery_key.text().split("\n")
    key = keys.read(credentials.STORE_PREFIX + beta["uuid"])
    assert [len(line.split()) for line in lines] == [7, 6] and crypto.key_from_sheet(" ".join(lines)) == key
    qtbot.keyClick(panel.kept, Qt.Key.Key_Escape)
    assert panel.recovery_sheet.isVisible() and not panel.btn_done.isEnabled()
    printed: list[str] = []
    monkeypatch.setattr(QPrintDialog, "exec", lambda self: QDialog.DialogCode.Accepted)
    monkeypatch.setattr(QTextDocument, "print_", lambda self, printer: printed.append(self.toPlainText()))
    next(b for b in panel.recovery_sheet.findChildren(type(panel.btn_done)) if b.text() == "Print Sheet…").click()
    [sheet] = printed
    for said in ("Recovery sheet for Beta Boards", beta["uuid"], beta["key_id"], to_local(beta["created_at"]), *lines):
        assert said in sheet, said
    panel.kept.click()
    panel.btn_done.click()
    assert panel.steps.isVisible() and not panel.recovery_sheet.isVisible()
    assert panel.recovery_key.text() == "" and panel.made is None
    panel.btn_new.click()
    qtbot.keyClicks(panel.customer, " beta boards ")
    panel.btn_create.click()
    assert dialogs[-1][0].startswith("AOI-TRN-044") and len(trained_ctx.stores()) == 2
    assert panel.new_sheet.isVisible() and panel.customer.text() == " beta boards "
    panel.customer.setText("Gamma")
    panel.btn_create.click()
    assert panel.recovery_sheet.isVisible() and panel.recovery_key.text()
    page.shell.set_user("engineer")
    assert panel.recovery_key.text() == "" and not panel.recovery_sheet.isVisible() and panel.made is None


def test_req_trn_017_restore_key_from_the_sheet(
    qtbot: QtBot, trained_ctx: AppContext, keys: credentials.MemoryCredentials, dialogs: list[tuple[str, str]]
) -> None:
    """On a new PC, the key gone from the key store: Restore Key… on the store opens its sheet, Restore off until the 52
    characters are typed, counted as they are typed. Another key's sheet is refused (AOI-TRN-044), what was typed kept
    to check; the store's own, in lower case with hyphens, saves the key again, closes the sheet and says so. A sign-in
    and Esc close the sheet, and a shredded store's Restore Key… is off."""
    page = _settings(qtbot, trained_ctx)
    panel = page.stores
    [acme] = trained_ctx.stores()
    name = credentials.STORE_PREFIX + acme["uuid"]
    key = keys.read(name) or b""
    keys.delete(name)
    panel.btn_restore.click()
    assert panel.restore_sheet.title() == "Restore the key for Acme Electronics"
    assert QApplication.focusWidget() is panel.typed and panel.typed_count.text() == "0 of 52 characters"
    _fits(page)
    wrong = crypto.sheet(bytes(range(32)))
    qtbot.keyClicks(panel.typed, wrong[:14])  # three groups and the spaces after them
    assert panel.typed_count.text() == "12 of 52 characters" and not panel.btn_restore_key.isEnabled()
    panel.typed.setText(wrong)
    assert panel.typed_count.text() == "52 of 52 characters" and panel.btn_restore_key.isEnabled()
    panel.btn_restore_key.click()
    assert dialogs[-1][0].startswith("AOI-TRN-044") and "check each group of four" in dialogs[-1][1]
    assert keys.read(name) is None and panel.restore_sheet.isVisible() and panel.typed.text() == wrong
    panel.typed.setText(crypto.sheet(key).lower().replace(" ", "-"))
    qtbot.keyClick(panel.typed, Qt.Key.Key_Return)
    assert keys.read(name) == key and not panel.restore_sheet.isVisible() and panel.typed.text() == ""
    assert page.shell.statusBar().currentMessage() == "The key for Acme Electronics is saved on this station again"
    panel.btn_restore.click()
    qtbot.keyClicks(panel.typed, wrong[:4])
    page.shell.set_user("admin")  # a sign-in, the same Admin again: the sheet closes, the half-typed key cleared
    assert panel.restore_sheet.isHidden() and panel.typed.text() == "" and panel.steps.isVisible()
    panel.btn_restore.click()
    qtbot.keyClick(panel.typed, Qt.Key.Key_Escape)
    assert not panel.restore_sheet.isVisible() and panel.steps.isVisible()
    trained_ctx.shred_store(acme["uuid"])
    page.on_show()
    assert _rows(panel.table)[0][4] == to_local(trained_ctx.stores()[0]["shredded_at"])
    assert not panel.btn_restore.isEnabled()
    assert panel.btn_restore.toolTip() == "Pick a store that is not shredded"


def _idle(qtbot: QtBot, page: SettingsPage) -> None:
    qtbot.waitUntil(page.idle, timeout=30000)


def test_req_trn_017_move_board_model_in(
    qtbot: QtBot, trained_ctx: AppContext, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Move Board Model In… lists the board models in no store, then the store's own to finish a move that stopped, its
    button then reading Finish Moving In. Move In encrypts the board model's files on the pool and says how many; Cancel
    leaves the rest plain and says how many are left, and Finish Moving In moves them. A shredded store takes none."""
    ctx = trained_ctx
    page = _settings(qtbot, ctx)
    panel = page.stores
    board(ctx, "MOV", tmp_path / "mov", 3, 11)
    board(ctx, "STP", tmp_path / "stp", 4, 12)
    page.on_show()
    panel.btn_move.click()
    assert panel.move_sheet.title() == "Move a board model into the store for Acme Electronics"
    _fits(page)
    items = [panel.board_box.itemText(i) for i in range(panel.board_box.count())]
    assert items == ["MOV", "STP", "TINY (finish moving in)"] and panel.btn_move_in.text() == "Move In"
    panel.board_box.setCurrentIndex(2)
    assert panel.btn_move_in.text() == "Finish Moving In"
    panel.board_box.setCurrentIndex(0)
    panel.btn_move_in.click()
    steps = (panel.btn_move_in, panel.btn_move, panel.btn_restore, panel.btn_shred)
    assert not any(b.isEnabled() for b in steps)  # off while the move runs: its result has not come back yet
    _idle(qtbot, page)
    assert all(b.isEnabled() for b in steps)
    acme = ctx.stores()[0]
    assert (ctx.store_of("MOV") or {})["uuid"] == acme["uuid"] and not panel.move_sheet.isVisible()
    assert all(stores.header_of(Path(s["path"])) is not None for s in ctx.samples("MOV"))
    said = page.shell.statusBar().currentMessage()
    assert said == "3 files of MOV moved into the store for Acme Electronics, 0 there already"
    assert _rows(panel.table)[0][3] == ", ".join(acme["board_models"]) and "MOV" in acme["board_models"]
    encrypt, done = ctx._encrypt_in_place, []

    def cancelled_after_two(store: dict[str, Any], key: bytes, path: Path) -> None:
        encrypt(store, key, path)
        done.append(path)
        if len(done) == 2 and page._bg is not None:
            page._bg.job.cancel()  # as Cancel on the busy overlay does

    monkeypatch.setattr(ctx, "_encrypt_in_place", cancelled_after_two)
    panel.btn_move.click()
    assert panel.board_box.currentData() == "STP"
    panel.btn_move_in.click()
    _idle(qtbot, page)
    said = page.shell.statusBar().currentMessage()
    assert said == "Stopped with 2 files of STP moved; Finish Moving In moves the other 2"
    assert panel.move_sheet.isVisible() and panel.board_box.currentText() == "STP (finish moving in)"
    assert panel.btn_move_in.text() == "Finish Moving In"
    panel.btn_move_in.click()
    _idle(qtbot, page)
    said = page.shell.statusBar().currentMessage()
    assert said == "2 files of STP moved into the store for Acme Electronics, 2 there already"
    assert all(stores.header_of(Path(s["path"])) is not None for s in ctx.samples("STP"))
    ctx.shred_store(acme["uuid"])
    page.on_show()
    assert not panel.btn_move.isEnabled() and panel.btn_move.toolTip() == "Pick a store that is not shredded"


def test_req_trn_017_shred_store_on_screen(
    qtbot: QtBot, trained_ctx: AppContext, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    dialogs: list[tuple[str, str]],
) -> None:  # fmt: skip
    """Shred Store…, red and last in its row, names the customer, the board models and the counts the shred deletes,
    and Shred, red too, waits for the customer's name typed as it is. The shred runs on the pool, says what it deleted,
    and the row shows when. A file that would not go is refused (AOI-TRN-044); Shred Store… then finishes the shred,
    and is off once nothing of the store is left. Esc closes the sheet, and so does a refusal."""
    ctx = trained_ctx
    page = _settings(qtbot, ctx)
    panel = page.stores
    board(ctx, "SHB", tmp_path / "shb", 3, 13)
    beta = ctx.create_store("Beta")
    ctx.move_in("SHB", beta["uuid"])
    page.on_show()
    row = panel.btn_shred.parentWidget().layout()
    assert panel.btn_shred.objectName() == "danger" and row.indexOf(panel.btn_shred) == row.count() - 1
    panel.table.selectRow(1)
    panel.btn_shred.click()
    assert panel.shred_sheet.title() == "Shred the store for Beta"
    _fits(page)
    assert panel.shred_what.text().startswith(
        "Shred deletes this station's key, then 3 image and manifest file(s) of SHB and 0 file(s) of their AI models"
    )
    assert panel.btn_shred_now.objectName() == "danger" and not panel.btn_shred_now.isEnabled()
    qtbot.keyClick(panel.confirm, Qt.Key.Key_Escape)
    assert not panel.shred_sheet.isVisible() and panel.steps.isVisible()
    panel.btn_shred.click()
    qtbot.keyClicks(panel.confirm, "beta")
    assert not panel.btn_shred_now.isEnabled()
    panel.confirm.setText("Beta")
    paths = [Path(s["path"]) for s in ctx.samples("SHB")]
    unlink = Path.unlink

    def held(self: Path, missing_ok: bool = False) -> None:
        if self == paths[1]:
            raise PermissionError(13, "The file is open in another program", str(self))
        unlink(self, missing_ok=missing_ok)

    monkeypatch.setattr(Path, "unlink", held)
    panel.btn_shred_now.click()
    _idle(qtbot, page)
    assert dialogs[-1][0].startswith("AOI-TRN-044") and ctx.stores()[1]["shredded_at"]
    assert not panel.shred_sheet.isVisible() and panel.steps.isVisible()  # the sheet closes on the table as it is
    assert _rows(panel.table)[1][4] == to_local(ctx.stores()[1]["shredded_at"]) and panel.btn_shred.isEnabled()
    monkeypatch.setattr(Path, "unlink", unlink)
    panel.btn_shred.click()
    assert panel.shred_what.text().startswith("The shred of this store stopped part-way: 1 file(s) of SHB")
    panel.confirm.setText("Beta")
    panel.btn_shred_now.click()
    _idle(qtbot, page)
    said = page.shell.statusBar().currentMessage()
    assert said.startswith("The store for Beta is shredded: 1 file(s) and 0 AI model file(s) deleted.")
    assert not any(p.exists() for p in paths) and not panel.shred_sheet.isVisible()
    assert not panel.btn_shred.isEnabled() and panel.btn_shred.toolTip() == "Shredded; nothing of it is left"
