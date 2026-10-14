"""REQ-TRN-021, REQ-USR-003 for B5 of the 2026-10 business-readiness brief (docs/sketches/first-run-guide.md, Q75):
while the station is set up, with no AI model active and no board inspected, a start goes on as the user who started the
first-run guide, with its board model in the header and Home shown, not as the one who signed in last, who may be an
Operator who cannot go on. Until ADR 0002's sign-in."""

from __future__ import annotations

from typing import cast

import pytest
from pytestqt.qtbot import QtBot

from aoi.core.services import AppContext, GuideStarter
from aoi.errors import AoiError
from aoi.ui.main_window import HomePage, MainWindow
from tests.test_dataset_stores import as_admin
from tests.test_start_user import _reopened


def started(qtbot: QtBot, ctx: AppContext, last_page: str = "Home", carried: str | None = None) -> MainWindow:
    """The station started again on `ctx`'s workspace, its window closed last on `last_page`, shown; with `carried`,
    the window a workspace switch builds, the role signed in before carried."""
    reopened = _reopened(ctx)
    reopened.settings.last_page = last_page
    win = MainWindow(reopened, carried)
    qtbot.addWidget(win)
    win.resize(1600, 900)
    win.show()
    qtbot.waitExposed(win)
    return win


def test_req_trn_021_a_restart_goes_on_as_the_user_who_started_the_guide(qtbot: QtBot, ctx: AppContext) -> None:
    """An Admin makes TBOX-A1 in Acme's store, and the Engineer AAA-1 with no store and then TBOX-B2, which the Admin
    moves into the store. After the Operator signs in with Switch User, a start signs in the Engineer, who made the
    newest board model the guide shows for, with TBOX-B2 in the header and its screen 2 on Home, though the window was
    closed on Inspection, and the status bar says who and why. A workspace switch keeps the role carried and the page,
    as before. With the Engineer an Operator now, a start signs in the first Admin, and the status bar says that the
    Admin goes on with it."""
    as_admin(ctx, ctx.create_customer_board_model, "TBOX-A1", "Acme")
    ctx.ensure_board_model("AAA-1")  # in no store: Home shows its cards, as today
    ctx.ensure_board_model("TBOX-B2")
    store = cast(dict[str, str], ctx.store_of("TBOX-A1"))["uuid"]
    as_admin(ctx, ctx.move_in, "TBOX-B2", store)
    ctx.sign_in("operator")
    assert ctx.last_signed_in() == "operator" and ctx.guide_starter() == GuideStarter("engineer", "TBOX-B2", True)
    win = started(qtbot, ctx, "Inspection")
    assert win.ctx.user == "engineer" and win.board_model == "TBOX-B2"
    home = cast(HomePage, win.pages["Home"])
    assert win.stack.currentWidget() is home and home.guide.images.isVisible()
    assert win.statusBar().currentMessage() == (
        "Signed in as engineer (Engineer), who started setting up TBOX-B2. Not you? Press Switch User."
    )
    assert [e["after"]["user"] for e in win.ctx.audit_entries(action="user.start")][0] == "engineer"
    win.close()

    win = started(qtbot, win.ctx, "Inspection", carried="Operator")
    assert win.ctx.user == "operator" and win.stack.currentWidget() is win.pages["Inspection"]
    assert "started setting up" not in win.statusBar().currentMessage()
    win.close()

    again = _reopened(win.ctx)
    again.db.execute("UPDATE users SET role='Operator' WHERE name='engineer'")  # as a table edited outside the app
    assert again.guide_starter() == GuideStarter("admin", "TBOX-B2", False)
    win = started(qtbot, again)
    assert win.ctx.user == "admin" and win.board_model == "TBOX-B2"
    assert win.statusBar().currentMessage() == (
        "Signed in as admin (Admin) to go on setting up TBOX-B2, as the user who started it is no longer an Engineer "
        "or Admin here. Not you? Press Switch User."
    )
    win.close()


def test_req_trn_021_a_station_in_use_or_a_step_that_cannot_be_read_changes_no_start(
    ctx: AppContext, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A board model whose guide step cannot be read is passed over, logged, so choosing who signs in never refuses
    the workspace: the next one the guide shows for is taken. A station that inspects boards of a board model in no
    store with Golden board comparison alone, with no AI model, is in use: a start signs in the user who signed in
    last, as before, though the guide still shows for another board model."""
    ctx.ensure_board_model("AAA-1")
    as_admin(ctx, ctx.create_customer_board_model, "TBOX-A1", "Acme")
    as_admin(ctx, ctx.create_customer_board_model, "TBOX-B2", "Acme")
    ctx.sign_in("operator")
    step = ctx.guide_step

    def unreadable(board_model: str | None) -> int | None:
        if board_model == "TBOX-B2":
            raise AoiError("AOI-TRN-038", view="Up")  # a version row edited outside the app
        return step(board_model)

    monkeypatch.setattr(ctx, "guide_step", unreadable)
    assert ctx.guide_starter() == GuideStarter("admin", "TBOX-A1", True) and ctx.start_user() == "admin"
    counts = ctx.db.inspection_counts
    monkeypatch.setattr(ctx.db, "inspection_counts", lambda b: (3, 1) if b == "AAA-1" else counts(b))
    assert ctx.guide_step("TBOX-A1") == 2 and ctx.guide_starter() is None and ctx.start_user() == "operator"


def test_req_trn_021_once_an_ai_model_is_active_a_restart_signs_in_who_signed_in_last(
    qtbot: QtBot, trained_ctx: AppContext
) -> None:
    """With an AI model judging another board model's boards, a board model the guide sets up changes no start: it
    signs in the user who signed in last, on the page shown last, as before."""
    ctx = trained_ctx
    as_admin(ctx, ctx.create_customer_board_model, "TBOX-A1", "Acme")
    ctx.sign_in("operator")
    assert ctx.guide_step("TBOX-A1") == 2 and ctx.guide_starter() is None
    win = started(qtbot, ctx, "Inspection")
    assert win.ctx.user == "operator" and win.stack.currentWidget() is win.pages["Inspection"]
    assert win.statusBar().currentMessage().startswith("Signed in as operator (Operator), who signed in last")
    win.close()
