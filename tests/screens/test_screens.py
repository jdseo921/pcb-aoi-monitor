"""Offscreen screenshots of every page for every role, compared with the approved images (REQ-SET-004; S21a).

`tools/render_screens.py` draws the pages on the synthetic workspace at 1920x1080 (Engineering standard, "Screen
code"), with DejaVu Sans and no hinting, a pixel-based stand-in for the trained AI model (`PinnedModel`, whose verdict
and boxes do not depend on the CPU) and pinned values for the two numbers the float alignment moves, so every Linux
machine draws the same pixels; the comparison runs on Linux only, since Windows draws Segoe UI.

A pixel differs when one of its channels moves by more than LEVELS from the approved image, and a page fails when more
than MAX_CLUSTER differing pixels touch (8-connected). One changed character makes such a cluster: at 14 pt with the
pinned font, any one changed digit makes one of 24 px or more in normal and muted text and of 10 px or more in
disabled grey, and any other one-letter change one of 5 px or more, but for i/l and the pairs ./, and :/; (2 to 4 px).
Noise does not: three renders on the machine the approved images come from drew every page pixel for pixel alike, and
renders with OpenCV, NumPy and Qt held to older CPU code moved the aligned board picture by at most 42 levels, at
single pixels. So a cluster of up to MAX_CLUSTER pixels is margin for anti-aliasing that differs between machines, and
how many such specks a page has does not matter. The rendered images, with a diff image per failing page, stay in
tests/screens/actual/ for CI to upload; an intended change is approved with `python tools/render_screens.py
--approve`, and Jay approves the images by merging.
"""

from __future__ import annotations

import itertools
import json
import shutil
import sys
from pathlib import Path

import cv2
import numpy as np
import pytest
from PySide6.QtGui import QImage
from PySide6.QtWidgets import QApplication, QLabel

from aoi.core.imaging import load_image, save_image
from aoi.core.services import AppContext
from aoi.ui import theme
from aoi.ui.main_window import NAV
from tools import render_screens

ROOT = Path(__file__).resolve().parents[2]
ACTUAL_DIR = ROOT / "tests" / "screens" / "actual"
SIZE = (1920, 1080)
LEVELS = 40  # a pixel differs when one of its channels moves by more than this, of 255
MAX_CLUSTER = 4  # a page fails when more differing pixels than this touch (module docstring)
APPROVE = "python tools/render_screens.py --approve"
LINUX = sys.platform == "linux"


def _changed_areas(approved: np.ndarray, actual: np.ndarray) -> tuple[list[int], np.ndarray]:
    """The sizes of the clusters of over MAX_CLUSTER touching pixels that differ by more than LEVELS in any channel,
    largest first (none: the page passes), and the mask of every differing pixel."""
    mask = np.abs(approved.astype(np.int16) - actual.astype(np.int16)).max(axis=2) > LEVELS
    _, _, stats, _ = cv2.connectedComponentsWithStats(mask.astype(np.uint8), connectivity=8)
    return sorted((int(n) for n in stats[1:, cv2.CC_STAT_AREA] if n > MAX_CLUSTER), reverse=True), mask


def _diff_image(actual: np.ndarray, mask: np.ndarray) -> np.ndarray:
    """The new image at half brightness with the differing pixels in NG red, for a reviewer."""
    out = (actual // 2).astype(np.uint8)
    red = [int(theme.NG_COLOR[i : i + 2], 16) for i in (1, 3, 5)]
    out[mask] = red[::-1]  # load_image and save_image work in BGR
    return out


def test_req_set_004_the_render_workspace_inspects_with_the_pinned_model(screens: tuple[AppContext, Path]) -> None:
    """The stored inspection came from `PinnedModel`: its time is FIXED_MS, which no real run reports, its score is
    the pinned one (6 against the threshold 3), and it was judged on FIXED_SSIM and FIXED_INLIERS; `prepare()` asserts
    the time for the Inspection and Compare pages. So a render whose pin was dropped fails here and in the renders, on
    both platforms, not only by the pixels it changes."""
    ctx, _ = screens
    record = ctx.inspections(board_model=render_screens.BOARD_MODEL)[0]
    assert json.loads(record["metrics"])["elapsed_ms"] == render_screens.FIXED_MS
    assert record["result"] == "NG" and record["score"] == pytest.approx(2.0)  # 96 levels / PINNED_SCALE / threshold
    checks = {c["metric"]: c["value"] for c in ctx.db.checks_for(record["id"])}
    pinned = (render_screens.FIXED_SSIM, render_screens.FIXED_INLIERS)
    assert (checks["SSIM similarity"], checks["Alignment inliers"]) == pinned


@pytest.mark.skipif(not LINUX, reason="the approved images are drawn with DejaVu Sans on Linux; Windows draws Segoe UI")
def test_req_set_004_every_page_matches_its_approved_image(screens: tuple[AppContext, Path], qapp: object) -> None:
    """Every page, for every role that may open it, at 1920x1080, matches its approved image as the module docstring
    says: no more than MAX_CLUSTER touching pixels differ."""
    ctx, dataset = screens
    shutil.rmtree(ACTUAL_DIR, ignore_errors=True)
    with render_screens.pinned_rendering(qapp, render_screens.TEST_FONT):
        files = render_screens.render_pages(ctx, dataset, ACTUAL_DIR, SIZE)
    assert len(files) == sum(len(cls.roles) for _, cls in NAV) + len(render_screens.STORED_STATES)
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
            areas, mask = _changed_areas(before, after)
            if areas:
                diff = path.with_suffix(".diff.png")
                save_image(diff, _diff_image(after, mask))
                changed = f"{len(areas)} area(s) of over {MAX_CLUSTER} touching pixels changed, up to {areas[0]} px"
                failures.append(f"{name}: {changed}; see {diff.name}")
    hint = f"the new images are in {ACTUAL_DIR}; an intended change is approved with: {APPROVE}"
    assert not failures, "\n".join([*failures, hint])
    shutil.rmtree(ACTUAL_DIR)  # nothing to review


@pytest.mark.skipif(not LINUX, reason="the approved images are drawn with DejaVu Sans on Linux; Windows draws Segoe UI")
def test_req_set_004_one_changed_word_or_digit_fails_a_page(qapp: QApplication) -> None:
    """The comparison fails a page on one changed word of a 14 pt label and on any one changed digit of a number, in
    normal, muted and disabled text, and on 5 touching pixels; it passes a page against itself and against specks of
    up to MAX_CLUSTER touching pixels all over it (the measurements in the module docstring)."""
    page = load_image(render_screens.APPROVED_DIR / "settings-admin.png")
    specks = page.copy()
    specks[20:1060:9, 20:1900:9] ^= 255  # single pixels all over the page
    for dy, dx in ((0, 0), (0, 1), (1, 0), (1, 1)):  # and squares of four touching pixels between them
        specks[25 + dy : 1060 : 18, 25 + dx : 1900 : 18] ^= 255
    assert _changed_areas(page, page.copy())[0] == [] and _changed_areas(page, specks)[0] == []
    specks[1070, 900:905] ^= 255
    assert _changed_areas(page, specks)[0] == [5]

    def label(text: str, color: str) -> np.ndarray:
        shown = QLabel(text)
        shown.setStyleSheet(f"background: {theme.BG}; color: {color};")
        shown.resize(300, 40)
        image = shown.grab().toImage().convertToFormat(QImage.Format.Format_RGB888)
        rows = np.frombuffer(image.constBits(), np.uint8, image.sizeInBytes()).reshape(40, image.bytesPerLine())
        return rows[:, : 300 * 3].reshape(40, 300, 3).copy()

    with render_screens.pinned_rendering(qapp, render_screens.TEST_FONT):
        for color in (theme.TEXT, theme.TEXT_MUTED, theme.TEXT_DISABLED):
            assert _changed_areas(label("Log retention (days)", color), label("Log retention (hours)", color))[0]
            digits = {d: label(f"0.93{d}7", color) for d in "0123456789"}
            for a, b in itertools.permutations(digits, 2):
                assert _changed_areas(digits[a], digits[b])[0], (color, a, b)
