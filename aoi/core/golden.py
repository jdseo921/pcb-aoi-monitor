"""The Golden board a training run builds: the per-pixel median of its aligned OK images (REQ-TRN-007), worked out a
band of rows at a time, so a run holds that band of every image rather than every image whole. No Qt."""

from __future__ import annotations

import numpy as np

BAND_BYTES = 1 << 30  # the band of every image held at once: 1 GiB, whatever the images' number and size


class Median:
    """`np.median(np.stack(images), axis=0).astype(np.uint8)` of `count` colour images of `shape` (height, width), to
    the bit, worked out band by band: the caller adds every image for the first band, then reads them again and adds
    every image for each later band, until `done`. Each band of every image takes at most `budget` bytes."""

    def __init__(self, count: int, shape: tuple[int, int], budget: int = BAND_BYTES) -> None:
        height, width = shape
        rows = max(1, min(height, budget // max(1, count * width * 3)))
        self.bands = [slice(top, min(top + rows, height)) for top in range(0, height, rows)]
        self.board = np.zeros((height, width, 3), np.uint8)
        self._count, self._band, self._added = count, 0, 0
        self._stack = np.empty((count, rows, width, 3), np.uint8)

    @property
    def done(self) -> bool:
        return self._band == len(self.bands)

    def add(self, image: np.ndarray) -> None:
        """Take the band in hand of the next image; the last image of a band works the band out."""
        rows = self.bands[self._band]
        self._stack[self._added, : rows.stop - rows.start] = image[rows]
        self._added += 1
        if self._added == self._count:
            band = self._stack[:, : rows.stop - rows.start]
            self.board[rows] = np.median(band, axis=0, overwrite_input=True).astype(np.uint8)
            self._band, self._added = self._band + 1, 0
