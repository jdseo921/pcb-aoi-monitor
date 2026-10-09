"""REQ-TRN-001 (stage S31): Training's import sheet, docs/sketches/training-import.md. The files picked or found in a
folder are listed inline, never in a dialog over the picker, each with its label, defect type and view, set for all
and per row; Import waits for every NG file's type, and the files not imported are listed with their codes."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import QComboBox, QTableWidget
from pytestqt.qtbot import QtBot

from aoi.core.sample_import import ImportFile, ImportReport
from aoi.defects import names
from aoi.errors import AoiError
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
    Enter sends the files; while they import nothing can be changed. The report shows each file copied, skipped or
    refused with its code, or not imported; Import again sends only those not in, Copy List copies every row with what
    happened; a file stopped at by a plain error shows AOI-SET-007, as the error dialog does; Esc closes the sheet."""
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
    sheet.open_files([a, c, d, e], Path("/src"))
    qtbot.waitExposed(sheet)
    qtbot.waitUntil(sheet.isActiveWindow)  # its keys work in the window that has the focus
    assert sheet.title() == "Import 4 file(s)" and _rows(sheet.table) == [
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

    sheet.type_box.setCurrentIndex(sheet.type_box.findData("Solder Ball"))
    sheet.type_box.activated.emit(sheet.type_box.currentIndex())  # for every NG file, c's folder type too
    qtbot.mouseClick(sheet.views.button(1), Qt.MouseButton.LeftButton)  # Side for all
    _pick(qtbot, sheet.table, 1, TYPE, "Solder Bridge")
    _pick(qtbot, sheet.table, 3, LABEL, "NG")  # e: NG, so it needs a type again
    assert not sheet.btn_import.isEnabled()
    _pick(qtbot, sheet.table, 3, TYPE, "Scratch")
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

    skipped = AoiError("AOI-TRN-015", path=d.path, board_model="B")
    sheet.show_report(ImportReport(added=[a, c], refused=[(d, skipped)], left=[e]), lambda x: f"{x.code} {x.what}")
    assert [r[STATUS] for r in _rows(sheet.table)] == ["copied", "copied", "AOI-TRN-015 Image already imported",
                                                      "not imported"]  # fmt: skip
    assert sheet.note.text() == "2 imported · 2 not imported" and sheet.btn_cancel.text() == "Close"
    assert sheet.btn_import.isEnabled() and not cell_item(sheet.table, 0, LABEL).flags() & Qt.ItemFlag.ItemIsEditable
    qtbot.mouseClick(sheet.btn_copy, Qt.MouseButton.LeftButton)
    copied = [line.split("\t") for line in QGuiApplication.clipboard().text().splitlines()]
    said = ["AOI-TRN-015 Image already imported", f"{skipped.code} {skipped.what}"]
    assert len(copied) == 4 and copied[2] == [d.path, "NG", "Solder Ball", "Side", *said], copied
    qtbot.mouseClick(sheet.btn_import, Qt.MouseButton.LeftButton)
    assert sent[1] == [e], "Import again sends only the files not in"
    sheet.show_report(ImportReport(refused=[(e, AoiError("AOI-TRN-016", path=e.path))]), lambda x: x.code)
    assert sheet.note.text() == "Nothing to import: every file was refused (see the list)."
    qtbot.mouseClick(sheet.btn_import, Qt.MouseButton.LeftButton)
    sheet.show_report(ImportReport(stopped=(e, OSError("the drive went away"))), lambda x: x.code)
    assert cell_text(sheet.table, 3, STATUS) == "AOI-SET-007 Unexpected error", "a plain error as its dialog says it"
    assert (
        sheet.note.text() == "0 imported · 1 not imported"
        and cell_item(sheet.table, 3, STATUS).toolTip() == "AOI-SET-007"
    )
    qtbot.keyClick(sheet.table, Qt.Key.Key_Escape)
    assert closed == [True]
