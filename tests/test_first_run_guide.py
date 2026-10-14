"""REQ-TRN-021 for B5 of the 2026-10 business-readiness brief (D4; docs/sketches/first-run-guide.md, Q66, Q67, Q76):
Home opens an empty workspace on the first-run guide. Its first screen takes the board model's name and its customer
and makes the board model in the customer's encrypted dataset store; a customer's first board model shows the store's
recovery key on the screen itself, the frame held until I Have Saved the Key, which waits for the key to be saved or
printed. A refusal is said under the control that raised it, with no dialog. An Engineer sees the screen greyed with
the role it needs, an Operator Home's empty state; Show All Steps › and Show the Guide › switch between the guide and
the cards."""

from __future__ import annotations

from pathlib import Path
from typing import cast

import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QFileDialog, QWidget
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
    close do nothing and say why. The key kept, the header selects the board model and Home shows its cards."""
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
    assert win.board_model == "TBOX-A1" and cast(HomePage, win.pages["Home"]).cards.isVisible()
    said = "Board model TBOX-A1 is set up for Hanil Electronics."
    assert win.statusBar().currentMessage() == said and win.navigate("Training")


def test_req_trn_021_a_customer_with_a_store_and_a_refusal_under_create(
    qtbot: QtBot, ctx: AppContext, monkeypatch: pytest.MonkeyPatch, dialogs: list[tuple[str, str]]
) -> None:
    """A customer with a store, picked from the list by Enter, which picks and makes nothing, or typed in another case:
    the board model goes in that store with no key, and the header selects it. A refusal (AOI-TRN-044, a folder under
    images/ that holds files already) is said under Create with its code, and no dialog; typing again clears it."""
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
    typed(qtbot, guide, "ACME-1", "acme")
    assert not guide.refused.isVisible()
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
    with + New board model, Show the Guide › back; an Operator gets Home's empty state, which says to ask an Admin. A
    sign-in clears what was typed."""
    win = shell(qtbot, ctx, "admin")
    win.navigate("Home")
    home = cast(HomePage, win.pages["Home"])
    guide = home.guide
    typed(qtbot, guide, "TBOX-A1", "Hanil Electronics")
    win.set_user("engineer")
    assert guide.isVisible() and (guide.name.text(), guide.customer.text()) == ("", "")
    assert not any(w.isEnabled() for w in (guide.name, guide.customer, guide.btn_create))
    assert guide.role_line.text() == "Creating a board model in a customer's dataset store needs the Admin role."
    guide.btn_cards.click()
    assert not guide.isVisible() and home.empty.isVisible() and home.empty.link.text() == "+ New board model"
    assert home.btn_guide.isVisible()
    home.btn_guide.click()
    assert guide.isVisible() and not home.btn_guide.isVisible()
    win.set_user("operator")
    assert not guide.isVisible() and not home.btn_guide.isVisible()
    assert (home.empty.heading.text(), home.empty.sentence.text()) == (
        "No board model yet",
        "Ask an Admin to set up the first one.",
    )
    assert not home.empty.link.isVisibleTo(home)
