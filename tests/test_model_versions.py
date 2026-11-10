"""REQ-TRN-010 (stage S42, part 1): an AI model version and its Golden board are one: Activate and Roll Back switch both
together, in one call, with an audit entry, and every inspection records the version it used. Results on the synthetic
boards prove a code path; they are never quoted as accuracy."""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any, cast

import pytest

from aoi.core import anomaly
from aoi.core.imaging import list_images
from aoi.core.services import AppContext
from aoi.data.paths import resolve, to_stored
from aoi.errors import MISSING, AoiError
from tests.conftest import activated, another_version
from tests.test_train_from_version import BOARD, boards, oks
from tools.trainable import trainable

TINY = "TINY"  # the board model of trained_ctx (tests/conftest.py), whose v1.0 is active with its Golden board


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


def test_req_trn_010_activating_the_active_version_changes_nothing(trained_ctx: AppContext) -> None:
    """Activate Selected on the version already active wrote model.activate from v9.0 to v9.0, and Roll Back, which read
    that newest switch, then had no version to go to: greyed, and AOI-TRN-048 (review TRN-1). Now it changes nothing
    and writes nothing, and Roll Back still goes to the version active before."""
    ctx = trained_ctx
    first = cast(dict[str, Any], ctx.active_model(TINY))["version"]
    v9 = another_version(ctx, TINY, "v9.0")
    ctx.activate_model(v9)
    before = (ctx.active_model(TINY), ctx.reference_image(TINY), ctx.audit_entries())
    ctx.activate_model(v9)  # Activate Selected on the active row
    assert (ctx.active_model(TINY), ctx.reference_image(TINY), ctx.audit_entries()) == before
    assert ctx.rollback_model(TINY)["version"] == first


def test_req_trn_010_roll_back_passes_a_switch_that_changed_no_version(trained_ctx: AppContext) -> None:
    """A workspace may hold model.activate from v9.0 to v9.0, written by Activate Selected on the active row before it
    changed nothing, and activating the active version after Set Reference, which puts its Golden board back, writes one
    from v1.0 to v1.0; Roll Back read only the newest switch, so it had no version to go to (review TRN-1). Now it
    passes such an entry and goes to the version active before."""
    ctx, root = trained_ctx, trained_ctx.settings.root
    first = cast(dict[str, Any], ctx.active_model(TINY))
    golden = to_stored(golden_of(ctx, first), root)
    v9 = ctx.model(another_version(ctx, TINY, "v9.0"))
    ctx.activate_model(int(v9["id"]))
    same = {"active_version": "v9.0", "reference": golden}
    with ctx.db.transaction():  # as a station stored it before this fix
        ctx.audit("model.activate", "model", v9["uuid"], same, same)
    assert (ctx.previous_model(TINY) or {}).get("version") == first["version"]
    assert ctx.rollback_model(TINY)["version"] == first["version"]
    sample = ctx.samples(TINY, "OK")[0]
    ctx.set_reference(TINY, sample["id"])
    ctx.activate_model(int(first["id"]))  # the active version with its Golden board again: a switch of the board only
    entry = ctx.audit_entries(action="model.activate")[0]
    assert (entry["before"], entry["after"]) == (
        {"active_version": first["version"], "reference": to_stored(Path(sample["path"]), root)},
        {"active_version": first["version"], "reference": golden},
    )
    assert (ctx.previous_model(TINY) or {}).get("version") == "v9.0"


def test_req_trn_010_a_version_whose_ai_model_file_does_not_load_is_not_made_active(trained_ctx: AppContext) -> None:
    """Activate and Roll Back never loaded the version's AI model file, so a version whose .pt was missing, cut short or
    another AI model's went live, and every board was then refused with AOI-TRN-001 (review TRN-5). Now each is refused
    with AOI-TRN-048 naming the version, its file and why it does not load, loaded as load_model loads it, and the
    active version, the Golden board and the audit trail stay as they were."""
    ctx = trained_ctx
    first = cast(dict[str, Any], ctx.active_model(TINY))
    v9 = ctx.model(another_version(ctx, TINY, "v9.0"))
    pt = Path(v9["path"])
    whole = pt.read_bytes()
    harms = {  # the harm, and why the file does not load, in the app's own words
        "missing": (pt.unlink, MISSING),
        "cut short": (lambda: pt.write_bytes(whole[: len(whole) // 2]), anomaly.UNREADABLE),
        "another AI model's": (
            lambda: shutil.copyfile(first["path"], pt),
            f"its UUID {first['uuid']} is not {v9['uuid']}, as in the AI model registry",
        ),
    }
    for harm, (do, why) in harms.items():
        do()
        before = (ctx.active_model(TINY), ctx.reference_image(TINY), ctx.audit_entries())
        with pytest.raises(AoiError) as e:
            ctx.activate_model(int(v9["id"]))
        said = f"its AI model file {to_stored(pt, ctx.settings.root)} cannot be loaded ({why})"
        assert (e.value.code, str(e.value.params["reason"])) == ("AOI-TRN-048", said), harm
        assert (ctx.active_model(TINY), ctx.reference_image(TINY), ctx.audit_entries()) == before, harm
        pt.write_bytes(whole)
    ctx.activate_model(int(v9["id"]))  # whole again: it goes live
    Path(first["path"]).write_bytes(b"not an AI model file")  # the version Roll Back goes to
    with pytest.raises(AoiError) as e:
        ctx.rollback_model(TINY)
    assert e.value.code == "AOI-TRN-048" and cast(dict[str, Any], ctx.active_model(TINY))["version"] == "v9.0"
