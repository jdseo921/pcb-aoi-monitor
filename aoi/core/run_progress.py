"""How far a training run is and how long it has left (REQ-TRN-008, stage S40), without Qt.

A run is a count of steps of four kinds, known once it has read its first image: "read" (an image read, decoded and
warped, its first time or again for a later band of the Golden board), "median" (one step of a band's median,
`golden.Median`), "step" (one training step) and "map" (one anomaly map made and scored to calibrate). Each kind's steps
take the mean time its steps took so far. `AppContext.train` times one step of the median, one training step and one
map (`Median.probe`, `anomaly.probe`) as soon as it has its first image, so the time left is known from its second
report, and it reports after every step of every kind.
"""

from __future__ import annotations

import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass

from ..errors import Phrase

clock: Callable[[], float] = time.monotonic  # the seconds now; a test sets a clock of its own
KINDS = ("read", "median", "step", "map")


@dataclass(frozen=True)
class RunProgress:
    """A training run's report: `percent` of its time gone, never falling, and `left_s` seconds left, as estimated now
    (0 and None until a step of every kind still to come is timed); what it does now (`phase`); and a line for the
    run's log (`note`, "" for none). Phrases, shown in the UI language (#199)."""

    percent: int
    left_s: float | None
    phase: Phrase
    note: str = ""


class Eta:
    """The time left of a run of `counts` steps of each kind: `tick(kind)` as each step ends, `sample(kind, seconds)`
    for a step timed only to estimate, which the run does not count and which stands in for its kind until a step of
    it ends, `left()` the steps still to do at their kind's mean time."""

    def __init__(self, counts: Mapping[str, int]) -> None:
        self.counts = {k: counts.get(k, 0) for k in KINDS}
        self.done = dict.fromkeys(KINDS, 0)
        self.timed: dict[str, list[float]] = {k: [] for k in KINDS}
        self.sampled: set[str] = set()  # the kinds timed only by a sample so far
        self.shown = 0  # the percent last reported
        self.started = self.last = clock()

    def tick(self, kind: str) -> None:
        """A step of `kind` ended: it took the time since the step before it ended, of whatever kind; the first of its
        kind replaces the kind's sample."""
        now = clock()
        if kind in self.sampled:
            self.timed[kind] = []
            self.sampled.discard(kind)
        self.timed[kind].append(now - self.last)
        self.done[kind] += 1
        self.last = now

    def sample(self, kind: str, seconds: float) -> None:
        """A step of `kind` timed only to estimate took `seconds`; the next step is timed from now."""
        self.timed[kind].append(seconds)
        self.sampled.add(kind)
        self.last = clock()

    def left(self) -> float | None:
        """The seconds the steps still to do take at their kind's mean, None while a kind still to come is untimed."""
        to_do = {k: self.counts[k] - self.done[k] for k in KINDS if self.counts[k] > self.done[k]}
        if any(not self.timed[k] for k in to_do):
            return None
        return sum(n * sum(self.timed[k]) / len(self.timed[k]) for k, n in to_do.items())

    def report(self, phase: Phrase, note: str = "") -> RunProgress:
        """The run's report now: the time gone over the time gone and left, below 100 until the run ends, and never
        below the percent reported before, so the bar stays put while a slower step than timed moves the end away."""
        left, gone = self.left(), clock() - self.started
        if left is not None and gone + left > 0:
            self.shown = max(self.shown, min(99, int(100 * gone / (gone + left))))
        return RunProgress(self.shown, left, phase, note)
