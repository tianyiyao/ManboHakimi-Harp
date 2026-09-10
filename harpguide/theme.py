# -*- coding: utf-8 -*-
"""主题：色彩系统与字体（与设计稿 00002 模板一致的暗色科技风）。"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Theme:
    # 背景与面板
    background: str = "#0A0E14"
    surface: str = "#131820"
    surface_alt: str = "#1E2633"
    border: str = "#2A3444"

    # 强调色
    primary: str = "#00E5FF"       # 青蓝：当前音符 / 激活态
    secondary: str = "#FF6B35"     # 橙：下一个 / 松开预警
    success: str = "#00FF88"       # 绿：命中 / 完成
    danger: str = "#FF3B5C"        # 红：错误 / 停止
    gold: str = "#FFD54A"          # 金：PERFECT 判定 / 高分反馈

    # 文字
    text_primary: str = "#E8EDF5"
    text_secondary: str = "#7A8599"

    # 键位
    key_idle: str = "#1E2633"
    key_idle_border: str = "#2A3444"

    # 音高映射（按 8 键列索引）
    #   1 2 3 (Z X C) 低音区 -> 蓝
    #   4 5 6 (V B N) 中音区 -> 青
    #   7 1' (M ,)   高音区 -> 绿
    pitch_colors: tuple = ("#0088FF", "#0088FF", "#0088FF",
                           "#00E5FF", "#00E5FF", "#00E5FF",
                           "#00FF88", "#00FF88")

    font_mono: str = "Consolas"          # 数值 / 键位字母（Windows 自带等宽）
    font_sans: str = "Microsoft YaHei"   # 中文正文

    def pitch_color(self, key_index: int) -> str:
        if 0 <= key_index < len(self.pitch_colors):
            return self.pitch_colors[key_index]
        return self.primary


THEME = Theme()


def lerp_color(a: str, b: str, t: float) -> str:
    """两个 hex 颜色之间线性插值。"""
    t = max(0.0, min(1.0, t))
    ar, ag, ab = int(a[1:3], 16), int(a[3:5], 16), int(a[5:7], 16)
    br, bg, bb = int(b[1:3], 16), int(b[3:5], 16), int(b[5:7], 16)
    r = round(ar + (br - ar) * t)
    g = round(ag + (bg - ag) * t)
    bl = round(ab + (bb - ab) * t)
    return f"#{r:02X}{g:02X}{bl:02X}"
