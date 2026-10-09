"""REQ-TRN-006 (stage S36): a frozen dataset version is split once, seeded and recorded, into a training set and a
locked validation set of at least 50 OK images and 30 % of the NG, by defect type where it can; locking is audited and
never undone, and training refuses to start while an image it would read is locked, by its content, not its path."""

from __future__ import annotations

import hashlib
import sqlite3
from pathlib import Path
from typing import Any

import numpy as np
import pytest

from aoi.core import datasets
from aoi.core.imaging import save_image
from aoi.core.services import AppContext
from aoi.errors import AoiError
from tests.conftest import plain
from tests.test_datasets import agree, ready
from tests.test_labeller_agreement import CAL
from tools.trainable import trainable


def frozen(ctx: AppContext, tmp_path: Path) -> dict[str, Any]:
    """CAL-1's version 1: 80 OK and 20 NG (Scratch) images of 32 x 32 px, checked and agreed."""
    samples, cal = ready(ctx, tmp_path / "boards")
    agree(ctx, cal, samples)
    return ctx.freeze_dataset(CAL, "Top", "R3", "Acme")


def items(n_ok: int, types: dict[str, int]) -> list[dict[str, Any]]:
    """Dataset items as the rows hold them: n_ok OK files, and per defect type that many NG files boxed with it."""
    rows = [("OK", None, f"ok{i}") for i in range(n_ok)]
    rows += [("NG", kind, f"{kind}{i}") for kind, n in types.items() for i in range(n)]
    return [
        {"uuid": f"u-{key}", "sha256": hashlib.sha256(key.encode()).hexdigest(), "label": label, "defect_type": None,
         "boxes": [{"dct_type": kind}] if kind else []}
        for label, kind, key in rows
    ]  # fmt: skip


def test_req_trn_006_minimums_enforced(ctx: AppContext, tmp_path: Path) -> None:
    """A version with fewer than 50 OK images, one the workspace does not hold and one split already are refused with
    AOI-TRN-022, writing nothing; a lock holds 50 OK images and 30 % of the NG rounded up (6 of 20), the rest is the
    training set, and the lock is audited with its seed and counts."""
    v1 = frozen(ctx, tmp_path)
    drawn = set(ctx.db.ok_check_draws(CAL, "Top")[0]["sample_uuids"])
    keep = drawn | {s["uuid"] for s in ctx.samples(CAL) if s["path"] == ctx.db.reference(CAL)}  # the Golden board too
    for s in [s for s in ctx.samples(CAL, "OK") if s["uuid"] not in keep][:31]:
        ctx.set_label(s["uuid"], "UNSURE")  # out of the next version: 49 OK left, its drawn labels still checked
    v2 = ctx.freeze_dataset(CAL, "Top", "R4", "Acme")
    assert sum(i["label"] == "OK" for i in ctx.dataset_items(v2["uuid"])) == 49
    reasons = []
    for uid in (v2["uuid"], "no-such-version"):
        with pytest.raises(AoiError) as refused:
            ctx.lock_validation_set(uid, seed=1)
        reasons.append((refused.value.code, refused.value.params["name"], str(refused.value.params["reason"])))
    assert reasons == [
        ("AOI-TRN-022", v2["name"], "it holds 49 OK image(s), and a validation set holds 50"),
        ("AOI-TRN-022", "no-such-version", "the workspace holds no such dataset version"),
    ]
    assert ctx.validation_split(v2["uuid"]) is None and ctx.audit_entries(action="dataset.lock") == []
    split = ctx.lock_validation_set(v1["uuid"], seed=1)
    labels = {i["uuid"]: i["label"] for i in ctx.dataset_items(v1["uuid"])}
    counts = {part: [labels[u] for u in split[part]].count for part in ("train", "validation")}
    assert (counts["validation"]("OK"), counts["validation"]("NG")) == (50, 6)
    assert (counts["train"]("OK"), counts["train"]("NG")) == (30, 14)
    assert sorted(split["train"] + split["validation"]) == sorted(labels)  # each file in one part
    with pytest.raises(AoiError) as again:
        ctx.lock_validation_set(v1["uuid"], seed=2)
    assert str(again.value.params["reason"]) == "its validation set is locked already, and a version is split only once"
    assert ctx.validation_split(v1["uuid"]) == split
    [entry] = ctx.audit_entries(action="dataset.lock")
    assert (entry["object_uuid"], entry["user_uuid"]) == (v1["uuid"], ctx.user_uuid)
    counted = {"train_ok": 30, "train_ng": 14, "validation_ok": 50, "validation_ng": 6}
    assert entry["after"] == {"split_uuid": split["uuid"], "seed": 1, **counted, "validation_ng_types": {"Scratch": 6}}


def test_req_trn_006_split_is_reproducible(ctx: AppContext, tmp_path: Path) -> None:
    """The split is recorded with its seed, and the same files and seed split the same in any order; another seed
    draws another split. A later version is split around the earlier lock: every file locked before is locked again,
    whatever its seed. NG files spread over their defect types in proportion. The rows refuse to change or go."""
    v1 = frozen(ctx, tmp_path)
    rows = ctx.dataset_items(v1["uuid"])
    expected = datasets.split(rows, 1234, set(), set())
    split = ctx.lock_validation_set(v1["uuid"], seed=1234)
    assert split["validation"] == [i["uuid"] for i in expected["validation"]]
    assert split["train"] == [i["uuid"] for i in expected["train"]]
    assert (split["seed"], split["locked_by"], split["locked_at"][-6:]) == (1234, ctx.user_uuid, "+00:00")
    again = datasets.split(list(reversed(rows)), 1234, set(), set())
    assert [i["uuid"] for i in again["validation"]] == split["validation"]
    other = datasets.split(rows, 1235, set(), set())
    assert {i["uuid"] for i in other["validation"]} != set(split["validation"])
    v2 = ctx.freeze_dataset(CAL, "Top", "R4", "Acme")  # the same 100 files
    by_uuid = {i["uuid"]: i["sha256"] for i in rows}
    locked = {by_uuid[u] for u in split["validation"]}
    split2 = ctx.lock_validation_set(v2["uuid"], seed=99)
    sha2 = {i["uuid"]: i["sha256"] for i in ctx.dataset_items(v2["uuid"])}
    assert {sha2[u] for u in split2["validation"]} == locked  # already 50 OK and 6 NG, so no more
    many = items(80, {"Scratch": 10, "Short": 7, "Open": 3})
    ng = [i for i in datasets.split(many, 5, set(), set())["validation"] if i["label"] == "NG"]
    assert sorted(datasets.stratum(i) for i in ng) == ["Open", "Scratch", "Scratch", "Scratch", "Short", "Short"]
    for sql in ("UPDATE validation_splits SET seed=2", "UPDATE validation_split_items SET part='train'",
                "DELETE FROM validation_splits", "DELETE FROM validation_split_items"):  # fmt: skip
        with pytest.raises(sqlite3.DatabaseError, match="never (changed|unlocked|moved|deleted)"):
            ctx.db.execute(sql)


def test_req_trn_006_overlap_by_hash_refused(ctx: AppContext, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Training reads only a version's training set, never a locked validation image (REQ-TRN-006, REQ-TRN-007): CAL-1's
    version 1 trains and reads none of its 56 locked files. A training set holding a locked image by its SHA-256, a copy
    under another name in another board model, is refused with AOI-TRN-043 before any image is read, and nothing is
    saved; a version without the copy trains."""
    v1 = frozen(ctx, tmp_path)
    split = ctx.lock_validation_set(v1["uuid"], seed=7)
    files = {i["uuid"]: i for i in ctx.dataset_items(v1["uuid"])}
    read: list[str] = []
    real = ctx._load_image_sha256
    monkeypatch.setattr(ctx, "_load_image_sha256", lambda path: read.append(Path(path).name) or real(path))
    ctx.train(v1["uuid"], epochs=1, image_size=32)
    locked = {Path(files[u]["path"]).name for u in split["validation"]}
    assert len(locked) == 56 and len(set(read)) == 44 and not locked & set(read)  # its 30 OK and 14 NG, each read
    (folder := tmp_path / "copy").mkdir()
    copy = folder / "another_name.png"
    copy.write_bytes(plain(ctx, files[split["validation"][0]]["path"], CAL))  # its bytes as CAL-1's store holds them
    rng = np.random.default_rng(43)
    new = [folder / f"new_{i:02d}.png" for i in range(datasets.TRAIN_OK)]
    for name in new:
        save_image(name, rng.integers(0, 256, (32, 32, 3), dtype=np.uint8))
    ctx.import_samples("COPY", [str(n) for n in new], "OK")  # new_00: the reference
    ctx.import_samples("COPY", [str(copy)], "OK")
    read.clear()
    with pytest.raises(AoiError) as copied:
        ctx.train(trainable(ctx, "COPY"), epochs=1, image_size=32)
    assert (copied.value.code, copied.value.params["count"], read) == ("AOI-TRN-043", 1, [])
    assert ctx.models("COPY") == [] and len(ctx.audit_entries(action="model.train")) == 1  # CAL-1's alone
    [held] = [s for s in ctx.samples("COPY") if Path(s["path"]).name.startswith("another_name")]
    ctx.delete_sample(held["id"])
    ctx.train(trainable(ctx, "COPY"), epochs=1, image_size=32)
    assert len(ctx.models("COPY")) == 1
