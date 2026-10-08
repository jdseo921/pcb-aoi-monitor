"""REQ-TRN-002 and the data half of REQ-TRN-003 (stage S32): every image's label is kept with its history, and a
workspace from before the history keeps every label it had."""

from __future__ import annotations

import re
import sqlite3
from contextlib import closing
from pathlib import Path

from aoi.core.services import AppContext
from aoi.data import migrate as mg
from aoi.data.db import Database

TAIL = "-0000-4000-8000-000000000000"  # the end of a well-formed UUID4
UUID4 = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$")


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
