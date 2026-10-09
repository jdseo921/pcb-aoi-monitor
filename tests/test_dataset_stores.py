"""REQ-TRN-017 (stage S38; ADR 0010): a customer's images and manifests are encrypted at rest in a dataset store of
their own, under a key the station keeps outside the workspace; a file that does not open is refused with a code and
never read as plain, and a board model's images are in one customer's store only."""

from __future__ import annotations

import errno
import hashlib
import json
import shutil
import sqlite3
import tempfile
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
from tests.test_datasets import agree, ready
from tests.test_labeller_agreement import CAL

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


def test_req_trn_017_changed_moved_or_foreign_file_refused(ctx: AppContext, tmp_path: Path) -> None:
    """A file of a store swapped with another of its files, one with a bit changed, a plain image put in its place and
    another store's file put in its place are each refused with AOI-TRN-025 naming the file, verify_dataset lists them
    changed, and the freeze is refused; moving the board model in again refuses the other store's file."""
    samples, cal = ready(ctx, tmp_path / "boards")
    agree(ctx, cal, samples)
    v1 = ctx.freeze_dataset(CAL, "Top", "R3", "Acme")
    board(ctx, "B2", tmp_path / "b2", 1, 9)
    moved_in(ctx, "B2", "Beta")
    paths, root = [i["path"] for i in ctx.dataset_items(v1["uuid"])], ctx.settings.root
    a, b = root / paths[3], root / paths[4]
    swap = a.read_bytes()
    a.write_bytes(b.read_bytes())
    b.write_bytes(swap)
    data = bytearray((root / paths[5]).read_bytes())
    data[len(data) // 2] ^= 1
    (root / paths[5]).write_bytes(bytes(data))
    shutil.copyfile(tmp_path / "boards" / "board_000.png", root / paths[6])
    shutil.copyfile(ctx.samples("B2")[0]["path"], root / paths[7])
    damaged = "{file} was changed, moved or damaged since it was written"
    expected = [damaged, damaged, damaged, "{file} is not encrypted", "{file} is encrypted under another store's key"]
    for path, reason in zip(paths[3:8], expected, strict=True):
        assert refusal(ctx.load_image, root / path) == ("AOI-TRN-025", reason.format(file=path))
    checked = ctx.verify_dataset(v1["uuid"])
    assert (checked["manifest"], checked["changed"], checked["missing"]) == ("same", paths[3:8], [])
    assert refusal(ctx.freeze_dataset, CAL, "Top", "R3", "Acme")[0] == "AOI-TRN-025" and len(ctx.datasets(CAL)) == 1
    again = refusal(as_admin, ctx, ctx.move_in, CAL, (ctx.store_of(CAL) or {})["uuid"])
    assert again == ("AOI-TRN-044", f"{paths[7]} is encrypted under another store's key")
    assert ctx.audit_entries(action="store.move_in")[0]["after"]["board_model"] == "B2"  # the refusal wrote nothing


def test_req_trn_017_mixed_customers_refused(ctx: AppContext, tmp_path: Path) -> None:
    """A version is frozen only from a board model in the store of the customer it names: in no store, or in another
    customer's, it is refused with AOI-TRN-027 writing nothing. A board model joins one store and never leaves it, and
    the rows refuse to change or go. The version's manifest is encrypted in the store too, and a station without the
    key cannot verify it (AOI-TRN-025)."""
    samples, cal = ready(ctx, tmp_path / "boards", customer=None)
    agree(ctx, cal, samples)
    none = "its images are in no customer's dataset store; an Admin moves them in"
    assert refusal(ctx.freeze_dataset, CAL, "Top", "R3", "Acme") == ("AOI-TRN-027", none)
    acme, beta = (as_admin(ctx, ctx.create_store, name)["uuid"] for name in ("Acme", "Beta"))
    as_admin(ctx, ctx.move_in, CAL, acme)
    left = f"{CAL} is in the store of Acme, and a board model never leaves it"
    assert refusal(as_admin, ctx, ctx.move_in, CAL, beta) == ("AOI-TRN-044", left)
    assert refusal(as_admin, ctx, ctx.move_in, "NOPE", acme) == (
        "AOI-TRN-044",
        "the workspace holds no board model NOPE",
    )
    assert refusal(as_admin, ctx, ctx.move_in, CAL, "no-such-store") == ("AOI-TRN-044", GONE)
    other = "its images are in the dataset store of Acme, not of Beta"
    assert refusal(ctx.freeze_dataset, CAL, "Top", "R3", "Beta") == ("AOI-TRN-027", other)
    assert ctx.datasets(CAL) == [] and ctx.audit_entries(action="dataset.freeze") == []
    assert len(ctx.audit_entries(action="store.move_in")) == 1
    v1 = ctx.freeze_dataset(CAL, "Top", "R3", " Acme ")
    manifest = (ctx.settings.root / v1["manifest_path"]).read_bytes()
    assert v1["customer"] == "Acme" and manifest.startswith(crypto.MAGIC) and b'"files"' not in manifest
    assert json.loads(plain(ctx, v1["manifest_path"], CAL))["name"] == v1["name"]
    for sql in ("UPDATE dataset_stores SET customer='Beta'", "DELETE FROM dataset_stores",
                "UPDATE board_model_stores SET store_uuid='x'", "DELETE FROM board_model_stores"):  # fmt: skip
        with pytest.raises(sqlite3.DatabaseError, match="never|shredded"):
            ctx.db.execute(sql)
    ctx.close()
    station = AppContext(ctx.settings, key_store=credentials.MemoryCredentials())
    try:
        assert refusal(station.verify_dataset, v1["uuid"]) == ("AOI-TRN-025", NO_KEY)
    finally:
        station.close()


def test_req_trn_017_shred_ends_store_for_good(
    ctx: AppContext, keys: credentials.MemoryCredentials, tmp_path: Path
) -> None:
    """Shredding a store deletes its key, records it (a row and store.shred with the key id and counts) and deletes its
    board model's images, its frozen versions' folders and its AI models and Golden boards; the rows stay. From then on
    a file of it, a copy put back included, does not open: reading, verifying, importing and freezing are refused with
    the day it was shredded, and the store takes no move-in or key. Another customer's store is untouched, the customer
    may have a new store, and shredding it again deletes what was put back, audited."""
    samples, cal = ready(ctx, tmp_path / "boards")
    agree(ctx, cal, samples)
    v1 = ctx.freeze_dataset(CAL, "Top", "R3", "Acme")
    board(ctx, "B2", tmp_path / "b2", 1, 9)
    beta = moved_in(ctx, "B2", "Beta")
    acme, root, models = ctx.store_of(CAL) or {}, ctx.settings.root, ctx.settings.models_dir / CAL
    models.mkdir(parents=True)
    (models / f"{CAL}_v1.pt").write_bytes(b"weights")  # an AI model of the board model, plain under models/
    path = Path(ctx.samples(CAL)[0]["path"])
    shutil.copyfile(path, tmp_path / "backup")
    count = len(ctx.samples(CAL)) + 1  # its images and v1's manifest
    assert as_admin(ctx, ctx.shred_store, acme["uuid"]) == {"files": count, "models": 1}
    assert keys.read(credentials.STORE_PREFIX + acme["uuid"]) is None
    assert [(root / f).exists() for f in (f"images/{CAL}", f"datasets/{v1['name']}", models)] == [False] * 3
    day = str((ctx.store_of(CAL) or {})["shredded_at"])[:10]
    path.parent.mkdir(parents=True)
    shutil.copyfile(tmp_path / "backup", path)  # a copy kept elsewhere, put back
    assert refusal(ctx.load_image, path) == ("AOI-TRN-025", f"it was shredded on {day}")
    assert refusal(ctx.verify_dataset, v1["uuid"]) == ("AOI-TRN-025", f"it was shredded on {day}")
    assert refusal(ctx.import_samples, CAL, [str(tmp_path / "b2" / "B2_0.png")], "OK")[0] == "AOI-TRN-025"
    assert refusal(ctx.freeze_dataset, CAL, "Top", "R3", "Acme") == (
        "AOI-TRN-027",
        f"its dataset store was shredded on {day}",
    )
    assert refusal(as_admin, ctx, ctx.move_in, CAL, acme["uuid"]) == ("AOI-TRN-044", GONE)
    assert refusal(as_admin, ctx, ctx.restore_store_key, acme["uuid"], crypto.sheet(bytes(32))) == ("AOI-TRN-044", GONE)
    assert ctx.load_image(ctx.samples("B2")[0]["path"]).shape == (32, 32, 3)
    assert keys.read(credentials.STORE_PREFIX + beta["uuid"]) is not None
    assert as_admin(ctx, ctx.create_store, "acme")["customer"] == "acme"  # a new engagement, a new key
    [entry] = ctx.audit_entries(action="store.shred")
    assert entry["role"] == "Admin" and entry["after"] == {
        "customer": "Acme", "key_id": acme["key_id"], "board_models": [CAL], "files": count, "models": 1,
        "resumed": False,
    }  # fmt: skip
    assert as_admin(ctx, ctx.shred_store, acme["uuid"]) == {"files": 1, "models": 0}  # the copy put back
    assert not path.exists()
    assert ctx.audit_entries(action="store.shred")[0]["after"]["resumed"] is True
    assert ctx.db.query("SELECT key_id, files FROM store_shreds") == [{"key_id": acme["key_id"], "files": count}]
    for sql in ("UPDATE store_shreds SET files=0", "DELETE FROM store_shreds"):
        with pytest.raises(sqlite3.DatabaseError, match="never"):
            ctx.db.execute(sql)
    assert refusal(as_admin, ctx, ctx.shred_store, "no-such-store") == (
        "AOI-TRN-044",
        "the workspace holds no such store",
    )


def test_req_trn_017_interrupted_shred_resumes(
    ctx: AppContext, keys: credentials.MemoryCredentials, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A key store that will not delete the key refuses the shred with AOI-TRN-044, changing nothing. A shred stopped
    after the key went and before it was recorded leaves nothing of the store readable, and the next call records it; a
    file that would not go is named, the rest are gone and the shred stays recorded, and the next call deletes it."""
    board(ctx, "SHR", tmp_path / "shr", 3, 5)
    store, root = moved_in(ctx, "SHR", "Acme"), ctx.settings.root
    paths, name = [Path(s["path"]) for s in ctx.samples("SHR")], credentials.STORE_PREFIX + store["uuid"]
    delete = keys.delete
    monkeypatch.setattr(keys, "delete", lambda n: (_ for _ in ()).throw(OSError("Access is denied")))
    refused = refusal(as_admin, ctx, ctx.shred_store, store["uuid"])
    assert refused == ("AOI-TRN-044", "this station's key store did not delete the key (Access is denied)")
    assert keys.read(name) is not None and not ctx.stores()[0]["shredded_at"] and all(p.exists() for p in paths)
    assert ctx.load_image(paths[0]).shape == (32, 32, 3) and ctx.audit_entries(action="store.shred") == []
    monkeypatch.setattr(keys, "delete", delete)
    add = ctx.db.add_audit
    monkeypatch.setattr(ctx.db, "add_audit", lambda *a: (_ for _ in ()).throw(sqlite3.OperationalError("disk full")))
    with pytest.raises(sqlite3.OperationalError):
        as_admin(ctx, ctx.shred_store, store["uuid"])
    assert keys.read(name) is None and not ctx.stores()[0]["shredded_at"] and all(p.exists() for p in paths)
    assert refusal(ctx.load_image, paths[0]) == ("AOI-TRN-025", NO_KEY)
    monkeypatch.setattr(ctx.db, "add_audit", add)
    unlink = Path.unlink

    def held(self: Path, missing_ok: bool = False) -> None:
        if self == paths[1]:
            raise PermissionError(errno.EACCES, "The file is open in another program", str(self))
        unlink(self, missing_ok=missing_ok)

    monkeypatch.setattr(Path, "unlink", held)
    code, reason = refusal(as_admin, ctx, ctx.shred_store, store["uuid"])
    stuck = paths[1].relative_to(root).as_posix()
    assert code == "AOI-TRN-044" and reason.startswith(f"1 file(s) would not go, {stuck} first ([Errno 13] The file")
    assert reason.endswith("; shred it again") and [p.exists() for p in paths] == [False, True, False]
    assert ctx.stores()[0]["shredded_at"]
    monkeypatch.setattr(Path, "unlink", unlink)
    assert as_admin(ctx, ctx.shred_store, store["uuid"]) == {"files": 1, "models": 0}
    assert not (root / "images" / "SHR").exists()
    shreds = ctx.audit_entries(action="store.shred")
    assert [(e["after"]["files"], e["after"]["resumed"]) for e in shreds] == [(1, True), (3, False)]


def test_req_trn_017_no_plain_file_while_training(
    ctx: AppContext, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Training an AI model of a board model in a store reads its images decrypted in memory only (ADR 0010, decision
    11): no file in the workspace or the temp folder after the run holds an image's plain bytes or its pixels, and the
    images stay encrypted."""
    sources = board(ctx, "TRN", tmp_path / "trn", 3, 6)
    moved_in(ctx, "TRN", "Acme")
    temp = tmp_path / "temp"
    temp.mkdir()
    monkeypatch.setattr(tempfile, "tempdir", str(temp))
    ctx.train("TRN", epochs=1, image_size=32)
    secrets = [s.read_bytes() for s in sources] + [
        np.asarray(ctx.load_image(s["path"])).tobytes() for s in ctx.samples("TRN")
    ]
    written = [p for p in [*ctx.settings.root.rglob("*"), *temp.rglob("*")] if p.is_file()]
    assert any(p.suffix == ".pt" for p in written)
    for f in written:
        data = f.read_bytes()
        assert not any(s in data for s in secrets), f
    assert all(Path(s["path"]).read_bytes().startswith(crypto.MAGIC) for s in ctx.samples("TRN"))
