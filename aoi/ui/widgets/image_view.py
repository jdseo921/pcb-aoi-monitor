"""Zoom/pan image viewer with defect boxes, ROI drawing and view syncing."""

from __future__ import annotations

from typing import cast

import cv2
import numpy as np
from PySide6.QtCore import QLineF, QPoint, QPointF, QRectF, QSize, Qt, Signal
from PySide6.QtGui import (
    QBrush,
    QColor,
    QFocusEvent,
    QFont,
    QImage,
    QKeyEvent,
    QMouseEvent,
    QPainter,
    QPen,
    QPixmap,
    QTransform,
    QWheelEvent,
)
from PySide6.QtWidgets import (
    QGraphicsItem,
    QGraphicsPixmapItem,
    QGraphicsRectItem,
    QGraphicsScene,
    QGraphicsSimpleTextItem,
    QGraphicsView,
    QWidget,
)

from .. import theme


def label_font() -> QFont:
    """FONT_PT (14 pt, 18 in the presenter theme) for text drawn on an image: a QGraphics item takes the application
    font, not the stylesheet's."""
    font = QFont()
    font.setPointSize(theme.FONT_PT)
    return font


def _style_label(t: QGraphicsSimpleTextItem, dx: float) -> None:
    """A box's label in the theme: TEXT (15:1 on the backing, whatever the board behind it looks like) at FONT_PT, `dx`
    px right of the box's corner and above it, on its backing in BG_IMAGE (its one child)."""
    t.setFont(label_font())
    t.setBrush(QBrush(QColor(theme.TEXT)))
    t.setTransform(QTransform.fromTranslate(dx, -t.boundingRect().height() - 6))  # above the corner, in pixels
    backing = cast(QGraphicsRectItem, t.childItems()[0])
    backing.setRect(t.boundingRect().adjusted(-4, -3, 4, 3))
    backing.setBrush(QBrush(QColor(theme.BG_IMAGE)))


def to_qpixmap(img: np.ndarray) -> QPixmap:
    if img.ndim == 2:
        img = cv2.cvtColor(img, cv2.COLOR_GRAY2BGR)
    rgb = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
    h, w = rgb.shape[:2]
    q = QImage(rgb.data, w, h, 3 * w, QImage.Format.Format_RGB888)
    return QPixmap.fromImage(q.copy())


class ImageView(QGraphicsView):
    roiDrawn = Signal(QRectF)  # image coordinates
    pointPicked = Signal(QPointF)  # image coordinates, in pick mode
    viewChanged = Signal()

    def __init__(self, parent: QWidget | None = None, placeholder: str = "No image") -> None:
        super().__init__(parent)
        self.setScene(QGraphicsScene(self))
        self.setRenderHints(QPainter.RenderHint.Antialiasing | QPainter.RenderHint.SmoothPixmapTransform)
        self.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.setBackgroundBrush(QColor(theme.BG_IMAGE))
        self.setMinimumSize(theme.IMAGE_MIN_W, theme.IMAGE_MIN_H)
        self._pix: QGraphicsPixmapItem | None = None
        self._overlay_items: list[QGraphicsItem] = []
        self._draw_mode = self._pick_mode = False
        self._drag_start: QPointF | None = None
        self._rubber: QGraphicsRectItem | None = None
        self._space = False  # Space held: a left drag pans, in any mode (recipe-editor sketch)
        self._pan_from: QPoint | None = None  # where a middle or Space drag was last, in viewport px
        self._peers: list[ImageView] = []
        self._syncing = False
        self._placeholder = self.scene().addSimpleText(placeholder, label_font())
        self._placeholder.setBrush(QColor(theme.TEXT_MUTED))  # 8:1 on BG_IMAGE; it is a hint, not a disabled control
        self.horizontalScrollBar().valueChanged.connect(self._emit_changed)
        self.verticalScrollBar().valueChanged.connect(self._emit_changed)

    # --- content ---------------------------------------------------------------
    def set_image(self, img: np.ndarray | None, keep_view: bool = False) -> None:
        self.clear_overlays()
        if self._pix is not None:
            self.scene().removeItem(self._pix)
            self._pix = None
        self._placeholder.setVisible(img is None)
        if img is None:
            return
        self._pix = self.scene().addPixmap(to_qpixmap(img))
        self._pix.setZValue(-1)
        self.scene().setSceneRect(QRectF(self._pix.pixmap().rect()))
        if not keep_view:
            self.fit()

    def fit(self) -> None:
        """The whole picture in the view, measured as fitInView does but on the viewport with no scroll bars: those of
        a zoom go only at the next event, and a fit measured with them left the board 5 % short of the pane (#248)."""
        room = self.maximumViewportSize() - QSize(4, 4)  # fitInView's margin of 2 px a side
        rect = self._pix.sceneBoundingRect() if self._pix is not None else QRectF()
        if rect.isEmpty() or room.isEmpty():
            return
        ratio = min(room.width() / rect.width(), room.height() / rect.height())
        self.setTransform(QTransform.fromScale(ratio, ratio))
        self.centerOn(rect.center())
        self._emit_changed()

    def clear_overlays(self) -> None:
        for it in self._overlay_items:
            self.scene().removeItem(it)
        self._overlay_items.clear()

    def add_box(
        self,
        x: float,
        y: float,
        w: float,
        h: float,
        color: str = theme.NG_COLOR,
        label: str = "",
        width: float = 2.0,
        dashed: bool = False,
    ) -> None:
        pen = QPen(QColor(color), width)
        pen.setCosmetic(True)
        if dashed:
            pen.setStyle(Qt.PenStyle.DashLine)
        r = self.scene().addRect(QRectF(x, y, w, h), pen)
        self._overlay_items.append(r)
        if label:  # text on a backing above the box's corner, the same size at every zoom (REQ-SET-004)
            t = QGraphicsSimpleTextItem(label)
            t.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIgnoresTransformations)
            t.setPos(x, y)
            backing = QGraphicsRectItem(t)
            backing.setPen(QPen(Qt.PenStyle.NoPen))
            backing.setFlag(QGraphicsItem.GraphicsItemFlag.ItemStacksBehindParent)
            _style_label(t, 4)
            self.scene().addItem(t)
            self._overlay_items.append(t)

    def restyle(self) -> None:
        """The theme was switched (REQ-SET-008): the background, the "No image" hint and every box's label again in the
        theme's colours and text size, each label where it was across."""
        self.setBackgroundBrush(QColor(theme.BG_IMAGE))
        self._placeholder.setFont(label_font())
        self._placeholder.setBrush(QColor(theme.TEXT_MUTED))
        for t in self._overlay_items:
            if isinstance(t, QGraphicsSimpleTextItem):
                _style_label(t, t.transform().dx())

    def add_measure(self, points: list[QPointF], color: str = theme.ROI_SELECTED) -> None:
        """Points picked: a ring theme.MARK_D px across at every zoom each, and the line between the first two."""
        pen, d = QPen(QColor(color), 2), theme.MARK_D
        pen.setCosmetic(True)
        if len(points) > 1:
            self._overlay_items.append(self.scene().addLine(QLineF(points[0], points[1]), pen))
        for p in points:
            ring = self.scene().addEllipse(QRectF(-d / 2, -d / 2, d, d), pen)
            ring.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIgnoresTransformations)
            ring.setPos(p)
            self._overlay_items.append(ring)

    def center_on_box(self, x: float, y: float, w: float, h: float) -> None:
        self.fitInView(QRectF(x - w, y - h, w * 3, h * 3), Qt.AspectRatioMode.KeepAspectRatio)

    # --- zoom / pan --------------------------------------------------------------
    def wheelEvent(self, e: QWheelEvent) -> None:
        f = 1.25 if e.angleDelta().y() > 0 else 0.8
        self.scale(f, f)
        self._emit_changed()

    def mouseDoubleClickEvent(self, e: QMouseEvent) -> None:
        self.fit()

    def _pans(self, e: QMouseEvent) -> bool:
        """A press that pans, whatever the mode: the middle button, or the left one while Space is held."""
        return e.button() == Qt.MouseButton.MiddleButton or self._space and e.button() == Qt.MouseButton.LeftButton

    def keyPressEvent(self, e: QKeyEvent) -> None:
        if e.key() == Qt.Key.Key_Home:
            self.fit()
        elif e.key() == Qt.Key.Key_Space:
            self._space = True
        else:
            super().keyPressEvent(e)

    def keyReleaseEvent(self, e: QKeyEvent) -> None:
        if e.key() == Qt.Key.Key_Space and not e.isAutoRepeat():
            self._space = False
        super().keyReleaseEvent(e)

    def focusOutEvent(self, e: QFocusEvent) -> None:
        super().focusOutEvent(e)
        self._space = False  # Space let go elsewhere is never seen here

    # --- ROI drawing ---------------------------------------------------------------
    def set_draw_mode(self, on: bool, pick: bool = False) -> None:
        """Drag draws an ROI (`on`), or, with `pick`, a click picks a point (Calibrate Scale…); else drag pans."""
        self._draw_mode, self._pick_mode = on and not pick, on and pick
        self.setDragMode(QGraphicsView.DragMode.NoDrag if on else QGraphicsView.DragMode.ScrollHandDrag)
        self.setCursor(Qt.CursorShape.CrossCursor if on else Qt.CursorShape.ArrowCursor)

    def mousePressEvent(self, e: QMouseEvent) -> None:
        if self._pans(e):
            self._pan_from = e.position().toPoint()
            return
        if self._pick_mode and e.button() == Qt.MouseButton.LeftButton and self._pix is not None:
            if self._pix.sceneBoundingRect().contains(p := self.mapToScene(e.position().toPoint())):
                self.pointPicked.emit(p)  # a click off the image measures nothing
            return
        if self._draw_mode and e.button() == Qt.MouseButton.LeftButton and self._pix is not None:
            self._drag_start = self.mapToScene(e.position().toPoint())
            pen = QPen(QColor(theme.ROI_SELECTED), 2)
            pen.setCosmetic(True)
            pen.setStyle(Qt.PenStyle.DashLine)
            self._rubber = self.scene().addRect(QRectF(self._drag_start, self._drag_start), pen)
            return
        super().mousePressEvent(e)

    def mouseMoveEvent(self, e: QMouseEvent) -> None:
        if self._pan_from is not None:
            at, (h, v) = e.position().toPoint(), (self.horizontalScrollBar(), self.verticalScrollBar())
            h.setValue(h.value() - (at.x() - self._pan_from.x()))
            v.setValue(v.value() - (at.y() - self._pan_from.y()))
            self._pan_from = at
            return
        if self._rubber is not None and self._drag_start is not None:
            self._rubber.setRect(QRectF(self._drag_start, self.mapToScene(e.position().toPoint())).normalized())
            return
        super().mouseMoveEvent(e)

    def mouseReleaseEvent(self, e: QMouseEvent) -> None:
        if self._pan_from is not None:
            self._pan_from = None
            return
        if self._rubber is not None:
            rect = self._rubber.rect().intersected(self.sceneRect())
            self.scene().removeItem(self._rubber)
            self._rubber = None
            self._drag_start = None
            if rect.width() >= 4 and rect.height() >= 4:
                self.roiDrawn.emit(rect)
            return
        super().mouseReleaseEvent(e)

    # --- synchronised views (Compare page) ---------------------------------------
    def link(self, other: ImageView) -> None:
        self._peers.append(other)
        other._peers.append(self)

    def _emit_changed(self, *_: object) -> None:
        self.viewChanged.emit()
        if self._syncing or self.isHidden():  # a pane its page hid (Compare's Golden board in Defect boxes only) moves
            return  # no other: its fit, at the width it last had, shrank the board shown by half (#248)
        for p in self._peers:
            p._syncing = True
            p.setTransform(self.transform())
            p.horizontalScrollBar().setValue(self.horizontalScrollBar().value())
            p.verticalScrollBar().setValue(self.verticalScrollBar().value())
            p._syncing = False
