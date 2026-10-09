"""REQ-TRN-002 and the data half of REQ-TRN-003 (stage S32): every image is labelled OK, NG or UNSURE with its defect
boxes, a relabel adds rows and keeps the old ones in history, and UNSURE images stay out of training and validation."""

from __future__ import annotations

import re
import sqlite3
from contextlib import closing
from pathlib import Path
from typing import Any

import numpy as np
import pytest
from pytestqt.qtbot import QtBot

from aoi import defects
from aoi.core import anomaly, labels
from aoi.core.labels import DefectBox
from aoi.core.services import AppContext
from aoi.data import migrate as mg
from aoi.data.db import Database
from aoi.errors import AoiError
from tests.test_req_done_in_v01 import BOARD, _window

TAIL = "-0000-4000-8000-000000000000"  # the end of a well-formed UUID4
UUID4 = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$")


class Stop(Exception):
    """Raised in place of the training itself, once the test has seen what it was given."""


def _rows(ctx: AppContext) -> tuple[int, int]:
    """How many label rows and box rows the workspace holds, superseded ones included."""
    count = [int(ctx.db.query(f"SELECT COUNT(*) n FROM {t}")[0]["n"]) for t in ("labels", "defect_boxes")]
    return count[0], count[1]


def test_req_trn_002_unsure_excluded(qtbot: QtBot, trained_ctx: AppContext, monkeypatch: pytest.MonkeyPatch) -> None:
    """An image labelled UNSURE is in no list training or validation reads, nor in the Home and Training counts; it is
    listed for the customer's quality engineer with who labelled it and when. Training loads only OK and NG images, and
    the OK images it holds back to calibrate (its validation part) come from those."""
    ctx = trained_ctx
    ok, ng = ctx.samples(BOARD, "OK"), ctx.samples(BOARD, "NG")
    unsure = [ok[-1], ng[-1]]  # not the reference, which is the first OK sample
    for s in unsure:
        assert UUID4.match(ctx.set_label(s["uuid"], "UNSURE"))
    assert [s["uuid"] for s in ctx.samples(BOARD, "OK")] == [s["uuid"] for s in ok[:-1]]
    assert [s["uuid"] for s in ctx.samples(BOARD, "NG")] == [s["uuid"] for s in ng[:-1]]
    status = ctx.board_status(BOARD)
    assert (status.ok_samples, status.ng_samples) == (len(ok) - 1, len(ng) - 1)
    listed = ctx.unsure_samples(BOARD)
    assert [s["uuid"] for s in listed] == [s["uuid"] for s in unsure] and all(s["label"] == "UNSURE" for s in listed)
    assert {(s["labelled_by"], s["labelled_by_name"]) for s in listed} == {(ctx.db.user_uuid("engineer"), "engineer")}
    assert all(s["labelled_at"].endswith("+00:00") and Path(s["path"]).is_absolute() for s in listed)
    loaded: list[str] = []
    seen: dict[str, int] = {}
    real_load = ctx.load_image

    def load(path: str | Path) -> np.ndarray:
        loaded.append(str(path))
        return real_load(path)

    def train(ok_images: list[np.ndarray], ng_images: list[np.ndarray], *a: Any, **k: Any) -> None:
        seen.update(ok=len(ok_images), ng=len(ng_images))
        raise Stop

    monkeypatch.setattr(ctx, "load_image", load)
    monkeypatch.setattr(anomaly, "train", train)
    with pytest.raises(Stop):
        ctx.train(BOARD, epochs=1, image_size=32)
    assert seen == {"ok": len(ok) - 1, "ng": len(ng) - 1}
    assert not {s["path"] for s in unsure} & set(loaded)
    win = _window(qtbot, ctx)
    win.navigate("Training")
    page = win.pages["Training"]
    assert page.counts.text().startswith(f"{len(ok) - 1} OK · {len(ng) - 1} NG · ")  # UNSURE counted as neither


def test_req_trn_003_relabel_keeps_history(trained_ctx: AppContext) -> None:
    """A relabel, a box change and the Training page's Mark OK each add a label row and mark the one before superseded
    by it; the boxes of a label stay with it in history; nothing is deleted or changed in place, and each write is
    audited with the label before and after."""
    ctx = trained_ctx
    sample = ctx.samples(BOARD, "OK")[-1]
    first = ctx.label_history(sample["uuid"])
    assert [(r["label"], r["superseded_by"]) for r in first] == [("OK", None)]  # the import's own row
    assert first[0]["labelled_by"] == ctx.db.user_uuid("engineer")
    a = DefectBox(10, 12, 20, 8, "Solder Bridge")
    b = DefectBox(30, 5, 6, 6, "Scratch")
    rows = _rows(ctx)
    ng = ctx.set_label(sample["uuid"], "NG", "Solder Bridge", [a])
    ctx.set_user("admin")
    moved = ctx.set_boxes(sample["uuid"], [DefectBox(11, 12, 20, 8, "Solder Bridge"), b])
    ctx.set_user("engineer")
    ctx.update_sample(sample["id"], "OK", None)
    history = ctx.label_history(sample["uuid"])  # newest first
    assert [r["label"] for r in history] == ["OK", "NG", "NG", "OK"]
    assert [r["superseded_by"] for r in history] == [None, history[0]["uuid"], moved, ng]
    assert [r["uuid"] for r in history[1:3]] == [moved, ng] and history[3]["uuid"] == first[0]["uuid"]
    assert [r["labelled_by_name"] for r in history[:3]] == ["engineer", "admin", "engineer"]
    assert [[(x["x"], x["dct_type"]) for x in r["boxes"]] for r in history] == [
        [],
        [(11, "Solder Bridge"), (30, "Scratch")],
        [(10, "Solder Bridge")],
        [],
    ]
    assert all(x["superseded_by"] == r["superseded_by"] for r in history for x in r["boxes"])
    assert ctx.boxes(sample["uuid"]) == [] and len(ctx.box_history(sample["uuid"])) == 3
    assert _rows(ctx) == (rows[0] + 3, rows[1] + 3)  # rows added, none removed
    current = next(s for s in ctx.samples(BOARD) if s["uuid"] == sample["uuid"])
    assert (current["label"], current["label_uuid"]) == ("OK", history[0]["uuid"])
    sets = ctx.audit_entries(object_type="sample", object_uuid=sample["uuid"])
    assert [e["action"] for e in sets] == ["sample.update", "label.set", "label.set"]
    assert sets[1]["before"]["label_uuid"] == ng and sets[1]["after"]["label_uuid"] == moved
    assert sets[1]["after"]["boxes"][1] == {"x": 30, "y": 5, "w": 6, "h": 6, "dct_type": "Scratch", "severity": "Minor"}
    with pytest.raises(sqlite3.DatabaseError, match="never changed"):
        ctx.db.execute("UPDATE labels SET label='NG' WHERE uuid=?", (history[0]["uuid"],))
    with pytest.raises(sqlite3.DatabaseError, match="never changed"):
        ctx.db.execute("UPDATE defect_boxes SET superseded_by=NULL WHERE label_uuid=?", (ng,))
    for table in ("labels", "defect_boxes"):
        with pytest.raises(sqlite3.DatabaseError, match="never deleted"):
            ctx.db.execute(f"DELETE FROM {table} WHERE sample_uuid=?", (sample["uuid"],))
    assert _rows(ctx) == (rows[0] + 3, rows[1] + 3)


def test_req_trn_003_severity_matches_dct(trained_ctx: AppContext, monkeypatch: pytest.MonkeyPatch) -> None:
    """Each box stores its position and size, one of the 33 defect types and the severity aoi/defects.py gives that
    type; a box outside the image or not in whole pixels, a type that is not one of the 33 (Anomaly included), and a box
    or defect type on an OK or UNSURE image are refused with a code and nothing is written. An NG image whose own type
    is not one of the 33 (an older label's Anomaly) is refused boxes with a message naming that type and what to do.
    The image's size is read for the boxes before the database is locked, so no file is read while other writes wait."""
    ctx = trained_ctx
    sample = ctx.samples(BOARD, "NG")[-1]
    size = ctx.load_image(sample["path"]).shape  # the image is 640 x 480
    boxes = [DefectBox(i, i, 4, 4, t.name) for i, t in enumerate(defects.DEFECT_TYPES)]
    depth, real = [], labels.image_size
    monkeypatch.setattr(labels, "image_size", lambda path: depth.append(ctx.db._tx_depth) or real(path))
    ctx.set_boxes(sample["uuid"], boxes)
    assert depth == [0]
    stored = ctx.boxes(sample["uuid"])
    assert len(stored) == 33 == len(defects.names())
    assert [(r["x"], r["y"], r["w"], r["h"], r["dct_type"]) for r in stored] == [
        (b.x, b.y, b.w, b.h, b.dct_type) for b in boxes
    ]
    assert [r["severity"] for r in stored] == [defects.BY_NAME[b.dct_type].severity for b in boxes]
    assert {r["severity"] for r in stored} == {"Critical", "Major", "Minor"}
    edge = DefectBox(size[1] - 5, size[0] - 5, 5, 5, "Scratch")
    ctx.set_boxes(sample["uuid"], [edge])  # touching the bottom right corner is inside
    rows, entries = _rows(ctx), ctx.audit_entries()
    refusals: list[tuple[str, list[DefectBox], str]] = [
        ("NG", [DefectBox(size[1] - 5, 0, 6, 5, "Scratch")], "AOI-TRN-031"),
        ("NG", [DefectBox(0, size[0] - 4, 4, 5, "Scratch")], "AOI-TRN-031"),
        ("NG", [DefectBox(-1, 0, 4, 4, "Scratch")], "AOI-TRN-031"),
        ("NG", [DefectBox(0, 0, 0, 4, "Scratch")], "AOI-TRN-031"),
        ("NG", [DefectBox(0, 0, 4, 4, "Anomaly")], "AOI-TRN-030"),
        ("NG", [DefectBox(0, 0, 4, 4, "Smudge")], "AOI-TRN-030"),
        ("NG", [DefectBox(0.5, 0, 4, 4, "Scratch")], "AOI-TRN-030"),
        ("NG", [DefectBox(0, True, 4, 4, "Scratch")], "AOI-TRN-030"),
        ("NG", [DefectBox(0, 0, "4", 4, "Scratch")], "AOI-TRN-030"),
        ("OK", [edge], "AOI-TRN-030"),
        ("UNSURE", [edge], "AOI-TRN-030"),
        ("Maybe", [], "AOI-TRN-030"),
    ]
    for label, given, code in refusals:
        with pytest.raises(AoiError) as refused:
            ctx.set_label(sample["uuid"], label, None, given)
        assert refused.value.code == code, (label, given)
    with pytest.raises(AoiError) as typed:
        ctx.set_label(sample["uuid"], "OK", "Scratch")
    assert typed.value.code == "AOI-TRN-030" and "only an NG image takes" in typed.value.what
    with pytest.raises(AoiError) as outside:
        ctx.set_boxes(sample["uuid"], [edge, DefectBox(size[1] - 5, 0, 6, 5, "Scratch")])
    assert outside.value.code == "AOI-TRN-031" and f"{size[1]} × {size[0]} px" in outside.value.what
    with pytest.raises(AoiError) as gone:
        ctx.set_label("00000000-0000-4000-8000-000000000000", "OK")
    assert gone.value.code == "AOI-TRN-032"
    assert (_rows(ctx), ctx.audit_entries()) == (rows, entries)
    ctx.db.add_label(sample["uuid"], "NG", "Anomaly", [], None)  # as a folder named anomaly once imported it
    with pytest.raises(AoiError) as old:
        ctx.set_boxes(sample["uuid"], [edge])
    assert old.value.code == "AOI-TRN-030" and re.search("defect type, Anomaly, is not .* Mark NG", old.value.what)


def test_req_trn_002_migration_carries_every_label_over(tmp_path: Path) -> None:
    """A workspace from before the labels table keeps every sample's label: the migration writes one current label row
    per sample, with its label and defect type, at the time the sample was added and with no labeller recorded (none
    was); samples.label stays as the import wrote it, and a relabel afterwards adds a row as for any other label."""
    path = tmp_path / "aoi.sqlite"
    files = mg.load_migrations()
    before = next(i for i, m in enumerate(files) if m.name == "labels_and_boxes")
    with closing(sqlite3.connect(path)) as old:
        mg.migrate(old, files[:before])
        for uid, label, dtype in ((f"{'a' * 8}{TAIL}", "OK", None), (f"{'b' * 8}{TAIL}", "NG", "Tombstone")):
            old.execute(
                "INSERT INTO samples(uuid, board_model, path, label, defect_type, side, added_at)"
                " VALUES(?,?,?,?,?,?,?)",
                (uid, "OLD", f"images/OLD/{label}/{uid}.png", label, dtype, "Top", "2026-09-30T01:02:03+00:00"),
            )
        old.commit()
    db = Database(path)
    carried = db.query("SELECT * FROM labels ORDER BY id")
    assert [(r["label"], r["defect_type"], r["labelled_by"], r["at_utc"], r["superseded_by"]) for r in carried] == [
        ("OK", None, None, "2026-09-30T01:02:03+00:00", None),
        ("NG", "Tombstone", None, "2026-09-30T01:02:03+00:00", None),
    ]
    assert all(UUID4.match(r["uuid"]) for r in carried) and db.query("SELECT * FROM defect_boxes") == []
    assert [(s["label"], s["defect_type"], s["label_uuid"]) for s in db.samples("OLD")] == [
        (r["label"], r["defect_type"], r["uuid"]) for r in carried
    ]
    db.add_label(carried[1]["sample_uuid"], "UNSURE", None, [], None)
    assert [s["label"] for s in db.samples("OLD")] == ["OK", "UNSURE"]
    assert db.query("SELECT label FROM samples ORDER BY id") == [{"label": "OK"}, {"label": "NG"}]
    db.close()


def test_req_trn_002_every_sample_has_a_current_label(ctx: AppContext, synthetic_dataset: Path) -> None:
    """An import and Database.add_sample, which every import goes through, store each sample with its current label
    row; every sample read joins that row, so a sample stored without one would leave every list (S31 keeps this)."""
    ctx.import_samples("B", [str(synthetic_dataset / "golden.png")], "OK")
    ctx.db.add_sample("B", "images/B/board.png", "NG", "Scratch")
    orphans = "SELECT s.uuid FROM samples s LEFT JOIN labels l ON l.sample_uuid = s.uuid AND l.superseded_by IS NULL"
    assert ctx.db.query(f"{orphans} WHERE l.id IS NULL") == [] and len(ctx.samples("B")) == 2


def test_req_trn_002_mark_skips_rows_labelled_so(ctx: AppContext) -> None:
    """Mark OK on an OK image, or Mark NG with its own type on an NG image, adds no label row and no audit entry when
    the label has a labeller, so the labeller and any check of it stay; another type is a relabel. A label carried
    over with no labeller is labelled again, with the user acting as its labeller, so it can be checked."""
    me = ctx.user_uuid
    ok = ctx.db.add_sample("B", "images/B/1.png", "OK", labelled_by=me)
    ng = ctx.db.add_sample("B", "images/B/2.png", "NG", "Scratch", labelled_by=me)
    carried = ctx.db.add_sample("B", "images/B/3.png", "OK")  # as migration 0014 carries a label over: no labeller
    before, entries = ctx.samples("B"), ctx.audit_entries()
    ctx.update_sample(ok, "OK", None)
    ctx.update_sample(ng, "NG", "Scratch")
    assert (ctx.samples("B"), ctx.audit_entries()) == (before, entries)
    ctx.update_sample(ng, "NG", "Tombstone")
    ctx.update_sample(carried, "OK", None)
    assert len(ctx.db.label_history(before[1]["uuid"])) == 2
    assert [r["labelled_by"] for r in ctx.db.label_history(before[2]["uuid"])] == [me, None]
