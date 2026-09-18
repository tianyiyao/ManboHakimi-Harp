# -*- coding: utf-8 -*-
"""主浮窗：无边框透明置顶窗口。

- 顶部信息条：♪ 曲名 | BPM | 倍率 | 进度时间 | 齿轮（设置）
- 拖动信息条移动窗口；齿轮打开设置面板
- 鼠标穿透可切换（Ctrl+Shift+T）
"""
from __future__ import annotations

import ctypes
import ctypes.wintypes as wt
import sys
from typing import Callable, Optional

from PySide6.QtCore import QPoint, QPointF, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import (QBrush, QColor, QFont, QGuiApplication,
                           QLinearGradient, QPainter, QPen)
from PySide6.QtWidgets import QHBoxLayout, QLabel, QVBoxLayout, QWidget

from .config import Settings
from .hintbar import HotkeyBar
from .keys import KeyHintWidget
from .lyrics import LyricWidget
from .models import Score
from .sidebar import ScoreSidebar
from .theme import THEME
from .waterfall import WaterfallWidget

GWL_EXSTYLE = -20
WS_EX_LAYERED = 0x00080000
WS_EX_TRANSPARENT = 0x00000020
WS_EX_TOOLWINDOW = 0x00000080
WS_EX_NOACTIVATE = 0x08000000

# WM_NCHITTEST 相关：让系统处理无边框窗口的边缘拖拽 resize
WM_NCHITTEST = 0x0084
HTCLIENT = 1
HTLEFT, HTRIGHT, HTTOP, HTBOTTOM = 10, 11, 12, 15
HTTOPLEFT, HTTOPRIGHT = 13, 14
HTBOTTOMLEFT, HTBOTTOMRIGHT = 16, 17


class TopBar(QWidget):
    """顶部信息条：双击标题无操作；拖动移动窗口；齿轮发信号。"""
    settings_clicked = Signal()
    drag_moved = Signal(QPoint)

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setFixedHeight(44)
        self._drag_offset: Optional[QPoint] = None
        self._hover_gear = False

        self.name_label = QLabel("未选择曲目")
        self.name_label.setFont(QFont(THEME.font_sans, 11, QFont.Weight.Bold))
        self.name_label.setStyleSheet(f"color:{THEME.text_primary}; background:transparent;")

        self.bpm_label = QLabel("")
        self.bpm_label.setFont(QFont(THEME.font_mono, 10, QFont.Weight.Bold))
        self.bpm_label.setStyleSheet(f"color:{THEME.primary}; background:transparent;")

        self.speed_label = QLabel("")
        self.speed_label.setFont(QFont(THEME.font_mono, 9))
        self.speed_label.setStyleSheet(f"color:{THEME.text_secondary}; background:transparent;")

        self.time_label = QLabel("00:00 / 00:00")
        self.time_label.setFont(QFont(THEME.font_mono, 9))
        self.time_label.setStyleSheet(f"color:{THEME.text_secondary}; background:transparent;")

        self.transpose_label = QLabel("调性 自然♮")
        self.transpose_label.setFont(QFont(THEME.font_mono, 9, QFont.Weight.Bold))
        self.transpose_label.setStyleSheet(f"color:{THEME.text_secondary}; background:transparent;")

        # 最近命中平均偏移（供玩家校准「判定偏移」；少于 4 次命中时留空）
        self.offset_label = QLabel("")
        self.offset_label.setFont(QFont(THEME.font_mono, 9, QFont.Weight.Bold))
        self.offset_label.setStyleSheet(f"color:{THEME.text_secondary}; background:transparent;")

        lay = QHBoxLayout(self)
        lay.setContentsMargins(16, 4, 10, 4)
        lay.setSpacing(14)
        lay.addWidget(self.name_label)
        lay.addStretch(1)
        lay.addWidget(self.bpm_label)
        lay.addWidget(self.speed_label)
        lay.addWidget(self.transpose_label)
        lay.addWidget(self.offset_label)
        lay.addWidget(self.time_label)

    # ---- 命中偏移提示 ----
    def set_offset(self, avg_ms: Optional[float] = None, count: int = 0) -> None:
        """显示最近若干次命中的平均带符号偏移。

        |均值| 偏大说明玩家整体按早了/按晚了，可据此调整设置里的「判定偏移」；
        偏差很小时用绿色表示「手感已经对齐」。
        """
        if avg_ms is None or count < 4:
            self.offset_label.setText("")
            return
        self.offset_label.setText(f"偏移 {avg_ms:+.0f}ms")
        if abs(avg_ms) <= 110:
            color = THEME.success
        elif abs(avg_ms) <= 220:
            color = THEME.primary
        else:
            color = THEME.secondary
        self.offset_label.setStyleSheet(f"color:{color}; background:transparent;")

    # ---- 调性指示（半音阶口风琴推键） ----
    def set_transpose(self, current: int, required: int = 0, auto: bool = False) -> None:
        """更新调性指示。

        current=当前档(-1降/0自然/+1升)，required=当前音符需要的档，
        auto=自动变调模式（跟随歌曲，绿色显示，无需手动小键盘切调）。
        """
        names = {-1: "降调↓", 0: "自然♮", 1: "升调↑"}
        if auto:
            text = f"自动变调 · {names.get(current, '自然♮')}"
            color = THEME.success          # 绿色：自动跟随中
        else:
            text = f"调性 {names.get(current, '自然♮')}"
            if required != 0 and required != current:
                text += f" → 需{names.get(required, '')}"
                color = THEME.secondary    # 橙色：提示需要切推键
            elif current != 0:
                color = THEME.primary      # 青色：非自然档
            else:
                color = THEME.text_secondary
        self.transpose_label.setText(text)
        self.transpose_label.setStyleSheet(f"color:{color}; background:transparent;")

    # ---- 拖动移动窗口 ----
    def mousePressEvent(self, e) -> None:  # noqa: N802
        if e.button() == Qt.MouseButton.LeftButton:
            self._drag_offset = e.globalPosition().toPoint() - self.window().pos()

    def mouseMoveEvent(self, e) -> None:  # noqa: N802
        if self._drag_offset is not None:
            self.drag_moved.emit(
                e.globalPosition().toPoint() - self._drag_offset)

    def mouseReleaseEvent(self, e) -> None:  # noqa: N802
        self._drag_offset = None

    def paintEvent(self, event) -> None:  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        # ♪ 图标
        p.setPen(QPen(QColor(THEME.primary), 2.0))
        cx, cy = 12.0, self.height() / 2
        p.drawLine(QPointF(cx + 5, cy - 9), QPointF(cx + 5, cy + 4))
        p.drawEllipse(QPointF(cx + 2.5, cy + 4), 2.5, 2.5)
        p.drawEllipse(QPointF(cx + 7.5, cy + 3), 2.5, 2.5)
        p.drawLine(QPointF(cx + 10, cy - 8), QPointF(cx + 5, cy - 9))
        # 齿轮
        gx = self.width() - 18
        gy = self.height() / 2
        p.setPen(QPen(QColor(THEME.text_secondary), 1.6))
        p.drawEllipse(QPointF(gx, gy), 3.5, 3.5)
        for a in range(8):
            import math
            ang = a * math.pi / 4
            p.drawLine(
                QPointF(gx + 5.2 * math.cos(ang), gy + 5.2 * math.sin(ang)),
                QPointF(gx + 7.6 * math.cos(ang), gy + 7.6 * math.sin(ang)))

    def mouseDoubleClickEvent(self, e) -> None:  # noqa: N802
        pass


class ProgressBar(QWidget):
    """可交互进度条：点击 / 拖动跳转，并显示 A-B 循环区间。

    - 单击任意位置 -> 跳到该进度
    - 按住拖动 -> 连续擦洗（scrub）
    - 区间标记：A 点青色竖线、B 点橙色竖线、区间内部淡青高亮
    """

    seek_requested = Signal(float)     # 目标位置比例 0..1

    MARGIN = 16.0

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setFixedHeight(30)
        self.setMouseTracking(True)
        self._ratio = 0.0
        self._hover = False
        self._dragging = False
        self._loop_a: Optional[float] = None    # 比例
        self._loop_b: Optional[float] = None

    # ---- 外部接口 ----
    def set_ratio(self, r: float) -> None:
        self._ratio = max(0.0, min(1.0, r))
        self.update()

    def set_loop_range(self, a_ratio: Optional[float],
                       b_ratio: Optional[float]) -> None:
        self._loop_a, self._loop_b = a_ratio, b_ratio
        self.update()

    # ---- 坐标换算 ----
    def _track_rect(self) -> QRectF:
        return QRectF(self.MARGIN, self.height() / 2 - 2.0,
                      max(1.0, self.width() - self.MARGIN * 2), 4.0)

    def _ratio_at(self, x: float) -> float:
        t = self._track_rect()
        if t.width() <= 0:
            return 0.0
        return max(0.0, min(1.0, (x - t.left()) / t.width()))

    # ---- 交互 ----
    def mousePressEvent(self, e) -> None:  # noqa: N802
        if e.button() == Qt.MouseButton.LeftButton:
            self._dragging = True
            self.seek_requested.emit(self._ratio_at(e.position().x()))

    def mouseMoveEvent(self, e) -> None:  # noqa: N802
        self._hover = True
        if self._dragging:
            self.seek_requested.emit(self._ratio_at(e.position().x()))
        else:
            self.update()

    def mouseReleaseEvent(self, e) -> None:  # noqa: N802
        self._dragging = False
        self.update()

    def enterEvent(self, e) -> None:  # noqa: N802
        self._hover = True
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.update()

    def leaveEvent(self, e) -> None:  # noqa: N802
        self._hover = False
        self.update()

    # ---- 绘制 ----
    def paintEvent(self, event) -> None:  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        track = self._track_rect()

        # 轨道
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(30, 38, 51))
        p.drawRoundedRect(track, 2, 2)

        # A-B 循环区间高亮
        if self._loop_a is not None and self._loop_b is not None:
            x0 = track.left() + track.width() * min(self._loop_a, self._loop_b)
            x1 = track.left() + track.width() * max(self._loop_a, self._loop_b)
            band = QRectF(x0, track.top(), max(1.0, x1 - x0), track.height())
            p.setBrush(QColor(0, 229, 255, 64))
            p.drawRoundedRect(band, 2, 2)
            # A / B 竖线标记
            for cx, color, tag in ((x0, THEME.primary, "A"),
                                   (x1, THEME.secondary, "B")):
                p.setPen(QPen(QColor(color), 1.6))
                p.drawLine(QPointF(cx, track.top() - 5), QPointF(cx, track.bottom() + 5))
                p.setFont(QFont(THEME.font_mono, 7, QFont.Weight.Bold))
                p.setPen(QColor(color))
                p.drawText(QRectF(cx - 6, track.top() - 16, 12, 10),
                           Qt.AlignmentFlag.AlignCenter, tag)

        # 已播放部分
        if self._ratio > 0.005:
            fill = QRectF(track.left(), track.top(),
                          track.width() * self._ratio, track.height())
            grad = QLinearGradient(fill.left(), 0, fill.right(), 0)
            grad.setColorAt(0, QColor(THEME.primary))
            grad.setColorAt(1, QColor(THEME.success))
            p.setBrush(QBrush(grad))
            p.drawRoundedRect(fill, 2, 2)

        # 播放头手柄：悬停或拖动时放大
        hx = track.left() + track.width() * self._ratio
        r = 6.0 if (self._hover or self._dragging) else 4.0
        p.setPen(QPen(QColor(THEME.primary), 1.5))
        p.setBrush(QColor(THEME.text_primary))
        p.drawEllipse(QPointF(hx, track.center().y()), r, r)



class OverlayWindow(QWidget):
    """浮窗主窗口。"""

    resized = Signal(int, int)   # (width, height)：用户拖拽调整大小后发出

    # 布局常量（除瀑布流外所有固定部分）
    TOPBAR_H = 44
    KEYS_H = 120
    PROGRESS_H = 30
    LYRICS_H = 56
    MARGIN_TOP = 6
    MARGIN_BOTTOM = 4
    SPACING = 6
    MIN_WATERFALL = 100
    MIN_WIDTH = 360
    RESIZE_MARGIN = 8           # 边缘拖拽 resize 的像素宽度

    def __init__(self, settings: Settings, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self._settings = settings
        self._click_through = False
        self._total_ms = 0.0
        self._loop_a_ms = None
        self._loop_b_ms = None

        self.setWindowTitle("ManboHakimi-Harp")
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)

        self.topbar = TopBar()
        self.waterfall = WaterfallWidget(settings)
        self.keys = KeyHintWidget(settings)
        self.lyrics = LyricWidget()
        self.progress = ProgressBar()
        self.hotkeybar = HotkeyBar()

        # 瀑布流音轨列跟随琴键中心（默认网格与校准自由布局均对齐）
        self.waterfall.set_column_info(self.keys.column_info)
        self.keys.geometry_changed.connect(self._on_key_geometry_changed)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(10, self.MARGIN_TOP, 10, self.MARGIN_BOTTOM)
        lay.setSpacing(self.SPACING)
        lay.addWidget(self.topbar)
        lay.addWidget(self.waterfall)
        lay.addWidget(self.keys)
        lay.addWidget(self.lyrics)
        lay.addWidget(self.progress)
        lay.addWidget(self.hotkeybar)

        self.topbar.drag_moved.connect(self._move_to)
        self.hotkeybar.setVisible(bool(settings.show_hotkeys))
        self._update_minimum_size()
        self._resize_from_settings()
        self._apply_lyrics_visibility()
        self.hotkeybar.refresh_height()

        # 左侧曲目抽屉：浮窗的子部件，靠父窗口裁剪实现滑出 / 缩进
        self.sidebar = ScoreSidebar(settings, self)
        self.sidebar.raise_()
        self._sync_sidebar_span()

        self._ensure_on_screen()

        # resize 尺寸防抖保存
        self._save_timer = QTimer(self)
        self._save_timer.setSingleShot(True)
        self._save_timer.setInterval(600)
        self._save_timer.timeout.connect(self._settings.save)

    # ---- 外部接口 ----
    def set_score(self, score: Score) -> None:
        self.topbar.name_label.setText(f"♪ {score.name}")
        self.topbar.bpm_label.setText(f"BPM {score.bpm:g}")
        self.waterfall.set_score(score)
        self.keys.set_score(score)
        self.lyrics.set_score(score)
        # 换曲后歌词区可能需要显示/隐藏（影响固定高度），重新布局
        self._apply_lyrics_visibility()
        # 换曲后旧的 A-B 标记失效
        self.progress.set_loop_range(None, None)
        self.waterfall.set_loop_range(None, None)

    def set_speed(self, speed: float) -> None:
        self.topbar.speed_label.setText(f"{speed:g}x")

    def set_loop_range(self, a_ms, b_ms) -> None:
        """注入 A-B 循环区间的绝对时间（ms）；None = 清除标记。"""
        total = self._total_ms
        if a_ms is None or b_ms is None or total <= 0:
            self.progress.set_loop_range(None, None)
        else:
            self.progress.set_loop_range(a_ms / total, b_ms / total)
        self.waterfall.set_loop_range(a_ms, b_ms)

    def set_position_provider(self, provider: Callable[[], float]) -> None:
        self.waterfall.set_position_provider(provider)

    def set_transpose(self, current: int, required: int = 0, auto: bool = False) -> None:
        """更新顶部调性指示（半音阶口风琴推键）。"""
        self.topbar.set_transpose(current, required, auto)

    def set_judge_offset(self, avg_ms: Optional[float] = None, count: int = 0) -> None:
        """更新顶部「最近命中平均偏移」提示（None = 清空）。"""
        self.topbar.set_offset(avg_ms, count)

    def update_time(self, pos_ms: float, total_ms: float) -> None:
        self._total_ms = total_ms
        self.progress.set_ratio(pos_ms / total_ms if total_ms > 0 else 0.0)
        self.progress.setEnabled(total_ms > 0)
        self.lyrics.tick(pos_ms)

        def fmt(ms: float) -> str:
            ms = max(0, int(ms))
            return f"{ms // 60000:02d}:{(ms % 60000) // 1000:02d}"

        self.topbar.time_label.setText(f"{fmt(pos_ms)} / {fmt(total_ms)}")

    def apply_settings(self) -> None:
        self.waterfall.apply_settings()
        self.hotkeybar.setVisible(bool(self._settings.show_hotkeys))
        self.hotkeybar.refresh_height()
        self._apply_lyrics_visibility()
        self._resize_from_settings()

    def set_hotkeys_visible(self, enable: bool) -> None:
        """显示 / 隐藏底部热键提示条。"""
        self._settings.show_hotkeys = enable
        self.apply_settings()

    # ---- 校准 ----
    def apply_calibration(self, geoms) -> None:
        """注入校准布局（None = 默认网格）。"""
        self.keys.set_geometries(geoms)

    def _on_key_geometry_changed(self) -> None:
        self.waterfall.update()
        self.keys.update()

    # ---- 尺寸管理 ----
    def _content_width(self) -> float:
        """内容区可用宽度（去掉左右各 10px margin）。"""
        w = self.width()
        if w <= 1:
            w = max(self.MIN_WIDTH, self._settings.window_w)
        return max(1.0, float(w - 20))

    def _hotkey_bar_height(self) -> int:
        """底部热键提示条所需高度（关闭时为 0）。"""
        if not self._settings.show_hotkeys:
            return 0
        return self.hotkeybar.height_for_width(self._content_width())

    def _lyrics_visible(self) -> bool:
        """歌词区是否真的显示（需开启 + 当前曲目带歌词）。"""
        return bool(self._settings.show_lyrics and self.lyrics
                    and getattr(self.lyrics, "_score", None)
                    and self.lyrics._score.lyrics)

    def _fixed_height(self) -> int:
        """除瀑布流外所有固定部分的总高度。"""
        fixed = self.TOPBAR_H + self.KEYS_H + self.PROGRESS_H
        fixed += self.MARGIN_TOP + self.MARGIN_BOTTOM
        n_widgets = 3                      # 顶栏 / 琴键 / 进度条
        if self._lyrics_visible():
            fixed += self.LYRICS_H         # 歌词区：与真实可见性保持一致，无歌词不占位
            n_widgets += 1
        bar_h = self._hotkey_bar_height()
        if bar_h > 0:
            fixed += bar_h
            n_widgets += 1
        fixed += (n_widgets - 1) * self.SPACING
        return fixed

    def _waterfall_from_height(self, h: int) -> int:
        return max(self.MIN_WATERFALL, int(h - self._fixed_height()))

    def _height_from_waterfall(self, wf: int) -> int:
        return int(self._fixed_height() + wf)

    def _update_minimum_size(self) -> None:
        self.setMinimumSize(self.MIN_WIDTH, self._fixed_height() + self.MIN_WATERFALL)

    def _resize_from_settings(self) -> None:
        w = max(self.MIN_WIDTH, self._settings.window_w)
        h = max(self._fixed_height() + self.MIN_WATERFALL, self._settings.window_h)
        self.resize(w, h)
        self._settings.window_w = w
        self._settings.window_h = h
        self._apply_waterfall_height()

    def _apply_waterfall_height(self) -> None:
        """根据当前窗口高度计算瀑布流弹性高度并同步设置。"""
        wf = self._waterfall_from_height(self.height())
        self.waterfall.setFixedHeight(wf)
        self._settings.waterfall_height = wf

    def set_waterfall_height(self, px: int) -> None:
        """设置面板滑杆调整瀑布流高度：换算成窗口总高并 resize。"""
        self._settings.waterfall_height = px
        self.resize(self.width(), self._height_from_waterfall(px))
        self._settings.window_h = self.height()
        self._settings.save()

    def _apply_lyrics_visibility(self) -> None:
        self.lyrics.setVisible(self._lyrics_visible())
        # 歌词开关影响固定高度，需要更新最小尺寸并重新应用尺寸
        self._update_minimum_size()
        self._resize_from_settings()

    # ---- 曲目抽屉 ----
    def _sync_sidebar_span(self) -> None:
        """抽屉纵向范围：顶栏下沿 ~ 底部热键提示条上沿。

        两头都避开：上面不挡拖动条，下面不挡常驻的热键键帽说明。
        """
        if not hasattr(self, "sidebar"):
            return
        top = self.MARGIN_TOP + self.TOPBAR_H + self.SPACING
        bottom = self.height() - self.MARGIN_BOTTOM
        bar_h = self._hotkey_bar_height()
        if bar_h > 0:
            bottom -= bar_h + self.SPACING
        self.sidebar.set_span(top, bottom - top)

    def set_sidebar_enabled(self, enable: bool) -> None:
        """鼠标穿透 / 校准等场景下临时收起并隐藏抽屉。"""
        if not hasattr(self, "sidebar"):
            return
        if enable:
            self.sidebar.show()
            self._sync_sidebar_span()
        else:
            self.sidebar.collapse()
            self.sidebar.hide()

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        old_w = self._settings.window_w
        # 宽度变化可能让底部热键提示条换行，先按新宽度重算其高度
        self.hotkeybar.refresh_height()
        self._apply_waterfall_height()
        self._sync_sidebar_span()
        self._settings.window_w = self.width()
        self._settings.window_h = self.height()
        # 宽度变化时按比例缩放已校准的琴键几何，保持相对对齐
        if old_w > 0 and abs(old_w - self.width()) > 1:
            self.keys.rescale_geometries(old_w, self.width())
        self.resized.emit(self.width(), self.height())
        if hasattr(self, "_save_timer"):
            self._save_timer.start()

    def _ensure_on_screen(self) -> None:
        """确保浮窗完整落在当前屏幕可用区域内；过大时压缩窗口尺寸。"""
        screen = QGuiApplication.screenAt(self.frameGeometry().center())
        if screen is None:
            screen = QGuiApplication.primaryScreen()
        if screen is None:
            return
        avail = screen.availableGeometry()
        # 窗口比可用区域更高/更宽时，压缩窗口尺寸
        if self.height() > avail.height() or self.width() > avail.width():
            new_w = min(self.width(), avail.width())
            new_h = min(self.height(), avail.height())
            self.resize(new_w, new_h)
            self._settings.window_w, self._settings.window_h = new_w, new_h

        rect = self.frameGeometry()
        x = max(avail.left(), min(rect.x(), avail.right() - rect.width()))
        y = max(avail.top(), min(rect.y(), avail.bottom() - rect.height()))
        # 保证左上角至少还在屏幕内，方便用户拖回来
        if x > avail.right() - 80:
            x = avail.right() - 80
        if y > avail.bottom() - 60:
            y = avail.bottom() - 60
        self.move(x, y)
        self._settings.window_x, self._settings.window_y = x, y

    def nativeEvent(self, event_type, message):  # noqa: N802
        """无边框窗口四边/四角拖拽 resize（Windows WM_NCHITTEST）。"""
        if sys.platform != "win32":
            return False, 0
        et = event_type.decode("utf-8", "ignore") if isinstance(event_type, bytes) \
            else str(event_type)
        if et != "windows_generic_MSG":
            return False, 0
        try:
            msg = wt.MSG.from_address(int(message))
        except Exception:
            return False, 0
        if msg.message != WM_NCHITTEST or self._click_through:
            return False, 0
        x = ctypes.c_short(msg.lParam & 0xFFFF).value
        y = ctypes.c_short((msg.lParam >> 16) & 0xFFFF).value
        rect = wt.RECT()
        try:
            ctypes.windll.user32.GetWindowRect(int(self.winId()), ctypes.byref(rect))
        except Exception:
            return False, 0
        m = self.RESIZE_MARGIN
        left = x < rect.left + m
        right = x >= rect.right - m
        top = y < rect.top + m
        bottom = y >= rect.bottom - m
        hit = HTCLIENT
        if top and left:
            hit = HTTOPLEFT
        elif top and right:
            hit = HTTOPRIGHT
        elif bottom and left:
            hit = HTBOTTOMLEFT
        elif bottom and right:
            hit = HTBOTTOMRIGHT
        elif top:
            hit = HTTOP
        elif bottom:
            hit = HTBOTTOM
        elif left:
            hit = HTLEFT
        elif right:
            hit = HTRIGHT
        if hit != HTCLIENT:
            # 左侧抽屉的把手就贴在窗口最左缘，如果让给 resize 判定，
            # 鼠标会被当成"在边框上"而收不到 enterEvent，抽屉永远展不开。
            # 所以抽屉覆盖到的区域优先让给抽屉。
            if hasattr(self, "sidebar") and self.sidebar.isVisible():
                if self.sidebar.geometry().contains(self.mapFromGlobal(QPoint(x, y))):
                    return False, 0
            return True, hit
        return False, 0

    # ---- 窗口控制 ----
    def _move_to(self, top_left: QPoint) -> None:
        self.move(top_left)
        self._settings.window_x, self._settings.window_y = top_left.x(), top_left.y()
        self._ensure_on_screen()

    def set_click_through(self, enable: bool) -> None:
        """鼠标穿透：WS_EX_TRANSPARENT，鼠标事件全部穿透到游戏。"""
        self._click_through = enable
        self._settings.click_through = enable
        # 穿透态下窗口收不到任何鼠标事件，抽屉无法悬停展开，先收起来免得误以为卡住
        self.set_sidebar_enabled(not enable)
        try:
            hwnd = int(self.winId())
            user32 = ctypes.windll.user32
            style = user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
            if enable:
                style |= WS_EX_TRANSPARENT | WS_EX_LAYERED | WS_EX_NOACTIVATE
            else:
                style &= ~WS_EX_TRANSPARENT
                style |= WS_EX_LAYERED | WS_EX_TOOLWINDOW
            user32.SetWindowLongW(hwnd, GWL_EXSTYLE, style)
        except Exception as e:
            print(f"[Overlay] 点击穿透切换失败: {e}")

    @property
    def click_through(self) -> bool:
        return self._click_through

    # ---- 事件 ----
    def paintEvent(self, event) -> None:  # noqa: N802
        """半透明面板底：颜色带 alpha，保证子元素仍然清晰。"""
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        alpha = int(255 * self._settings.opacity)
        grad = QLinearGradient(0, 0, 0, self.height())
        grad.setColorAt(0, QColor(13, 20, 30, alpha))
        grad.setColorAt(1, QColor(10, 14, 20, alpha))
        p.setBrush(QBrush(grad))
        p.setPen(QPen(QColor(0, 229, 255, 50), 1.0))
        p.drawRoundedRect(self.rect().adjusted(0, 0, -1, -1), 16, 16)

        # 右下角 resize 手柄提示（点击穿透时隐藏）
        if not self._click_through:
            pen = QPen(QColor(255, 255, 255, 90))
            pen.setWidthF(1.4)
            p.setPen(pen)
            r = self.rect()
            for i in range(3):
                x = r.right() - 6 - i * 5
                y = r.bottom() - 3
                p.drawLine(QPointF(x, y), QPointF(r.right() - 3, y - (x - (r.right() - 6))))

    def enterEvent(self, e) -> None:  # noqa: N802
        self.topbar.setCursor(Qt.CursorShape.SizeAllCursor)

    def leaveEvent(self, e) -> None:  # noqa: N802
        self.topbar.setCursor(Qt.CursorShape.ArrowCursor)

    def mousePressEvent(self, e) -> None:  # noqa: N802
        # 点击右上角齿轮区域打开设置
        if e.button() == Qt.MouseButton.LeftButton:
            gx = self.width() - 18
            gy = 44 / 2 + 6
            if abs(e.position().x() - gx) < 14 and abs(e.position().y() - gy) < 14:
                self.topbar.settings_clicked.emit()
