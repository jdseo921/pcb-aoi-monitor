"""A splitter whose two panes sit side by side where there is room, and one over the other where there is not (#104).

At 1366 × 768 a page has 1100 px or less across, which several pages' side-by-side panes did not fit: the page then
scrolled sideways, and a pane at its least width cut its buttons. A `ReflowSplitter` reports the least width its panes
need one over the other, so a page is never held wider by them, and turns to the side-by-side arrangement only when its
width holds both panes at their least widths. The arrangement follows the width it is given, never the reverse, so it
settles in one resize.
"""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import QEvent, QSize, Qt, Signal
from PySide6.QtGui import QResizeEvent
from PySide6.QtWidgets import QGroupBox, QSizePolicy, QSplitter, QWidget

from .. import theme


def least_width(w: QWidget) -> int:
    """The width a layout gives `w` at least: its own least width where one is set, else its least size hint, and none
    for a widget that ignores its hints across (Qt's qSmartMinSize)."""
    if w.sizePolicy().horizontalPolicy() == QSizePolicy.Policy.Ignored and not w.minimumWidth():
        return 0
    return w.minimumWidth() or w.minimumSizeHint().width()


class ReflowSplitter(QSplitter):
    """Panes side by side where the splitter is at least as wide as they need side by side (`wide_need`); one over
    the other, each its full width, where it is narrower. `need`, when given, says that width instead of the panes'
    least widths: a pane can need more to show its content whole than a layout would hold it to. `arranged` says which
    arrangement it took, side by side (True) or not, at each change. Side by side, the panes take the widths the page
    gave (`set_wide_sizes`) or the user's, as the handle was last dragged, never the widths they had as they turned one
    over the other: those are of whatever width the splitter had then, as little as 300 px while a page not shown yet
    is first laid out, and at 1920 px the panes kept that share, Compare's decision table squeezed into 190 px."""

    arranged = Signal(bool)

    def __init__(self, need: Callable[[], int] | None = None, parent: QWidget | None = None) -> None:
        super().__init__(Qt.Orientation.Horizontal, parent)
        self.need = need
        self.wide_sizes: list[int] = []  # the panes' widths side by side, kept while they are one over the other
        self._arranging = False
        self.splitterMoved.connect(self._dragged)

    def set_wide_sizes(self, sizes: list[int]) -> None:
        """The panes' widths side by side, or their shares of the width there is: given now when they are, else when
        they are next."""
        self.wide_sizes = list(sizes)
        if self.wide():
            self.setSizes(self.wide_sizes)

    def _dragged(self, _pos: int, _index: int) -> None:
        if self.wide():
            self.wide_sizes = self.sizes()

    def panes(self) -> list[QWidget]:
        return [w for w in (self.widget(i) for i in range(self.count())) if w is not None and not w.isHidden()]

    def wide(self) -> bool:
        return self.orientation() == Qt.Orientation.Horizontal

    def wide_need(self) -> int:
        """The least width that holds every pane side by side, the handles between them included."""
        if self.need is not None:
            return self.need()
        panes = self.panes()
        return sum(least_width(w) for w in panes) + self.handleWidth() * max(len(panes) - 1, 0)

    def reflow(self) -> None:
        """The arrangement the width it has holds, asked again after what a pane shows has changed its need."""
        if self.width() > 0:
            self._arrange(self.width() >= self.wide_need())

    def minimumSizeHint(self) -> QSize:  # noqa: N802 (Qt's name)
        """As wide as the widest pane needs one over the other: the splitter turns to that below its side-by-side
        need, so the page is never held wider than it. As tall as the arrangement it has needs."""
        hint = super().minimumSizeHint()
        return QSize(max((least_width(w) for w in self.panes()), default=0), hint.height())

    def resizeEvent(self, event: QResizeEvent) -> None:  # noqa: N802 (Qt's name)
        self._arrange(event.size().width() >= self.wide_need())
        super().resizeEvent(event)

    def event(self, event: QEvent) -> bool:
        """A pane whose need changed while the width stayed, as Training's import sheet opening in the Samples pane,
        asks its splitter to lay it out again: the arrangement is asked again then, so the panes never stay side by
        side squeezed under their least widths (#104)."""
        if event.type() == QEvent.Type.LayoutRequest:
            self.reflow()
        return super().event(event)

    def _arrange(self, wide: bool) -> None:
        """Side by side (`wide`) or not. A handler of `arranged` that asks again while the change is under way never
        turns it back: a need that changes with the arrangement would turn it to and fro without end (review of A7,
        which found Compare's do that); the next resize or layout request asks again."""
        if wide == self.wide() or self._arranging:
            return
        self._arranging = True
        try:
            self.setOrientation(Qt.Orientation.Horizontal if wide else Qt.Orientation.Vertical)
            if wide and self.wide_sizes:
                self.setSizes(self.wide_sizes)
            self.arranged.emit(wide)
        finally:
            self._arranging = False


class SideSplit(QSplitter):
    """A picture beside a side panel, the panel at the width `want` gives it wherever the picture keeps
    theme.IMAGE_MIN_W beside it: a narrower window narrows the picture, never the panel (#104). Inspection's verdict
    panel, narrowed, wrapped onto more lines than a 1366 x 768 window has and pushed Start out of it; the Recipe
    Editor's, at the share its weights gave it, lost its ROI table's last column at 1920 x 1080. Asked again at each
    resize, and by the page when the theme changes the panel's text size."""

    def __init__(self, want: Callable[[QWidget], int]) -> None:
        super().__init__(Qt.Orientation.Horizontal)
        self.want = want

    def resizeEvent(self, event: QResizeEvent) -> None:  # noqa: N802 (Qt's name)
        super().resizeEvent(event)
        self.keep_side()

    def keep_side(self) -> None:
        side = self.widget(1)
        if self.count() != 2 or side is None:
            return
        room = self.width() - self.handleWidth()
        want = self.want(side)
        if room - want >= theme.IMAGE_MIN_W:
            self.setSizes([room - want, want])


def least_at_width(widget: QWidget, hint: QSize) -> QSize:
    """`hint`, `widget`'s least size, no shorter than its layout's least height at the width it has, its wrapped
    lines' heights at that width included."""
    layout = widget.layout()
    if layout is None or not layout.hasHeightForWidth() or widget.width() <= 0:
        return hint
    return QSize(hint.width(), max(hint.height(), layout.totalMinimumHeightForWidth(widget.width())))


class WrappedPane(QWidget):
    """A pane whose least height is its layout's at the width it has (`least_at_width`). A splitter takes a pane's
    least height from its least size hint, which counts a wrapped line once: a pane of wrapped lines was given less
    than it needs at 1366 px, and its layout squeezed the picture or the table under it short of their least heights
    (#104)."""

    def minimumSizeHint(self) -> QSize:  # noqa: N802 (Qt's name)
        return least_at_width(self, super().minimumSizeHint())

    def resizeEvent(self, event: QResizeEvent) -> None:  # noqa: N802 (Qt's name)
        super().resizeEvent(event)
        if event.size().width() != event.oldSize().width():
            self.updateGeometry()  # its least height follows its width


class WrappedGroup(QGroupBox):
    """A group box at least as tall as its layout's least height at the width it has, its rows laid out at that width.
    In a box layout, a group of wrapped lines in a form was given the form's preferred height for its width, which a
    QFormLayout reckons short of what its wrapped lines need: at 1366 x 768 the lines of Training's Labeller agreement
    were cut short (A7). A box layout takes a widget's least height for its width from its layout, and holds it to the
    widget's own least height, so that is what this sets, again at each new width and each change of the lines it
    holds. And a QFormLayout narrowed to a width it had measured before laid its rows out at the heights of the width
    it had last laid them out at: after a window 2560 px wide, the line under Training's dataset version kept two lines'
    height at 1366 px where it wraps to three (A7); its layout is asked again at each new width."""

    def resizeEvent(self, event: QResizeEvent) -> None:  # noqa: N802 (Qt's name)
        super().resizeEvent(event)
        if event.size().width() != event.oldSize().width():
            layout = self.layout()
            if layout is not None and layout.hasHeightForWidth():
                layout.invalidate()  # its rows laid out again, at this width's heights
            self._hold()

    def event(self, event: QEvent) -> bool:
        if event.type() == QEvent.Type.LayoutRequest:  # a line's text or font changed its height
            self._hold()
        return super().event(event)

    def _hold(self) -> None:
        layout = self.layout()
        if layout is None or not layout.hasHeightForWidth() or self.width() <= 0:
            return
        need = layout.totalMinimumHeightForWidth(self.width())
        if need != self.minimumHeight():
            self.setMinimumHeight(need)
