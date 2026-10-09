"""REQ-TRN-007: a training run holds the images it learns from in bounded memory, and learns what it learnt before.

The AI model is trained from each image's tensor at the network's input size and calibrated from anomaly maps made one
at a time, so no image or map at the camera's resolution is kept beyond the one in hand. Results on the synthetic
boards prove a code path; they are never quoted as accuracy.
"""

from __future__ import annotations

import random
import tracemalloc
from collections.abc import Iterator
from pathlib import Path

import numpy as np
import pytest

from aoi.core import anomaly
from aoi.core.imaging import list_images, load_image


@pytest.mark.parametrize("q", [anomaly.PIXEL_PERCENTILE, 99.9, 50.0, 100.0, 0.0])
def test_req_trn_007_pixel_threshold_read_from_largest_values(q: float) -> None:
    """The percentile of every map's pixels together, as numpy gives it for one array of them all, to the bit, from
    each map's largest values: maps of other sizes, a map of one value repeated (ties across the cut) and a map of
    one pixel, made as they are asked for."""
    rng = np.random.default_rng(3)
    shapes = [(480, 640), (37, 53), (1, 1), (200, 300), (64, 64)]
    maps = [(rng.gamma(2.0, 1.0, s) * rng.uniform(0.5, 5)).astype(np.float32) for s in shapes]
    maps[3][:] = np.float32(2.5)  # every pixel of one map the same: ties at the rank read
    made: list[int] = []

    def each() -> Iterator[np.ndarray]:
        for i, m in enumerate(maps):
            made.append(i)
            yield m

    count = sum(m.size for m in maps)
    got = anomaly.top_percentile(each(), count, q)
    expected = np.percentile(np.concatenate([m.ravel() for m in maps]), q)
    assert got == expected and got.dtype == expected.dtype == np.float32
    assert made == list(range(len(maps)))
    for seed in range(40):  # and on maps of random sizes and spreads
        r = np.random.default_rng(seed)
        sizes = [(int(r.integers(1, 90)), int(r.integers(1, 90))) for _ in range(3)]
        ms = [(r.gamma(2.0, 1.0, s) * 3).astype(np.float32) for s in sizes]
        whole = np.percentile(np.concatenate([m.ravel() for m in ms]), q)
        assert anomaly.top_percentile(iter(ms), sum(m.size for m in ms), q) == whole


def test_req_trn_007_pixel_threshold_holds_one_map_at_a_time() -> None:
    """Reading the pixel threshold keeps only each map's largest values, not the map: 12 maps of 4 MB made one at a
    time hold at most 3 maps' bytes at once (the map in hand, its partitioned copy and the values kept), where a view
    of each partitioned copy's tail would keep every copy whole."""
    rng = np.random.default_rng(5)
    shape, n = (1000, 1000), 12

    def each() -> Iterator[np.ndarray]:
        for _ in range(n):
            yield rng.random(shape, dtype=np.float32)

    tracemalloc.start()
    try:
        anomaly.top_percentile(each(), n * shape[0] * shape[1], anomaly.PIXEL_PERCENTILE)
        peak = tracemalloc.get_traced_memory()[1]
    finally:
        tracemalloc.stop()
    assert peak < 3 * shape[0] * shape[1] * 4, peak


def test_req_trn_007_calibration_as_from_whole_images(synthetic_dataset: Path) -> None:
    """An AI model trained from prepared images is calibrated as one would be from the whole images: the normal error
    of its training images, each held-out OK image's and NG image's score, and the pixel threshold from every held-out
    map's pixels together, each recomputed here from the images at their full size with the model's own network."""
    ok = [load_image(p) for p in list_images(synthetic_dataset / "train" / "ok")[:8]]
    ng = [load_image(p) for p in list_images(synthetic_dataset / "train" / "ng")[:3]]
    cfg = anomaly.TrainConfig(image_size=64, epochs=2, steps_per_epoch=2, seed=5)
    model = anomaly.train([anomaly.prepare(im, 64) for im in ok], [anomaly.prepare(im, 64) for im in ng], cfg)
    random.seed(cfg.seed)  # the held-out OK images, drawn as the run draws them
    idx = list(range(len(ok)))
    random.shuffle(idx)
    held, trained = idx[:2], idx[2:]
    errs = np.stack([model.raw_error(ok[i]) for i in trained])
    assert np.array_equal(model.meta["err_mean"], errs.mean(axis=0).astype(np.float32))
    maps = [model.anomaly_map(ok[i]) for i in held]
    assert model.meta["ok_scores"] == [model.score(m) for m in maps]
    assert model.meta["ng_scores"] == [model.score(model.anomaly_map(im)) for im in ng]
    whole = float(np.percentile(np.concatenate([m.ravel() for m in maps]), 99.95))
    assert model.meta["pixel_threshold"] == max(whole * 1.15, model.image_threshold * 0.6, 1e-4)
    p = anomaly.prepare(ok[0], 64)
    assert p.shape == ok[0].shape[:2]
    assert np.array_equal(model.prepared_map(p), model.anomaly_map(ok[0]))
