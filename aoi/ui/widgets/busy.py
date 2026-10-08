"""A busy indicator over the place where a result will appear (REQ-SET-021, stage S17b).

Nothing shows for the first second, so quick work does not flicker; then what is running and the seconds so far;
after ten seconds a progress bar, the time left when the job reports progress, and Cancel.
"""

from __future__ import annotations

import time
from typing import Any

from PySide6.QtCore import QEvent, QObject, Qt, QTimer
from PySide6.QtWidgets import QLabel, QProgressBar, QPushButton, QVBoxLayout, QWidget

from ...core.jobs import Job
from .. import theme


class BusyOverlay(QWidget):
    """Covers `over` while a job runs: `watch(job)` when the work starts, `finish()` when its result or error has
    arrived. Cancel asks the job to stop and hides the overlay; the page drops the result (`Page.run_in_background`)."""

    SHOW_AFTER_S = 1.0
    DETAIL_AFTER_S = 10.0

    def __init__(self, over: QWidget, what: str = "") -> None:
        super().__init__(over)
        self._over, self._what = over, what or self.tr("Working…")
        self._job: Job[Any] | None = None
        self._t0 = 0.0
        self.setObjectName("busy")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        layout = QVBoxLayout(self)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.label = QLabel(self._what)
        self.label.setObjectName("busyText")
        self.label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.bar = QProgressBar()
        self.bar.setFixedWidth(theme.PROGRESS_W)
        self.cancel_button = QPushButton(self.tr("Cancel"))
        self.cancel_button.clicked.connect(self._on_cancel)
        layout.addWidget(self.label)
        layout.addWidget(self.bar, 0, Qt.AlignmentFlag.AlignHCenter)
        layout.addWidget(self.cancel_button, 0, Qt.AlignmentFlag.AlignHCenter)
        self._timer = QTimer(self)
        self._timer.setInterval(200)
        self._timer.timeout.connect(self._tick)
        over.installEventFilter(self)
        self.hide()

    def watch(self, job: Job[Any]) -> None:
        self._job, self._t0 = job, time.monotonic()
        self.bar.setRange(0, 0)  # indeterminate until the job reports a total
        self.bar.hide()
        self.cancel_button.hide()
        self.hide()
        self._timer.start()

    def finish(self) -> None:
        self._timer.stop()
        self._job = None
        self.hide()

    @property
    def elapsed_s(self) -> float:
        return time.monotonic() - self._t0 if self._job is not None else 0.0

    def _on_cancel(self) -> None:
        if self._job is not None:
            self._job.cancel()
        self.finish()

    def _tick(self) -> None:
        if self._job is None or self.elapsed_s < self.SHOW_AFTER_S:
            return
        text = self.tr("{what}  {seconds:.0f} s").format(what=self._what, seconds=self.elapsed_s)
        if self.elapsed_s >= self.DETAIL_AFTER_S:
            info = self._job.progress()
            if info.total:
                self.bar.setRange(0, info.total)
                self.bar.setValue(info.done)
            if info.left_s is not None:
                text += self.tr("  ·  about {seconds:.0f} s left").format(seconds=info.left_s)
            self.bar.show()
            self.cancel_button.show()
        self.label.setText(text)
        if not self.isVisible():
            self.setGeometry(self._over.rect())
            self.show()
            self.raise_()

    def eventFilter(self, obj: QObject, event: QEvent) -> bool:
        if obj is self._over and event.type() == QEvent.Type.Resize:
            self.setGeometry(self._over.rect())
        return False
