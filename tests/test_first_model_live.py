"""REQ-TRN-012 and REQ-TRN-010, decision D3 of the 2026-10 business-readiness brief: a board model's first AI model goes
live when its training ends, with an audit entry naming why and a status line that says so, as there is no version in
use to keep; every later version installs inactive, as before, for an Engineer to activate. A trained version that is
not active (one trained before this, or whose activation failed) is named wherever "No AI model yet" was said of it,
and Inspection offers to activate it. Results on the synthetic boards prove a code path; they are never accuracy."""

from __future__ import annotations

import shutil
import sqlite3
from pathlib import Path
from typing import Any, cast

import pytest
from PySide6.QtCore import Qt
from pytestqt.qtbot import QtBot

from aoi.core import anomaly, model_card
from aoi.core.imaging import list_images
from aoi.core.services import FIRST_LIVE, AppContext
from aoi.data.db import new_uuid
from aoi.data.paths import resolve, to_stored
from aoi.ui.main_window import HomePage, MainWindow
from aoi.ui.pages.inspection import InspectionPage
from aoi.ui.pages.model_test import ModelTestPage
from aoi.ui.pages.training import TrainingPage
from tests.conftest import log_rows
from tests.test_train_from_version import BOARD, boards
from tools.trainable import trainable

WAITING = "ZZZ"  # a board model with a Golden board and one AI model version, not active


def _window(qtbot: QtBot, ctx: AppContext, user: str) -> MainWindow:
    win = MainWindow(ctx)
    qtbot.addWidget(win)
    win.show()
    qtbot.waitExposed(win)
    win.set_user(user)
    return win


def _waiting_version(ctx: AppContext) -> str:
    """WAITING, with TINY's first OK board as its Golden board and TINY's weights registered for it as v1.0, inactive,
    with its card, as a version trained before a first version went live by itself stays; its UUID."""
    ctx.ensure_board_model(WAITING)
    ctx.set_reference(WAITING, ctx.samples("TINY", "OK")[0]["id"])
    src = cast(dict[str, Any], ctx.active_model("TINY"))
    model, uid = anomaly.AnomalyModel.load(src["path"]), new_uuid()
    model.meta.update(board_model=WAITING, version="v1.0", uuid=uid)
    path = Path(src["path"]).with_name(f"{WAITING}_v1.0.pt")
    model.save(path)
    for a, b in zip(model_card.paths(Path(src["path"])), model_card.paths(path), strict=True):
        shutil.copyfile(a, b)  # its card, which activation needs (REQ-TRN-011)
    ctx.db.register_model(WAITING, "v1.0", str(path), {}, activate=False, uid=uid)
    return uid


def test_req_trn_012_a_board_models_first_ai_model_goes_live_when_trained_and_a_later_one_installs_inactive(
    ctx: AppContext, synthetic_dataset: Path
) -> None:
    """The first training of a board model registers its version, as every training does (model.train, activated
    False), then makes it active with its Golden board in an entry of its own: model.activate, by the Engineer who
    trained it, with the reason. Roll Back has nothing to go back to. The second training installs inactive."""
    boards(ctx, synthetic_dataset, 21)
    before, root = ctx.reference_image(BOARD), ctx.settings.root
    first = ctx.train(trainable(ctx, BOARD), epochs=1, image_size=32)
    golden = resolve(first["golden_image"], root)
    assert first["activated"] and cast(dict[str, Any], ctx.active_model(BOARD))["uuid"] == first["uuid"]
    assert Path(ctx.reference_image(BOARD) or "") == golden
    (trained,) = ctx.audit_entries(action="model.train")
    (live,) = ctx.audit_entries(action="model.activate")
    assert trained["after"]["activated"] is False and trained["before"] == {"active_version": None}
    assert (live["object_uuid"], live["reason"]) == (first["uuid"], FIRST_LIVE)
    assert live["before"] == {"active_version": None, "reference": to_stored(Path(before), root) if before else None}
    assert live["after"] == {"active_version": first["version"], "reference": to_stored(golden, root)}
    assert (live["user_uuid"], live["role"]) == (ctx.db.user_uuid("engineer"), "Engineer")
    assert ctx.previous_model(BOARD) is None and ctx.inactive_model(BOARD) is None

    second = ctx.train(trainable(ctx, BOARD), epochs=1, image_size=32)
    assert not second["activated"] and cast(dict[str, Any], ctx.active_model(BOARD))["uuid"] == first["uuid"]
    assert len(ctx.audit_entries(action="model.activate")) == 1 and ctx.inactive_model(BOARD) is None


def test_req_trn_012_a_first_version_that_cannot_go_live_stays_inactive_and_is_named(
    ctx: AppContext, synthetic_dataset: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A first version whose activation fails (here the disk full as it is written) stays registered and inactive, the
    run still ends with it: no activation entry, a warning in the log, and `inactive_model` names it."""
    boards(ctx, synthetic_dataset, 21)

    def full(*args: Any) -> None:
        raise sqlite3.OperationalError("database or disk is full")

    monkeypatch.setattr(ctx, "_switch_to", full)
    meta = ctx.train(trainable(ctx, BOARD), epochs=1, image_size=32)
    assert not meta["activated"] and ctx.active_model(BOARD) is None
    assert cast(dict[str, Any], ctx.inactive_model(BOARD))["uuid"] == meta["uuid"]
    assert ctx.audit_entries(action="model.activate") == []
    assert [r["board_model"] for r in log_rows(ctx.settings.root / "logs") if r["event"] == "training.first_not_live"]


def test_req_trn_012_training_says_when_its_version_went_live(qtbot: QtBot, trained_ctx: AppContext) -> None:
    """The status bar, and the run's log on Training, say a first version is active from now on; a later version's
    line says to activate it, as before."""
    win = _window(qtbot, trained_ctx, "engineer")
    page = cast(TrainingPage, win.pages["Training"])
    assert win.navigate("Training")
    page._on_done({"version": "v1.0", "train_seconds": 3, "board_model": "TINY", "activated": True})
    said = (
        "AI model v1.0 trained and active: the first AI model of TINY judges its boards from now on. Each later"
        " version installs inactive until you activate it."
    )
    assert win.statusBar().currentMessage() == said == page.log.toPlainText().splitlines()[-1]
    page._on_done({"version": "v1.1", "train_seconds": 3, "board_model": "TINY", "activated": False})
    said = "AI model v1.1 trained: select it and press Activate Selected to judge boards with it"
    assert win.statusBar().currentMessage() == said == page.log.toPlainText().splitlines()[-1]


def test_req_trn_010_inspection_names_a_version_that_is_not_active_and_offers_activate(
    qtbot: QtBot, trained_ctx: AppContext, synthetic_dataset: Path
) -> None:
    """A board model with a trained version and none active: Inspection's line names it, with Activate v1.0, greyed for
    an Operator with the role it needs, in the line too; a board judged then stores AOI-TRN-051 naming the version,
    never AOI-TRN-003 ("No AI model … yet"). An Engineer's Activate makes it active, audited, and the line goes; the
    next board is judged by it."""
    ctx = trained_ctx
    uid = _waiting_version(ctx)
    win = _window(qtbot, ctx, "operator")
    page = cast(InspectionPage, win.pages["Inspection"])
    assert win.navigate("Inspection")
    win.bm_combo.setCurrentText(WAITING)
    qtbot.waitUntil(ctx.jobs.idle, timeout=10000)
    why = "Activating an AI model version needs the Engineer or Admin role."
    assert page.ai_row.isVisible() and page.btn_activate.text() == "Activate v1.0"
    assert page.ai_line.text() == (
        f"AI model v1.0 of {WAITING} is trained but not active: only the Golden board comparison judges its boards."
        f" {why}"
    )
    assert not page.btn_activate.isEnabled() and page.btn_activate.toolTip() == why
    oks = list_images(synthetic_dataset / "test" / "ok")

    def judge(board: Path) -> None:
        page._set_queue([board])
        page.next_board()
        qtbot.waitUntil(lambda: page.worker is None and ctx.jobs.idle(), timeout=60000)

    judge(oks[0])
    codes = [a["code"] for a in ctx.alarms()]
    assert "AOI-TRN-051" in codes and "AOI-TRN-003" not in codes, codes
    (alarm,) = [a for a in ctx.alarms() if a["code"] == "AOI-TRN-051"]
    assert alarm["message"].startswith(f"AI model v1.0 of {WAITING} is not active: only the Golden board comparison")

    win.set_user("engineer")
    assert page.btn_activate.isEnabled() and why not in page.ai_line.text()
    qtbot.mouseClick(page.btn_activate, Qt.MouseButton.LeftButton)
    assert cast(dict[str, Any], ctx.active_model(WAITING))["uuid"] == uid and not page.ai_row.isVisible()
    assert win.statusBar().currentMessage() == f"AI model v1.0 is active: it judges the next boards of {WAITING}."
    entry = ctx.audit_entries(action="model.activate")[0]
    assert (entry["object_uuid"], entry["role"], entry["reason"]) == (uid, "Engineer", None)
    judge(oks[1])
    assert page.inspector is not None and page.inspector.model_version == "v1.0"


def test_req_trn_010_home_and_ai_model_test_name_a_version_that_is_not_active(
    qtbot: QtBot, trained_ctx: AppContext
) -> None:
    """Home's Train AI model card and AI Model Test's empty state name the version trained but not active, and say to
    activate it on Training, where they said there was no AI model yet."""
    _waiting_version(trained_ctx)
    win = _window(qtbot, trained_ctx, "engineer")
    win.bm_combo.setCurrentText(WAITING)
    assert win.navigate("Home")
    home = cast(HomePage, win.pages["Home"])
    assert home.status_labels["Train AI model"].text() == "AI model v1.0 trained, not active. Activate it on Training."
    assert win.navigate("AI Model Test")
    test = cast(ModelTestPage, win.pages["AI Model Test"])
    assert test.empty.heading.text() == f"AI model v1.0 of {WAITING} is not active"
    assert test.empty.sentence.text().startswith("Activate it on Training.")
