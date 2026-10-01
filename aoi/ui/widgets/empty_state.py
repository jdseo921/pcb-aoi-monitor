"""The empty-state block every empty list, image area and card shows (REQ-SET-019; sketch, "Empty state").

Three parts: what is missing (16 pt), what to do (one sentence, 14 pt) and one link button to where it is done. The
block either covers a host widget (an image view or a table, placed over it like `BusyOverlay`) or stands in a layout
on its own, as the 3D Profile card does. Pages decide the words; `Page.empty_step` turns "do this on <page>" into the
link, or into "Ask an Engineer …" for a role that cannot open that page.
"""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import QEvent, QObject, Qt
from PySide6.QtWidgets import QLabel, QPushButton, QVBoxLayout, QWidget


class EmptyState(QWidget):
    def __init__(self, over: QWidget | None = None, kind: str = "") -> None:
        super().__init__(over)
        self._over = over
        self._go: Callable[[], object] | None = None
        self.setObjectName("empty")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        layout = QVBoxLayout(self)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.heading = QLabel()
        self.heading.setObjectName("emptyHeading")
        self.sentence = QLabel()
        self.sentence.setObjectName("muted")
        for label in (self.heading, self.sentence):
            label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            label.setWordWrap(True)
            layout.addWidget(label)
        self.link = QPushButton()
        if kind:
            self.link.setObjectName(kind)
        self.link.clicked.connect(self._follow)
        layout.addWidget(self.link, 0, Qt.AlignmentFlag.AlignHCenter)
        if over is not None:
            over.installEventFilter(self)
        self.hide()

    def show_state(self, heading: str, sentence: str, link: str = "", go: Callable[[], object] | None = None) -> None:
        """Show what is missing and what to do; with `link` and `go`, also the one button that leads there."""
        self.heading.setText(heading)
        self.sentence.setText(sentence)
        self.link.setText(link)
        self.link.setVisible(bool(link) and go is not None)
        self._go = go
        if self._over is not None:
            self.setGeometry(self._over.rect())
        self.show()
        self.raise_()

    def _follow(self) -> None:
        if self._go is not None:
            self._go()

    def eventFilter(self, obj: QObject, event: QEvent) -> bool:
        if event.type() == QEvent.Type.Resize and obj is self._over:
            self.setGeometry(self._over.rect())
        return False
