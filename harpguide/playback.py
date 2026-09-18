# -*- coding: utf-8 -*-
"""播放引擎：仅驱动 UI 渲染，不模拟任何输入、不发声、不与游戏交互。

时间轴以曲目时间（ms）为单位；speed_multiplier 只影响推进速率。
支持三种循环：
- 整曲循环（loop=True）
- A-B 段落循环（loop_range=(a_ms, b_ms)）——优先级高于整曲循环
- 预备拍 count-in（位置为负值）
"""
from __future__ import annotations

from typing import Optional, Tuple

from PySide6.QtCore import QObject, QElapsedTimer, Signal

from .models import Score


class PlaybackEngine(QObject):
    """曲目时钟。UI 每帧调用 position_ms() 获取当前曲目位置。"""

    state_changed = Signal(bool)         # playing?
    loop_range_changed = Signal()        # A-B 区间变更（设置/清除/切曲）
    pass_finished = Signal(float)        # 一整遍播完回绕到起点（参数＝回绕后的位置 ms）

    def __init__(self, score: Score, speed: float = 1.0, loop: bool = False,
                 count_in_beats: int = 4, parent: Optional[QObject] = None):
        super().__init__(parent)
        self.score = score
        self.speed = speed
        self.loop = loop
        self.count_in_beats = count_in_beats

        self._loop_range: Optional[Tuple[float, float]] = None   # (A 点 ms, B 点 ms)
        self._elapsed = QElapsedTimer()
        self._playing = False
        self._offset_ms = 0.0        # 暂停时累计的曲目位置
        self._finished = False

    # ---- 基本控制 ----
    @property
    def playing(self) -> bool:
        return self._playing

    @property
    def finished(self) -> bool:
        return self._finished

    def start_ms(self) -> float:
        """曲目起点（含预备拍，为负值）。"""
        if self.count_in_beats <= 0:
            return 0.0
        return -self.count_in_beats * 60000.0 / self.score.bpm

    def total_ms(self) -> float:
        return self.score.total_ms()

    def play(self) -> None:
        if self._playing:
            return
        if self._finished:
            self.reset()
        self._playing = True
        self._elapsed.start()
        self.state_changed.emit(True)

    def pause(self) -> None:
        if not self._playing:
            return
        self._offset_ms += self._elapsed.elapsed() * self.speed
        self._playing = False
        self.state_changed.emit(False)

    def toggle(self) -> None:
        self.pause() if self._playing else self.play()

    def reset(self) -> None:
        """回到起点：设有 A-B 区间时回到 A 点，否则回到曲首（含预备拍）。"""
        self._playing = False
        self._finished = False
        self._offset_ms = self._loop_range[0] if self._loop_range else self.start_ms()
        self.state_changed.emit(False)

    def seek(self, position_ms: float) -> None:
        """跳转到指定曲目位置。"""
        self._offset_ms = position_ms
        self._finished = False
        if self._playing:
            self._elapsed.restart()

    # ---- A-B 段落循环 ----
    @property
    def loop_range(self) -> Optional[Tuple[float, float]]:
        return self._loop_range

    def set_loop_range(self, a_ms: float, b_ms: float) -> bool:
        """设置 A-B 循环区间。自动交换顺序；区间过短则拒绝。"""
        a, b = (a_ms, b_ms) if a_ms <= b_ms else (b_ms, a_ms)
        if b - a < 50.0:          # 至少 50ms，避免误点造成死循环
            return False
        self._loop_range = (max(a, self.start_ms()), min(b, self.total_ms()))
        self._finished = False
        # 当前播放位置若在区间外，立即拉回 A 点
        if not (self._loop_range[0] <= self.position_ms() <= self._loop_range[1]):
            self.seek(self._loop_range[0])
        self.loop_range_changed.emit()
        return True

    def clear_loop_range(self) -> None:
        if self._loop_range is not None:
            self._loop_range = None
            self.loop_range_changed.emit()

    @property
    def has_loop_range(self) -> bool:
        return self._loop_range is not None

    # ---- 时间轴 ----
    def position_ms(self) -> float:
        """当前曲目位置（ms）。起点之前为负值（预备拍阶段）。"""
        pos = self._offset_ms
        if self._playing:
            pos += self._elapsed.elapsed() * self.speed

        total = self.total_ms()

        # A-B 段落循环优先：越过 B 点直接回绕到 A 点（不触发结束）
        # 仅在播放中回绕；暂停/手动 seek 时如实返回请求位置，避免位置显示错乱
        if self._loop_range is not None and self._playing:
            a, b = self._loop_range
            if pos > b and b > a:
                return self._wrap(a + (pos - b) % (b - a))

        if total > 0 and pos >= total:
            if self.loop:
                # 循环：从起点（不含预备拍）重新开始
                start = self.start_ms()
                return self._wrap(
                    start + (pos - total) % max(total - start, 1.0))
            pos = total
            if self._playing:
                self._playing = False
                self._finished = True
                self._offset_ms = total
                self.state_changed.emit(False)
        return pos

    def _wrap(self, pos: float) -> float:
        """回绕到新一遍：把位置基准前移并通知 `pass_finished`。

        回绕原先只在 position_ms() 里"算一次"：位置每帧被多处读取（渲染 / 判定 /
        调性提示），纯计算没有副作用，于是没有任何人知道"新一遍开始了"——上一遍的
        已判定音符仍然生效，A-B 循环第二遍开始后玩家按对也不给分（判定像停摆）。
        现在回绕只发生一次：位置基准落成 `_offset_ms` + 重启计时器，并发出信号。
        """
        self._offset_ms = pos
        self._elapsed.restart()
        self.pass_finished.emit(pos)
        return pos

    def beat_ms(self) -> float:
        return 60000.0 / self.score.bpm

    def set_score(self, score: Score) -> None:
        self.score = score
        self.clear_loop_range()
        self.reset()
