# -*- coding: utf-8 -*-
"""首次启动风险声明弹窗：必须勾选确认后才能使用。"""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (QCheckBox, QDialog, QHBoxLayout, QLabel,
                               QPushButton, QVBoxLayout)

from .theme import THEME


class RiskDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("ManboHakimi-Harp · 风险提示")
        self.setFixedSize(480, 380)
        self.setWindowFlags(
            (self.windowFlags() & ~Qt.WindowType.WindowContextHelpButtonHint)
            | Qt.WindowType.WindowStaysOnTopHint)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, False)

        self.setStyleSheet(f"""
            QDialog {{ background: {THEME.surface}; border-radius: 16px; }}
            QLabel#title {{ color: {THEME.secondary}; font-size: 20px;
                font-weight: bold; background: transparent; }}
            QLabel#body {{ color: {THEME.text_primary}; font-size: 13px;
                line-height: 1.7; background: transparent; }}
            QLabel#warn {{ color: {THEME.secondary}; font-size: 13px;
                line-height: 1.7; background: transparent; }}
            QCheckBox {{ color: {THEME.text_primary}; font-size: 13px; spacing: 10px; }}
            QCheckBox::indicator {{ width: 20px; height: 20px; border-radius: 4px;
                border: 1px solid {THEME.border}; background: {THEME.surface_alt}; }}
            QCheckBox::indicator:checked {{ background: {THEME.primary};
                border-color: {THEME.primary}; }}
            QPushButton#primary {{ background: {THEME.primary}; color: {THEME.background};
                border: none; border-radius: 8px; font-size: 14px; font-weight: bold; }}
            QPushButton#primary:disabled {{ background: {THEME.surface_alt};
                color: {THEME.text_secondary}; }}
            QPushButton#ghost {{ background: transparent; color: {THEME.text_secondary};
                border: 1px solid {THEME.border}; border-radius: 8px; font-size: 14px; }}""")

        lay = QVBoxLayout(self)
        lay.setContentsMargins(28, 24, 28, 24)
        lay.setSpacing(14)

        title = QLabel("⚠ 风险提示")
        title.setObjectName("title")
        lay.addWidget(title)

        body = QLabel(
            "本工具为纯视觉练习辅助，旨在帮助玩家学习口风琴曲谱：\n"
            "· 不模拟任何键鼠输入\n"
            "· 不读取游戏画面或内存\n"
            "· 不注入游戏进程\n"
            "· 不联网，数据完全本地存储")
        body.setObjectName("body")
        lay.addWidget(body)

        warn = QLabel(
            "但请注意：游戏官方使用内核级反作弊系统（ACE），对第三方 Overlay "
            "的合规边界未明确表态，存在被检测的可能性。\n"
            "建议首次使用先在训练场测试；使用风险由用户自行承担。"
            "如官方明确禁止此类工具，请立即停止使用。")
        warn.setObjectName("warn")
        warn.setWordWrap(True)
        lay.addWidget(warn)

        lay.addStretch(1)

        self.confirm_cb = QCheckBox("我已阅读并了解上述风险")
        lay.addWidget(self.confirm_cb)

        btns = QHBoxLayout()
        btns.setSpacing(12)
        self.btn_accept = QPushButton("同意并继续")
        self.btn_accept.setObjectName("primary")
        self.btn_accept.setFixedHeight(40)
        self.btn_accept.setEnabled(False)
        self.btn_accept.clicked.connect(self.accept)
        self.btn_quit = QPushButton("退出")
        self.btn_quit.setObjectName("ghost")
        self.btn_quit.setFixedHeight(40)
        self.btn_quit.clicked.connect(self.reject)
        btns.addWidget(self.btn_accept, 1)
        btns.addWidget(self.btn_quit)
        lay.addLayout(btns)

        self.confirm_cb.toggled.connect(self.btn_accept.setEnabled)
