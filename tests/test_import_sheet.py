"""REQ-TRN-001 (stage S31): Training's import sheet, docs/sketches/training-import.md. The files picked or found in a
folder are listed inline, never in a dialog over the picker, each with its label, defect type and view, set for all
and per row; Import waits for every NG file's type, and the files not imported are listed with their codes."""

from __future__ import annotations

import shutil
import threading
from pathlib import Path

import pytest
from PySide6.QtCore import Qt
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import QApplication, QComboBox, QFileDialog, QPushButton, QTableWidget
from pytestqt.qtbot import QtBot

from aoi.core.imaging import list_images
from aoi.core.sample_import import ImportFile, ImportReport
from aoi.core.services import AppContext
from aoi.data import atomic
from aoi.defects import names
from aoi.errors import AoiError
from aoi.ui.main_window import MainWindow
from aoi.ui.pages.base import cell_item, cell_text
from aoi.ui.pages.training_import import FILE, LABEL, STATUS, TYPE, VIEW, ImportSheet


def _rows(table: QTableWidget) -> list[list[str]]:
    """The sheet's rows: File, Label, Defect type, View, Status."""
    return [[cell_text(table, r, c) for c in range(STATUS + 1)] for r in range(table.rowCount())]


def _pick(qtbot: QtBot, table: QTableWidget, row: int, column: int, key: str) -> None:
    """A row's own value, as a user sets it: the cell made current, F2, the value picked in its drop-down, then Esc."""
    table.setCurrentCell(row, column)
    qtbot.keyClick(table, Qt.Key.Key_F2)
    (box,) = [w for w in table.viewport().findChildren(QComboBox) if w.isVisible()]  # a closed one waits to go
    box.setCurrentIndex(box.findData(key))
    box.activated.emit(box.currentIndex())  # as a tap in its list or an arrow key: kept at once, Enter is Import
    qtbot.keyClick(box, Qt.Key.Key_Escape)


def test_req_trn_001_the_sheet_takes_each_file_with_its_view_and_an_ng_file_with_one_of_the_33_types(
    qtbot: QtBot,
) -> None:
    """Opened on a folder's files: OK, NG typed by its folder, NG with no type, and no label. Import is off while an
    NG file has no type; the type picker holds the 33 types alone (no "Unknown", no "Anomaly"), none picked. The view,
    label and type for all, then a row's own by F2; an OK file's type, a file's name and its status are not picked.
    The note says how many NG files need a type until none does. Enter sends the files; while they import nothing can
    be changed. The report shows each file copied, skipped or refused with its code, or not imported, the sheet's
    counts in the note, and the coded line (what happened and what to do) of the row the keys move to under the table,
    gone once a change to the row, its own or for all, makes it ready again; Import again sends only those not in, and
    Close reads Cancel again; Copy List copies every row with what happened; a file stopped at by a plain error shows
    AOI-SET-007, as the error dialog does; Esc closes the sheet. A file's name shows its end, its whole path in its
    accessible text."""
    sent: list[list[ImportFile]] = []
    closed: list[bool] = []
    sheet = ImportSheet(sent.append, lambda: closed.append(True))
    qtbot.addWidget(sheet)
    a, c, d, e = (
        ImportFile("/src/ok/a.png", "OK"),
        ImportFile("/src/ng/Solder_Bridge/c.png", "NG", "Solder Bridge"),
        ImportFile("/src/ng/d.png", "NG"),
        ImportFile("/src/loose/e.png", None),
    )
    sheet.open_files("B", [a, c, d, e], Path("/src"))
    qtbot.waitExposed(sheet)
    qtbot.waitUntil(sheet.isActiveWindow)  # its keys work in the window that has the focus
    assert sheet.title() == "Import 4 file(s) into B" and _rows(sheet.table) == [
        ["ok/a.png", "OK", "—", "Top", "ready"],
        ["ng/Solder_Bridge/c.png", "NG", "Solder Bridge", "Top", "ready"],
        ["ng/d.png", "NG", "pick a type", "Top", "waiting: type needed"],
        ["loose/e.png", "—", "—", "Top", "unsorted: pick a label"],
    ]
    assert not sheet.btn_import.isEnabled() and sheet.note.text() == "1 NG file(s) need a defect type"
    assert sheet.views.checkedId() == 0 and sheet.labels.checkedId() == -1, "Top for all; a mixed batch, no label"
    kinds = [sheet.type_box.itemData(i) for i in range(sheet.type_box.count())]
    assert kinds == names() and len(kinds) == 33 and sheet.type_box.currentIndex() == -1
    sheet.category.setCurrentIndex(sheet.category.findData("Solder"))
    assert {sheet.type_box.itemData(i) for i in range(sheet.type_box.count())} < set(names())
    editable = [[bool(cell_item(sheet.table, r, col).flags() & Qt.ItemFlag.ItemIsEditable) for col in range(5)]
                for r in range(4)]  # fmt: skip
    assert [r[FILE] or r[STATUS] for r in editable] == [False] * 4
    assert [r[TYPE] for r in editable] == [False, True, True, False]
    assert sheet.table.textElideMode() == Qt.TextElideMode.ElideLeft  # two names that differ near their end differ
    assert cell_item(sheet.table, 1, FILE).data(Qt.ItemDataRole.AccessibleTextRole) == c.path

    sheet.type_box.setCurrentIndex(sheet.type_box.findData("Solder Ball"))
    sheet.type_box.activated.emit(sheet.type_box.currentIndex())  # for every NG file, c's folder type too
    assert sheet.note.text() == ""
    qtbot.mouseClick(sheet.views.button(1), Qt.MouseButton.LeftButton)  # Side for all
    _pick(qtbot, sheet.table, 1, TYPE, "Solder Bridge")
    _pick(qtbot, sheet.table, 3, LABEL, "NG")  # e: NG, so it needs a type again
    assert not sheet.btn_import.isEnabled() and sheet.note.text() == "1 NG file(s) need a defect type"
    _pick(qtbot, sheet.table, 3, TYPE, "Scratch")
    assert sheet.note.text() == ""
    _pick(qtbot, sheet.table, 0, VIEW, "Bottom")
    assert [(f.label, f.defect_type, f.side) for f in (a, c, d, e)] == [
        ("OK", None, "Bottom"),
        ("NG", "Solder Bridge", "Side"),
        ("NG", "Solder Ball", "Side"),
        ("NG", "Scratch", "Side"),
    ]
    qtbot.keyClick(sheet.table, Qt.Key.Key_Return)
    assert sent == [[a, c, d, e]] and sheet.running and not sheet.btn_import.isEnabled()
    assert not any(w.isEnabled() for w in (*sheet.views.buttons(), *sheet.labels.buttons(), sheet.type_box))
    assert sheet.table.editTriggers() == QTableWidget.EditTrigger.NoEditTriggers

    x = sent[0]  # what the pool imports: copies of the rows, its report shown on the rows they were made from
    skipped = AoiError("AOI-TRN-015", path=d.path, board_model="B", sample="d_1.png", label="NG")
    report = ImportReport(added=[x[0], x[1]], refused=[(x[2], skipped)], left=[x[3]])
    sheet.show_report(report, lambda x: f"{x.code} {x.what}")
    assert [r[STATUS] for r in _rows(sheet.table)] == ["copied", "copied", "AOI-TRN-015 Image already imported",
                                                      "not imported"]  # fmt: skip
    assert sheet.note.text() == "2 imported · 1 already imported · 1 not imported"
    assert sheet.btn_cancel.text() == "Close" and not sheet.why.isVisible()
    sheet.table.setCurrentCell(0, FILE)
    for key, shown in ((Qt.Key.Key_Down, ""), (Qt.Key.Key_Down, f"{skipped.code} {skipped.what}"), (Qt.Key.Key_Up, "")):
        qtbot.keyClick(sheet.table, key)  # the row the keys move to: its coded line, which no tooltip has to show
        assert (sheet.why.text(), sheet.why.isVisible()) == (shown, bool(shown)), sheet.table.currentRow()
    assert sheet.btn_import.isEnabled() and not cell_item(sheet.table, 0, LABEL).flags() & Qt.ItemFlag.ItemIsEditable
    qtbot.mouseClick(sheet.btn_copy, Qt.MouseButton.LeftButton)
    copied = [line.split("\t") for line in QGuiApplication.clipboard().text().splitlines()]
    said = ["AOI-TRN-015 Image already imported", f"{skipped.code} {skipped.what}"]
    assert len(copied) == 4 and copied[2] == [d.path, "NG", "Solder Ball", "Side", *said], copied
    qtbot.mouseClick(sheet.btn_import, Qt.MouseButton.LeftButton)
    assert sent[1] == [e] and sheet.btn_cancel.text() == "Cancel", "Import again sends only the files not in"
    sheet.show_report(ImportReport(refused=[(sent[1][0], AoiError("AOI-TRN-016", path=e.path))]), lambda x: x.code)
    assert sheet.note.text() == "2 imported · 1 already imported · 1 not imported", "the sheet's, not this pass's"
    sheet.table.setCurrentCell(3, FILE)
    assert (sheet.why.text(), sheet.why.isVisible()) == ("AOI-TRN-016", True)
    sheet.set_cell(3, VIEW, "Bottom")  # the row is ready again: its coded line goes with its status
    assert (cell_text(sheet.table, 3, STATUS), sheet.why.text(), sheet.why.isVisible()) == ("ready", "", False)
    qtbot.mouseClick(sheet.btn_import, Qt.MouseButton.LeftButton)
    sheet.show_report(ImportReport(stopped=(sent[2][0], OSError("the drive went away"))), lambda x: x.code)
    assert cell_text(sheet.table, 3, STATUS) == "AOI-SET-007 Unexpected error", "a plain error as its dialog says it"
    assert cell_item(sheet.table, 3, STATUS).toolTip() == sheet.why.text() == "AOI-SET-007"
    qtbot.mouseClick(sheet.views.button(0), Qt.MouseButton.LeftButton)  # Top for all: the same for a change for all
    assert (cell_text(sheet.table, 3, STATUS), sheet.why.text(), sheet.why.isVisible()) == ("ready", "", False)
    qtbot.keyClick(sheet.table, Qt.Key.Key_Escape)
    assert closed == [True]


def test_req_trn_001_training_opens_the_sheet_inline_and_imports_on_the_pool(
    qtbot: QtBot,
    ctx: AppContext,
    synthetic_dataset: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    dialogs: list[tuple[str, str]],
) -> None:
    """Import Folder… opens the sheet inline above the samples table with no dialog; while it is open Import is the
    page's one blue primary and Start Training a plain button. Enter imports on the pool: the samples table shows the
    files imported, the status line counts them, and the file with no label is listed with AOI-TRN-016. Esc closes the
    sheet and Start Training is the primary again. Ctrl+N (Add NG Images…) opens it with NG for all and Import off
    until a type is picked, and another board model in the header closes it."""
    oks, ngs = list_images(synthetic_dataset / "train" / "ok"), list_images(synthetic_dataset / "train" / "ng")
    folder = tmp_path / "src"
    for src, name in ((oks[0], "ok/a.png"), (ngs[0], "ng/solder_bridge/c.png"), (oks[1], "loose/e.png")):
        (folder / name).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(src, folder / name)
    win = MainWindow(ctx)
    qtbot.addWidget(win)
    win.resize(1600, 900)
    win.show()
    qtbot.waitExposed(win)
    win.set_user("engineer")
    win._on_board_model("NEWB")
    win.navigate("Training")
    qtbot.waitUntil(win.isActiveWindow)
    page = win.pages["Training"]
    sheet = page.sheet
    page.import_from(str(folder))
    assert sheet.isVisible() and QApplication.activeModalWidget() is None
    primaries = [b for b in page.findChildren(QPushButton) if b.objectName() == "primary"]
    assert primaries == [sheet.btn_import], [b.text() for b in primaries]
    qtbot.keyClick(sheet.table, Qt.Key.Key_Return)
    qtbot.waitUntil(lambda: page._bg is None and not sheet.running, timeout=60000)
    assert [r[STATUS] for r in _rows(sheet.table)] == ["AOI-TRN-016 Image has no label", "copied", "copied"]
    assert win.statusBar().currentMessage() == "Imported 1 OK and 1 NG images; 1 not imported (see the list)"
    stored = [(r["label"], r["defect_type"], r["side"]) for r in ctx.samples("NEWB")]
    assert stored == [("NG", "Solder Bridge", "Top"), ("OK", None, "Top")] and page.samples.rowCount() == 2
    qtbot.keyClick(sheet.table, Qt.Key.Key_Escape)
    assert not sheet.isVisible() and page.btn_train.objectName() == "primary" and not sheet.btn_import.objectName()

    monkeypatch.setattr(QFileDialog, "getOpenFileNames", staticmethod(lambda *a, **k: ([str(ngs[1])], "")))
    qtbot.keyClick(page.samples, Qt.Key.Key_N, Qt.KeyboardModifier.ControlModifier)
    assert sheet.isVisible() and sheet.labels.checkedId() == 1 and not sheet.btn_import.isEnabled()
    win._on_board_model("OTHER")
    assert not sheet.isVisible() and not dialogs


def test_req_trn_001_the_pool_imports_copies_of_the_rows_as_they_read_at_import(qtbot: QtBot) -> None:
    """Import with a row's drop-down still open keeps that pick first and closes the drop-down, so each file goes as
    its row reads; the pool gets copies of the rows, and while they import nothing reaches them (set_cell does nothing
    then). The report comes back on the copies and shows on the rows they were made from. "Nothing to import: every
    file was refused" is said only when every file of the sheet was, and a sheet of images already imported says so
    in its own words."""
    sent: list[list[ImportFile]] = []
    sheet = ImportSheet(sent.append, lambda: None)
    qtbot.addWidget(sheet)
    a, b = ImportFile("/s/ok/a.png", "OK"), ImportFile("/s/ok/b.png", "OK")
    sheet.open_files("A", [a, b])
    qtbot.waitExposed(sheet)
    sheet.table.setCurrentCell(1, VIEW)
    qtbot.keyClick(sheet.table, Qt.Key.Key_F2)
    (box,) = [w for w in sheet.table.viewport().findChildren(QComboBox) if w.isVisible()]
    box.setCurrentIndex(box.findData("Bottom"))  # picked in the open drop-down, not yet kept
    sheet.start()
    assert not [w for w in sheet.table.viewport().findChildren(QComboBox) if w.isVisible()], "closed at Import"
    assert sent == [[a, b]] and b.side == "Bottom" and not {id(f) for f in sent[0]} & {id(a), id(b)}
    sheet.set_cell(0, LABEL, "NG")  # as a drop-down left open would, while the files import
    assert (a.label, sent[0][0].label, cell_text(sheet.table, 0, LABEL)) == ("OK", "OK", "OK")
    refused = AoiError("AOI-TRN-016", path=a.path)
    sheet.show_report(ImportReport(refused=[(sent[0][0], refused), (sent[0][1], refused)]), lambda x: x.code)
    assert sheet.note.text() == "Nothing to import: every file was refused (see the list)."
    skipped = AoiError("AOI-TRN-015", path=a.path, board_model="A", sample="a_1.png", label="OK")
    sheet.start()
    sheet.show_report(ImportReport(refused=[(sent[1][0], skipped), (sent[1][1], skipped)]), lambda x: x.code)
    assert sheet.note.text() == "Nothing to import: every file is already imported."


def test_req_trn_001_the_sheet_imports_into_the_board_model_it_was_opened_for(
    qtbot: QtBot, ctx: AppContext, synthetic_dataset: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    dialogs: list[tuple[str, str]],
) -> None:  # fmt: skip
    """The review's probe: the sheet names the board model it was opened for, and its Import goes there, never to the
    header's. Another board model chosen in the header while an import runs lets that import end and then closes the
    sheet, so Import again cannot send the rest elsewhere; an idle sheet closes at once. A folder with no image opens no
    sheet, and the status line says so."""
    folder = tmp_path / "src"
    oks = list_images(synthetic_dataset / "train" / "ok")[:2]
    for src, name in ((oks[0], "ok/a.png"), (oks[1], "loose/e.png")):
        (folder / name).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(src, folder / name)
    for name in ("A", "B"):
        ctx.ensure_board_model(name)
    reached, go = threading.Event(), threading.Event()
    copy = atomic.copy_file

    def held(src: str | Path, dst: str | Path) -> None:
        reached.set()
        assert go.wait(30)
        copy(src, dst)

    monkeypatch.setattr(atomic, "copy_file", held)
    win = MainWindow(ctx)
    qtbot.addWidget(win)
    win.show()
    win.set_user("engineer")
    win._reload_board_models("A")
    win.navigate("Training")
    page = win.pages["Training"]
    page.import_from(str(folder))
    page.sheet.btn_import.click()
    qtbot.waitUntil(reached.is_set, timeout=30000)
    win._reload_board_models("B")  # while A's import runs
    assert page.sheet.isVisible() and page.sheet.running, "the import goes on"
    go.set()
    qtbot.waitUntil(lambda: page._bg is None, timeout=30000)
    assert not page.sheet.isVisible() and page.btn_train.objectName() == "primary", "closed once it ended"

    def names() -> dict[str, list[str]]:
        return {bm: [Path(r["path"]).name[0] for r in ctx.samples(bm)] for bm in ("A", "B")}

    assert names() == {"A": ["a"], "B": []}
    page.import_from(str(folder))
    assert page.sheet.title() == "Import 2 file(s) into B"
    page.sheet.set_cell(0, LABEL, "OK")  # loose/e.png
    win.board_model = "A"  # the header read by the page with no change sent to it (white box)
    page.sheet.btn_import.click()
    qtbot.waitUntil(lambda: page._bg is None, timeout=30000)
    assert names() == {"A": ["a"], "B": ["e", "a"]} and not dialogs
    (folder / "none").mkdir()
    win.board_model = "B"
    page.import_from(str(folder / "none"))
    assert not page.sheet.isVisible()
    assert win.statusBar().currentMessage() == f"No images in {folder / 'none'} or its sub-folders: nothing to import"
