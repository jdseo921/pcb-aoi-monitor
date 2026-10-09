"""REQ-TRN-017 on screen (Datasets stage, 3 of 4): Settings › Dataset stores, Admin only as the page is, lists the
customers' encrypted dataset stores and takes the steps on them in inline sheets in the table's place (ADR 0010): New
Store… shows the new store's recovery sheet this once, and Restore Key… takes the key back from it on a new PC."""

from __future__ import annotations

from typing import cast

import pytest
from PySide6.QtCore import Qt
from PySide6.QtGui import QTextDocument
from PySide6.QtPrintSupport import QPrintDialog
from PySide6.QtWidgets import QApplication, QDialog, QTableWidget
from pytestqt.qtbot import QtBot

from aoi.core import crypto
from aoi.core.services import AppContext
from aoi.data import credentials
from aoi.times import to_local
from aoi.ui.pages.base import cell_text
from aoi.ui.pages.settings import SettingsPage
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
