"""A row of controls that wraps onto a second line where the page is too narrow for it (REQ-LOG-009, #104).

Logs & Export's filters fill a 1920 px page in one row; with the Review filter they asked for 1536 px, more than the
1350 px a 1600 px window gives the page, which then scrolled sideways. In a `FlowLayout` the row breaks between two
items instead, each a label with its field, so no filter is cut off and none is parted from its label.
"""

from __future__ import annotations

from PySide6.QtCore import QMargins, QPoint, QRect, QSize, Qt
from PySide6.QtWidgets import QHBoxLayout, QLabel, QLayout, QLayoutItem, QSizePolicy, QSpacerItem, QWidget

from .. import theme


class FlowLayout(QLayout):
    """Items left to right at their size hints, `gap` apart across and down, each line as tall as its tallest item and
    its items given its height, or centred on it where they cannot grow to it; an item that does not fit the line's
    room starts the next line. An item wider than the whole width is given the width, never less than its minimum. Its
    minimum width is its widest item's minimum, and its height follows its width (`heightForWidth`).

    A line's room left over goes to its items added with `add_stretched` and its stretches (`add_stretch`), as a box
    layout's stretch gives it; a line with none of them sits at the layout's left, or at its right with `right` set, as
    a row that starts with a stretch (#104). On one line, a row so built places its items where the box layout it
    replaces did: a stretch takes no gap beside it, as there."""

    def __init__(self, parent: QWidget | None = None, gap: int = theme.SPACE_S, right: bool = False) -> None:
        super().__init__(parent)
        self._items: list[QLayoutItem] = []
        self._stretched: list[QLayoutItem] = []
        self._gap = gap
        self._right = right
        self.setContentsMargins(QMargins(0, 0, 0, 0))

    def add_stretched(self, w: QWidget) -> None:
        """Add `w`, given the room its line leaves over."""
        self.addWidget(w)
        self._stretched.append(self._items[-1])

    def add_stretch(self) -> None:
        """Add a stretch: the room its line leaves over, between the items before it and those after."""
        self.addItem(QSpacerItem(0, 0, QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum))
        self._stretched.append(self._items[-1])

    def addItem(self, item: QLayoutItem) -> None:
        self._items.append(item)

    def count(self) -> int:
        return len(self._items)

    def itemAt(self, index: int) -> QLayoutItem | None:
        return self._items[index] if 0 <= index < len(self._items) else None

    def takeAt(self, index: int) -> QLayoutItem | None:
        if not 0 <= index < len(self._items):
            return None
        item = self._items.pop(index)
        self._stretched = [i for i in self._stretched if i is not item]
        return item

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
        x = 0  # the width the line's items and their gaps take so far
        for item in self._items:
            stretch = item.spacerItem() is not None
            if item.isEmpty() and not (stretch and self._is_stretched(item)):
                continue
            size = QSize(0, 0) if stretch else item.sizeHint().boundedTo(QSize(room.width(), 1 << 24))
            size = size.expandedTo(QSize(0, 0) if stretch else item.minimumSize())
            filled = any(i.spacerItem() is None for i, _ in lines[-1])
            if not stretch and filled and x + gap + size.width() > room.width():
                lines.append([])
                x, filled = 0, False
            if not stretch:
                x += (gap if filled else 0) + size.width()
            lines[-1].append((item, size))
        y = room.top()
        shown_lines = [line for line in lines if any(item.spacerItem() is None for item, _ in line)]
        for line in shown_lines:
            shown = [size for item, size in line if item.spacerItem() is None]
            height = max(size.height() for size in shown)
            left = max(room.width() - sum(size.width() for size in shown) - gap * (len(shown) - 1), 0)
            grow = [size for item, size in line if self._is_stretched(item)]
            for i, size in enumerate(grow):  # the room left over, shared out as evenly as whole pixels allow
                size.setWidth(size.width() + left // len(grow) + (1 if i < left % len(grow) else 0))
            x = room.left() + (left if self._right and not grow else 0)
            first = True
            for item, size in line:
                if item.spacerItem() is None:  # a gap between two items, none beside a stretch
                    x += 0 if first else gap
                    first = False
                    if move:  # the line's height, which an item that cannot grow to it is centred in, as a box gives
                        item.setGeometry(QRect(QPoint(x, y), QSize(size.width(), height)))
                x += size.width()
            y += height + gap
        return y - gap - room.top() + m.top() + m.bottom() if shown_lines else m.top() + m.bottom()

    def _is_stretched(self, item: QLayoutItem) -> bool:
        return any(i is item for i in self._stretched)


def labelled(label: str, field: QWidget, stretch: int = 0) -> QWidget:
    """A field with its label before it: one item of a `FlowLayout`, which wraps between items, never inside one. The
    field takes the room the pair is given beyond its hint with `stretch` 1."""
    pair = QWidget()
    row = QHBoxLayout(pair)
    row.setContentsMargins(0, 0, 0, 0)
    row.addWidget(QLabel(label))
    row.addWidget(field, stretch)
    return pair
