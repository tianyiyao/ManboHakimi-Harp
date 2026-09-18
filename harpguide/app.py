# -*- coding: utf-8 -*-
"""应用主控制器：组装浮窗 / 设置面板 / 悬浮球 / 热键 / 播放引擎。

唯一的时间驱动源是一个 16ms 的 QTimer（约 60fps）：
引擎只推进"曲目时钟"，UI 每帧查询位置后重绘。全程不产生任何键鼠模拟。
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import List, Optional

from PySide6.QtCore import QObject, QTimer
from PySide6.QtWidgets import QApplication

from .calibration import CalibrationData, resolution_key
from .calibration_panel import CalibrationPanel
from .config import Settings, app_root, data_dir
from .editor import EditorWindow
from .floating_ball import FloatingBall
from .hotkeys import HotkeyFilter
from .keywatch import (HOLD_EARLY_MS, HOLD_LATE_MS, JUDGE_GOOD_MS,
                       MISS_WINDOW_MS, KeyWatcher, judge_offset)
from .models import NoteType, Score, load_scores
from .overlay import OverlayWindow
from .playback import PlaybackEngine
from .risk_dialog import RiskDialog
from .settings_panel import SettingsPanel
from .theme import THEME
from .tray import TrayController

FRAME_MS = 16

# 判定标签 -> 反馈颜色（PERFECT 金 / GREAT 绿 / GOOD 青 / MISS 红）
JUDGE_COLORS = {
    "PERFECT": THEME.gold,
    "GREAT": THEME.success,
    "GOOD": THEME.primary,
    "MISS": THEME.danger,
}


class AppController(QObject):
    def __init__(self, app: QApplication):
        super().__init__(app)
        self.app = app
        self.settings = Settings.load()
        self.scores: List[Score] = self._load_scores()
        if not self.scores:
            self.scores = self._builtin_scores()

        score = self._pick_score(self.settings.last_score_id) or self.scores[0]

        # 引擎与 UI
        self.engine = PlaybackEngine(
            score, speed=self.settings.speed_multiplier,
            loop=self.settings.loop,
            count_in_beats=self.settings.count_in_beats)
        self.engine.reset()

        self.overlay = OverlayWindow(self.settings)
        self.overlay.set_score(score)
        self.overlay.set_speed(self.settings.speed_multiplier)
        self.overlay.set_position_provider(self.engine.position_ms)
        self.overlay.move(self.settings.window_x, self.settings.window_y)
        self.overlay._ensure_on_screen()
        self.overlay.topbar.settings_clicked.connect(self.toggle_settings)
        self.overlay.set_click_through(self.settings.click_through)
        self.overlay.progress.seek_requested.connect(self._seek_ratio)
        # 命中反馈 HUD 显隐跟随设置
        self.overlay.waterfall.set_feedback_enabled(self.settings.hit_feedback)

        # A-B 段落循环
        self._loop_a_ms: Optional[float] = None
        self._loop_b_ms: Optional[float] = None

        # 半音阶口风琴调性档（小键盘 1/2/3 切换）：-1 降调 / 0 自然 / +1 升调
        self._transpose: int = 0
        # 自动变调：跟随歌曲自动切换调性档（小键盘 0 / 设置面板开关）
        self._auto_transpose: bool = self.settings.auto_transpose

        # 命中反馈（判定 / 连击 / 得分）：被动轮询 8 键，不拦截、不模拟输入
        self._key_watcher = KeyWatcher()
        self._combo: int = 0
        self._score: int = 0
        self._judged: set = set()          # 已判定音符在 score.notes 中的下标，避免重复计分/漏音误判
        self._warned: set = set()          # 已报过「抢拍/拖拍 MISS」的音符下标：不消耗音符，只提醒一次
        self._off_hist: List[float] = []   # 最近若干次命中的带符号偏移，用于提示玩家调判定偏移

        # 校准数据（按「物理分辨率 @ 缩放比」分档持久化）
        self.calibration = CalibrationData.load()
        self.calibration.screen_key = resolution_key(self.overlay)
        saved_geoms = self.calibration.profile()
        if saved_geoms:
            self.overlay.apply_calibration(saved_geoms)

        # 校准面板
        self.cal_panel = CalibrationPanel()
        self.cal_panel.scale_requested.connect(self._scale_calibration)
        self.cal_panel.reset_requested.connect(self._reset_calibration)
        self.cal_panel.save_requested.connect(self._save_calibration)
        self.cal_panel.cancel_requested.connect(self._cancel_calibration)
        self.cal_panel.set_profile_key(self.calibration.screen_key)
        self._calibrating = False
        self._cal_was_playing = False
        self._cal_was_clickthrough = False

        # 多显示器：浮窗被拖到另一块屏且该屏缩放/分辨率不同时，自动切换档案。
        # 用帧循环低频轮询而不是 screenChanged 信号——后者在部分 PySide6 版本
        # 的 QWidget 上不暴露，轮询更稳且开销可忽略（约 0.5s 一次）。
        self._screen_check_frames = 0

        # 乐谱编辑器
        self.editor = EditorWindow()
        self.editor.saved.connect(self._on_score_saved)
        self.editor.preview_requested.connect(self._on_editor_preview)

        self.panel = SettingsPanel(self.settings)
        self.overlay.sidebar.set_scores(self.scores, score.id)
        # 曲目侧边栏（左侧悬停抽屉）接管原设置面板里的曲目列表
        self.overlay.sidebar.score_selected.connect(self._select_score)
        self.overlay.sidebar.score_renamed.connect(self._rename_score)
        self.overlay.sidebar.score_deleted.connect(self._delete_score)
        self.overlay.sidebar.edit_requested.connect(self._open_score_in_editor)
        self.panel.speed_changed.connect(self._set_speed)
        self.panel.opacity_changed.connect(self._set_opacity)
        self.panel.waterfall_height_changed.connect(self._set_waterfall_height)
        self.panel.loop_changed.connect(self._set_loop)
        self.panel.click_through_changed.connect(self.overlay.set_click_through)
        self.panel.count_in_changed.connect(self._set_count_in)
        self.panel.preparation_lead_changed.connect(self._set_preparation_lead)
        self.panel.countdown_warning_changed.connect(self._set_countdown_warning)
        self.panel.beat_lines_changed.connect(self._set_beat_lines)
        self.panel.hold_shine_changed.connect(self._set_hold_shine)
        self.panel.lookahead_changed.connect(self._set_lookahead)
        self.panel.loop_range_set.connect(self._panel_set_loop_range)
        self.panel.loop_range_cleared.connect(self._clear_loop_range)
        # 「设 A 点 / 设 B 点」按钮：面板拿不到引擎位置，只发请求，
        # 真正取值在 _panel_set_point 里完成（此前该信号无人连接 = 按钮点了没反应）
        self.panel.set_current_point_requested.connect(self._panel_set_point)
        self.panel.lyrics_changed.connect(self._set_show_lyrics)
        self.panel.hotkeys_hint_changed.connect(self._set_hotkeys_hint)
        self.panel.auto_transpose_changed.connect(self._set_auto_transpose)
        self.panel.hit_feedback_changed.connect(self._set_hit_feedback)
        self.panel.judge_offset_changed.connect(self._set_judge_offset)
        self.overlay.resized.connect(self._on_overlay_resized)

        self.ball = FloatingBall()
        self.ball.expand_requested.connect(self.show_overlay_mode)
        self.ball.hide()

        # 热键（Windows）
        self.hotkeys = HotkeyFilter()
        self.app.installNativeEventFilter(self.hotkeys)
        self.hotkeys.triggered.connect(self._on_hotkey)
        self.hotkeys.register_all()
        if self.hotkeys.failed:
            self.panel.set_hotkey_warning(self.hotkeys.failed_labels())

        # 系统托盘（Windows 任务栏右下角）：右键菜单退出/设置等
        self.tray = TrayController(self)
        from PySide6.QtGui import QIcon as _QI
        from .config import app_root as _app_root
        icon = _QI(str(_app_root() / "assets" / "icon.ico"))
        if not self.tray.install(icon, tooltip="ManboHakimi-Harp · 口风琴练习"):
            print("[Tray] 当前环境无可用托盘，回退到仅浮窗模式")
        self.tray.toggle_visible_requested.connect(self.toggle_visible)
        self.tray.open_settings_requested.connect(self.toggle_settings)
        self.tray.toggle_playback_requested.connect(self._tray_toggle_playback)
        self.tray.reset_requested.connect(self._reset_all)
        self.tray.open_calibration_requested.connect(self.toggle_calibration)
        self.tray.open_editor_requested.connect(self.toggle_editor)
        self.tray.quit_requested.connect(self.shutdown)
        # 引擎播放状态 → 托盘菜单"开始/暂停"勾选同步
        self.engine.state_changed.connect(self.tray.set_playing)

        # 帧驱动
        self._frame_timer = QTimer(self)
        self._frame_timer.setInterval(FRAME_MS)
        self._frame_timer.timeout.connect(self._tick)
        self._frame_timer.start()
        self._clock_ms = 0.0

        self._hidden = False
        self._hidden_restore: List = []   # 隐藏前正在显示的窗口，恢复时精确还原
        self._ball_mode = False

        # 恢复上次为该曲目设置的 A-B 区间
        self._restore_loop_range(score)
        self.panel.set_loop_status(*self._loop_status())

    # ---- 曲目 ----
    def _load_scores(self) -> List[Score]:
        """合并加载：EXE 同级 scores/（用户曲目优先）+ 打包内建 scores（同名 id 去重）。

        顺序规则是「**先到先得**」：用户目录排在前面，所以同名时用户曲目胜出。
        旧实现是后到的覆盖先到的，与注释声称的"用户目录同名曲目覆盖内置"正好相反——
        开发态两个目录其实是同一个（data_dir() == app_root()），所以问题被掩盖了；
        打包成 EXE 后用户目录是 EXE 同级、内建在 _MEIPASS 里，于是**用户在编辑器里
        改过并保存的同名曲目，每次启动都会被内置版本顶掉**。

        `builtin` 标记只在「内建目录确实不是用户目录」时才置位，供侧边栏把
        重命名 / 删除置灰（EXE 内部的文件改不了）。
        """
        user_scores_dir = data_dir() / "scores"
        candidates: List[tuple] = [(user_scores_dir, False)]
        if getattr(sys, "frozen", False):
            meipass = Path(getattr(sys, "_MEIPASS", ""))
            candidates.append((meipass / "scores", True))
        else:
            candidates.append((app_root() / "scores", True))
        merged: dict = {}
        order: List[str] = []
        for folder, is_builtin_dir in candidates:
            for s in load_scores(folder):
                if s.id in merged:
                    continue                       # 先到先得：用户目录优先
                s.builtin = bool(is_builtin_dir and folder != user_scores_dir)
                order.append(s.id)
                merged[s.id] = s
        return [merged[i] for i in order]

    @staticmethod
    def _builtin_scores() -> List[Score]:
        """内置演示曲目（scores 目录丢失时的兜底）。"""
        from .jianpu import parse_jianpu
        return [
            parse_jianpu(
                "| 1 1 5 5 6 6 5- | 4 4 3 3 2 2 1- | "
                "| 5 5 4 4 3 3 2- | 5 5 4 4 3 3 2- | "
                "| 1 1 5 5 6 6 5- | 4 4 3 3 2 2 1- |",
                name="小星星（演示）", bpm=90, score_id="twinkle"),
        ]

    def _pick_score(self, score_id: str) -> Optional[Score]:
        for s in self.scores:
            if s.id == score_id:
                return s
        return None

    def _select_score(self, score_id: str) -> None:
        score = self._pick_score(score_id)
        if not score:
            return
        self.settings.last_score_id = score_id
        self.settings.save()
        self._loop_a_ms = None
        self._loop_b_ms = None
        self.engine.set_score(score)
        self.overlay.set_score(score)
        self._reset_feedback(self.engine.position_ms())
        self.overlay.set_loop_range(None, None)
        self._restore_loop_range(score)
        self.overlay.sidebar.set_scores(self.scores, score_id)
        self.panel.set_loop_status(*self._loop_status())

    # ---- 设置项 ----
    def _set_speed(self, v: float) -> None:
        """变速时保持当前位置与播放状态（修复：原先会误暂停）。"""
        was_playing = self.engine.playing
        pos = self.engine.position_ms()
        self.engine.speed = v
        self.settings.speed_multiplier = v
        self.overlay.set_speed(v)
        self.engine.pause()
        self.engine.seek(pos)
        if was_playing:
            self.engine.play()

    def _set_opacity(self, v: float) -> None:
        self.settings.opacity = v
        self.overlay.update()

    def _set_waterfall_height(self, v: int) -> None:
        self.overlay.set_waterfall_height(v)

    def _set_show_lyrics(self, v: bool) -> None:
        self.settings.show_lyrics = v
        self.overlay.apply_settings()
        self.settings.save()

    def _set_hotkeys_hint(self, v: bool) -> None:
        """底部热键提示条开关。"""
        self.overlay.set_hotkeys_visible(v)
        self.settings.save()
        print(f"[HintBar] 底部热键提示 {'开启' if v else '关闭'}")

    def _on_overlay_resized(self, w: int, h: int) -> None:
        """用户拖拽调整浮窗大小后：同步设置面板的瀑布流高度滑杆。"""
        self.panel.sync_height_slider(self.settings.waterfall_height)

    def _set_loop(self, v: bool) -> None:
        self.engine.loop = v
        self.settings.loop = v

    def _set_count_in(self, v: int) -> None:
        self.engine.count_in_beats = v
        self.settings.count_in_beats = v
        self.engine.reset()
        self._reset_feedback(self.engine.position_ms())

    def _set_preparation_lead(self, v: float) -> None:
        self.settings.preparation_lead_beats = v

    def _set_countdown_warning(self, v: bool) -> None:
        self.settings.countdown_warning = v
        self.overlay.waterfall.update()

    def _set_beat_lines(self, v: bool) -> None:
        self.settings.show_beat_lines = v
        self.overlay.waterfall.update()

    def _set_hold_shine(self, v: bool) -> None:
        self.settings.hold_shine = v
        self.overlay.waterfall.update()

    def _set_lookahead(self, v: int) -> None:
        self.settings.lookahead_ms = v
        self.overlay.waterfall.update()

    # ---- A-B 段落循环 ----
    def _loop_status(self) -> tuple:
        """返回 (A 拍, B 拍) 或 (None, None)。"""
        bpm = self.engine.score.bpm
        a = None if self._loop_a_ms is None else self._loop_a_ms * bpm / 60000.0
        b = None if self._loop_b_ms is None else self._loop_b_ms * bpm / 60000.0
        return (a, b)

    def _refresh_loop_marks(self) -> None:
        self.overlay.set_loop_range(self._loop_a_ms, self._loop_b_ms)

    def _seek_ratio(self, ratio: float) -> None:
        """进度条点击/拖动：按比例跳转（保持播放状态）。"""
        total = self.engine.total_ms()
        if total <= 0:
            return
        self.engine.seek(ratio * total)
        self._sync_judged(ratio * total)   # 跳转后旧音符不再算漏音

    def _mark_loop_a(self) -> None:
        """把当前位置设为循环 A 点。"""
        pos = self.engine.position_ms()
        if pos < 0:                       # 预备拍期间视为 0
            pos = 0.0
        self._loop_a_ms = pos
        # A 点越过 B 点则丢弃旧 B 点
        if self._loop_b_ms is not None and self._loop_b_ms <= self._loop_a_ms:
            self._loop_b_ms = None
            self.engine.clear_loop_range()
        self._apply_loop_range()
        print(f"[Loop] A = {pos:.0f}ms")

    def _mark_loop_b(self) -> None:
        """B 点：首次按下设为 B 点并开启循环，已开启时再按则清除。"""
        if self.engine.has_loop_range:
            self._clear_loop_range()
            return
        self._set_loop_b_at_current()

    def _set_loop_b_at_current(self) -> None:
        """无条件把当前位置设为 B 点（面板按钮用，不切换清除）。"""
        pos = max(self.engine.position_ms(), 0.0)
        if self._loop_a_ms is None:
            # 没有 A 点：以曲首为 A，便于快速圈定一段
            self._loop_a_ms = 0.0
        self._loop_b_ms = pos
        self._apply_loop_range()
        print(f"[Loop] B = {pos:.0f}ms")

    def _panel_set_point(self, which: str) -> None:
        if which == "a":
            self._mark_loop_a()
        else:
            self._set_loop_b_at_current()

    def _apply_loop_range(self) -> None:
        if self._loop_a_ms is None or self._loop_b_ms is None:
            self._refresh_loop_marks()
            self.panel.set_loop_status(*self._loop_status())
            return
        ok = self.engine.set_loop_range(self._loop_a_ms, self._loop_b_ms)
        if not ok:
            self._loop_b_ms = None
            self.engine.clear_loop_range()
        self._refresh_loop_marks()
        self._persist_loop_range()
        self.panel.set_loop_status(*self._loop_status())

    def _clear_loop_range(self) -> None:
        self._loop_a_ms = None
        self._loop_b_ms = None
        self.engine.clear_loop_range()
        self._refresh_loop_marks()
        self._persist_loop_range()
        self.panel.set_loop_status(None, None)
        print("[Loop] A-B 区间已清除")

    def _panel_set_loop_range(self, a_beat: float, b_beat: float) -> None:
        """面板直接输入拍数设置区间。"""
        bpm = self.engine.score.bpm
        a_ms, b_ms = a_beat * 60000.0 / bpm, b_beat * 60000.0 / bpm
        self._loop_a_ms, self._loop_b_ms = a_ms, b_ms
        self._apply_loop_range()

    def _persist_loop_range(self) -> None:
        """按曲目持久化 A-B 区间（单位：拍）。"""
        sid = self.engine.score.id
        a, b = self._loop_status()
        if a is None or b is None:
            self.settings.loop_ranges.pop(sid, None)
        else:
            self.settings.loop_ranges[sid] = [round(a, 3), round(b, 3)]
        self.settings.save()

    def _restore_loop_range(self, score: Score) -> None:
        raw = self.settings.loop_ranges.get(score.id)
        if not raw or len(raw) != 2:
            return
        a_ms = float(raw[0]) * 60000.0 / score.bpm
        b_ms = float(raw[1]) * 60000.0 / score.bpm
        self._loop_a_ms, self._loop_b_ms = a_ms, b_ms
        self._apply_loop_range()

    # ---- 曲目管理 ----
    def _rename_score(self, score_id: str, new_name: str) -> None:
        from .editor import sanitize_id, unique_score_id
        score = self._pick_score(score_id)
        if not score or not new_name.strip():
            return
        new_name = new_name.strip()
        scores_dir = data_dir() / "scores"
        old_path = scores_dir / f"{score_id}.json"
        # 内置曲目只读：文件在 EXE 内部（_MEIPASS）或安装目录，删不掉也改不了。
        # 旧逻辑仍然往用户目录写一份新文件，于是原曲目还在 -> 列表里出现两条
        # 名字不同的"同一首歌"。这里直接拒绝，由侧边栏把菜单项置灰并说明原因。
        if getattr(score, "builtin", False) or not old_path.exists():
            print(f"[Score] 内置曲目只读，不能重命名: {score_id}")
            return
        new_id = sanitize_id(new_name)
        new_path = scores_dir / f"{new_id}.json"
        if new_id != score_id and new_path.exists():
            # 撞上别人的曲目文件：另挑一个 id，绝不覆盖
            new_id = unique_score_id(new_name, scores_dir)
            new_path = scores_dir / f"{new_id}.json"
        score.name = new_name
        score.id = new_id
        try:
            if old_path != new_path:
                old_path.unlink()
            score.save(new_path)
        except OSError as e:
            print(f"[Score] 重命名失败: {e}")
            return
        self.settings.last_score_id = new_id
        if score_id in self.settings.loop_ranges:
            self.settings.loop_ranges[new_id] = self.settings.loop_ranges.pop(score_id)
        self.settings.save()
        self.scores = self._load_scores()
        self._select_score(new_id)
        print(f"[Score] 已重命名为 {new_name}")

    def _delete_score(self, score_id: str) -> None:
        score = self._pick_score(score_id)
        path = data_dir() / "scores" / f"{score_id}.json"
        if (score is not None and getattr(score, "builtin", False)) or not path.exists():
            print(f"[Score] 内置曲目不可删除: {score_id}")
            return
        try:
            path.unlink()
        except OSError as e:
            print(f"[Score] 删除失败: {e}")
            return
        self.settings.loop_ranges.pop(score_id, None)
        self.scores = self._load_scores()
        self._clear_loop_range()
        if self.scores:
            self._select_score(self.scores[0].id)
        else:
            # 用户删空了所有可删曲目（内置不可删，所以理论上不会到这）：
            # 兜底注入一首内置演示曲，避免后面 self.scores[0] 崩。
            self.scores = self._builtin_scores()
            self._select_score(self.scores[0].id)
        print(f"[Score] 已删除 {score_id}")

    # ---- 热键 ----
    def _on_hotkey(self, name: str) -> None:
        # 隐藏模式下不允许改变播放状态（否则按下播放却看不到浮窗进度）。
        if self._hidden and name in (
            "toggle_playback", "reset", "mark_loop_a", "mark_loop_b",
        ):
            return
        if name == "toggle_playback":
            self.engine.toggle()
        elif name == "reset":
            self.engine.reset()
            self._reset_feedback(self.engine.position_ms())
        elif name == "toggle_visible":
            self.toggle_visible()
        elif name == "toggle_ball":
            self.toggle_ball()
        elif name == "mark_loop_a":
            self._mark_loop_a()
        elif name == "mark_loop_b":
            self._mark_loop_b()
        elif name == "toggle_clickthrough":
            self.overlay.set_click_through(not self.overlay.click_through)
            self.panel.click_cb.setChecked(self.overlay.click_through)
        elif name == "toggle_calibration":
            self.toggle_calibration()
        elif name == "toggle_editor":
            self.toggle_editor()
        elif name == "quit":
            self.shutdown()
        elif name == "transpose_down":
            self._set_transpose(-1)
        elif name == "transpose_natural":
            self._set_transpose(0)
        elif name == "transpose_up":
            self._set_transpose(1)
        elif name == "toggle_auto_transpose":
            self._set_auto_transpose(not self._auto_transpose)
        elif name == "judge_offset_down":
            self._nudge_judge_offset(-20)
        elif name == "judge_offset_zero":
            self._set_judge_offset(0)
        elif name == "judge_offset_up":
            self._nudge_judge_offset(20)

    # ---- 半音阶调性 ----
    def _set_transpose(self, v: int) -> None:
        """手动切调（小键盘 1/2/3）：会自动退出自动变调模式。"""
        if self._auto_transpose:
            self._set_auto_transpose(False)
        self._transpose = v
        required = self._current_required_transpose(self.engine.position_ms())
        self.overlay.set_transpose(v, required, auto=False)

    def _set_auto_transpose(self, v: bool) -> None:
        """切换自动变调：开启后调性档自动跟随歌曲，关闭后回到手动切调。"""
        self._auto_transpose = v
        self.settings.auto_transpose = v
        self.settings.save()
        if v:
            # 开启时立即同步到当前所需档，消除手动切换空档
            self._transpose = self._current_required_transpose(self.engine.position_ms())
        # 同步设置面板复选框（热键切开关时面板也要一致）
        cb = getattr(self.panel, "auto_transpose_cb", None)
        if cb is not None:
            cb.blockSignals(True)
            cb.setChecked(v)
            cb.blockSignals(False)
        print(f"[Transpose] 自动变调 {'开启' if v else '关闭'}")

    def _current_required_transpose(self, pos: float) -> int:
        """当前播放位置需要的调性档：取活跃音符，否则未来 1 拍内的音符。"""
        score = self.engine.score
        bpm = score.bpm
        beat_ms = 60000.0 / bpm
        for note in score.notes:
            if note.type is NoteType.REST:
                continue
            if note.start_ms(bpm) <= pos < note.end_ms(bpm):
                return note.accidental
        for note in score.notes:
            if note.type is NoteType.REST:
                continue
            if note.start_ms(bpm) > pos and note.start_ms(bpm) - pos <= beat_ms:
                return note.accidental
        return 0

    # ---- 命中反馈（判定 / 连击 / 得分） ----
    def _set_hit_feedback(self, v: bool) -> None:
        self.settings.hit_feedback = v
        self.settings.save()
        self._key_watcher.reset()
        self.overlay.waterfall.set_feedback_enabled(v)
        if not v:
            self.overlay.keys.clear_feedback()
        self._reset_feedback(self.engine.position_ms())
        print(f"[Feedback] 命中反馈 {'开启' if v else '关闭'}")

    def _set_judge_offset(self, v: int) -> None:
        """判定偏移（ms）：正值补偿「整体按晚」，负值补偿「整体按早」。

        改变后旧的偏移统计不再有意义，清掉让顶栏重新累积。
        """
        v = max(-600, min(600, int(v)))
        if v == int(getattr(self.settings, "judge_offset_ms", 0) or 0):
            return
        self.settings.judge_offset_ms = v
        self.settings.save()
        self._off_hist.clear()
        self.overlay.set_judge_offset(None)
        self.panel.sync_offset_slider(v)
        print(f"[Feedback] 判定偏移 {v:+d}ms")

    def _nudge_judge_offset(self, delta: int) -> None:
        cur = int(getattr(self.settings, "judge_offset_ms", 0) or 0)
        self._set_judge_offset(cur + delta)

    def _reset_feedback(self, pos: float = 0.0) -> None:
        self._combo = 0
        self._score = 0
        self._judged.clear()
        self._warned.clear()
        self._off_hist.clear()
        self._key_watcher.reset()
        self.overlay.waterfall.clear_feedback()
        self.overlay.keys.clear_feedback()
        self.overlay.set_judge_offset(None)
        self._sync_judged(pos)

    def _reset_all(self) -> None:
        """重置播放位置 + 清空命中反馈（托盘菜单"重置"用）。"""
        self.engine.reset()
        self._reset_feedback(self.engine.position_ms())

    def _jpos(self, pos: float) -> float:
        """判定用的"校准后曲目时间"。

        `judge_offset_ms` 正值表示玩家习惯性偏晚按，把基准一起后移即可对齐。
        """
        try:
            off = float(getattr(self.settings, "judge_offset_ms", 0) or 0)
        except (TypeError, ValueError):
            off = 0.0
        return pos - off

    def _sync_judged(self, pos: float) -> None:
        """把当前位置之前（已经完全滑过判定线）的音符标记为已判定。

        用于重置 / 跳转 / 切曲后，避免它们被当成"漏音"瞬间刷一堆 MISS。
        """
        score = self.engine.score
        bpm = score.bpm
        jpos = self._jpos(pos)
        for i, n in enumerate(score.notes):
            if n.type is NoteType.REST:
                continue
            if n.start_ms(bpm) < jpos - MISS_WINDOW_MS:
                self._judged.add(i)

    def _process_hits(self, pos: float, pressed: Optional[List[str]] = None,
                      held: Optional[set] = None) -> None:
        """每帧调用：判定本帧按键 -> 长按按住判定 -> 漏音检测。

        `pressed` / `held` 由 `_tick` 传入（每帧只轮询一次键盘）；单独调用时自行轮询。
        """
        if pressed is None:
            pressed, held = self._key_watcher.poll()
        if not self.settings.hit_feedback:
            return
        jpos = self._jpos(pos)
        # 1) 本帧新按下的键：短按判定 / 长按起音
        for key in pressed:
            self._on_key_hit(key, jpos)
        score = self.engine.score
        bpm = score.bpm
        held = held or set()
        # 2) 长按按住判定 + 漏音检测（合并成一次遍历）
        for i, n in enumerate(score.notes):
            if n.type is NoteType.REST or i in self._judged:
                continue
            start = n.start_ms(bpm)
            if (n.type is NoteType.HOLD and n.key in held
                    and start - HOLD_EARLY_MS <= jpos <= n.end_ms(bpm) + HOLD_LATE_MS):
                # 长音：键正被按住且与音符区间有重叠 -> 命中。
                # 提前压住是长音的正确手法，不该被罚，因此偏移下限钳到 0（=PERFECT）；
                # 上限钳到 GOOD 窗口——晚压住的长音至少算 GOOD，不判 MISS。
                self._judged.add(i)
                off = min(max(jpos - start, 0.0), JUDGE_GOOD_MS)
                self._apply_judgment(score.key_index(n.key), off)
                continue
            # 漏音：起点过了窗口仍未被按下 -> MISS
            if start + MISS_WINDOW_MS < jpos:
                self._judged.add(i)
                self._register_miss(score.key_index(n.key))

    def _on_key_hit(self, key: str, pos: float) -> None:
        """处理一次按键边沿（短按判定 / 长按起音）。"""
        score = self.engine.score
        col = score.key_index(key)
        if col < 0:
            return
        bpm = score.bpm
        # 找该列最近的、还没判定的音符。
        # 注意：`_judged` 存的是「音符在 score.notes 里的下标」而不是 id(note)。
        # 用 id() 会踩 CPython 地址复用：换曲（编辑器试听 / 切歌）后新音符可能
        # 拿到已释放旧音符的地址，被误判成"已判定"，于是玩家按对了却被匹配到
        # 更后面的音符 -> 莫名其妙 MISS。
        best_i = -1
        best_off = 0.0
        for i, n in enumerate(score.notes):
            if n.key != key or n.type is NoteType.REST or i in self._judged:
                continue
            off = pos - n.start_ms(bpm)
            if abs(off) <= MISS_WINDOW_MS and (best_i < 0 or abs(off) < abs(best_off)):
                best_i, best_off = i, off
        if best_i < 0:
            # 该列附近根本没有音符 -> 空按。
            # 练习工具里试键、摸键位是常态，静默忽略：不判 MISS，也不断连击。
            return
        if abs(best_off) <= JUDGE_GOOD_MS:
            self._judged.add(best_i)
            self._apply_judgment(col, best_off)
            return
        # 抢拍 / 拖拍宽容带：玩家的确在打这个音符，只是时机偏了。
        # 记一次 MISS 提醒，但**不消耗该音符** —— 玩家可以在窗口内重按救回来。
        # 同一个音符只提醒一次，避免连按刷屏。
        if best_i not in self._warned:
            self._warned.add(best_i)
            self._register_miss(col)

    def _apply_judgment(self, col: int, off: float) -> None:
        """按偏移给出判定，并推送连击 / 得分 / 浮层 / 琴键光环。"""
        label, points = judge_offset(off)
        if label == "MISS":
            self._combo = 0
        else:
            self._combo += 1
            # 连击奖励：连得越多，单次加分越多
            self._score += points + max(0, self._combo - 1) * 2
        self._record_offset(off)
        color = JUDGE_COLORS.get(label, THEME.danger)
        self.overlay.waterfall.push_judgment(col, label, color)
        self.overlay.keys.flash_hit(col, color)
        self.overlay.waterfall.set_combo(self._combo, self._score)

    def _record_offset(self, off: float) -> None:
        """记录本次命中的带符号偏移，并在顶栏给出「最近平均偏移」提示。"""
        self._off_hist.append(float(off))
        if len(self._off_hist) > 24:
            del self._off_hist[:-24]
        if len(self._off_hist) < 4:
            return
        avg = sum(self._off_hist) / len(self._off_hist)
        self.overlay.set_judge_offset(avg, len(self._off_hist))

    def _register_miss(self, col: int) -> None:
        if col < 0:
            return
        self._combo = 0
        self.overlay.waterfall.push_judgment(col, "MISS", THEME.danger)
        self.overlay.keys.flash_hit(col, THEME.danger)
        self.overlay.waterfall.set_combo(self._combo, self._score)

    # ---- 模式切换 ----
    def toggle_settings(self) -> None:
        if self.panel.isVisible():
            self.panel.hide()
        else:
            self.panel.move_beside(self.overlay.pos())
            self.panel.show()

    def toggle_visible(self) -> None:
        """切换浮窗显隐（F2 热键 / 托盘菜单）。

        隐藏前记下"当时谁在显示"，恢复时按记录精确还原。旧实现固定 show
        三件套，于是悬浮球模式下「隐藏 -> 再显示」会把完整浮窗一起弹出来
        （球和窗同屏，且浮窗盖住球）。
        """
        if self._hidden:
            self._hidden = False
            self._hidden_restore = getattr(self, "_hidden_restore", None)
            targets = self._hidden_restore or [self.overlay]
            for w in targets:
                w.show()
            return
        self._hidden_restore = [w for w in (self.overlay, self.panel, self.ball)
                                if w.isVisible()]
        self._hidden = True
        for w in (self.overlay, self.panel, self.ball):
            w.hide()

    def toggle_ball(self) -> None:
        if self._ball_mode:
            self.show_overlay_mode()
        else:
            self._ball_mode = True
            self.overlay.hide()
            self.panel.hide()
            self.ball.show()

    def show_overlay_mode(self) -> None:
        self._ball_mode = False
        self.ball.hide()
        self.overlay.show()

    # ---- 校准模式 ----
    def _refresh_calibration_screen(self) -> None:
        """跟随浮窗所在屏幕切换校准档案。

        屏幕换了（分辨率或缩放比不同）就重新套用对应档案，
        没有对应档案则回到默认网格，避免套用另一块屏的像素偏移。
        """
        key = resolution_key(self.overlay)
        if key == self.calibration.screen_key:
            return
        self.calibration.screen_key = key
        self.cal_panel.set_profile_key(key)
        self.overlay.apply_calibration(self.calibration.profile())
        print(f"[Calibration] 切换档案: {key}")

    def toggle_calibration(self) -> None:
        """Ctrl+Shift+C：进入校准 / 已在校准时保存并退出。"""
        if self._calibrating:
            self._save_calibration()
        else:
            self._enter_calibration()

    def _enter_calibration(self) -> None:
        self._calibrating = True
        # 进入时再对一次屏幕（用户可能刚把浮窗拖到另一块屏）
        self._refresh_calibration_screen()
        # 暂停播放，记住状态
        self._cal_was_playing = self.engine.playing
        self.engine.pause()
        # 关闭鼠标穿透以便拖动琴键
        self._cal_was_clickthrough = self.overlay.click_through
        if self.overlay.click_through:
            self.overlay.set_click_through(False)
        # 确保浮窗可见（悬浮球模式则切回完整模式）
        self.show_overlay_mode()
        self.overlay.waterfall.set_calibration_preview(True)
        self.overlay.keys.set_calibrating(True)
        self.panel.hide()
        # 校准时琴键要拖到左边缘，抽屉会挡住第一键，先撤下
        self.overlay.set_sidebar_enabled(False)
        self.cal_panel.move_beside(self.overlay.pos())
        self.cal_panel.show()
        print("[Calibration] 进入校准模式")

    def _exit_calibration(self) -> None:
        self._calibrating = False
        self.overlay.keys.set_calibrating(False)
        self.overlay.waterfall.set_calibration_preview(False)
        self.cal_panel.hide()
        self.overlay.set_sidebar_enabled(not self.overlay.click_through)
        # 恢复鼠标穿透
        if self._cal_was_clickthrough:
            self.overlay.set_click_through(True)
            self.panel.click_cb.setChecked(True)
        print("[Calibration] 退出校准模式")

    def _save_calibration(self) -> None:
        geoms = self.overlay.keys.geometries()
        if geoms is None:
            # 用户全部重置回默认网格：删除该分辨率的方案
            self.calibration.clear_profile()
        else:
            self.calibration.set_profile(geoms)
        self.calibration.save()
        self._exit_calibration()

    def _cancel_calibration(self) -> None:
        # 放弃修改：恢复磁盘上的方案（或默认网格）
        saved = CalibrationData.load().profile()
        self.overlay.apply_calibration(saved)
        self._exit_calibration()

    def _reset_calibration(self) -> None:
        # 重置为默认网格（仍处于校准模式，可继续微调）
        self.overlay.keys.reset_to_default()

    def _scale_calibration(self, factor: float) -> None:
        self.overlay.keys.scale_all(factor)

    # ---- 乐谱编辑器 ----
    def toggle_editor(self) -> None:
        """Ctrl+Shift+E：打开 / 收起乐谱编辑器。"""
        if self.editor.isVisible():
            self.editor.hide()
        else:
            # 打开时载入当前曲目作为编辑底稿
            self.editor.load_score(self.engine.score)
            self.editor.show()
            self.editor.raise_()
            self.editor.activateWindow()

    def _on_score_saved(self, score_id: str) -> None:
        """编辑器保存后：重新加载曲目列表并切换到新曲目。"""
        self.scores = self._load_scores()
        self._select_score(score_id)

    def _open_score_in_editor(self, score_id: str) -> None:
        """从设置面板右键菜单：切到该曲目并打开编辑器编辑。"""
        score = self._pick_score(score_id)
        if not score:
            return
        self._select_score(score_id)
        self.editor.load_score(score)
        self.editor.show()
        self.editor.raise_()
        self.editor.activateWindow()

    def _on_editor_preview(self) -> None:
        """试听：把编辑中的内容（未保存）直接载入浮窗播放；再按暂停。"""
        if self.engine.score.id == "__preview__" and self.engine.playing:
            self.engine.pause()
            return
        score = self.editor.build_score("__preview__", preview=True)
        if not score.notes:
            print("[Editor] 试听忽略：编辑区没有音符")
            return
        self.engine.set_score(score)
        self.overlay.set_score(score)
        self.engine.reset()
        # 换了一套音符必须清空判定状态：否则旧曲的「已判定下标」会套用到
        # 试听曲上（下标含义完全不同），造成漏判 / 误判 MISS。
        self._reset_feedback(self.engine.position_ms())
        self.engine.play()
        self.show_overlay_mode()

    # ---- 帧循环 ----
    def _tick(self) -> None:
        self._clock_ms += FRAME_MS
        pos = self.engine.position_ms()
        total = self.engine.total_ms()

        # 低频检查屏幕变化（多显示器 / 缩放比切换）
        self._screen_check_frames += 1
        if self._screen_check_frames >= 30:
            self._screen_check_frames = 0
            if not self._calibrating:
                self._refresh_calibration_screen()

        # 命中反馈：注入真实时钟（动画用）+ 播放中被动轮询 8 键做判定
        self.overlay.waterfall.set_real_ms(self._clock_ms)
        # 每帧都轮询一次键盘：暂停/预备拍期间按住不放，恢复时不会被误当成"新按下"
        pressed, held = self._key_watcher.poll()
        if (self.settings.hit_feedback and self.engine.playing
                and self.overlay.isVisible()):
            self._process_hits(pos, pressed, held)

        if self.overlay.isVisible():
            self.overlay.waterfall.set_playing(self.engine.playing)
            self.overlay.keys.tick(pos, self._clock_ms)
            self.overlay.update_time(pos, total)
            required = self._current_required_transpose(pos)
            if self._auto_transpose:
                self._transpose = required   # 自动跟随歌曲调性档
            self.overlay.set_transpose(
                self._transpose, required, auto=self._auto_transpose)
            self.overlay.waterfall.update()
        if self.ball.isVisible():
            self.ball.set_playing(self.engine.playing)
            self.ball.set_note_char(self._current_key_char(pos))
            self.ball.tick(self._clock_ms)

    def _current_key_char(self, pos: float) -> Optional[str]:
        score = self.engine.score
        for note in score.notes:
            if note.type is NoteType.REST:
                continue
            if note.start_ms(score.bpm) <= pos < note.end_ms(score.bpm):
                return note.key if note.key != "," else ","
        return None

    # ---- 生命周期 ----
    def start(self) -> None:
        # 首次启动：风险声明
        if not self.settings.risk_accepted:
            dlg = RiskDialog()
            if dlg.exec() != RiskDialog.DialogCode.Accepted:
                self.app.quit()
                raise SystemExit(0)
            self.settings.risk_accepted = True
            self.settings.save()
        self.overlay.show()

    def shutdown(self) -> None:
        # 停帧驱动、撤销所有热键注册、保存当前设置
        if hasattr(self, "_frame_timer") and self._frame_timer.isActive():
            self._frame_timer.stop()
        self.hotkeys.unregister_all()
        if hasattr(self, "tray"):
            self.tray.shutdown()
        self.settings.save()
        self.app.quit()

    # ---- 托盘辅助 ----
    def _tray_toggle_playback(self) -> None:
        """从托盘点"开始/暂停"：先恢复完整可见模式，再切引擎状态。

        避免点托盘后用户看不到进度（hidden / 悬浮球 模式下按 F1 已修过）。
        """
        if self._hidden:
            self.toggle_visible()
        if self._ball_mode:
            self.show_overlay_mode()
        self.engine.toggle()
