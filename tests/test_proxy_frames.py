"""How the industry scenarios change a board's photo (#459), on boards drawn here: no dataset runs in CI."""

from __future__ import annotations

import random

import cv2
import numpy as np
import pytest

from tools import proxy_frames as pf


def board(seed: int = 0, size: tuple[int, int] = (120, 160)) -> np.ndarray:
    """A drawn board: green with a few dark parts, so a warp or a change shows."""
    rng = np.random.default_rng(seed)
    img = np.full((*size, 3), (40, 120, 40), np.uint8)
    for _ in range(6):
        x, y = int(rng.integers(10, size[1] - 30)), int(rng.integers(10, size[0] - 30))
        cv2.rectangle(img, (x, y), (x + 18, y + 12), (30, 30, 30), -1)
    return img


def test_459_placed_moves_the_image_and_its_mask_together() -> None:
    img = board()
    mask = np.zeros(img.shape[:2], np.uint8)
    mask[50:60, 70:80] = 255
    out, moved = pf.placed(img, mask, 0.0, 10, 5)
    assert out.shape == img.shape and moved is not None
    ys, xs = np.nonzero(moved)
    assert (ys.min(), xs.min()) == (55, 80)
    assert set(np.unique(moved)) <= {0, 255}  # nearest neighbour: still a mask
    turned, back = pf.placed(img, mask, 180.0, 0, 0)
    assert back is not None and back[60:70, 80:90].any() and not back[50:60, 70:80].any()
    assert pf.placed(img, None, 3.0, 0, 0)[1] is None


def test_459_drift_starts_at_nothing_and_ends_at_the_shifts_full_drift() -> None:
    assert pf.drift(0, 2000) == {"light": 1.0, "warm": 0.0, "dx": 0.0, "angle": 0.0, "blur": 0.0}
    end = pf.drift(1999, 2000)
    assert end["light"] == pytest.approx(0.90) and end["dx"] == pytest.approx(15) and end["angle"] == pytest.approx(0.5)
    img = board()
    out, _ = pf.drifted(img, None, end)
    assert out.mean() < img.mean()  # 10 % less light
    assert np.array_equal(pf.drifted(img, None, pf.drift(0, 2000))[0], img)


def test_459_placement_turns_one_board_in_200_backwards() -> None:
    rng = random.Random(1)
    got = [pf.placement(rng) for _ in range(4000)]
    back = [p for p in got if abs(pf.angle_of(p)) > 90]
    assert 5 <= len(back) <= 40
    assert all(abs(pf.angle_of(p)) <= 5 for p in got if p not in back)
    assert all(abs(p["dx"]) <= 60 and abs(p["dy"]) <= 60 for p in got)


def test_459_reshot_changes_a_board_a_little() -> None:
    img = board()
    a, _ = pf.reshot(img, None, random.Random(3))
    b, _ = pf.reshot(img, None, random.Random(3))
    assert np.array_equal(a, b) and not np.array_equal(a, img)
    assert np.abs(a.astype(int) - img.astype(int)).mean() < 8


def test_459_bad_frames_and_variations_change_the_image_and_keep_its_size() -> None:
    img = board(size=(240, 320))
    frames = pf.bad_frames()
    assert {"overexposed", "underexposed", "motion blur", "out of focus", "hand over the board"} <= set(frames)
    for name, f in frames.items():
        out = f(img)
        assert not np.array_equal(out, img), name
        assert out.shape == img.shape or name == "much smaller image", name
    assert frames["much smaller image"](img).shape[0] < img.shape[0] // 4
    for name, v in pf.variations().items():
        a, b = v(img, random.Random(5)), v(img, random.Random(5))
        assert a.shape == img.shape and np.array_equal(a, b) and not np.array_equal(a, img), name
    rev = pf.revised(img)
    assert rev.shape == img.shape and not np.array_equal(rev, img)
    assert np.array_equal(rev[:100], img[:100])  # the revision changes one area only
