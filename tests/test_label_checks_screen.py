"""REQ-TRN-004 on screen (Datasets stage, 1 of 4): Training's samples table names each image's labeller and checker,
and Check Label records a second user's check of the images selected. Under ADR 0002, until sign-in ships, the
second user is a second name picked in the header."""

from __future__ import annotations

import shutil
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from pytestqt.qtbot import QtBot

from aoi.core.imaging import list_images
from aoi.core.labels import DefectBox
from aoi.core.services import AppContext
from aoi.ui.pages.base import cell_text
from aoi.ui.pages.training import TrainingPage
from tests.test_label_editor import _page, _select, _wait
from tests.test_req_done_in_v01 import BOARD

COLUMNS = ["ID", "Label", "Defect type", "View", "Labelled", "Checked", "File"]
BOX = [DefectBox(10, 10, 24, 24, "Scratch")]


def _rows(page: TrainingPage) -> dict[str, list[str]]:
    """The samples table's rows by file name, each as its cells read."""
    cols = range(page.samples.columnCount())
    rows = [[cell_text(page.samples, r, c) for c in cols] for r in range(page.samples.rowCount())]
    return {row[-1]: row for row in rows}


def _return(page: TrainingPage) -> None:
    """Return typed in the samples table, the key of Check Label (labels sketch)."""
    page.samples.setFocus()
    QTest.keyClick(page.samples, Qt.Key.Key_Return)
    _wait(page)


def test_req_trn_004_check_label_by_a_second_user(qtbot: QtBot, trained_ctx: AppContext) -> None:
    """The table names each image's labeller and checker. Check Label (Return) is off for the user who labelled the
    images selected, saying so in its tooltip; signed in as another user it checks each selected image that can be
    checked, leaves the others as they are and says why, and the Checked column then names the checker. Return typed in
    a spin box or a drop-down list checks nothing."""
    ctx = trained_ctx  # the import labelled every sample as the engineer
    ng, bare = ctx.samples(BOARD, "NG")[:2]
    ok = ctx.samples(BOARD, "OK")[0]
    ctx.set_boxes(ng["uuid"], BOX)
    page = _page(qtbot, ctx)
    header = [page.samples.horizontalHeaderItem(c).text() for c in range(page.samples.columnCount())]
    assert header == COLUMNS
    name = Path(ng["path"]).name
    assert _rows(page)[name][4:6] == ["engineer", "—"]
    _select(page, ng["id"])
    _wait(page)
    assert not page.btn_check.isEnabled() and page.btn_check.toolTip() == "You labelled this image"
    page.shell.set_user("admin")
    _select(page, ng["id"], bare["id"], ok["id"])
    _wait(page)
    assert page.btn_check.isEnabled() and page.act_check.shortcut().toString() == "Return"
    page.epochs.setFocus()
    QTest.keyClick(page.epochs, Qt.Key.Key_Return)
    page.dataset_version.setFocus()
    QTest.keyClick(page.dataset_version, Qt.Key.Key_Return)
    _wait(page)
    assert ctx.audit_entries(action="label.check") == [], "Return in a field is the field's"
    _return(page)
    rows = _rows(page)
    assert rows[name][5] == "admin ✓" and rows[Path(ok["path"]).name][5] == "admin ✓"
    assert rows[Path(bare["path"]).name][5] == "—"
    checked = {e["object_uuid"] for e in ctx.audit_entries(action="label.check")}
    assert checked == {ng["uuid"], ok["uuid"]}
    status = page.shell.statusBar().currentMessage()
    left = Path(bare["path"]).name
    assert status == f"Checked 2 label(s); 1 left unchecked, {left} first: Draw its defect boxes first"
    _select(page, ng["id"])
    _wait(page)
    assert not page.btn_check.isEnabled() and page.btn_check.toolTip() == "Checked by admin"
    _select(page, bare["id"])
    _wait(page)
    assert not page.btn_check.isEnabled() and page.btn_check.toolTip() == "Draw its defect boxes first"


def test_req_trn_004_enter_in_the_import_sheet_imports(
    qtbot: QtBot, trained_ctx: AppContext, synthetic_dataset: Path, tmp_path: Path
) -> None:
    """With the import sheet open and an image the user can check selected, Enter typed in the sheet imports, as the
    sheet's Import, and checks nothing; typed in the samples table it checks the image. Neither meets the other as an
    ambiguous shortcut, which Qt would act on neither of."""
    ctx = trained_ctx
    ng = ctx.samples(BOARD, "NG")[0]
    ctx.set_boxes(ng["uuid"], BOX)
    folder = tmp_path / "src" / "ok"
    folder.mkdir(parents=True)
    shutil.copy(list_images(synthetic_dataset / "test" / "ok")[0], folder / "new.png")
    page = _page(qtbot, ctx)
    page.shell.set_user("admin")
    _select(page, ng["id"])
    _wait(page)
    page.import_from(str(folder.parent))
    assert page.sheet.isVisible() and page.btn_check.isEnabled()
    QTest.keyClick(page.sheet.table, Qt.Key.Key_Return)
    assert page.sheet.running, "Enter in the sheet imports"
    qtbot.waitUntil(lambda: page._bg is None and not page.sheet.running, timeout=60000)
    assert ctx.audit_entries(action="label.check") == []
    assert any(Path(s["path"]).name.startswith("new_") for s in ctx.samples(BOARD)), "imported, its name made unique"
    _select(page, ng["id"])
    _return(page)
    assert {e["object_uuid"] for e in ctx.audit_entries(action="label.check")} == {ng["uuid"]}
