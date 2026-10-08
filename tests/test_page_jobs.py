"""#194 (REQ-USR-001, REQ-LOG-004, REQ-SET-021): an export or image import a page runs in the background works for the
user who started it, even after a Switch User, and runs to its end unless that user presses Cancel: the buttons and
links that would start a second one, and stop the first, are off until it ends, and its busy overlay stays on top."""

from __future__ import annotations

import shutil
from collections.abc import Callable
from pathlib import Path
from time import sleep
from typing import Any

import pytest
from PySide6.QtCore import QDate, Qt
from PySide6.QtWidgets import QFileDialog, QInputDialog, QMessageBox
from pytestqt.qtbot import QtBot

from aoi.core.services import AppContext
from aoi.data import atomic
from aoi.ui.main_window import MainWindow
from aoi.ui.pages.training import NgDialog
from aoi.ui.widgets.busy import BusyOverlay
from tests.test_req_done_in_v01 import BOARD, _button, _window

N = 24  # files per action; each copy is slowed to 50 ms, so an action runs for about 1.2 s


@pytest.fixture
def slow_copies(monkeypatch: pytest.MonkeyPatch) -> None:
    real = atomic.copy_file
    monkeypatch.setattr(atomic, "copy_file", lambda *a, **k: sleep(0.05) or real(*a, **k))


@pytest.fixture
def pickers(monkeypatch: pytest.MonkeyPatch, ng_board: Path, tmp_path: Path) -> Path:
    """Every dialog answered: N copies of `ng_board` picked, Top, Yes, and exports into the returned folder."""
    out = tmp_path / "out"
    out.mkdir()
    monkeypatch.setattr(QFileDialog, "getOpenFileNames", staticmethod(lambda *a, **k: ([str(ng_board)] * N, "")))
    monkeypatch.setattr(QInputDialog, "getItem", staticmethod(lambda *a, **k: ("Top", True)))
    monkeypatch.setattr(NgDialog, "exec", lambda self: 1)  # OK on "Unknown / mixed", Top
    monkeypatch.setattr(QMessageBox, "question", staticmethod(lambda *a, **k: QMessageBox.StandardButton.Yes))
    monkeypatch.setattr(QFileDialog, "getExistingDirectory", staticmethod(lambda *a, **k: str(out)))
    monkeypatch.setattr(QFileDialog, "getSaveFileName", staticmethod(lambda *a, **k: (str(out / "rows.csv"), "")))
    return out


def _records_with_overlays(ctx: AppContext, board: Path, folder: Path) -> None:
    folder.mkdir()
    for i in range(N):
        overlay = folder / f"overlay_{i:03d}.png"
        shutil.copyfile(board, overlay)
        rec = {"board_model": BOARD, "result": "OK", "view": "Top", "image_path": str(overlay)}
        ctx.db.add_inspection({**rec, "overlay_path": str(overlay)}, [], None)


def _imported(ctx: AppContext) -> int:
    """Copies in the sample folder: an import copies every file first and adds the samples at the end (#178)."""
    return len([p for p in (ctx.settings.images_dir / BOARD / "OK").glob("*") if not p.name.startswith(".")])


def _copied(folder: Path) -> int:
    return len(list(folder.glob("overlay_*.png")))  # a copy in progress has a temporary name


def _last(ctx: AppContext, action: str) -> dict[str, Any]:
    return ctx.audit_entries(action=action)[0]


def _on_top(busy: BusyOverlay) -> list[bool]:
    """Whether a click on "Importing…" or "Exporting…", and on Cancel, reaches it, with no empty state over it (the
    window's childAt, as QApplication.widgetAt but not limited to the offscreen platform's 800 x 600 screen)."""
    return [w.window().childAt(w.mapTo(w.window(), w.rect().center())) is w for w in (busy.label, busy.cancel_button)]


def _switch_when(qtbot: QtBot, win: MainWindow, started: Callable[[], bool], role: str) -> None:
    qtbot.waitUntil(started, timeout=30000)
    win.set_user(role.lower())  # Switch User, in the header, outside the busy overlay


@pytest.mark.usefixtures("slow_copies")
def test_req_usr_001_a_background_import_or_export_works_for_the_user_who_started_it(
    qtbot: QtBot,
    trained_ctx: AppContext,
    ng_board: Path,
    pickers: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    dialogs: list[tuple[str, str]],
) -> None:
    """An Engineer starts + OK Images, Export Image Overlays and Export CSV, and an Operator takes the station while
    each runs: each job finishes, and its audit entry names the Engineer who started it, not the Operator."""
    engineer = (trained_ctx.db.user_uuid("engineer"), "Engineer")
    assert engineer[0] is not None
    win = _window(qtbot, trained_ctx)
    training = win.pages["Training"]
    win.navigate("Training")
    before, copies = len(trained_ctx.samples(BOARD)), _imported(trained_ctx)
    training.add_ok()
    _switch_when(qtbot, win, lambda: _imported(trained_ctx) > copies, "Operator")
    qtbot.waitUntil(lambda: training._bg is None, timeout=60000)
    entry = _last(trained_ctx, "sample.import")
    assert (entry["user_uuid"], entry["role"]) == engineer, "the import is the Engineer's, not the next user's"
    assert (entry["after"]["added"], entry["after"]["cancelled"]) == (N, False)
    assert len(trained_ctx.samples(BOARD)) == before + N and trained_ctx.role == "Operator"

    win.set_user("engineer")
    _records_with_overlays(trained_ctx, ng_board, tmp_path / "overlays")
    logs = win.pages["Logs & Export"]
    win.navigate("Logs & Export")
    status = win.statusBar().currentMessage
    logs.export_overlays()
    _switch_when(qtbot, win, lambda: _copied(pickers) > 0, "Operator")
    qtbot.waitUntil(lambda: logs._bg is None, timeout=60000)
    entry = _last(trained_ctx, "export.overlays")
    assert (entry["user_uuid"], entry["role"]) == engineer, "the export is the Engineer's, not the next user's"
    assert (entry["after"]["copied"], entry["after"]["cancelled"]) == (N, False)
    assert status() == f"Copied {N} overlay image(s) to {pickers}"

    win.set_user("engineer")
    win.navigate("Logs & Export")
    gathered: list[int] = []
    real = trained_ctx.defects_for
    monkeypatch.setattr(trained_ctx, "defects_for", lambda iid: gathered.append(iid) or sleep(0.05) or real(iid))
    logs.export_csv()
    _switch_when(qtbot, win, lambda: bool(gathered), "Operator")
    qtbot.waitUntil(lambda: logs._bg is None, timeout=60000)
    assert not dialogs, "the Operator is not refused an export the Engineer started"
    assert status().startswith(f"Exported {len(logs.rows)} records"), status()
    for entry in trained_ctx.audit_entries(action="export.csv")[:2]:  # the records and the checks file
        assert (entry["user_uuid"], entry["role"]) == engineer, entry["object_type"]


@pytest.mark.usefixtures("slow_copies")
def test_req_set_021_a_second_export_or_import_waits_for_the_first(
    qtbot: QtBot,
    trained_ctx: AppContext,
    ng_board: Path,
    pickers: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """While Export Image Overlays runs, Export CSV and Export Image Overlays are off, also after a switch to an
    Admin, who may export; while + OK Images runs, + NG Images, Import Folder… and Start Training are off. A click on
    one does nothing, the first job copies every file, and the buttons come back when it ends."""
    _records_with_overlays(trained_ctx, ng_board, tmp_path / "overlays")
    win = _window(qtbot, trained_ctx)
    logs = win.pages["Logs & Export"]
    win.navigate("Logs & Export")
    status = win.statusBar().currentMessage
    exports = [_button(logs, "Export CSV"), _button(logs, "Export Image Overlays")]
    logs.export_overlays()
    qtbot.waitUntil(lambda: _copied(pickers) > 0, timeout=30000)
    while_running = [b.isEnabled() for b in exports]
    qtbot.mouseClick(exports[0], Qt.MouseButton.LeftButton)  # Export CSV: would stop the export it waits for
    win.set_user("admin")  # the page stays and its buttons follow the new role
    while_running += [b.isEnabled() for b in exports]
    qtbot.waitUntil(lambda: logs._bg is None, timeout=60000)
    assert _copied(pickers) == N and status() == f"Copied {N} overlay image(s) to {pickers}", status()
    assert _last(trained_ctx, "export.overlays")["after"]["cancelled"] is False
    assert not (pickers / "rows.csv").exists(), "the clicked Export CSV did not run"
    assert while_running == [False] * 4
    assert all(b.isEnabled() for b in exports), "the exports come back when the first ends"

    monkeypatch.setattr(QFileDialog, "getExistingDirectory", staticmethod(lambda *a, **k: ""))  # Import Folder: none
    win.set_user("engineer")
    training = win.pages["Training"]
    win.navigate("Training")
    others = [_button(training, t) for t in ("+ NG Images", "Import Folder…", "Start Training")]
    ok_before = len(trained_ctx.samples(BOARD, "OK"))
    ng_before, copies = len(trained_ctx.samples(BOARD, "NG")), _imported(trained_ctx)
    training.add_ok()
    qtbot.waitUntil(lambda: _imported(trained_ctx) > copies, timeout=30000)
    while_running = [b.isEnabled() for b in others]
    for b in others[:2]:  # Start Training is not clicked: on a build where it is on, it would train for minutes
        qtbot.mouseClick(b, Qt.MouseButton.LeftButton)
    qtbot.waitUntil(lambda: training._bg is None, timeout=60000)
    assert len(trained_ctx.samples(BOARD, "OK")) == ok_before + N, "+ OK Images copied every file"
    assert len(trained_ctx.samples(BOARD, "NG")) == ng_before, "the clicked + NG Images did not run"
    assert while_running == [False] * 3
    assert all(b.isEnabled() for b in others), "the imports and Start Training come back when the import ends"
    status_before = status()
    training._add_stopped(N, N)  # Cancel came after the last file: every image was added, so no "Stopped" line
    assert status() == status_before


@pytest.mark.usefixtures("slow_copies")
def test_req_set_021_an_empty_state_neither_stops_an_import_nor_hides_the_busy_overlay(
    qtbot: QtBot,
    trained_ctx: AppContext,
    ng_board: Path,
    pickers: Path,
    tmp_path: Path,
    dialogs: list[tuple[str, str]],
) -> None:
    """On a board model with no samples, + OK Images and Import Folder… each add all their files and nothing else while
    the empty table's Import Folder… link is clicked and an import is started again; the page shown again, or Filter on
    days with no records during Export Image Overlays, leaves "Importing…" or "Exporting…" and Cancel on top."""
    (pickers / "ok").mkdir()  # Import Folder… picks this folder
    for i in range(N):
        shutil.copyfile(ng_board, pickers / "ok" / f"board_{i:02d}.png")
    win = _window(qtbot, trained_ctx)
    training, logs = win.pages["Training"], win.pages["Logs & Export"]
    for page in (training, logs):
        page.busy.SHOW_AFTER_S, page.busy.DETAIL_AFTER_S = 0.1, 0.1  # the 1 s and 10 s of the product, shortened
    seen: list[object] = []
    for name, start in (("EMPTY-OK", training.add_ok), ("EMPTY-FOLDER", training.import_folder)):
        trained_ctx.ensure_board_model(name)
        win._reload_board_models(name)
        win.navigate("Training")
        start()
        qtbot.waitUntil(training.busy.cancel_button.isVisible, timeout=30000)  # after 0.2 s of an import's 1.2 s
        win.navigate("Home")
        win.navigate("Training")  # shown again: the table is refreshed under "Importing…"
        if name == "EMPTY-OK":  # + OK adds its samples at the end (#178), so the empty state shows again
            seen.append((training.samples_empty.isVisible(), _on_top(training.busy)))
        link_on = training.samples_empty.link.isEnabled()
        qtbot.mouseClick(training.samples_empty.link, Qt.MouseButton.LeftButton)  # would start a second import
        training.import_folder()  # as Space on the link, or a click before it turned off, would
        training.add_ok()
        qtbot.waitUntil(lambda: training._bg is None, timeout=60000)
        after = _last(trained_ctx, "sample.import")["after"]
        seen.append((name, len(trained_ctx.samples(name)), after["cancelled"], link_on))
    _records_with_overlays(trained_ctx, ng_board, tmp_path / "overlays")
    win.navigate("Logs & Export")
    logs.export_overlays()
    qtbot.waitUntil(logs.busy.cancel_button.isVisible, timeout=30000)
    logs.d_from.setDate(QDate(2001, 1, 1))
    logs.d_to.setDate(QDate(2001, 1, 2))
    qtbot.mouseClick(_button(logs, "Filter"), Qt.MouseButton.LeftButton)  # no records on these days
    seen.append(("Logs", logs.empty.isVisible(), _on_top(logs.busy)))
    qtbot.waitUntil(lambda: logs._bg is None, timeout=60000)
    expected = [(True, [True, True]), ("EMPTY-OK", N, False, False), ("EMPTY-FOLDER", N, False, False)]
    assert seen == [*expected, ("Logs", True, [True, True])] and _copied(pickers) == N and not dialogs
