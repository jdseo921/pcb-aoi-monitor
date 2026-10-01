"""Render every page offscreen, for every role that may open it, into PNG files (REQ-SET-004; stage S21).

``pytest tests/screens`` renders at 1920x1080 and compares with ``tests/screens/approved/``; a page that differs
fails, and CI uploads the new images. ``python tools/render_screens.py --approve`` rewrites the approved set after an
intended change of a screen: the images are generated files, and Jay approves them by merging. ``--out DIR --size
3840x2160 --scale 2`` renders a review set at another screen size and scale.

The pages are rendered on the synthetic workspace: the board model TINY with the seeded dataset's samples, a tiny AI
model trained for a few epochs (seeded, so its threshold is the same in every run), one inspected NG board, one
recipe revision with one ROI. Everything else that would change from run to run is pinned: record ids and the suffix
of every sample's file name come from a counter instead of uuid4(), every stored time is FIXED_TIME and is shown as
UTC, the inspection time is FIXED_MS, the Logs filter covers that week, the Settings page shows FIXED_WORKSPACE, and
the Inspection page is rendered with auto-save off so the render adds no record. On Linux the pages are drawn with
DejaVu Sans without hinting, so every Linux machine draws the same pixels; Windows draws Segoe UI, so there the tests
check sizes and contrast only.
"""

from __future__ import annotations

import argparse
import itertools
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

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:  # run as a script: the repository root holds the ``aoi`` and ``tools`` packages
    sys.path.insert(0, str(ROOT))

APPROVED_DIR = ROOT / "tests" / "screens" / "approved"
BOARD_MODEL = "TINY"
FIXED_TIME = "2026-01-01T09:00:00+00:00"  # every stored time, so a render does not change with the clock
FIXED_MS = 480.0  # the inspection time Inspection and Compare show
FIXED_WORKSPACE = "C:/AOI_Workspace"  # what the Settings page shows instead of the temporary folder
TEST_FONT = '"DejaVu Sans"'  # the font the approved images are drawn with (Linux)
DATASET_OK, DATASET_NG, DATASET_SEED = 30, 14, 7  # as tests/conftest.py
TINY_EPOCHS, TINY_IMAGE_SIZE = 6, 64

if TYPE_CHECKING:
    from PySide6.QtWidgets import QApplication

    from aoi.core.services import AppContext
    from aoi.ui.main_window import MainWindow


def slug(title: str) -> str:
    """ "Logs & Export" -> "logs-export"."""
    return re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")


def counted_uuids() -> Iterator[uuid.UUID]:
    """What uuid4() returns while the workspace is built: 000001…, 000002…, so the six hex digits that import_samples
    adds to a sample's file name, and every record id, are the same in every run."""
    for n in itertools.count(1):
        yield uuid.UUID(int=(n << 104) | n, version=4)


def build_workspace(root: Path) -> AppContext:
    """The synthetic workspace the pages are rendered on; see the module docstring."""
    from aoi.config import Settings
    from aoi.core.imaging import list_images
    from aoi.core.recipe import ROI
    from aoi.core.services import AppContext
    from tools.make_synthetic_dataset import write_dataset

    os.environ["AOI_WORKSPACE"] = str(root / "default_workspace")  # settings.json is saved there, never in ~/
    dataset = root / "dataset"
    write_dataset(dataset, DATASET_OK, DATASET_NG, DATASET_SEED)
    with mock.patch("uuid.uuid4", side_effect=counted_uuids()):
        ctx = AppContext(Settings(workspace=str(root / "workspace"), device="cpu"))
        ctx.set_user("engineer", "Engineer")
        ctx.import_samples(BOARD_MODEL, [str(p) for p in list_images(dataset / "train" / "ok")], "OK")
        ctx.import_samples(BOARD_MODEL, [str(p) for p in list_images(dataset / "train" / "ng")], "NG")
        ctx.train(BOARD_MODEL, epochs=TINY_EPOCHS, image_size=TINY_IMAGE_SIZE)
        recipe = ctx.recipe(BOARD_MODEL)[1]
        recipe.rois.append(ROI("R1", "Presence", 40, 40, 120, 80))
        ctx.save_recipe(recipe)
        ctx.inspect_file(BOARD_MODEL, str(ng_board(dataset)))  # one record for Logs, one alarm for Inspection
    for table, column in (
        ("board_models", "created_at"),
        ("samples", "added_at"),
        ("models", "created_at"),
        ("recipes", "created_at"),
        ("inspections", "time"),
        ("alarms", "time"),
    ):  # the audit trail keeps its real times: it is append-only and no page shows it
        ctx.db.execute(f"UPDATE {table} SET {column}=?", (FIXED_TIME,))  # noqa: S608 - fixed table names above
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
    """The stylesheet with ``font`` as the family (none: the theme's own list) and hinting off, so a render does not
    depend on the machine's fonts; the application's stylesheet and font are put back afterwards."""
    from PySide6.QtGui import QFont

    from aoi.ui import theme

    before_sheet, before_font = app.styleSheet(), QFont(app.font())
    pinned = QFont(before_font)
    pinned.setHintingPreference(QFont.HintingPreference.PreferNoHinting)
    app.setFont(pinned)
    app.setStyleSheet(theme.stylesheet(FONT_FAMILY=font) if font else theme.QSS)
    try:
        yield
    finally:
        app.setStyleSheet(before_sheet)
        app.setFont(before_font)


@contextmanager
def fixed_inspection_time() -> Iterator[None]:
    """Every inspection reports FIXED_MS, so the time Inspection and Compare show does not change the pixels."""
    from aoi.core.inspector import Inspector

    real = Inspector.inspect

    def inspect(self: Inspector, *args: Any, **kwargs: Any) -> Any:
        res = real(self, *args, **kwargs)
        res.elapsed_ms = FIXED_MS
        return res

    with mock.patch.object(Inspector, "inspect", inspect):
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

    page: Any = win.pages[title]
    if title == "Inspection" and page.last is None:
        page.autosave.setChecked(False)  # the render adds no record and no alarm
        page._set_queue([ng_board(dataset)])
        page.next_board()
        wait_until(lambda: page.last is not None)
    elif title == "Compare" and page.res is None:
        page.set_test(str(ng_board(dataset)))
        wait_until(lambda: page.res is not None)
    elif title == "Logs & Export":
        page.d_from.setDate(QDate(2025, 12, 25))
        page.d_to.setDate(QDate(2026, 1, 8))
        page.refresh()
    elif title == "Settings":
        page.ws.setText(FIXED_WORKSPACE)


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
    with fixed_inspection_time():
        for role in ROLES:
            win.set_role(role, role.lower())
            for title, page in win.pages.items():
                if role not in page.roles:
                    continue
                assert win.navigate(title), title
                prepare(win, title, dataset)
                QApplication.processEvents()
                name = f"{slug(title)}-{role.lower()}"
                files[name] = out / f"{name}.png"
                assert win.grab().save(str(files[name])), files[name]
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
