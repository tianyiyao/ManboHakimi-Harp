# -*- coding: utf-8 -*-
"""底部热键提示条：把常用全局热键以「键帽 + 说明」常驻在浮窗最下方。

设计要点：
- 纯展示，`WA_TransparentForMouseEvents`，不影响拖动窗口 / 鼠标穿透
- 宽度不足时自动换行；行数变化通过 `height_for_width()` 反馈给主窗口，
  主窗口据此把它计入固定高度，保证瀑布流弹性区高度计算正确
- 可在设置面板「显示 → 底部热键提示」里开关（默认开）
"""
from __future__ import annotations

from typing import List, Optional, Tuple

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QFontMetricsF, QPainter, QPen
from PySide6.QtWidgets import QSizePolicy, QWidget

from .theme import THEME

# (键帽文本, 说明文本)。键帽仅使用 Consolas 支持的 ASCII，避免某些环境下缺字。
HOTKEY_HINTS: List[Tuple[str, str]] = [
    ("F1", "开始/暂停"),
    ("F2", "重置"),
    ("F3", "显隐"),
    ("F4", "悬浮球"),
    ("C-S-A", "A点"),
    ("C-S-B", "B点/清除"),
    ("C-S-T", "穿透"),
    ("C-S-C", "校准"),
    ("C-S-E", "编辑器"),
    ("N0", "自动变调"),
    ("N1/2/3", "降/自然/升"),
    ("N4/5/6", "判定偏移"),
    ("C-S-Q", "退出"),
]

ROW_H = 21          # 单行高度 px
CAP_H = 15.0        # 键帽高度 px
CAP_PAD_X = 4.5     # 键帽左右内边距
GAP_CAP_TEXT = 4.5  # 键帽与说明之间的间距
GAP_CHIP = 13.0     # 相邻提示之间的间距


class HotkeyBar(QWidget):
    """底部热键提示条（只读展示）。"""

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        # 只作展示：鼠标事件直接穿透，不干扰窗口拖动与游戏操作
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self._font_key = QFont(THEME.font_mono, 8, QFont.Weight.Bold)
        self._font_txt = QFont(THEME.font_sans, 8)
        self._rows = 1
        self.setFixedHeight(ROW_H)

    # ---- 布局计算 ----
    def _chips(self):
        """预量每枚提示的宽度：(键帽, 说明, 键帽宽, 总宽)。"""
        fk = QFontMetricsF(self._font_key)
        ft = QFontMetricsF(self._font_txt)
        out = []
        for cap, desc in HOTKEY_HINTS:
            cap_w = fk.horizontalAdvance(cap) + CAP_PAD_X * 2
            total = cap_w + GAP_CAP_TEXT + ft.horizontalAdvance(desc)
            out.append((cap, desc, cap_w, total))
        return out

    def _layout(self, width: float):
        """按给定宽度排版，返回 (行数, [(cap, desc, x, y, cap_w)])。"""
        chips = self._chips()
        placed = []
        rows = 1
        x = 0.0
        limit = max(1.0, float(width))
        for cap, desc, cap_w, total in chips:
            if x > 0 and x + total > limit:
                rows += 1
                x = 0.0
            placed.append((cap, desc, x, (rows - 1) * ROW_H, cap_w))
            x += total + GAP_CHIP
        return rows, placed

    def height_for_width(self, width: float) -> int:
        """给定可用宽度下需要的高度；主窗口用它算固定高度。"""
        rows, _ = self._layout(width)
        return max(ROW_H, rows * ROW_H)

    def refresh_height(self) -> int:
        """按当前宽度重算并应用自身高度，返回新高度。"""
        h = self.height_for_width(self.width())
        if h != self.height():
            self.setFixedHeight(h)
        self._rows = h // ROW_H
        return h

    # ---- 绘制 ----
    def paintEvent(self, event) -> None:  # noqa: N802
        w = self.width()
        if w <= 0:
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)

        # 顶部分隔线：把提示条与上方进度条视觉上分开
        p.setPen(QPen(QColor(0, 229, 255, 38), 1.0))
        p.drawLine(QPointF(0, 0.5), QPointF(w, 0.5))

        _, placed = self._layout(w)
        for cap, desc, x, y, cap_w in placed:
            cap_rect = QRectF(x, y + (ROW_H - CAP_H) / 2.0, cap_w, CAP_H)
            # 键帽底 + 描边
            p.setBrush(QColor(255, 255, 255, 16))
            p.setPen(QPen(QColor(0, 229, 255, 96), 1.0))
            p.drawRoundedRect(cap_rect, 3.5, 3.5)
            # 键位字母
            p.setFont(self._font_key)
            p.setPen(QColor(THEME.primary))
            p.drawText(cap_rect, Qt.AlignmentFlag.AlignCenter, cap)
            # 说明文字
            p.setFont(self._font_txt)
            p.setPen(QColor(THEME.text_secondary))
            tx = x + cap_w + GAP_CAP_TEXT
            p.drawText(QRectF(tx, y, max(1.0, w - tx), ROW_H),
                       int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter),
                       desc)
