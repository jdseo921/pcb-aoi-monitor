"""The Golden board a training run builds: the per-pixel median of its aligned OK images (REQ-TRN-007), worked out a
band of rows at a time, so a run holds that band of every image rather than every image whole. No Qt."""

from __future__ import annotations

from collections.abc import Callable

import numpy as np

from . import run_progress

BAND_BYTES = 1 << 30  # the band of every image held at once: 1 GiB, whatever the images' number and size
# the rows of every image one step of a band's median works out at once: 64 MiB, about 0.85 s on a 4-core cloud VM for
# 50 images at 20 MP, where a whole band of 1 GiB took 15 s, more than the 10 s between a run's reports (REQ-TRN-008)
STEP_BYTES = 1 << 26


class Median:
    """`np.median(np.stack(images), axis=0).astype(np.uint8)` of `count` colour images of `shape` (height, width), to
    the bit, worked out band by band: the caller adds every image for the first band, then reads them again and adds
    every image for each later band, until `done`. Each band of every image takes at most `budget` bytes, and each
    step of its median `step` bytes."""

    def __init__(self, count: int, shape: tuple[int, int], budget: int = BAND_BYTES, step: int = STEP_BYTES) -> None:
        height, width = shape
        rows = max(1, min(height, budget // max(1, count * width * 3)))
        self.bands = [slice(top, min(top + rows, height)) for top in range(0, height, rows)]
        self.step_rows = max(1, min(rows, step // max(1, count * width * 3)))
        self.steps = sum(-(-(b.stop - b.start) // self.step_rows) for b in self.bands)  # of every band's median
        self.board = np.zeros((height, width, 3), np.uint8)
        self._count, self._band, self._added = count, 0, 0
        self._stack = np.empty((count, rows, width, 3), np.uint8)

    @property
    def done(self) -> bool:
        return self._band == len(self.bands)

    def add(self, image: np.ndarray, stepped: Callable[[], None] | None = None) -> None:
        """Take the band in hand of the next image; the last image of a band works the band out, `step_rows` rows at a
        time, calling `stepped()` after each step, so a training run reports, and can stop, between them."""
        rows = self.bands[self._band]
        self._stack[self._added, : rows.stop - rows.start] = image[rows]
        self._added += 1
        if self._added == self._count:
            for top in range(rows.start, rows.stop, self.step_rows):
                self._work(rows.start, top, min(top + self.step_rows, rows.stop))
                if stepped is not None:
                    stepped()
            self._band, self._added = self._band + 1, 0

    def _work(self, start: int, top: int, end: int) -> None:
        """The median of rows `top` to `end` of the board, from the band in hand, which starts at row `start`."""
        part = self._stack[:, top - start : end - start]
        self.board[top:end] = np.median(part, axis=0, overwrite_input=True).astype(np.uint8)

    def probe(self) -> float:
        """The seconds one step of the median takes, timed on noise before any image is added (REQ-TRN-008)."""
        rows, rng = self.step_rows, np.random.default_rng(0)
        self._stack[:, :rows] = rng.integers(0, 256, (self._count, rows, self.board.shape[1], 3), dtype=np.uint8)
        started = run_progress.clock()
        self._work(0, 0, rows)
        return run_progress.clock() - started
