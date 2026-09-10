# -*- coding: utf-8 -*-
"""命中检测：被动读取 8 个演奏键的物理按下状态 + 节奏判定。

设计原则（与全项目一致，绝不模拟键鼠）：
- 只用 `GetAsyncKeyState` **轮询读取**按键状态，不安装键盘钩子、不拦截、不吞键，
  游戏照常收到按键；本项目也从不向系统发送任何按键 / 鼠标事件。
- 轮询在主控 16ms 帧循环里进行，开销可忽略。
- 非 Windows 平台静默降级（poll 恒返回空）。

判定（类似《指上钢琴》等音游）：
    PERFECT  |偏移| <= 110ms
    GREAT    |偏移| <= 220ms
    GOOD     |偏移| <= 350ms
    MISS     其余（空按 / 超时未按）

关于「按对了还出 MISS」：真实演奏里按键与谱面总有一点系统性时差
（人的反应 + 画面延迟）。因此这里有四个宽容设计：
1. 判定窗口整体放宽（见上表）；
2. `MATCH_WINDOW_MS` 比判定窗口更宽——落在里面的按键视为「这一列已有音符」，
   只是迟到/重复，**不再额外记一次空按 MISS**，避免一次失误变成两个 MISS；
3. `judge_offset_ms`（设置面板「判定偏移」）可以把整个判定基准平移，
   用来补偿玩家固定偏早/偏晚的手感；
4. 漏音窗口 = 判定窗口 + `MISS_GRACE_MS`，杜绝"还能判 GOOD 却被漏音抢先判 MISS"
   的帧序竞争。
"""
from __future__ import annotations

import ctypes
import sys
from typing import Dict, List, Optional

# 游戏内口风琴 8 键的虚拟键码（VK）
VK_PLAY_KEYS: Dict[str, int] = {
    "Z": 0x5A,
    "X": 0x58,
    "C": 0x43,
    "V": 0x56,
    "B": 0x42,
    "N": 0x4E,
    "M": 0x4D,
    ",": 0xBC,   # VK_OEM_COMMA
}

# 判定窗口（ms）：从严到宽
JUDGE_PERFECT_MS = 110.0
JUDGE_GREAT_MS = 220.0
JUDGE_GOOD_MS = 350.0
# 命中窗口：按键落在 [start-window, start+window] 内才算"打到"这个音符
HIT_WINDOW_MS = JUDGE_GOOD_MS
# 音符超时（漏音）窗口**必须略宽于判定窗口**：两者相等时，漏音定时器会在
# 「刚好还能判 GOOD 的那一帧」抢先触发，于是玩家按对了却看到 MISS（帧序竞争）。
# 留 90ms 余量后，任何能判 GOOD 及以上的按键都保证先被吃掉，不会再被漏音抢先。
MISS_GRACE_MS = 90.0
MISS_WINDOW_MS = JUDGE_GOOD_MS + MISS_GRACE_MS
# 按键匹配窗口：比判定窗口更宽。落在这个范围内的按键说明"这一列刚刚/即将有音符"，
# 只是时机偏了或是重复按，**不再叠加一次空按 MISS**（避免一次失误两处 MISS）。
MATCH_WINDOW_MS = 640.0

# 判定 -> (显示文字, 基础分)
JUDGE_TABLE = (
    (JUDGE_PERFECT_MS, "PERFECT", 100),
    (JUDGE_GREAT_MS, "GREAT", 70),
    (JUDGE_GOOD_MS, "GOOD", 40),
)


def judge_offset(offset_ms: float) -> tuple:
    """按时间偏移给出 (判定标签, 基础分)。offset = 实际按下时刻 - 音符起点。"""
    a = abs(offset_ms)
    for limit, label, points in JUDGE_TABLE:
        if a <= limit:
            return (label, points)
    return ("MISS", 0)


class KeyWatcher:
    """轮询检测 8 键的"按下瞬间"（边沿触发）。

    用法：每帧调用 poll()，返回本帧**新按下**的键字母列表。
    """

    def __init__(self, vk_map: Optional[Dict[str, int]] = None):
        self._map = dict(vk_map) if vk_map else dict(VK_PLAY_KEYS)
        self._down: Dict[str, bool] = {k: False for k in self._map}
        self._user32 = ctypes.windll.user32 if sys.platform == "win32" else None

    @property
    def available(self) -> bool:
        return self._user32 is not None

    def poll(self) -> List[str]:
        """返回本帧刚按下的键（仅读取，不拦截、不吞键）。

        为防「帧被游戏拖慢导致漏掉一次快速敲击」，除了比较 0x8000（当前是否按下），
        还读取 0x0001（**上次调用之后是否发生过按下**）。游戏满载时帧间隔可能 >40ms，
        单靠 0x8000 的边沿比较会漏掉这种短促轻敲；加上 0x0001 保证不漏。
        """
        if self._user32 is None:
            return []
        pressed: List[str] = []
        for key, vk in self._map.items():
            try:
                state = self._user32.GetAsyncKeyState(vk)
            except Exception:
                continue
            down = bool(state & 0x8000)
            since_last = bool(state & 0x0001)
            if (down and not self._down[key]) or since_last:
                pressed.append(key)
            self._down[key] = down
        return pressed

    def reset(self) -> None:
        """清空边沿状态（切曲 / 重置时调用，避免把"一直按住"误判为新按下）。"""
        for k in self._down:
            self._down[k] = False
