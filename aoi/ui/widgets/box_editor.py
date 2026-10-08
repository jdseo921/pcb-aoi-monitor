"""The defect boxes of an NG image, drawn, selected, moved and resized on it (REQ-TRN-003; labels sketch, S33).

`BoxEditor` is an `ImageView` (zoom, pan, fit and its Draw mode) that holds the image's boxes, each a `DefectBox` in
image pixels. A finger works as the mouse does: Qt turns a touch the view does not take into the same mouse events.
With the focus on it, the keys do what the mouse does: Enter in Draw mode places a box, and the arrows move and size
the selected one.
"""

from __future__ import annotations

from dataclasses import replace

from PySide6.QtCore import QEvent, QPoint, QPointF, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QBrush, QColor, QFocusEvent, QKeyEvent, QMouseEvent, QPen, QTransform
from PySide6.QtWidgets import QGraphicsItem, QGraphicsRectItem, QWidget

from ...core.labels import DefectBox
from ...defects import BY_NAME, names
from .. import theme
from .image_view import ImageView

MIN_SIDE = 4  # px of the image: a resize leaves a box at least this wide and tall, as ImageView draws none smaller
OUTWARD = ((-1, -1), (1, -1), (1, 1), (-1, 1))  # each corner's way out of its box, in the order of `_corners`
KEY_SIDE_PX = 64  # px on screen, at any zoom: the side of the box Enter places, which the arrows then move and size
BURST_MS = 500  # arrow keys pressed within this of each other, or of the last one let go, are one change
ARROWS = {Qt.Key.Key_Left: (-1, 0), Qt.Key.Key_Right: (1, 0), Qt.Key.Key_Up: (0, -1), Qt.Key.Key_Down: (0, 1)}
SHIFT, CTRL = Qt.KeyboardModifier.ShiftModifier, Qt.KeyboardModifier.ControlModifier
ENTER = (Qt.Key.Key_Return, Qt.Key.Key_Enter)


def _corners(b: DefectBox) -> list[QPointF]:
    """Top left, top right, bottom right, bottom left: the order of the handles."""
    return [QPointF(b.x, b.y), QPointF(b.x + b.w, b.y), QPointF(b.x + b.w, b.y + b.h), QPointF(b.x, b.y + b.h)]


def _clamp(v: int, low: int, high: int) -> int:
    return max(low, min(v, high))


def _moved(b: DefectBox, d: QPointF, width: int, height: int) -> DefectBox:
    """`b` moved by `d`, kept inside the image."""
    return replace(b, x=_clamp(round(b.x + d.x()), 0, width - b.w), y=_clamp(round(b.y + d.y()), 0, height - b.h))


def _resized(b: DefectBox, corner: int, d: QPointF, width: int, height: int) -> DefectBox:
    """`b` with `corner` (an index of `_corners`) moved by `d` and the opposite corner where it was: never past it,
    never closer to it than MIN_SIDE, never outside the image."""
    left, top = corner in (0, 3), corner in (0, 1)
    fixed_x, fixed_y = b.x + (b.w if left else 0), b.y + (b.h if top else 0)
    x = round((b.x if left else b.x + b.w) + d.x())
    y = round((b.y if top else b.y + b.h) + d.y())
    x = _clamp(min(x, fixed_x - MIN_SIDE) if left else max(x, fixed_x + MIN_SIDE), 0, width)
    y = _clamp(min(y, fixed_y - MIN_SIDE) if top else max(y, fixed_y + MIN_SIDE), 0, height)
    (x0, x1), (y0, y1) = sorted((x, fixed_x)), sorted((y, fixed_y))
    return replace(b, x=x0, y=y0, w=max(x1 - x0, 1), h=max(y1 - y0, 1))


class BoxEditor(ImageView):
    """An image with its defect boxes: the selected one yellow with a handle at each corner, the others green, each
    labelled with its number, type and severity. In Draw mode a drag adds a box of `new_type`; otherwise a drag on a
    box moves it and a drag on a handle of the selected box resizes it, and a drag elsewhere pans. A selected box under
    two handles across on screen has its handles outside it, so a press inside it still moves it. By keys, Enter in Draw
    mode places a box 64 px a side on screen at the middle of the image shown, the arrows move the selected box by 1
    px (Shift: 10 px) and Ctrl with them moves its bottom right corner. Each gesture that changes the boxes ends in one
    `edited`, at its release, so a drag is stored once, not at every move, and a burst of arrow keys half a second
    after its last key; `settled` follows the end of every gesture. While `locked` (the image read or a change stored)
    a press or a key that would change a box only says `refused`."""

    edited = Signal()  # the boxes changed: the page stores them
    picked = Signal(int)  # the selected box, -1 for none
    settled = Signal()  # a drag ended, stored or not
    refused = Signal()  # a change asked for while `locked`

    def __init__(self, parent: QWidget | None = None, placeholder: str = "") -> None:
        super().__init__(parent, placeholder)
        self.boxes: list[DefectBox] = []
        self.chosen = -1
        self.new_type = names()[0]
        self._grab: tuple[int, int, QPointF, DefectBox] | None = None  # box, corner (-1: the box), start, box before
        self.locked = False
        self._keyed: tuple[int, DefectBox] | None = None  # the box the arrows move, as it was before them
        self._burst = QTimer(self)
        self._burst.setSingleShot(True)
        self._burst.setInterval(BURST_MS)
        self._burst.timeout.connect(self._keys_done)
        self.roiDrawn.connect(self._drawn)
        self.viewChanged.connect(self.redraw)  # the handles and labels follow the zoom

    def show_boxes(self, boxes: list[DefectBox], chosen: int = -1) -> None:
        """Show `boxes`, `chosen` selected (-1 or past the end: none)."""
        self.boxes, self._grab, self._keyed = list(boxes), None, None
        self._burst.stop()
        self.chosen = chosen if 0 <= chosen < len(self.boxes) else -1
        self.redraw()

    def choose(self, chosen: int) -> None:
        """Select box `chosen` (-1: none) and say so with `picked`."""
        chosen = chosen if 0 <= chosen < len(self.boxes) else -1
        if chosen != self.chosen:
            self.chosen = chosen
            self.redraw()
            self.picked.emit(chosen)

    def redraw(self) -> None:
        self.clear_overlays()
        for n, b in enumerate(self.boxes):
            label = self.tr("{number} {type} ◆ {severity}")
            label = label.format(number=n + 1, type=b.dct_type, severity=BY_NAME[b.dct_type].severity)
            self.add_box(b.x, b.y, b.w, b.h, theme.ROI_SELECTED if n == self.chosen else theme.ROI_COLOR, label)
            text, on_screen = self._overlay_items[-1], self.viewportTransform()
            left, wide = on_screen.map(QPointF(b.x, b.y)).x(), text.boundingRect().width() + 8  # with its backing
            if left + wide > self.viewport().width():  # cut at the pane's right edge: it ends at the box's right
                across = on_screen.map(QPointF(b.x + b.w, b.y)).x() - left  # edge instead, or the pane's left
                text.setTransform(QTransform.fromTranslate(max(across - wide + 4, 4 - left), text.transform().dy()))
        if self.chosen < 0:
            return
        pen = QPen(QColor(theme.ROI_SELECTED), 2)
        pen.setCosmetic(True)
        small = self._small()
        for n, corner in enumerate(_corners(self.boxes[self.chosen])):
            handle = QGraphicsRectItem(self._handle(n, small))  # 16 px at every zoom (labels sketch)
            handle.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIgnoresTransformations)
            handle.setPos(corner)
            handle.setPen(pen)
            handle.setBrush(QBrush(QColor(theme.BG_IMAGE)))
            self.scene().addItem(handle)
            self._overlay_items.append(handle)

    def _bounds(self) -> tuple[int, int]:
        rect = self.sceneRect()
        return round(rect.width()), round(rect.height())

    def _small(self) -> bool:
        """The selected box is under two handles across on screen, as a few pixels of a 20 MP image at fit are."""
        b = self.boxes[self.chosen]
        shown = self.mapFromScene(QRectF(b.x, b.y, b.w, b.h)).boundingRect()
        return min(shown.width(), shown.height()) < 2 * theme.HANDLE_PX

    def _handle(self, corner: int, small: bool) -> QRectF:
        """The handle at `corner` of the selected box, in screen pixels from it: on it, or outside a small box."""
        side, (sx, sy) = theme.HANDLE_PX, OUTWARD[corner]
        if not small:
            return QRectF(-side / 2, -side / 2, side, side)
        return QRectF(-side if sx < 0 else 0, -side if sy < 0 else 0, side, side)

    def _hit(self, at: QPoint) -> tuple[int, int] | None:
        """(box, corner) under the viewport point `at`: a corner of the selected box, by its handle (within HANDLE_PX
        of it, across plus down, or the handle drawn outside a small box), else the topmost box there with corner -1,
        else None."""
        if self.chosen >= 0:
            corners, small = _corners(self.boxes[self.chosen]), self._small()
            distance, corner = min(((self.mapFromScene(c) - at).manhattanLength(), i) for i, c in enumerate(corners))
            if not small and distance <= theme.HANDLE_PX:
                return self.chosen, corner
            for i, c in enumerate(corners):
                if small and self._handle(i, small).translated(QPointF(self.mapFromScene(c))).contains(QPointF(at)):
                    return self.chosen, i
        point = self.mapToScene(at)
        for n in reversed(range(len(self.boxes))):  # the last drawn lies on top
            b = self.boxes[n]
            if QRectF(b.x, b.y, b.w, b.h).contains(point):
                return n, -1
        return None

    def _drawn(self, rect: QRectF) -> None:
        """A box dragged out in Draw mode, already cut to the image and at least 4 px a side: the next box, of
        `new_type`, selected."""
        x0, y0, x1, y1 = (round(v) for v in (rect.left(), rect.top(), rect.right(), rect.bottom()))
        self.boxes.append(DefectBox(x0, y0, x1 - x0, y1 - y0, self.new_type))
        self.choose(len(self.boxes) - 1)
        self.edited.emit()

    def _follow(self, e: QMouseEvent) -> None:
        """The grabbed box or corner under the pointer of `e`."""
        if self._grab is None:
            return
        n, corner, start, before = self._grab
        d, (width, height) = self.mapToScene(e.position().toPoint()) - start, self._bounds()
        self.boxes[n] = _moved(before, d, width, height) if corner < 0 else _resized(before, corner, d, width, height)
        self.redraw()

    def mousePressEvent(self, e: QMouseEvent) -> None:
        self._keys_done()  # the arrows' change, stored before the mouse makes another
        left = e.button() == Qt.MouseButton.LeftButton
        hit = None if self._draw_mode or not left else self._hit(e.position().toPoint())
        if left and self.locked and (self._draw_mode or hit is not None):
            self.refused.emit()
            return
        if hit is None:
            super().mousePressEvent(e)  # Draw mode's drag, or a pan
            return
        self.choose(hit[0])
        self._grab = (hit[0], hit[1], self.mapToScene(e.position().toPoint()), self.boxes[hit[0]])

    def mouseDoubleClickEvent(self, e: QMouseEvent) -> None:
        """A second press soon after a tap, on a box: a press, so a tap then a drag moves it; elsewhere a fit."""
        if self._draw_mode or self._hit(e.position().toPoint()) is None:
            super().mouseDoubleClickEvent(e)
            return
        self.mousePressEvent(e)

    def mouseMoveEvent(self, e: QMouseEvent) -> None:
        if self._grab is None:
            super().mouseMoveEvent(e)
            return
        self._follow(e)

    def mouseReleaseEvent(self, e: QMouseEvent) -> None:
        if self._grab is None:
            super().mouseReleaseEvent(e)  # Draw mode's box, stored by its `edited`, or the end of a pan
            self.settled.emit()
            return
        self._follow(e)
        self._let_go()

    def dragging(self) -> bool:
        """A box or a Draw mode box is being dragged, or moved by arrow keys not yet stored."""
        return self._grab is not None or self._rubber is not None or self._keyed is not None

    def _let_go(self) -> None:
        """The end of a drag on a box, at its release or when that never comes: one `edited` if it changed the box."""
        if self._grab is not None:
            n, before = self._grab[0], self._grab[3]
            self._grab = None
            if self.boxes[n] != before:
                self.edited.emit()
            self.settled.emit()

    def focusOutEvent(self, e: QFocusEvent) -> None:
        super().focusOutEvent(e)
        self._let_go()  # the window went away mid-drag: the release will not come
        self._keys_done()

    def leaveEvent(self, e: QEvent) -> None:
        super().leaveEvent(e)
        self._let_go()

    def _takes(self, e: QKeyEvent) -> bool:
        """A key this view acts on now: an arrow while a box is selected, Enter in Draw mode on an image."""
        if e.key() in ARROWS:
            return self.chosen >= 0
        return e.key() in ENTER and self._draw_mode and self._pix is not None

    def event(self, e: QEvent) -> bool:
        if e.type() == QEvent.Type.ShortcutOverride and isinstance(e, QKeyEvent) and self._takes(e):
            e.accept()  # the image's own keys before the page's (a page key on Enter, as the sketch's Check Label)
            return True
        return super().event(e)

    def keyPressEvent(self, e: QKeyEvent) -> None:
        if not self._takes(e):
            super().keyPressEvent(e)  # with no box selected the arrows scroll the image, as before
            return
        if self.locked:
            self.refused.emit()
            return
        width, height = self._bounds()
        if e.key() in ENTER:
            self._keys_done()
            side = max(MIN_SIDE, min(round(KEY_SIDE_PX / self.transform().m11()), width, height))
            corner = self.mapToScene(self.viewport().rect().center()) - QPointF(side / 2, side / 2)
            b = _moved(DefectBox(0, 0, side, side, self.new_type), corner, width, height)  # inside the image
            self._drawn(QRectF(b.x, b.y, b.w, b.h))
            return
        if self._keyed is None or self._keyed[0] != self.chosen:
            self._keys_done()
            self._keyed = (self.chosen, self.boxes[self.chosen])
        b, (dx, dy), step = self.boxes[self.chosen], ARROWS[Qt.Key(e.key())], 10 if e.modifiers() & SHIFT else 1
        d = QPointF(dx * step, dy * step)
        resize = bool(e.modifiers() & CTRL)  # its bottom right corner, the top left one staying
        self.boxes[self.chosen] = _resized(b, 2, d, width, height) if resize else _moved(b, d, width, height)
        self.redraw()
        self._burst.start()

    def keyReleaseEvent(self, e: QKeyEvent) -> None:
        if e.key() in ARROWS and self._keyed is not None and not e.isAutoRepeat():
            self._burst.start()  # half a second after the last key let go
        super().keyReleaseEvent(e)

    def _keys_done(self) -> None:
        """The end of a burst of arrow keys: the box they moved stored once, if it changed."""
        self._burst.stop()
        if self._keyed is not None:
            n, before = self._keyed
            self._keyed = None
            if n < len(self.boxes) and self.boxes[n] != before:
                self.edited.emit()
            self.settled.emit()
