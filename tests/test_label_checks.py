"""REQ-TRN-004 (stage S34): a second user checks every NG label and a seeded random 10 % of the OK labels of a board
model and view, and only then are its labels ready to freeze. Under ADR 0002, until sign-in ships at 1.0, the second
user is a second picked name."""

from __future__ import annotations

import random
import sqlite3
from pathlib import Path

import pytest

from aoi.core.labels import DefectBox
from aoi.core.services import AppContext
from aoi.errors import AoiError
from tests.test_labels import UUID4
from tests.test_req_done_in_v01 import BOARD

BOX = [DefectBox(0, 0, 4, 4, "Scratch")]


def _checks(ctx: AppContext) -> int:
    return int(ctx.db.query("SELECT COUNT(*) n FROM label_checks")[0]["n"])


def _current(ctx: AppContext, uid: str) -> dict[str, object]:
    return next(s for s in ctx.samples(BOARD) if s["uuid"] == uid)


def _refused(ctx: AppContext, uid: str, code: str) -> None:
    """check_label of `uid` is refused with `code` and writes no check and no audit entry."""
    rows, entries = _checks(ctx), ctx.audit_entries()
    with pytest.raises(AoiError) as refused:
        ctx.check_label(uid)
    assert refused.value.code == code and (_checks(ctx), ctx.audit_entries()) == (rows, entries)


def test_req_trn_004_same_user_cannot_check(trained_ctx: AppContext) -> None:
    """The user who labelled an image cannot check its label; another Engineer or Admin can, once, and the check names
    the label row, so a relabel needs a check of its own. A label with no labeller recorded, an UNSURE label and an NG
    image with no defect box cannot be checked. A refusal writes nothing, and a check is never changed or deleted."""
    ctx = trained_ctx  # the import labelled every sample as the engineer
    ok, ng = ctx.samples(BOARD, "OK"), ctx.samples(BOARD, "NG")
    sample, unsure, unknown = ok[-1], ok[1]["uuid"], ok[2]["uuid"]
    admin = ctx.db.user_uuid("admin")
    _refused(ctx, sample["uuid"], "AOI-TRN-033")  # the engineer labelled it
    ctx.set_user("admin")
    check = ctx.check_label(sample["uuid"])
    checked = _current(ctx, sample["uuid"])
    assert UUID4.match(check) and (checked["checked_by"], checked["checked_by_name"]) == (admin, "admin")
    assert str(checked["checked_at"]).endswith("+00:00") and checked["label_uuid"] == sample["label_uuid"]
    (entry,) = ctx.audit_entries(action="label.check")
    assert (entry["object_uuid"], entry["user_uuid"]) == (sample["uuid"], admin)
    assert entry["after"] == {"check_uuid": check, "label_uuid": sample["label_uuid"], "label": "OK"}
    _refused(ctx, sample["uuid"], "AOI-TRN-034")  # checked already
    relabel = ctx.set_label(sample["uuid"], "OK")  # the admin labels it again: a new label row, not checked
    assert _current(ctx, sample["uuid"])["checked_by"] is None
    _refused(ctx, sample["uuid"], "AOI-TRN-033")  # the admin's own label now
    ctx.set_label(unsure, "UNSURE")
    ctx.db.add_label(unknown, "OK", None, [], None)  # no labeller, as migration 0014 carries a label over
    for uid in (unsure, unknown, ng[-1]["uuid"]):  # UNSURE; no labeller; an NG image with no defect box
        _refused(ctx, uid, "AOI-TRN-034")
    ctx.set_user("engineer")
    ctx.check_label(sample["uuid"])  # the engineer checks the admin's relabel
    ctx.set_boxes(ng[-1]["uuid"], BOX)
    ctx.set_user("admin")
    ctx.check_label(ng[-1]["uuid"])
    assert _current(ctx, sample["uuid"])["label_uuid"] == relabel and _checks(ctx) == 3
    with pytest.raises(sqlite3.DatabaseError, match="never changed"):
        ctx.db.execute("UPDATE label_checks SET checked_by=?", (admin,))
    with pytest.raises(sqlite3.DatabaseError, match="never deleted"):
        ctx.db.execute("DELETE FROM label_checks")


def test_req_trn_004_not_ready_until_checked(trained_ctx: AppContext, synthetic_dataset: Path) -> None:
    """labels_ready_to_freeze is False until every NG label of the board model and view and drawn OK labels numbering
    at least 10 % of its OK labels, rounded up, are checked by a second user. The OK labels are drawn at random with a
    recorded seed; a later draw adds to the earlier ones; an OK label checked but not drawn does not count; a relabel,
    a new NG image or more OK images make it False again until they are checked or drawn and checked; UNSURE images and
    another view do not count. A board model or view with no OK or NG label is not ready, and a view that is not Top,
    Side or Bottom is refused (AOI-TRN-038) with nothing written."""
    ctx = trained_ctx
    ok, ng = ctx.samples(BOARD, "OK"), ctx.samples(BOARD, "NG")
    status = ctx.label_check_status(BOARD, "Top")
    assert (status["ok"], status["ng"], status["ok_needed"]) == (len(ok), len(ng), 2) == (20, 3, 2)
    assert status["ng_unchecked"] == [s["uuid"] for s in ng] and not ctx.labels_ready_to_freeze(BOARD, "Top")
    for s in ng:
        ctx.set_boxes(s["uuid"], BOX)
    ctx.set_user("admin")
    for s in ng:
        ctx.check_label(s["uuid"])
    assert not ctx.label_check_status(BOARD, "Top")["ng_unchecked"] and not ctx.labels_ready_to_freeze(BOARD, "Top")
    draw = ctx.draw_ok_checks(BOARD, "Top", seed=7)
    assert draw is not None and (draw["seed"], draw["ok_labels"]) == (7, 20)
    assert draw["sample_uuids"] == random.Random(7).sample([s["uuid"] for s in ok], 2)  # the seed and this pool
    (entry,) = ctx.audit_entries(action="label.draw")
    assert entry["after"]["seed"] == 7 and entry["after"]["sample_uuids"] == draw["sample_uuids"]
    assert ctx.draw_ok_checks(BOARD, "Top") is None  # enough drawn: nothing is written
    ctx.set_user("engineer")
    other = next(s for s in ok[1:] if s["uuid"] not in draw["sample_uuids"])
    ctx.set_label(other["uuid"], "OK")  # labelled by the engineer, checked below by the admin, but not drawn
    ctx.set_user("admin")
    for uid in (other["uuid"], draw["sample_uuids"][0]):
        ctx.check_label(uid)
    assert not ctx.labels_ready_to_freeze(BOARD, "Top")
    ctx.check_label(draw["sample_uuids"][1])
    assert ctx.labels_ready_to_freeze(BOARD, "Top")
    ctx.set_user("engineer")
    ctx.set_label(draw["sample_uuids"][0], "OK")  # a relabel needs a new check
    assert not ctx.labels_ready_to_freeze(BOARD, "Top")
    ctx.set_user("admin")
    ctx.check_label(draw["sample_uuids"][0])
    ctx.set_user("engineer")
    ctx.set_label(ng[0]["uuid"], "UNSURE")  # out of the count
    ctx.import_samples(BOARD, [str(synthetic_dataset / "golden.png")], "NG", "Scratch", "Bottom")  # another view
    assert ctx.labels_ready_to_freeze(BOARD, "Top") and not ctx.labels_ready_to_freeze(BOARD, "Bottom")
    ctx.import_samples(BOARD, [str(synthetic_dataset / "test" / "ok" / "ok_000.png")], "OK")  # 21 OK: 3 to check
    assert ctx.label_check_status(BOARD, "Top")["ok_needed"] == 3 and not ctx.labels_ready_to_freeze(BOARD, "Top")
    more = ctx.draw_ok_checks(BOARD, "Top", seed=8)
    assert more is not None and len(more["sample_uuids"]) == 1 and more["sample_uuids"][0] not in draw["sample_uuids"]
    ctx.set_user("admin")
    ctx.check_label(more["sample_uuids"][0])
    assert ctx.labels_ready_to_freeze(BOARD, "Top")
    assert set(ctx.label_check_status(BOARD, "Top")["ok_drawn"]) == {*draw["sample_uuids"], *more["sample_uuids"]}
    assert not ctx.labels_ready_to_freeze(BOARD, "Side") and not ctx.labels_ready_to_freeze("NO-SUCH-BOARD", "Top")
    entries = ctx.audit_entries()
    for view in ("top", "../Top", ""):
        for call in (ctx.label_check_status, ctx.labels_ready_to_freeze, ctx.draw_ok_checks):
            with pytest.raises(AoiError) as refused:
                call(BOARD, view)
            assert refused.value.code == "AOI-TRN-038" and "Top, Side or Bottom" in refused.value.action
    assert ctx.audit_entries() == entries
