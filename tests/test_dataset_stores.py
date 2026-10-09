"""REQ-TRN-017 (stage S38; ADR 0010): a customer's images and manifests are encrypted at rest in a dataset store of
their own, under a key the station keeps outside the workspace; a file that does not open is refused with a code and
never read as plain, and a board model's images are in one customer's store only."""

from __future__ import annotations

import sqlite3
from typing import Any

import pytest

from aoi.core import crypto
from aoi.core.services import AppContext
from aoi.data import credentials
from aoi.errors import AoiError

TWICE = "the customer has a store already, and has one at a time"
GONE = "the workspace holds no such store, or it is shredded"


def as_admin(ctx: AppContext, call: Any, *args: Any) -> Any:
    """`call(*args)` as the seeded Admin, then back to the engineer."""
    ctx.set_user("admin")
    try:
        return call(*args)
    finally:
        ctx.set_user("engineer")


def refusal(call: Any, *args: Any) -> tuple[str, str]:
    """The code and reason of the AoiError `call(*args)` raises."""
    with pytest.raises(AoiError) as refused:
        call(*args)
    return refused.value.code, str(refused.value.params.get("reason"))


def test_req_trn_017_key_saved_only_with_its_store(
    ctx: AppContext, keys: credentials.MemoryCredentials, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A store whose audit entry cannot be written leaves no key in the key store, and a key store that refuses the key
    leaves no store and no entry: AOI-TRN-044 with the system's reason."""
    written: list[str] = []
    monkeypatch.setattr(keys, "write", lambda name, secret: written.append(name))
    add = ctx.db.add_audit
    monkeypatch.setattr(ctx.db, "add_audit", lambda *a: (_ for _ in ()).throw(sqlite3.OperationalError("disk full")))
    with pytest.raises(sqlite3.OperationalError):
        as_admin(ctx, ctx.create_store, "Acme")
    assert written == [] and ctx.stores() == []
    monkeypatch.setattr(ctx.db, "add_audit", add)
    monkeypatch.setattr(keys, "write", lambda name, secret: (_ for _ in ()).throw(OSError("Access is denied")))
    refused = refusal(as_admin, ctx, ctx.create_store, "Acme")
    assert refused == ("AOI-TRN-044", "this station's key store refused the key (Access is denied)")
    assert ctx.stores() == [] and ctx.audit_entries(action="store.create") == []


def test_req_trn_017_store_made_once_and_key_restored(ctx: AppContext, keys: credentials.MemoryCredentials) -> None:
    """A customer has one store at a time, whatever the case or spaces of its name, and no store has no customer. The
    key is in the key store only, audited by its id, and the recovery sheet gives it back: a sheet that is not the
    store's key is refused with AOI-TRN-044 writing nothing, and the right one, typed in any case with hyphens, saves
    the key again, audited."""
    store = as_admin(ctx, ctx.create_store, " Acme ")
    name = credentials.STORE_PREFIX + store["uuid"]
    key = keys.read(name) or b""
    assert (store["customer"], len(key), crypto.key_from_sheet(store["sheet"])) == ("Acme", 32, key)
    assert refusal(as_admin, ctx, ctx.create_store, "ACME") == ("AOI-TRN-044", TWICE)
    assert refusal(as_admin, ctx, ctx.create_store, "  ") == ("AOI-TRN-044", "no customer is given")
    [listed] = ctx.stores()
    assert listed == {k: v for k, v in store.items() if k != "sheet"} | {"shredded_at": None, "board_models": []}
    [created] = ctx.audit_entries(action="store.create")
    assert created["after"] == {"customer": "Acme", "key_id": store["key_id"]} and created["role"] == "Admin"
    keys.delete(name)  # a new PC or Windows account
    typed = refusal(as_admin, ctx, ctx.restore_store_key, store["uuid"], crypto.sheet(bytes(range(32))))
    assert typed == ("AOI-TRN-044", "the key typed is not this store's key; check each group of four")
    assert refusal(as_admin, ctx, ctx.restore_store_key, "no-such-store", store["sheet"]) == ("AOI-TRN-044", GONE)
    assert keys.read(name) is None and ctx.audit_entries(action="store.restore") == []
    as_admin(ctx, ctx.restore_store_key, store["uuid"], store["sheet"].lower().replace(" ", "-"))
    [entry] = ctx.audit_entries(action="store.restore")
    assert keys.read(name) == key and (entry["object_uuid"], entry["after"]) == (
        store["uuid"],
        {"key_id": store["key_id"]},
    )
