"""A row of controls that wraps onto a second line where the page is too narrow for it (REQ-LOG-009, #104).

Logs & Export's filters fill a 1920 px page in one row; with the Review filter they asked for 1536 px, more than the
1350 px a 1600 px window gives the page, which then scrolled sideways. In a `FlowLayout` the row breaks between two
items instead, each a label with its field, so no filter is cut off and none is parted from its label.
"""

from __future__ import annotations

from PySide6.QtCore import QMargins, QPoint, QRect, QSize, Qt
from PySide6.QtWidgets import QLayout, QLayoutItem, QWidget

from .. import theme


class FlowLayout(QLayout):
    """Items left to right at their size hints, `gap` apart across and down, each line as tall as its tallest item and
    its items centred on it; an item that does not fit the line's room starts the next line. An item wider than the
    whole width is given the width, never less than its minimum. Its minimum width is its widest item's minimum, and
    its height follows its width (`heightForWidth`)."""

    def __init__(self, parent: QWidget | None = None, gap: int = theme.SPACE_S) -> None:
        super().__init__(parent)
        self._items: list[QLayoutItem] = []
        self._gap = gap
        self.setContentsMargins(QMargins(0, 0, 0, 0))

    def addItem(self, item: QLayoutItem) -> None:
        self._items.append(item)

    def count(self) -> int:
        return len(self._items)

    def itemAt(self, index: int) -> QLayoutItem | None:
        return self._items[index] if 0 <= index < len(self._items) else None

    def takeAt(self, index: int) -> QLayoutItem | None:
        return self._items.pop(index) if 0 <= index < len(self._items) else None

    def expandingDirections(self) -> Qt.Orientation:
        return Qt.Orientation(0)

    def hasHeightForWidth(self) -> bool:
        return True

    def heightForWidth(self, width: int) -> int:
        return self._lay_out(QRect(0, 0, width, 0), move=False)

    def setGeometry(self, rect: QRect) -> None:
        super().setGeometry(rect)
        self._lay_out(rect, move=True)

    def sizeHint(self) -> QSize:
        """Every item on one line."""
        gap = self._gap
        shown = [i.sizeHint() for i in self._items if not i.isEmpty()]
        width = sum(s.width() for s in shown) + gap * max(len(shown) - 1, 0)
        m = self.contentsMargins()
        return QSize(width + m.left() + m.right(), max((s.height() for s in shown), default=0) + m.top() + m.bottom())

    def minimumSize(self) -> QSize:
        size = QSize()
        for item in self._items:
            if not item.isEmpty():
                size = size.expandedTo(item.minimumSize())
        m = self.contentsMargins()
        return size + QSize(m.left() + m.right(), m.top() + m.bottom())

    def _lay_out(self, rect: QRect, move: bool) -> int:
        """Place the items in `rect` when `move`; the height they take either way."""
        m = self.contentsMargins()
        room = rect.adjusted(m.left(), m.top(), -m.right(), -m.bottom())
        gap = self._gap
        lines: list[list[tuple[QLayoutItem, QSize]]] = [[]]
        x = 0
        for item in (i for i in self._items if not i.isEmpty()):
            size = item.sizeHint().boundedTo(QSize(room.width(), 1 << 24)).expandedTo(item.minimumSize())
            if lines[-1] and x + gap + size.width() > room.width():
                lines.append([])
                x = 0
            x += (gap if lines[-1] else 0) + size.width()
            lines[-1].append((item, size))
        y = room.top()
        for line in (line for line in lines if line):
            height = max(size.height() for _, size in line)
            x = room.left()
            for item, size in line:
                if move:
                    item.setGeometry(QRect(QPoint(x, y + (height - size.height()) // 2), size))
                x += size.width() + gap
            y += height + gap
        return y - gap - room.top() + m.top() + m.bottom() if any(lines) else m.top() + m.bottom()
