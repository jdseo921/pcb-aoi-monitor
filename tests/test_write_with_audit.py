"""#178: a write and its audit entry commit together or not at all (REQ-LOG-004). An import that fails part-way stores
nothing, an overlay export that fails part-way records what left, and a training run whose registration fails keeps the
Golden board in use and never reuses a file name a result may name (REQ-CMP-003)."""

from __future__ import annotations

import shutil
import sqlite3
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from PySide6.QtWidgets import QFileDialog, QInputDialog
from pytestqt.qtbot import QtBot

from aoi.config import Settings
from aoi.core.imaging import list_images, load_image, save_image
from aoi.core.services import AppContext
from aoi.data import atomic
from aoi.ui.main_window import MainWindow
from tests.test_req_done_in_v01 import BOARD, _window
from tests.test_roles_and_audit import WRITES

ROOT = Path(__file__).resolve().parents[1]


def _fail_audit(monkeypatch: pytest.MonkeyPatch, ctx: AppContext, action: str) -> None:
    """The audit entry `action` cannot be written, as with a full disk or a database another program holds."""
    add = ctx.db.add_audit

    def add_or_fail(*a: Any) -> str:
        if a[2] == action:
            raise sqlite3.OperationalError("database or disk is full")
        return add(*a)

    monkeypatch.setattr(ctx.db, "add_audit", add_or_fail)


def _state(ctx: AppContext, out: Path) -> set[str]:
    """Every row of the database, and every file in the workspace (logs and the database aside) and in `out`."""
    files = [p for root in (ctx.settings.root, out) for p in root.rglob("*") if p.is_file()]
    kept = {str(p) for p in files if "logs" not in p.parts and not p.name.startswith("aoi.sqlite")}
    return set(ctx.db._conn.iterdump()) | kept


def _second_version(ctx: AppContext) -> None:
    """v1.1 active, so activating v1.0 (WRITES) changes which AI model judges."""
    v10 = ctx.models("TINY")[0]
    ctx.db.register_model("TINY", "v1.1", v10["path"], {}, activate=True)


def _a_result(ctx: AppContext) -> None:
    """One stored result with its overlay, so archiving and exporting overlays have something to change."""
    ctx.inspect_file("TINY", ctx.samples("TINY", "OK")[0]["path"])


# a write that would change nothing on the trained workspace gets something to change, or its case proves nothing
SETUP: dict[str, Callable[[AppContext], None]] = {
    "activate_model": _second_version,
    "archive_old": _a_result,
    "export_overlays": _a_result,
}


@pytest.mark.parametrize("method", list(WRITES))
def test_req_log_004_a_write_whose_audit_entry_fails_leaves_nothing(
    method: str, trained_ctx: AppContext, synthetic_dataset: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    action, call = WRITES[method]
    trained_ctx.set_user("admin")  # every write's role
    SETUP.get(method, lambda ctx: None)(trained_ctx)
    out = tmp_path / "out"
    out.mkdir()
    before = _state(trained_ctx, out)
    _fail_audit(monkeypatch, trained_ctx, action)
    with pytest.raises(sqlite3.OperationalError):
        call(trained_ctx, synthetic_dataset, out)
    assert _state(trained_ctx, out) ^ before == set()  # no row, revision or file without its entry


def test_req_log_004_a_recipe_revision_and_its_entry_survive_a_crash_together(workspace: Settings) -> None:
    script = f"""
import os
from aoi.config import Settings
from aoi.core.recipe import Recipe
from aoi.core.services import AppContext
ctx = AppContext(Settings(workspace={workspace.workspace!r}, device="cpu"))
ctx.set_user("engineer")
ctx.ensure_board_model("B1")
add = ctx.db.add_audit
ctx.db.add_audit = lambda *a: os._exit(9) if a[2] == "recipe.save" else add(*a)  # the process dies in between
ctx.save_recipe(Recipe.from_dict({{**Recipe(board_model="B1").to_dict(), "warn_ratio": 2.1}}))
"""
    assert subprocess.run([sys.executable, "-c", script], cwd=ROOT, timeout=120).returncode == 9
    ctx = AppContext(workspace)
    assert ctx.recipe("B1")[0] == 1 and ctx.recipe("B1")[1].warn_ratio != 2.1
    assert ctx.audit_entries(action="recipe.save") == []
    ctx.close()


def test_req_trn_001_an_import_that_fails_part_way_stores_nothing(
    qtbot: QtBot,
    ctx: AppContext,
    synthetic_dataset: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    dialogs: list[tuple[str, str]],
) -> None:
    win = MainWindow(ctx)
    qtbot.addWidget(win)
    win.set_user("engineer")
    win._on_board_model("NEWB")
    page = win.pages["Training"]
    files = [tmp_path / f"ok{i}.png" for i in range(3)]
    for f, p in zip(files, list_images(synthetic_dataset / "train" / "ok"), strict=False):
        shutil.copy(p, f)
    files[2].unlink()  # gone between the pick and the copy
    monkeypatch.setattr(QFileDialog, "getOpenFileNames", staticmethod(lambda *_: ([str(f) for f in files], "")))
    monkeypatch.setattr(QInputDialog, "getItem", staticmethod(lambda *a: (a[3][0], True)))
    page.add_ok()  # the copies run on the pool (#194); the error reaches the coded dialog
    qtbot.waitUntil(lambda: page._bg is None, timeout=30000)
    [(title, text)] = dialogs  # refused as Inspection refuses it (REQ-TRN-001, S31); the copies made are removed
    assert title == "AOI-INSP-001 Image cannot be read" and "ok2.png" in text, (title, text)
    assert ctx.samples("NEWB") == [] and ctx.audit_entries(action="sample.import") == []
    assert not any((ctx.settings.images_dir / "NEWB").rglob("*.png"))  # no copy left behind
    shutil.copy(list_images(synthetic_dataset / "train" / "ok")[2], files[2])  # the file put back: Try again
    page.add_ok()
    qtbot.waitUntil(lambda: page._bg is None, timeout=30000)
    assert len(ctx.samples("NEWB")) == 3 and ctx.reference_image("NEWB") and ctx.recipe("NEWB")[0] == 1
    assert [e["after"]["added"] for e in ctx.audit_entries(action="sample.import")] == [3]


def test_req_trn_001_a_folder_import_that_fails_part_way_says_what_was_imported(
    qtbot: QtBot,
    ctx: AppContext,
    synthetic_dataset: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    dialogs: list[tuple[str, str]],
) -> None:
    """A folder import imports one file per call (Cancel keeps what was imported), so a file it cannot copy leaves the
    files before it imported: the message says so, and the table shows them, so the folder is not imported twice."""
    folder = tmp_path / "fold"
    (folder / "ok").mkdir(parents=True)
    for i, p in enumerate(list_images(synthetic_dataset / "train" / "ok")[:5]):
        shutil.copy(p, folder / "ok" / f"ok_{i}.png")
    copy = atomic.copy_file

    def copy_or_refuse(src: str | Path, dst: str | Path) -> None:
        if Path(src).name == "ok_2.png":
            raise PermissionError(13, "Permission denied", str(src))
        copy(src, dst)

    monkeypatch.setattr(atomic, "copy_file", copy_or_refuse)
    win = MainWindow(ctx)
    qtbot.addWidget(win)
    win.set_user("engineer")
    win._on_board_model("NEWB")
    page = win.pages["Training"]
    page.import_from(str(folder))
    qtbot.waitUntil(lambda: page._bg is None, timeout=30000)
    assert len(ctx.samples("NEWB")) == 2 and page.samples.rowCount() == 2  # the two before it, shown in the table
    [(title, text)] = dialogs
    assert title == "AOI-TRN-009 Folder import stopped part-way", title
    assert "ok_2.png" in text and "Permission denied" in text and "image 3 of 5" in text, text
    assert "the 2 image(s) imported before it" in text and "the 2 image(s) already imported are skipped" in text, text
    assert win.statusBar().currentMessage() == "Imported 2 OK and 0 NG images"


def test_req_log_004_an_export_onto_its_own_file_is_never_removed(
    trained_ctx: AppContext, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An export whose entry cannot be written removes what it wrote, but never the station's own file it was
    exported onto (the model's .pt, an overlay exported into the results folder)."""
    ctx = trained_ctx
    _a_result(ctx)
    overlay = Path(ctx.inspections()[0]["overlay_path"])
    model = Path(ctx.models("TINY")[0]["path"])
    _fail_audit(monkeypatch, ctx, "export.model")
    with pytest.raises(sqlite3.OperationalError):
        ctx.export_model(ctx.models("TINY")[0]["id"], model)
    _fail_audit(monkeypatch, ctx, "export.overlays")
    with pytest.raises(sqlite3.OperationalError):
        ctx.export_overlays(ctx.inspections(), overlay.parent)
    assert model.is_file() and overlay.is_file()


def test_req_log_002_an_overlay_export_that_fails_part_way_records_what_left(
    qtbot: QtBot,
    trained_ctx: AppContext,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    dialogs: list[tuple[str, str]],
) -> None:
    for s in trained_ctx.samples(BOARD, "OK")[:2]:
        trained_ctx.inspect_file(BOARD, s["path"])
    win = _window(qtbot, trained_ctx)
    win.navigate("Logs & Export")
    page = win.pages["Logs & Export"]
    first, second = (Path(r["overlay_path"]).name for r in page.rows)
    dest = tmp_path / "usb"
    (dest / second).mkdir(parents=True)  # a name the copy cannot take
    monkeypatch.setattr(QFileDialog, "getExistingDirectory", staticmethod(lambda *_: str(dest)))
    page.export_overlays()  # on the pool (#194); the error reaches the coded dialog
    qtbot.waitUntil(lambda: page._bg is None, timeout=30000)
    [(title, text)] = dialogs
    assert title == "AOI-LOG-001 Export stopped part-way" and second in text, (title, text)
    assert (dest / first).is_file()
    entry = trained_ctx.audit_entries(action="export.overlays")[0]["after"]
    assert (entry["records"], entry["copied"], entry["folder"]) == (2, 1, str(dest)) and second in entry["error"]


def test_req_trn_010_a_run_that_fails_to_register_keeps_the_golden_board(
    trained_ctx: AppContext, ng_board: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ctx = trained_ctx
    golden, entries = ctx.reference_image(BOARD), ctx.audit_entries()
    with monkeypatch.context() as m:
        m.setattr(ctx.db, "register_model", lambda *a, **k: (_ for _ in ()).throw(sqlite3.OperationalError("locked")))
        with pytest.raises(sqlite3.OperationalError):
            ctx.train(BOARD, epochs=1, image_size=32)
    assert ctx.reference_image(BOARD) == golden and ctx.audit_entries() == entries
    assert [m["version"] for m in ctx.models(BOARD)] == ["v1.0"]
    assert not list((ctx.settings.models_dir / BOARD).glob("*v1.1*"))  # the failed run's files are removed
    ctx.inspect_file(BOARD, str(ng_board))
    rid = ctx.inspections()[0]["id"]
    ctx.train(BOARD, epochs=1, image_size=32)
    assert ctx.judged_reference(rid)[1] == "same"


def test_req_cmp_003_training_never_writes_over_a_golden_board_a_result_names(
    trained_ctx: AppContext, ng_board: Path
) -> None:
    ctx = trained_ctx
    left = ctx.settings.models_dir / BOARD / f"{BOARD}_v1.1_golden.png"  # a run that died before it was registered
    img = load_image(str(ctx.reference_image(BOARD)))
    img[:20] = 0
    save_image(left, img)
    ctx.db.set_reference(BOARD, str(left))  # in use, as the code before #178 left it
    ctx.inspect_file(BOARD, str(ng_board))
    rid, judged = ctx.inspections()[0]["id"], left.read_bytes()
    ctx.train(BOARD, epochs=1, image_size=32)
    assert [m["version"] for m in ctx.models(BOARD)] == ["v1.2", "v1.0"]
    assert left.read_bytes() == judged and ctx.judged_reference(rid)[1] == "same"
