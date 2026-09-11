# -*- coding: utf-8 -*-
"""音符瀑布流渲染器。

关键设计（长按音符提示体系）：
- 短按音符：固定高度方块，头部到达判定线时快速点击
- 长按音符：高度随时值成正比的长条；头部到达判定线时按下、尾部离开时松开
- 长条内部流光：自上而下流动的微光，提示"需要持续按住"
- 松开预警：剩余时间 < 20% 时整条渐变为橙色，尾部闪烁
- 判定线：常态半透明青色；有音符命中时点亮并扩散光晕
"""
from __future__ import annotations

from typing import Callable, Optional

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import (QBrush, QColor, QFont, QLinearGradient, QPainter,
                           QPen, QRadialGradient)
from PySide6.QtWidgets import QWidget

from .config import Settings
from .models import Note, NoteType, Score
from .theme import THEME, lerp_color

LOOKAHEAD_MS = 2000.0   # 音符提前出现的毫秒数（默认值，可被 Settings 覆盖）
TAP_HEIGHT = 18.0       # 短按音符高度 px
NOTE_WIDTH = 48.0       # 音符宽度 px
FLASH_MS = 150.0        # 命中闪光时长
MIN_LOOKAHEAD_MS = 600.0
MAX_LOOKAHEAD_MS = 6000.0
POPUP_MS = 780.0        # 判定文字（PERFECT/GREAT/…）上浮 + 淡出时长
POPUP_BOX_W = 160.0     # 判定文字的绘制框宽度（居中在音轨上，钳在控件内）
COMBO_HOLD_MS = 1500.0  # 连击数字停留在高亮状态的时长


class WaterfallWidget(QWidget):
    def __init__(self, settings: Settings, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self._settings = settings
        self._score: Optional[Score] = None
        self._position: Callable[[], float] = lambda: 0.0
        self._playing = False
        self._column_info: Optional[Callable[[int], tuple]] = None  # 校准对齐
        self._preview = False       # 校准模式：绘制列参考线
        self._loop_range: Optional[tuple] = None   # (A ms, B ms)
        # ---- 命中反馈（判定 / 连击 / 得分） ----
        self._feedback_on = True
        self._popups: list = []     # 判定文字浮层：[{col,text,color,born}]
        self._combo = 0
        self._fb_score = 0          # 注意：命名避开 self._score（那是指的乐谱对象）
        self._combo_born = 0.0
        self._real_ms = 0.0         # 真实时钟（动画用，与播放速度/暂停无关）
        self.setMinimumHeight(120)
        self._update_height()

    # ---- 命中反馈接口 ----
    def set_real_ms(self, ms: float) -> None:
        """注入真实时钟（主控每帧调用），用于判定文字/连击的动画推进。"""
        self._real_ms = ms

    def set_feedback_enabled(self, on: bool) -> None:
        self._feedback_on = on
        if not on:
            self.clear_feedback()
        self.update()

    def clear_feedback(self) -> None:
        self._popups.clear()
        self._combo = 0
        self._fb_score = 0
        self.update()

    def push_judgment(self, col: int, text: str, color: str) -> None:
        """在某个音轨列底部弹出一条判定文字（PERFECT / GREAT / GOOD / MISS）。"""
        self._popups.append({"col": col, "text": text, "color": color,
                             "born": self._real_ms})
        if len(self._popups) > 12:
            self._popups = self._popups[-12:]
        self.update()

    def _popup_box_x(self, col: int) -> float:
        """判定文字框的左边界：居中在音轨上，但钳在控件内。

        最左 / 最右列的判定文字如果不钳，会被控件边缘裁掉（PERFECT -> RFECT）。
        """
        cx = self._col_x(col) + self._note_width(col) / 2
        x0 = cx - POPUP_BOX_W / 2
        return max(0.0, min(x0, max(0.0, self.width() - POPUP_BOX_W)))

    def set_combo(self, combo: int, score: int) -> None:
        if combo != self._combo:
            self._combo_born = self._real_ms
        self._combo = combo
        self._fb_score = score
        self.update()

    # ---- 外部接口 ----
    def set_score(self, score: Score) -> None:
        self._score = score

    def set_loop_range(self, a_ms: Optional[float], b_ms: Optional[float]) -> None:
        """A-B 循环区间（ms）；None = 不显示标记。"""
        self._loop_range = None if (a_ms is None or b_ms is None) else (a_ms, b_ms)
        self.update()

    def lookahead_ms(self) -> float:
        """音符从顶部滑到判定线所需时间：越大越慢。"""
        v = float(getattr(self._settings, "lookahead_ms", LOOKAHEAD_MS))
        return max(MIN_LOOKAHEAD_MS, min(MAX_LOOKAHEAD_MS, v))

    def set_position_provider(self, provider: Callable[[], float]) -> None:
        self._position = provider

    def set_playing(self, playing: bool) -> None:
        self._playing = playing

    def set_column_info(self, provider: Optional[Callable[[int], tuple]]) -> None:
        """注入琴键几何提供器：col -> (列中心 x, 音符宽度)。

        由 overlay 注入 keys.column_info，保证音轨与琴键中心对齐
        （默认网格与校准自由布局均适用）。
        """
        self._column_info = provider
        self.update()

    def set_calibration_preview(self, on: bool) -> None:
        self._preview = on
        self.update()

    def _update_height(self) -> None:
        self.setFixedHeight(self._settings.waterfall_height)

    def apply_settings(self) -> None:
        self._update_height()

    # ---- 几何 ----
    def _judge_y(self) -> float:
        return self.height() - 26.0

    def _col_x(self, col: int) -> float:
        x, _w = self._col_rect(col)
        return x

    def _note_width(self, col: int) -> float:
        _x, w = self._col_rect(col)
        return w

    def _col_rect(self, col: int) -> tuple:
        """返回音符块的 (左边缘 x, 宽度)：优先跟随校准后的琴键中心。"""
        if self._column_info is not None:
            try:
                cx, w = self._column_info(col)
                return (max(2.0, cx - w / 2.0), w)
            except Exception:
                pass
        pad = 24.0
        col_w = (self.width() - pad * 2) / 8.0
        x = pad + col * col_w + (col_w - NOTE_WIDTH) / 2.0
        return (max(pad, x), NOTE_WIDTH)

    def _y_of(self, t: float, pos: float) -> float:
        """曲目时间 t 映射到 Y 坐标：t=pos 时正好在判定线上。"""
        judge_y = self._judge_y()
        top_y = 6.0
        progress = (t - pos) / self.lookahead_ms()  # 0=判定线, 1=顶部
        return judge_y - progress * (judge_y - top_y)

    # ---- 绘制 ----
    def paintEvent(self, event) -> None:  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)

        # 面板底色
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(13, 24, 32, 128))
        p.drawRoundedRect(self.rect(), 10, 10)

        if self._score is None:
            return
        pos = self._position()
        bpm = self._score.bpm
        beat_ms = 60000.0 / bpm
        judge_y = self._judge_y()

        self._paint_beat_lines(p, pos, beat_ms, judge_y)
        if self._preview:
            self._paint_preview_lines(p)
        self._paint_notes(p, pos, bpm)
        self._paint_judge_line(p, pos, bpm)
        self._paint_count_in(p, pos)
        self._paint_feedback(p)

    # ---- 命中反馈渲染（PERFECT/GREAT/GOOD/MISS + 连击 + 得分） ----
    def _paint_feedback(self, p: QPainter) -> None:
        if not self._feedback_on:
            return
        judge_y = self._judge_y()

        # 判定文字：自判定线向上浮起并淡出
        alive = []
        for pu in self._popups:
            age = self._real_ms - pu["born"]
            if age < 0 or age > POPUP_MS:
                continue
            alive.append(pu)
            k = age / POPUP_MS
            alpha = int(255 * max(0.0, 1.0 - k) ** 1.4)
            if alpha <= 2:
                continue
            col = pu["col"]
            y = judge_y - 26.0 - k * 48.0
            # 字号先弹大再回落。
            # 上限刻意压到 28：文字框钳在控件内后，最左列的判定文字会紧贴
            # 左边缘，而左边缘还要给曲目侧边栏的 22px 把手让位——字号再大，
            # PERFECT 的头一个字母就会被把手压掉。
            size = int(20 + 8 * max(0.0, 1.0 - k * 3.0))
            p.setFont(QFont(THEME.font_mono, size, QFont.Weight.Bold))
            c = QColor(pu["color"])
            c.setAlpha(alpha)
            p.setPen(c)
            # 文字框（160 宽）居中在音轨上，但必须钳在控件内——
            # 否则最左/最右列的判定文字会被裁掉（PERFECT 变 RFECT）。
            x0 = self._popup_box_x(col)
            p.drawText(QRectF(x0, y - 18, POPUP_BOX_W, 36),
                       Qt.AlignmentFlag.AlignCenter, pu["text"])
        self._popups = alive

        # 连击数字：命中后弹跳放大，静置一段时间后变淡
        if self._combo >= 2:
            idle = self._real_ms - self._combo_born
            alpha = int(210 * max(0.22, 1.0 - idle / COMBO_HOLD_MS))
            pop = max(0.0, 1.0 - idle / 150.0)          # 刚命中时 1 -> 0
            size = int(30 + 12 * pop)
            color = THEME.gold if self._combo >= 10 else THEME.primary
            p.setFont(QFont(THEME.font_mono, size, QFont.Weight.Bold))
            c = QColor(color)
            c.setAlpha(alpha)
            p.setPen(c)
            p.drawText(QRectF(self.width() / 2 - 120, self.height() * 0.10,
                              240, size + 8),
                       Qt.AlignmentFlag.AlignCenter, str(self._combo))
            p.setFont(QFont(THEME.font_mono, 9, QFont.Weight.Bold))
            c2 = QColor(THEME.text_secondary)
            c2.setAlpha(alpha)
            p.setPen(c2)
            p.drawText(QRectF(self.width() / 2 - 120, self.height() * 0.10 - 16,
                              240, 16),
                       Qt.AlignmentFlag.AlignCenter, "COMBO")

        # 得分：右上角常驻
        if self._fb_score > 0:
            p.setFont(QFont(THEME.font_mono, 10, QFont.Weight.Bold))
            p.setPen(QColor(THEME.text_secondary))
            p.drawText(QRectF(self.width() - 160, 6, 150, 18),
                       Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                       f"得分 {self._fb_score}")

    def _paint_preview_lines(self, p: QPainter) -> None:
        """校准模式：每个琴键中心画垂直虚线，直通判定线，方便对齐。"""
        pen = QPen(QColor(THEME.primary))
        pen.setStyle(Qt.PenStyle.DashLine)
        pen.setWidthF(1.0)
        pen.setDashPattern([4, 6])
        p.setPen(pen)
        for col in range(8):
            cx = self._col_x(col) + self._note_width(col) / 2
            p.drawLine(QPointF(cx, 4.0), QPointF(cx, self._judge_y()))

    def _paint_beat_lines(self, p: QPainter, pos: float,
                          beat_ms: float, judge_y: float) -> None:
        if not self._settings.show_beat_lines:
            return
        beats_per_bar = 4
        first = int(pos // beat_ms) + 1
        t = first * beat_ms
        while t <= pos + self.lookahead_ms():
            y = self._y_of(t, pos)
            if 0 <= y <= self.height():
                heavy = (first % beats_per_bar) == 0
                alpha = 26 if heavy else 13
                p.setPen(QColor(255, 255, 255, alpha))
                p.drawLine(QPointF(24, y), QPointF(self.width() - 24, y))
            first += 1
            t = first * beat_ms

    def _paint_notes(self, p: QPainter, pos: float, bpm: float) -> None:
        for note in self._score.notes:  # type: ignore
            if note.type is NoteType.REST:
                continue
            t0, t1 = note.start_ms(bpm), note.end_ms(bpm)
            y0 = self._y_of(t0, pos)   # 头部（判定线端）
            y1 = self._y_of(t1, pos)   # 尾部（后端）
            if y1 > self.height() or y0 < 0:
                continue  # 完全离开可见区
            col = self._score.key_index(note.key)  # type: ignore
            if col < 0:
                continue
            x = self._col_x(col)
            nw = self._note_width(col)
            base = THEME.pitch_color(col)

            if note.type is NoteType.TAP:
                self._paint_tap(p, note, x, nw, y0, t0, pos, base)
            else:
                self._paint_hold(p, note, x, nw, y0, y1, t0, t1, pos, base)

    # ---- 短按音符 ----
    def _paint_tap(self, p: QPainter, note: Note, x: float, nw: float, y0: float,
                   t0: float, pos: float, base: str) -> None:
        top = y0 - TAP_HEIGHT
        rect = QRectF(x, top, nw, TAP_HEIGHT)
        # 命中闪光：头部处于判定线附近
        dt = pos - t0
        if 0 <= dt <= FLASH_MS:
            k = 1.0 - dt / FLASH_MS
            glow = QRadialGradient(rect.center(), 26)
            glow.setColorAt(0, QColor(0, 229, 255, int(160 * k)))
            glow.setColorAt(1, QColor(0, 229, 255, 0))
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QBrush(glow))
            p.drawEllipse(rect.center(), 26, 26)
        grad = QLinearGradient(x, top, x, top + TAP_HEIGHT)
        grad.setColorAt(0, QColor(base))
        grad.setColorAt(1, QColor(base).darker(160))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QBrush(grad))
        p.drawRoundedRect(rect, 6, 6)
        self._paint_accidental(p, note, x, top, nw, TAP_HEIGHT)

    # ---- 长按音符 ----
    def _paint_hold(self, p: QPainter, note: Note, x: float, nw: float, y0: float,
                    y1: float, t0: float, t1: float, pos: float, base: str) -> None:
        s = self._settings
        height = max(y0 - y1, TAP_HEIGHT)
        active = t0 <= pos <= t1
        remaining = max(0.0, (t1 - pos) / max(t1 - t0, 1.0))

        # 剩余 <20% 且已进入长按阶段：渐变到橙色（松开预警）
        color = base
        if s.countdown_warning and active and remaining < 0.2:
            color = lerp_color(base, THEME.secondary, (0.2 - remaining) / 0.2)

        rect = QRectF(x, y1, nw, height)
        grad = QLinearGradient(x, y1, x, y1 + height)
        grad.setColorAt(0, QColor(color))
        grad.setColorAt(1, QColor(color).darker(150))

        # 长按中：外发光
        if active:
            glow = QColor(color)
            glow.setAlpha(110)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(glow)
            p.drawRoundedRect(rect.adjusted(-3, -3, 3, 3), 9, 9)

        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QBrush(grad))
        p.drawRoundedRect(rect, 6, 6)
        # 半透明白描边
        pen = QPen(QColor(255, 255, 255, 60))
        pen.setWidthF(1.0)
        p.setPen(pen)
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRoundedRect(rect, 6, 6)

        # 内部流光：自上而下循环流动
        if s.hold_shine and height > 34 and not active:
            phase = (pos % 1000.0) / 1000.0
            shine_y = y1 + phase * (height - 8)
            sg = QLinearGradient(x, shine_y, x, shine_y + 12)
            sg.setColorAt(0, QColor(255, 255, 255, 0))
            sg.setColorAt(0.5, QColor(255, 255, 255, 70))
            sg.setColorAt(1, QColor(255, 255, 255, 0))
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QBrush(sg))
            p.drawRect(QRectF(x + 2, shine_y, nw - 4, 12))

        # 尾部菱形（松开标记）：接近松开时闪烁
        tail_c = QPointF(x + nw / 2, y1)
        blink = active and remaining < 0.2 and (int(pos / 100) % 2 == 0)
        tail_color = QColor(THEME.secondary if blink else color)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(tail_color)
        self._paint_diamond(p, tail_c, 6.0)

        # 头部亮条（按下标记）
        head = QRectF(x + 2, y0 - 8, nw - 4, 8)
        p.setBrush(QColor(255, 255, 255, 220 if active else 120))
        p.drawRoundedRect(head, 4, 4)
        self._paint_accidental(p, note, x, y1, nw, height)

    def _paint_accidental(self, p: QPainter, note: Note, x: float, y: float,
                          nw: float, h: float) -> None:
        """半音音符右上角画 #（升调）/ b（降调）标记。"""
        if note.accidental == 0:
            return
        mark = "#" if note.accidental > 0 else "b"
        font = QFont(THEME.font_mono, max(9, int(min(nw, h) * 0.55)),
                     QFont.Weight.Bold)
        p.setFont(font)
        p.setPen(QColor(THEME.secondary))
        p.drawText(QRectF(x + nw * 0.50, y, nw * 0.46, max(h, TAP_HEIGHT)),
                   Qt.AlignmentFlag.AlignCenter, mark)

    @staticmethod
    def _paint_diamond(p: QPainter, center: QPointF, r: float) -> None:
        pts = [QPointF(center.x(), center.y() - r), QPointF(center.x() + r, center.y()),
               QPointF(center.x(), center.y() + r), QPointF(center.x() - r, center.y())]
        from PySide6.QtGui import QPolygonF
        p.drawPolygon(QPolygonF(pts))

    # ---- 判定线 ----
    def _paint_judge_line(self, p: QPainter, pos: float, bpm: float) -> None:
        judge_y = self._judge_y()
        # 是否有音符正处于判定线
        hit = False
        hit_col = -1
        for note in self._score.notes:  # type: ignore
            if note.type is NoteType.REST:
                continue
            if note.start_ms(bpm) <= pos <= note.end_ms(bpm):
                hit = True
                hit_col = self._score.key_index(note.key)  # type: ignore
                break

        alpha = 255 if hit else 100
        pen = QPen(QColor(0, 229, 255, alpha))
        pen.setWidthF(2.0)
        if hit:
            glow_pen = QPen(QColor(0, 229, 255, 60))
            glow_pen.setWidthF(8.0)
            p.setPen(glow_pen)
            p.drawLine(QPointF(24, judge_y), QPointF(self.width() - 24, judge_y))
        p.setPen(pen)
        p.drawLine(QPointF(24, judge_y), QPointF(self.width() - 24, judge_y))

        # 判定菱形跟随当前音符列
        if hit and hit_col >= 0:
            cx = self._col_x(hit_col) + self._note_width(hit_col) / 2
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(0, 229, 255, 230))
            self._paint_diamond(p, QPointF(cx, judge_y), 6.0)

    def _paint_count_in(self, p: QPainter, pos: float) -> None:
        if pos >= 0 or self._score is None:
            return
        beat_ms = 60000.0 / self._score.bpm
        remain = int(-pos / beat_ms) + 1
        font = QFont(THEME.font_mono, 16, QFont.Weight.Bold)
        p.setFont(font)
        p.setPen(QColor(232, 237, 245, 200))
        p.drawText(QRectF(0, self.height() / 2 - 60, self.width(), 40),
                   Qt.AlignmentFlag.AlignCenter, "准备")
        p.setPen(QColor(0, 229, 255))
        p.drawText(QRectF(0, self.height() / 2 - 20, self.width(), 60),
                   Qt.AlignmentFlag.AlignCenter, str(max(remain, 1)))
