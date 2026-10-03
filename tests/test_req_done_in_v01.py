"""Tests for the register rows marked Done in v0.1 (stage S06), so the trace matrix can prove them.

Each test is named for its row in docs/requirements/stage1.md and checks that row's acceptance criteria. REQ-INSP-015's
check of every board lives in tests/regression/test_regression_verdicts.py, where the synthetic regression set is; that
set holds no WARN board, so the rule itself is tested here, on the engine's own verdict step.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from time import perf_counter

import cv2
import pytest
from PySide6.QtCore import QPoint, QPointF, QRectF, Qt
from PySide6.QtGui import QTransform, QWheelEvent
from PySide6.QtWidgets import QApplication, QFileDialog, QGraphicsRectItem, QMessageBox, QPushButton, QWidget
from pytestqt.qtbot import QtBot

from aoi.config import Settings, resolve_device
from aoi.core.compare import CompareResult, Region
from aoi.core.explain import explain
from aoi.core.imaging import list_images
from aoi.core.inspector import InspectionResult, Inspector, re_grade
from aoi.core.recipe import ROI, ROI_TYPES, Recipe
from aoi.core.services import AppContext
from aoi.errors import AoiError
from aoi.ui.main_window import MainWindow
from aoi.ui.pages.inspection import InspectionPage
from tests.conftest import TrainedModel, engineer

BOARD = "TINY"


def _window(qtbot: QtBot, ctx: AppContext, role: str = "Engineer") -> MainWindow:
    win = MainWindow(ctx)
    qtbot.addWidget(win)
    win.resize(1600, 900)
    win.show()
    qtbot.waitExposed(win)
    win.set_role(role, role.lower())
    assert win.board_model == BOARD
    return win


def _inspect_one(qtbot: QtBot, win: MainWindow, path: Path) -> InspectionPage:
    page = win.pages["Inspection"]
    win.navigate("Inspection")
    page._set_queue([path])
    page.next_board()
    qtbot.waitUntil(lambda: page.last is not None, timeout=30000)
    return page


def _button(page: QWidget, text: str) -> QPushButton:
    """The button on `page` labelled `text`, for a test to click as a user would."""
    return next(b for b in page.findChildren(QPushButton) if b.text() == text)


def test_req_insp_003_one_box_per_defect_and_the_file_is_unchanged(
    qtbot: QtBot, trained_ctx: AppContext, ng_board: Path
) -> None:
    before = hashlib.sha256(ng_board.read_bytes()).hexdigest()
    page = _inspect_one(qtbot, _window(qtbot, trained_ctx, "Operator"), ng_board)
    assert page.last.defects, "a board with a missing component yields at least one defect"
    boxes = [it.rect() for it in page.view._overlay_items if isinstance(it, QGraphicsRectItem)]
    assert boxes == [QRectF(d.x, d.y, d.w, d.h) for d in page.last.defects]
    assert hashlib.sha256(ng_board.read_bytes()).hexdigest() == before


def test_req_insp_004_columns_in_order_and_selecting_a_row_centres_its_box(
    qtbot: QtBot, trained_ctx: AppContext, ng_board: Path
) -> None:
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


SPOT = Region(100, 120, 20, 20, 400, 90.0, "compare")  # one difference region of 400 px
OVER_SPOT = ROI("U1", "Presence", 90, 110, 40, 40)  # a Presence ROI over it names it a Missing Component: Critical


@pytest.mark.parametrize(
    ("metrics", "spots", "rois", "verdict", "flagged", "severities"),
    [
        pytest.param({}, 0, [], "OK", {}, [], id="ok"),
        pytest.param({"changed_pct": 0.45}, 0, [], "WARN", {"Changed area %": "WARN"}, [], id="warn-from-a-check"),
        pytest.param({"alignment_inliers": 5}, 0, [], "WARN", {"Alignment inliers": "WARN"}, [], id="warn-alignment"),
        pytest.param({}, 1, [], "WARN", {}, ["Major"], id="warn-from-a-major-defect"),
        pytest.param({}, 1, [OVER_SPOT], "WARN", {}, ["Critical"], id="warn-from-a-critical-defect"),
        pytest.param(
            {"ssim": 0.5, "alignment_inliers": 5},
            1,
            [OVER_SPOT],
            "NG",
            {"SSIM similarity": "NG", "Alignment inliers": "WARN"},
            ["Critical"],
            id="ng-before-warn",
        ),
    ],
)
def test_req_insp_015_ng_then_warn_from_a_check_or_a_major_or_critical_defect_else_ok(
    metrics: dict[str, float],
    spots: int,
    rois: list[ROI],
    verdict: str,
    flagged: dict[str, str],
    severities: list[str],
) -> None:
    """The engine's own verdict step, `Inspector.judge` (which `inspect` and `re_grade` call), on golden board evidence
    made to order: a clean board (SSIM 0.99, no pixel changed, 200 alignment points) but for `metrics`, with `spots`
    difference regions. The recipe allows one region, so a defect can be found while every check passes. No ROI type
    names a Minor defect (ROI_DEFECT), so the engine cannot find one; the WARN cases are a WARN check or a defect above
    Minor."""
    clean = {"ssim": 0.99, "changed_pct": 0.0, "compare_regions": spots, "alignment_inliers": 200}
    evidence = CompareResult(regions=[SPOT] * spots, metrics={**clean, **metrics, "alignment_method": "homography"})
    res = InspectionResult("not judged", 0.0, compare=evidence)
    Inspector(Recipe(board_model=BOARD, use_ai=False, max_diff_regions=1, rois=rois)).judge(res, None)
    assert {c.name: c.verdict for c in res.checks if c.verdict not in ("OK", "INFO")} == flagged
    assert [d.severity for d in res.defects] == severities
    assert res.verdict == verdict


def test_req_insp_015_no_board_is_judged_without_its_golden_board_or_with_no_check(
    ctx: AppContext, synthetic_dataset: Path, ng_board: Path
) -> None:
    """A board no check judged was OK (#169): with the golden board's file gone, the comparison was dropped as if none
    were set and an NG board passed with no check; with neither a golden board nor an AI model, every board passed. Now
    a golden board the database names whose file is gone or cannot be read refuses the board with AOI-INSP-009, the
    engine gives a board no check judged, inspected or judged again, no verdict but AOI-INSP-010 saying why, and an OK
    stored with no check is not said to be inside its thresholds."""
    ctx.import_samples(BOARD, [str(p) for p in list_images(synthetic_dataset / "train" / "ok")], "OK")
    golden, kept = Path(str(ctx.reference_image(BOARD))), Path(str(ctx.reference_image(BOARD))).read_bytes()
    judged = ctx.inspect_file(BOARD, str(ng_board), save=False)  # the golden board comparison alone: no AI model
    assert judged.verdict == "NG" and {c.source for c in judged.checks} == {"Compare"}
    for why, change in (
        ("the file is gone", golden.unlink),
        ("it cannot be read (AOI-INSP-004 File format not supported)", lambda: golden.write_bytes(b"no image")),
    ):
        change()
        with pytest.raises(AoiError) as unavailable:
            ctx.inspect_file(BOARD, str(ng_board))
        assert unavailable.value.code == "AOI-INSP-009", unavailable.value
        assert f"names {golden} as its Golden board, but {why}, so no board" in unavailable.value.what
    assert ctx.inspections() == [], "no record for a board not inspected"
    golden.write_bytes(kept)
    ctx.ensure_board_model("EMPTY")  # neither a golden board nor an AI model
    with pytest.raises(AoiError) as nothing:
        ctx.inspect_file("EMPTY", str(ng_board))
    assert nothing.value.code == "AOI-INSP-010"
    assert "of board model EMPTY: no Golden board is set; no AI model is trained." in nothing.value.what
    with pytest.raises(AoiError) as turned_off:  # thresholds that turn every check off judge nothing either
        re_grade(judged, Recipe(board_model=BOARD, use_compare=False, use_ai=False), None)
    assert turned_off.value.code == "AOI-INSP-010"
    off = "the recipe turns the Golden board comparison off; the recipe turns the AI model off"
    assert off in turned_off.value.what
    assert [s.text() for s in explain(InspectionResult("OK", 0.0))] == [
        "The stored checks do not show why; inspect the board again."
    ]


def test_req_insp_016_six_step_cards_open_their_pages_and_show_status(
    qtbot: QtBot, trained_ctx: AppContext, ng_board: Path, synthetic_dataset: Path
) -> None:
    """Each card opens its page in one click; each status is read again whenever Home opens, and shows within 300 ms
    of Home opening in every one of 11 openings after a warm-up."""
    win = _window(qtbot, trained_ctx)
    home = win.pages["Home"]
    buttons = [b for b in home.findChildren(QPushButton) if b.text().startswith("Open ")]
    assert len(buttons) == 6 == len(home.STEPS)
    for b, (_, name, _, target) in zip(buttons, home.STEPS, strict=True):
        win.navigate("Home")
        qtbot.mouseClick(b, Qt.MouseButton.LeftButton)
        assert win.stack.currentWidget() is win.pages[target], name

    def open_home() -> tuple[float, dict[str, str]]:
        """Home opened from another page: the seconds until its status is set and painted, and the status shown."""
        win.navigate("Inspection")
        t0 = perf_counter()
        win.navigate("Home")
        QApplication.processEvents()  # the repaint the new status asked for
        return perf_counter() - t0, {name: label.text() for name, label in home.status_labels.items()}

    _, before = open_home()  # the warm-up: a first opening's one-off costs are not Home's
    ok, ng = len(trained_ctx.samples(BOARD, "OK")), len(trained_ctx.samples(BOARD, "NG"))
    assert before["Upload samples"] == f"{ok} OK · {ng} NG uploaded" and "Active AI model" in before["Self-train"]
    assert before["Inspect"] == "No boards inspected yet. Load images on Inspection."
    # The data behind four cards changes between two openings: one more OK sample, a saved recipe, an inspected board.
    trained_ctx.import_samples(BOARD, [str(next((synthetic_dataset / "test" / "ok").glob("*.png")))], "OK")
    revision = trained_ctx.save_recipe(Recipe(board_model=BOARD, rois=[ROI("R1")]))
    res = trained_ctx.inspect_file(BOARD, str(ng_board))
    first, after = open_home()
    assert after == {
        **before,
        "Upload samples": f"{ok + 1} OK · {ng} NG uploaded",
        "Tune recipe": f"Recipe revision {revision}",
        "Inspect": f"1 boards inspected · {int(res.verdict == 'NG')} NG",
        "Export": "Ready",
    }
    opens = [first] + [open_home()[0] for _ in range(10)]  # every opening after the warm-up
    assert max(opens) < 0.3, f"Home status took up to {max(opens) * 1000:.0f} ms ({len(opens)} openings)"


def test_req_cmp_001_linked_views_zoom_and_pan_together_within_1px(
    qtbot: QtBot, trained_ctx: AppContext, tiny_model: TrainedModel
) -> None:
    """A wheel step on one view zooms both, and a pan of either view moves the other to the same board position,
    within 1 px at 100 % zoom. The board is the golden board at four times its size, so both pans stay inside the
    scroll range across and down: at its own size a view could pan it 16 px at most before Compare was shown, and not
    down at all once it was, so a pan the test asked for was clamped before the link was tested."""
    win = _window(qtbot, trained_ctx)
    win.navigate("Compare")
    page = win.pages["Compare"]
    ref, test = page.ref_view, page.test_view
    board = cv2.resize(tiny_model.reference, None, fx=4, fy=4, interpolation=cv2.INTER_NEAREST)
    ref.set_image(board)
    test.set_image(board)

    def gap() -> float:
        """How far apart, in board pixels, the two views' centres are."""
        a, b = (v.mapToScene(v.viewport().rect().center()) for v in (ref, test))
        return max(abs(a.x() - b.x()), abs(a.y() - b.y()))

    fitted = ref.transform().m11()
    up = QPoint(0, 120)  # one wheel step away from the user: zoom in
    ref.wheelEvent(
        QWheelEvent(
            QPointF(10, 10),
            QPointF(10, 10),
            QPoint(),
            up,
            Qt.MouseButton.NoButton,
            Qt.KeyboardModifier.NoModifier,
            Qt.ScrollPhase.NoScrollPhase,
            False,
        )
    )
    assert ref.transform().m11() == pytest.approx(fitted * 1.25)
    assert test.transform() == ref.transform() and gap() <= 1
    ref.resetTransform()  # 100 % zoom, where the criterion is measured; the pan below carries it to the other view
    for view, (x, y) in ((ref, (437, 291)), (test, (1500, 900))):  # a pan of the golden board, then of the test board
        view.horizontalScrollBar().setValue(x)
        view.verticalScrollBar().setValue(y)
        assert (view.horizontalScrollBar().value(), view.verticalScrollBar().value()) == (x, y), "the pan was clamped"
        assert test.transform() == ref.transform() == QTransform()
        assert gap() <= 1, f"the views' centres are {gap():.1f} px apart after a pan to {x}, {y}"


def test_req_cmp_006_any_stored_ok_sample_can_be_the_reference_and_metrics_recompute(
    qtbot: QtBot, trained_ctx: AppContext, ng_board: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An OK sample of the board model picked with Reference… becomes the reference, and every row of the decision
    table is then what the engine gives the board against that sample."""
    win = _window(qtbot, trained_ctx)
    win.navigate("Compare")
    page = win.pages["Compare"]
    page.set_test(str(ng_board))
    qtbot.waitUntil(lambda: page.res is not None, timeout=30000)  # the inspection runs on a pool thread (S17b)
    against_golden = page.res
    assert page.ref_label.text() == "Reference: Golden board"
    sample = trained_ctx.samples(BOARD, "OK")[-1]["path"]  # any stored OK sample: here the newest
    monkeypatch.setattr(QFileDialog, "getOpenFileName", staticmethod(lambda *_: (sample, "")))  # the user picks it
    qtbot.mouseClick(_button(page, "Reference…"), Qt.MouseButton.LeftButton)
    qtbot.waitUntil(lambda: page.res is not against_golden, timeout=30000)

    board, reference = trained_ctx.load_image(ng_board), trained_ctx.load_image(sample)
    want = trained_ctx.inspect(BOARD, board, reference=reference)  # the engine's own result against the sample
    columns = (0, 2, 3, 5)  # Check, Value, Threshold, Result
    table = [
        [page.metrics.item(r, c).data(Qt.ItemDataRole.DisplayRole) for c in columns]
        for r in range(page.metrics.rowCount())
    ]
    assert len(table) == len(want.checks) + 1 and table[-1][0] == "Inspection time (ms)"  # timed, so not compared
    for row, c in zip(table, want.checks, strict=False):
        value, threshold = pytest.approx(c.value, abs=1e-4), pytest.approx(c.threshold, abs=1e-4)
        assert row == [page._check_text(c)[0], value, threshold, c.verdict], c.name
    assert page.res.verdict == want.verdict
    # Not the golden board's table shown again: what measures the board against its reference has moved.
    golden = {c.name: c.value for c in against_golden.checks}
    assert {"SSIM similarity", "Changed area %", "Alignment inliers"} <= {
        c.name for c in want.checks if c.value != golden[c.name]
    }
    assert page.ref_label.text() == f"Reference: {Path(sample).name}"


def test_req_rcp_002_five_roi_types_and_five_fields_save_and_reload(
    qtbot: QtBot, trained_ctx: AppContext, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Five ROIs drawn on the Golden board, each given its type and its five fields in the editor's own widgets and
    stored with Save Recipe, come back the same in a new window on a new context over the same workspace."""
    monkeypatch.setattr(QMessageBox, "information", staticmethod(lambda *_: QMessageBox.StandardButton.Ok))
    win = _window(qtbot, trained_ctx)
    win.navigate("Recipe Editor")
    page = win.pages["Recipe Editor"]
    assert ROI_TYPES == ["Presence", "Polarity", "Solder Bridge", "Height", "Anomaly"]
    assert [page.r_type.itemData(i) for i in range(page.r_type.count())] == ROI_TYPES
    fields = [(1.25 + i, 0.125 * (i + 1), 1.5 + i, 2.25 + i, 3.75 + i) for i in range(5)]  # exact in binary
    boxes = [(20 + 60 * i, 30, 40, 50) for i in range(5)]
    for i, roi_type in enumerate(ROI_TYPES):
        page.roi_type.setCurrentIndex(page.roi_type.findData(ROI_TYPES[i - 1]))  # drawn as another type, then set
        page.view.roiDrawn.emit(QRectF(*boxes[i]))  # what a drag on the Golden board in Draw ROI mode gives
        assert page.r_type.currentData() == ROI_TYPES[i - 1]  # the new ROI is selected in the Selected ROI box
        page.r_type.setCurrentIndex(page.r_type.findData(roi_type))
        spins = (page.r_ai, page.r_hmin, page.r_hmax, page.r_vmin, page.r_vmax)  # AI score, height and volume min/max
        for spin, value in zip(spins, fields[i], strict=True):
            spin.setValue(value)
        qtbot.mouseClick(_button(page, "Apply"), Qt.MouseButton.LeftButton)
    qtbot.mouseClick(_button(page, "Save Recipe"), Qt.MouseButton.LeftButton)

    reopened = engineer(AppContext(Settings(workspace=trained_ctx.settings.workspace, device="cpu")))  # a restart
    want = [ROI(f"R{i + 1}", t, *boxes[i], *fields[i]) for i, t in enumerate(ROI_TYPES)]
    assert reopened.recipe(BOARD)[1].rois == want
    win = _window(qtbot, reopened)
    win.navigate("Recipe Editor")
    page = win.pages["Recipe Editor"]
    assert page.roi_table.rowCount() == 5
    for i, roi_type in enumerate(ROI_TYPES):
        page.roi_table.selectRow(i)
        spins = (page.r_ai, page.r_hmin, page.r_hmax, page.r_vmin, page.r_vmax)
        assert (page.r_type.currentData(), *(s.value() for s in spins)) == (roi_type, *fields[i])


def test_req_set_002_auto_picks_cuda_when_present_and_cpu_otherwise(monkeypatch: pytest.MonkeyPatch) -> None:
    import torch

    monkeypatch.setattr(torch.cuda, "is_available", lambda: True)
    assert resolve_device("auto") == "cuda" and resolve_device("cpu") == "cpu"
    monkeypatch.setattr(torch.cuda, "is_available", lambda: False)
    assert resolve_device("auto") == "cpu" and resolve_device("cuda") == "cpu"
