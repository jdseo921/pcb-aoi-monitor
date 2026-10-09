"""REQ-TRN-007 and REQ-TRN-017 (stage S39): training takes a frozen dataset version and reads only its training set, at
least 20 OK images of one board model and view, of one customer's dataset store and for a use that customer allowed.
Results on the synthetic boards prove a code path; they are never quoted as accuracy."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from aoi.core import datasets
from aoi.core.imaging import encode_image, list_images, load_image
from aoi.core.services import AppContext
from aoi.data.db import new_uuid
from aoi.errors import AoiError
from tests.conftest import seal
from tests.test_dataset_stores import as_admin
from tools.make_synthetic_dataset import ng_type
from tools.trainable import AT, trainable

BOARD = "TBOX-A1"


def oks(synthetic_dataset: Path) -> list[str]:
    """The synthetic OK boards, the 20 of train/ first and then the 10 of test/."""
    return [str(p) for split in ("train", "test") for p in list_images(synthetic_dataset / split / "ok")]


def boards(ctx: AppContext, synthetic_dataset: Path, ok: int, ng: int = 3) -> list[dict[str, Any]]:
    """`ok` OK and `ng` NG synthetic boards imported into BOARD; its samples."""
    ctx.import_samples(BOARD, oks(synthetic_dataset)[:ok], "OK")
    for p in list_images(synthetic_dataset / "train" / "ng")[:ng]:
        ctx.import_samples(BOARD, [str(p)], "NG", ng_type(p))
    return ctx.samples(BOARD)


def refused(ctx: AppContext, version: str, use: str = "own") -> AoiError:
    """The AoiError training `version` for `use` raises."""
    with pytest.raises(AoiError) as e:
        ctx.train(version, epochs=1, image_size=32, use=use)
    return e.value


def spied(ctx: AppContext, monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """The names of the files training reads, as it reads them."""
    read: list[str] = []
    real = ctx._load_image_sha256
    monkeypatch.setattr(ctx, "_load_image_sha256", lambda path: read.append(Path(path).name) or real(path))
    return read


def test_req_trn_007_refuses_under_20_ok(
    ctx: AppContext, synthetic_dataset: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A training set of 19 OK images, the 20th locked for validation, is refused with AOI-TRN-045 before any image is
    read, and nothing is saved. With a 21st imported, the next version's 20, the locked image still locked, train an AI
    model whose OK images are the 20 and whose NG images only calibrate it, and which names the version it came from."""
    samples = boards(ctx, synthetic_dataset, 20)
    read = spied(ctx, monkeypatch)
    held = [samples[-4]["uuid"]]  # the last OK sample, before the 3 NG
    e = refused(ctx, trainable(ctx, BOARD, held=held))
    assert e.code == "AOI-TRN-045" and "its training set holds 19 OK image(s), and training needs 20" in e.what
    assert (read, ctx.models(BOARD), ctx.audit_entries(action="model.train")) == ([], [], [])
    ctx.import_samples(BOARD, oks(synthetic_dataset)[20:21], "OK")
    version = trainable(ctx, BOARD, held=held)
    meta = ctx.train(version, epochs=1, image_size=32)
    assert (meta["n_ok_train"] + meta["n_ok_val"], meta["n_ng"], len(meta["ok_scores"])) == (20, 3, meta["n_ok_val"])
    assert (meta["dataset"], meta["dataset_uuid"], meta["use"]) == (
        ctx.db.datasets("", version)[0]["name"],
        version,
        "own",
    )
    [entry] = ctx.audit_entries(action="model.train")
    assert entry["after"]["metrics"]["dataset_uuid"] == version
    assert datasets.TRAIN_OK == 20


def test_req_trn_007_trains_only_on_a_locked_versions_training_set(
    ctx: AppContext, synthetic_dataset: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """No such version, and a version whose validation set is not locked, are refused with AOI-TRN-045; Training trains
    from the newest locked version. A run reads its training set's files and none of its validation set's, and a file
    whose bytes are not the ones frozen stops it with AOI-TRN-045 naming the file, nothing saved."""
    samples = boards(ctx, synthetic_dataset, 22)
    e = refused(ctx, new_uuid())
    assert e.code == "AOI-TRN-045" and "the workspace holds no such dataset version" in e.what
    with pytest.raises(AoiError) as none:
        ctx.training_version(BOARD)
    assert none.value.code == "AOI-TRN-045" and "no frozen dataset version of it" in none.value.what
    unsplit = trainable(ctx, BOARD, split=False)
    e = refused(ctx, unsplit)
    assert e.code == "AOI-TRN-045" and "its validation set is not locked" in e.what
    held = [samples[0]["uuid"], samples[1]["uuid"], samples[-1]["uuid"]]  # 2 OK and 1 NG locked
    version = trainable(ctx, BOARD, held=held)
    assert ctx.training_version(BOARD)["uuid"] == version
    read = spied(ctx, monkeypatch)
    meta = ctx.train(version, epochs=1, image_size=32)
    names = {Path(s["path"]).name for s in samples}
    locked = {Path(s["path"]).name for s in samples if s["uuid"] in held}
    assert set(read) == names - locked and (meta["n_ok_train"] + meta["n_ok_val"], meta["n_ng"]) == (20, 2)
    item = next(i for i in ctx.dataset_items(version) if i["label"] == "OK" and i["sample_uuid"] not in held)
    other = encode_image(item["path"], load_image(oks(synthetic_dataset)[25]))
    seal(ctx, item["path"], BOARD, other)  # another board in its place, encrypted as the store's own files are
    e = refused(ctx, version)
    assert e.code == "AOI-TRN-045" and f"{item['path']} is not the file frozen, by its SHA-256" in e.what
    assert len(ctx.models(BOARD)) == 1


def test_req_trn_017_use_beyond_permission_refused(ctx: AppContext, synthetic_dataset: Path) -> None:
    """A run for a use the version's customer did not allow is refused with AOI-TRN-046 and an audit entry naming the
    use, the customer and why, nothing trained; a version that allows the use trains for it, as its AI model says."""
    boards(ctx, synthetic_dataset, 20)
    own = trainable(ctx, BOARD)
    e = refused(ctx, own, use="demos")
    assert (e.code, e.params["use"]) == ("AOI-TRN-046", "demos") and "Acme Electronics allowed only own" in e.what
    [entry] = ctx.audit_entries(action="training.refused")
    assert (entry["object_uuid"], entry["role"], entry["reason"]) == (
        own,
        "Engineer",
        "Acme Electronics allowed only own",
    )
    assert entry["after"] == {"use": "demos", "customer": "Acme Electronics", "code": "AOI-TRN-046"}
    assert ctx.models(BOARD) == []
    both = trainable(ctx, BOARD, uses=("own", "demos"))
    assert ctx.train(both, epochs=1, image_size=32, use="demos")["use"] == "demos"


def test_req_trn_017_training_from_another_customers_store_refused(ctx: AppContext, synthetic_dataset: Path) -> None:
    """A version that names another customer than the store its images are in, one whose board model is in no store,
    and one whose store is shredded are each refused with AOI-TRN-046 and an audit entry, nothing trained: a run never
    mixes customers."""
    boards(ctx, synthetic_dataset, 20)
    trainable(ctx, BOARD)  # TBOX-A1's images in Acme Electronics' store
    beta = trainable(ctx, BOARD, customer="Beta")
    e = refused(ctx, beta)
    assert e.code == "AOI-TRN-046" and "in the dataset store of Acme Electronics, not of Beta" in e.what
    loose = new_uuid()  # a version of a board model in no store, as one frozen before stores could be
    who = str(ctx.db.user_uuid("engineer"))
    row = {"uuid": loose, "name": "DS-LOOSE-R1-TOP-v1", "board_model": "LOOSE", "revision": "R1", "view": "Top"}
    row |= {"version": 1, "customer": "Acme Electronics", "allowed_uses": ["own"], "agreement_check_uuid": loose}
    row |= {"manifest_path": "datasets/DS-LOOSE-R1-TOP-v1/manifest.json", "manifest_sha256": "0" * 64}
    ctx.db.add_dataset(row | {"frozen_by": who, "frozen_at": AT}, [])
    e = refused(ctx, loose)
    assert e.code == "AOI-TRN-046" and "its images are in no customer's dataset store" in e.what
    store = ctx.store_of(BOARD) or {}
    as_admin(ctx, ctx.shred_store, store["uuid"])
    e = refused(ctx, trainable(ctx, BOARD))
    assert e.code == "AOI-TRN-046" and "its dataset store was shredded on" in e.what
    assert len(ctx.audit_entries(action="training.refused")) == 3 and ctx.models(BOARD) == []
