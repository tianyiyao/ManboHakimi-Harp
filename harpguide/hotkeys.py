# -*- coding: utf-8 -*-
"""全局热键：RegisterHotKey + Windows 原生消息过滤。

热键表：
    F1              开始 / 暂停提示
    F2              重置到 A 点（无 A-B 时回曲首）
    F3              显示 / 隐藏浮窗
    F4              切换悬浮球 / 完整模式
    Ctrl+Shift+A    设置 A-B 循环的 A 点（当前位置）
    Ctrl+Shift+B    设置 B 点并开启循环；已开启时再按 = 清除并回到整曲
    Ctrl+Shift+T    切换鼠标穿透
    Ctrl+Shift+C    琴键校准模式（保存并退出）
    Ctrl+Shift+E    乐谱编辑器
    Ctrl+Shift+Q    退出程序
    小键盘1/2/3     降调 / 半音(自然) / 升调（半音阶口风琴推键）
    小键盘0         自动变调（跟随歌曲自动切换调性档）
    小键盘4/6       判定偏移 -20ms / +20ms（补偿按早/按晚，命中反馈用）
    小键盘5         判定偏移归零

注意：仅在 Windows 下生效；其他平台静默降级（无热键）。
"""
from __future__ import annotations

import ctypes
import ctypes.wintypes as wt
import sys
from typing import Dict, List

from PySide6.QtCore import QAbstractNativeEventFilter, QObject, Signal

WM_HOTKEY = 0x0312
MOD_ALT, MOD_CONTROL, MOD_SHIFT = 0x0001, 0x0002, 0x0004
MOD_NOREPEAT = 0x4000

VK_F1, VK_F2, VK_F3, VK_F4 = 0x70, 0x71, 0x72, 0x73
VK_T, VK_Q, VK_C, VK_E = 0x54, 0x51, 0x43, 0x45
VK_A, VK_B = 0x41, 0x42
VK_NUMPAD0, VK_NUMPAD1, VK_NUMPAD2, VK_NUMPAD3 = 0x60, 0x61, 0x62, 0x63
VK_NUMPAD4, VK_NUMPAD5, VK_NUMPAD6 = 0x64, 0x65, 0x66

# 热键名 -> (modifiers, vk)
HOTKEY_DEFS = {
    "toggle_playback": (0, VK_F1),
    "reset":           (0, VK_F2),
    "toggle_visible":  (0, VK_F3),
    "toggle_ball":     (0, VK_F4),
    "mark_loop_a":     (MOD_CONTROL | MOD_SHIFT, VK_A),
    "mark_loop_b":     (MOD_CONTROL | MOD_SHIFT, VK_B),
    "toggle_clickthrough": (MOD_CONTROL | MOD_SHIFT, VK_T),
    "toggle_calibration": (MOD_CONTROL | MOD_SHIFT, VK_C),
    "toggle_editor":   (MOD_CONTROL | MOD_SHIFT, VK_E),
    "quit":            (MOD_CONTROL | MOD_SHIFT, VK_Q),
    "transpose_down":    (0, VK_NUMPAD1),
    "transpose_natural": (0, VK_NUMPAD2),
    "transpose_up":      (0, VK_NUMPAD3),
    "toggle_auto_transpose": (0, VK_NUMPAD0),
    "judge_offset_down": (0, VK_NUMPAD4),
    "judge_offset_zero": (0, VK_NUMPAD5),
    "judge_offset_up":   (0, VK_NUMPAD6),
}

# 人类可读的热键名（用于冲突提示）
HOTKEY_LABELS = {
    "toggle_playback": "F1 开始/暂停",
    "reset":           "F2 重置",
    "toggle_visible":  "F3 显示/隐藏",
    "toggle_ball":     "F4 悬浮球",
    "mark_loop_a":     "Ctrl+Shift+A 标记 A 点",
    "mark_loop_b":     "Ctrl+Shift+B 标记 B 点",
    "toggle_clickthrough": "Ctrl+Shift+T 鼠标穿透",
    "toggle_calibration": "Ctrl+Shift+C 琴键校准",
    "toggle_editor":   "Ctrl+Shift+E 乐谱编辑器",
    "quit":            "Ctrl+Shift+Q 退出",
    "transpose_down":    "小键盘1 降调",
    "transpose_natural": "小键盘2 半音(自然)",
    "transpose_up":      "小键盘3 升调",
    "toggle_auto_transpose": "小键盘0 自动变调",
    "judge_offset_down": "小键盘4 判定偏移-20ms",
    "judge_offset_zero": "小键盘5 判定偏移归零",
    "judge_offset_up":   "小键盘6 判定偏移+20ms",
}


class HotkeyHub(QObject):
    """信号中转器（QAbstractNativeEventFilter 不是 QObject，需组合）。"""
    triggered = Signal(str)


class HotkeyFilter(QAbstractNativeEventFilter):
    """捕获 WM_HOTKEY 并通过 hub 信号分发（线程安全）。"""

    def __init__(self) -> None:
        super().__init__()
        self.hub = HotkeyHub()
        self.triggered = self.hub.triggered
        self._id_to_name: Dict[int, str] = {}
        self._user32 = ctypes.windll.user32 if sys.platform == "win32" else None
        self._next_id = 1
        self.failed: List[str] = []      # 注册失败的热键名（被其他程序占用）

    def nativeEventFilter(self, event_type, message) -> bool:  # noqa: N802
        if event_type == b"windows_generic_MSG" or event_type == "windows_generic_MSG":
            try:
                msg = wt.MSG.from_address(int(message))
            except Exception:
                return False
            if msg.message == WM_HOTKEY:
                name = self._id_to_name.get(msg.wParam)
                if name:
                    self.hub.triggered.emit(name)
                    return True
        return False

    def register_all(self) -> None:
        self.failed.clear()
        if not self._user32:
            return
        for name, (mods, vk) in HOTKEY_DEFS.items():
            hid = self._next_id
            self._next_id += 1
            ok = self._user32.RegisterHotKey(None, hid, mods | MOD_NOREPEAT, vk)
            if ok:
                self._id_to_name[hid] = name
            else:
                self.failed.append(name)
                print(f"[Hotkey] 注册失败（可能被其他程序占用）: {name}")

    def failed_labels(self) -> List[str]:
        """返回人类可读的冲突热键列表。"""
        return [HOTKEY_LABELS.get(n, n) for n in self.failed]

    def unregister_all(self) -> None:
        if not self._user32:
            return
        for hid in list(self._id_to_name.keys()):
            self._user32.UnregisterHotKey(None, hid)
        self._id_to_name.clear()
