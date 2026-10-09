"""REQ-TRN-006 on screen (Datasets stage 4 of 4): Training › Datasets' Split and Lock Validation Set…, whose sheet
shows what the version picked holds against what a validation set takes and a random seed the user may change, and
Lock, which splits the version once, on the pool. Results on synthetic boards prove a code path; they are never quoted
as accuracy."""

from __future__ import annotations

import threading
from pathlib import Path
from typing import Any

import pytest
from PySide6.QtCore import Qt
from pytestqt.qtbot import QtBot

from aoi.core.services import AppContext
from aoi.ui.pages import base
from tests.test_datasets import agree, ready
from tests.test_freeze_screen import _datasets, _idle
from tests.test_labeller_agreement import CAL
from tests.test_validation_set import frozen
from tests.test_versions_screen import _row

LOCKED_TIP = "Its validation set is locked: a new split needs a new dataset version"


def test_req_trn_006_split_and_lock_on_screen(qtbot: QtBot, ctx: AppContext, tmp_path: Path) -> None:
    """Split and Lock Validation Set… opens the sheet for the version picked in the labeller agreement's place: its OK
    and NG files against what the validation set takes, and a random seed with the focus; Freeze Dataset… and the
    button are off while it is open, and Esc closes it, writing nothing. Lock is off with no seed; Enter locks with
    the seed typed on the pool, the buttons off meanwhile: the sheet closes, the table says 50 / 6, the status line
    counts both sets, the audit holds the seed, and the button is off with why while Verify Manifest stays on."""
    v1 = frozen(ctx, tmp_path)
    page = _datasets(qtbot, ctx)
    versions, split = page.versions, page.versions.split
    assert versions.btn_split.isEnabled() and versions.btn_split.toolTip() == ""
    versions.btn_split.click()
    assert split.isVisible() and not page.agreement.isVisible()
    assert split.title() == f"Split and lock the validation set of {v1['name']}"
    assert split.what.text() == (
        "✓ 80 OK and 20 NG files. The validation set takes 50 OK and 6 NG (30 % of the NG, rounded up), by defect type"
        " where it can, and the training set the rest."
    )
    assert split.kinds.isVisible() and split.kinds.text() == "NG by defect type: Scratch 20"
    assert split.seed.hasFocus() and 0 <= int(split.seed.text()) <= 2**31 - 1 and split.btn_lock.isEnabled()
    assert not versions.btn_split.isEnabled() and not page.working.act_freeze.isEnabled()  # one sheet at a time
    qtbot.keyClick(split.seed, Qt.Key.Key_Escape)
    assert not split.isVisible() and page.agreement.isVisible() and ctx.validation_split(v1["uuid"]) is None
    assert versions.btn_split.isEnabled() and page.working.act_freeze.isEnabled()
    versions.btn_split.click()
    split.seed.clear()
    assert not split.btn_lock.isEnabled()
    qtbot.keyClicks(split.seed, "-")  # the validator lets no sign in
    assert split.seed.text() == ""
    qtbot.keyClicks(split.seed, "1")
    qtbot.keyClick(split.seed, Qt.Key.Key_Return)
    assert not split.btn_lock.isEnabled() and not versions.btn_verify.isEnabled()  # while the lock runs
    _idle(qtbot, page)
    assert not split.isVisible() and page.agreement.isVisible() and _row(page, 0)[5] == "50 / 6"
    said = page.shell.statusBar().currentMessage()
    assert said == f"Locked the validation set of {v1['name']}: 50 OK / 6 NG, the training set 30 OK / 14 NG, seed 1"
    [entry] = ctx.audit_entries(action="dataset.lock")
    assert (entry["object_uuid"], entry["after"]["seed"]) == (v1["uuid"], 1)
    assert not versions.btn_split.isEnabled() and versions.btn_split.toolTip() == LOCKED_TIP
    assert versions.btn_verify.isEnabled()


def test_req_trn_006_split_sheet_names_too_few_ok_files(qtbot: QtBot, ctx: AppContext, tmp_path: Path) -> None:
    """A version with fewer OK files than a validation set takes: the sheet says so with the fix, and Lock stays off
    with a seed. A sign-in, another board model or another version picked closes the sheet, writing nothing."""
    frozen(ctx, tmp_path)
    drawn = set(ctx.db.ok_check_draws(CAL, "Top")[0]["sample_uuids"])
    keep = drawn | {s["uuid"] for s in ctx.samples(CAL) if s["path"] == ctx.db.reference(CAL)}  # the Golden board too
    for s in [s for s in ctx.samples(CAL, "OK") if s["uuid"] not in keep][:31]:
        ctx.set_label(s["uuid"], "UNSURE")  # out of the next version: 49 OK left
    v2 = ctx.freeze_dataset(CAL, "Top", "R4", "Acme")
    page = _datasets(qtbot, ctx)
    split = page.versions.split
    assert page.versions.picked() == v2["uuid"]
    page.versions.btn_split.click()
    assert split.what.text() == (
        "✗ 49 OK and 20 NG files: a validation set takes 50 OK files. Freeze a version with more OK images, then split"
        " that."
    )
    assert split.seed.hasAcceptableInput() and not split.btn_lock.isEnabled()
    leave = (
        lambda: page.shell.set_user("engineer"),
        lambda: page.shell._on_board_model(""),
        lambda: page.versions.table.selectRow(1),
    )
    for step in leave:
        assert split.isVisible() and split.version is not None and split.version["uuid"] == v2["uuid"]
        step()
        assert not split.isVisible() and split.version is None
        page.shell._on_board_model(CAL)
        page.versions.table.selectRow(0)
        page.versions.btn_split.click()
    assert ctx.validation_split(v2["uuid"]) is None


def test_req_trn_006_lock_cancelled_too_late_or_refused(
    qtbot: QtBot, ctx: AppContext, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, dialogs: list[tuple[str, str]]
) -> None:
    """A Cancel before the lock began writes nothing, says so and keeps the sheet for another try. The lock checks no
    Cancel: one while it runs comes too late, and the lock is said and shown as without it. A version split behind
    the sheet is refused with AOI-TRN-022: the dialog, and the sheet closes on what the table shows now."""
    samples, cal = ready(ctx, tmp_path / "boards")
    agree(ctx, cal, samples)
    v1 = ctx.freeze_dataset(CAL, "Top", "R3", "Acme")
    v2 = ctx.freeze_dataset(CAL, "Top", "R4", "Acme")
    page = _datasets(qtbot, ctx)
    versions, split = page.versions, page.versions.split
    start, queued = base.start, []
    monkeypatch.setattr(base, "start", lambda w, pool: queued.append((w, pool)) or w)  # the job held in the queue
    versions.btn_split.click()
    split.btn_lock.click()
    split.busy.cancel_button.click()
    start(*queued[0])  # it runs only now, cancelled
    _idle(qtbot, page)
    assert page.shell.statusBar().currentMessage() == f"Lock of {v2['name']} cancelled: nothing was written"
    assert split.isVisible() and split.btn_lock.isEnabled() and ctx.validation_split(v2["uuid"]) is None
    monkeypatch.setattr(base, "start", start)
    lock, began, go_on = ctx.lock_validation_set, threading.Event(), threading.Event()

    def held(uuid: str, seed: int) -> dict[str, Any]:
        began.set()
        go_on.wait(30)  # until the test has pressed Cancel
        return lock(uuid, seed)

    monkeypatch.setattr(ctx, "lock_validation_set", held)
    split.seed.setText("2")
    split.btn_lock.click()
    qtbot.waitUntil(began.is_set, timeout=30000)
    split.busy.cancel_button.click()
    go_on.set()
    _idle(qtbot, page)
    said = page.shell.statusBar().currentMessage()
    assert said.startswith(f"Locked the validation set of {v2['name']}: 50 OK / 6 NG") and said.endswith("seed 2")
    assert not split.isVisible() and _row(page, 0)[5] == "50 / 6"
    versions.table.selectRow(1)
    versions.btn_split.click()
    lock(v1["uuid"], 3)  # behind the sheet
    split.btn_lock.click()
    _idle(qtbot, page)
    assert [title.split()[0] for title, _ in dialogs] == ["AOI-TRN-022"]
    assert not split.isVisible() and versions.picked() == v1["uuid"] and _row(page, 1)[5] == "50 / 6"
    assert not versions.btn_split.isEnabled() and versions.btn_split.toolTip() == LOCKED_TIP
