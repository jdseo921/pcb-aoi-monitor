"""A board reviewed as a false call goes to Training as an OK sample in one step (REQ-TRN-020, ADR 0013): Logs &
Export's Add to Training as OK, an Engineer's and an Admin's. The records are written through the data layer with
made-up verdicts over a noise image, so nothing here is an accuracy."""

from __future__ import annotations

from pathlib import Path
from typing import cast

import cv2
import numpy as np
import pytest
from PySide6.QtWidgets import QInputDialog
from pytestqt.qtbot import QtBot

from aoi.core.services import DEFECT, FALSE_CALL, AppContext
from aoi.errors import AoiError
from aoi.ui.main_window import MainWindow
from aoi.ui.pages.logs import LogsPage
from tests.conftest import listed
from tests.test_no_freeze import BUDGET_S, assert_off_ui_thread, gap_meter, heavy_calls
from tools.trainable import in_store


def _board(tmp_path: Path, name: str, seed: int) -> str:
    """A 320 × 240 noise image, a different one for each seed, so no two are the same sample."""
    img = np.random.default_rng(seed).integers(0, 256, (240, 320, 3), dtype=np.uint8)
    path = tmp_path / f"{name}.png"
    cv2.imwrite(str(path), img)
    return str(path)


def _record(ctx: AppContext, image: str | None, view: str | None = "Bottom", board: str = "B") -> int:
    rec = {"board_model": board, "result": "NG", "operator": "kim", "image_path": image, "model_version": "v1.0",
           "recipe_rev": 1, "view": view, "score": 0.9}  # fmt: skip
    return ctx.db.add_inspection(rec, [])


def test_req_trn_020_a_false_call_is_added_as_an_ok_sample_in_its_view_once(ctx: AppContext, tmp_path: Path) -> None:
    """The record's stored board image becomes an OK sample of its board model in the record's view, and the import's
    audit entry names the record; a second call adds nothing and names the sample that holds the image."""
    ctx.ensure_board_model("B")
    iid = _record(ctx, _board(tmp_path, "ng", 1))
    ctx.review_result(iid, FALSE_CALL, "Dust on the board")
    out = ctx.add_false_call_sample(iid)
    (sample,) = ctx.samples("B")
    assert out == {"added": 1, "sample": sample["uuid"], "label": "OK", "board_model": "B", "view": "Bottom"}
    assert (sample["label"], sample["side"]) == ("OK", "Bottom")
    assert Path(sample["path"]).read_bytes() == (tmp_path / "ng.png").read_bytes()  # the very board, copied
    entry = ctx.audit_entries(action="sample.import")[0]
    assert entry["after"]["from_inspection"] == ctx.db.inspection(iid)["uuid"]
    assert entry["after"]["added"] == 1 and entry["role"] == "Engineer"

    again = ctx.add_false_call_sample(iid)
    assert again == out | {"added": 0} and len(ctx.samples("B")) == 1


def test_req_trn_020_a_record_not_reviewed_as_a_false_call_is_refused_and_nothing_changes(
    ctx: AppContext, tmp_path: Path
) -> None:
    """AOI-TRN-050 for an unknown record, a record reviewed as a real defect, one not reviewed, and one with no stored
    image; no sample and no audit entry is written. A record from before views were stored is a top view (S35)."""
    ctx.ensure_board_model("B")
    real, open_ = (_record(ctx, _board(tmp_path, name, seed)) for name, seed in (("real", 2), ("open", 3)))
    no_image = _record(ctx, None)
    ctx.review_result(real, DEFECT)
    ctx.review_result(no_image, FALSE_CALL, "Dust on the board")
    before = ctx.audit_entries()
    for iid, reason in (
        (999, "no such record"),
        (real, "it is not reviewed as a false call"),
        (open_, "it is not reviewed as a false call"),
        (no_image, "its board image was not stored"),
    ):
        with pytest.raises(AoiError) as refused:
            ctx.add_false_call_sample(iid)
        assert refused.value.code == "AOI-TRN-050" and refused.value.what == (
            f"Record {iid} was not added to Training: {reason}. Nothing was changed."
        )
    assert ctx.samples("B") == [] and ctx.audit_entries() == before

    old = _record(ctx, _board(tmp_path, "old", 5), view=None)
    ctx.review_result(old, FALSE_CALL, "Dust on the board")
    assert ctx.add_false_call_sample(old)["view"] == "Top"


def test_req_trn_020_a_board_inspected_from_a_customer_s_store_is_added_decrypted(
    ctx: AppContext, tmp_path: Path
) -> None:
    """A record whose board image is a file of a customer's dataset store (REQ-TRN-017), such as a stored sample
    inspected again, is read decrypted: another board model outside a store gets the image plain, its SHA-256 the
    picture's; the store's own board model holds it already, so nothing is added."""
    ctx.ensure_board_model("B")
    source = _board(tmp_path, "stored", 7)
    ctx.import_samples("S", [source], "NG", "Missing Component")
    in_store(ctx, "S", "Acme Electronics")
    (stored,) = ctx.samples("S")
    assert Path(stored["path"]).read_bytes() != Path(source).read_bytes()  # encrypted on disk
    other, own = _record(ctx, stored["path"]), _record(ctx, stored["path"], board="S")
    for iid in (other, own):
        ctx.review_result(iid, FALSE_CALL, "Dust on the board")
    assert ctx.add_false_call_sample(other)["added"] == 1
    (sample,) = ctx.samples("B")
    assert Path(sample["path"]).read_bytes() == Path(source).read_bytes()  # plain, outside a store
    out = ctx.add_false_call_sample(own)
    assert (out["added"], out["sample"], out["label"]) == (0, stored["uuid"], "NG") and len(ctx.samples("S")) == 1


def test_req_trn_020_logs_adds_the_selected_false_call_to_training(
    qtbot: QtBot, ctx: AppContext, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Add to Training as OK shows for an Engineer and an Admin, never an Operator; it is on only while the selected
    record is reviewed as a false call, so reviewing one with F11 turns it on; pressing it adds the board on the pool
    thread and says so in the status bar, and pressing it again says the board is a sample already."""
    ctx.ensure_board_model("B")
    iid = _record(ctx, _board(tmp_path, "ng", 6))
    win = MainWindow(ctx)
    qtbot.addWidget(win)
    win.set_user("operator")
    win.navigate("Logs & Export")
    page = cast(LogsPage, win.pages["Logs & Export"])
    listed(qtbot, page)
    assert not page.btn_train.isHidden() and not page.btn_train.isEnabled()  # an Operator reviews; Training is not
    assert page.btn_train.toolTip() == "Adding a board to Training needs the Engineer or Admin role."  # theirs
    win.set_user("engineer")
    win.navigate("Logs & Export")
    listed(qtbot, page)
    assert not page.btn_train.isHidden() and not page.btn_train.isEnabled()  # nothing selected
    page.table.selectRow(0)
    assert not page.btn_train.isEnabled()  # not reviewed yet
    monkeypatch.setattr(QInputDialog, "getItem", staticmethod(lambda *a, **k: ("Dust on the board", True)))
    page.review.act_false.trigger()
    qtbot.waitUntil(page.btn_train.isEnabled, timeout=30000)

    status = win.statusBar().currentMessage
    with heavy_calls(stall="AppContext.add_false_call_sample") as calls, gap_meter(qtbot) as g:
        page.btn_train.click()
        assert ctx.samples("B") == [], "the copy runs on a pool thread"
        qtbot.waitUntil(lambda: "on Training" in status(), timeout=30000)
    assert_off_ui_thread(calls, "AppContext.add_false_call_sample", "AppContext.import_samples")
    assert g["longest_s"] < BUDGET_S, g
    assert status() == f"Record {iid}'s board is now an OK sample of B (Bottom) on Training."
    assert [(s["label"], s["side"]) for s in ctx.samples("B")] == [("OK", "Bottom")]
    qtbot.waitUntil(page.btn_train.isEnabled, timeout=30000)  # the job ended
    page.btn_train.click()
    qtbot.waitUntil(lambda: "already" in status(), timeout=30000)
    assert status() == f"Record {iid}'s board is already a sample of B, labelled OK, on Training."
    assert len(ctx.samples("B")) == 1
