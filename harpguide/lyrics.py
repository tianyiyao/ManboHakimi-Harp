# -*- coding: utf-8 -*-
"""歌词提示区：卡拉OK式显示当前歌词行，随播放进度推进。

- 当前行：主青色大字号居中
- 上一行 / 下一行：灰色小字号淡出（提供上下文）
- 无歌词的曲目自动隐藏，不占布局空间
"""
from __future__ import annotations

from typing import Optional

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QFont, QPainter
from PySide6.QtWidgets import QWidget

from .models import Score
from .theme import THEME


class LyricWidget(QWidget):
    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self._score: Optional[Score] = None
        self._pos_ms: float = 0.0
        self.setFixedHeight(56)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)

    # ---- 外部接口 ----
    def set_score(self, score: Optional[Score]) -> None:
        self._score = score
        self._pos_ms = 0.0
        self.setVisible(bool(score and score.lyrics))
        self.update()

    def tick(self, pos_ms: float) -> None:
        self._pos_ms = pos_ms
        if self.isVisible():
            self.update()

    # ---- 绘制 ----
    def paintEvent(self, event) -> None:  # noqa: N802
        if not self._score or not self._score.lyrics:
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)

        cur = self._score.lyric_at(self._pos_ms)
        n = len(self._score.lyrics)

        # 面板底
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(19, 24, 32, 120))
        p.drawRoundedRect(self.rect(), 8, 8)

        cy = self.height() / 2
        # 当前行（主青、大字号）
        if cur is not None:
            p.setFont(QFont(THEME.font_sans, 14, QFont.Weight.Bold))
            p.setPen(QColor(THEME.text_primary))
            self._draw_text_center(p, self._score.lyrics[cur].text, cy - 8, 0.7)

        # 下一行预览
        if cur is None:
            if n > 0:
                p.setFont(QFont(THEME.font_sans, 12))
                p.setPen(QColor(THEME.text_secondary))
                self._draw_text_center(p, self._score.lyrics[0].text, cy, 0.9)
        elif cur + 1 < n:
            p.setFont(QFont(THEME.font_sans, 10))
            p.setPen(QColor(150, 160, 175, 150))
            self._draw_text_center(p, self._score.lyrics[cur + 1].text,
                                   cy + 14, 0.35)

    def _draw_text_center(self, p: QPainter, text: str, y: float, alpha: float) -> None:
        c = p.pen().color()
        c.setAlpha(int(c.alpha() * alpha))
        p.setPen(c)
        p.drawText(QRectF(8, y - 12, self.width() - 16, 24),
                   Qt.AlignmentFlag.AlignCenter, text)
