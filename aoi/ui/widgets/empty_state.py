"""The empty-state block every empty list, image area and card shows (REQ-SET-019; sketch, "Empty state").

Three parts: what is missing (16 pt), what to do (one sentence, 14 pt) and one link button to where it is done. The
block either covers a host widget (an image view or a table, placed over it like `BusyOverlay`) or stands in a layout
on its own, as the 3D Profile card does. Pages decide the words; `Page.empty_step` turns "do this on <page>" into the
link, or into "Ask an Engineer …" for a role that cannot open that page.
"""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import QEvent, QObject, QRect, QSize, Qt
from PySide6.QtWidgets import QLabel, QPushButton, QVBoxLayout, QWidget


class _Text(QLabel):
    """A wrapped label that a layout may narrow below its longest word, such as a golden board's file name: the word
    then runs past the edge and every line still shows. With that word's width as its minimum, the layout worked the
    label's height out at the word's width, and the label showed fewer lines than its text wraps to."""

    def minimumSizeHint(self) -> QSize:
        return QSize(0, super().minimumSizeHint().height())


class _Block(QVBoxLayout):
    """Centres its items as one block, as wide as they would like within the area and as tall as its text wraps to at
    that width. Qt's centring (`setAlignment(AlignCenter)`) works the height out at the width the block would like
    before it narrows the block to the area, so in an area narrower than that (Compare's two panes side by side) the
    text got the height of fewer lines than it wraps to and was cut off at the top and bottom."""

    def heightForWidth(self, width: int) -> int:
        """The height at the width `setGeometry` narrows the block to, so a layout that holds the empty state, such as
        the 3D Profile card's, gives it the height its text needs there."""
        return super().heightForWidth(min(width, self.sizeHint().width()))

    def setGeometry(self, rect: QRect) -> None:
        hint = self.sizeHint()
        width = min(hint.width(), rect.width())
        height = min(self.heightForWidth(width) if self.hasHeightForWidth() else hint.height(), rect.height())
        x, y = rect.x() + (rect.width() - width) // 2, rect.y() + (rect.height() - height) // 2
        super().setGeometry(QRect(x, y, width, height))


class EmptyState(QWidget):
    def __init__(self, over: QWidget | None = None, kind: str = "") -> None:
        super().__init__(over)
        self._over = over
        self._go: Callable[[], object] | None = None
        self.setObjectName("empty")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        layout = _Block(self)
        self.heading = _Text()
        self.heading.setObjectName("emptyHeading")
        self.sentence = _Text()
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
