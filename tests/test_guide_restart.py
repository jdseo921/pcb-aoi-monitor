"""REQ-TRN-021, REQ-USR-003 for B5 of the 2026-10 business-readiness brief (docs/sketches/first-run-guide.md, Q75):
until an AI model is active, a start goes on as the user who started the first-run guide, with its board model in the
header, not as the one who signed in last, who may be an Operator who cannot go on. Until ADR 0002's sign-in."""

from __future__ import annotations

from typing import cast

from pytestqt.qtbot import QtBot

from aoi.core.services import AppContext
from aoi.ui.main_window import HomePage, MainWindow
from tests.test_dataset_stores import as_admin
from tests.test_start_user import _reopened


def started(qtbot: QtBot, ctx: AppContext) -> MainWindow:
    """The station started again on `ctx`'s workspace, its window shown."""
    win = MainWindow(_reopened(ctx))
    qtbot.addWidget(win)
    win.resize(1600, 900)
    win.show()
    qtbot.waitExposed(win)
    return win


def test_req_trn_021_a_restart_goes_on_as_the_user_who_started_the_guide(qtbot: QtBot, ctx: AppContext) -> None:
    """An Admin makes TBOX-A1 in Acme's store, and the Engineer AAA-1 with no store and then TBOX-B2, which the Admin
    moves into the store. After the Operator signs in with Switch User, a start signs in the Engineer, who made the
    newest board model the guide shows for, with TBOX-B2 in the header and its screen 2 on Home, and the status bar says
    who and why. With the Engineer an Operator now, a start signs in the first Admin."""
    as_admin(ctx, ctx.create_customer_board_model, "TBOX-A1", "Acme")
    ctx.ensure_board_model("AAA-1")  # in no store: Home shows its cards, as today
    ctx.ensure_board_model("TBOX-B2")
    store = cast(dict[str, str], ctx.store_of("TBOX-A1"))["uuid"]
    as_admin(ctx, ctx.move_in, "TBOX-B2", store)
    ctx.sign_in("operator")
    assert ctx.last_signed_in() == "operator" and ctx.guide_starter() == ("engineer", "TBOX-B2")
    win = started(qtbot, ctx)
    assert win.ctx.user == "engineer" and win.board_model == "TBOX-B2"
    home = cast(HomePage, win.pages["Home"])
    assert win.stack.currentWidget() is home and home.guide.images.isVisible()
    assert win.statusBar().currentMessage() == (
        "Signed in as engineer (Engineer), who started setting up TBOX-B2. Not you? Press Switch User."
    )
    assert [e["after"]["user"] for e in win.ctx.audit_entries(action="user.start")][0] == "engineer"
    win.close()

    again = _reopened(win.ctx)
    again.db.execute("UPDATE users SET role='Operator' WHERE name='engineer'")  # as a table edited outside the app
    win = started(qtbot, again)
    assert win.ctx.user == "admin" and win.board_model == "TBOX-B2"
    assert win.statusBar().currentMessage().startswith("Signed in as admin (Admin), who started setting up TBOX-B2.")
    win.close()


def test_req_trn_021_once_an_ai_model_is_active_a_restart_signs_in_who_signed_in_last(
    qtbot: QtBot, trained_ctx: AppContext
) -> None:
    """With an AI model judging another board model's boards, a board model the guide sets up changes no start: it
    signs in the user who signed in last, as before."""
    ctx = trained_ctx
    as_admin(ctx, ctx.create_customer_board_model, "TBOX-A1", "Acme")
    ctx.sign_in("operator")
    assert ctx.guide_step("TBOX-A1") == 2 and ctx.guide_starter() is None
    win = started(qtbot, ctx)
    assert win.ctx.user == "operator"
    assert win.statusBar().currentMessage().startswith("Signed in as operator (Operator), who signed in last")
    win.close()
