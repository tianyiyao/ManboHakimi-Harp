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
    MISS     超时未按 / 抢拍拖拍

关于「按对了还出 MISS」：真实演奏里按键与谱面总有一点系统性时差
（人的反应 + 画面延迟）。因此这里有一整套宽容设计：
1. 判定窗口整体放宽（见上表）；
2. 抢拍 / 拖拍宽容带（`GRACE_MS`）——偏移超出 GOOD 窗口但仍落在
   `MISS_WINDOW_MS` 内的按键，说明玩家**确实在打这个音符**，只是时机偏了。
   此时记一次 MISS 但**不消耗该音符**，玩家可以在窗口内重按救回来。
   这是修复「第一次没按好，再按还是 MISS」的关键（旧实现直接把音符吃掉，
   于是重按既匹配不到原音符、又被判成空按，连吃两个 MISS）；
3. 空按**不判 MISS**（见 `app._on_key_hit`）——练习工具里试键/找键是常态，
   附近根本没音符的敲击静默忽略，不再断连击；
4. `judge_offset_ms`（设置面板「判定偏移」）可以把整个判定基准平移，
   用来补偿玩家固定偏早/偏晚的手感；
5. 漏音窗口 = 判定窗口 + `GRACE_MS`，杜绝"还能判 GOOD 却被漏音抢先判 MISS"
   的帧序竞争；
6. **长按（hold）单独判定**——玩家常在长音起点**之前**就把键压住（这是正确的
   长按手法），那一刻没有新的按键边沿，只看边沿的旧逻辑会整条长音判 MISS。
   因此长音改为「键处于按住状态 + 与音符区间有重叠」判定，见 `HOLD_EARLY_MS`。
"""
from __future__ import annotations

import ctypes
import sys
from typing import Dict, List, Optional, Set, Tuple

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

# 抢拍 / 拖拍宽容带。
# 偏移落在 (GOOD, MISS] 之间的按键：玩家确实在打这个音符，只是时机偏了。
# 记一次 MISS，但**不消耗音符**，玩家还能重按救回来（详见模块 docstring 第 2 条）。
GRACE_MS = 160.0
# 音符超时（漏音）窗口**必须宽于判定窗口**：两者相等时，漏音定时器会在
# 「刚好还能判 GOOD 的那一帧」抢先触发，于是玩家按对了却看到 MISS（帧序竞争）。
MISS_WINDOW_MS = JUDGE_GOOD_MS + GRACE_MS

# 长按（hold）音符的按住判定窗口。
# 长音天生要「提前压住」，因此早侧的宽容度远大于判定窗口；
# 晚侧给一点余量，处理手松得慢的玩家。
HOLD_EARLY_MS = 300.0
HOLD_LATE_MS = 120.0

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
    """轮询检测 8 键的按下状态。

    用法：每帧调用 poll()，返回 `(本帧新按下的键, 当前按住不放的键)`。
    - 新按下的键用于短按（tap）判定与起音；
    - 按住集合用于长按（hold）判定——长音要提前压住，只看边沿会漏。
    """

    def __init__(self, vk_map: Optional[Dict[str, int]] = None):
        self._map = dict(vk_map) if vk_map else dict(VK_PLAY_KEYS)
        self._down: Dict[str, bool] = {k: False for k in self._map}
        self._user32 = ctypes.windll.user32 if sys.platform == "win32" else None

    @property
    def available(self) -> bool:
        return self._user32 is not None

    def poll(self) -> Tuple[List[str], Set[str]]:
        """返回 (本帧刚按下的键, 当前处于按住状态的键)。仅读取，不拦截、不吞键。

        为防「帧被游戏拖慢导致漏掉一次快速敲击」，除了比较 0x8000（当前是否按下），
        还读取 0x0001（**上次调用之后是否发生过按下**）。游戏满载时帧间隔可能 >40ms，
        单靠 0x8000 的边沿比较会漏掉这种短促轻敲；加上 0x0001 保证不漏。
        """
        if self._user32 is None:
            return [], set()
        pressed: List[str] = []
        held: Set[str] = set()
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
            if down:
                held.add(key)
        return pressed, held

    def reset(self) -> None:
        """以当前物理按键状态重新建立基线，避免把已按住的键当作新按下。"""
        for key, vk in self._map.items():
            if self._user32 is None:
                self._down[key] = False
                continue
            try:
                # 同时读掉 0x0001 历史位；下一帧只报告重置之后的新按下。
                self._down[key] = bool(self._user32.GetAsyncKeyState(vk) & 0x8000)
            except Exception:
                self._down[key] = False
