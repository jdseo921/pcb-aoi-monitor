"""REQ-TRN-015 (S28c, 1 of 5): the AI score threshold a board model's recipe overrides is the AI model's calibrated
value, which `AppContext.calibrated_threshold` reads from the AI model registry. Setting, changing or clearing the
override is a new recipe revision, also audited as `recipe.ai_threshold` with the board model, the user and the value
before and after, and AppContext refuses it below the Engineer role. A calibration the registry cannot give is
AOI-TRN-012, which Training's Threshold column shows."""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from pytestqt.qtbot import QtBot

from aoi.core.services import AppContext
from aoi.errors import AoiError
from aoi.ui.pages.base import cell_item, cell_text
from aoi.ui.pages.training import TrainingPage
from tests.test_req_done_in_v01 import BOARD, _window
from tools.trainable import trainable


def _judged_by(ctx: AppContext, board: Path) -> float:
    """The threshold the AI check of a new inspection of `board` judges by."""
    res = ctx.inspect_file(BOARD, str(board), save=False)
    return next(c.threshold for c in res.checks if c.source == "AI")


def _save_override(ctx: AppContext, value: float | None) -> int:
    recipe = ctx.recipe(BOARD)[1]
    recipe.anomaly_threshold = value
    return ctx.save_recipe(recipe)


def test_req_trn_015_setting_and_clearing_an_override_are_audited(trained_ctx: AppContext, ng_board: Path) -> None:
    """An override saved is a new revision that judges the next inspection, with a `recipe.ai_threshold` entry that
    names the board model, the user, the revisions and the value before and after; clearing it is a new revision
    audited the same way, after which the calibrated value judges again, a newly trained AI model's included, while a
    stored result's AI model keeps its own. A save that keeps the override writes no entry of it (0, which the engine
    reads as none, is none here too). An Operator is refused with AOI-USR-001 and nothing is written."""
    ctx = trained_ctx
    cal, model = ctx.calibrated_threshold(BOARD), ctx.active_model(BOARD)
    assert cal is not None and model is not None and cal == json.loads(model["metrics"])["image_threshold"]
    rev, override, engineer = ctx.recipe(BOARD)[0], round(cal * 2, 3), ctx.db.user_uuid("engineer")
    assert _save_override(ctx, override) == rev + 1
    (entry,) = ctx.audit_entries(action="recipe.ai_threshold")
    assert (entry["object_type"], entry["object_uuid"], entry["user_uuid"], entry["role"]) == (
        "board_model", BOARD, engineer, "Engineer"
    )  # fmt: skip
    named = {"ai_model": model["version"], "calibrated": cal}
    assert entry["before"] == {"revision": rev, "override": None, "threshold": cal, **named}
    assert entry["after"] == {"revision": rev + 1, "override": override, "threshold": override, **named}
    assert _judged_by(ctx, ng_board) == pytest.approx(override)
    assert _save_override(ctx, None) == rev + 2
    entry = ctx.audit_entries(action="recipe.ai_threshold")[0]
    assert (entry["object_uuid"], entry["user_uuid"]) == (BOARD, engineer)
    assert entry["before"] == {"revision": rev + 1, "override": override, "threshold": override, **named}
    assert entry["after"] == {"revision": rev + 2, "override": None, "threshold": cal, **named}
    assert _judged_by(ctx, ng_board) == pytest.approx(cal)
    _save_override(ctx, 0.0)
    _save_override(ctx, None)
    assert ctx.recipe(BOARD)[0] == rev + 4 and len(ctx.audit_entries(action="recipe.ai_threshold")) == 2
    ctx.set_user("operator")
    with pytest.raises(AoiError) as refused:
        _save_override(ctx, 9.0)
    assert refused.value.code == "AOI-USR-001" and ctx.recipe(BOARD)[0] == rev + 4
    assert len(ctx.audit_entries(action="recipe.ai_threshold")) == 2
    ctx.set_user("engineer")
    ctx.train(trainable(ctx, BOARD), epochs=1, image_size=32)  # a newly trained AI model, calibrated afresh
    newer = ctx.calibrated_threshold(BOARD)
    assert newer is not None and newer != cal and _judged_by(ctx, ng_board) == pytest.approx(newer)
    assert ctx.calibrated_threshold(BOARD, model["uuid"]) == cal, "the AI model a stored result names keeps its own"


DAMAGED: dict[str, Callable[[dict[str, Any]], str]] = {  # registry rows changed by hand, from what training stored
    "threshold-not-a-number": lambda meta: json.dumps({**meta, "image_threshold": "damaged"}),
    "threshold-true": lambda meta: json.dumps({**meta, "image_threshold": True}),  # no longer read as 1.0 (review)
    "no-pixel-threshold": lambda meta: json.dumps({k: v for k, v in meta.items() if k != "pixel_threshold"}),
    "not-json": lambda meta: "{not json",
    "not-an-object": lambda meta: "[]",
    "a-count-true": lambda meta: json.dumps({**meta, "n_ng": True, "image_threshold": None}),  # true is no count
}
NO_COUNTS = ("not-json", "not-an-object", "a-count-true")  # rows whose OK/NG sample counts cannot be read either


@pytest.mark.parametrize("damage", DAMAGED)
def test_req_trn_015_a_calibration_that_cannot_be_read_is_aoi_trn_012(
    qtbot: QtBot, trained_ctx: AppContext, damage: str
) -> None:
    """An AI model whose registry row holds no usable calibration (an AI score threshold and a pixel threshold, both
    above 0, as Re-evaluate needs them) is AOI-TRN-012, naming its version and board model, and so is a UUID the
    registry does not hold, named by the version a stored result gives; an override can still be saved, its entry naming
    no calibrated value. Training's Threshold column gives the code, with what happened and what to do as the row's
    tooltip and in a line under the table (one for each such row: the next test), where a row like it stopped the page;
    the sample counts beside it show while the row still gives them, and an empty cell where it does not. With no AI
    model active there is no calibrated value."""
    ctx = trained_ctx
    model = ctx.active_model(BOARD)
    assert model is not None
    meta = json.loads(model["metrics"])
    counts = f"{meta['n_ok_train'] + meta['n_ok_val']}/{meta['n_ng']}"
    ctx.db.execute("UPDATE models SET metrics=? WHERE uuid=?", (DAMAGED[damage](meta), model["uuid"]))  # by hand
    with pytest.raises(AoiError) as unreadable:
        ctx.calibrated_threshold(BOARD)
    assert unreadable.value.code == "AOI-TRN-012"
    assert f"AI model {model['version']} of board model {BOARD}" in unreadable.value.what
    with pytest.raises(AoiError) as gone:
        ctx.calibrated_threshold(BOARD, "a-uuid-the-registry-does-not-hold")
    assert gone.value.code == "AOI-TRN-012" and "AI model a-uuid-the-registry-does-not-hold of" in gone.value.what
    with pytest.raises(AoiError) as gone:  # a stored result's AI model, named by the version the result gives
        ctx.calibrated_threshold(BOARD, "a-uuid-the-registry-does-not-hold", "v0.9")
    assert gone.value.code == "AOI-TRN-012" and f"AI model v0.9 of board model {BOARD}" in gone.value.what
    _save_override(ctx, 4.0)
    entry = ctx.audit_entries(action="recipe.ai_threshold")[0]
    assert entry["before"]["threshold"] is entry["after"]["calibrated"] is None and entry["after"]["threshold"] == 4.0
    win = _window(qtbot, ctx, "Engineer")
    training = win.pages["Training"]
    assert isinstance(training, TrainingPage) and win.navigate("Training")
    (row,) = [r for r in range(training.models.rowCount()) if cell_text(training.models, r, 1) == model["version"]]
    assert cell_text(training.models, row, 3) == "AOI-TRN-012"
    tip = f"AOI-TRN-012 AI model {model['version']} of board model {BOARD} has no usable calibration in the AI model"
    assert cell_item(training.models, row, 3).toolTip().startswith(tip)
    assert "train again or activate another version on Training" in cell_item(training.models, row, 3).toolTip()
    note = training.models_note  # the same line under the table, read without a tooltip, by touch or key (review)
    assert note.isVisibleTo(training) and note.text() == cell_item(training.models, row, 3).toolTip()
    assert cell_text(training.models, row, 4) == ("" if damage in NO_COUNTS else counts)
    ctx.db.execute("UPDATE models SET active=0 WHERE board_model=?", (BOARD,))
    assert ctx.calibrated_threshold(BOARD) is None
    ctx.db.execute("UPDATE models SET metrics=? WHERE uuid=?", (model["metrics"], model["uuid"]))  # mended by hand
    training.refresh()
    assert "AOI-TRN-012" not in [cell_text(training.models, r, 3) for r in range(training.models.rowCount())]
    assert note.isHidden(), "no row it cannot read: no line under the table"


def test_req_trn_015_training_says_aoi_trn_012_for_every_ai_model_it_cannot_read(
    qtbot: QtBot, trained_ctx: AppContext
) -> None:
    """Training's line under the versions table gives each AI model version whose calibration it cannot read its own
    AOI-TRN-012 line, the row's tooltip, never only the first (review round 3); with no board model picked there is no
    table, and no line under it."""
    ctx = trained_ctx
    ctx.train(trainable(ctx, BOARD), epochs=1, image_size=32)  # a second AI model version
    models = ctx.models(BOARD)
    assert len(models) == 2
    for m in models:  # both registry rows changed by hand
        damaged = DAMAGED["threshold-not-a-number"](json.loads(m["metrics"]))
        ctx.db.execute("UPDATE models SET metrics=? WHERE uuid=?", (damaged, m["uuid"]))
    win = _window(qtbot, ctx, "Engineer")
    training = win.pages["Training"]
    assert isinstance(training, TrainingPage) and win.navigate("Training")
    tips = [cell_item(training.models, r, 3).toolTip() for r in range(training.models.rowCount())]
    said = sorted(
        f"AOI-TRN-012 AI model {m['version']} of board model {BOARD} has no usable calibration" for m in models
    )
    assert [tip[: len(s)] for tip, s in zip(sorted(tips), said, strict=True)] == said, tips
    note = training.models_note
    assert note.isVisibleTo(training) and sorted(note.text().split("\n")) == sorted(tips), "one line per row"
    win._on_board_model("")
    assert note.isHidden(), "no board model: no table, and no line under it"
