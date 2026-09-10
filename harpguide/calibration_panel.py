# -*- coding: utf-8 -*-
"""校准面板：配合校准模式的操作工具条（独立置顶小窗）。

信号：
    scale_requested(float)   整体缩放系数
    reset_requested()        恢复默认网格布局
    save_requested()         保存并退出校准
    cancel_requested()       放弃修改并退出
"""
from __future__ import annotations

from typing import Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (QFrame, QHBoxLayout, QLabel, QPushButton,
                               QVBoxLayout, QWidget)

from .theme import THEME


def _btn(text: str, primary: bool = False) -> QPushButton:
    b = QPushButton(text)
    if primary:
        b.setStyleSheet(f"""
            QPushButton {{ color: {THEME.background}; font-size: 13px; font-weight: bold;
                background: {THEME.primary}; border: none; border-radius: 8px;
                padding: 9px 14px; }}
            QPushButton:hover {{ background: #33ECFF; }}""")
    else:
        b.setStyleSheet(f"""
            QPushButton {{ color: {THEME.text_primary}; font-size: 12px;
                background: {THEME.surface_alt}; border: 1px solid {THEME.border};
                border-radius: 8px; padding: 8px 12px; }}
            QPushButton:hover {{ border-color: {THEME.primary};
                color: {THEME.primary}; }}""")
    b.setCursor(Qt.CursorShape.PointingHandCursor)
    return b


class CalibrationPanel(QWidget):
    scale_requested = Signal(float)
    reset_requested = Signal()
    save_requested = Signal()
    cancel_requested = Signal()

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setWindowTitle("ManboHakimi-Harp 校准")
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setFixedSize(360, 370)

        self.setStyleSheet(f"""
            QWidget#calpanel {{
                background: rgba(19,24,32,246);
                border-radius: 14px; border: 1px solid {THEME.border}; }}
            QLabel#title {{ color: {THEME.text_primary}; font-size: 15px;
                font-weight: bold; background: transparent; }}
            QLabel#step {{ color: {THEME.text_secondary}; font-size: 12px;
                background: transparent; line-height: 1.6; }}
            QLabel#warn {{ color: {THEME.secondary}; font-size: 11px;
                background: transparent; }}""")

        root = QWidget(self, objectName="calpanel")
        root.setGeometry(self.rect())
        lay = QVBoxLayout(root)
        lay.setContentsMargins(18, 14, 18, 14)
        lay.setSpacing(10)

        # 标题
        head = QHBoxLayout()
        title = QLabel("琴键校准", objectName="title")
        head.addWidget(title)
        head.addStretch(1)
        btn_close = QPushButton("✕")
        btn_close.setFixedSize(26, 26)
        btn_close.setStyleSheet(f"color:{THEME.text_secondary}; background:transparent;"
                                f"border:none; font-size:14px;")
        btn_close.clicked.connect(self.cancel_requested)
        head.addWidget(btn_close)
        lay.addLayout(head)

        sep = QFrame()
        sep.setFixedHeight(1)
        sep.setStyleSheet(f"background:{THEME.border}; border:none;")
        lay.addWidget(sep)

        # 步骤说明
        steps = QLabel(
            "① 拖动浮窗顶部信息条，将琴键区移到游戏键位附近\n"
            "② 拖动单个琴键，使其与游戏内按键完全重合\n"
            "③ 滚轮缩放单个键；方向键微调（Shift = 10px）\n"
            "④ 瀑布流虚线会实时对齐琴键中心，确认后保存")
        steps.setWordWrap(True)
        lay.addWidget(steps)

        # 整体操作
        row_scale = QHBoxLayout()
        row_scale.setSpacing(8)
        b_big = _btn("整体放大")
        b_small = _btn("整体缩小")
        b_reset = _btn("恢复默认网格")
        b_big.clicked.connect(lambda: self.scale_requested.emit(1.15))
        b_small.clicked.connect(lambda: self.scale_requested.emit(1 / 1.15))
        b_reset.clicked.connect(self.reset_requested)
        row_scale.addWidget(b_big)
        row_scale.addWidget(b_small)
        row_scale.addWidget(b_reset)
        lay.addLayout(row_scale)

        lay.addStretch(1)

        # 当前档案（物理分辨率 @ 缩放比）
        self.profile_label = QLabel("当前档案：--")
        self.profile_label.setWordWrap(True)
        self.profile_label.setStyleSheet(
            f"color:{THEME.primary}; font-size:11px; background:transparent;")
        lay.addWidget(self.profile_label)

        # 底部提示
        warn = QLabel("校准按「屏幕物理分辨率 @ 缩放比」分档保存（config/calibration.json）\n"
                      "校准期间播放会暂停、鼠标穿透自动关闭")
        warn.setWordWrap(True)
        warn.setObjectName("warn")
        lay.addWidget(warn)

        # 确认操作
        row_ok = QHBoxLayout()
        row_ok.setSpacing(8)
        b_save = _btn("保存并退出", primary=True)
        b_cancel = _btn("放弃修改")
        b_save.clicked.connect(self.save_requested)
        b_cancel.clicked.connect(self.cancel_requested)
        row_ok.addWidget(b_save)
        row_ok.addWidget(b_cancel)
        lay.addLayout(row_ok)

    def set_profile_key(self, key: str) -> None:
        """显示当前正在编辑/生效的校准档案键。"""
        self.profile_label.setText(f"当前档案：{key}")

    def move_beside(self, overlay_pos) -> None:
        self.move(overlay_pos.x() + 600 + 12, overlay_pos.y())
