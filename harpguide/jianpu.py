# -*- coding: utf-8 -*-
"""简谱解析器：把文本简谱转换为 Score（含长按音符支持）。

语法：
    1 2 3 4 5 6 7     基本音级（短按）
    8 或 1'            高音 1（第 8 键）
    #4                 升 4（半音阶：切「升调」档按 V 键）
    b3                 降 3（等价 #2，切「升调」档按 X 键）
    3-                长按 2 拍（一个 "-" 延长一拍）
    6--               长按 3 拍
    -                 延音线：把前一个音符再延长一拍（与 6-- 等价，写起来更松快）
    0                 休止 1 拍
    0.5:3             分数时值（拍:音级），用于八分/十六分音符
    0.5:#4            分数时值 + 升号
    |                 小节线（忽略）
    // 注释           行注释

示例：
    | 1 2 3- 4 | 5 5 6-- 7 |
    | 0.5:1 0.5:2 1- 3 | 8 7 6- |
    | 1- - - |            与 "1---" 等价（4 拍）
    | #4 #5 #6 |         半音阶下行（升调档）
"""
from __future__ import annotations

import re
from typing import List

from .models import DEFAULT_KEYMAP, Note, NoteType, Score, resolve_pitch

_BARLINE = re.compile(r"[|‖]")
_DASH_ONLY = re.compile(r"-+")


def _parse_token(token: str) -> Note | None:
    """解析单个简谱 token，返回 Note；默认时值 1 拍。

    支持半音：#4（升 4）、b3（降 3，等价 #2）。升降号会经 resolve_pitch
    规范化到「物理键 + 调性档」，降号等价转成升号（半音阶单推键习惯）。
    """
    token = token.strip()
    if not token:
        return None

    duration = 1.0
    accidental = 0
    body = token

    # 分数时值形式  beat:degree  例如 0.5:3 八分音符、0.5:#4 八分升 4
    m = re.match(r"^(\d+(?:\.\d+)?)[:：]([#b]?)(\d)('?)$", body)
    if m:
        duration = float(m.group(1))
        accidental = 1 if m.group(2) == "#" else (-1 if m.group(2) == "b" else 0)
        body = m.group(3) + m.group(4)          # 如 "3" 或 "1'"
    else:
        # 普通形式：#4 / b3 / 1 / 1' / 8 / #1' 等（可带延音线 -）
        m2 = re.match(r"^([#b]?)(\d)('?)(-*)$", body)
        if not m2:
            return None
        accidental = 1 if m2.group(1) == "#" else (-1 if m2.group(1) == "b" else 0)
        body = m2.group(2) + m2.group(3)
        if m2.group(4):
            duration = 1.0 + len(m2.group(4))   # 基础 1 拍 + 每条 "-" 延长 1 拍

    high = body.endswith("'")
    num = int(body.rstrip("'"))

    if num == 0:  # 休止符（不支持升降）
        if duration == 1.0 and token.endswith("-"):
            duration = 1.0 + len(token) - 1
        return Note(key="rest", type=NoteType.REST, duration=duration, beat=0.0)

    degree = 8 if (high or num == 8) else num
    if not (1 <= degree <= 8):
        return None

    key_idx, acc = resolve_pitch(degree, accidental)
    ntype = NoteType.HOLD if duration > 1.0 else NoteType.TAP
    return Note(
        key=DEFAULT_KEYMAP[key_idx],
        type=ntype,
        duration=duration,
        beat=0.0,
        accidental=acc,
    )


def parse_jianpu(text: str, name: str = "未命名", bpm: float = 80.0,
                 score_id: str = "") -> Score:
    """把简谱文本解析为 Score。"""
    # 去掉行注释
    text = re.sub(r"//[^\n]*", "", text)
    notes: List[Note] = []
    beat = 0.0
    for raw in text.split():
        if _BARLINE.fullmatch(raw):
            continue
        # 延音线：把前一个音符再延长，等价于在它后面补 "-"
        if _DASH_ONLY.fullmatch(raw):
            if notes:
                add = float(len(raw))
                last = notes[-1]
                last.duration += add
                if last.type is NoteType.TAP and last.duration > 1.0:
                    last.type = NoteType.HOLD
                beat += add
            continue
        note = _parse_token(raw)
        if note is None:
            continue
        note.beat = beat
        beat += note.duration
        notes.append(note)
    return Score(id=score_id or name, name=name, bpm=bpm, notes=notes)
