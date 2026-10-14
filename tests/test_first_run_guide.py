"""REQ-TRN-021 for B5 of the 2026-10 business-readiness brief (D4; docs/sketches/first-run-guide.md, Q66, Q67, Q76):
Home opens an empty workspace on the first-run guide. Its first screen takes the board model's name and its customer
and makes the board model in the customer's encrypted dataset store; a customer's first board model shows the store's
recovery key on the screen itself, the frame held until I Have Saved the Key, which waits for the key to be saved or
printed. A refusal is said under the control that raised it, with no dialog. An Engineer sees the screen greyed with
the role it needs, an Operator Home's empty state; Show All Steps › and Show the Guide › switch between the guide and
the cards, until the next sign-in."""

from __future__ import annotations

from pathlib import Path
from typing import cast

import pytest
from PySide6.QtCore import Qt
from PySide6.QtPrintSupport import QPrintDialog
from PySide6.QtWidgets import QApplication, QDialog, QFileDialog, QWidget
from pytestqt.qtbot import QtBot

from aoi.core.services import AppContext
from aoi.ui.main_window import HomePage, MainWindow
from aoi.ui.pages.guide import FirstRunGuide
from tests.test_dataset_stores import as_admin
from tests.test_first_board_model_store import shell

STEPS = "● 1 Board model  ───  ○ 2 Images  ───  ○ 3 Train"


def guide_of(win: MainWindow) -> FirstRunGuide:
    return cast(HomePage, win.pages["Home"]).guide


def typed(qtbot: QtBot, guide: FirstRunGuide, name: str, customer: str) -> None:
    for field, text in ((guide.name, name), (guide.customer, customer)):
        field.clear()
        qtbot.keyClicks(field, text)


def frame_free(win: MainWindow) -> bool:
    return not win.held and win.nav.isEnabled() and win.header.isEnabled()


def test_req_trn_021_an_empty_workspace_opens_on_the_guide(
    qtbot: QtBot, ctx: AppContext, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The Admin's Home with no board model is screen 1, its name field focused: the name is checked as it is typed,
    with its code when refused, and Create waits for a name a new board model may have and a customer. Create, by
    Enter in a field, makes the board model in the customer's new store and shows the store's key on the screen: until
    I Have Saved the Key, which waits for the key to be saved, the sidebar, the header, the page keys and the window's
    close do nothing and say why. The key kept, the header selects the board model and the guide goes on to screen 2."""
    win = shell(qtbot, ctx)
    win.navigate("Home")
    guide = guide_of(win)
    assert guide.isVisible() and not cast(HomePage, win.pages["Home"]).cards.isVisible()
    assert (guide.heading.text(), guide.steps.text()) == ("Set up your first board model", STEPS)
    assert QWidget.focusWidget(win) is guide.name and not guide.btn_create.isEnabled()
    typed(qtbot, guide, "CON", "Hanil Electronics")
    assert guide.name_line.text().startswith("AOI-TRN-019 ") and not guide.btn_create.isEnabled()
    typed(qtbot, guide, "TBOX-A1", "Hanil Electronics")
    assert guide.name_line.text() == "✓ TBOX-A1 can be used." and guide.btn_create.isEnabled()
    qtbot.keyClick(guide.customer, Qt.Key.Key_Return)
    [store] = ctx.stores()
    assert store["board_models"] == ["TBOX-A1"] and guide.holding() and guide.key_step.isVisible()
    assert guide.made_line.text() == "✓ TBOX-A1 · for Hanil Electronics"
    assert guide.steps.text() == STEPS.replace("●", "✓")
    assert not frame_free(win) and not guide.btn_kept.isEnabled() and not guide.btn_cards.isEnabled()
    held = "Save the recovery key to a file or print it, then press I Have Saved the Key."
    assert not win.navigate("Training") and win.statusBar().currentMessage() == held
    assert not win.close() and win.isVisible()  # the key would be lost unsaved
    win.activateWindow()  # a window's keys need it active, which the offscreen platform does not make it by itself
    qtbot.waitUntil(lambda: QApplication.activeWindow() is win)
    qtbot.keyClick(guide.key_step, Qt.Key.Key_Return)  # Enter while the key was neither saved nor printed
    assert guide.holding() and win.statusBar().currentMessage() == "Save the key to a file or print it first"
    dest = tmp_path / "usb" / "recovery-key-Hanil-Electronics.txt"
    dest.parent.mkdir()
    monkeypatch.setattr(QFileDialog, "getSaveFileName", staticmethod(lambda *a: (str(dest), "")))
    guide.recovery.btn_save.click()
    assert dest.read_text(encoding="utf-8").startswith("Recovery key for Hanil Electronics")
    assert guide.recovery.saved_line.text() == f"✓ Saved to {dest}" and guide.btn_kept.isEnabled()
    assert [e["action"] for e in ctx.audit_entries()][0] == "store.sheet_saved"
    qtbot.keyClick(guide.key_step, Qt.Key.Key_Return)
    assert frame_free(win) and not guide.holding() and guide.recovery.made is None
    assert win.board_model == "TBOX-A1" and guide.images.isVisible()  # on to screen 2, its images
    assert guide.steps.text() == "✓ 1 Board model  ───  ● 2 Images  ───  ○ 3 Train"
    said = "Board model TBOX-A1 is set up for Hanil Electronics."
    assert win.statusBar().currentMessage() == said and win.navigate("Training")


def test_req_trn_021_a_customer_with_a_store_and_a_refusal_under_create(
    qtbot: QtBot, ctx: AppContext, monkeypatch: pytest.MonkeyPatch, dialogs: list[tuple[str, str]]
) -> None:
    """A customer with a store, picked from the list by Enter, which picks and makes nothing, or typed in another case:
    the board model goes in that store with no key, and the header selects it. A refusal (AOI-TRN-044, a folder under
    images/ that holds files already) is said under Create with its code, and no dialog; typing again clears it, and
    so does a sign-in."""
    as_admin(ctx, ctx.create_store, "Acme")
    loose = ctx.settings.root / "images" / "LOOSE" / "OK" / "a.png"
    loose.parent.mkdir(parents=True)
    loose.write_bytes(b"an image copied in by hand")
    win = shell(qtbot, ctx)
    win.navigate("Home")
    guide = guide_of(win)
    typed(qtbot, guide, "LOOSE", "")
    qtbot.keyClicks(guide.customer, "Ac")
    popup = guide.customers.popup()
    assert popup is not None
    qtbot.waitUntil(popup.isVisible)
    qtbot.keyClick(popup, Qt.Key.Key_Down)
    qtbot.keyClick(popup, Qt.Key.Key_Return)
    assert guide.customer.text() == "Acme" and ctx.board_models() == []  # picked; nothing made
    guide.btn_create.click()
    assert guide.refused.isVisible() and guide.refused.text().startswith("AOI-TRN-044 ") and dialogs == []
    assert ctx.board_models() == [] and not guide.holding()
    qtbot.keyClicks(guide.name, "2")
    assert not guide.refused.isVisible()
    typed(qtbot, guide, "LOOSE", "Acme")
    guide.btn_create.click()
    assert guide.refused.isVisible()
    win.set_user("engineer")
    win.set_user("admin")
    assert not guide.refused.isVisible() and guide.refused.text() == "" and guide.name.text() == ""
    typed(qtbot, guide, "ACME-1", "acme")
    guide.btn_create.click()
    assert not guide.holding() and frame_free(win) and win.board_model == "ACME-1"
    assert ctx.stores()[0]["board_models"] == ["ACME-1"]
    said = "Board model ACME-1 is set up for Acme."
    assert win.statusBar().currentMessage() == said


def test_req_trn_021_a_key_save_refused_is_said_under_its_buttons(
    qtbot: QtBot, ctx: AppContext, monkeypatch: pytest.MonkeyPatch, dialogs: list[tuple[str, str]]
) -> None:
    """A save of the key into the workspace is refused (AOI-LOG-002): said under the key's buttons, with no dialog, and
    I Have Saved the Key stays off."""
    win = shell(qtbot, ctx)
    win.navigate("Home")
    guide = guide_of(win)
    typed(qtbot, guide, "TBOX-A1", "Hanil Electronics")
    guide.btn_create.click()
    inside = ctx.settings.root / "recovery-key.txt"
    monkeypatch.setattr(QFileDialog, "getSaveFileName", staticmethod(lambda *a: (str(inside), "")))
    guide.recovery.btn_save.click()
    assert guide.key_refused.text().startswith("AOI-LOG-002 ") and guide.key_refused.isVisible() and dialogs == []
    assert not inside.exists() and not guide.btn_kept.isEnabled() and guide.holding()


def test_req_trn_021_the_guide_for_each_role(qtbot: QtBot, ctx: AppContext) -> None:
    """An Engineer sees screen 1 greyed, saying the role it needs, and Show All Steps › leads to Home's empty state
    with + New board model, Show the Guide › back, until the next sign-in; an Operator gets Home's empty state, which
    says to ask an Admin. A sign-in clears what was typed."""
    win = shell(qtbot, ctx, "admin")
    win.navigate("Home")
    home = cast(HomePage, win.pages["Home"])
    guide = home.guide
    typed(qtbot, guide, "TBOX-A1", "Hanil Electronics")
    win.set_user("engineer")
    assert guide.isVisible() and (guide.name.text(), guide.customer.text()) == ("", "")
    assert not any(w.isEnabled() for w in (guide.name, guide.customer, guide.btn_create))
    role = "Setting up a board model for a customer needs the Admin role."  # the guide's words, on a press too
    assert guide.role_line.text() == role and guide.btn_create.toolTip() == role
    qtbot.mouseClick(guide.name, Qt.MouseButton.LeftButton)
    assert win.statusBar().currentMessage() == role
    guide.btn_cards.click()
    assert not guide.isVisible() and home.empty.isVisible() and home.empty.link.text() == "+ New board model"
    assert home.btn_guide.isVisible()
    home.btn_guide.click()
    assert guide.isVisible() and not home.btn_guide.isVisible()
    guide.btn_cards.click()
    win.set_user("admin")  # Show All Steps › was the Engineer's: the next user gets the guide
    assert guide.isVisible() and not home.btn_guide.isVisible()
    win.set_user("operator")
    assert not guide.isVisible() and not home.btn_guide.isVisible()
    assert (home.empty.heading.text(), home.empty.sentence.text()) == (
        "No board model yet",
        "Ask an Admin to set up the first one.",
    )
    assert not home.empty.link.isVisibleTo(home)


def test_req_trn_021_a_first_start_opens_on_the_name(qtbot: QtBot, ctx: AppContext) -> None:
    """A start with no board model, as main.py makes it, puts the focus on the name once the window opens: the window
    is built, and Home shown, before it is."""
    win = MainWindow(ctx)
    qtbot.addWidget(win)
    win.show()
    qtbot.waitExposed(win)
    win.activateWindow()
    qtbot.waitUntil(lambda: QApplication.activeWindow() is win)
    assert ctx.role == "Admin" and QApplication.focusWidget() is guide_of(win).name


def test_req_trn_021_create_says_why_it_is_off(qtbot: QtBot, ctx: AppContext) -> None:
    """A press on Create while it is off says why on the status bar, as a touch screen shows no tooltip; Enter in a
    field says the same and moves to the field still to fill. Enter after a customer's whole name, with no row of the
    list picked, is Create's."""
    as_admin(ctx, ctx.create_store, "Acme")
    win = shell(qtbot, ctx)
    win.navigate("Home")
    guide = guide_of(win)
    qtbot.mouseClick(guide.btn_create, Qt.MouseButton.LeftButton)
    assert win.statusBar().currentMessage() == "Type a board model name and its customer"
    typed(qtbot, guide, "CON", "")
    qtbot.mouseClick(guide.btn_create, Qt.MouseButton.LeftButton)
    assert win.statusBar().currentMessage().startswith("AOI-TRN-019 ")
    typed(qtbot, guide, "ACME-1", "")
    win.statusBar().clearMessage()
    qtbot.keyClick(guide.name, Qt.Key.Key_Return)
    assert win.statusBar().currentMessage() == "Type a board model name and its customer"
    assert win.focusWidget() is guide.customer
    qtbot.keyClicks(guide.customer, "Acme")
    popup = guide.customers.popup()
    assert popup is not None
    qtbot.waitUntil(popup.isVisible)
    qtbot.keyClick(popup, Qt.Key.Key_Return)  # no row picked: Create
    assert ctx.stores()[0]["board_models"] == ["ACME-1"] and win.board_model == "ACME-1"


def test_req_trn_021_the_held_frame_says_why_and_takes_its_keys(
    qtbot: QtBot, ctx: AppContext, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """While the key shows, a press on a greyed header button, on Show All Steps › or on I Have Saved the Key says why,
    and Ctrl+4 opens no page. Ctrl+S saves the key, a save refused first being past once one works; Ctrl+P prints
    it, the line naming the file it went to; F1 lists the three keys."""
    win = shell(qtbot, ctx)
    win.navigate("Home")
    guide = guide_of(win)
    typed(qtbot, guide, "TBOX-A1", "Hanil Electronics")
    guide.btn_create.click()
    held = "Save the recovery key to a file or print it, then press I Have Saved the Key."
    unsaved = "Save the key to a file or print it first"
    for control, said in ((win.btn_new, held), (guide.btn_cards, held), (guide.btn_kept, unsaved)):
        win.statusBar().clearMessage()
        qtbot.mouseClick(control, Qt.MouseButton.LeftButton)
        assert not control.isEnabled() and win.statusBar().currentMessage() == said
    win.activateWindow()
    qtbot.waitUntil(lambda: QApplication.activeWindow() is win)
    qtbot.keyClick(win, Qt.Key.Key_4, Qt.KeyboardModifier.ControlModifier)
    assert win.stack.currentWidget() is win.pages["Home"] and win.statusBar().currentMessage() == held
    assert "Ctrl+S   Save to File…" in win.keys_text() and "Enter   I Have Saved the Key" in win.keys_text()
    assert "Ctrl+P   Print…" in win.keys_text()
    inside, usb = ctx.settings.root / "recovery-key.txt", tmp_path / "usb"
    usb.mkdir()
    picks = iter([str(inside), str(usb / "key.txt")])
    monkeypatch.setattr(QFileDialog, "getSaveFileName", staticmethod(lambda *a: (next(picks), "")))
    qtbot.keyClick(guide.key_step, Qt.Key.Key_S, Qt.KeyboardModifier.ControlModifier)
    assert guide.key_refused.isVisible() and guide.key_refused.text().startswith("AOI-LOG-002 ")
    qtbot.keyClick(guide.key_step, Qt.Key.Key_S, Qt.KeyboardModifier.ControlModifier)
    assert (usb / "key.txt").exists() and not guide.key_refused.isVisible() and guide.btn_kept.isEnabled()

    def to_file(dialog: QPrintDialog) -> QDialog.DialogCode:
        dialog.printer().setOutputFileName(str(usb / "key.pdf"))
        return QDialog.DialogCode.Accepted

    monkeypatch.setattr(QPrintDialog, "exec", to_file)
    qtbot.keyClick(guide.key_step, Qt.Key.Key_P, Qt.KeyboardModifier.ControlModifier)
    assert guide.recovery.saved_line.text() == f"✓ Sent to {usb / 'key.pdf'}" and (usb / "key.pdf").exists()
