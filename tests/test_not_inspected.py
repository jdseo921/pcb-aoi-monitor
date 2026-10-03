"""A board that could not be judged never shows the verdict of the board shown before it (REQ-INSP-002, #182): the
banner reads "Not inspected" with a shape in the neutral colour, and that board's picture, defects and verdict go."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest
from PySide6.QtWidgets import QFileDialog
from pytestqt.qtbot import QtBot

from aoi.core.services import AppContext
from aoi.ui import theme
from aoi.ui.pages.base import cell_item
from aoi.ui.pages.compare import ComparePage
from aoi.ui.pages.model_test import ModelTestPage
from tests.test_req_done_in_v01 import _window

NOT_INSPECTED = f"{theme.VERDICT_SHAPES['INFO']} Not inspected"


def test_req_insp_002_an_unreadable_board_never_shows_the_verdict_before(
    qtbot: QtBot,
    trained_ctx: AppContext,
    synthetic_dataset: Path,
    tmp_path: Path,
    dialogs: list[tuple[str, str]],
) -> None:
    """Inspection, as an Operator: an OK board, a file that is no image, another board. The banner said "✓ OK" beside
    "board_0042.png · not inspected", over the OK board's picture, and Compare… opened the OK board's record. Now the
    banner says Not inspected, the picture and the defect list go, and the page says which board was not inspected,
    why, and that Next Board carries on; Compare's Use Last Inspected still opens the OK board, under its own name."""
    ok = sorted(synthetic_dataset.glob("test/ok/*.png"))[0]
    bad = tmp_path / "board_0042.png"
    bad.write_bytes(b"not an image at all")
    win = _window(qtbot, trained_ctx, "Operator")
    win.navigate("Inspection")
    page = win.pages["Inspection"]
    page._set_queue([ok, bad, ok])
    page.next_board()
    qtbot.waitUntil(lambda: page.last is not None and page.worker is None, timeout=30000)
    assert page.verdict.text() == theme.verdict_label("OK") and page.view._pix is not None
    page.next_board()
    qtbot.waitUntil(lambda: bool(dialogs) and page.worker is None, timeout=30000)
    print("after board 2:", repr(page.verdict.text()), "|", page.summary.text(), "|", dialogs[0][0])
    assert dialogs[0][0].startswith("AOI-INSP-004")
    assert page.verdict.text() == NOT_INSPECTED, "the banner shows the verdict of the board before"
    assert page.verdict.styleSheet() == theme.verdict_style("INFO")
    assert page.view._pix is None and page.table.rowCount() == 0
    assert page.last is None and page.last_path is None and page.last_id is None
    assert not page.act_save.isEnabled() and page.summary.text() == "board_0042.png  ·  not inspected"
    assert page.empty.isVisible() and page.empty.heading.text() == "board_0042.png was not inspected"
    assert page.empty.sentence.text().startswith("AOI-INSP-004 ") and "Next Board" in page.empty.sentence.text()
    assert page.empty.link.text() == "Next Board ›"
    page.open_compare()  # the board before is not opened under this one's name
    assert win.stack.currentWidget() is page
    win.navigate("Compare")
    win.navigate("Inspection")
    assert page.empty.isVisible(), "the not-inspected state stays when the page is shown again"
    compare = win.pages["Compare"]
    compare.use_last()
    assert compare.test_label.text() == f"Test board: {ok.name} (stored result)"


def test_req_insp_002_an_unreadable_last_board_offers_load_images(
    qtbot: QtBot,
    trained_ctx: AppContext,
    synthetic_dataset: Path,
    tmp_path: Path,
    dialogs: list[tuple[str, str]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Inspection, as an Operator: the last board of the queue is a file that is no image. The empty state said "Press
    Next Board to carry on with the queue." with Next Board ›, which only said "End of queue"; now it says no board is
    left and offers Load Images…, and the boards loaded through it can be inspected (REQ-SET-019)."""
    bad = tmp_path / "board_0042.png"
    bad.write_bytes(b"not an image at all")
    win = _window(qtbot, trained_ctx, "Operator")
    win.navigate("Inspection")
    page = win.pages["Inspection"]
    page._set_queue([bad])
    page.next_board()
    qtbot.waitUntil(lambda: bool(dialogs) and page.worker is None, timeout=30000)
    print("last board:", repr(page.empty.sentence.text()), "|", repr(page.empty.link.text()))
    assert page.empty.isVisible() and page.empty.heading.text() == "board_0042.png was not inspected"
    last = "No board is left in the queue. Load Images… or Load Folder… to queue more boards."
    assert "Next Board" not in page.empty.sentence.text(), "the empty state offers Next Board at the end of the queue"
    assert page.empty.sentence.text().endswith(last)
    assert page.empty.link.isVisible() and page.empty.link.text() == "Load Images…"
    ok = sorted(synthetic_dataset.glob("test/ok/*.png"))[0]
    monkeypatch.setattr(QFileDialog, "getOpenFileNames", staticmethod(lambda *a, **k: ([str(ok)], "")))
    page.empty.link.click()
    assert page.queue == [ok] and page.skipped is None and page.act_next.isEnabled()


def test_req_insp_002_a_failed_preview_never_shows_the_row_before(
    qtbot: QtBot,
    trained_ctx: AppContext,
    synthetic_dataset: Path,
    ng_board: Path,
    tmp_path: Path,
    dialogs: list[tuple[str, str]],
) -> None:
    """AI Model Test: the NG row previewed, then the OK row whose file was moved away. The banner kept "✗ NG" over the
    NG board beside the OK row; now it says Not inspected and the picture goes."""
    folder = tmp_path / "validation"
    (folder / "ok").mkdir(parents=True)
    (folder / "ng").mkdir()
    shutil.copy(sorted(synthetic_dataset.glob("test/ok/*.png"))[0], folder / "ok" / "ok_board.png")
    shutil.copy(ng_board, folder / "ng" / "ng_board.png")
    win = _window(qtbot, trained_ctx, "Engineer")
    win.navigate("AI Model Test")
    page = win.pages["AI Model Test"]
    assert isinstance(page, ModelTestPage)
    page.folder = str(folder)
    page.run()
    qtbot.waitUntil(lambda: bool(page.rows) and page.btn_run.isEnabled(), timeout=60000)
    row = {Path(cell_item(page.table, i, 0).toolTip()).name: i for i in range(page.table.rowCount())}
    page.table.selectRow(row["ng_board.png"])
    qtbot.waitUntil(lambda: page._bg is None and page.view._pix is not None, timeout=30000)
    assert page.preview_verdict.text() == theme.verdict_label("NG")
    (folder / "ok" / "ok_board.png").unlink()
    page.table.selectRow(row["ok_board.png"])
    qtbot.waitUntil(lambda: page._bg is None and bool(dialogs), timeout=30000)
    print("preview banner:", repr(page.preview_verdict.text()), "| dialog:", dialogs[0][0])
    assert dialogs[0][0].startswith("AOI-INSP-001")
    assert page.preview_verdict.text() == NOT_INSPECTED, "the banner shows the row before"
    assert page.preview_verdict.styleSheet() == theme.verdict_style("INFO", big=False)
    assert page.view._pix is None


def test_req_insp_002_compare_shows_no_verdict_beside_a_board_it_could_not_read(
    qtbot: QtBot, trained_ctx: AppContext, ng_board: Path, tmp_path: Path, dialogs: list[tuple[str, str]]
) -> None:
    """Compare: an NG board judged, then a test image that is no image. The banner, the decision table and the NG
    board's picture stayed under the other board's name; now they go, as on Cancel, and Re-evaluate is one click
    away."""
    win = _window(qtbot, trained_ctx, "Engineer")
    win.navigate("Compare")
    page = win.pages["Compare"]
    assert isinstance(page, ComparePage)
    page.set_test(str(ng_board))
    qtbot.waitUntil(lambda: page._bg is None and page.res is not None, timeout=30000)
    assert page.verdict.text() == theme.verdict_label("NG") and page.metrics.rowCount() > 0
    bad = tmp_path / "board_0042.png"
    bad.write_bytes(b"not an image at all")
    page.set_test(str(bad))
    qtbot.waitUntil(lambda: page._bg is None and bool(dialogs), timeout=30000)
    print("banner:", repr(page.verdict.text()), "| rows:", page.metrics.rowCount(), "| dialog:", dialogs[0][0])
    assert dialogs[0][0].startswith("AOI-INSP-004")
    assert page.verdict.text() == NOT_INSPECTED, "the banner shows the board before"
    assert page.res is None and page.metrics.rowCount() == 0 and page.why.toPlainText() == ""
    assert page.test_view._pix is None and page.test_label.text() == "Test board: board_0042.png"
    assert page.test_empty.isVisible() and page.test_empty.heading.text() == "board_0042.png was not inspected"
    assert page.test_empty.sentence.text().startswith("AOI-INSP-004 ")
    assert page.test_empty.link.text() == "Re-evaluate ›"
