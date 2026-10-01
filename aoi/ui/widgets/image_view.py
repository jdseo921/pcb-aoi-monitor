"""Zoom/pan image viewer with defect boxes, ROI drawing and view syncing."""

from __future__ import annotations

import cv2
import numpy as np
from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QBrush, QColor, QFont, QImage, QPainter, QPen, QPixmap, QTransform
from PySide6.QtWidgets import QGraphicsRectItem, QGraphicsScene, QGraphicsSimpleTextItem, QGraphicsView

from .. import theme


def label_font() -> QFont:
    """14 pt for text drawn on an image: a QGraphics item takes the application font, not the stylesheet's."""
    font = QFont()
    font.setPointSize(theme.FONT_PT)
    return font


def to_qpixmap(img: np.ndarray) -> QPixmap:
    if img.ndim == 2:
        img = cv2.cvtColor(img, cv2.COLOR_GRAY2BGR)
    rgb = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
    h, w = rgb.shape[:2]
    q = QImage(rgb.data, w, h, 3 * w, QImage.Format_RGB888)
    return QPixmap.fromImage(q.copy())


class ImageView(QGraphicsView):
    roiDrawn = Signal(QRectF)  # image coordinates
    viewChanged = Signal()

    def __init__(self, parent=None, placeholder: str = "No image"):
        super().__init__(parent)
        self.setScene(QGraphicsScene(self))
        self.setRenderHints(QPainter.Antialiasing | QPainter.SmoothPixmapTransform)
        self.setDragMode(QGraphicsView.ScrollHandDrag)
        self.setTransformationAnchor(QGraphicsView.AnchorUnderMouse)
        self.setBackgroundBrush(QColor(theme.BG_IMAGE))
        self.setMinimumSize(theme.IMAGE_MIN_W, theme.IMAGE_MIN_H)
        self._pix = None
        self._overlay_items = []
        self._draw_mode = False
        self._drag_start: QPointF | None = None
        self._rubber: QGraphicsRectItem | None = None
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
        if self._pix is not None:
            self.fitInView(self._pix, Qt.KeepAspectRatio)
            self._emit_changed()

    def clear_overlays(self) -> None:
        for it in self._overlay_items:
            self.scene().removeItem(it)
        self._overlay_items.clear()

    def add_box(
        self, x, y, w, h, color: str = theme.NG_COLOR, label: str = "", width: float = 2.0, dashed: bool = False
    ) -> None:
        pen = QPen(QColor(color), width)
        pen.setCosmetic(True)
        if dashed:
            pen.setStyle(Qt.DashLine)
        r = self.scene().addRect(QRectF(x, y, w, h), pen)
        self._overlay_items.append(r)
        if label:  # 14 pt text on a dark backing above the box's corner, the same size at every zoom (REQ-SET-004)
            t = QGraphicsSimpleTextItem(label)
            t.setFont(label_font())
            t.setBrush(QBrush(QColor(theme.TEXT)))  # 15:1 on the backing, whatever the board behind it looks like
            t.setFlag(QGraphicsSimpleTextItem.ItemIgnoresTransformations)
            t.setPos(x, y)
            t.setTransform(QTransform.fromTranslate(4, -t.boundingRect().height() - 6))  # above the corner, in pixels
            backing = QGraphicsRectItem(t.boundingRect().adjusted(-4, -3, 4, 3), t)
            backing.setPen(QPen(Qt.NoPen))
            backing.setBrush(QBrush(QColor(theme.BG_IMAGE)))
            backing.setFlag(QGraphicsRectItem.ItemStacksBehindParent)
            self.scene().addItem(t)
            self._overlay_items.append(t)

    def center_on_box(self, x, y, w, h) -> None:
        self.fitInView(QRectF(x - w, y - h, w * 3, h * 3), Qt.KeepAspectRatio)

    # --- zoom / pan --------------------------------------------------------------
    def wheelEvent(self, e):
        f = 1.25 if e.angleDelta().y() > 0 else 0.8
        self.scale(f, f)
        self._emit_changed()

    def mouseDoubleClickEvent(self, e):
        self.fit()

    # --- ROI drawing ---------------------------------------------------------------
    def set_draw_mode(self, on: bool) -> None:
        self._draw_mode = on
        self.setDragMode(QGraphicsView.NoDrag if on else QGraphicsView.ScrollHandDrag)
        self.setCursor(Qt.CrossCursor if on else Qt.ArrowCursor)

    def mousePressEvent(self, e):
        if self._draw_mode and e.button() == Qt.LeftButton and self._pix is not None:
            self._drag_start = self.mapToScene(e.position().toPoint())
            pen = QPen(QColor(theme.ROI_SELECTED), 2)
            pen.setCosmetic(True)
            pen.setStyle(Qt.DashLine)
            self._rubber = self.scene().addRect(QRectF(self._drag_start, self._drag_start), pen)
            return
        super().mousePressEvent(e)

    def mouseMoveEvent(self, e):
        if self._rubber is not None and self._drag_start is not None:
            self._rubber.setRect(QRectF(self._drag_start, self.mapToScene(e.position().toPoint())).normalized())
            return
        super().mouseMoveEvent(e)

    def mouseReleaseEvent(self, e):
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

    def _emit_changed(self, *_):
        self.viewChanged.emit()
        if self._syncing:
            return
        for p in self._peers:
            p._syncing = True
            p.setTransform(self.transform())
            p.horizontalScrollBar().setValue(self.horizontalScrollBar().value())
            p.verticalScrollBar().setValue(self.verticalScrollBar().value())
            p._syncing = False
