"""Render every page offscreen, for every role that may open it, into PNG files (REQ-SET-004; stage S21).

``pytest tests/screens`` renders at 1920x1080 and compares with ``tests/screens/approved/``; a page that differs
fails, and CI uploads the new images. ``python tools/render_screens.py --approve`` rewrites the approved set after an
intended change of a screen: the images are generated files, and Jay approves them by merging. ``--out DIR --size
3840x2160 --scale 2`` renders a review set at another screen size and scale.

The pages are rendered on the synthetic workspace: the board model TINY with the seeded dataset's samples, a tiny AI
model trained for a few epochs, one inspected NG board (its first IC missing), one recipe revision with one Presence
ROI around that IC. Everything that would change from run to run is pinned, and what would change with the machine's
CPU is pinned or kept within the comparison's tolerance: record ids and the UUID in every sample's file name come from
a counter instead of uuid4(), every stored time is FIXED_TIME and is shown as UTC, the Logs filter covers that week, the
Settings page shows FIXED_WORKSPACE, and the Inspection page is rendered with `log_result` patched out, so it adds no
record. The inspections shown run with PinnedModel in place of the trained model and report FIXED_MS: the training is
seeded, but PyTorch's float rounding differs by CPU type (the same seed and data gave thresholds of 3.06 and 2.01 with
its vectorised and its default CPU kernels), so a trained model's score, boxes and verdict differ between machines.
PinnedModel takes the model out of that equation: its map is 8-bit OpenCV arithmetic from the golden board, and the
Training page lists its threshold. The ORB alignment stays a float pipeline, so the golden board and the aligned test
board can still differ by a level or a sub-pixel between machines (with OpenCV's AVX code turned off, the alignment
found 379 points instead of 382 and the similarity read 0.9395 instead of 0.9377); the shift-tolerant difference, the
quantised map and the wide margins between the shown values and their thresholds keep the verdict, the boxes and the
scores identical, and the two numbers that follow the alignment's last digits are pinned: Compare shows FIXED_SSIM and
FIXED_INLIERS. What still moves is the aligned board picture, by a level or two (at most 42 levels, at 2 single pixels,
with OpenCV and NumPy held to SSE3), which the comparison tolerates (tests/screens/test_screens.py). On Linux the pages
are drawn with DejaVu Sans without hinting, so every Linux machine draws the same pixels; Windows draws Segoe UI, so
there the tests check sizes and contrast only.
"""

from __future__ import annotations

import argparse
import itertools
import json
import os
import re
import sys
import tempfile
import time
import uuid
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import TYPE_CHECKING, Any
from unittest import mock

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:  # run as a script: the repository root holds the ``aoi`` and ``tools`` packages
    sys.path.insert(0, str(ROOT))

APPROVED_DIR = ROOT / "tests" / "screens" / "approved"
BOARD_MODEL = "TINY"
FIXED_TIME = "2026-01-01T09:00:00+00:00"  # every stored time, so a render does not change with the clock
FIXED_MS = 480.0  # the inspection time Inspection and Compare show
FIXED_SSIM, FIXED_INLIERS = 0.95, 400  # the similarity and alignment points Compare shows (module docstring)
STORED_STATES = (  # Compare
    "compare-stored-operator", "compare-golden-changed-operator", "compare-tried-engineer", "compare-save-engineer",
)  # fmt: skip
FIXED_WORKSPACE = "C:/AOI_Workspace"  # what the Settings page shows instead of the temporary folder
TEST_FONT = '"DejaVu Sans"'  # the font the approved images are drawn with (Linux)
DATASET_OK, DATASET_NG, DATASET_SEED = 30, 14, 7  # as tests/conftest.py
TINY_EPOCHS, TINY_IMAGE_SIZE = 6, 64
PINNED_SCALE = 16.0  # grey levels of difference from the golden board per unit of PinnedModel's anomaly score
PINNED_IMAGE_THRESHOLD = 3.0  # PinnedModel's NG threshold on the 99.9th-percentile score (48 levels)
PINNED_PIXEL_THRESHOLD = 2.0  # PinnedModel's threshold for a pixel to belong to a defect region (32 levels)
# The map is quantised to multiples of PINNED_STEP levels; the NG board's values (104 to 108) sit mid-bin, so the level
# or two of rounding the float alignment can add changes no shown number.
PINNED_STEP = 16

if TYPE_CHECKING:
    from PySide6.QtWidgets import QApplication

    from aoi.core.services import AppContext
    from aoi.ui.main_window import MainWindow


def slug(title: str) -> str:
    """ "Logs & Export" -> "logs-export"."""
    return re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")


def counted_uuids() -> Iterator[uuid.UUID]:
    """What uuid4() returns while the workspace is built: 000001…, 000002…, so the UUID that names each sample's file
    and the record's evidence files (#245), and every record id, are the same in every run."""
    for n in itertools.count(1):
        yield uuid.UUID(int=(n << 104) | n, version=4)


class PinnedModel:
    """What the renders inspect with in place of the trained AnomalyModel: the interface Inspector uses (anomaly_map,
    score, image_threshold, pixel_threshold, meta), computed from pixels only.

    The map is the compare pipeline's own 8-bit difference from the golden board (5x5 blur, Lab, the shift-tolerant
    difference, a 3x3 opening against specks), quantised to PINNED_STEP levels and divided by PINNED_SCALE; the
    thresholds are constants. Every step is integer OpenCV arithmetic (bit-exact with OpenCV's SIMD and IPP paths
    disabled), so the map depends on its two input images alone. Those still come through the float ORB alignment; the
    shift-tolerant difference, the quantisation and the margins to the thresholds are what keep the shown verdict, boxes
    and scores identical between machines, where a trained model's are not (module docstring). The model is still
    trained, saved and listed; only what the inspected board shows on Inspection, Compare, Logs and Home comes from it.
    """

    def __init__(self, reference: np.ndarray, meta: dict[str, Any]) -> None:
        self.reference = reference
        self.meta = {
            **meta,
            "image_threshold": PINNED_IMAGE_THRESHOLD,
            "pixel_threshold": PINNED_PIXEL_THRESHOLD,
            "threshold_rule": "fixed for the screenshots",
        }
        self.image_threshold = PINNED_IMAGE_THRESHOLD
        self.pixel_threshold = PINNED_PIXEL_THRESHOLD

    def anomaly_map(self, img: np.ndarray) -> np.ndarray:
        from aoi.core.compare import shift_tolerant_diff

        if img.shape != self.reference.shape:  # Inspector aligns the board onto the reference before this call
            raise ValueError(f"the image {img.shape} is not aligned to the reference {self.reference.shape}")
        a = cv2.cvtColor(cv2.GaussianBlur(img, (5, 5), 0), cv2.COLOR_BGR2LAB)
        b = cv2.cvtColor(cv2.GaussianBlur(self.reference, (5, 5), 0), cv2.COLOR_BGR2LAB)
        speck = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3))
        diff = cv2.morphologyEx(shift_tolerant_diff(a, b), cv2.MORPH_OPEN, speck)
        return (diff // PINNED_STEP * PINNED_STEP).astype(np.float32) / PINNED_SCALE

    def score(self, amap: np.ndarray) -> float:
        return float(np.percentile(amap, 99.9))  # as AnomalyModel.score


def build_workspace(root: Path) -> AppContext:
    """The synthetic workspace the pages are rendered on; see the module docstring."""
    from aoi.config import Settings
    from aoi.core.imaging import list_images
    from aoi.core.labels import DefectBox
    from aoi.core.recipe import ROI
    from aoi.core.services import AppContext
    from tools.make_synthetic_dataset import ng_type, write_dataset

    os.environ["AOI_WORKSPACE"] = str(root / "default_workspace")  # settings.json is saved there, never in ~/
    dataset = root / "dataset"
    write_dataset(dataset, DATASET_OK, DATASET_NG, DATASET_SEED)
    with mock.patch("uuid.uuid4", side_effect=counted_uuids()):
        ctx = AppContext(Settings(workspace=str(root / "workspace"), device="cpu"))
        ctx.set_user("engineer")
        ctx.import_samples(BOARD_MODEL, [str(p) for p in list_images(dataset / "train" / "ok")], "OK")
        for p in list_images(dataset / "train" / "ng"):  # one call each: an NG sample is imported with its type
            ctx.import_samples(BOARD_MODEL, [str(p)], "NG", ng_type(p))
        ctx.train(BOARD_MODEL, epochs=TINY_EPOCHS, image_size=TINY_IMAGE_SIZE)
        recipe = ctx.recipe(BOARD_MODEL)[1]
        recipe.rois.append(ROI("R1", "Presence", 110, 110, 110, 110))  # around the IC the NG board lacks (LAYOUT[0])
        ctx.save_recipe(recipe)
        with pinned_engine():
            ctx.inspect_file(BOARD_MODEL, str(ng_board(dataset)))  # one record for Logs, one alarm for Inspection
        missing = ctx.samples(BOARD_MODEL, "NG")[0]  # ng_000: the seed leaves out its first IC (LAYOUT[0])
        ctx.set_boxes(missing["uuid"], [DefectBox(110, 110, 110, 110, "Missing Component")])  # Training's editor
    for table, column in (
        ("board_models", "created_at"),
        ("samples", "added_at"),
        ("models", "created_at"),
        ("recipes", "created_at"),
        ("inspections", "time"),
        ("alarms", "time"),
    ):  # the audit trail keeps its real times: it is append-only and no page shows it
        ctx.db.execute(f"UPDATE {table} SET {column}=?", (FIXED_TIME,))  # noqa: S608 - fixed table names above
    # The Training page lists the model's threshold: PinnedModel's, the one the Compare table applies.
    for m in ctx.models(BOARD_MODEL):
        metrics = {**json.loads(m["metrics"] or "{}"), "image_threshold": PINNED_IMAGE_THRESHOLD}
        ctx.db.execute("UPDATE models SET metrics=? WHERE id=?", (json.dumps(metrics), m["id"]))
    return ctx


def ng_board(dataset: Path) -> Path:
    """The test-split board with a missing component, as tests/conftest.py picks it."""
    return next(dataset.glob("test/ng/*missing_component*.png"))


def pin_time_zone() -> Callable[[], None]:
    """Show stored times as UTC whatever the machine's zone (the records are stored at FIXED_TIME); returns a function
    that puts the zone back. Windows cannot change the zone from Python, and no image comparison runs there."""
    if not hasattr(time, "tzset"):
        return lambda: None
    before = os.environ.get("TZ")
    os.environ["TZ"] = "UTC"
    time.tzset()

    def restore() -> None:
        if before is None:
            os.environ.pop("TZ", None)
        else:
            os.environ["TZ"] = before
        time.tzset()

    return restore


@contextmanager
def pinned_rendering(app: QApplication, font: str) -> Iterator[None]:
    """The stylesheet with ``font`` as the family (none: the theme's own list), hinting off and grey anti-aliasing, so
    a render does not depend on the machine's fonts or screen; the application's stylesheet and font are put back."""
    from PySide6.QtGui import QFont

    from aoi.ui import theme

    before_sheet, before_font = app.styleSheet(), QFont(app.font())
    pinned = QFont(before_font)
    pinned.setHintingPreference(QFont.HintingPreference.PreferNoHinting)
    pinned.setStyleStrategy(QFont.StyleStrategy.NoSubpixelAntialias)  # grey edges, not the screen's RGB fringes
    if font:
        pinned.setFamily(font.strip('"'))  # text drawn on the image (QGraphics items) takes the application font
    app.setFont(pinned)
    app.setStyleSheet(theme.stylesheet(FONT_FAMILY=font) if font else theme.QSS)
    try:
        yield
    finally:
        app.setStyleSheet(before_sheet)
        app.setFont(before_font)


@contextmanager
def pinned_engine() -> Iterator[None]:
    """Every inspection runs with PinnedModel in place of the trained model, reports FIXED_MS and is judged on
    FIXED_SSIM and FIXED_INLIERS, so the verdict, the score, the boxes, the time and the checks that Inspection,
    Compare, Logs and Home show are the same on every machine."""
    from aoi.core import inspector
    from aoi.core.compare import CompareResult
    from aoi.core.inspector import Inspector

    real, real_compare = Inspector.inspect, inspector.compare

    def compare(*args: Any, **kwargs: Any) -> CompareResult:
        res = real_compare(*args, **kwargs)
        res.metrics.update(ssim=FIXED_SSIM, alignment_inliers=FIXED_INLIERS)  # their last digits follow the CPU
        return res

    def inspect(self: Inspector, *args: Any, **kwargs: Any) -> Any:
        model = self.model
        if model is not None:
            if self.reference is None:
                raise RuntimeError("the render workspace has no reference image, so its inspections cannot be pinned")
            self.model = PinnedModel(self.reference, model.meta)  # duck-typed; the Inspector is shared, so put back
        try:
            res = real(self, *args, **kwargs)
        finally:
            self.model = model
        res.elapsed_ms = FIXED_MS
        return res

    with mock.patch.object(Inspector, "inspect", inspect), mock.patch.object(inspector, "compare", compare):
        yield


def wait_until(condition: Callable[[], bool], timeout_ms: int = 60000) -> None:
    from PySide6.QtCore import QDeadlineTimer
    from PySide6.QtWidgets import QApplication

    deadline = QDeadlineTimer(timeout_ms)
    while not condition():
        if deadline.hasExpired():
            raise TimeoutError("the page did not finish rendering its content")
        QApplication.processEvents()


def prepare(win: MainWindow, title: str, dataset: Path) -> None:
    """Put the page in the state the screenshot shows: content where the workspace has some, fixed values where
    the real ones would change from run to run."""
    from PySide6.QtCore import QDate

    from aoi.ui.pages.base import cell_text

    page: Any = win.pages[title]
    if title == "Inspection":
        if page.last is None:
            no_record = mock.patch.object(type(page.ctx), "log_result", lambda *a, **k: 0)  # no record and no alarm
            with pinned_engine(), no_record:
                page._set_queue([ng_board(dataset)])
                page.next_board()
                wait_until(lambda: page.last is not None)
                assert page.last.elapsed_ms == FIXED_MS, "the Inspection run was not pinned"  # no real run: 480.0
        page.table.selectRow(0)  # an Operator zooms to a defect: the walk measures a selected row (#203)
    elif title == "Compare" and page.res is None:
        with pinned_engine():
            page.set_test(str(ng_board(dataset)))
            wait_until(lambda: page.res is not None)
            assert page.res.elapsed_ms == FIXED_MS, "the Compare run was not pinned"
    elif title == "Training":
        page.import_from(str(dataset / "train"))  # the import sheet open on ok/ and ng/, its NG rows waiting for a type
        page.sheet.table.clearFocus()  # the sheet takes the keys: let go, or the next page drawn shows a field's caret
        page.bar.setRange(0, TINY_EPOCHS)
        page.bar.setValue(TINY_EPOCHS)  # as a finished run leaves it: the percentage on the accent chunk (#203)
        missing = str(page.ctx.samples(BOARD_MODEL, "NG")[0]["id"])  # the label editor on its box, selected
        rows = range(page.samples.rowCount())
        page.samples.selectRow(next(r for r in rows if cell_text(page.samples, r, 0) == missing))
        page.editor.view.choose(0)
        if not page.editor.draw_btn.isChecked():  # Draw mode on: the button's on look in the shot and the size walk
            page.editor.draw_btn.click()
    elif title == "Logs & Export":
        page.d_from.setDate(QDate(2025, 12, 25))
        page.d_to.setDate(QDate(2026, 1, 8))
        page.refresh()
    elif title == "Settings":
        page.ws.setText(FIXED_WORKSPACE)


def render_stored(win: Any, ctx: AppContext, out: Path) -> dict[str, Path]:
    """Compare on the record `build_workspace` saved, as an Operator opens it from Inspection: beside the golden board
    it was judged against, then with that file changed, which the pane explains (REQ-CMP-003); the file is put back.
    Then as an Engineer judges it again with other thresholds: the would-be verdict beside Re-evaluate, and Save to
    Recipe's sheet with a reason typed, nothing saved (REQ-CMP-005)."""
    from PySide6.QtWidgets import QApplication

    page, files = win.pages["Compare"], {}
    record = ctx.inspections(board_model=BOARD_MODEL)[0]["id"]
    golden = Path(str(ctx.reference_image(BOARD_MODEL)))
    kept = golden.read_bytes()
    win.set_user("operator")
    try:
        for name in STORED_STATES:
            golden.write_bytes(kept + b"\0" if name == STORED_STATES[1] else kept)
            if name == STORED_STATES[2]:
                win.set_user("engineer")
            win.statusBar().clearMessage()
            assert win.navigate("Compare")
            page.show_stored(record)
            wait_until(lambda: page._bg is None)
            if name in STORED_STATES[2:]:  # an AI score threshold above the AI score, and no pixel differs enough
                page.ai_thr.set_override(7.0)
                page.diff_thr.setValue(255)
                page.act_try.trigger()
                wait_until(lambda: page._bg is None)
            if name == STORED_STATES[3]:
                page.act_save.trigger()
                page.reason.setText("No pixel differs enough on this board")
            QApplication.processEvents()
            files[name] = out / f"{name}.png"
            assert win.grab().save(str(files[name])), files[name]
    finally:
        golden.write_bytes(kept)
    return files


def render_pages(
    ctx: AppContext, dataset: Path, out: Path, size: tuple[int, int] = (1920, 1080), scale: float = 1.0
) -> dict[str, Path]:
    """Render every page for every role that may open it into ``out``; returns {"home-operator": path, ...}.
    ``size`` is the screen in pixels: with ``scale`` (QT_SCALE_FACTOR, set before Qt starts) the window measures
    ``size / scale`` logical pixels, so the image still measures ``size``."""
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication

    from aoi.ui.main_window import MainWindow
    from aoi.ui.pages.base import ROLES

    out.mkdir(parents=True, exist_ok=True)
    win = MainWindow(ctx)
    win.resize(round(size[0] / scale), round(size[1] / scale))
    win.show()
    QTest.qWaitForWindowExposed(win)
    files: dict[str, Path] = {}
    for role in ROLES:
        win.set_user(role.lower())
        for title, page in win.pages.items():
            if role not in page.roles:
                continue
            win.statusBar().clearMessage()  # the page before's message is not this page's; what it says itself stays
            assert win.navigate(title), title
            prepare(win, title, dataset)
            QApplication.processEvents()
            name = f"{slug(title)}-{role.lower()}"
            files[name] = out / f"{name}.png"
            assert win.grab().save(str(files[name])), files[name]
    files.update(render_stored(win, ctx, out))
    win.close()
    return files


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--out", type=Path, help="folder for the images (default: a temporary folder)")
    parser.add_argument("--size", default="1920x1080", help="screen size in pixels, WIDTHxHEIGHT")
    parser.add_argument("--scale", type=float, default=1.0, help="Qt scale factor, 1.5 for 150 %%")
    parser.add_argument("--approve", action="store_true", help=f"rewrite {APPROVED_DIR.relative_to(ROOT)}")
    parser.add_argument("--font", default=TEST_FONT if sys.platform == "linux" else "", help="font family to pin")
    args = parser.parse_args(argv)
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    os.environ["QT_SCALE_FACTOR"] = str(args.scale)  # read when the application starts, so before any Qt import
    pin_time_zone()
    from PySide6.QtGui import QImage
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication([])
    width, height = (int(v) for v in args.size.lower().split("x"))
    out = APPROVED_DIR if args.approve else args.out or Path(tempfile.mkdtemp(prefix="aoi-screens-"))
    if args.approve:
        for stale in APPROVED_DIR.glob("*.png"):
            stale.unlink()
    with tempfile.TemporaryDirectory(prefix="aoi-screens-workspace-") as tmp, pinned_rendering(app, args.font):
        ctx = build_workspace(Path(tmp))
        try:
            files = render_pages(ctx, Path(tmp) / "dataset", out, (width, height), args.scale)
        finally:
            ctx.close()
    drawn = QImage(str(next(iter(files.values())))).size()
    print(f"{len(files)} images of {drawn.width()}x{drawn.height()} px in {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
