"""Offscreen screenshots of every page for every role, compared with the approved images (REQ-SET-004; S21a).

`tools/render_screens.py` draws the pages on the synthetic workspace at 1920x1080 (Engineering standard, "Screen
code"), with DejaVu Sans and no hinting, so every Linux machine draws the same pixels; the comparison runs on Linux
only, since Windows draws Segoe UI. A page fails when more than PIXEL_SHARE of its pixels differ from the approved
image by more than LEVELS in any channel: anti-aliasing can move a few pixels by a few levels between FreeType builds,
while a changed word, a moved control or a changed colour moves many pixels by many levels (a changed digit in one
label is about 0.01 % of a page, a changed column of file names about 1 %). The rendered images, with a diff image per
failing page, stay in tests/screens/actual/ for CI to upload; an intended change is approved with
`python tools/render_screens.py --approve`, and Jay approves the images by merging.
"""

from __future__ import annotations

import shutil
import sys
from collections.abc import Iterator
from pathlib import Path

import numpy as np
import pytest

from aoi.core.imaging import load_image, save_image
from aoi.core.services import AppContext
from aoi.ui import theme
from aoi.ui.main_window import NAV
from tools import render_screens

ROOT = Path(__file__).resolve().parents[2]
ACTUAL_DIR = ROOT / "tests" / "screens" / "actual"
SIZE = (1920, 1080)
LEVELS = 40  # a pixel differs when one of its channels moves by more than this, of 255
PIXEL_SHARE = 0.005  # a page fails when more than this share of its pixels differ
APPROVE = "python tools/render_screens.py --approve"
LINUX = sys.platform == "linux"


@pytest.fixture(scope="module")
def screens(tmp_path_factory: pytest.TempPathFactory) -> Iterator[tuple[AppContext, Path]]:
    """The synthetic workspace the pages are rendered on, built once for this module; stored times are shown as UTC."""
    restore_zone = render_screens.pin_time_zone()
    root = tmp_path_factory.mktemp("screens")
    ctx = render_screens.build_workspace(root)
    yield ctx, root / "dataset"
    ctx.close()
    restore_zone()


def _differing(approved: np.ndarray, actual: np.ndarray) -> tuple[float, np.ndarray]:
    """The share of pixels that differ by more than LEVELS in any channel, and the mask of those pixels."""
    mask = np.abs(approved.astype(np.int16) - actual.astype(np.int16)).max(axis=2) > LEVELS
    return float(mask.mean()), mask


def _diff_image(actual: np.ndarray, mask: np.ndarray) -> np.ndarray:
    """The new image at half brightness with the differing pixels in NG red, for a reviewer."""
    out = (actual // 2).astype(np.uint8)
    red = [int(theme.NG_COLOR[i : i + 2], 16) for i in (1, 3, 5)]
    out[mask] = red[::-1]  # load_image and save_image work in BGR
    return out


@pytest.mark.skipif(not LINUX, reason="the approved images are drawn with DejaVu Sans on Linux; Windows draws Segoe UI")
def test_req_set_004_every_page_matches_its_approved_image(screens: tuple[AppContext, Path], qapp: object) -> None:
    """Every page, for every role that may open it, at 1920x1080, within the tolerance in the module docstring."""
    ctx, dataset = screens
    shutil.rmtree(ACTUAL_DIR, ignore_errors=True)
    with render_screens.pinned_rendering(qapp, render_screens.TEST_FONT):
        files = render_screens.render_pages(ctx, dataset, ACTUAL_DIR, SIZE)
    assert len(files) == sum(len(cls.roles) for _, cls in NAV)
    approved = {p.stem for p in render_screens.APPROVED_DIR.glob("*.png")}
    assert set(files) == approved, f"pages and approved images differ: {sorted(set(files) ^ approved)}; run {APPROVE}"
    failures = []
    for name, path in sorted(files.items()):
        before, after = load_image(render_screens.APPROVED_DIR / f"{name}.png"), load_image(path)
        if after.shape[:2] != SIZE[::-1]:
            failures.append(f"{name}: rendered {after.shape[1]}x{after.shape[0]}, not {SIZE[0]}x{SIZE[1]}")
        elif before.shape != after.shape:
            failures.append(f"{name}: the approved image is {before.shape[1]}x{before.shape[0]}")
        else:
            share, mask = _differing(before, after)
            if share > PIXEL_SHARE:
                diff = path.with_suffix(".diff.png")
                save_image(diff, _diff_image(after, mask))
                failures.append(f"{name}: {share:.2%} of the pixels differ (limit {PIXEL_SHARE:.1%}); see {diff.name}")
    hint = f"the new images are in {ACTUAL_DIR}; an intended change is approved with: {APPROVE}"
    assert not failures, "\n".join([*failures, hint])
    shutil.rmtree(ACTUAL_DIR)  # nothing to review
