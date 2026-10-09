"""REQ-TRN-010 and REQ-TRN-011 (stage S43, part 2): a trained version installs inactive with its model card; only a
version with a card can be made active; Training's AI models list rolls back in one click to the version it names and
shows the selected version's card. Results on the synthetic boards prove a code path; they are never quoted as
accuracy."""

from __future__ import annotations

from pathlib import Path
from typing import Any, cast

import pytest
from PySide6.QtCore import Qt
from pytestqt.qtbot import QtBot

from aoi.core import model_card
from aoi.core.services import AppContext
from aoi.errors import AoiError
from aoi.ui.pages.training import TrainingPage
from tests.conftest import another_version
from tests.test_req_done_in_v01 import BOARD, _window


def test_req_trn_010_a_trained_version_installs_inactive(trained_ctx: AppContext) -> None:
    """Training adds a version, inactive, with its card; the active version and the Golden board stay as they were,
    and the training's audit entry says it activated nothing."""
    ctx = trained_ctx
    active, reference = cast(dict[str, Any], ctx.active_model(BOARD)), ctx.reference_image(BOARD)
    meta = ctx.train(ctx.training_version(BOARD)["uuid"], 1, 32)
    new = next(m for m in ctx.models(BOARD) if m["uuid"] == meta["uuid"])
    assert not new["active"] and ctx.model_card(int(new["id"])) is not None
    assert (cast(dict[str, Any], ctx.active_model(BOARD))["uuid"], ctx.reference_image(BOARD)) == (
        active["uuid"],
        reference,
    )
    entry = ctx.audit_entries(action="model.train")[0]
    assert entry["after"]["activated"] is False and entry["before"] == {"active_version": active["version"]}
    assert ctx.previous_model(BOARD) is None  # training switched nothing to roll back from


def test_req_trn_011_activation_refused_without_card(trained_ctx: AppContext) -> None:
    """A version whose card is missing is refused with AOI-TRN-049; nothing changes and nothing is audited."""
    ctx = trained_ctx
    mid = another_version(ctx, BOARD, "v9.0")
    for f in model_card.paths(Path(ctx.model(mid)["path"])):
        f.unlink()
    before = (ctx.active_model(BOARD), ctx.reference_image(BOARD), ctx.audit_entries())
    with pytest.raises(AoiError) as e:
        ctx.activate_model(mid)
    assert e.value.code == "AOI-TRN-049" and "it has no AI model card" in e.value.what
    assert (ctx.active_model(BOARD), ctx.reference_image(BOARD), ctx.audit_entries()) == before


def test_req_trn_010_roll_back_on_training_names_its_version(
    qtbot: QtBot, trained_ctx: AppContext, dialogs: list[tuple[str, str]]
) -> None:
    """Roll Back is off until an activation gives it a version to go back to; then it reads "Roll Back to v1.0" and
    one click makes v1.0 active again."""
    ctx = trained_ctx
    win = _window(qtbot, ctx, "Engineer")
    page = cast(TrainingPage, win.pages["Training"])
    assert win.navigate("Training")
    assert not page.btn_rollback.isEnabled() and page.btn_rollback.text() == "Roll Back"
    first = cast(dict[str, Any], ctx.active_model(BOARD))["version"]
    ctx.activate_model(another_version(ctx, BOARD, "v9.0"))
    page.refresh()
    assert page.btn_rollback.isEnabled() and page.btn_rollback.text() == f"Roll Back to {first}"
    qtbot.mouseClick(page.btn_rollback, Qt.MouseButton.LeftButton)
    assert cast(dict[str, Any], ctx.active_model(BOARD))["version"] == first
    assert page.btn_rollback.text() == "Roll Back to v9.0" and dialogs == []


def test_req_trn_011_card_shown_on_training(qtbot: QtBot, trained_ctx: AppContext) -> None:
    """AI Model Card shows the selected version's card under the list, its first line saying it is not yet tested."""
    ctx = trained_ctx
    win = _window(qtbot, ctx, "Engineer")
    page = cast(TrainingPage, win.pages["Training"])
    assert win.navigate("Training")
    assert page.card_view.isHidden()
    page.models.selectRow(0)
    page.show_card()
    text = page.card_view.toPlainText()
    assert page.card_view.isVisible() and text.startswith(f"# Model card: {BOARD} ")
    assert "Not yet tested on a locked validation set" in text
