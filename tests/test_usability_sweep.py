"""The low-risk fixes of the usability sweep of 2026-11-06 (project report): a greyed button says
what turns it on (M1), Switch User says why Sign In is off as a password is typed (M2) and that an account in set-up
waits for an Admin before anyone types (M3), Recipe Editor's ROI form is off with no ROI selected (M4), and a page
refused before leaves no line on the page opened next (M7)."""

from __future__ import annotations

from typing import cast

from PySide6.QtCore import QEvent, QPointF, Qt
from PySide6.QtGui import QMouseEvent
from PySide6.QtWidgets import QApplication, QWidget
from pytestqt.qtbot import QtBot

from aoi.core.recipe import ROI
from aoi.core.services import AppContext
from aoi.ui.main_window import MainWindow
from aoi.ui.pages.inspection import InspectionPage
from aoi.ui.pages.logs import LogsPage
from aoi.ui.pages.recipe_editor import RecipeEditorPage
from aoi.ui.sign_in_dialog import SignInDialog
from tests.conftest import PASSPHRASE, listed


def _press(control: QWidget) -> None:
    """A press as a touch screen makes it: no tooltip, only the press."""
    pos = QPointF(control.rect().center())
    press = QMouseEvent(
        QEvent.Type.MouseButtonPress, pos, pos, Qt.MouseButton.LeftButton, Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )  # fmt: skip
    QApplication.sendEvent(control, press)


def test_req_usr_001_a_button_greyed_by_the_page_says_what_turns_it_on(qtbot: QtBot, ctx: AppContext) -> None:
    """Inspection's review buttons, Compare with Golden board › and Stop, and Logs' Open in Compare ›, greyed before a
    board or a record, each say why in their tooltip and on the status bar at a press; their own tooltip comes back
    once they are on."""
    ctx.ensure_board_model("TINY")
    win = MainWindow(ctx)
    qtbot.addWidget(win)
    win.show()
    win.set_user("operator")
    assert win.navigate("Inspection")
    page = cast(InspectionPage, win.pages["Inspection"])
    for b in (page.review.btn_defect, page.review.btn_false, page.btn_compare, page.btn_stop):
        assert not b.isEnabled() and b.toolTip(), b.text()
        _press(b)
        assert win.statusBar().currentMessage() == b.toolTip(), b.text()
    assert "NG or WARN" in page.review.btn_defect.toolTip() and "Start" in page.btn_stop.toolTip()
    page.review.show_record({"id": 1, "result": "NG"})
    assert page.review.btn_defect.isEnabled() and page.review.btn_defect.toolTip() == ""
    assert win.navigate("Logs & Export")
    logs = cast(LogsPage, win.pages["Logs & Export"])
    listed(qtbot, logs)
    assert not logs.btn_compare.isEnabled() and logs.btn_compare.toolTip() == "Select a record in the table first."
    win.close()


def test_req_usr_002_switch_user_says_why_sign_in_is_off_while_a_password_is_typed(
    qtbot: QtBot, ctx: AppContext
) -> None:
    """A new password too short counts its characters; two that differ say so; two that agree turn Sign In on."""
    win = MainWindow(ctx)
    qtbot.addWidget(win)
    box = SignInDialog(win, "admin")  # the first Admin: the one account claimed at the station (ADR 0024 D24)
    box.password.setText("short")
    assert box.hint.text() == "5 of at least 15 characters." and not box.btn_sign_in.isEnabled()
    box.again.setText("short")  # the two agree, still too short: Sign In stays off, the count still says why
    assert box.hint.text() == "5 of at least 15 characters." and not box.btn_sign_in.isEnabled()
    box.password.setText(PASSPHRASE)
    box.again.setText(PASSPHRASE + "x")
    assert box.hint.text() == "The two passwords differ." and not box.btn_sign_in.isEnabled()
    box.again.setText(PASSPHRASE)
    assert box.btn_sign_in.isEnabled() and "admin has no password yet" in box.hint.text()
    box.reject()
    win.close()


def test_req_usr_002_an_account_in_set_up_says_it_waits_for_an_admin_before_anyone_types(
    qtbot: QtBot, ctx: AppContext
) -> None:
    """Once an Admin has a password, an Operator who picks the Engineer still in set-up reads AOI-USR-009's sentence,
    with no field to type in and Sign In off, rather than typing a password twice to be refused; the Admin signed in
    sees the fields, as they hand the account over."""
    ctx.sign_in("admin", password=PASSPHRASE)  # the station's first Admin chooses theirs
    ctx.sign_in("operator")
    assert not ctx.may_set_up("Engineer")
    win = MainWindow(ctx)
    qtbot.addWidget(win)
    box = SignInDialog(win, "engineer")
    box.show()
    assert "engineer has no password yet, and one is chosen only with an Admin signed in." in box.hint.text()
    assert "Ask an Admin to sign in" in box.hint.text()
    assert not box.password.isVisible() and not box.again.isVisible() and not box.btn_sign_in.isEnabled()
    box.reject()
    ctx.sign_in("admin", password=PASSPHRASE)
    assert ctx.may_set_up("Engineer")
    handover = SignInDialog(win, "engineer")
    handover.show()
    assert handover.password.isVisible() and handover.again.isVisible()
    handover.reject()
    win.close()


def test_req_rcp_001_the_roi_form_is_off_until_an_roi_is_selected(qtbot: QtBot, ctx: AppContext) -> None:
    """With no ROI selected the form takes no value, and Apply and Delete say to select one; selecting R1 turns the
    form on with R1's values."""
    ctx.ensure_board_model("TINY")
    ctx.set_user("engineer")
    recipe = ctx.recipe("TINY")[1]
    recipe.rois.append(ROI("R1", "Presence", 10, 10, 20, 20, ai_score=1.5))
    ctx.save_recipe(recipe)
    win = MainWindow(ctx)
    qtbot.addWidget(win)
    win.set_user("engineer")
    assert win.navigate("Recipe Editor")
    page = cast(RecipeEditorPage, win.pages["Recipe Editor"])
    page.roi_table.clearSelection()
    fields = (page.r_name, page.r_type, page.r_ai, page.r_hmin, page.r_hmax, page.r_vmin, page.r_vmax, page.r_enabled)
    assert not any(w.isEnabled() for w in fields)
    assert "Select an ROI" in page.apply_btn.toolTip() and "Select an ROI" in page.delete_btn.toolTip()
    page.roi_table.selectRow(0)
    assert page.r_name.isEnabled() and page.r_name.text() == "R1" and page.r_ai.value() == 1.5
    assert all(w.isEnabled() for w in fields) and page.apply_btn.isEnabled() and page.apply_btn.toolTip() == ""
    page.roi_table.clearSelection()
    assert not any(w.isEnabled() for w in fields) and not page.delete_btn.isEnabled()
    win.close()


def test_req_set_018_a_page_refused_before_leaves_no_line_on_the_next_page(qtbot: QtBot, ctx: AppContext) -> None:
    """An Operator who presses 3D Profile reads why it is greyed; opening Logs & Export next clears that line, while a
    line of another kind stays, as a run's progress does."""
    win = MainWindow(ctx)
    qtbot.addWidget(win)
    win.show()
    win.set_user("operator")
    assert not win.navigate("3D Profile")
    assert win.statusBar().currentMessage() == "3D Profile needs the Engineer / Admin role"
    assert win.navigate("Logs & Export")
    assert win.statusBar().currentMessage() == ""
    win.status("Inspecting board_07.png (3 of 12)…", ms=0)
    assert win.navigate("Compare")
    assert win.statusBar().currentMessage() == "Inspecting board_07.png (3 of 12)…"
    win.close()
