# -*- coding: utf-8 -*-
"""悬浮球模式：56px 圆形折叠态。

待机：♪ 符号；播放中：当前音符字母 + 呼吸光环。
拖动移动；单击展开为完整浮窗。
"""
from __future__ import annotations

import math
from typing import Optional

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QBrush, QColor, QFont, QPainter, QPen, QRadialGradient
from PySide6.QtWidgets import QWidget

from .theme import THEME

BALL = 56.0


class FloatingBall(QWidget):
    expand_requested = Signal()

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setWindowTitle("ManboHakimi-Harp Ball")
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setFixedSize(int(BALL + 16), int(BALL + 16))
        self._char: Optional[str] = None       # 播放中显示的键位字母
        self._playing = False
        self._real_ms = 0.0
        self._dragging = False
        self._drag_offset = None
        self._press_global = None              # 按下时的全局坐标（判断是否只是单击）
        self._moved = False
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def set_note_char(self, char: Optional[str]) -> None:
        self._char = char
        self.update()

    def set_playing(self, playing: bool) -> None:
        self._playing = playing
        self.update()

    def tick(self, real_ms: float) -> None:
        self._real_ms = real_ms
        self.update()

    # ---- 交互 ----
    # 移动超过这个像素数就认定为「拖拽」，松手时不再触发展开
    DRAG_THRESHOLD = 4

    def mousePressEvent(self, e) -> None:  # noqa: N802
        if e.button() == Qt.MouseButton.LeftButton:
            self._dragging = True
            pos = e.globalPosition().toPoint()
            self._drag_offset = pos - self.pos()
            self._press_global = pos
            self._moved = False

    def mouseMoveEvent(self, e) -> None:  # noqa: N802
        if not (self._dragging and self._drag_offset is not None):
            return
        pos = e.globalPosition().toPoint()
        if self._press_global is not None:
            delta = pos - self._press_global
            if abs(delta.x()) + abs(delta.y()) > self.DRAG_THRESHOLD:
                self._moved = True
        self.move(pos - self._drag_offset)

    def mouseReleaseEvent(self, e) -> None:  # noqa: N802
        if not self._dragging:
            return
        # 只有「没怎么动」才算单击 -> 展开。
        # 旧实现里 moved 算出来却没用（还被写成 bool 表达式），
        # 于是拖完悬浮球一松手就会把完整浮窗也弹出来。
        was_click = not self._moved
        self._dragging = False
        self._drag_offset = None
        self._press_global = None
        self._moved = False
        if was_click:
            self.expand_requested.emit()

    # ---- 绘制 ----
    def paintEvent(self, event) -> None:  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        c = QPointF(self.width() / 2, self.height() / 2)
        r = BALL / 2

        # 播放中：呼吸光环（2s 循环）
        if self._playing:
            phase = (math.sin(self._real_ms / 1000.0 * math.pi) + 1) / 2  # 0..1
            halo = QRadialGradient(c, r + 8 + phase * 5)
            halo.setColorAt(r / (r + 13), QColor(0, 229, 255, 70))
            halo.setColorAt(1, QColor(0, 229, 255, 0))
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QBrush(halo))
            p.drawEllipse(c, r + 13, r + 13)

        # 主体
        p.setBrush(QColor(19, 24, 32, 235))
        ring = QPen(QColor(0, 229, 255, 180), 2.0)
        p.setPen(ring)
        p.drawEllipse(c, r, r)

        # 内容：当前音符字母或 ♪
        if self._char:
            p.setFont(QFont(THEME.font_mono, 17, QFont.Weight.Bold))
            p.setPen(QColor(THEME.primary))
            p.drawText(QRectF(c.x() - r, c.y() - r, BALL, BALL),
                       Qt.AlignmentFlag.AlignCenter, self._char)
        else:
            p.setPen(QPen(QColor(THEME.primary), 2.4))
            px, py = c.x() - 6, c.y() - 8
            p.drawLine(QPointF(px + 4, py), QPointF(px + 4, py + 11))
            p.drawEllipse(QPointF(px + 1.5, py + 11), 3, 3)
            p.drawEllipse(QPointF(px + 6.5, py + 10), 3, 3)
            p.drawLine(QPointF(px + 9, py - 1), QPointF(px + 4, py))
