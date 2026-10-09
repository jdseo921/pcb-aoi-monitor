"""REQ-TRN-005 and -006 on screen (Datasets stage 4 of 4): Training › Datasets' Versions table, the board model's
frozen versions newest first, and Verify Manifest, which re-hashes the version picked on the pool. Results on synthetic
boards prove a code path; they are never quoted as accuracy."""

from __future__ import annotations

import threading
from pathlib import Path

import pytest
from pytestqt.qtbot import QtBot

from aoi.core.services import AppContext
from aoi.times import to_local
from aoi.ui.pages.base import cell_text
from aoi.ui.pages.training import TrainingPage
from tests.test_datasets import agree, ready
from tests.test_freeze_screen import _datasets, _idle
from tests.test_labeller_agreement import CAL


def _row(page: TrainingPage, row: int) -> list[str]:
    t = page.versions.table
    return [cell_text(t, row, c) for c in range(t.columnCount())]


def test_req_trn_005_versions_table(qtbot: QtBot, ctx: AppContext, tmp_path: Path) -> None:
    """The Versions table lists the board model's frozen versions newest first, the newest picked: name, when frozen
    in local time, by whom, its OK and NG files, its locked validation set or "not locked", customer, uses, and a
    Manifest cell blank until Verify Manifest has checked it. A version Freeze makes is picked once it is listed."""
    samples, cal = ready(ctx, tmp_path / "boards")
    agree(ctx, cal, samples)
    v1 = ctx.freeze_dataset(CAL, "Top", "R3", "Acme", ["own", "shared"])
    ctx.lock_validation_set(v1["uuid"], seed=1)
    v2 = ctx.freeze_dataset(CAL, "Top", "R4", "Acme")
    page = _datasets(qtbot, ctx)
    assert page.versions.isVisible() and page.versions.table.rowCount() == 2
    assert _row(page, 0) == [
        v2["name"],
        to_local(v2["frozen_at"]),
        "engineer",
        "80",
        "20",
        "not locked",
        "Acme",
        "own",
        "",
    ]
    assert _row(page, 1)[3:8] == ["80", "20", "50 / 6", "Acme", "own, shared"]
    assert page.versions.picked() == v2["uuid"] and page.versions.btn_verify.isEnabled()
    page.versions.table.selectRow(1)
    page.refresh()
    assert page.versions.picked() == v1["uuid"]  # kept as the page refreshes
    page.working.btn_freeze.click()
    page.working.sheet.btn_now.click()
    _idle(qtbot, page)
    assert page.versions.table.rowCount() == 3 and page.versions.picked() == ctx.datasets(CAL)[0]["uuid"]


def test_req_trn_005_versions_empty_state(qtbot: QtBot, ctx: AppContext, tmp_path: Path) -> None:
    """With no frozen version the table says so and what to do, with Freeze Dataset… opening the sheet while the
    working set has an image labelled OK or NG, off while the sheet is open; Verify Manifest is off."""
    ready(ctx, tmp_path / "boards")
    page = _datasets(qtbot, ctx)
    empty = page.versions.empty
    assert empty.isVisible() and empty.heading.text() == "No frozen dataset for CAL-1 yet"
    assert empty.sentence.text() == "Check the labels, Freeze Dataset, then split and lock its validation set."
    assert empty.link.text() == "Freeze Dataset…" and not page.versions.btn_verify.isEnabled()
    empty.link.click()
    assert page.working.sheet.isVisible() and not empty.link.isEnabled()  # off, as Freeze Dataset… is
    page.working.sheet.close_sheet()
    assert empty.link.isEnabled()
    ctx.ensure_board_model("NO-SAMPLES")
    page.shell._reload_board_models("NO-SAMPLES")
    assert empty.heading.text() == "No frozen dataset for NO-SAMPLES yet" and not empty.link.isVisibleTo(empty)


def test_req_trn_005_verify_manifest(
    qtbot: QtBot, ctx: AppContext, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Verify Manifest re-hashes the version picked on the pool, Verify Manifest off meanwhile: all files match, its
    Manifest cell says ✓ 100/100 and the status line says so. With a file changed and one removed since the freeze:
    ✗ 1 changed, 1 missing, and under the table AOI-TRN-023 with both files named. Cancel stops a check after the
    files hashed so far and marks nothing, the cell keeping what the check before found."""
    samples, cal = ready(ctx, tmp_path / "boards")
    agree(ctx, cal, samples)
    v1 = ctx.freeze_dataset(CAL, "Top", "R3", "Acme")
    page = _datasets(qtbot, ctx)
    versions = page.versions
    versions.btn_verify.click()
    assert not versions.btn_verify.isEnabled()
    _idle(qtbot, page)
    assert _row(page, 0)[8] == "✓ 100/100" and not versions.found.isVisible()
    assert page.shell.statusBar().currentMessage() == f"{v1['name']}: all 100 files match its manifest"
    files = ctx.dataset_items(v1["uuid"])
    changed, gone = (ctx.settings.root / files[i]["path"] for i in (0, 1))
    changed.write_bytes(b"not the frozen file")
    gone.unlink()
    versions.btn_verify.click()
    _idle(qtbot, page)
    assert versions.picked() == v1["uuid"] and _row(page, 0)[8] == "✗ 1 changed, 1 missing"
    said = versions.found.text()
    assert versions.found.isVisible() and said.startswith(f"AOI-TRN-023 {v1['name']} does not match what was frozen")
    assert said.endswith(f"Changed or missing: {changed.name}, {gone.name}")
    sha, hashed, go_on = ctx._verified_sha256, [], threading.Event()

    def held_after_two(path: Path) -> str | None:
        hashed.append(path)
        if len(hashed) == 3:  # the manifest, then two files
            go_on.wait(30)  # until the test has pressed Cancel
        return sha(path)

    monkeypatch.setattr(ctx, "_verified_sha256", held_after_two)
    versions.btn_verify.click()
    qtbot.waitUntil(lambda: len(hashed) == 3, timeout=30000)
    versions.busy.cancel_button.click()
    go_on.set()
    _idle(qtbot, page)
    said = page.shell.statusBar().currentMessage()
    assert said == f"Verify Manifest of {v1['name']} stopped after 2 of 100 files; nothing was marked"
    assert _row(page, 0)[8] == "✗ 1 changed, 1 missing" and versions.found.isVisible()
