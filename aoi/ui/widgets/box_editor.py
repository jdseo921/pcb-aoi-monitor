"""Boxes on an image, drawn, selected, moved and resized on it: the defect boxes of an NG image (`BoxEditor`,
REQ-TRN-003; labels sketch, S33) and the ROIs of a recipe on its Golden board (`RoiEditor`, REQ-RCP-001; recipe-editor
sketch, S49).

`Boxes` is an `ImageView` (zoom, pan, fit and its Draw mode) that holds the boxes, each in image pixels. A finger works
as the mouse does: Qt turns a touch the view does not take into the same mouse events. With the focus on it, the keys
do what the mouse does: Enter in Draw mode places a box, and the arrows move and size the selected one.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace
from typing import Generic, TypeVar

from PySide6.QtCore import QEvent, QPoint, QPointF, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QBrush, QColor, QFocusEvent, QKeyEvent, QMouseEvent, QPen, QTransform
from PySide6.QtWidgets import QGraphicsItem, QGraphicsRectItem, QGraphicsView, QWidget

from ...core.labels import DefectBox
from ...core.recipe import ROI
from ...defects import BY_NAME, names
from .. import theme
from .image_view import ImageView

MIN_SIDE = 4  # px of the image: a resize leaves a box at least this wide and tall, as ImageView draws none smaller
Grip = tuple[float, float]  # a handle's place on its box, as fractions of its width and height from the top left
CORNERS: tuple[Grip, ...] = ((0, 0), (1, 0), (1, 1), (0, 1))  # top left, top right, bottom right, bottom left
SIDES: tuple[Grip, ...] = ((0.5, 0), (1, 0.5), (0.5, 1), (0, 0.5))  # the middle of the top, right, bottom and left
B = TypeVar("B", DefectBox, ROI)
KEY_SIDE_PX = 64  # px on screen, at any zoom: the side of the box Enter places, which the arrows then move and size
BURST_MS = 500  # arrow keys pressed within this of each other, or of the last one let go, are one change
ARROWS = {Qt.Key.Key_Left: (-1, 0), Qt.Key.Key_Right: (1, 0), Qt.Key.Key_Up: (0, -1), Qt.Key.Key_Down: (0, 1)}
SHIFT, CTRL = Qt.KeyboardModifier.ShiftModifier, Qt.KeyboardModifier.ControlModifier
ENTER = (Qt.Key.Key_Return, Qt.Key.Key_Enter)


def _points(b: DefectBox | ROI, grips: tuple[Grip, ...]) -> list[QPointF]:
    """Where the handles `grips` lie on `b`, in image pixels."""
    return [QPointF(b.x + fx * b.w, b.y + fy * b.h) for fx, fy in grips]


def _clamp(v: int, low: int, high: int) -> int:
    return max(low, min(v, high))


def _moved(b: B, d: QPointF, width: int, height: int) -> B:
    """`b` moved by `d`, kept inside the image."""
    return replace(b, x=_clamp(round(b.x + d.x()), 0, width - b.w), y=_clamp(round(b.y + d.y()), 0, height - b.h))


def _side(start: int, length: int, f: float, d: float, most: int) -> tuple[int, int]:
    """One axis of `_resized`: the start and length of a box whose side `f` names (0 the start, 1 the end, 0.5 neither)
    moved by `d` while the opposite side stays: never past it, never closer to it than MIN_SIDE, never outside 0 to
    `most`."""
    if f == 0.5:
        return start, length
    low = f == 0
    fixed, v = (start + length, round(start + d)) if low else (start, round(start + length + d))
    v = _clamp(min(v, fixed - MIN_SIDE) if low else max(v, fixed + MIN_SIDE), 0, most)
    a, b = sorted((v, fixed))
    return a, max(b - a, 1)


def _resized(b: B, grip: Grip, d: QPointF, width: int, height: int) -> B:
    """`b` with the handle at `grip` moved by `d`: a corner moves its two sides, a side's middle that side alone, and
    each opposite side stays where it was (`_side`)."""
    (x, w), (y, h) = _side(b.x, b.w, grip[0], d.x(), width), _side(b.y, b.h, grip[1], d.y(), height)
    return replace(b, x=x, y=y, w=w, h=h)


class Boxes(ImageView, Generic[B]):
    """An image with its boxes, each labelled (`_label`), the selected one with a handle at each of `grips`. In Draw
    mode a drag gives `roiDrawn`, a new box for the subclass to add; otherwise a drag on a box moves it and a drag on a
    handle of the selected box resizes it, and a drag elsewhere pans. A selected box under `small_px` across on screen
    has its handles outside it, so a press inside it still moves it. By keys, Enter in Draw mode places a box 64 px a
    side on screen at the middle of the image shown, the arrows move the selected box by 1 px (Shift: 10 px) and Ctrl
    with them moves its bottom right corner. Each gesture that changes the boxes ends in one `edited`, at its release,
    so a drag is stored once, not at every move, and a burst of arrow keys half a second after its last key; `settled`
    follows the end of every gesture. While `locked` (the image read or a change stored) a press or a key that would
    change a box only says `refused`."""

    edited = Signal()  # the boxes changed: the page stores them
    picked = Signal(int)  # the selected box, -1 for none
    settled = Signal()  # a drag ended, stored or not
    refused = Signal()  # a change asked for while `locked`
    grips = CORNERS
    small_px = 2 * theme.HANDLE_PX

    def __init__(self, parent: QWidget | None = None, placeholder: str = "") -> None:
        super().__init__(parent, placeholder)
        self.boxes: list[B] = []
        self.chosen = -1
        self._grab: tuple[int, Grip | None, QPointF, B] | None = None  # box, handle (None: the box), start, box before
        self.locked = False
        self._keyed: tuple[int, B] | None = None  # the box the arrows move, as it was before them
        self._burst = QTimer(self)
        self._burst.setSingleShot(True)
        self._burst.setInterval(BURST_MS)
        self._burst.timeout.connect(self._keys_done)
        self.viewChanged.connect(self.redraw)  # the handles and labels follow the zoom

    def show_boxes(self, boxes: list[B], chosen: int = -1) -> None:
        """Show `boxes`, `chosen` selected (-1 or past the end: none)."""
        self.boxes, self._grab, self._keyed = list(boxes), None, None
        self._burst.stop()
        self.chosen = chosen if 0 <= chosen < len(self.boxes) else -1
        self.redraw()

    def zoom(self, factor: float) -> None:
        """Zoom by `factor` about the middle of the view: the Zoom In and Zoom Out buttons and keys, for a hand with no
        wheel (the wheel zooms about the pointer)."""
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorViewCenter)
        self.scale(factor, factor)
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self._emit_changed()

    def zoom_to_box(self) -> None:
        """The selected box, with its own width and height again around it, filling the view."""
        if self.chosen >= 0:
            b = self.boxes[self.chosen]
            self.center_on_box(b.x, b.y, b.w, b.h)
            self._emit_changed()

    def choose(self, chosen: int) -> None:
        """Select box `chosen` (-1: none) and say so with `picked`."""
        chosen = chosen if 0 <= chosen < len(self.boxes) else -1
        if chosen != self.chosen:
            self.chosen = chosen
            self.redraw()
            self.picked.emit(chosen)

    def _label(self, n: int) -> str:
        """The text above box `n`."""
        raise NotImplementedError

    def _pen(self, n: int) -> tuple[str, bool]:
        """Box `n`'s colour, and whether its line is dashed: the selected box yellow, the others green."""
        return (theme.ROI_SELECTED if n == self.chosen else theme.ROI_COLOR), False

    def redraw(self) -> None:
        self.clear_overlays()
        for n, b in enumerate(self.boxes):
            colour, dashed = self._pen(n)
            self.add_box(b.x, b.y, b.w, b.h, colour, self._label(n), dashed=dashed)
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
        for grip, point in zip(self.grips, _points(self.boxes[self.chosen], self.grips), strict=True):
            handle = QGraphicsRectItem(self._handle(grip, small))  # 16 px at every zoom (labels sketch)
            handle.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIgnoresTransformations)
            handle.setPos(point)
            handle.setPen(pen)
            handle.setBrush(QBrush(QColor(theme.BG_IMAGE)))
            self.scene().addItem(handle)
            self._overlay_items.append(handle)

    def _bounds(self) -> tuple[int, int]:
        rect = self.sceneRect()
        return round(rect.width()), round(rect.height())

    def _small(self) -> bool:
        """The selected box is under `small_px` across on screen, as a few pixels of a 20 MP image at fit are."""
        b = self.boxes[self.chosen]
        shown = self.mapFromScene(QRectF(b.x, b.y, b.w, b.h)).boundingRect()
        return min(shown.width(), shown.height()) < self.small_px

    def _handle(self, grip: Grip, small: bool) -> QRectF:
        """The handle at `grip` on the selected box, in screen pixels from it: on it, or outside a small box."""
        side, (sx, sy) = theme.HANDLE_PX, (2 * grip[0] - 1, 2 * grip[1] - 1)  # its way out of the box: -1, 0 or 1
        if not small:
            return QRectF(-side / 2, -side / 2, side, side)
        x, y = (-side if s < 0 else -side / 2 if s == 0 else 0 for s in (sx, sy))
        return QRectF(x, y, side, side)

    def _hit(self, at: QPoint) -> tuple[int, Grip | None] | None:
        """(box, handle) under the viewport point `at`: a handle of the selected box (within HANDLE_PX of it, across
        plus down, or the handle drawn outside a small box), else the topmost box there with handle None, else None."""
        if self.chosen >= 0:
            points, small = _points(self.boxes[self.chosen], self.grips), self._small()
            distance, i = min(((self.mapFromScene(c) - at).manhattanLength(), i) for i, c in enumerate(points))
            if not small and distance <= theme.HANDLE_PX:
                return self.chosen, self.grips[i]
            for grip, c in zip(self.grips, points, strict=True):
                if small and self._handle(grip, small).translated(QPointF(self.mapFromScene(c))).contains(QPointF(at)):
                    return self.chosen, grip
        point = self.mapToScene(at)
        for n in reversed(range(len(self.boxes))):  # the last drawn lies on top
            b = self.boxes[n]
            if QRectF(b.x, b.y, b.w, b.h).contains(point):
                return n, None
        return None

    def _follow(self, e: QMouseEvent) -> None:
        """The grabbed box or corner under the pointer of `e`."""
        if self._grab is None:
            return
        n, grip, start, before = self._grab
        d, (width, height) = self.mapToScene(e.position().toPoint()) - start, self._bounds()
        self.boxes[n] = _moved(before, d, width, height) if grip is None else _resized(before, grip, d, width, height)
        self.redraw()

    def mousePressEvent(self, e: QMouseEvent) -> None:
        self._keys_done()  # the arrows' change, stored before the mouse makes another
        left = e.button() == Qt.MouseButton.LeftButton
        idle = not left or self._draw_mode or self._pick_mode or self._pans(e)  # a press here picks or pans
        hit = None if idle else self._hit(e.position().toPoint())
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
            x, y = _clamp(round(corner.x()), 0, width - side), _clamp(round(corner.y()), 0, height - side)
            self.roiDrawn.emit(QRectF(x, y, side, side))  # inside the image, as a drag in Draw mode gives it
            return
        if self._keyed is None or self._keyed[0] != self.chosen:
            self._keys_done()
            self._keyed = (self.chosen, self.boxes[self.chosen])
        b, (dx, dy), step = self.boxes[self.chosen], ARROWS[Qt.Key(e.key())], 10 if e.modifiers() & SHIFT else 1
        d = QPointF(dx * step, dy * step)
        resize = bool(e.modifiers() & CTRL)  # its bottom right corner, the top left one staying
        self.boxes[self.chosen] = _resized(b, (1, 1), d, width, height) if resize else _moved(b, d, width, height)
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


class BoxEditor(Boxes[DefectBox]):
    """The defect boxes of an NG image, each labelled with its number, type and severity; a box drawn in Draw mode is of
    `new_type`, and selected."""

    def __init__(self, parent: QWidget | None = None, placeholder: str = "") -> None:
        super().__init__(parent, placeholder)
        self.new_type = names()[0]
        self.roiDrawn.connect(self._drawn)

    def _label(self, n: int) -> str:
        b = self.boxes[n]
        label = self.tr("{number} {type} ◆ {severity}")
        return label.format(number=n + 1, type=b.dct_type, severity=BY_NAME[b.dct_type].severity)

    def _drawn(self, rect: QRectF) -> None:
        """A box dragged out in Draw mode, already cut to the image and at least 4 px a side: the next box, of
        `new_type`, selected."""
        x0, y0, x1, y1 = (round(v) for v in (rect.left(), rect.top(), rect.right(), rect.bottom()))
        self.boxes.append(DefectBox(x0, y0, x1 - x0, y1 - y0, self.new_type))
        self.choose(len(self.boxes) - 1)
        self.edited.emit()


class RoiEditor(Boxes[ROI]):
    """A recipe's ROIs on its Golden board, each labelled with its name and type: the selected one yellow with a handle
    at each corner and in the middle of each side; the others green as saved (`saved`, the revision loaded), yellow and
    dashed while changed and not saved, grey while disabled (recipe-editor sketch). The page adds the ROI a drag in
    Draw mode gives (`roiDrawn`); `marks`, the points Calibrate Scale… picked, and `extra`, the boxes of a Try's
    defects, are drawn with the ROIs at every redraw, so a zoom or a drag keeps them."""

    grips = CORNERS + SIDES
    small_px = 3 * theme.HANDLE_PX  # its handles outside a box under this across: the press inside it still moves it

    def __init__(self, parent: QWidget | None = None, placeholder: str = "") -> None:
        super().__init__(parent, placeholder)
        self.saved: list[ROI] = []
        self.type_text: Callable[[str], str] = str  # an ROI type in the UI language
        self.marks: list[QPointF] = []
        self.extra: list[tuple[int, int, int, int, str, str]] = []  # x, y, w, h, colour, label

    def _label(self, n: int) -> str:
        r = self.boxes[n]
        return f"{r.name} [{self.type_text(r.type)}]"

    def _pen(self, n: int) -> tuple[str, bool]:
        r = self.boxes[n]
        changed = r not in self.saved
        if n == self.chosen or changed:
            return theme.ROI_SELECTED, changed
        return (theme.ROI_COLOR if r.enabled else theme.ROI_DISABLED), False

    def redraw(self) -> None:
        super().redraw()
        for x, y, w, h, colour, label in self.extra:
            self.add_box(x, y, w, h, colour, label)
        self.add_measure(self.marks)
