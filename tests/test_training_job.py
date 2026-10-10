"""REQ-TRN-008 (stage S40): training runs as a job of the AppContext, not of a page, with its progress and time left
reported at least every 10 s through every phase, Cancel stopping it within 10 s with the active AI model kept, and
going on whatever page is shown. A fake clock stands for a slow station, each step taking over twice what it took at
20 MP on a 4-core cloud VM (an image read 0.86 s, docs/tests/2026-10-01-resolution-test.md; a step of the Golden
board's median of 50 images 0.85 s; a training step at 256 px 0.22 s; a map 0.53 s). Results on the synthetic boards
prove a code path; they are never quoted as accuracy."""

from __future__ import annotations

import re
import threading
from collections.abc import Callable
from functools import partial
from pathlib import Path
from typing import Any, cast

import numpy as np
import pytest
import torch
from pytestqt.qtbot import QtBot

from aoi.core import anomaly, golden, run_progress
from aoi.core.imaging import list_images, load_image
from aoi.core.jobs import Job
from aoi.core.run_progress import RunProgress
from aoi.core.services import ALIGNING, AppContext
from aoi.errors import AoiError
from aoi.ui.main_window import HomePage, MainWindow
from aoi.ui.pages.training import TrainingPage
from tests.test_train_from_version import BOARD, boards
from tools.trainable import trainable

COST = {"read": 4.0, "median": 2.0, "step": 0.5, "map": 1.5}  # the fake seconds each kind of step takes
PHASES = ("Aligning", "Building", "Golden board", "Training epoch", "Calibrating", "Saving")  # each line's start
Reports = list[tuple[float, RunProgress | str]]


class Clock:
    """The seconds on a fake clock, which a test or the slow steps move on."""

    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


def slow(ctx: AppContext, monkeypatch: pytest.MonkeyPatch) -> Clock:
    """A fake clock that each image read (the reference board's too), step of the Golden board's median, training
    step and anomaly map moves on by COST, and a Golden board of two bands of the synthetic boards' 480 rows, worked out
    100 rows a step, so a run goes through every phase."""
    clock = Clock()
    monkeypatch.setattr(run_progress, "clock", clock)

    def timed(cost: float, fn: Callable[..., Any]) -> Callable[..., Any]:
        def call(*a: Any) -> Any:
            clock.now += cost
            return fn(*a)

        return call

    monkeypatch.setattr(ctx, "_read_frozen", timed(COST["read"], ctx._read_frozen))
    monkeypatch.setattr(ctx, "load_image", timed(COST["read"], ctx.load_image))
    monkeypatch.setattr(anomaly, "augment", timed(COST["step"] / anomaly.TrainConfig.batch_size, anomaly.augment))
    monkeypatch.setattr(anomaly.AnomalyModel, "prepared_map", timed(COST["map"], anomaly.AnomalyModel.prepared_map))
    monkeypatch.setattr(golden.Median, "_work", timed(COST["median"], golden.Median._work))
    monkeypatch.setattr(golden, "BAND_BYTES", 20 * 640 * 3 * 300)  # 300 rows of 20 OK boards a band
    monkeypatch.setattr(golden, "STEP_BYTES", 20 * 640 * 3 * 100)  # 5 steps: 3 of the first band, 2 of the second
    return clock


def run(ctx: AppContext, version: str, clock: Clock, cancel_at: str = "") -> tuple[Job[Any], Reports]:
    """Train `version` as the Training page does, 2 epochs at 32 px: each report with the fake time it came at. With
    `cancel_at`, Cancel at the first report whose phase starts with it, recorded as "cancel"."""
    reports: Reports = []

    def listen(job: Job[Any]) -> None:
        def got(values: tuple[RunProgress]) -> None:
            reports.append((clock.now, values[0]))
            if cancel_at and values[0].phase.startswith(cancel_at) and not job.cancelled:
                reports.append((clock.now, "cancel"))
                job.cancel()

        job.on_progress(got)

    job = ctx.start_training(version, 2, 32, listen=listen)
    assert job.wait(300)
    return job, reports


def test_req_trn_008_progress_every_10s(
    ctx: AppContext, synthetic_dataset: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A run reports after every image read, step of the Golden board's median, training step and map, so on a slow
    station no two reports are more than 10 s apart, from its start to its end, through every phase: aligning, building
    the Golden board, its second band, each epoch and calibrating. From its second report on, a step of each kind but
    the read timed on the first image read, the time left is the time the run then takes, and the percent only grows;
    its log notes the images, the epochs and the threshold."""
    boards(ctx, synthetic_dataset, 20)
    clock = slow(ctx, monkeypatch)
    job, reports = run(ctx, trainable(ctx, BOARD), clock)
    assert job.result is not None and job.error is None
    times = [0.0] + [t for t, _ in reports] + [clock.now]
    assert max(b - a for a, b in zip(times, times[1:], strict=False)) <= 10, times
    shown = [p for _, p in reports if isinstance(p, RunProgress)]
    assert all(any(p.phase.startswith(phase) for p in shown) for phase in PHASES), sorted({p.phase for p in shown})
    assert shown[0].left_s is None and shown[0].note.startswith("Aligning 23 images")
    for t, p in reports[1:]:
        assert isinstance(p, RunProgress) and p.left_s == pytest.approx(clock.now - t, abs=0.01), (t, p)
    assert [p.percent for p in shown] == sorted(p.percent for p in shown) and shown[-1].percent == 99
    notes = [p.note for p in shown if p.note]
    assert [n.split(" ")[0] for n in notes] == ["Aligning", "Training", "Epoch", "Calibrated"], notes


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


@pytest.mark.parametrize("phase", PHASES)
def test_req_trn_008_cancel_keeps_active_model(
    phase: str, ctx: AppContext, synthetic_dataset: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Cancel in any phase stops the run within 10 s, after the step in hand, of whatever kind, or as the AI model
    saves, before it is registered: no report after it, the job ended cancelled with no result and no error, and no AI
    model file, version, Golden board or audit entry kept; the active AI model stays."""
    boards(ctx, synthetic_dataset, 20)
    version = trainable(ctx, BOARD)
    ctx.train(version, epochs=1, image_size=32)  # the active AI model
    models, active, reference = ctx.models(BOARD), ctx.db.active_model(BOARD), ctx.db.reference(BOARD)
    files, audit = sorted(ctx.settings.models_dir.rglob("*")), ctx.audit_entries()
    clock = slow(ctx, monkeypatch)
    job, reports = run(ctx, version, clock, cancel_at=phase)
    cancelled = next(t for t, p in reports if p == "cancel")
    assert reports[-1] == (cancelled, "cancel") and clock.now - cancelled <= 10, (phase, clock.now - cancelled)
    assert job.cancelled and job.result is None and job.error is None and ctx.training is job
    assert ctx.models(BOARD) == models and ctx.db.active_model(BOARD) == active
    assert ctx.db.reference(BOARD) == reference and sorted(ctx.settings.models_dir.rglob("*")) == files
    assert ctx.audit_entries() == audit


def test_req_trn_008_one_run_at_a_time(
    ctx: AppContext, synthetic_dataset: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A second run while one goes on is refused with AOI-TRN-047 and leaves the first going on to its end; once it
    has ended, a run starts again."""
    boards(ctx, synthetic_dataset, 20)
    version = trainable(ctx, BOARD)
    go = threading.Event()
    read = ctx._read_frozen
    monkeypatch.setattr(ctx, "_read_frozen", lambda *a: go.wait(60) and read(*a))
    first = ctx.start_training(version, 2, 32)
    with pytest.raises(AoiError) as second:
        ctx.start_training(version, 2, 32)
    assert second.value.code == "AOI-TRN-047" and ctx.training is first
    go.set()
    assert first.wait(300) and first.result is not None and len(ctx.models(BOARD)) == 1
    assert ctx.start_training(version, 2, 32).wait(300) and len(ctx.models(BOARD)) == 2


def test_req_trn_008_survives_page_change(
    qtbot: QtBot, ctx: AppContext, synthetic_dataset: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A run started on Training goes on while another page is shown: the header shows it on every page, and Home's
    Train AI model card too, and the header opens Training; once it ends, the header and the card hide it and Training
    shows the AI model saved."""
    boards(ctx, synthetic_dataset, 20)
    trainable(ctx, BOARD)
    go = threading.Event()
    read = ctx._read_frozen
    monkeypatch.setattr(ctx, "_read_frozen", lambda *a: go.wait(60) and read(*a))  # the run goes on until let go
    win = MainWindow(ctx)
    qtbot.addWidget(win)
    win.show()
    win.set_user("engineer")
    win._on_board_model(BOARD)
    win.navigate("Training")
    page = cast(TrainingPage, win.pages["Training"])
    page.epochs.setValue(page.epochs.minimum())
    page.input_size.setCurrentIndex(0)
    try:
        page.btn_train.click()
        win.navigate("Inspection")
        qtbot.waitUntil(lambda: win.training_link.isVisible(), timeout=10000)
        assert re.fullmatch(
            r"Training \d+ % · (estimating…|less than a minute left|about \d+ min left)", win.training_link.text()
        )
        win.navigate("Home")
        home = cast(HomePage, win.pages["Home"])
        qtbot.waitUntil(lambda: home.training_line.isVisible(), timeout=10000)
        assert re.fullmatch(r"Training running \d+ % · .+", home.training_line.text())
        win.training_link.click()
        assert win.stack.currentWidget() is page and page.btn_stop.isEnabled()
        win.navigate("Inspection")
    finally:
        go.set()
    qtbot.waitUntil(lambda: page.worker is None, timeout=300000)
    qtbot.waitUntil(lambda: not win.training_link.isVisible(), timeout=5000)
    assert not home.training_line.isVisible() and len(ctx.models(BOARD)) == 1
    win.navigate("Training")
    assert "Saved AI model v1.0" in page.log.toPlainText() and page.bar.value() == 100
