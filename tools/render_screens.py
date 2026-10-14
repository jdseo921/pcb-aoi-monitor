"""Render every page offscreen, for every role that may open it, into PNG files (REQ-SET-004; stage S21).

``pytest tests/screens`` renders at 1920x1080 and compares with ``tests/screens/approved/``; a page that differs fails,
and CI uploads the new images. The last images are the light presenter theme's (REQ-SET-008, PRESENTER_SHOTS), switched
on and off again as an Admin does it. ``python tools/render_screens.py --approve`` rewrites the approved set after an
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
there the tests check sizes and contrast only. The presenter theme is drawn twice: at the screen size, and at 1366 x 768
(PRESENTER_SMALL_SHOTS), every page the demo scripts open as a 1366 x 768 projector shows it (#104).
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
from collections import Counter
from collections.abc import Callable, Iterator
from contextlib import ExitStack, contextmanager
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
SETTLE_MS = 40  # past the 20 ms after which Qt resizes a list to its contents (`settle`)
SETTLE_PASSES = 100  # event loop passes a page may take to lay itself out before a grab
CLEAR_BUTTON_WAIT_S = 10  # at most: a field's clear button fades in over about 300 ms (Qt's QLineEdit), more under load
PAGE_VIEWS = {  # <page>-<view>-<role>
    "Training": ("datasets", "freeze", "split", "blind", "missing"),
    "Settings": ("advanced", "restore", "move-in", "shred"),
    "Logs & Export": ("types",),
    "AI Model Test": ("targets",),
}
STORED_STATES = (  # Compare
    "compare-stored-operator", "compare-golden-changed-operator", "compare-tried-engineer", "compare-save-engineer",
)  # fmt: skip
PRESENTER_SHOTS = {  # the presenter theme (REQ-SET-008): presenter-<page>-<role>, the pages a demo shows
    "presenter-home-admin": ("Home", "admin"),  # 3D Profile hidden, Exit presenter theme in the header
    "presenter-inspection-operator": ("Inspection", "operator"),  # the result, its verdict at 48 pt; no Settings
    "presenter-compare-engineer": ("Compare", "engineer"),
    "presenter-settings-admin": ("Settings", "admin"),  # kept for the Admin's Reset Demo, without the hardware table
}
SMALL_SIZE = (1366, 768)  # a projector that takes no more (#104): the presenter theme at its 16 pt size (theme.SMALL_H)
PRESENTER_SMALL_SHOTS = {  # every page the demo scripts open (tools/screen_sizes.py), at SMALL_SIZE, as the Admin
    "presenter-1366-home-admin": ("Home", "admin"),
    "presenter-1366-inspection-admin": ("Inspection", "admin"),
    "presenter-1366-compare-admin": ("Compare", "admin"),
    "presenter-1366-training-admin": ("Training", "admin"),
    "presenter-1366-ai-model-test-admin": ("AI Model Test", "admin"),
    "presenter-1366-recipe-editor-admin": ("Recipe Editor", "admin"),
    "presenter-1366-logs-export-admin": ("Logs & Export", "admin"),
    "presenter-1366-settings-admin": ("Settings", "admin"),
}
NEW_BOARD_MODEL_SHOTS = {"new-board-model-admin": "form", "new-board-model-key-admin": "key"}  # dialogs (ADR 0021)
GUIDE_SHOTS = {  # Home's first-run guide (B5): screen 1 as the Admin types, the key Create shows, and the Engineer's;
    # screen 2 for a board model with no image yet, then with GUIDE_OK and GUIDE_NG images in and the box area open;
    # screen 3 before Train and with what Train made, its reads pinned (`guide_steps`)
    "home-guide-admin": ("admin", "form"),
    "home-guide-key-admin": ("admin", "key"),
    "home-guide-engineer": ("engineer", "form"),
    "home-guide-images-admin": ("admin", "images"),
    "home-guide-boxes-admin": ("admin", "boxes"),
    "home-guide-train-admin": ("admin", "train"),
    "home-guide-trained-admin": ("admin", "trained"),
}
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


def counted_uuids(start: int = 1) -> Iterator[uuid.UUID]:
    """What uuid4() returns while the workspace is built: 000001…, 000002…, so the UUID that names each sample's file
    and the record's evidence files (#245), and every record id, are the same in every run; from `start`, for what a
    render adds after (GUIDE_UUIDS)."""
    for n in itertools.count(start):
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


def pinned_key() -> tuple[bytes, bytes]:
    """A store's key as `crypto.new_key` draws it, its key id fixed, as Settings › Dataset stores shows it."""
    return os.urandom(32), bytes.fromhex("5ca1ab1e") + bytes(12)


def guide_key() -> tuple[bytes, bytes]:
    """GUIDE_CUSTOMER's store key as `pinned_key` draws one, under a key id of its own: no two stores share one."""
    return os.urandom(32), bytes.fromhex("ced0a201") + bytes(12)


def build_workspace(root: Path) -> AppContext:
    """The synthetic workspace the pages are rendered on; see the module docstring."""
    from aoi.config import Settings
    from aoi.core.imaging import list_images
    from aoi.core.labels import DefectBox
    from aoi.core.recipe import ROI
    from aoi.core.services import AppContext
    from aoi.data import credentials
    from tools.make_synthetic_dataset import ng_type, write_dataset
    from tools.trainable import trainable

    os.environ["AOI_WORKSPACE"] = str(root / "default_workspace")  # settings.json is saved there, never in ~/
    dataset = root / "dataset"
    write_dataset(dataset, DATASET_OK, DATASET_NG, DATASET_SEED)
    with mock.patch("uuid.uuid4", side_effect=counted_uuids()), mock.patch("aoi.core.crypto.new_key", pinned_key):
        keys = credentials.MemoryCredentials()  # the store key trainable makes, never written to the Credential Manager
        settings = Settings(workspace=str(root / "workspace"), device="cpu", shift_check_hours=0)  # no clock in renders
        ctx = AppContext(settings, keys)
        ctx.set_user("engineer")
        ctx.import_samples(BOARD_MODEL, [str(p) for p in list_images(dataset / "train" / "ok")], "OK")
        for p in list_images(dataset / "train" / "ng"):  # one call each: an NG sample is imported with its type
            ctx.import_samples(BOARD_MODEL, [str(p)], "NG", ng_type(p))
        meta = ctx.train(trainable(ctx, BOARD_MODEL), epochs=TINY_EPOCHS, image_size=TINY_IMAGE_SIZE)
        if not meta["activated"]:  # a board model's first version goes live when trained (ADR 0018), unless refused
            ctx.activate_model(int(ctx.models(BOARD_MODEL)[0]["id"]))  # which this raises again, with its code
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
    with mock.patch.object(theme, "FONT_FAMILY", font or theme.FONT_FAMILY):  # a theme switched on meanwhile keeps it
        app.setStyleSheet(theme.stylesheet())
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


def settle() -> None:
    """Let the window finish laying out, so a grab draws a page alike however busy the machine is. A list that adjusts
    to its contents resizes itself to its size hint 20 ms after its items change, outside its layout, and each layout
    above a widget whose size hint changed lays out on a LayoutRequest posted while the one below it was laid out: one
    pass of the event loop each. A grab one pass after `prepare` caught Logs & Export's Operator list in the width it
    had before its names were added or, on a busy machine, with Qt's resize done and the layout not: the list 7 px wider
    than its place, its arrow cut off (#396's CI). So sleep past that resize without handling events, then handle
    events until a pass moves, resizes and lays out nothing."""
    from PySide6.QtCore import QCoreApplication, QEvent, QObject
    from PySide6.QtTest import QTest

    class Layouts(QObject):
        """Counts the layout events the application delivers: a widget moved or resized, or a layout asked for."""

        kinds = (QEvent.Type.LayoutRequest, QEvent.Type.Move, QEvent.Type.Resize)

        def __init__(self) -> None:
            super().__init__()
            self.seen = 0

        def eventFilter(self, watched: QObject, event: QEvent) -> bool:
            self.seen += event.type() in self.kinds
            return False

    QTest.qSleep(SETTLE_MS)
    app = QCoreApplication.instance()
    assert app is not None
    layouts = Layouts()
    app.installEventFilter(layouts)
    try:
        for _ in range(SETTLE_PASSES):
            layouts.seen = 0
            QCoreApplication.processEvents()
            if not layouts.seen:
                return
        raise TimeoutError("the page kept laying itself out")
    finally:
        app.removeEventFilter(layouts)


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
        page.bar.setValue(page.bar.maximum())  # as a finished run leaves it: the percentage on the accent chunk (#203)
        missing = str(page.ctx.samples(BOARD_MODEL, "NG")[0]["id"])  # the label editor on its box, selected
        rows = range(page.samples.rowCount())
        page.samples.selectRow(next(r for r in rows if cell_text(page.samples, r, 0) == missing))
        wait_until(page.editor.idle)  # its image and boxes, read on a pool thread
        page.editor.view.choose(0)
        if not page.editor.draw_btn.isChecked():  # Draw mode on: the button's on look in the shot and the size walk
            page.editor.draw_btn.click()
    elif title == "Logs & Export":
        page.d_from.setDate(QDate(2025, 12, 25))
        page.d_to.setDate(QDate(2026, 1, 8))
        page.refresh()
    elif title == "Settings":
        page.ws.setText(FIXED_WORKSPACE)


def show_view(win: MainWindow, title: str, view: str | None) -> None:
    """`title` with its `view` shown (PAGE_VIEWS); None, the view it opens on. Training's are its Datasets tab, as a
    click on the tab shows it, Freeze Dataset…'s sheet for the version after the workspace's, the Split sheet on the
    workspace's version, opened as Split and Lock Validation Set… opens it on a version not split (that one is, with no
    validation file, so the sheet is opened for it directly) with seed 7, and the blind labelling
    panel on its first image, the board model's images standing in for a calibration set of 100 (the workspace holds
    fewer): Stop closes it, the status line saying so until the next page clears it, and its What is missing tab
    (REQ-TRN-021); with None the focus is cleared, as Training opens with none, so the pages after render alike.
    Settings' are its Advanced tick ticked, then Restore Key…, Move Board Model In… and Shred Store… on the store the
    screenshot workspace's version is in, the first and last under that tick (ADR 0021). Logs & Export's is its Defect
    types tab, counted on the records the filter lists (REQ-LOG-008). AI Model
    Test's is Agreed Targets…' sheet with who agreed them typed, nothing saved (REQ-TST-008)."""
    from PySide6.QtWidgets import QApplication

    page: Any = win.pages[title]
    if title == "Training":
        if view == "blind":
            samples = page.ctx.samples(page.board_model)
            page.open_blind("", [s["uuid"] for s in samples], {s["uuid"]: str(s["path"]) for s in samples})
            wait_until(lambda: page.blind.shown is not None and page.blind._reading is None)
        else:
            page._stop_blind()
        page.working.sheet.close_sheet()
        page.versions.split.close_sheet()
        page.tabs.setCurrentIndex(0 if view is None else 2 if view == "missing" else 1)
        if view == "freeze":
            page.working.open_sheet()
        if view == "split":
            version = page.versions.rows[0]
            page.versions.split.open_for(version, page.versions.counts[version["uuid"]])
            page.versions.split.seed.setText(str(DATASET_SEED))  # not a random one, so a render does not change
        if view is None and (focus := QApplication.focusWidget()) is not None:
            focus.clearFocus()
    if title == "Logs & Export":
        page.tabs.setCurrentIndex(1 if view == "types" else 0)
        wait_until(lambda: page.counting is None)  # counted on a pool thread
    if title == "AI Model Test":
        page.targets_sheet.close_sheet()
        if view == "targets":
            page.open_targets()
            page.targets_sheet.agreed_with.setText("Acme Electronics, J. Kim (quality lead), minutes of 2026-01-01")
            page.targets_sheet.missed.clearFocus()  # no caret, which blinks, in the image
        elif (focus := QApplication.focusWidget()) is not None:
            focus.clearFocus()
    if title == "Settings":
        page.stores.close_sheet()
        steps = {"restore": page.stores.btn_restore, "move-in": page.stores.btn_move, "shred": page.stores.btn_shred}
        page.stores.advanced.setChecked(view in ("advanced", "restore", "shred"))
        if view in steps:
            steps[view].click()
        elif (focus := QApplication.focusWidget()) is not None:
            focus.clearFocus()


def render_stored(win: Any, ctx: AppContext, out: Path) -> dict[str, Path]:
    """Compare on the record `build_workspace` saved, as an Operator opens it from Inspection: beside the golden board
    it was judged against, then with that file changed, which the pane explains (REQ-CMP-003); the file is put back.
    Then as an Engineer judges it again with other thresholds: the would-be verdict beside Re-evaluate, and Save to
    Recipe's sheet with a reason typed, nothing saved (REQ-CMP-005)."""

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
            settle()
            files[name] = out / f"{name}.png"
            assert win.grab().save(str(files[name])), files[name]
    finally:
        golden.write_bytes(kept)
    return files


NEW_BOARD_MODEL = "TBOX-A2"  # the board model the New board model dialog's screenshots type, made by none of them
NEW_CUSTOMER = "Beta Boards"
GUIDE_BOARD_MODEL, GUIDE_CUSTOMER = "TBOX-C1", "Cedar Circuits"  # screen 2's, made last, after every other screenshot
GUIDE_OK, GUIDE_NG = 10, 3  # the images screen 2's box area shows copied in: too few OK images, the NG ones enough
GUIDE_UUIDS = 1_000_000  # where screen 2's ids count from, past every one the workspace was built with
GUIDE_READY = {"ok": 90, "ng": 10, "ng_boxed": 10}  # screen 3's images of the Top view, as the sketch draws them
GUIDE_SHIFT_UNTIL = "2026-10-14T07:40:00+00:00"  # the shift check Train ran counts until then (shown in UTC)
# A name the line under the name field refuses (no Latin letter or digit, AOI-TRN-054; ADR 0023): the size walk's, in
# no screenshot, as the pinned DejaVu Sans draws no Korean and another font would draw it on each machine its own way
REFUSED_BOARD_MODEL = "보드"


def pinned_store() -> dict[str, str]:
    """A new store of NEW_CUSTOMER as `create_store` returns it, its key, UUID, key id and day pinned; none is made."""
    from aoi.core import crypto

    store = {"uuid": "00000000-0000-4000-8000-0000000000b2", "customer": NEW_CUSTOMER, "key_id": "5ca1ab1e" + "0" * 24}
    return store | {"sheet": crypto.sheet(bytes(range(32))), "created_at": FIXED_TIME}


def new_board_model_dialog(win: Any, step: str) -> Any:
    """The New board model dialog as an Admin fills it for a new customer's first board model (ADR 0021): the form, or
    the recovery key step that Create would show, for `pinned_store`; or, for `refused`, the form with
    REFUSED_BOARD_MODEL typed, the line under it saying why (ADR 0023)."""
    from aoi.ui.board_model_dialog import NewBoardModelDialog

    dialog = NewBoardModelDialog(win)
    dialog.board.setText(REFUSED_BOARD_MODEL if step == "refused" else NEW_BOARD_MODEL)
    dialog.customer.setCurrentText(NEW_CUSTOMER)
    if step == "key":
        dialog.made = NEW_BOARD_MODEL
        dialog.show_key(pinned_store())
    return dialog


def clear_buttons_still(root: Any) -> None:
    """Wait until the clear button of each field under `root` has ended its fade: whole in a field that holds text,
    gone in an empty one. Qt fades it over about 300 ms, longer on a loaded machine, where a fixed wait fell short."""
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QLineEdit, QToolButton

    buttons = [b for b in root.findChildren(QToolButton) if b.metaObject().className() == "QLineEditIconButton"]

    def still() -> bool:
        return all(
            float(b.property("opacity")) == (1.0 if isinstance(f := b.parent(), QLineEdit) and f.text() else 0.0)
            for b in buttons
        )

    deadline = time.monotonic() + CLEAR_BUTTON_WAIT_S
    while not still() and time.monotonic() < deadline:
        QTest.qWait(20)


def store_key_dialog(win: Any) -> Any:
    """Settings' New Store… recovery key dialog for `pinned_store` (ADR 0021)."""
    from aoi.ui.pages.recovery_key import RecoveryKeyDialog

    return RecoveryKeyDialog(win, win.ctx, pinned_store(), lambda e: None, win.status)


def render_dialogs(win: Any, out: Path) -> dict[str, Path]:
    """The New board model dialog's form and its recovery key step (NEW_BOARD_MODEL_SHOTS), as the Admin opens it."""
    files = {}
    win.set_user("admin")
    for name, step in NEW_BOARD_MODEL_SHOTS.items():
        dialog = new_board_model_dialog(win, step)
        dialog.show()
        settle()
        if (focus := dialog.focusWidget()) is not None:
            focus.clearFocus()  # no caret, which blinks, in the image
        clear_buttons_still(dialog)  # the customer's clear button whole, as it fades in after the text is set
        settle()
        files[name] = out / f"{name}.png"
        assert dialog.grab().save(str(files[name])), files[name]
        dialog.recovery.clear()
        dialog.steps.setCurrentWidget(dialog.form)
        dialog.close()
        dialog.deleteLater()
    return files


def guide_at_3(ctx: Any) -> Callable[[str | None], int | None]:
    """`ctx.guide_step` with GUIDE_BOARD_MODEL at screen 3, Train."""
    real = ctx.guide_step

    def step(board_model: str | None) -> int | None:
        return 3 if board_model == GUIDE_BOARD_MODEL else real(board_model)

    return step


def guide_ready(ctx: Any) -> Callable[..., Any]:
    """`ctx.missing` with GUIDE_BOARD_MODEL's first three lines met, as GUIDE_READY counts them, for screen 3."""
    import dataclasses

    real = ctx.missing

    def missing(board_model: str, trial: bool | None = None) -> Any:
        found = real(board_model, trial)
        if board_model != GUIDE_BOARD_MODEL:
            return found
        needs = tuple(dataclasses.replace(n, have=GUIDE_READY.get(n.key, n.have)) for n in found.needs)
        return dataclasses.replace(found, view="Top", needs=needs)

    return missing


def guide_made() -> dict[str, Any]:
    """What Train made for GUIDE_BOARD_MODEL, as `AppContext.guide_result` gives it, pinned to the sketch's figures:
    v1.0 (Trial) trained on 40 OK and 7 NG images, 0 of 3 defects missed and 1 of 50 false calls on those kept apart,
    and a shift check passed."""
    from aoi.core import stats

    rates = {"missed_defects": stats.rate(0, 3), "false_calls": stats.rate(1, 50)}
    return {
        "dataset": {"view": "Top"},
        "model": {"version": "v1.0 (Trial)"},
        "held": {"ok": 50, "ng": 3},
        "trained": {"ok": 40, "ng": 7},
        "run": {"metrics": {"rates": rates}},
        "shift": {"state": "passed", "until": GUIDE_SHIFT_UNTIL, "check": None, "hours": 8},
    }


def guide_steps(win: Any, dataset: Path) -> Iterator[str]:
    """Home's first-run guide (B5) in each state of GUIDE_SHOTS in turn, its name yielded with the window laid out:
    with no board model in the header, as a workspace with none shows it, screen 1 with NEW_BOARD_MODEL and NEW_CUSTOMER
    typed by the Admin, the recovery key Create would show for `pinned_store` and screen 1 greyed for the Engineer;
    then screen 2 for GUIDE_BOARD_MODEL, made in GUIDE_CUSTOMER's store, with no image, and with GUIDE_OK OK and
    GUIDE_NG NG images of `dataset` in, the box area on the first NG image; then screen 3 for it, before Train and with
    what Train made. Screen 3's reads are pinned (`guide_step` 3, `guide_ready`, `guide_made`), as a training in the
    render would take minutes and give rates that differ from machine to machine. Then the header's board model back.
    For the screenshots and the size walk alike; screen 2's board model stays, so it comes after every other
    screenshot."""
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication

    from aoi.core.imaging import list_images
    from tools.make_synthetic_dataset import ng_type

    ctx, guide = win.ctx, win.pages["Home"].guide
    ids = counted_uuids(GUIDE_UUIDS)
    win.bm_combo.setCurrentIndex(-1)
    try:
        for name, (role, step) in GUIDE_SHOTS.items():
            win.set_user(role)
            win.statusBar().clearMessage()
            pins = ExitStack()  # screen 3's reads, pinned while its state is shown
            if step in ("train", "trained"):
                pins.enter_context(mock.patch.object(ctx, "guide_step", guide_at_3(ctx)))
                pins.enter_context(mock.patch.object(ctx, "missing", guide_ready(ctx)))
            if step == "trained":
                pins.enter_context(mock.patch.object(ctx, "guide_result", lambda bm: guide_made()))
            with mock.patch("uuid.uuid4", side_effect=ids), mock.patch("aoi.core.crypto.new_key", guide_key):
                if step == "images":
                    ctx.create_customer_board_model(GUIDE_BOARD_MODEL, GUIDE_CUSTOMER)
                    win.select_board_model(GUIDE_BOARD_MODEL)
                if step == "boxes":
                    ok = list_images(dataset / "train" / "ok")[:GUIDE_OK]
                    ctx.import_samples(GUIDE_BOARD_MODEL, [str(p) for p in ok], "OK")
                    for p in list_images(dataset / "train" / "ng")[:GUIDE_NG]:
                        ctx.import_samples(GUIDE_BOARD_MODEL, [str(p)], "NG", ng_type(p))
            assert win.navigate("Home")
            win.pages["Home"].on_show()  # what was made or copied above shown, as a page shown again shows it
            if role == "admin" and step == "form":
                guide.name.setText(NEW_BOARD_MODEL)
                guide.customer.setText(NEW_CUSTOMER)
            if step == "key":
                guide.show_key(NEW_BOARD_MODEL, pinned_store())
            while guide.images.reading is not None:  # the box area's NG image, read on a pool thread
                QTest.qWait(20)
            settle()
            if (focus := QApplication.focusWidget()) is not None:
                focus.clearFocus()  # no caret, which blinks, in the image
            settle()
            yield name
            pins.close()
            if step == "key":  # forgotten unsaved, as no Admin may: a screenshot's key is pinned, of no store
                guide.recovery.clear()
                guide.reset()
                guide.holding_changed.emit(False)
    finally:
        win.bm_combo.setCurrentText(BOARD_MODEL)


def render_guide(win: Any, dataset: Path, out: Path) -> dict[str, Path]:
    """The first-run guide's screenshots (GUIDE_SHOTS), in the states `guide_steps` leaves it in."""
    files = {}
    for name in guide_steps(win, dataset):
        files[name] = out / f"{name}.png"
        assert win.grab().save(str(files[name])), files[name]
    return files


def render_presenter(win: Any, dataset: Path, out: Path) -> dict[str, Path]:
    """The presenter theme (REQ-SET-008), switched on as an Admin does it, with Settings' tick, and PRESENTER_SHOTS in
    it, each page as `prepare` leaves it; then PRESENTER_SMALL_SHOTS in a window of SMALL_SIZE logical pixels, at any
    scale, where the theme takes its 16 pt size; then the window back at its size and the theme switched off again with
    the header's Exit presenter theme."""

    files = {}
    size = win.size()
    win.set_user("admin")
    assert win.navigate("Settings")
    win.pages["Settings"].presenter.click()
    try:
        for name, (title, role) in [*PRESENTER_SHOTS.items(), *PRESENTER_SMALL_SHOTS.items()]:
            if name == next(iter(PRESENTER_SMALL_SHOTS)):
                win.resize(*SMALL_SIZE)
            win.set_user(role)
            win.statusBar().clearMessage()
            assert win.navigate(title), title
            prepare(win, title, dataset)
            settle()
            files[name] = out / f"{name}.png"
            assert win.grab().save(str(files[name])), files[name]
    finally:
        win.resize(size)
        win.set_user("admin")
        win.exit_presenter.click()
    return files


def render_pages(
    ctx: AppContext, dataset: Path, out: Path, size: tuple[int, int] = (1920, 1080), scale: float = 1.0
) -> dict[str, Path]:
    """Render every page for every role that may open it into ``out``, then the stored Compare states and the presenter
    theme's shots; returns {"home-operator": path, ...}.
    ``size`` is the screen in pixels: with ``scale`` (QT_SCALE_FACTOR, set before Qt starts) the window measures
    ``size / scale`` logical pixels, so the image still measures ``size``."""
    from PySide6.QtTest import QTest

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
            settle()
            name = f"{slug(title)}-{role.lower()}"
            files[name] = out / f"{name}.png"
            assert win.grab().save(str(files[name])), files[name]
            for view in PAGE_VIEWS.get(title, ()):
                show_view(win, title, view)
                settle()
                name = f"{slug(title)}-{view}-{role.lower()}"
                files[name] = out / f"{name}.png"
                assert win.grab().save(str(files[name])), files[name]
            show_view(win, title, None)
    files.update(render_stored(win, ctx, out))
    files.update(render_presenter(win, dataset, out))
    files.update(render_dialogs(win, out))
    files.update(render_guide(win, dataset, out))  # last: it makes a board model, and selects the one before again
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
    sizes = Counter(f"{image.width()}x{image.height()}" for image in (QImage(str(f)).size() for f in files.values()))
    print(", ".join(f"{n} images of {size} px" for size, n in sizes.items()), f"in {out}")  # 1366 x 768 too (#104)
    return 0


if __name__ == "__main__":
    sys.exit(main())
