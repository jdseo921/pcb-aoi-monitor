"""ADR 0024 D24 and D25 (usability sweep H1 and H2, industry norms): no account is claimed at a station, and each role
lands on its own work. D24: until an Admin has a password only the Admin account may choose one, an Engineer is only
handed over, and the screens make no board model before the Admin's password. D25: an Operator starts and signs in on
Inspection, and their Home is the cards without What is missing."""

from __future__ import annotations

from typing import cast

import pytest
from pytestqt.qtbot import QtBot

from aoi.core.services import AppContext
from aoi.errors import AoiError
from aoi.ui.main_window import HomePage, MainWindow
from aoi.ui.sign_in_dialog import SignInDialog
from tests.conftest import PASSPHRASE


def test_req_usr_005_only_the_admin_is_claimed_while_no_admin_has_a_password(ctx: AppContext) -> None:
    """A station's first run: an Operator may not choose the Engineer's password (AOI-USR-009) and the dialog says so
    before anything is typed; the first Admin's password is chosen at the station; then the Admin hands the Engineer
    over."""
    ctx.sign_in("operator")
    assert ctx.may_set_up("Admin") and not ctx.may_set_up("Engineer")
    with pytest.raises(AoiError, match="AOI-USR-009"):
        ctx.sign_in("engineer", password=PASSPHRASE)
    assert ctx.user == "operator"
    ctx.sign_in("admin", password=PASSPHRASE)  # the first Admin, at the station
    ctx.take_recovery_code()
    assert ctx.may_set_up("Engineer")  # the Admin signed in hands the Engineer over
    ctx.sign_in("engineer", password=PASSPHRASE + " too")
    assert ctx.role == "Engineer"


def test_req_usr_005_switch_user_says_an_engineer_waits_for_the_first_admin(qtbot: QtBot, ctx: AppContext) -> None:
    win = MainWindow(ctx)
    qtbot.addWidget(win)
    box = SignInDialog(win, "engineer")
    box.show()
    assert "only with an Admin signed in" in box.hint.text()
    assert not box.password.isVisible() and not box.btn_sign_in.isEnabled()
    box.user.setCurrentIndex(next(i for i, u in enumerate(box.users) if u["name"] == "admin"))
    assert box.password.isVisible() and box.again.isVisible()  # the first Admin chooses theirs here
    box.reject()
    win.close()


def test_req_set_013_no_board_model_is_made_on_screen_before_the_admins_password(qtbot: QtBot, ctx: AppContext) -> None:
    """The guide's Create and the header's + New stay off while the Admin has no password, each saying why; once the
    Admin has one, both turn on."""
    win = MainWindow(ctx)
    qtbot.addWidget(win)
    win.show()
    assert win.first_admin_unset() == "admin" and win.ctx.role == "Admin"
    guide = cast(HomePage, win.pages["Home"]).guide
    guide.name.setText("TBOX-A2")
    guide.customer.setText("Beta Boards")
    assert not guide.btn_create.isEnabled() and "Admin's password first" in guide.btn_create.toolTip()
    assert not win.btn_new.isEnabled() and "Admin's password first" in win.btn_new.toolTip()
    guide.make_board_model()  # Enter in a field: nothing is made, the status bar says why
    assert ctx.board_models() == [] and "Admin's password first" in win.statusBar().currentMessage()
    ctx.sign_in("admin", password=PASSPHRASE)
    ctx.take_recovery_code()
    win.set_user("admin")
    guide.show_for(None)
    guide.name.setText("TBOX-A2")  # a sign-in clears the fields
    guide.customer.setText("Beta Boards")
    assert win.first_admin_unset() is None and guide.btn_create.isEnabled() and win.btn_new.isEnabled()
    win.close()


def test_req_usr_001_an_operator_lands_on_inspection_and_their_home_has_no_set_up_list(
    qtbot: QtBot, ctx: AppContext
) -> None:
    """D25: a start as an Operator opens Inspection whatever page was last shown, Switch User to an Operator does too,
    and an Operator's Home shows the cards without What is missing, which an Engineer still sees."""
    ctx.ensure_board_model("TINY")
    ctx.settings.last_page = "Logs & Export"
    ctx.sign_in("operator")
    win = MainWindow(ctx)
    qtbot.addWidget(win)
    win.show()
    assert ctx.role == "Operator" and win.stack.currentWidget() is win.pages["Inspection"]
    assert win.navigate("Home")
    home = cast(HomePage, win.pages["Home"])
    assert home.cards.isVisible() and home.missing_list.isHidden()
    win.set_user("engineer")
    assert win.navigate("Home") and not home.missing_list.isHidden()
    assert win.landing("Logs & Export") == "Logs & Export"
    win.set_user("operator")
    assert win.landing("Logs & Export") == "Inspection"
    win.close()
