# -*- coding: utf-8 -*-
"""乐谱编辑器（钢琴卷帘）。

交互：
- 左键点空白格：创建 1 拍短按音符（tap）
- 左键按住向右拖：拉长时值；超过 1 拍自动变为长按（hold）
- 左键按住音符拖动：移动起始位置
- 左键按住音符右边缘：调整时值
- Ctrl / Shift + 左键点音符：加选
- 右键点音符：删除
- 顶部可改曲名与 BPM、切换吸附精度；支持撤销/重做、复制粘贴、导入导出

网格精度：默认 0.5 拍（八分音符），可切到 0.25 拍（十六分）。
行 = 8 个琴键（顶部为高音 1）。
"""
from __future__ import annotations

import hashlib
import math
import re
from pathlib import Path
from typing import List, Optional

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import (QColor, QFont, QKeySequence, QLinearGradient,
                           QPainter, QPen, QPolygonF, QShortcut)
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog, QFileDialog,
                               QHBoxLayout, QLabel, QLineEdit, QMessageBox,
                               QPlainTextEdit, QPushButton, QScrollArea,
                               QSpinBox, QVBoxLayout, QWidget)

from .config import data_dir
from .jianpu import parse_jianpu, scan_tokens
from .models import DEFAULT_KEYMAP, KEY_LABELS, Note, NoteType, Score
from .theme import THEME

STEP = 0.5            # 默认编辑精度（拍）
PPB = 60.0            # 每拍像素
ROW_H = 34.0
LEFT_MARGIN = 64.0
TOP_MARGIN = 24.0
KEY_COUNT = 8
MIN_BEATS = 32.0


def _exec_topmost(dialog: QWidget) -> int:
    """把模态对话框置顶后 exec，防止被游戏等全屏窗口压在后面。"""
    dialog.setWindowFlags(dialog.windowFlags() | Qt.WindowType.WindowStaysOnTopHint)
    dialog.raise_()
    dialog.activateWindow()
    return dialog.exec()


def _topmost_message(parent: QWidget, title: str, text: str,
                     buttons: QMessageBox.StandardButtons,
                     default: QMessageBox.StandardButton,
                     icon: QMessageBox.Icon = QMessageBox.Icon.Question) -> QMessageBox.StandardButton:
    """创建并置顶显示一个 QMessageBox。"""
    msg = QMessageBox(parent)
    msg.setWindowTitle(title)
    msg.setText(text)
    msg.setStandardButtons(buttons)
    msg.setDefaultButton(default)
    msg.setIcon(icon)
    return QMessageBox.StandardButton(_exec_topmost(msg))


def _topmost_file_dialog(dlg: QFileDialog) -> tuple:
    """置顶执行 QFileDialog；返回 (DialogCode.Accepted, selected_files) 或 (Rejected, [])。"""
    ok = _exec_topmost(dlg) == QDialog.DialogCode.Accepted
    files = dlg.selectedFiles() if ok else []
    return ok, files
UNDO_LIMIT = 100


def sanitize_id(name: str) -> str:
    """从曲名生成安全文件名（同时在曲名互不相同时保证 id 互不相同）。

    纯 ASCII 曲名直接用可读的 slug；一旦曲名里没有 ASCII 字符（中文曲名是常态），
    旧的兜底 `return slug or "user_song"` 会让**所有**中文曲名塌缩成同一个
    `user_song` —— 于是「另存为」的默认文件名总是 scores/user_song.json、
    「重命名」也会写到同一个文件上，前一首自编曲被静默覆盖（真丢数据）。
    这里改成按曲名取稳定哈希后缀：同名同 id（覆盖是预期），不同名一定不同 id。
    """
    slug = re.sub(r"[^0-9A-Za-z_]+", "_", name).strip("_").lower()
    if slug and len(slug) <= 40:
        return slug
    digest = hashlib.md5(name.encode("utf-8")).hexdigest()[:8]
    if slug:                       # ASCII 够长：可读前缀 + 哈希，避免超长/截断撞车
        return f"{slug[:40]}_{digest}"
    return f"song_{digest}"


def unique_score_id(name: str, folder: Path) -> str:
    """给「新建 / 另存为」挑一个不覆盖别人的曲目 id。

    目标文件不存在 -> 直接用；
    已存在且里面就是同名的这首 -> 视为同一首歌，覆盖是预期行为；
    已存在但是别的曲目 -> 追加 _2 / _3 …，绝不静默覆盖别人的文件。
    """
    base = sanitize_id(name)
    candidate, n = base, 2
    while True:
        path = folder / f"{candidate}.json"
        if not path.exists():
            return candidate
        try:
            if Score.load(path).name == name:
                return candidate
        except Exception:               # 读不出来（损坏/非本格式）就当它是别人的文件
            pass
        candidate = f"{base}_{n}"
        n += 1


class EditorGrid(QWidget):
    """钢琴卷帘网格：负责音符的布局编辑、选择、撤销栈与绘制。"""

    changed = Signal()          # 内容变化（供窗口更新撤销按钮状态）

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self._keymap: List[str] = list(DEFAULT_KEYMAP)
        self._notes: List[Note] = []
        self._selection: List[Note] = []
        self._mode = ""                 # "" / "create" / "move" / "resize"
        self._grab_off = 0.0
        self._beats = MIN_BEATS
        self._step = STEP
        self._cursor_beat = 0.0
        self._undo: List[List[Note]] = []
        self._redo: List[List[Note]] = []
        self._clipboard: List[Note] = []
        self.setMouseTracking(True)
        self._update_size()

    # ---- 数据 ----
    def load_score(self, score: Score) -> None:
        self._keymap = list(score.keymap)
        self._notes = [Note(n.key, n.type, n.duration, n.beat, n.accidental) for n in score.notes]
        self._selection = []
        self._mode = ""
        self._undo.clear()
        self._redo.clear()
        self._update_size()
        self.update()
        self.changed.emit()

    def set_notes(self, notes: List[Note], append: bool = False) -> int:
        """用一批音符替换（或追加到）编辑区内容，返回写入了几个音符。

        先记快照再改，所以这一下是可撤销的——粘错一段谱子不必手工清空重画。
        追加时从现有内容末尾起算并对齐到整拍：两段之间留一个明确的空档，
        比让前一段的尾音和后一段的头直接连上更好读。
        """
        if not notes:
            return 0
        self._snapshot()
        if append and self._notes:
            base = float(math.ceil(max(n.beat + n.duration for n in self._notes)))
            self._notes.extend(
                Note(n.key, n.type, n.duration, n.beat + base, n.accidental)
                for n in notes)
        else:
            self._notes = self._copy_all(notes)
        self._selection = []
        self._mode = ""
        self._update_size()
        self.update()
        self.changed.emit()
        return len(notes)

    def notes(self) -> List[Note]:
        return sorted(
            (Note(n.key, n.type, n.duration, n.beat, n.accidental) for n in self._notes),
            key=lambda n: (n.beat, n.key))

    def selection(self) -> List[Note]:
        return list(self._selection)

    # ---- 撤销 / 重做 ----
    @staticmethod
    def _copy_all(notes: List[Note]) -> List[Note]:
        return [Note(n.key, n.type, n.duration, n.beat, n.accidental) for n in notes]

    def _snapshot(self) -> None:
        """在改动前记录一份快照。"""
        self._undo.append(self._copy_all(self._notes))
        if len(self._undo) > UNDO_LIMIT:
            self._undo.pop(0)
        self._redo.clear()

    def _restore(self, state: List[Note]) -> None:
        self._notes = self._copy_all(state)
        self._selection = []
        self._mode = ""
        self._update_size()
        self.update()
        self.changed.emit()

    def can_undo(self) -> bool:
        return bool(self._undo)

    def can_redo(self) -> bool:
        return bool(self._redo)

    def undo(self) -> bool:
        if not self._undo:
            return False
        self._redo.append(self._copy_all(self._notes))
        self._restore(self._undo.pop())
        return True

    def redo(self) -> bool:
        if not self._redo:
            return False
        self._undo.append(self._copy_all(self._notes))
        self._restore(self._redo.pop())
        return True

    # ---- 音符操作（供鼠标事件、快捷键与自检复用） ----
    def _create_note(self, beat: float, key_idx: int) -> Note:
        note = Note(key=self._keymap[key_idx], type=NoteType.TAP,
                    duration=1.0, beat=beat)
        self._notes.append(note)
        self._selection = [note]
        self._update_size()
        self.changed.emit()
        return note

    def _apply_duration(self, note: Note, duration: float) -> None:
        note.duration = max(self._step, duration)
        note.type = NoteType.HOLD if note.duration > 1.0 else NoteType.TAP
        self._update_size()
        self.changed.emit()

    def _delete_note(self, note: Note) -> None:
        if note in self._notes:
            self._notes.remove(note)
            if note in self._selection:
                self._selection.remove(note)
            self.changed.emit()

    def delete_selection(self) -> bool:
        if not self._selection:
            return False
        self._snapshot()
        for n in list(self._selection):
            self._delete_note(n)
        self._selection = []
        self._update_size()
        self.update()
        return True

    def clear_all(self) -> bool:
        if not self._notes:
            return False
        self._snapshot()
        self._notes.clear()
        self._selection = []
        self._update_size()
        self.update()
        self.changed.emit()
        return True

    def select_all(self) -> None:
        self._selection = list(self._notes)
        self.update()

    def cycle_accidental(self) -> bool:
        """选中音符循环切换升降：自然(0) → 升(+1) → 降(-1) → 自然(0)。

        对应半音阶口风琴的推键：升号 = 切升调档、降号 = 切降调档。
        """
        if not self._selection:
            return False
        self._snapshot()
        for n in self._selection:
            n.accidental = 1 if n.accidental == 0 else (-1 if n.accidental == 1 else 0)
        self.update()
        self.changed.emit()
        return True

    # ---- 剪贴板 ----
    def copy(self) -> bool:
        if not self._selection:
            return False
        self._clipboard = self._copy_all(
            sorted(self._selection, key=lambda n: (n.beat, n.key)))
        return True

    def cut(self) -> bool:
        if not self.copy():
            return False
        return self.delete_selection()

    def has_clipboard(self) -> bool:
        return bool(self._clipboard)

    def paste(self) -> bool:
        """粘贴到光标所在拍（保持组内相对位置与键位行）。"""
        if not self._clipboard:
            return False
        self._snapshot()
        base = min(n.beat for n in self._clipboard)
        target = self._paste_target()
        new_notes = []
        for n in self._clipboard:
            nn = Note(n.key, n.type, n.duration, max(0.0, target + (n.beat - base)), n.accidental)
            self._notes.append(nn)
            new_notes.append(nn)
        self._selection = new_notes
        self._update_size()
        self.update()
        self.changed.emit()
        return True

    def duplicate(self) -> bool:
        """就地复制一份，接在选区末尾。"""
        if not self._selection:
            return False
        self._snapshot()
        base = min(n.beat for n in self._selection)
        span = max(n.beat + n.duration for n in self._selection) - base
        target = base + span
        new_notes = []
        for n in self._selection:
            nn = Note(n.key, n.type, n.duration, target + (n.beat - base), n.accidental)
            self._notes.append(nn)
            new_notes.append(nn)
        self._selection = new_notes
        self._update_size()
        self.update()
        self.changed.emit()
        return True

    def _paste_target(self) -> float:
        """粘贴落点：优先跟随鼠标光标所在拍。"""
        if self._cursor_beat > 0:
            return self._cursor_beat
        if self._selection:
            return max(n.beat + n.duration for n in self._selection)
        return 0.0

    # ---- 吸附精度 ----
    def set_step(self, step: float) -> None:
        self._step = max(0.25, min(1.0, float(step)))
        self.update()

    def step(self) -> float:
        return self._step

    # ---- 几何换算 ----
    def _update_size(self) -> None:
        if self._notes:
            end = max(n.beat + n.duration for n in self._notes)
            self._beats = max(MIN_BEATS, float(int(end) + 8))
        else:
            self._beats = MIN_BEATS
        self.setFixedSize(int(LEFT_MARGIN + self._beats * PPB + 24),
                          int(TOP_MARGIN + KEY_COUNT * ROW_H + 10))

    def _snap_beat(self, x: float) -> float:
        raw = (x - LEFT_MARGIN) / PPB
        return max(0.0, round(raw / self._step) * self._step)

    def _key_at(self, y: float) -> int:
        """y 坐标 -> 键索引（0..7）；无效返回 -1。"""
        row = int((y - TOP_MARGIN) // ROW_H)
        if 0 <= row < KEY_COUNT:
            return KEY_COUNT - 1 - row     # 顶部行 = 索引 7
        return -1

    def _note_at(self, pos: QPointF) -> Optional[Note]:
        key_idx = self._key_at(pos.y())
        if key_idx < 0:
            return None
        key = self._keymap[key_idx]
        beat = (pos.x() - LEFT_MARGIN) / PPB
        for note in reversed(self._notes):
            if note.key == key and note.beat <= beat < note.beat + note.duration:
                return note
        return None

    def _note_right_edge_x(self, note: Note) -> float:
        return LEFT_MARGIN + (note.beat + note.duration) * PPB

    # ---- 鼠标交互 ----
    def mousePressEvent(self, e) -> None:  # noqa: N802
        pos = e.position()
        self._cursor_beat = self._snap_beat(pos.x())
        self.setFocus(Qt.FocusReason.MouseFocusReason)

        if e.button() == Qt.MouseButton.RightButton:
            note = self._note_at(pos)
            if note is not None:
                self._snapshot()
                self._delete_note(note)
                self.update()
            return
        if e.button() != Qt.MouseButton.LeftButton:
            return

        additive = bool(e.modifiers() & (Qt.KeyboardModifier.ControlModifier
                                         | Qt.KeyboardModifier.ShiftModifier))
        note = self._note_at(pos)
        if note is not None:
            if additive:
                if note in self._selection:
                    self._selection.remove(note)
                else:
                    self._selection.append(note)
            elif note not in self._selection:
                self._selection = [note]
            # 右边缘 12px 内 = 调整时值；其余 = 移动
            self._snapshot()
            if pos.x() >= self._note_right_edge_x(note) - 12:
                self._mode = "resize"
            else:
                self._mode = "move"
                self._grab_off = (pos.x() - (LEFT_MARGIN + note.beat * PPB)) / PPB
        else:
            beat = self._snap_beat(pos.x())
            key_idx = self._key_at(pos.y())
            if key_idx >= 0 and beat >= 0:
                self._snapshot()
                note = self._create_note(beat, key_idx)
                self._mode = "create"
        self.update()

    def mouseMoveEvent(self, e) -> None:  # noqa: N802
        pos = e.position()
        if self._key_at(pos.y()) >= 0:
            self._cursor_beat = self._snap_beat(pos.x())
        if not self._mode or not self._selection:
            return
        target = self._selection[-1]
        if self._mode == "move":
            new_beat = self._snap_beat(pos.x() - self._grab_off * PPB)
            delta = new_beat - target.beat
            # 整组一起移动，并保证不越过 0
            delta = max(delta, -min(n.beat for n in self._selection))
            for n in self._selection:
                n.beat = max(0.0, n.beat + delta)
            self._update_size()
        else:  # create / resize：向右拉长时值
            dur = self._snap_beat(pos.x()) - target.beat
            self._apply_duration(target, max(self._step, dur) if dur > 0 else self._step)
        self.changed.emit()
        self.update()

    def mouseReleaseEvent(self, e) -> None:  # noqa: N802
        self._mode = ""
        self._update_size()

    # ---- 绘制 ----
    def paintEvent(self, event) -> None:  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)

        # 行底（奇偶行交替）
        for i in range(KEY_COUNT):
            y = TOP_MARGIN + (KEY_COUNT - 1 - i) * ROW_H
            shade = QColor(22, 28, 38) if i % 2 else QColor(17, 22, 30)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(shade)
            p.drawRect(QRectF(LEFT_MARGIN, y, self.width() - LEFT_MARGIN, ROW_H))
            # 行标签：键位字母 + 简谱数字
            p.setPen(QColor(THEME.text_secondary))
            p.setFont(QFont(THEME.font_mono, 9))
            p.drawText(QRectF(6, y, LEFT_MARGIN - 10, ROW_H / 2 + 4),
                       Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignBottom,
                       f" {self._keymap[i]}")
            p.setPen(QColor(THEME.pitch_color(i)))
            p.drawText(QRectF(6, y + ROW_H / 2 - 4, LEFT_MARGIN - 10, ROW_H / 2),
                       Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop,
                       f" {KEY_LABELS[i]}{'.' if i == 7 else ''}")

        # 拍线与小节线
        b = 0.0
        while b <= self._beats:
            x = LEFT_MARGIN + b * PPB
            bar = (b % 4 == 0)
            p.setPen(QColor(255, 255, 255, 44 if bar else 18))
            p.drawLine(QPointF(x, TOP_MARGIN),
                       QPointF(x, TOP_MARGIN + KEY_COUNT * ROW_H))
            if bar:
                p.setPen(QColor(THEME.text_secondary))
                p.setFont(QFont(THEME.font_mono, 8))
                p.drawText(QRectF(x + 2, 2, 40, 16), f"{int(b)}")
            b += 1.0
        # 半拍辅助线（跟随吸附精度）
        if self._step <= 0.5:
            b = self._step
            while b <= self._beats:
                x = LEFT_MARGIN + b * PPB
                p.setPen(QColor(255, 255, 255, 8))
                p.drawLine(QPointF(x, TOP_MARGIN),
                           QPointF(x, TOP_MARGIN + KEY_COUNT * ROW_H))
                b += 0.5

        # 光标位置竖线（粘贴落点参考）
        if self._cursor_beat > 0:
            cx = LEFT_MARGIN + self._cursor_beat * PPB
            p.setPen(QPen(QColor(0, 229, 255, 90), 1.0))
            p.drawLine(QPointF(cx, TOP_MARGIN),
                       QPointF(cx, TOP_MARGIN + KEY_COUNT * ROW_H))

        # 音符
        for note in self._notes:
            self._paint_note(p, note)
        p.end()

    def _paint_note(self, p: QPainter, note: Note) -> None:
        key_idx = self._keymap.index(note.key) if note.key in self._keymap else -1
        if key_idx < 0:
            return
        x = LEFT_MARGIN + note.beat * PPB + 1
        w = note.duration * PPB - 2
        y = TOP_MARGIN + (KEY_COUNT - 1 - key_idx) * ROW_H + 4
        h = ROW_H - 8
        base = QColor(THEME.pitch_color(key_idx))

        grad = QLinearGradient(x, y, x, y + h)
        if note.type is NoteType.HOLD:
            grad.setColorAt(0, base)
            grad.setColorAt(1, base.darker(170))
        else:
            grad.setColorAt(0, base.lighter(120))
            grad.setColorAt(1, base)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(grad)
        p.drawRoundedRect(QRectF(x, y, w, h), 5, 5)

        # 长按：头部亮条 + 尾部菱形
        if note.type is NoteType.HOLD:
            p.setBrush(QColor(255, 255, 255, 200))
            p.drawRoundedRect(QRectF(x + 2, y + 2, w - 4, 4), 2, 2)
            cx = x + w - 2
            cy = y + h / 2
            p.setBrush(base.lighter(130))
            r = 5.0
            p.drawPolygon(QPolygonF([QPointF(cx, cy - r), QPointF(cx + r, cy),
                                     QPointF(cx, cy + r), QPointF(cx - r, cy)]))
        # 键位字母
        p.setPen(QColor(10, 14, 20))
        p.setFont(QFont(THEME.font_mono, 8, QFont.Weight.Bold))
        p.drawText(QRectF(x, y, w, h), Qt.AlignmentFlag.AlignCenter, note.key)

        # 半音标记：升调 # / 降调 b（右上角）
        if note.accidental != 0:
            mark = "#" if note.accidental > 0 else "b"
            p.setPen(QColor(THEME.secondary))
            p.setFont(QFont(THEME.font_mono, 9, QFont.Weight.Bold))
            p.drawText(QRectF(x + w * 0.5, y, w * 0.5, h * 0.5),
                       Qt.AlignmentFlag.AlignCenter, mark)

        # 选中描边：活动音符（最后点选的）用实线加粗，其余用虚线
        if note in self._selection:
            active = bool(self._selection) and note is self._selection[-1]
            pen = QPen(QColor(THEME.primary), 1.8 if active else 1.2)
            if not active:
                pen.setStyle(Qt.PenStyle.DashLine)
            p.setPen(pen)
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawRoundedRect(QRectF(x - 1, y - 1, w + 2, h + 2), 6, 6)


def _primary_btn(text: str) -> QPushButton:
    b = QPushButton(text)
    b.setStyleSheet(f"""
        QPushButton {{ color: {THEME.background}; font-size: 13px; font-weight: bold;
            background: {THEME.primary}; border: none; border-radius: 8px;
            padding: 9px 16px; }}
        QPushButton:hover {{ background: #33ECFF; }}""")
    b.setCursor(Qt.CursorShape.PointingHandCursor)
    return b


def _ghost_btn(text: str) -> QPushButton:
    b = QPushButton(text)
    b.setStyleSheet(f"""
        QPushButton {{ color: {THEME.text_primary}; font-size: 12px;
            background: {THEME.surface_alt}; border: 1px solid {THEME.border};
            border-radius: 8px; padding: 7px 12px; }}
        QPushButton:hover {{ border-color: {THEME.primary}; color: {THEME.primary}; }}
        QPushButton:disabled {{ color: {THEME.text_secondary};
            border-color: {THEME.surface_alt}; }}""")
    b.setCursor(Qt.CursorShape.PointingHandCursor)
    return b


# ---- 粘贴简谱 ----
# 对话框里的语法提示：用户抄到的是数字，卡住的地方 90% 就在这几行。
JIANPU_HINT = ("1–7 = 音级 · 8 或 1' = 高音 1 · #4 = 升半音 · 3- = 长按 2 拍 · "
               "0 = 休止 · 0.5:4 = 八分音符 · | = 小节线（可省略）")

# 「填入示例」用的《小星星》：公有领域，且大多数人一眼能对上节奏，
# 拿它比对"抄来的谱子对不对"最直观。
EXAMPLE_JIANPU = ("| 1 1 5 5 | 6 6 5- | 4 4 3 3 | 2 2 1- |\n"
                  "| 5 5 4 4 | 3 3 2- | 5 5 4 4 | 3 3 2- |")


class JianpuPasteDialog(QDialog):
    """「粘贴简谱」：把一段数字简谱解析成音符，替换或追加到编辑区。

    EXE 里原本没有简谱解析入口（`jianpu.py` 只挂在开发脚本 `gen_scores.py` 上），
    普通玩家从网上抄到一段 "1 2 3 5 3 2 1" 只能一个音一个音点进卷帘。这个对话框
    做两件事：把文本变成音符；把**识别不了的 token 明确列出来**——解析器对不认识的
    token 是静默跳过的，不列出来用户只会看到"少了个音"，然后一个音一个音去对数。
    """

    def __init__(self, parent: Optional[QWidget] = None, default_name: str = "",
                 default_bpm: int = 90, has_notes: bool = False):
        super().__init__(parent)
        self.setWindowTitle("粘贴简谱")
        self.setMinimumSize(600, 380)

        self.setStyleSheet(f"""
            QDialog {{ background: {THEME.surface}; color: {THEME.text_primary};
                font-family: '{THEME.font_sans}'; }}
            QLineEdit, QSpinBox, QPlainTextEdit {{
                background: {THEME.surface_alt}; color: {THEME.text_primary};
                border: 1px solid {THEME.border}; border-radius: 6px;
                padding: 5px 8px; selection-background-color: {THEME.primary}; }}
            QPlainTextEdit {{ font-family: 'Consolas', 'Courier New', monospace;
                font-size: 13px; }}
            QLabel#hint {{ color: {THEME.text_secondary}; font-size: 11px; }}
            QLabel#bad {{ color: {THEME.danger}; font-size: 11px; }}
            QCheckBox {{ color: {THEME.text_primary}; font-size: 12px; }}""")

        lay = QVBoxLayout(self)
        lay.setContentsMargins(14, 12, 14, 12)
        lay.setSpacing(8)
        lay.addWidget(QLabel("从网上抄来的数字简谱，直接粘进下面这个框：", objectName="hint"))

        self.text_edit = QPlainTextEdit()
        self.text_edit.setPlaceholderText("例如：| 1 1 5 5 | 6 6 5- |")
        self.text_edit.setMinimumHeight(130)
        lay.addWidget(self.text_edit, 1)

        row = QHBoxLayout()
        row.setSpacing(8)
        row.addWidget(QLabel("曲名", objectName="hint"))
        self.name_edit = QLineEdit(default_name or "新曲目")
        self.name_edit.setFixedWidth(190)
        row.addWidget(self.name_edit)
        row.addWidget(QLabel("BPM", objectName="hint"))
        self.bpm_spin = QSpinBox()
        self.bpm_spin.setRange(40, 240)
        self.bpm_spin.setValue(int(default_bpm))
        row.addWidget(self.bpm_spin)
        self.append_cb = QCheckBox("追加到现有内容末尾")
        self.append_cb.setEnabled(bool(has_notes))
        self.append_cb.setToolTip("编辑区还有音符时，可以把这段接在后面"
                                  if has_notes else "编辑区是空的，没有可追加的内容")
        row.addWidget(self.append_cb)
        row.addStretch(1)
        lay.addLayout(row)

        lay.addWidget(QLabel(JIANPU_HINT, objectName="hint"))
        self.preview = QLabel("", objectName="hint")
        self.preview.setWordWrap(True)
        lay.addWidget(self.preview)

        btns = QHBoxLayout()
        btns.setSpacing(8)
        btn_example = _ghost_btn("填入示例")
        btn_example.clicked.connect(lambda: self.text_edit.setPlainText(EXAMPLE_JIANPU))
        btns.addWidget(btn_example)
        btns.addStretch(1)
        btn_cancel = _ghost_btn("取消")
        btn_cancel.clicked.connect(self.reject)
        btns.addWidget(btn_cancel)
        self.btn_ok = _primary_btn("载入编辑区")
        self.btn_ok.clicked.connect(self.accept)
        btns.addWidget(self.btn_ok)
        lay.addLayout(btns)

        # 信号连接放在控件都建好之后：textChanged 会立刻回调 _refresh_preview
        self.text_edit.textChanged.connect(self._refresh_preview)
        self.bpm_spin.valueChanged.connect(self._refresh_preview)
        self._refresh_preview()

    # ---- 实时预检 ----
    def _refresh_preview(self) -> None:
        """边打字边报数：识别了多少音符 / 大约多长 / 哪些 token 认不出来。"""
        text = self.text_edit.toPlainText()
        ok, bad = scan_tokens(text)
        parts = []
        if ok:
            seconds = parse_jianpu(
                text, bpm=float(self.bpm_spin.value())).total_ms() / 1000.0
            parts.append(f"识别 {len(ok)} 个音符")
            parts.append(f"约 {seconds:.0f} 秒")
        else:
            parts.append("还没有可识别的音符")
        if bad:
            uniq = list(dict.fromkeys(bad))
            shown = " ".join(uniq[:6]) + (" …" if len(uniq) > 6 else "")
            parts.append(f"认不出来：{shown}")
        self.preview.setObjectName("bad" if bad else "hint")
        self.preview.setText(" · ".join(parts))
        # 改了 objectName 要重新套一遍样式表，否则颜色不会跟着变
        self.preview.style().unpolish(self.preview)
        self.preview.style().polish(self.preview)
        self.btn_ok.setEnabled(bool(ok))

    # ---- 结果 ----
    def result_score(self) -> Score:
        """按当前输入构造 Score（对话框 accept 之后调用）。"""
        return parse_jianpu(
            self.text_edit.toPlainText(),
            name=self.name_edit.text().strip() or "新曲目",
            bpm=float(self.bpm_spin.value()))

    def append_mode(self) -> bool:
        return self.append_cb.isEnabled() and self.append_cb.isChecked()


class EditorWindow(QWidget):
    """乐谱编辑器主窗口（标准窗框，可自由移动缩放）。"""

    saved = Signal(str)             # score_id
    preview_requested = Signal()    # 试听（不保存，直接在浮窗播放当前编辑内容）

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setWindowTitle("ManboHakimi-Harp 乐谱编辑器")
        self.resize(1040, 460)
        self._source_id = ""

        self.setStyleSheet(f"""
            QWidget {{ background: {THEME.surface}; color: {THEME.text_primary};
                font-family: '{THEME.font_sans}'; }}
            QLineEdit, QSpinBox, QComboBox {{
                background: {THEME.surface_alt}; color: {THEME.text_primary};
                border: 1px solid {THEME.border}; border-radius: 6px;
                padding: 5px 8px; selection-background-color: {THEME.primary}; }}
            QSpinBox::up-button, QSpinBox::down-button {{ width: 16px; }}
            QComboBox QAbstractItemView {{ background: {THEME.surface};
                color: {THEME.text_primary}; selection-background-color: {THEME.primary}; }}
            QScrollArea {{ border: none; background: {THEME.background}; }}
            QScrollBar:horizontal {{ height: 10px; background: transparent; }}
            QScrollBar:vertical {{ width: 10px; background: transparent; }}
            QScrollBar::handle:horizontal, QScrollBar::handle:vertical {{
                background: {THEME.border}; border-radius: 5px; min-width: 40px;
                min-height: 40px; }}
            QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal,
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ width: 0; height: 0; }}
            QLabel#cap {{ color: {THEME.text_secondary}; font-size: 11px; }}
            QLabel#fld {{ color: {THEME.text_secondary}; font-size: 12px; }}""")

        lay = QVBoxLayout(self)
        lay.setContentsMargins(14, 12, 14, 10)
        lay.setSpacing(8)

        # 工具行 1：曲名 / BPM / 吸附 / 试听 / 保存
        head = QHBoxLayout()
        head.setSpacing(10)
        head.addWidget(QLabel("曲名", objectName="fld"))
        self.name_edit = QLineEdit("新曲目")
        self.name_edit.setFixedWidth(200)
        head.addWidget(self.name_edit)

        head.addWidget(QLabel("BPM", objectName="fld"))
        self.bpm_spin = QSpinBox()
        self.bpm_spin.setRange(40, 240)
        self.bpm_spin.setValue(90)
        head.addWidget(self.bpm_spin)

        head.addWidget(QLabel("吸附", objectName="fld"))
        self.snap_box = QComboBox()
        self.snap_box.addItem("1/8 拍（0.5）", 0.5)
        self.snap_box.addItem("1/16 拍（0.25）", 0.25)
        self.snap_box.addItem("整拍（1.0）", 1.0)
        self.snap_box.currentIndexChanged.connect(
            lambda i: self.grid.set_step(self.snap_box.itemData(i)))
        head.addWidget(self.snap_box)

        head.addStretch(1)
        btn_preview = _ghost_btn("试听")
        btn_preview.setStyleSheet(f"""
            QPushButton {{ color: {THEME.primary}; font-size: 13px; font-weight: bold;
                background: transparent; border: 1px solid {THEME.primary};
                border-radius: 8px; padding: 8px 16px; }}
            QPushButton:hover {{ background: rgba(0,229,255,26); }}""")
        btn_preview.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_preview.clicked.connect(self.preview_requested)
        head.addWidget(btn_preview)
        btn_save = _primary_btn("保存并载入")
        btn_save.clicked.connect(lambda: self._save(None))
        head.addWidget(btn_save)
        lay.addLayout(head)

        # 工具行 2：编辑操作
        tools = QHBoxLayout()
        tools.setSpacing(8)
        self.btn_undo = _ghost_btn("撤销")
        self.btn_redo = _ghost_btn("重做")
        self.btn_copy = _ghost_btn("复制")
        self.btn_paste = _ghost_btn("粘贴")
        self.btn_delete = _ghost_btn("删除选中")
        self.btn_clear = _ghost_btn("清空")
        btn_jianpu = _ghost_btn("粘贴简谱")
        btn_jianpu.setToolTip("把从网上抄来的数字简谱直接粘进来（例如 1 2 3 5 3 2 1）")
        btn_import = _ghost_btn("导入 JSON")
        btn_export = _ghost_btn("导出 JSON")
        self.btn_undo.clicked.connect(self._do_undo)
        self.btn_redo.clicked.connect(self._do_redo)
        self.btn_copy.clicked.connect(self.grid_copy)
        self.btn_paste.clicked.connect(self.grid_paste)
        self.btn_delete.clicked.connect(self.grid_delete)
        self.btn_clear.clicked.connect(self.grid_clear)
        btn_jianpu.clicked.connect(self.paste_jianpu)
        btn_import.clicked.connect(self.import_json)
        btn_export.clicked.connect(self.export_json)
        for w in (self.btn_undo, self.btn_redo, self.btn_copy, self.btn_paste,
                  self.btn_delete, self.btn_clear, btn_jianpu, btn_import, btn_export):
            tools.addWidget(w)
        tools.addStretch(1)
        lay.addLayout(tools)

        # 操作说明
        cap = QLabel("左键点空白=新建 · 右拖=拉长（>1拍变长按） · 拖动=移动 · "
                     "拖右缘=调时值 · 右键=删除 · Ctrl/Shift+点=加选", objectName="cap")
        lay.addWidget(cap)

        # 卷帘区
        self.grid = EditorGrid()
        self.grid.changed.connect(self._sync_buttons)
        scroll = QScrollArea()
        scroll.setWidget(self.grid)
        scroll.setWidgetResizable(False)
        lay.addWidget(scroll, 1)

        self._install_shortcuts()
        self._sync_buttons()

    # ---- 快捷键 ----
    def _install_shortcuts(self) -> None:
        """快捷键挂在卷帘网格上（WidgetWithChildrenShortcut）。

        为什么不挂在窗口上：那样焦点在「曲名」输入框里时 Ctrl+V / Ctrl+A
        会被抢走，连贴个曲名都做不到。挂在网格上则两者互不干扰。
        """
        self.grid.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        binds = (
            ("Ctrl+Z", self._do_undo),
            ("Ctrl+Y", self._do_redo),
            ("Ctrl+Shift+Z", self._do_redo),
            ("Ctrl+C", self.grid_copy),
            ("Ctrl+X", self.grid_cut),
            ("Ctrl+V", self.grid_paste),
            ("Ctrl+D", self.grid_duplicate),
            ("Ctrl+A", self.grid_select_all),
            ("Delete", self.grid_delete),
            ("Backspace", self.grid_delete),
            ("Shift+3", self.grid_cycle_accidental),   # # 键：循环升降（自然→升→降）
        )
        for seq, slot in binds:
            sc = QShortcut(QKeySequence(seq), self.grid)
            sc.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
            sc.activated.connect(slot)

    def showEvent(self, e) -> None:  # noqa: N802
        super().showEvent(e)
        self.grid.setFocus(Qt.FocusReason.OtherFocusReason)

    def _sync_buttons(self) -> None:
        self.btn_undo.setEnabled(self.grid.can_undo())
        self.btn_redo.setEnabled(self.grid.can_redo())
        has_sel = bool(self.grid.selection())
        self.btn_copy.setEnabled(has_sel)
        self.btn_delete.setEnabled(has_sel)
        self.btn_paste.setEnabled(self.grid.has_clipboard())
        self.btn_clear.setEnabled(bool(self.grid.notes()))

    # ---- 编辑动作（按钮与快捷键共用） ----
    def _do_undo(self) -> None:
        self.grid.undo()
        self._sync_buttons()

    def _do_redo(self) -> None:
        self.grid.redo()
        self._sync_buttons()

    def grid_copy(self) -> None:
        self.grid.copy()
        self._sync_buttons()

    def grid_cut(self) -> None:
        self.grid.cut()
        self._sync_buttons()

    def grid_paste(self) -> None:
        self.grid.paste()
        self._sync_buttons()

    def grid_duplicate(self) -> None:
        self.grid.duplicate()
        self._sync_buttons()

    def grid_select_all(self) -> None:
        self.grid.select_all()
        self._sync_buttons()

    def grid_delete(self) -> None:
        self.grid.delete_selection()
        self._sync_buttons()

    def grid_cycle_accidental(self) -> None:
        self.grid.cycle_accidental()
        self._sync_buttons()

    def grid_clear(self) -> None:
        if not self.grid.notes():
            return
        if _topmost_message(
                self, "清空编辑区", "确定清空当前所有音符吗？（可以用撤销恢复）",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No) == QMessageBox.StandardButton.Yes:
            self.grid.clear_all()
            self._sync_buttons()

    # ---- 导入 / 导出 ----
    def import_json(self) -> Optional[str]:
        dlg = QFileDialog(self, "导入曲目 JSON", str(data_dir() / "scores"), "ManboHakimi-Harp 曲谱 (*.json)")
        dlg.setFileMode(QFileDialog.FileMode.ExistingFile)
        dlg.setAcceptMode(QFileDialog.AcceptMode.AcceptOpen)
        ok, files = _topmost_file_dialog(dlg)
        if not ok or not files:
            return None
        path = files[0]
        try:
            score = Score.load(path)
        except Exception as e:
            _topmost_message(self, "导入失败", f"无法解析该文件：\n{e}",
                            QMessageBox.StandardButton.Ok,
                            QMessageBox.StandardButton.Ok,
                            QMessageBox.Icon.Warning)
            return None
        score.id = ""                 # 当作新曲目，避免覆盖同名
        self.load_score(score)
        self._sync_buttons()
        return path

    def export_json(self) -> Optional[str]:
        name = self.name_edit.text().strip() or "未命名"
        default = str(data_dir() / "scores" / f"{sanitize_id(name)}.json")
        dlg = QFileDialog(self, "导出曲目 JSON", default, "ManboHakimi-Harp 曲谱 (*.json)")
        dlg.setFileMode(QFileDialog.FileMode.AnyFile)
        dlg.setAcceptMode(QFileDialog.AcceptMode.AcceptSave)
        ok, files = _topmost_file_dialog(dlg)
        if not ok or not files:
            return None
        path = files[0]
        if not path.lower().endswith(".json"):
            path += ".json"
        try:
            self.build_score(sanitize_id(Path(path).stem)).save(path)
        except OSError as e:
            _topmost_message(self, "导出失败", f"写入失败：\n{e}",
                            QMessageBox.StandardButton.Ok,
                            QMessageBox.StandardButton.Ok,
                            QMessageBox.Icon.Warning)
            return None
        print(f"[Editor] 已导出 {path}")
        return path

    # ---- 粘贴简谱 ----
    def paste_jianpu(self) -> Optional[Score]:
        """「粘贴简谱」按钮：弹对话框，确认后把解析结果落到编辑区。"""
        cur_name = self.name_edit.text().strip()
        dlg = JianpuPasteDialog(self, default_name=cur_name or "新曲目",
                                default_bpm=self.bpm_spin.value(),
                                has_notes=bool(self.grid.notes()))
        if _exec_topmost(dlg) != QDialog.DialogCode.Accepted:
            return None
        return self.apply_jianpu(dlg.result_score(), append=dlg.append_mode())

    def apply_jianpu(self, score: Score, append: bool = False) -> Optional[Score]:
        """把解析好的曲目落到编辑区（对话框确认后调用；自检直接调这里）。

        「换曲名 = 存成新曲目」：编辑区在编辑某首曲目时 `_source_id` 就是它的 id，
        保存会覆盖那个文件。粘进一段新谱子却沿用原曲名，多半是"重写这一首"；
        改了曲名则视为新建，否则会把《小星星》的文件内容换成《起风了》。
        """
        if not score.notes:
            return None
        cur_name = self.name_edit.text().strip()
        self.name_edit.setText(score.name)
        self.bpm_spin.setValue(int(round(score.bpm)))
        if not append and score.name != cur_name:
            self._source_id = ""          # 曲名变了 -> 当新曲目，不覆盖原文件
        self.grid.set_notes(score.notes, append=append)
        self._sync_buttons()
        print(f"[Editor] 粘贴简谱：{len(score.notes)} 个音符"
              f"{'（追加）' if append else ''}")
        return score

    # ---- 载入 / 保存 ----
    def load_score(self, score: Score) -> None:
        self._source_id = score.id
        self.name_edit.setText(score.name)
        self.bpm_spin.setValue(int(round(score.bpm)))
        self.grid.load_score(score)

    def build_score(self, score_id: str, preview: bool = False) -> Score:
        """由当前编辑内容构造 Score（不写盘），供试听 / 保存复用。"""
        name = self.name_edit.text().strip() or "未命名"
        return Score(
            id=score_id,
            name=f"试听：{name}" if preview else name,
            bpm=float(self.bpm_spin.value()),
            notes=self.grid.notes())

    def _save(self, folder: Optional[Path] = None) -> str:
        name = self.name_edit.text().strip() or "未命名"
        folder = folder or (data_dir() / "scores")
        folder.mkdir(parents=True, exist_ok=True)
        # 已在编辑某首曲目 -> 沿用它的 id（保存=覆盖自己）；
        # 新曲目 -> 挑一个不撞别人的 id，否则「小星星」和「大星星」的
        # 旧逻辑都会写成 scores/user_song.json，后者静默吃掉前者。
        score_id = self._source_id or unique_score_id(name, folder)
        score = self.build_score(score_id)
        path = folder / f"{score_id}.json"
        score.save(path)
        self._source_id = score_id
        print(f"[Editor] 已保存 {path}")
        self.saved.emit(score_id)
        return score_id
