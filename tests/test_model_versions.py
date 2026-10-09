"""REQ-TRN-010 (stage S42, part 1): an AI model version and its Golden board are one: Activate and Roll Back switch both
together, in one call, with an audit entry, and every inspection records the version it used. Results on the synthetic
boards prove a code path; they are never quoted as accuracy."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from aoi.core.imaging import list_images
from aoi.core.services import AppContext
from aoi.data.paths import resolve, to_stored
from aoi.errors import AoiError
from tests.conftest import activated
from tests.test_train_from_version import BOARD, boards, oks
from tools.trainable import trainable


def two_versions(ctx: AppContext, synthetic_dataset: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    """v1.0 trained from 21 OK boards and v1.1 from 26, each with its own Golden board; v1.1 is active."""
    boards(ctx, synthetic_dataset, 21)
    activated(ctx, ctx.train(trainable(ctx, BOARD), epochs=1, image_size=32))
    ctx.import_samples(BOARD, oks(synthetic_dataset)[21:26], "OK")
    activated(ctx, ctx.train(trainable(ctx, BOARD), epochs=1, image_size=32))
    new, old = ctx.models(BOARD)  # newest first
    return old, new


def golden_of(ctx: AppContext, model: dict[str, Any]) -> Path:
    """The Golden board file a model version records."""
    return resolve(json.loads(model["metrics"])["golden_image"], ctx.settings.root)


def test_req_trn_010_rollback_restores_golden_board(ctx: AppContext, synthetic_dataset: Path) -> None:
    """Roll Back makes the version active before the active one active again, with its own Golden board, in one call
    audited as model.rollback; a second Roll Back returns to the version rolled back from."""
    old, new = two_versions(ctx, synthetic_dataset)
    assert golden_of(ctx, old) != golden_of(ctx, new)
    assert Path(ctx.reference_image(BOARD) or "") == golden_of(ctx, new)
    assert ctx.previous_model(BOARD)["version"] == old["version"]  # type: ignore[index]
    back = ctx.rollback_model(BOARD)
    assert back["version"] == old["version"] == ctx.active_model(BOARD)["version"]  # type: ignore[index]
    assert Path(ctx.reference_image(BOARD) or "") == golden_of(ctx, old)
    [entry] = ctx.audit_entries(action="model.rollback")
    root = ctx.settings.root
    assert entry["object_uuid"] == old["uuid"]
    assert entry["before"] == {"active_version": new["version"], "reference": to_stored(golden_of(ctx, new), root)}
    assert entry["after"] == {"active_version": old["version"], "reference": to_stored(golden_of(ctx, old), root)}
    ctx.rollback_model(BOARD)
    assert ctx.active_model(BOARD)["version"] == new["version"]  # type: ignore[index]
    assert Path(ctx.reference_image(BOARD) or "") == golden_of(ctx, new)


def test_req_trn_010_activation_audited(ctx: AppContext, synthetic_dataset: Path) -> None:
    """Activate switches the AI model and its Golden board together and audits both, before and after."""
    old, new = two_versions(ctx, synthetic_dataset)
    ctx.activate_model(int(old["id"]))
    assert ctx.active_model(BOARD)["version"] == old["version"]  # type: ignore[index]
    assert Path(ctx.reference_image(BOARD) or "") == golden_of(ctx, old)
    entry = ctx.audit_entries(action="model.activate")[0]  # newest first; each training's version was activated too
    assert (entry["before"]["active_version"], entry["after"]["active_version"]) == (new["version"], old["version"])
    assert entry["after"]["reference"] == to_stored(golden_of(ctx, old), ctx.settings.root)


def test_req_trn_010_inspection_records_version(ctx: AppContext, synthetic_dataset: Path) -> None:
    """A board inspected after a rollback is judged by the rolled-back version and its Golden board, and its record
    names that version."""
    old, _ = two_versions(ctx, synthetic_dataset)
    ctx.rollback_model(BOARD)
    board = str(list_images(synthetic_dataset / "test" / "ok")[0])
    insp = ctx.inspector(BOARD)
    assert ctx.engine_is_current(BOARD, insp)
    ctx.inspect_file(BOARD, board, insp)
    [record] = ctx.inspections(board_model=BOARD)
    assert (record["model_version"], record["model_uuid"]) == (old["version"], old["uuid"])


def test_req_trn_010_refusals_change_nothing(ctx: AppContext, synthetic_dataset: Path) -> None:
    """Roll Back with no earlier active version, and Activate of a version whose Golden board cannot be read, are
    refused with AOI-TRN-048; the active version, the Golden board and the audit trail stay as they were."""
    boards(ctx, synthetic_dataset, 21)
    activated(ctx, ctx.train(trainable(ctx, BOARD), epochs=1, image_size=32))
    with pytest.raises(AoiError) as e:
        ctx.rollback_model(BOARD)
    assert e.value.code == "AOI-TRN-048" and "no earlier version of this board model was active" in e.value.what
    ctx.import_samples(BOARD, oks(synthetic_dataset)[21:26], "OK")
    activated(ctx, ctx.train(trainable(ctx, BOARD), epochs=1, image_size=32))
    new, old = ctx.models(BOARD)
    golden_of(ctx, old).unlink()
    reference, entries = ctx.reference_image(BOARD), ctx.audit_entries()
    with pytest.raises(AoiError) as e:
        ctx.activate_model(int(old["id"]))
    assert e.value.code == "AOI-TRN-048" and "cannot be read" in e.value.what
    assert ctx.active_model(BOARD)["version"] == new["version"]  # type: ignore[index]
    assert (ctx.reference_image(BOARD), ctx.audit_entries()) == (reference, entries)
