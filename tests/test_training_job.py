"""REQ-TRN-008 (stage S40): what lets a training run report its percent and time left at least every 10 s: the Golden
board's median worked out a step of rows at a time, the time left counted from the steps of each kind timed so far,
and a training step and a map timed before the run's first. Results on the synthetic boards prove a code path; they
are never quoted as accuracy."""

from __future__ import annotations

from functools import partial
from pathlib import Path

import numpy as np
import pytest
import torch

from aoi.core import anomaly, golden, run_progress
from aoi.core.imaging import list_images, load_image
from aoi.core.run_progress import RunProgress
from aoi.core.services import ALIGNING


class Clock:
    """The seconds on a fake clock, which a test or the slow steps move on."""

    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


def test_req_trn_008_golden_board_in_steps() -> None:
    """A band's median is worked out a step of rows at a time, with a call after each, so a run reports and can stop
    between steps: the Golden board is the median of every board to the bit, in one step of STEP_BYTES, in steps of 3
    rows of bands of 10, and in steps of one row, after a probe has timed a step on noise."""
    rng = np.random.default_rng(2)
    boards = [rng.integers(0, 256, (48, 64, 3), dtype=np.uint8) for _ in range(21)]
    exact = np.median(np.stack(boards), axis=0).astype(np.uint8)
    row = 21 * 64 * 3  # one row of every board
    for budget, step, steps in ((golden.BAND_BYTES, golden.STEP_BYTES, 1), (10 * row, 3 * row, 19), (10 * row, 1, 48)):
        median = golden.Median(21, (48, 64), budget, step)
        assert median.probe() >= 0
        stepped: list[int] = []
        while not median.done:
            for board in boards:
                median.add(board, partial(stepped.append, 1))
        assert (len(stepped), median.steps) == (steps, steps) and np.array_equal(median.board, exact), step


def test_req_trn_008_time_left_from_the_steps_timed(monkeypatch: pytest.MonkeyPatch) -> None:
    """The time left counts each kind's steps still to do at the mean time its steps took so far, and is unknown while
    a kind still to come is untimed; a step timed only to estimate stands in for its kind until the kind's first step
    ends, which replaces it. The percent is the time gone over the time gone and left, at most 99 until the run ends,
    and never falls: a step slower than the mean moves the end away and the percent stays."""
    clock = Clock()
    monkeypatch.setattr(run_progress, "clock", clock)
    eta, phase = run_progress.Eta({"read": 2, "step": 3}), ALIGNING.fill(count=2)
    assert (eta.left(), eta.report(phase).percent) == (None, 0)
    clock.now = 4.0
    eta.tick("read")  # 4 s
    assert eta.left() is None  # no training step timed yet
    eta.sample("step", 10.0)
    assert eta.left() == 4 + 3 * 10
    clock.now = 8.0
    eta.tick("read")  # 4 s, from the sample on
    clock.now = 10.0
    eta.tick("step")  # 2 s, in the sample's place
    assert eta.report(phase) == RunProgress(int(100 * 10 / 14), 2 * 2, phase)
    clock.now = 50.0
    eta.tick("step")  # 40 s: a mean of 21 s, and 50 s of 71 s gone, 70 %
    assert (eta.left(), eta.report(phase).percent) == (21, 71)
    clock.now = 51.0
    eta.tick("step")
    assert (eta.left(), eta.report(phase).percent) == (0, 99)


def test_req_trn_008_probe_leaves_the_ai_model_as_without_it(synthetic_dataset: Path) -> None:
    """Timing a training step and a map on a throwaway network leaves the AI model a run then trains the same, to the
    bit, as without it: the probe draws from the random sources before training seeds them."""
    ok = [anomaly.prepare(load_image(p), 32) for p in list_images(synthetic_dataset / "train" / "ok")[:6]]
    cfg = anomaly.TrainConfig(image_size=32, epochs=1, steps_per_epoch=2, seed=3)
    plain = anomaly.train(ok, [], cfg)
    step_s, map_s = anomaly.probe(ok[0], cfg)
    probed = anomaly.train(ok, [], cfg)
    assert min(step_s, map_s) >= 0  # Windows' clock ticks every 15.6 ms, which a 32 px map can take less than
    weights = zip(plain.net.state_dict().values(), probed.net.state_dict().values(), strict=True)
    assert all(torch.equal(a, b) for a, b in weights) and plain.meta["ok_scores"] == probed.meta["ok_scores"]
