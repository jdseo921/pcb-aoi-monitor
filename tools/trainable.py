"""A frozen, split dataset version to train from, in a customer's dataset store, written through the database rather
than through the app's freeze, lock and move-in (REQ-TRN-005, REQ-TRN-006, REQ-TRN-017; S39): for the screenshots
(tools/render_screens.py) and the tests, which then need no checked labels, no agreement check and no 50 OK images to
lock. Those steps have tests of their own (tests/test_datasets.py, test_validation_set.py, test_dataset_stores.py).
Never for a customer's data: the app's own steps are the ones that check it."""

from __future__ import annotations

from collections.abc import Collection

from aoi.core import crypto, datasets, stores
from aoi.core.services import AppContext
from aoi.data import credentials
from aoi.data.db import new_uuid
from aoi.data.paths import to_stored

AT = "2026-10-09T00:00:00+00:00"  # the time every row written here holds


def key_of(ctx: AppContext, store_uuid: str) -> bytes:
    """The key the key store holds for a store."""
    return ctx.credentials.read(credentials.STORE_PREFIX + store_uuid) or b""


def a_store(ctx: AppContext, customer: str) -> str:
    """The UUID of `customer`'s dataset store, its row and key stored through the database and the key store when
    missing, so that only the call under test is role-checked and audited."""
    if found := [s for s in ctx.db.stores() if s["customer"] == customer and not s["shredded_at"]]:
        return str(found[0]["uuid"])
    (key, key_id), uid, who = crypto.new_key(), new_uuid(), str(ctx.db.user_uuid("admin"))
    ctx.db.add_store({"uuid": uid, "customer": customer, "key_id": key_id.hex(), "check_value": crypto.check_value(key),
                      "created_by": who, "created_at": AT})  # fmt: skip
    ctx.credentials.write(credentials.STORE_PREFIX + uid, key)
    return uid


def in_store(ctx: AppContext, board_model: str, customer: str) -> None:
    """`board_model` in `customer`'s store with its files encrypted, as move_in leaves it, stored through the database
    where missing, so that only the call under test is role-checked and audited."""
    if ctx.db.board_model_store(board_model) is None:
        row = {"uuid": new_uuid(), "board_model": board_model, "store_uuid": a_store(ctx, customer)}
        ctx.db.add_board_model_store(row | {"set_by": "admin", "set_at": AT})
    store = ctx.db.board_model_store(board_model) or {}
    key = key_of(ctx, store["uuid"])
    for f in stores.files_of(ctx.settings.root, board_model, [d["name"] for d in ctx.db.datasets(board_model)]):
        if stores.header_of(f) is None:
            ctx._encrypt_in_place(store, key, f)


def trainable(
    ctx: AppContext,
    board_model: str,
    customer: str = "Acme Electronics",
    uses: Collection[str] = ("own",),
    held: Collection[str] = (),
    split: bool = True,
) -> str:
    """The UUID of a new frozen version of `board_model`'s OK and NG samples of the first sample's view, split with
    every file in its training set but those of the sample UUIDs `held`, locked for validation (not split at all
    unless `split`); the board model is in `customer`'s store first (`in_store`), and the version names that customer
    and allows `uses`."""
    in_store(ctx, board_model, customer)
    samples = [s for s in ctx.db.samples(board_model) if s["label"] in ("OK", "NG")]
    view = samples[0]["side"] if samples else "Top"
    n = 1 + sum(d["view"] == view for d in ctx.db.datasets(board_model))
    who, uid, name = str(ctx.db.user_uuid("engineer")), new_uuid(), datasets.name(board_model, "R1", view, n)
    version = {"uuid": uid, "name": name, "board_model": board_model, "revision": "R1", "view": view, "version": n}
    version |= {"customer": customer, "allowed_uses": list(uses), "agreement_check_uuid": new_uuid()}
    version |= {"manifest_path": f"{datasets.FOLDER}/{name}/manifest.json", "manifest_sha256": "0" * 64}
    keys = ("sample_uuid", "label_uuid", "label", "defect_type", "labelled_by", "checked_by")
    files = [
        {"path": to_stored(s["path"], ctx.settings.root), "sha256": s["sha256"], "boxes": []}
        | {k: s["uuid"] if k == "sample_uuid" else s[k] for k in keys}
        for s in samples
        if s["side"] == view
    ]
    with ctx.db.transaction():
        ctx.db.add_dataset(version | {"frozen_by": who, "frozen_at": AT}, files)
        items = ctx.db.dataset_items(uid) if split else []
        parts = {"train": [i for i in items if i["sample_uuid"] not in held]}
        parts["validation"] = [i for i in items if i["sample_uuid"] in held]
        if split:
            row = {"uuid": new_uuid(), "dataset_uuid": uid, "seed": 0, "locked_by": who, "locked_at": AT}
            ctx.db.add_split(row, parts)
    return uid
