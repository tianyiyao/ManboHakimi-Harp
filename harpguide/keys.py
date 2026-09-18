# -*- coding: utf-8 -*-
"""琴键提示区：8 键（Z X C V B N M ,）双行标注 + 七态状态机。

状态        触发条件                         视觉
IDLE        无音符                            深灰半透明
UPCOMING    下一个音符 1 拍内                 橙色边框 + 橙色淡填充
PREPARING   长按音符提前 N 拍                 音符色边框呼吸闪烁（提示"要按住"）
ACTIVE_TAP  短按音符处于判定中                青色实心 + 发光（快速闪过）
ACTIVE_HOLD 长按音符按住中                    音符色实心 + 旋转虚线光环
NEAR_RELEASE 长按剩余 <20%                    橙色实心 + 边框闪烁 + 剩余进度条
DONE        音符刚结束 250ms 内               绿色淡填充渐隐

v0.4 校准模式：
- set_geometries() 注入自由布局（None = 默认网格）
- set_calibrating(True) 进入编辑：拖动琴键移动、滚轮缩放、方向键微调
- geometry_changed 信号通知瀑布流重新对齐列中心
"""
from __future__ import annotations

from enum import Enum, auto
from typing import Dict, List, Optional

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QBrush, QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import QWidget

from .calibration import (KeyGeom, MAX_KEY_SIZE, MIN_KEY_SIZE,
                          clamp_geom, default_geometries)
from .config import Settings
from .models import KEY_LABELS, NoteType, Score
from .theme import THEME, lerp_color

DONE_LINGER_MS = 300.0
WIDGET_HEIGHT = 120.0
HIT_FLASH_MS = 260.0      # 命中反馈光环时长（真实毫秒）


class KeyState(Enum):
    IDLE = auto()
    UPCOMING = auto()
    PREPARING = auto()
    ACTIVE_TAP = auto()
    ACTIVE_HOLD = auto()
    NEAR_RELEASE = auto()
    DONE = auto()


class KeyHintWidget(QWidget):
    geometry_changed = Signal()   # 校准模式下几何被修改

    def __init__(self, settings: Settings, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self._settings = settings
        self._score: Optional[Score] = None
        self._pos_ms: float = 0.0
        self._real_ms: float = 0.0
        self._done_at: Dict[str, float] = {}  # key -> 结束时刻（真实毫秒）
        # 命中反馈：col -> (按下时刻 real_ms, 颜色)
        self._hit_flash: Dict[int, tuple] = {}

        # 校准状态
        self._geoms: Optional[List[KeyGeom]] = None   # None = 默认网格
        self._calibrating = False
        self._hover_idx = -1
        self._drag_idx = -1
        self._drag_off = QPointF(0, 0)

        self.setFixedHeight(int(WIDGET_HEIGHT))
        self.setMinimumWidth(320)
        self.setMouseTracking(True)

    # ---- 校准接口 ----
    def set_geometries(self, geoms: Optional[List[KeyGeom]]) -> None:
        """注入自由布局；None 恢复默认网格。"""
        if geoms is None:
            self._geoms = None
        else:
            self._geoms = [clamp_geom(g, self.width(), self.height()) for g in geoms]
        self.geometry_changed.emit()
        self.update()

    def geometries(self) -> Optional[List[KeyGeom]]:
        return [KeyGeom(g.x, g.y, g.size) for g in self._geoms] if self._geoms else None

    def set_calibrating(self, on: bool) -> None:
        self._calibrating = on
        self._hover_idx = -1
        self._drag_idx = -1
        self.update()

    @property
    def calibrating(self) -> bool:
        return self._calibrating

    def geom_list(self) -> List[KeyGeom]:
        """当前生效的几何（校准布局或默认网格）。"""
        if self._geoms is not None:
            return self._geoms
        return default_geometries(self.width())

    def column_info(self, col: int) -> tuple:
        """瀑布流对齐用：返回 (列中心 x, 音符宽度)。"""
        geoms = self.geom_list()
        if 0 <= col < len(geoms):
            g = geoms[col]
            note_w = max(20.0, min(g.size - 8.0, 60.0))
            return (g.x, note_w)
        return (0.0, 40.0)

    def reset_to_default(self) -> None:
        """校准模式中：把工作副本重置为默认网格。"""
        self._geoms = None
        self.geometry_changed.emit()
        self.update()

    def rescale_geometries(self, old_w: float, new_w: float) -> None:
        """窗口宽度变化时，按比例缩放已校准的琴键几何，保持相对对齐。

        高度方向（y）不缩放（keys 区高度固定）；size 也按宽度比例缩放
        以保持键间距的相对关系。无校准数据（默认网格）时无需处理。
        """
        if old_w <= 0 or new_w <= 0 or self._geoms is None:
            return
        ratio = new_w / old_w
        self._geoms = [clamp_geom(
            KeyGeom(g.x * ratio, g.y, g.size * ratio),
            new_w, self.height()) for g in self._geoms]
        self.geometry_changed.emit()
        self.update()

    def scale_all(self, factor: float) -> None:
        """校准模式中：整体缩放（围绕各键中心）。"""
        geoms = self.geom_list()
        for g in geoms:
            g.size = max(MIN_KEY_SIZE, min(MAX_KEY_SIZE, g.size * factor))
        self._geoms = geoms
        # 缩放后重新夹紧位置
        self._geoms = [clamp_geom(g, self.width(), self.height()) for g in geoms]
        self.geometry_changed.emit()
        self.update()

    # ---- 曲目 / 帧驱动 ----
    def set_score(self, score: Score) -> None:
        self._score = score
        self._done_at.clear()
        self._hit_flash.clear()

    def flash_hit(self, col: int, color: str) -> None:
        """命中反馈：让某个琴键闪一次光环（判定成功=判定色，MISS=红色）。"""
        if col < 0:
            return
        self._hit_flash[col] = (self._real_ms, color)
        self.update()

    def clear_feedback(self) -> None:
        self._hit_flash.clear()
        self.update()

    def tick(self, pos_ms: float, real_ms: float) -> None:
        """每帧由主控调用：传入曲目位置与真实时钟。"""
        self._pos_ms = pos_ms
        self._real_ms = real_ms
        self._track_done(real_ms)
        # 清理过期的命中光环
        if self._hit_flash:
            for c in list(self._hit_flash.keys()):
                if real_ms - self._hit_flash[c][0] > HIT_FLASH_MS:
                    del self._hit_flash[c]
        self.update()

    def _track_done(self, real_ms: float) -> None:
        if not self._score:
            return
        for note in self._score.notes:
            if note.type is NoteType.REST or note.key == "rest":
                continue
            if note.end_ms(self._score.bpm) <= self._pos_ms:
                self._done_at[note.key] = note.end_ms(self._score.bpm)
        if len(self._done_at) > 8:
            self._done_at.clear()

    # ---- 状态计算 ----
    def _states(self) -> Dict[str, KeyState]:
        # 注意顺序：None 检查必须在解引用 _score 之前。
        # 旧写法先取 self._score.keymap 再判断 if not self._score，一旦没有曲目
        # 就是 'NoneType' object has no attribute 'keymap'（paintEvent 里的
        # 前置判断恰好挡住了它，但任何直接调用都会炸）。
        if not self._score:
            return {}
        states = {k: KeyState.IDLE for k in self._score.keymap}
        bpm = self._score.bpm
        beat_ms = 60000.0 / bpm
        lead_ms = self._settings.preparation_lead_beats * beat_ms

        for note in self._score.notes:
            if note.type is NoteType.REST or note.key not in states:
                continue
            t0, t1 = note.start_ms(bpm), note.end_ms(bpm)
            if t0 <= self._pos_ms < t1:
                # 当前音符
                if note.type is NoteType.TAP:
                    states[note.key] = KeyState.ACTIVE_TAP
                else:
                    remaining = (t1 - self._pos_ms) / max(t1 - t0, 1.0)
                    if (self._settings.countdown_warning
                            and remaining < 0.2):
                        states[note.key] = KeyState.NEAR_RELEASE
                    else:
                        states[note.key] = KeyState.ACTIVE_HOLD
            elif t0 > self._pos_ms:
                # 未来音符：取每键第一个未来音符
                if states[note.key] is KeyState.IDLE:
                    if note.type is NoteType.HOLD and t0 - self._pos_ms <= lead_ms:
                        states[note.key] = KeyState.PREPARING
                    elif t0 - self._pos_ms <= beat_ms:
                        states[note.key] = KeyState.UPCOMING
        # 刚结束 -> DONE
        for key, end_beat_ms in self._done_at.items():
            if key in states and states[key] is KeyState.IDLE:
                if self._pos_ms - end_beat_ms < 600.0:
                    states[key] = KeyState.DONE
        return states

    # ---- 绘制 ----
    def paintEvent(self, event) -> None:  # noqa: N802
        if not self._score and not self._calibrating:
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)

        if self._calibrating:
            self._paint_calibrating(p)
            return

        states = self._states()
        for i, key in enumerate(self._score.keymap):  # type: ignore
            g = self.geom_list()[i]
            self._paint_key(p, g, key, i, states.get(key, KeyState.IDLE))
        self.update()

    # 校准模式渲染：简化样式 + 拖拽提示
    def _paint_calibrating(self, p: QPainter) -> None:
        geoms = self.geom_list()
        keymap = self._score.keymap if self._score else ["Z", "X", "C", "V", "B", "N", "M", ","]
        for i, g in enumerate(geoms):
            rect = QRectF(g.x - g.size / 2, g.y - g.size / 2, g.size, g.size)
            selected = (i == self._hover_idx or i == self._drag_idx)
            pitch = QColor(THEME.pitch_color(i))

            if selected:
                # 选中：外发光 + 白色描边
                glow = QColor(THEME.primary)
                glow.setAlpha(110)
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(glow)
                p.drawRoundedRect(rect.adjusted(-4, -4, 4, 4), 12, 12)

            p.setPen(QPen(pitch, 2.0 if selected else 1.2))
            p.setBrush(QColor(THEME.surface_alt))
            p.drawRoundedRect(rect, 10, 10)

            # 键位字母
            font_l = QFont(THEME.font_mono, max(8, int(g.size * 0.28)),
                           QFont.Weight.Bold)
            p.setFont(font_l)
            p.setPen(QColor(THEME.primary if selected else THEME.text_primary))
            p.drawText(rect, Qt.AlignmentFlag.AlignCenter, keymap[i])

            # 中心十字准星
            p.setPen(QPen(QColor(255, 255, 255, 140), 1.0))
            r = 4.0
            p.drawLine(QPointF(g.x - r, g.y), QPointF(g.x + r, g.y))
            p.drawLine(QPointF(g.x, g.y - r), QPointF(g.x, g.y + r))

        # 底部提示条
        hint = "拖动琴键移动 · 滚轮缩放 · 方向键微调（1px，Shift=10px）"
        p.setFont(QFont(THEME.font_sans, 9))
        p.setPen(QColor(THEME.text_secondary))
        p.drawText(QRectF(0, self.height() - 18, self.width(), 16),
                   Qt.AlignmentFlag.AlignCenter, hint)

    def _paint_key(self, p: QPainter, g: KeyGeom, key: str,
                   index: int, state: KeyState) -> None:
        x = g.x - g.size / 2
        y = g.y - g.size / 2
        size = g.size
        rect = QRectF(x, y, size, size)
        label = KEY_LABELS[index] if index < len(KEY_LABELS) else key
        blink = (int(self._real_ms / 120) % 2 == 0)

        bg, border, border_w, text_color, glow = None, None, 1.0, THEME.text_secondary, None
        pitch = THEME.pitch_color(index)

        if state is KeyState.IDLE:
            bg = QColor(30, 38, 51, 153)
            border = QColor(THEME.key_idle_border)
        elif state is KeyState.UPCOMING:
            bg = QColor(255, 107, 53, 100)
            border = QColor(THEME.secondary)
            text_color = THEME.secondary
        elif state is KeyState.PREPARING:
            # 呼吸边框：提示"这个键要按住"
            bg = QColor(THEME.surface_alt)
            border = QColor(pitch) if blink else QColor(pitch).darker(180)
            border_w = 2.0
            text_color = pitch
        elif state is KeyState.ACTIVE_TAP:
            bg = QColor(pitch)
            glow = QColor(pitch)
            text_color = THEME.background
        elif state is KeyState.ACTIVE_HOLD:
            bg = QColor(pitch)
            glow = QColor(pitch)
            text_color = THEME.background
        elif state is KeyState.NEAR_RELEASE:
            bg = QColor(THEME.secondary if blink else lerp_color(
                pitch, THEME.secondary, 0.6))
            glow = QColor(THEME.secondary)
            border = QColor(THEME.secondary)
            border_w = 2.0
            text_color = THEME.background
        elif state is KeyState.DONE:
            bg = QColor(0, 255, 136, 76)
            text_color = THEME.success

        # 外发光
        if glow is not None:
            gcol = QColor(glow)
            gcol.setAlpha(90)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(gcol)
            p.drawRoundedRect(rect.adjusted(-3, -3, 3, 3), 13, 13)

        # 主体
        if border is not None:
            p.setPen(QPen(QColor(border), border_w))
        else:
            p.setPen(QPen(Qt.PenStyle.NoPen))
        p.setBrush(QBrush(bg) if bg is not None else Qt.BrushStyle.NoBrush)
        p.drawRoundedRect(rect, 10, 10)

        # 长按旋转虚线光环
        if state in (KeyState.ACTIVE_HOLD,):
            ring_pen = QPen(QColor(pitch))
            ring_pen.setWidthF(2.0)
            ring_pen.setStyle(Qt.PenStyle.DashLine)
            ring_pen.setDashPattern([6, 5])
            # 用时间驱动相位实现旋转
            phase = (self._real_ms / 40.0) % 11.0
            ring_pen.setDashOffset(phase)
            p.setPen(ring_pen)
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawEllipse(rect.center(), size / 2 + 7, size / 2 + 7)

        # 文字：上行简谱数字，下行键位字母（字号随键尺寸缩放）
        font_n = QFont(THEME.font_mono, max(9, int(size * 0.23)), QFont.Weight.Bold)
        font_l = QFont(THEME.font_mono, max(7, int(size * 0.14)), QFont.Weight.Normal)
        p.setFont(font_n)
        p.setPen(QColor(text_color))
        p.drawText(QRectF(x, y + size * 0.14, size, size * 0.36),
                   Qt.AlignmentFlag.AlignCenter, label)
        p.setFont(font_l)
        p.setPen(QColor(text_color).darker(140))
        p.drawText(QRectF(x, y + size * 0.55, size, size * 0.28),
                   Qt.AlignmentFlag.AlignCenter, key)

        # 高音 1 上方圆点（简谱记法）
        if index == 7:
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(text_color))
            p.drawEllipse(QPointF(x + size / 2, y + size * 0.08), 2.0, 2.0)

        # 半音标记：需要切「升调」(#) / 「降调」(b) 推键时，右上角画醒目符号
        acc = self._key_accidental(key)
        if acc != 0:
            mark = "#" if acc > 0 else "b"
            mark_font = QFont(THEME.font_mono, max(9, int(size * 0.20)),
                              QFont.Weight.Bold)
            p.setFont(mark_font)
            p.setPen(QColor(THEME.secondary))
            p.drawText(QRectF(x + size * 0.52, y + size * 0.02, size * 0.44, size * 0.30),
                       Qt.AlignmentFlag.AlignCenter, mark)

        # 长按剩余进度条
        if state in (KeyState.ACTIVE_HOLD, KeyState.NEAR_RELEASE) and self._score:
            self._paint_hold_progress(p, rect, key)

        # 命中反馈光环：按下瞬间扩散一圈判定色光环 + 键体白闪
        flash = self._hit_flash.get(index)
        if flash is not None:
            born, fcolor = flash
            k = max(0.0, min(1.0, (self._real_ms - born) / HIT_FLASH_MS))
            grow = size * 0.20 * k
            ring = rect.adjusted(-grow - 3, -grow - 3, grow + 3, grow + 3)
            pen = QPen(QColor(fcolor), max(1.0, 3.2 * (1.0 - k)))
            p.setPen(pen)
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawRoundedRect(ring, 12 + grow * 0.3, 12 + grow * 0.3)
            wfade = int(170 * max(0.0, 1.0 - k) ** 1.5)
            if wfade > 2:
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(QColor(255, 255, 255, wfade))
                p.drawRoundedRect(rect, 10, 10)

    def _paint_hold_progress(self, p: QPainter, rect: QRectF, key: str) -> None:
        """琴键底部剩余时间进度条：从满到空。"""
        note = self._find_current_note(key)
        if note is None:
            return
        t0, t1 = note.start_ms(self._score.bpm), note.end_ms(self._score.bpm)  # type: ignore
        remaining = max(0.0, min(1.0, (t1 - self._pos_ms) / max(t1 - t0, 1.0)))
        bar_h = 4.0
        bar_rect = QRectF(rect.x() + 6, rect.bottom() - bar_h - 5,
                          rect.width() - 12, bar_h)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(10, 14, 20, 180))
        p.drawRoundedRect(bar_rect, 2, 2)
        color = THEME.secondary if remaining < 0.2 else THEME.success
        p.setBrush(QColor(color))
        fill_w = bar_rect.width() * remaining
        if fill_w > 1:
            p.drawRoundedRect(QRectF(bar_rect.x(), bar_rect.y(),
                                     fill_w, bar_h), 2, 2)

    def _find_current_note(self, key: str):
        if not self._score:
            return None
        bpm = self._score.bpm
        for note in self._score.notes:
            if note.key == key and note.type is NoteType.HOLD:
                if note.start_ms(bpm) <= self._pos_ms < note.end_ms(bpm):
                    return note
        return None

    def _key_accidental(self, key: str) -> int:
        """返回该键「当前需要」的调性档（取活跃音符，否则最近未来音符）。

        用于在琴键右上角画 #/b 标记，提示玩家切半音阶口风琴的推键。
        """
        if not self._score:
            return 0
        bpm = self._score.bpm
        beat_ms = 60000.0 / bpm
        upcoming = None
        for note in self._score.notes:
            if note.type is NoteType.REST or note.key != key:
                continue
            t0, t1 = note.start_ms(bpm), note.end_ms(bpm)
            if t0 <= self._pos_ms < t1:
                return note.accidental          # 活跃音符优先
            if t0 > self._pos_ms and upcoming is None:
                upcoming = note
        if upcoming is not None and upcoming.start_ms(bpm) - self._pos_ms <= beat_ms * 2:
            return upcoming.accidental          # 未来 2 拍内提前提示
        return 0

    # ---- 校准编辑交互 ----
    def _hit_test(self, pos: QPointF) -> int:
        """返回命中（或最近）的键索引，未命中返回 -1。"""
        geoms = self.geom_list()
        for i in range(len(geoms) - 1, -1, -1):   # 后绘制者优先
            g = geoms[i]
            half = g.size / 2 + 6.0               # 判定略放宽
            if (abs(pos.x() - g.x) <= half and abs(pos.y() - g.y) <= half):
                return i
        return -1

    def mousePressEvent(self, e) -> None:  # noqa: N802
        if not self._calibrating:
            return
        if e.button() == Qt.MouseButton.LeftButton:
            pos = e.position()
            idx = self._hit_test(pos)
            self._hover_idx = idx
            if idx >= 0:
                g = self.geom_list()[idx]
                self._drag_idx = idx
                self._drag_off = QPointF(pos.x() - g.x, pos.y() - g.y)
                self.setFocus(Qt.FocusReason.MouseFocusReason)
            self.update()

    def mouseMoveEvent(self, e) -> None:  # noqa: N802
        if not self._calibrating:
            return
        pos = e.position()
        if self._drag_idx >= 0:
            g = self.geom_list()[self._drag_idx]
            g.x = pos.x() - self._drag_off.x()
            g.y = pos.y() - self._drag_off.y()
            self._geoms = self.geom_list()   # 确保工作副本固化
            clamped = clamp_geom(g, self.width(), self.height())
            g.x, g.y, g.size = clamped.x, clamped.y, clamped.size
            self.geometry_changed.emit()
        else:
            self._hover_idx = self._hit_test(pos)
        self.update()

    def mouseReleaseEvent(self, e) -> None:  # noqa: N802
        self._drag_idx = -1
        if self._calibrating:
            self.update()

    def wheelEvent(self, e) -> None:  # noqa: N802
        if not self._calibrating:
            return
        idx = self._drag_idx if self._drag_idx >= 0 else self._hover_idx
        if idx < 0:
            idx = self._hit_test(e.position())
        if idx < 0:
            return
        g = self.geom_list()[idx]
        step = 2.0 if e.angleDelta().y() > 0 else -2.0
        g.size = max(MIN_KEY_SIZE, min(MAX_KEY_SIZE, g.size + step))
        self._geoms = self.geom_list()
        clamped = clamp_geom(g, self.width(), self.height())
        g.x, g.y = clamped.x, clamped.y
        self._hover_idx = idx
        self.geometry_changed.emit()
        self.update()

    def keyPressEvent(self, e) -> None:  # noqa: N802
        if not self._calibrating:
            return
        idx = self._drag_idx if self._drag_idx >= 0 else self._hover_idx
        if idx < 0:
            return
        step = 10.0 if e.modifiers() & Qt.KeyboardModifier.ShiftModifier else 1.0
        g = self.geom_list()[idx]
        if e.key() == Qt.Key.Key_Left:
            g.x -= step
        elif e.key() == Qt.Key.Key_Right:
            g.x += step
        elif e.key() == Qt.Key.Key_Up:
            g.y -= step
        elif e.key() == Qt.Key.Key_Down:
            g.y += step
        elif e.key() in (Qt.Key.Key_Plus, Qt.Key.Key_Equal):
            g.size = min(MAX_KEY_SIZE, g.size + step)
        elif e.key() == Qt.Key.Key_Minus:
            g.size = max(MIN_KEY_SIZE, g.size - step)
        else:
            return
        self._geoms = self.geom_list()
        clamped = clamp_geom(g, self.width(), self.height())
        g.x, g.y, g.size = clamped.x, clamped.y, clamped.size
        self.geometry_changed.emit()
        self.update()
