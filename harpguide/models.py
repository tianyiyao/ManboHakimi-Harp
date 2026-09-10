# -*- coding: utf-8 -*-
"""数据模型：乐谱 / 音符（tap 短按 / hold 长按 / rest 休止）。"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import List, Optional

# 游戏内口风琴实际键位（截图确认）：Z X C V B N M ,  共 8 键
DEFAULT_KEYMAP = ["Z", "X", "C", "V", "B", "N", "M", ","]
# 简谱数字 -> 键位（1..8 对应 1 2 3 4 5 6 7 高音1）
KEY_LABELS = ["1", "2", "3", "4", "5", "6", "7", "1"]

# ---- 半音阶口风琴（chromatic harmonica）映射 ----
# 传统半音阶口风琴 8 个物理键 + 一个「推键」切换升半音。
# 这里把「简谱度数 + 升降号」规范化到「物理键 + 调性档(accidental)」。
# 约定：accidental 0=自然档，+1=升调档；降号 b 一律等价转成升号（b2=#1 等），
#       因此谱面半音统一提示「升调档」吹出，符合单推键习惯。
# 度数(1..8，8=高音1) -> 自然半音序号
_DEGREE_SEMITONE = {1: 0, 2: 2, 3: 4, 4: 5, 5: 7, 6: 9, 7: 11, 8: 12}
# 半音序号 -> (物理键 index, accidental)
_SEMITONE_TO_KEY = {
    0: (0, 0),    # 1        -> Z
    1: (0, 1),    # #1 / b2  -> Z 升调
    2: (1, 0),    # 2        -> X
    3: (1, 1),    # #2 / b3  -> X 升调
    4: (2, 0),    # 3        -> C
    5: (3, 0),    # 4        -> V
    6: (3, 1),    # #4 / b5  -> V 升调
    7: (4, 0),    # 5        -> B
    8: (4, 1),    # #5 / b6  -> B 升调
    9: (5, 0),    # 6        -> N
    10: (5, 1),   # #6 / b7  -> N 升调
    11: (6, 0),   # 7        -> M
    12: (7, 0),   # 高音1     -> ,
}


def resolve_pitch(degree: int, accidental: int) -> tuple[int, int]:
    """把「简谱度数(1..8) + 升降号(-1/0/+1)」规范化为 (物理键index, 调性档)。

    调性档只会是 0（自然）或 +1（升调）：降号等价转成升号，
    例如 b3 -> #2（X 键升调）、b4 -> 3（C 键自然）。
    """
    semi = _DEGREE_SEMITONE.get(degree, degree - 1) + accidental
    if semi < 0:          # b1 -> 7（低八度回绕）
        semi += 12
    elif semi > 12:       # #7 已到高音1；#i 超音域回绕到 #1
        semi -= 12
    key_idx, acc = _SEMITONE_TO_KEY.get(semi, (degree - 1, 0))
    return key_idx, acc


class NoteType(str, Enum):
    TAP = "tap"    # 短按：快速点击
    HOLD = "hold"  # 长按：按住直到长条结束
    REST = "rest"  # 休止：不操作


@dataclass
class Note:
    key: str                 # 键位标识：Z/X/C/V/B/N/M/, 或 "rest"
    type: NoteType
    duration: float          # 时值（拍）。0.25=十六分 0.5=八分 1=四分 2=二分
    beat: float              # 起始拍数
    accidental: int = 0      # 升降号：0=自然 / +1=升调档 / -1=降调档（半音阶口风琴推键）

    # ---- 时间换算 ----
    def start_ms(self, bpm: float) -> float:
        return self.beat * 60000.0 / bpm

    def duration_ms(self, bpm: float) -> float:
        return self.duration * 60000.0 / bpm

    def end_ms(self, bpm: float) -> float:
        return self.start_ms(bpm) + self.duration_ms(bpm)

    def accidental_mark(self) -> str:
        """半音标记：升 -> "#"、降 -> "b"、自然 -> ""。"""
        return "#" if self.accidental > 0 else ("b" if self.accidental < 0 else "")


@dataclass
class LyricLine:
    time_ms: float           # 歌词出现时间（曲目时间，毫秒）
    text: str                # 歌词文本


def _lyric_from_dict(raw: dict) -> LyricLine:
    return LyricLine(
        time_ms=float(raw.get("time", 0.0)),
        text=str(raw.get("text", "")),
    )


@dataclass
class Score:
    id: str = ""
    name: str = "未命名"
    bpm: float = 80.0
    time_signature: str = "4/4"
    keymap: List[str] = field(default_factory=lambda: list(DEFAULT_KEYMAP))
    notes: List[Note] = field(default_factory=list)
    lyrics: List[LyricLine] = field(default_factory=list)

    def total_beats(self) -> float:
        if not self.notes:
            return 0.0
        return max(n.beat + n.duration for n in self.notes)

    def total_ms(self) -> float:
        return self.total_beats() * 60000.0 / self.bpm

    def key_index(self, key: str) -> int:
        try:
            return self.keymap.index(key)
        except ValueError:
            return -1

    def lyric_at(self, pos_ms: float) -> Optional[int]:
        """返回当前播放位置对应的歌词行索引；无匹配返回 None。"""
        idx = -1
        for i, line in enumerate(self.lyrics):
            if line.time_ms <= pos_ms:
                idx = i
            else:
                break
        return idx if idx >= 0 else None

    # ---- 序列化 ----
    def to_dict(self) -> dict:
        return {
            "version": "2.1",
            "id": self.id,
            "name": self.name,
            "bpm": self.bpm,
            "timeSignature": self.time_signature,
            "keyMap": self.keymap,
            "notes": [
                {**{"key": n.key, "type": n.type.value, "duration": n.duration, "beat": n.beat},
                 **({"accidental": n.accidental} if n.accidental else {})}
                for n in self.notes
            ],
            "lyrics": [
                {"time": l.time_ms, "text": l.text} for l in self.lyrics
            ],
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Score":
        notes = []
        for raw in data.get("notes", []):
            key = str(raw.get("key", "rest"))
            ntype = NoteType(raw.get("type", "tap"))
            # 兼容 v1.0 旧格式（无 type 字段）：duration>1 视为长按
            if "type" not in raw and ntype is NoteType.TAP and float(raw.get("duration", 1)) > 1.0:
                ntype = NoteType.HOLD
            notes.append(Note(
                key=key,
                type=ntype,
                duration=float(raw.get("duration", 1.0)),
                beat=float(raw.get("beat", 0.0)),
                accidental=int(raw.get("accidental", 0)),
            ))
        return cls(
            id=str(data.get("id", "")),
            name=str(data.get("name", "未命名")),
            bpm=float(data.get("bpm", 80.0)),
            time_signature=str(data.get("timeSignature", "4/4")),
            keymap=list(data.get("keyMap", DEFAULT_KEYMAP)),
            notes=notes,
            lyrics=[_lyric_from_dict(r) for r in data.get("lyrics", [])],
        )

    @classmethod
    def load(cls, path: str | Path) -> "Score":
        p = Path(path)
        with open(p, "r", encoding="utf-8") as f:
            data = json.load(f)
        score = cls.from_dict(data)
        if not score.id:
            score.id = p.stem
        return score

    def save(self, path: str | Path) -> None:
        Path(path).write_text(
            json.dumps(self.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8"
        )


def load_scores(folder: str | Path) -> List[Score]:
    """加载曲目目录下所有 .json 乐谱，按名称排序。"""
    scores: List[Score] = []
    folder = Path(folder)
    if not folder.exists():
        return scores
    for p in sorted(folder.glob("*.json")):
        try:
            scores.append(Score.load(p))
        except Exception as e:  # 单个乐谱损坏不影响整体
            print(f"[ScoreLoader] 跳过损坏的乐谱 {p.name}: {e}")
    return scores


def find_score(folder: str | Path, score_id: str) -> Optional[Score]:
    for s in load_scores(folder):
        if s.id == score_id:
            return s
    return None
