"""Tests for the register rows marked Done in v0.1 (stage S06), so the trace matrix can prove them.

Each test is named for its row in docs/requirements/stage1.md and checks that row's acceptance criteria.
REQ-INSP-015 lives in tests/regression/test_regression_verdicts.py, where the regression set is.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from time import perf_counter

import pytest
from PySide6.QtCore import QPoint, QPointF, QRectF, Qt
from PySide6.QtGui import QWheelEvent
from PySide6.QtWidgets import QGraphicsRectItem, QPushButton

from aoi.config import resolve_device
from aoi.core.recipe import ROI, ROI_TYPES, Recipe
from aoi.core.services import AppContext
from aoi.ui.main_window import MainWindow

BOARD = "TINY"


def _window(qtbot, ctx: AppContext, role: str = "Engineer") -> MainWindow:
    win = MainWindow(ctx)
    qtbot.addWidget(win)
    win.resize(1600, 900)
    win.show()
    qtbot.waitExposed(win)
    win.set_role(role, role.lower())
    assert win.board_model == BOARD
    return win


def _inspect_one(qtbot, win: MainWindow, path: Path):
    page = win.pages["Inspection"]
    win.navigate("Inspection")
    page._set_queue([path])
    page.next_board()
    qtbot.waitUntil(lambda: page.last is not None, timeout=30000)
    return page


def test_req_insp_003_one_box_per_defect_and_the_file_is_unchanged(qtbot, trained_ctx, ng_board) -> None:
    before = hashlib.sha256(ng_board.read_bytes()).hexdigest()
    page = _inspect_one(qtbot, _window(qtbot, trained_ctx, "Operator"), ng_board)
    assert page.last.defects, "a board with a missing component yields at least one defect"
    boxes = [it.rect() for it in page.view._overlay_items if isinstance(it, QGraphicsRectItem)]
    assert boxes == [QRectF(d.x, d.y, d.w, d.h) for d in page.last.defects]
    assert hashlib.sha256(ng_board.read_bytes()).hexdigest() == before


def test_req_insp_004_columns_in_order_and_selecting_a_row_centres_its_box(qtbot, trained_ctx, ng_board) -> None:
    page = _inspect_one(qtbot, _window(qtbot, trained_ctx, "Operator"), ng_board)
    headers = [page.table.horizontalHeaderItem(i).text() for i in range(page.table.columnCount())]
    assert headers == ["No", "Type", "Score", "Side", "X", "Y"]
    assert page.table.rowCount() == len(page.last.defects)
    no = int(page.table.item(0, 0).text())
    d = next(d for d in page.last.defects if d.no == no)
    t0 = perf_counter()
    page.table.selectRow(0)
    qtbot.wait(1)  # let the view repaint once
    elapsed = perf_counter() - t0
    centre = page.view.mapToScene(page.view.viewport().rect().center())
    assert abs(centre.x() - (d.x + d.w / 2)) <= 2 and abs(centre.y() - (d.y + d.h / 2)) <= 2
    assert elapsed < 0.3, f"centring took {elapsed * 1000:.0f} ms"


def test_req_insp_016_six_step_cards_open_their_pages_and_show_status(qtbot, trained_ctx) -> None:
    win = _window(qtbot, trained_ctx)
    home = win.pages["Home"]
    buttons = [b for b in home.findChildren(QPushButton) if b.text().startswith("Open ")]
    assert len(buttons) == 6 == len(home.STEPS)
    for b, (_, name, _, target) in zip(buttons, home.STEPS, strict=True):
        win.navigate("Home")
        qtbot.mouseClick(b, Qt.LeftButton)
        assert win.stack.currentWidget() is win.pages[target], name
    win.navigate("Inspection")
    t0 = perf_counter()
    win.navigate("Home")
    elapsed = perf_counter() - t0
    status = {name: label.text() for name, label in home.status_labels.items()}
    assert all(status.values()), status
    assert status["Upload samples"].endswith("uploaded") and "Active model" in status["Self-train"]
    assert elapsed < 0.3, f"Home status took {elapsed * 1000:.0f} ms"


def test_req_cmp_001_linked_views_zoom_and_pan_together_within_1px(qtbot, trained_ctx, tiny_model) -> None:
    page = _window(qtbot, trained_ctx).pages["Compare"]
    page.ref_view.set_image(tiny_model.reference)
    page.test_view.set_image(tiny_model.reference)
    page.ref_view.wheelEvent(
        QWheelEvent(
            QPointF(10, 10),
            QPointF(10, 10),
            QPoint(),
            QPoint(0, 120),
            Qt.NoButton,
            Qt.NoModifier,
            Qt.NoScrollPhase,
            False,
        )
    )
    page.ref_view.resetTransform()  # 100 % zoom
    page.ref_view.horizontalScrollBar().setValue(137)
    page.ref_view.verticalScrollBar().setValue(91)
    assert page.test_view.transform() == page.ref_view.transform()
    a = page.ref_view.mapToScene(page.ref_view.viewport().rect().center())
    b = page.test_view.mapToScene(page.test_view.viewport().rect().center())
    assert abs(a.x() - b.x()) <= 1 and abs(a.y() - b.y()) <= 1


def test_req_cmp_006_any_stored_ok_sample_can_be_the_reference_and_metrics_recompute(qtbot, trained_ctx, ng_board):
    page = _window(qtbot, trained_ctx).pages["Compare"]
    page.set_test(str(ng_board))
    qtbot.waitUntil(lambda: page.res is not None, timeout=30000)  # the inspection runs on a pool thread (S17b)
    against_golden = dict(page.res.compare.metrics)
    assert page.ref_label.text() == "Reference: golden template"
    sample = trained_ctx.db.samples(BOARD, "OK")[0]["path"]
    first = page.res
    page.ref_override = sample  # what Reference… does after the file dialog
    page.run()
    qtbot.waitUntil(lambda: page.res is not first, timeout=30000)
    against_sample = page.res.compare.metrics
    assert page.ref_label.text() == f"Reference: {Path(sample).name}"
    assert against_sample["ssim"] != against_golden["ssim"]
    rows = {
        page.metrics.item(r, 0).text(): page.metrics.item(r, 2).data(Qt.DisplayRole)
        for r in range(page.metrics.rowCount())
    }
    assert rows["SSIM similarity"] == pytest.approx(against_sample["ssim"], abs=1e-4)


def test_req_rcp_002_five_roi_types_and_five_fields_save_and_reload(qtbot, trained_ctx) -> None:
    rois = [
        ROI(
            f"R{i}",
            t,
            x=10 * i,
            y=20 * i,
            w=30,
            h=40,
            ai_score=1.5 + i,
            height_min=0.1 * i,
            height_max=1.0 + i,
            volume_min=2.0 + i,
            volume_max=3.0 + i,
        )
        for i, t in enumerate(ROI_TYPES)
    ]
    assert [r.type for r in rois] == ["Presence", "Polarity", "Solder Bridge", "Height", "Anomaly"]
    rev = trained_ctx.save_recipe(Recipe(board_model=BOARD, rois=rois))
    loaded_rev, loaded = trained_ctx.recipe(BOARD)
    assert loaded_rev == rev and loaded.rois == rois
    page = _window(qtbot, trained_ctx).pages["Recipe Editor"]
    assert [page.r_type.itemText(i) for i in range(page.r_type.count())] == ROI_TYPES
    page.load()
    assert page.roi_table.rowCount() == 5
    page.roi_table.selectRow(3)
    assert (page.r_type.currentText(), page.r_hmin.value(), page.r_vmax.value()) == ("Height", 0.3, 6.0)


def test_req_set_002_auto_picks_cuda_when_present_and_cpu_otherwise(monkeypatch) -> None:
    import torch

    monkeypatch.setattr(torch.cuda, "is_available", lambda: True)
    assert resolve_device("auto") == "cuda" and resolve_device("cpu") == "cpu"
    monkeypatch.setattr(torch.cuda, "is_available", lambda: False)
    assert resolve_device("auto") == "cpu" and resolve_device("cuda") == "cpu"
