"""REQ-TRN-005 and -006 on screen (Datasets stage 4 of 4): Training › Datasets' Versions table, the board model's
frozen versions newest first; Verify Manifest, which re-hashes the version picked on the pool; and Export Manifest…,
which writes it as CSV. Results on synthetic
boards prove a code path; they are never quoted as accuracy."""

from __future__ import annotations

import csv
import json
import threading
from pathlib import Path

import pytest
from PySide6.QtWidgets import QFileDialog, QMessageBox
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


def test_req_trn_005_export_manifest(
    qtbot: QtBot,
    ctx: AppContext,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    dialogs: list[tuple[str, str]],
) -> None:
    """Export Manifest… asks first, naming the version and its file count, and No writes nothing. Yes and a file name
    write the version picked as CSV, one row per file in the manifest's order: path, SHA-256, label, defect type,
    boxes, labeller and checker by name and its part of the split; the export is audited and the status line says so.
    A file that cannot be written is AOI-LOG-002's dialog. Off with no version picked."""
    samples, cal = ready(ctx, tmp_path / "boards")
    agree(ctx, cal, samples)
    v1 = ctx.freeze_dataset(CAL, "Top", "R3", "Acme")
    split = ctx.lock_validation_set(v1["uuid"], seed=1)
    page = _datasets(qtbot, ctx)
    page.shell.set_user("admin")  # only an Admin exports (Q58, #151)
    asked, answers = [], [QMessageBox.StandardButton.No, QMessageBox.StandardButton.Yes, QMessageBox.StandardButton.Yes]

    def question(_parent: object, title: str, text: str, *_rest: object) -> QMessageBox.StandardButton:
        asked.append((title, text))
        return answers[len(asked) - 1]

    out = tmp_path / "out" / "manifest.csv"
    out.parent.mkdir()
    picked = [str(out), str(out.parent)]  # the second, a folder, cannot be written as a file
    monkeypatch.setattr(QMessageBox, "question", staticmethod(question))
    monkeypatch.setattr(QFileDialog, "getSaveFileName", staticmethod(lambda *_a: (picked.pop(0), "")))
    page.versions.btn_export.click()
    assert asked == [("Confirm export", f"Export the manifest of {v1['name']}: 100 files, one row each?")]
    assert not out.exists() and len(picked) == 2
    page.versions.btn_export.click()
    with out.open(encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        rows = list(reader)
    assert reader.fieldnames == ["path", "sha256", "label", "defect_type", "boxes", "labelled_by", "checked_by", "part"]
    items = ctx.dataset_items(v1["uuid"])
    assert [(r["path"], r["sha256"], r["label"]) for r in rows] == [(i["path"], i["sha256"], i["label"]) for i in items]
    ng = [(r, i) for r, i in zip(rows, items, strict=True) if i["label"] == "NG"]
    assert {r["defect_type"] for r, _ in ng} == {"Scratch"} and {r["checked_by"] for r, _ in ng} == {"kim"}
    assert all(json.loads(r["boxes"]) == i["boxes"] for r, i in ng)
    assert {r["labelled_by"] for r in rows} <= {u["name"] for u in ctx.users()}
    parts = {i["uuid"]: r["part"] for r, i in zip(rows, items, strict=True)}
    assert sorted(u for u, p in parts.items() if p == "validation") == sorted(split["validation"])
    [entry] = ctx.audit_entries(action="export.csv")
    assert (entry["object_type"], entry["after"]["rows"]) == ("dataset manifest", 100)
    said = page.shell.statusBar().currentMessage()
    assert said == f"Exported the manifest of {v1['name']}: 100 files to manifest.csv"
    page.versions.btn_export.click()
    assert [title.split()[0] for title, _ in dialogs] == ["AOI-LOG-002"] and not picked
    page.shell._on_board_model("")
    assert not page.versions.btn_export.isEnabled()
