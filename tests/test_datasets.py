"""REQ-TRN-005 and the freeze gate of REQ-TRN-004 (stage S35): a dataset version freezes as DS-<MODEL>-<REV>-<VIEW>-v<N>
with a SHA-256 manifest of every file once its labels are checked and two labellers agree; a later change goes into a
new version, and the frozen one's rows and manifest never change."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path

import pytest

from aoi.core.labels import DefectBox
from aoi.core.services import AppContext
from aoi.errors import AoiError
from tests.conftest import distinct_copies
from tests.test_labeller_agreement import CAL, calibration_workspace, label_blind
from tests.test_labels import UUID4


def ready(ctx: AppContext, folder: Path) -> tuple[list[dict[str, object]], str]:
    """CAL-1's 100 images, each NG one boxed, every NG and drawn OK label checked by kim, and a calibration set."""
    samples = calibration_workspace(ctx, folder)
    for s in ctx.samples(CAL, "NG"):
        ctx.set_boxes(s["uuid"], [DefectBox(1, 2, 8, 6, "Scratch")])
    ctx.set_user("kim")
    draw = ctx.draw_ok_checks(CAL, "Top", seed=5) or {}
    for uid in [s["uuid"] for s in ctx.samples(CAL, "NG")] + draw["sample_uuids"]:
        ctx.check_label(uid)
    cal = ctx.make_calibration_set(CAL, [str(s["uuid"]) for s in samples])
    ctx.set_user("engineer")
    return ctx.samples(CAL), cal


def agree(ctx: AppContext, cal: str, samples: list[dict[str, object]]) -> None:
    kim, lee = (label_blind(ctx, user, cal, samples, 0, 0) for user in ("kim", "lee"))
    assert ctx.run_agreement_check(cal, kim, lee)["agreed"]


def test_req_trn_005_name_format(ctx: AppContext, tmp_path: Path) -> None:
    """DS-<board model without hyphens>-<revision>-<VIEW>-v<N>, N per board model and view; the manifest lists each
    OK and NG file's path, SHA-256, label, boxes, labeller and checker, and its hash is stored; a refusal makes none."""
    samples, cal = ready(ctx, tmp_path / "boards")
    refusals = [("R-3", "Top", "Acme", ["own"]), ("R3", "Top", " ", ["own"]), ("R3", "Top", "Acme", ["resale"])]
    refusals += [("R3", "Top", "Acme", ["own"]), ("R3", "Bottom", "Acme", ["own"])]  # no agreed check; no image
    codes: list[tuple[str, object]] = []
    for revision, view, customer, uses in refusals:
        if view == "Bottom":
            agree(ctx, cal, samples)
        with pytest.raises(AoiError) as refused:
            ctx.freeze_dataset(CAL, view, revision, customer, uses)
        codes.append((refused.value.code, refused.value.params["name"]))
    top = "DS-CAL1-R3-TOP-v1"
    assert codes == [("AOI-TRN-027", "DS-CAL1-R-3-TOP-v1"), ("AOI-TRN-024", top), ("AOI-TRN-027", top),
                     ("AOI-TRN-027", top), ("AOI-TRN-027", "DS-CAL1-R3-BOTTOM-v1")]  # fmt: skip
    assert ctx.datasets(CAL) == [] == ctx.audit_entries(action="dataset.freeze")
    assert not (ctx.settings.root / "datasets").exists()
    v1, v2 = (ctx.freeze_dataset(CAL, "Top", rev, "Acme") for rev in ("R3", "R4"))
    assert [v1["name"], v2["name"], ctx.datasets(CAL)] == ["DS-CAL1-R3-TOP-v1", "DS-CAL1-R4-TOP-v2", [v2, v1]]
    agreed = ctx.agreement_checks(CAL)[0]["uuid"]
    assert (v1["customer"], v1["allowed_uses"], v1["agreement_check_uuid"]) == ("Acme", ["own"], agreed)
    assert UUID4.match(v1["uuid"]) and str(v1["frozen_at"]).endswith("+00:00")
    assert (v1["frozen_by"], v1["manifest_path"]) == (ctx.user_uuid, "datasets/DS-CAL1-R3-TOP-v1/manifest.json")
    manifest = json.loads(data := (ctx.settings.root / v1["manifest_path"]).read_bytes())
    assert hashlib.sha256(data).hexdigest() == v1["manifest_sha256"] and manifest["agreement_check"]["uuid"] == agreed
    head = ("uuid", "name", "board_model", "revision", "view", "version", "customer")
    assert [manifest[k] for k in head] == [v1["uuid"], v1["name"], CAL, "R3", "Top", 1, "Acme"]
    rows = ctx.dataset_items(v1["uuid"])
    assert manifest["files"] == [{k: v for k, v in i.items() if k not in ("id", "uuid", "dataset_uuid")} for i in rows]
    box = [{"x": 1, "y": 2, "w": 8, "h": 6, "dct_type": "Scratch", "severity": "Minor"}]
    keys = ("label_uuid", "label", "defect_type", "labelled_by", "checked_by")
    for f, s in zip(manifest["files"], samples, strict=True):  # all 100
        path = Path(str(s["path"]))
        assert f["path"] == path.relative_to(ctx.settings.root).as_posix() and f["sample_uuid"] == s["uuid"]
        assert f["sha256"] == hashlib.sha256(path.read_bytes()).hexdigest()
        assert [f[k] for k in keys] + [f["boxes"]] == [s[k] for k in keys] + [box if s["label"] == "NG" else []]
    entry = ctx.audit_entries(action="dataset.freeze")[-1]
    assert (entry["object_uuid"], entry["after"]["name"], entry["after"]["files"]) == (v1["uuid"], v1["name"], 100)


def test_req_trn_005_change_makes_new_version(ctx: AppContext, tmp_path: Path) -> None:
    """A relabel and a new file each go into the next version once its labels are ready again; the frozen version's
    record, files and manifest stay as they were, and the database refuses to change or delete them."""
    samples, cal = ready(ctx, tmp_path / "boards")
    agree(ctx, cal, samples)
    v1 = ctx.freeze_dataset(CAL, "Top", "R3", "Acme")
    items, data = ctx.dataset_items(v1["uuid"]), (ctx.settings.root / v1["manifest_path"]).read_bytes()
    ctx.set_boxes(ng := ctx.samples(CAL, "NG")[0]["uuid"], [DefectBox(3, 3, 5, 5, "Solder Bridge")])  # a label change
    with pytest.raises(AoiError) as unchecked:
        ctx.freeze_dataset(CAL, "Top", "R3", "Acme")
    assert (unchecked.value.code, unchecked.value.params["count"]) == ("AOI-TRN-020", 1)
    ctx.set_user("kim")
    ctx.check_label(ng)
    ctx.set_user("engineer")
    v2 = ctx.freeze_dataset(CAL, "Top", "R3", "Acme")
    old, new = ({i["sample_uuid"]: i for i in ctx.dataset_items(v["uuid"])}[ng] for v in (v1, v2))
    assert (old["boxes"][0]["dct_type"], new["boxes"][0]["dct_type"]) == ("Scratch", "Solder Bridge")
    assert new["label_uuid"] != old["label_uuid"] and v2["name"] == "DS-CAL1-R3-TOP-v2"
    ctx.import_samples(CAL, [str(distinct_copies(Path(str(samples[0]["path"])), tmp_path / "added", 1)[0])], "OK")
    with pytest.raises(AoiError) as short:  # a file added, new bytes (Q31): 81 OK, so 9 to check
        ctx.freeze_dataset(CAL, "Top", "R3", "Acme")
    assert (short.value.code, short.value.params["checked"], short.value.params["needed"]) == ("AOI-TRN-021", 8, 9)
    ctx.set_user("kim")
    ctx.check_label((ctx.draw_ok_checks(CAL, "Top", seed=6) or {})["sample_uuids"][0])
    ctx.set_user("engineer")
    v3 = ctx.freeze_dataset(CAL, "Top", "R3", "Acme")
    assert [len(ctx.dataset_items(v["uuid"])) for v in (v1, v2, v3)] == [100, 100, 101]
    assert ctx.datasets(CAL)[2] == v1 and ctx.dataset_items(v1["uuid"]) == items
    assert (ctx.settings.root / v1["manifest_path"]).read_bytes() == data
    changes = ["UPDATE datasets SET customer='B'", "UPDATE dataset_items SET label='NG'", "DELETE FROM datasets"]
    for sql in [*changes, "DELETE FROM dataset_items"]:
        with pytest.raises(sqlite3.DatabaseError, match="never (changed|deleted)"):
            ctx.db.execute(sql)


def test_req_trn_005_verify_detects_tampered_file(ctx: AppContext, tmp_path: Path) -> None:
    """verify_dataset re-hashes the manifest and each file against the SHA-256 stored at the freeze, writing nothing:
    all match after it, and after a sample the version names is removed, whose file the app keeps, with no foreign key
    broken; a changed byte, a removed file and a changed or removed manifest are reported by path; a version the
    workspace does not hold is AOI-TRN-028."""
    samples, cal = ready(ctx, tmp_path / "boards")
    agree(ctx, cal, samples)
    v1 = ctx.freeze_dataset(CAL, "Top", "R3", "Acme")
    paths, root = [i["path"] for i in ctx.dataset_items(v1["uuid"])], ctx.settings.root
    ctx.delete_sample(ctx.samples(CAL, "NG")[0]["id"])  # its record goes; the file the version names stays
    assert ctx.datasets(CAL) == [v1] and ctx.db.query("PRAGMA foreign_key_check") == []
    assert ctx.verify_dataset(v1["uuid"]) == {
        "manifest": "same",
        "files": 100,
        "matched": paths,
        "changed": [],
        "missing": [],
    }
    with open(root / paths[3], "ab") as f:
        f.write(b"\0")  # one byte added, as a program that rewrites the image would
    (root / paths[7]).unlink()
    manifest, entries = root / v1["manifest_path"], ctx.audit_entries()
    manifest.write_bytes(manifest.read_bytes().replace(b'"label": "NG"', b'"label": "OK"', 1))
    tampered = ctx.verify_dataset(v1["uuid"])
    assert [tampered[k] for k in ("manifest", "files", "changed", "missing")] == [
        "changed",
        100,
        [paths[3]],
        [paths[7]],
    ]
    assert tampered["matched"] == [p for p in paths if p not in (paths[3], paths[7])]
    manifest.unlink()
    assert ctx.verify_dataset(v1["uuid"])["manifest"] == "missing" and ctx.audit_entries() == entries
    with pytest.raises(AoiError) as unknown:
        ctx.verify_dataset("a-version-never-frozen")
    assert unknown.value.code == "AOI-TRN-028"
