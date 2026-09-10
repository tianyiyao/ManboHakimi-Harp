# -*- coding: utf-8 -*-
"""设置面板：浮窗右侧滑出，深色面板 + 滑块 / 开关。

v0.6 起内容变多，改为可滚动布局，并新增：
- A-B 段落循环控制（状态显示 / 快捷设点 / 精确拍数输入）
- 高级项：预备拍数、长按预亮提前量、预警开关、拍线、流光、下落速度
- 热键冲突告警条

v0.14：曲目列表迁出到浮窗左侧的 ScoreSidebar（悬停展开的抽屉），
本面板只保留一行指路说明，面板本身更聚焦于参数调节。
"""
from __future__ import annotations

from typing import List, Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (QCheckBox, QDoubleSpinBox, QFrame, QHBoxLayout,
                               QLabel, QPushButton, QScrollArea, QSlider,
                               QVBoxLayout, QWidget)

from .config import Settings
from .theme import THEME


def _slider() -> QSlider:
    s = QSlider(Qt.Orientation.Horizontal)
    s.setStyleSheet(f"""
        QSlider::groove:horizontal {{
            height: 4px; border-radius: 2px; background: {THEME.surface_alt}; }}
        QSlider::sub-page:horizontal {{
            border-radius: 2px; background: qlineargradient(x1:0,y1:0,x2:1,y2:0,
                stop:0 {THEME.primary}, stop:1 {THEME.success}); }}
        QSlider::handle:horizontal {{
            width: 14px; height: 14px; margin: -5px 0; border-radius: 7px;
            background: white; }}""")
    return s


def _checkbox(text: str) -> QCheckBox:
    cb = QCheckBox(text)
    cb.setStyleSheet(f"""
        QCheckBox {{ color: {THEME.text_primary}; font-size: 13px; spacing: 8px; background: transparent; }}
        QCheckBox::indicator {{
            width: 18px; height: 18px; border-radius: 4px;
            border: 1px solid {THEME.border}; background: {THEME.surface_alt}; }}
        QCheckBox::indicator:checked {{
            background: {THEME.primary}; border-color: {THEME.primary}; }}""")
    return cb


def _btn(text: str, primary: bool = False) -> QPushButton:
    b = QPushButton(text)
    if primary:
        b.setStyleSheet(f"""
            QPushButton {{ color: {THEME.background}; font-size: 12px; font-weight: bold;
                background: {THEME.primary}; border: none; border-radius: 7px;
                padding: 7px 10px; }}
            QPushButton:hover {{ background: #33ECFF; }}""")
    else:
        b.setStyleSheet(f"""
            QPushButton {{ color: {THEME.text_primary}; font-size: 12px;
                background: {THEME.surface_alt}; border: 1px solid {THEME.border};
                border-radius: 7px; padding: 6px 10px; }}
            QPushButton:hover {{ border-color: {THEME.primary}; color: {THEME.primary}; }}""")
    b.setCursor(Qt.CursorShape.PointingHandCursor)
    return b


class SettingsPanel(QWidget):
    """独立的置顶设置窗口，显示在浮窗右侧。"""

    closed = Signal()
    speed_changed = Signal(float)
    opacity_changed = Signal(float)
    waterfall_height_changed = Signal(int)
    loop_changed = Signal(bool)
    click_through_changed = Signal(bool)
    count_in_changed = Signal(int)
    preparation_lead_changed = Signal(float)
    countdown_warning_changed = Signal(bool)
    beat_lines_changed = Signal(bool)
    hold_shine_changed = Signal(bool)
    lookahead_changed = Signal(int)
    lyrics_changed = Signal(bool)
    hotkeys_hint_changed = Signal(bool)
    auto_transpose_changed = Signal(bool)
    hit_feedback_changed = Signal(bool)
    judge_offset_changed = Signal(int)
    loop_range_set = Signal(float, float)  # A 拍, B 拍
    loop_range_cleared = Signal()

    PANEL_W = 340
    PANEL_H = 660

    def __init__(self, settings: Settings, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self._settings = settings
        self.setWindowTitle("ManboHakimi-Harp 设置")
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setFixedSize(self.PANEL_W, self.PANEL_H)

        self.setStyleSheet(f"""
            QWidget#panel {{
                background: rgba(19,24,32,242);
                border-radius: 14px; border: 1px solid {THEME.border}; }}
            QLabel#sec {{ color: {THEME.text_secondary}; font-size: 12px;
                font-weight: bold; letter-spacing: 1px; background: transparent; }}
            QLabel#val {{ color: {THEME.primary};
                font-family: '{THEME.font_mono}'; font-size: 12px; background: transparent; }}
            QLabel#name {{ color: {THEME.text_primary}; font-size: 13px; background: transparent; }}
            QLabel#bpm  {{ color: {THEME.text_secondary}; font-size: 11px;
                font-family: '{THEME.font_mono}'; background: transparent; }}
            QLabel#hint {{ color: {THEME.text_secondary}; font-size: 11px;
                background: transparent; }}
            QLabel#loopstatus {{ color: {THEME.success}; font-size: 12px;
                font-family: '{THEME.font_mono}'; background: transparent; }}
            QLabel#warn {{ color: {THEME.background}; font-size: 11px;
                background: {THEME.secondary}; border-radius: 6px; padding: 6px 8px; }}
            QPushButton#close {{ color: {THEME.text_secondary}; background: transparent;
                border: none; font-size: 16px; }}
            QPushButton#close:hover {{ color: {THEME.text_primary}; }}
            QDoubleSpinBox {{ background: {THEME.surface_alt}; color: {THEME.text_primary};
                border: 1px solid {THEME.border}; border-radius: 6px;
                padding: 4px 6px; font-family: '{THEME.font_mono}'; font-size: 12px; }}
            QScrollArea {{ background: transparent; border: none; }}
            QScrollArea > QWidget > QWidget {{ background: transparent; }}
            QScrollBar:vertical {{ width: 8px; background: transparent; margin: 4px 0; }}
            QScrollBar::handle:vertical {{ background: {THEME.border};
                border-radius: 4px; min-height: 30px; }}
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
            QMenu {{ background: {THEME.surface}; color: {THEME.text_primary};
                border: 1px solid {THEME.border}; border-radius: 8px; padding: 4px; }}
            QMenu::item {{ padding: 6px 18px; border-radius: 5px; }}
            QMenu::item:selected {{ background: rgba(0,229,255,38); }}""")

        root = QWidget(self, objectName="panel")
        root.setGeometry(self.rect())
        outer = QVBoxLayout(root)
        outer.setContentsMargins(18, 14, 10, 14)
        outer.setSpacing(6)

        # 标题行（不滚动）
        head = QHBoxLayout()
        title = QLabel("设置")
        title.setStyleSheet(f"color:{THEME.text_primary}; font-size:16px; "
                            f"font-weight:bold; background:transparent;")
        head.addWidget(title)
        head.addStretch(1)
        btn_close = QPushButton("✕", objectName="close")
        btn_close.setFixedSize(28, 28)
        btn_close.clicked.connect(self.hide)
        head.addWidget(btn_close)
        outer.addLayout(head)

        # 热键冲突告警（默认隐藏）
        self.warn_label = QLabel("", objectName="warn")
        self.warn_label.setWordWrap(True)
        self.warn_label.hide()
        outer.addWidget(self.warn_label)

        # 滚动内容
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        content = QWidget()
        lay = QVBoxLayout(content)
        lay.setContentsMargins(0, 0, 8, 0)
        lay.setSpacing(8)
        scroll.setWidget(content)
        outer.addWidget(scroll, 1)

        # ---------- 曲目（已移到左侧抽屉） ----------
        lay.addWidget(QLabel("曲目", objectName="sec"))
        hint_scores = QLabel(
            "曲目列表已移到浮窗左侧边栏：把鼠标移到窗口左边缘的竖条「曲目」上\n"
            "会自动展开，移开自动缩回。在侧边栏里右键曲目可编辑 / 重命名 / 删除。",
            objectName="hint")
        hint_scores.setWordWrap(True)
        lay.addWidget(hint_scores)

        lay.addWidget(self._sep())

        # ---------- A-B 段落循环 ----------
        lay.addWidget(QLabel("循环练习（A-B）", objectName="sec"))
        self.loop_status = QLabel("A: --    B: --", objectName="loopstatus")
        lay.addWidget(self.loop_status)

        row_loop = QHBoxLayout()
        row_loop.setSpacing(6)
        b_a = _btn("设 A 点为当前")
        b_b = _btn("设 B 点并循环", primary=True)
        b_a.clicked.connect(lambda: self.set_point_requested.emit("a"))
        b_b.clicked.connect(lambda: self.set_point_requested.emit("b"))
        row_loop.addWidget(b_a)
        row_loop.addWidget(b_b)
        lay.addLayout(row_loop)

        row_nums = QHBoxLayout()
        row_nums.setSpacing(6)
        row_nums.addWidget(QLabel("A 拍", objectName="hint"))
        self.a_spin = QDoubleSpinBox()
        self.a_spin.setRange(0.0, 999.0)
        self.a_spin.setSingleStep(0.5)
        self.a_spin.setDecimals(2)
        row_nums.addWidget(self.a_spin, 1)
        row_nums.addWidget(QLabel("B 拍", objectName="hint"))
        self.b_spin = QDoubleSpinBox()
        self.b_spin.setRange(0.0, 999.0)
        self.b_spin.setSingleStep(0.5)
        self.b_spin.setDecimals(2)
        row_nums.addWidget(self.b_spin, 1)
        b_apply = _btn("应用拍数")
        b_apply.clicked.connect(
            lambda: self.loop_range_set.emit(self.a_spin.value(), self.b_spin.value()))
        row_nums.addWidget(b_apply)
        lay.addLayout(row_nums)

        row_clear = QHBoxLayout()
        b_clear = _btn("清除 A-B 区间")
        b_clear.clicked.connect(self.loop_range_cleared)
        row_clear.addWidget(b_clear)
        row_clear.addStretch(1)
        lay.addLayout(row_clear)

        hint_loop = QLabel("Ctrl+Shift+A 标记 A 点 · Ctrl+Shift+B 标记 B 点（再按清除）\n"
                           "F2 重置会回到 A 点；进度条可点击/拖动跳转",
                           objectName="hint")
        hint_loop.setWordWrap(True)
        lay.addWidget(hint_loop)

        lay.addWidget(self._sep())

        # ---------- 演奏 ----------
        lay.addWidget(QLabel("演奏", objectName="sec"))
        self.speed_slider = _slider()
        self.speed_slider.setRange(25, 200)  # 0.25x - 2.0x
        self.speed_slider.setValue(int(settings.speed_multiplier * 100))
        self.speed_label = QLabel(f"{settings.speed_multiplier:g}x", objectName="val")
        self.speed_slider.valueChanged.connect(
            lambda v: (self.speed_label.setText(f"{v / 100:g}x"),
                       self.speed_changed.emit(v / 100)))
        lay.addLayout(self._row("速度倍率", self.speed_slider, self.speed_label))

        self.count_in_slider = _slider()
        self.count_in_slider.setRange(0, 8)
        self.count_in_slider.setValue(int(settings.count_in_beats))
        self.count_in_label = QLabel(self._beat_text(settings.count_in_beats), objectName="val")
        self.count_in_slider.valueChanged.connect(
            lambda v: (self.count_in_label.setText(self._beat_text(v)),
                       self.count_in_changed.emit(v)))
        lay.addLayout(self._row("预备拍", self.count_in_slider, self.count_in_label))

        self.loop_cb = _checkbox("整曲循环播放（未设 A-B 时生效）")
        self.loop_cb.setChecked(settings.loop)
        self.loop_cb.toggled.connect(self.loop_changed)
        lay.addWidget(self.loop_cb)

        self.auto_transpose_cb = _checkbox("自动变调（跟随歌曲自动切换调性档）")
        self.auto_transpose_cb.setChecked(settings.auto_transpose)
        self.auto_transpose_cb.toggled.connect(self.auto_transpose_changed)
        lay.addWidget(self.auto_transpose_cb)

        hint_transpose = QLabel(
            "半音阶口风琴：开启后调性档自动跟随歌曲，只需专注按 Z/X/C/V/B/N/M/, 八键；\n"
            "关闭后用 小键盘1/2/3 手动切 降调/半音/升调，小键盘0 快速开关自动变调。",
            objectName="hint")
        hint_transpose.setWordWrap(True)
        lay.addWidget(hint_transpose)

        lay.addWidget(self._sep())

        # ---------- 显示 ----------
        lay.addWidget(QLabel("显示", objectName="sec"))
        self.opacity_slider = _slider()
        self.opacity_slider.setRange(30, 100)
        self.opacity_slider.setValue(int(settings.opacity * 100))
        self.opacity_label = QLabel(f"{int(settings.opacity * 100)}%", objectName="val")
        self.opacity_slider.valueChanged.connect(
            lambda v: (self.opacity_label.setText(f"{v}%"),
                       self.opacity_changed.emit(v / 100)))
        lay.addLayout(self._row("浮窗透明度", self.opacity_slider, self.opacity_label))

        self.height_slider = _slider()
        self.height_slider.setRange(100, 600)
        self.height_slider.setValue(settings.waterfall_height)
        self.height_label = QLabel(f"{settings.waterfall_height}px", objectName="val")
        self.height_slider.valueChanged.connect(
            lambda v: (self.height_label.setText(f"{v}px"),
                       self.waterfall_height_changed.emit(v)))
        lay.addLayout(self._row("瀑布流高度", self.height_slider, self.height_label))

        self.lookahead_slider = _slider()
        self.lookahead_slider.setRange(600, 6000)
        self.lookahead_slider.setSingleStep(100)
        self.lookahead_slider.setValue(int(settings.lookahead_ms))
        self.lookahead_label = QLabel(f"{settings.lookahead_ms / 1000:.1f}s", objectName="val")
        self.lookahead_slider.valueChanged.connect(
            lambda v: (self.lookahead_label.setText(f"{v / 1000:.1f}s"),
                       self.lookahead_changed.emit(v)))
        lay.addLayout(self._row("下落时间", self.lookahead_slider, self.lookahead_label))

        self.lead_slider = _slider()
        self.lead_slider.setRange(5, 40)     # 0.5 - 4.0 拍
        self.lead_slider.setValue(int(settings.preparation_lead_beats * 10))
        self.lead_label = QLabel(self._beat_text(settings.preparation_lead_beats), objectName="val")
        self.lead_slider.valueChanged.connect(
            lambda v: (self.lead_label.setText(self._beat_text(v / 10)),
                       self.preparation_lead_changed.emit(v / 10)))
        lay.addLayout(self._row("长按预亮", self.lead_slider, self.lead_label))

        self.beat_lines_cb = _checkbox("显示拍线")
        self.beat_lines_cb.setChecked(settings.show_beat_lines)
        self.beat_lines_cb.toggled.connect(self.beat_lines_changed)
        lay.addWidget(self.beat_lines_cb)

        self.lyrics_cb = _checkbox("显示歌词提示")
        self.lyrics_cb.setChecked(settings.show_lyrics)
        self.lyrics_cb.toggled.connect(self.lyrics_changed)
        lay.addWidget(self.lyrics_cb)

        self.hotkeys_hint_cb = _checkbox("底部热键提示条")
        self.hotkeys_hint_cb.setChecked(settings.show_hotkeys)
        self.hotkeys_hint_cb.toggled.connect(self.hotkeys_hint_changed)
        lay.addWidget(self.hotkeys_hint_cb)

        self.hit_feedback_cb = _checkbox("命中反馈（判定 / 连击 / 得分）")
        self.hit_feedback_cb.setChecked(settings.hit_feedback)
        self.hit_feedback_cb.toggled.connect(self.hit_feedback_changed)
        lay.addWidget(self.hit_feedback_cb)

        # 判定偏移：把整个判定基准平移，补偿玩家固定偏早/偏晚的手感
        self.offset_slider = _slider()
        self.offset_slider.setRange(-600, 600)
        self.offset_slider.setSingleStep(10)
        self.offset_slider.setPageStep(20)
        self.offset_slider.setValue(int(getattr(settings, "judge_offset_ms", 0) or 0))
        self.offset_label = QLabel(self._offset_text(settings.judge_offset_ms), objectName="val")
        self.offset_slider.valueChanged.connect(
            lambda v: (self.offset_label.setText(self._offset_text(v)),
                       self.judge_offset_changed.emit(v)))
        lay.addLayout(self._row("判定偏移", self.offset_slider, self.offset_label))

        hint_offset = QLabel(
            "顶栏会显示最近命中的「偏移」（+ = 你整体按晚了，- = 按早了）。"
            "把这个数字调到接近 0 就说明手感对齐了：\n"
            "· 拖本滑杆，或游戏中按 小键盘 4 / 6 每次 -20 / +20ms，小键盘 5 归零\n"
            "· 例：顶栏显示「偏移 +210ms」，就把本项调到 +210（几轮即可收敛）",
            objectName="hint")
        hint_offset.setWordWrap(True)
        lay.addWidget(hint_offset)

        hint_hit = QLabel(
            "按对琴键时给出 PERFECT / GREAT / GOOD / MISS 判定与连击、得分，手感类似《指上钢琴》。\n"
            "仅被动读取 8 个演奏键的状态，不拦截、不模拟按键，游戏照常收到按键。",
            objectName="hint")
        hint_hit.setWordWrap(True)
        lay.addWidget(hint_hit)

        self.shine_cb = _checkbox("长按音符流光动画")
        self.shine_cb.setChecked(settings.hold_shine)
        self.shine_cb.toggled.connect(self.hold_shine_changed)
        lay.addWidget(self.shine_cb)

        self.warn_cb = _checkbox("松开前橙色预警")
        self.warn_cb.setChecked(settings.countdown_warning)
        self.warn_cb.toggled.connect(self.countdown_warning_changed)
        lay.addWidget(self.warn_cb)

        lay.addWidget(self._sep())

        # ---------- 指针 ----------
        lay.addWidget(QLabel("指针", objectName="sec"))
        self.click_cb = _checkbox("鼠标穿透（游戏内操作不被浮窗挡住）")
        self.click_cb.setChecked(settings.click_through)
        self.click_cb.toggled.connect(self.click_through_changed)
        lay.addWidget(self.click_cb)

        lay.addWidget(self._sep())

        # ---------- 热键说明 ----------
        lay.addWidget(QLabel("热键", objectName="sec"))
        hotkeys = QLabel(
            "F1 开始/暂停    F2 重置(回 A 点)    F3 显示/隐藏\n"
            "F4 悬浮球    Ctrl+Shift+A 标记 A 点\n"
            "Ctrl+Shift+B 标记 B 点/清除    Ctrl+Shift+T 穿透\n"
            "Ctrl+Shift+C 琴键校准    Ctrl+Shift+E 编辑器\n"
            "Ctrl+Shift+Q 退出\n"
            "小键盘0 自动变调   小键盘1/2/3 降调/自然/升调\n"
            "小键盘4/6 判定偏移 -20/+20ms   小键盘5 归零")
        hotkeys.setObjectName("hint")
        hotkeys.setWordWrap(True)
        lay.addWidget(hotkeys)

        lay.addStretch(1)

    # ---- 小工具 ----
    @staticmethod
    def _beat_text(beats) -> str:
        b = float(beats)
        return "关闭" if b <= 0 else f"{b:g} 拍"

    @staticmethod
    def _offset_text(ms) -> str:
        v = int(ms or 0)
        return "0 ms" if v == 0 else f"{v:+d} ms"

    def sync_offset_slider(self, v: int) -> None:
        """外部（热键）改了判定偏移后，把滑杆同步过来（不重复发信号）。"""
        v = int(v)
        if self.offset_slider.value() == v:
            return
        self.offset_slider.blockSignals(True)
        self.offset_slider.setValue(v)
        self.offset_slider.blockSignals(False)
        self.offset_label.setText(self._offset_text(v))

    def _sep(self) -> QFrame:
        sep = QFrame()
        sep.setFixedHeight(1)
        sep.setStyleSheet(f"background:{THEME.border}; border:none;")
        return sep

    @staticmethod
    def _row(label: str, slider: QSlider, value: QLabel) -> QHBoxLayout:
        h = QHBoxLayout()
        h.setSpacing(8)
        name = QLabel(label)
        name.setStyleSheet(f"color:{THEME.text_primary}; font-size:12px; "
                           f"background:transparent;")
        name.setFixedWidth(70)
        h.addWidget(name)
        h.addWidget(slider, 1)
        h.addWidget(value)
        return h

    # ---- A-B ----
    def _on_set_current(self, which: str) -> None:
        """由面板按钮触发：用当前播放位置设点。

        实际取值在 app 侧完成（面板拿不到引擎），这里只是把语义传出去：
        A 点 -> loop_range_set(当前拍, 现有 B)；B 点 -> loop_range_set(现有 A, 当前拍)。
        为简化，按钮统一发一个"请求设点"信号。
        """
        if which == "a":
            self.set_current_point_requested.emit("a")
        else:
            self.set_current_point_requested.emit("b")

    set_current_point_requested = Signal(str)

    def set_loop_status(self, a_beat, b_beat) -> None:
        """更新 A-B 状态显示与拍数输入框。"""
        if a_beat is None and b_beat is None:
            self.loop_status.setText("A: --    B: --")
            self.loop_status.setStyleSheet(f"color:{THEME.text_secondary};")
        else:
            a_txt = "--" if a_beat is None else f"{a_beat:g}"
            b_txt = "--" if b_beat is None else f"{b_beat:g}"
            span = ("" if (a_beat is None or b_beat is None)
                    else f"    长度 {max(0.0, b_beat - a_beat):g} 拍")
            self.loop_status.setText(f"A: {a_txt} 拍    B: {b_txt} 拍{span}")
            self.loop_status.setStyleSheet(f"color:{THEME.success};")
        for spin, val in ((self.a_spin, a_beat), (self.b_spin, b_beat)):
            spin.blockSignals(True)
            if val is not None:
                spin.setValue(float(val))
            spin.blockSignals(False)

    # ---- 热键告警 ----
    def set_hotkey_warning(self, labels: List[str]) -> None:
        if not labels:
            self.warn_label.hide()
            return
        self.warn_label.setText(
            "⚠ 以下全局热键被其他程序占用，本程序内无效：\n" + "、".join(labels))
        self.warn_label.show()

    def sync_height_slider(self, value: int) -> None:
        """浮窗 resize 后同步瀑布流高度滑杆（不触发信号，避免循环）。"""
        self.height_slider.blockSignals(True)
        self.height_slider.setValue(value)
        self.height_label.setText(f"{value}px")
        self.height_slider.blockSignals(False)

    def move_beside(self, overlay_pos) -> None:
        self.move(overlay_pos.x() + 600 + 12, overlay_pos.y())
