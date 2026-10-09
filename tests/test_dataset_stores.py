"""REQ-TRN-017 (stage S38; ADR 0010): a customer's images and manifests are encrypted at rest in a dataset store of
their own, under a key the station keeps outside the workspace; a file that does not open is refused with a code and
never read as plain, and a board model's images are in one customer's store only."""

from __future__ import annotations

import errno
import hashlib
import sqlite3
from pathlib import Path
from typing import Any

import numpy as np
import pytest

from aoi.core import crypto
from aoi.core.imaging import image_header, save_image
from aoi.core.services import AppContext
from aoi.data import atomic, credentials
from aoi.errors import AoiError
from tests.conftest import plain

TWICE = "the customer has a store already, and has one at a time"
GONE = "the workspace holds no such store, or it is shredded"
NO_KEY = "this station holds no key for it"


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


def board(ctx: AppContext, name: str, folder: Path, n: int, seed: int) -> list[Path]:
    """`n` OK images of 32 x 32 px imported into `name`; returns the sources, which stay plain."""
    folder.mkdir()
    rng, paths = np.random.default_rng(seed), [folder / f"{name}_{i}.png" for i in range(n)]
    for p in paths:
        save_image(p, rng.integers(0, 256, (32, 32, 3), dtype=np.uint8))
    ctx.import_samples(name, [str(p) for p in paths], "OK")
    return paths


def moved_in(ctx: AppContext, board_model: str, customer: str) -> dict[str, Any]:
    """`board_model` moved by the admin into a new store of `customer`; returns the store, its sheet included."""
    store = as_admin(ctx, ctx.create_store, customer)
    as_admin(ctx, ctx.move_in, board_model, store["uuid"])
    return dict(store)


def test_req_trn_017_store_encrypted_at_rest(ctx: AppContext, tmp_path: Path) -> None:
    """Once a board model is moved into a customer's store, no file under images/<board model> is an image on disk, each
    reads back as the bytes hashed at import, and a file imported later is written encrypted; a board model in no store
    stays plain. Neither the key nor its sheet is in any file of the workspace, the database among them. A board model
    whose name is not one folder's is refused (AOI-TRN-019), moving nothing."""
    sources = board(ctx, "ENC", tmp_path / "enc", 5, 2)
    store = as_admin(ctx, ctx.create_store, "Acme")
    assert as_admin(ctx, ctx.move_in, "ENC", store["uuid"]) == {"moved": 5, "already": 0}
    assert as_admin(ctx, ctx.move_in, "ENC", store["uuid"]) == {"moved": 0, "already": 5}
    sources += board(ctx, "PLAIN", tmp_path / "plain", 1, 3)
    ctx.import_samples("ENC", [str(sources[-1])], "OK")
    for s, src in zip(ctx.samples("ENC"), sources, strict=True):
        raw, data = Path(s["path"]).read_bytes(), src.read_bytes()
        assert raw.startswith(crypto.MAGIC) and image_header(raw) is None, s["path"]
        assert plain(ctx, s["path"], "ENC") == data and s["sha256"] == hashlib.sha256(data).hexdigest()
        assert ctx.load_image(s["path"]).shape == (32, 32, 3)
    assert Path(ctx.samples("PLAIN")[0]["path"]).read_bytes() == sources[-1].read_bytes()  # in no store: as imported
    assert ctx.stores()[0]["board_models"] == ["ENC"] and ctx.store_of("PLAIN") is None
    assert (ctx.store_of("ENC") or {})["uuid"] == store["uuid"]
    key, sheet = crypto.key_from_sheet(store["sheet"]) or b"", store["sheet"].replace(" ", "").encode()
    for f in [p for p in ctx.settings.root.rglob("*") if p.is_file()]:
        data = f.read_bytes()
        assert key not in data and key.hex().encode() not in data and sheet not in data, f
    ctx.db.ensure_board_model(".")  # named before names were checked (#112): its folder would be all of images/
    assert refusal(as_admin, ctx, ctx.move_in, ".", store["uuid"])[0] == "AOI-TRN-019" and ctx.store_of(".") is None
    assert Path(ctx.samples("PLAIN")[0]["path"]).read_bytes() == sources[-1].read_bytes()
    moves = ctx.audit_entries(action="store.move_in")
    assert [(e["after"]["files"], e["after"]["resumed"]) for e in moves] == [(0, True), (5, False)]


def test_req_trn_017_missing_or_wrong_key_refused(ctx: AppContext, tmp_path: Path) -> None:
    """On a station that holds no key for a store, or another key under its name, a file of it is refused with
    AOI-TRN-025 naming the customer and why, never read, and nothing is moved in; the store's recovery sheet typed there
    restores reading."""
    board(ctx, "ENC", tmp_path / "enc", 2, 2)
    store = moved_in(ctx, "ENC", "Acme")
    path = ctx.samples("ENC")[0]["path"]
    ctx.close()
    other = AppContext(ctx.settings, key_store=credentials.MemoryCredentials())  # a new PC or Windows account
    try:
        with pytest.raises(AoiError) as refused:
            other.load_image(path)
        assert (refused.value.code, refused.value.params["store"], str(refused.value.params["reason"])) == (
            "AOI-TRN-025", "Acme", NO_KEY
        )  # fmt: skip
        assert refusal(as_admin, other, other.move_in, "ENC", store["uuid"]) == ("AOI-TRN-025", NO_KEY)
        other.credentials.write(credentials.STORE_PREFIX + store["uuid"], bytes(32))
        assert refusal(other.load_image, path) == ("AOI-TRN-025", "the key this station holds is not its key")
        as_admin(other, other.restore_store_key, store["uuid"], store["sheet"])
        assert other.load_image(path).shape == (32, 32, 3)
    finally:
        other.close()


def test_req_trn_017_interrupted_move_in_resumes(
    ctx: AppContext, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A move-in stopped by a write the disk refuses leaves that file plain and as it was, refused from then on as not
    encrypted rather than read as plain; moving the board model in again encrypts the rest and skips the files moved
    already, and each try is audited."""
    sources = board(ctx, "RES", tmp_path / "res", 6, 4)
    acme, write, calls = as_admin(ctx, ctx.create_store, "Acme")["uuid"], atomic.write_bytes, []

    def full(path: Any, data: bytes) -> None:
        calls.append(path)
        if len(calls) == 3:
            raise OSError(errno.ENOSPC, "No space left on device", str(path))
        write(path, data)

    monkeypatch.setattr(atomic, "write_bytes", full)
    code, reason = refusal(as_admin, ctx, ctx.move_in, "RES", acme)
    samples = ctx.samples("RES")
    stopped = samples[2]["path"]
    assert code == "AOI-TRN-044" and reason.startswith(f"{Path(stopped).relative_to(ctx.settings.root).as_posix()} did")
    assert Path(stopped).read_bytes() == sources[2].read_bytes() and (ctx.store_of("RES") or {})["uuid"] == acme
    assert ctx.load_image(samples[0]["path"]).shape == (32, 32, 3)
    assert refusal(ctx.load_image, stopped)[1].endswith(" is not encrypted")
    monkeypatch.setattr(atomic, "write_bytes", write)
    assert as_admin(ctx, ctx.move_in, "RES", acme) == {"moved": 4, "already": 2}
    for s, src in zip(ctx.samples("RES"), sources, strict=True):
        assert (
            Path(s["path"]).read_bytes().startswith(crypto.MAGIC) and plain(ctx, s["path"], "RES") == src.read_bytes()
        )
    moves = ctx.audit_entries(action="store.move_in")
    assert [(e["after"]["files"], e["after"]["resumed"]) for e in moves] == [(4, True), (6, False)]
