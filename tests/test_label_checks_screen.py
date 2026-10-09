"""REQ-TRN-004 on screen (Datasets stage, 1 of 4): Training's samples table names each image's labeller and checker,
Check Label records a second user's check of the images selected, Draw OK Labels to Check draws 10 % of the OK labels
of each view for it, and the filter Unchecked lists what a freeze still needs checked. Under ADR 0002, until sign-in
ships, the second user is a second name picked in the header."""

from __future__ import annotations

import shutil
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
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


def _filter(page: TrainingPage, shown: str) -> None:
    page.filter.setCurrentIndex(page.filter.findData(shown))


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


def test_req_trn_004_draw_ok_labels_and_filter_unchecked(qtbot: QtBot, trained_ctx: AppContext) -> None:
    """Draw OK Labels to Check draws 10 % of the OK labels, rounded up, once, and the line over the table counts the
    checks a freeze needs; the filter shows All, OK, NG, UNSURE or Unchecked, the NG labels and drawn OK labels not yet
    checked. Once a second user has checked them all, the filter Unchecked is empty and says so, and the line ends with
    ✓."""
    ctx = trained_ctx
    oks, ngs = ctx.samples(BOARD, "OK"), ctx.samples(BOARD, "NG")
    ctx.set_label(oks[0]["uuid"], "UNSURE")
    for s in ngs:
        ctx.set_boxes(s["uuid"], BOX)
    page = _page(qtbot, ctx)
    n_ok, n_ng = len(oks) - 1, len(ngs)
    need = -(-n_ok // 10)
    assert page.checks_line.text() == (
        f"0 of {n_ng} NG labels checked · 0 of {need} OK labels checked (10 % of {n_ok}, none drawn yet)"
    )
    shown = {"All": n_ok + n_ng + 1, "OK": n_ok, "NG": n_ng, "UNSURE": 1, "Unchecked": n_ng}
    for kind, n in shown.items():
        _filter(page, kind)
        assert page.samples.rowCount() == n, kind
    page.btn_draw.click()
    qtbot.waitUntil(lambda: len(ctx.audit_entries(action="label.draw")) == 1, timeout=10000)
    qtbot.waitUntil(lambda: page.samples.rowCount() == n_ng + need, timeout=10000)
    drawn = ctx.label_check_status(BOARD, "Top")["ok_drawn"]
    assert len(drawn) == need
    assert page.checks_line.text() == f"0 of {n_ng} NG labels checked · 0 of {need} OK labels checked (10 % of {n_ok})"
    page.btn_draw.click()
    qtbot.waitUntil(lambda: "enough" in page.shell.statusBar().currentMessage(), timeout=10000)
    assert page.shell.statusBar().currentMessage() == f"The OK labels drawn are enough: {need} of the {need} needed"
    assert len(ctx.audit_entries(action="label.draw")) == 1
    page.shell.set_user("admin")
    assert page.filter.currentData() == "Unchecked" and page.samples.rowCount() == n_ng + need
    page.samples.selectAll()
    _return(page)
    assert page.samples.rowCount() == 0 and page.samples_empty.isVisible()
    assert page.samples_empty.heading.text() == "Nothing left to check"
    assert page.checks_line.text() == (
        f"{n_ng} of {n_ng} NG labels checked · {need} of {need} OK labels checked (10 % of {n_ok}) ✓"
    )
    assert ctx.labels_ready_to_freeze(BOARD, "Top")
    QApplication.processEvents()
