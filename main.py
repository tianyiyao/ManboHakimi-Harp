# -*- coding: utf-8 -*-
"""ManboHakimi-Harp 入口。

用法：
    python main.py             启动浮窗
    python main.py --selftest  离屏自检（不弹窗，验证核心逻辑后退出）
"""
from __future__ import annotations

import sys

from PySide6.QtWidgets import QApplication


def _configure_high_dpi() -> None:
    """在创建 QApplication 之前确定高 DPI 策略（必须提前调用）。

    采用 PassThrough：125% / 150% 这类分数缩放在 Qt 里如实表现为
    1.25 / 1.5，而不会被四舍五入成 1 或 2。这样有两个好处：

    1. 浮窗与游戏内键位的相对比例在各缩放档位下是可预期的；
    2. 校准档案按「物理分辨率 @ devicePixelRatio」分档保存
       （见 calibration.resolution_key），换缩放比例不会套用错档案。
    """
    try:
        from PySide6.QtCore import Qt
        from PySide6.QtGui import QGuiApplication
        QGuiApplication.setHighDpiScaleFactorRoundingPolicy(
            Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)
    except Exception as e:      # 老版本 Qt 或非 GUI 环境下降级
        print(f"[DPI] 高 DPI 策略设置失败，使用默认值: {e}")


def main() -> int:
    _configure_high_dpi()
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(True)
    app.setApplicationName("ManboHakimi-Harp")

    from harpguide.app import AppController
    controller = AppController(app)

    if "--selftest" in sys.argv:
        return _selftest(controller)

    controller.start()
    return app.exec()


def _selftest(controller) -> int:
    """离屏自检：数据模型 / 简谱解析 / 播放引擎 / A-B 循环 / 渲染 / 编辑器 / 持久化。"""
    import shutil
    import tempfile
    from pathlib import Path

    from PySide6.QtCore import QElapsedTimer, QEvent, QPointF, Qt
    from PySide6.QtGui import QMouseEvent
    from harpguide.jianpu import parse_jianpu
    from harpguide.models import NoteType, Score

    # 0) 自检隔离：设置文件指向临时路径，并清掉用户真实配置里的「判定偏移」。
    #    否则用户调过的 judge_offset_ms（例如 +220ms）会平移判定基准，
    #    让下面的"漏音 / 命中"断言全失去意义；同时也保证自检绝不改写用户配置。
    _real_settings_path = controller.settings._path
    controller.settings._path = Path(tempfile.gettempdir()) / "harp_selftest_settings.json"
    controller.settings.judge_offset_ms = 0
    controller.overlay.set_judge_offset(None)
    controller.panel.sync_offset_slider(0)

    def _idx(sc, note) -> int:
        """音符在 score.notes 里的下标（`_judged` 现在按下标而不是 id() 记）。"""
        for i, x in enumerate(sc.notes):
            if x is note:
                return i
        raise AssertionError("音符不属于该曲目")

    # 0b) 项目名与数据目录（v0.13 由 HarpGuide 更名为 ManboHakimi-Harp）
    from harpguide import APP_NAME, __version__
    from harpguide.config import _LEGACY_APP_NAME, _migrate_legacy_dir, data_dir
    assert APP_NAME == "ManboHakimi-Harp", APP_NAME
    assert _LEGACY_APP_NAME == "HarpGuide"
    assert __version__.startswith("0.13"), __version__
    assert data_dir().is_dir()                     # 数据目录可创建/可写
    # 旧 %APPDATA%/HarpGuide 的数据应能被搬到新目录，且不覆盖新目录里已有的文件
    _mroot = Path(tempfile.mkdtemp())
    _old = _mroot / _LEGACY_APP_NAME
    (_old / "config").mkdir(parents=True)
    (_old / "config" / "settings.json").write_text('{"from":"legacy"}', encoding="utf-8")
    _new = _mroot / APP_NAME
    (_new / "config").mkdir(parents=True)
    _migrate_legacy_dir(_new)
    assert (_new / "config" / "settings.json").read_text(encoding="utf-8") == '{"from":"legacy"}'
    (_new / "config" / "settings.json").write_text('{"from":"new"}', encoding="utf-8")
    _migrate_legacy_dir(_new)
    assert (_new / "config" / "settings.json").read_text(encoding="utf-8") == '{"from":"new"}', \
        "迁移不得覆盖新目录里已有的配置"
    shutil.rmtree(_mroot, ignore_errors=True)
    print(f"[OK] 项目名 / 数据目录迁移（{APP_NAME} v{__version__}）")

    # 1) 简谱解析：长按识别 + 独立延音线
    score = parse_jianpu("| 1 2 3- 4 | 5 5 6-- 7 | 0 8 | 1- - - |", name="t", bpm=120)
    types = [(n.key, n.type.value, n.duration) for n in score.notes]
    assert types[0] == ("Z", "tap", 1.0), types[0]
    assert types[2] == ("C", "hold", 2.0), types[2]          # 3- 长按 2 拍
    assert types[6] == ("N", "hold", 3.0), types[6]          # 6-- 长按 3 拍
    assert types[8][0] == "rest" and types[9][0] == ","       # 休止 + 高音1
    # 孤立延音线 "-" 应把前一个音符延长到 4 拍（v0.6 修复：原先被直接丢弃）
    assert types[10] == ("Z", "hold", 4.0), types[10]
    assert score.notes[10].beat == 13.0, score.notes[10].beat
    print("[OK] 简谱解析（长按 + 孤立延音线）")

    # 1b) 半音阶：解析 / 映射 / 序列化 / 小键盘切调
    from harpguide.models import resolve_pitch
    from harpguide.hotkeys import HOTKEY_DEFS
    hs = parse_jianpu("| #4 #5 #6 | b3 b5 b7 | #1 | 1 |", name="semi", bpm=100)
    assert hs.notes[0].key == "V" and hs.notes[0].accidental == 1   # #4 -> V 升调
    assert hs.notes[1].key == "B" and hs.notes[1].accidental == 1   # #5 -> B 升调
    assert hs.notes[2].key == "N" and hs.notes[2].accidental == 1   # #6 -> N 升调
    assert hs.notes[3].key == "X" and hs.notes[3].accidental == 1   # b3=#2
    assert hs.notes[4].key == "V" and hs.notes[4].accidental == 1   # b5=#4
    assert hs.notes[5].key == "N" and hs.notes[5].accidental == 1   # b7=#6
    assert hs.notes[6].key == "Z" and hs.notes[6].accidental == 1   # #1
    assert hs.notes[7].key == "Z" and hs.notes[7].accidental == 0   # 自然 1
    # 等价自然音归一到自然键
    assert resolve_pitch(3, 1) == (3, 0)     # #3 = 4 -> V
    assert resolve_pitch(4, -1) == (2, 0)    # b4 = 3 -> C
    assert resolve_pitch(7, 1) == (7, 0)     # #7 = 高音1 -> ,
    assert resolve_pitch(1, -1) == (6, 0)    # b1 = 7 -> M
    # 序列化：升调写字段、自然音不写，往返保留
    d = hs.to_dict()
    assert d["notes"][0].get("accidental") == 1
    assert "accidental" not in d["notes"][7]
    hs2 = Score.from_dict(d)
    assert hs2.notes[0].accidental == 1 and hs2.notes[0].key == "V"
    assert hs2.notes[7].accidental == 0
    # 小键盘 1/2/3 热键
    assert HOTKEY_DEFS["transpose_down"][1] == 0x61
    assert HOTKEY_DEFS["transpose_natural"][1] == 0x62
    assert HOTKEY_DEFS["transpose_up"][1] == 0x63
    assert HOTKEY_DEFS["toggle_auto_transpose"][1] == 0x60   # 小键盘0 自动变调
    # 切调状态
    controller._set_transpose(1)
    assert controller._transpose == 1
    controller._set_transpose(0)
    assert controller._transpose == 0
    # 自动变调：开启后跟随歌曲所需档，手动切档会退出自动
    controller._set_auto_transpose(True)
    assert controller._auto_transpose is True
    assert controller.settings.auto_transpose is True
    assert controller.panel.auto_transpose_cb.isChecked()
    req = controller._current_required_transpose(controller.engine.position_ms())
    assert controller._transpose == req      # 开启时立即同步
    controller._set_transpose(0)             # 手动切档应退出自动
    assert controller._auto_transpose is False
    assert not controller.panel.auto_transpose_cb.isChecked()
    controller._set_auto_transpose(False)
    assert controller._auto_transpose is False
    assert controller.settings.auto_transpose is False
    print("[OK] 半音阶（解析/映射/序列化/小键盘切调/自动变调）")

    # 1c) 命中反馈：判定窗口 / 连击得分 / 空按 / 漏音 / 跳转同步
    from harpguide.keywatch import (MISS_WINDOW_MS, KeyWatcher, judge_offset)
    assert judge_offset(0) == ("PERFECT", 100)
    assert judge_offset(150)[0] == "GREAT"
    assert judge_offset(260)[0] == "GOOD"
    assert judge_offset(999)[0] == "MISS"
    kw = KeyWatcher()
    assert isinstance(kw.poll(), list)           # 被动轮询不上抛（Windows 实测无按键 -> [])
    kw.reset()
    controller.settings.hit_feedback = True
    controller.overlay.waterfall.set_feedback_enabled(True)
    controller._reset_feedback(0.0)
    sc_fb = controller.engine.score
    n_fb = next(n for n in sc_fb.notes if n.type is not NoteType.REST)
    controller._on_key_hit(n_fb.key, n_fb.start_ms(sc_fb.bpm))
    assert controller._combo == 1 and controller._score > 0
    assert _idx(sc_fb, n_fb) in controller._judged
    assert controller.overlay.waterfall._popups
    assert controller.overlay.waterfall._combo == 1
    # 空按（附近没有该键的音符）-> MISS + 连击清零
    controller._on_key_hit(n_fb.key, n_fb.start_ms(sc_fb.bpm) + 99999)
    assert controller._combo == 0
    # 漏音：起点过了窗口仍未按 -> 自动 MISS
    controller._reset_feedback(0.0)
    n_fb2 = next(n for n in sc_fb.notes
                 if n.type is not NoteType.REST and id(n) != id(n_fb))
    controller._process_hits(n_fb2.start_ms(sc_fb.bpm) + MISS_WINDOW_MS + 60)
    assert _idx(sc_fb, n_fb2) in controller._judged
    # 跳转同步：已滑过音符标记为已判定，避免刷一屏 MISS
    controller._reset_feedback(0.0)
    controller._sync_judged(sc_fb.total_ms())
    assert len(controller._judged) >= 1
    controller._reset_feedback(0.0)
    assert not controller._judged and controller._score == 0 and controller._combo == 0
    controller.overlay.waterfall.set_feedback_enabled(controller.settings.hit_feedback)

    # 1c-2) 判定偏移 + 空按宽容（修复「按对了还出 MISS」）
    from harpguide.keywatch import JUDGE_GOOD_MS, MATCH_WINDOW_MS
    from harpguide.models import Note as _Note, Score as _SynthScore
    assert MATCH_WINDOW_MS > MISS_WINDOW_MS, "匹配窗口必须比判定窗口宽，否则会双重 MISS"
    assert MISS_WINDOW_MS > JUDGE_GOOD_MS, "漏音窗口必须比判定窗口宽，否则漏音会抢在命中之前"
    assert judge_offset(320)[0] == "GOOD" and judge_offset(360)[0] == "MISS"
    synth = _SynthScore(
        id="__selftest_synth__", name="自检·判定偏移", bpm=60.0,
        notes=[_Note("Z", NoteType.TAP, 1.0, 0.0),     # 0 ms
               _Note("Z", NoteType.TAP, 1.0, 0.6),     # 600 ms
               _Note("Z", NoteType.TAP, 1.0, 12.0)],   # 12000 ms
    )
    _real_path_fb = controller.settings._path
    controller.settings._path = Path(tempfile.gettempdir()) / "harp_fb_test.json"
    backup_score = controller.engine.score
    controller.engine.set_score(synth)
    controller._reset_feedback(0.0)

    # 判定偏移 +250：玩家整体按晚 250ms，也应判成"正点"
    controller._set_judge_offset(250)
    assert controller.settings.judge_offset_ms == 250
    controller._on_key_hit("Z", controller._jpos(250.0))     # -> 等效 0 偏移
    assert controller._combo == 1, controller._combo
    assert 0 in controller._judged
    # 同一音符重复按：落在匹配窗口内 -> 静默忽略，不再清零连击
    controller._on_key_hit("Z", controller._jpos(250.0 + 80))
    assert controller._combo == 1, "重复按同一音符不应再记 MISS"
    assert len(controller.overlay.waterfall._popups) == 1
    # 第二个音符按点也能命中（偏移统一平移）
    controller._on_key_hit("Z", controller._jpos(250.0 + 600.0))
    assert controller._combo == 2, controller._combo
    # 附近确实没有音符 -> 真・空按 MISS
    controller._on_key_hit("Z", controller._jpos(250.0 + 4000.0))
    assert controller._combo == 0
    # 漏音检测同样按偏移平移后的基准
    controller._reset_feedback(0.0)
    controller._process_hits(12000.0 + 250.0 + MISS_WINDOW_MS + 60.0, pressed=[])
    assert 2 in controller._judged
    # 回归（用户反馈「按对了还是显示 MISS」的帧序竞争）：
    # 在「刚好还能判 GOOD」的时刻，漏音定时器不得抢先把这个音符判掉。
    # 用末尾音符（后方无音符，不会被"更近的下一个音符"按最近匹配抢走）。
    controller._set_judge_offset(0)
    controller._reset_feedback(0.0)
    n_edge = synth.notes[2]
    t_edge = n_edge.start_ms(synth.bpm) + JUDGE_GOOD_MS
    controller._process_hits(t_edge, pressed=[])
    assert 2 not in controller._judged, "还能判 GOOD，不该被漏音抢先"
    controller._on_key_hit("Z", controller._jpos(t_edge))
    assert 2 in controller._judged and controller._combo == 1, "边缘时刻按对了必须判 GOOD"
    assert controller.overlay.waterfall._popups[-1]["text"] == "GOOD"
    # 最近匹配：两个音符之间按下，判给「在判定窗口内更近」的那个
    controller._reset_feedback(0.0)
    controller._on_key_hit("Z", controller._jpos(250.0))     # 0ms 前、600ms 后 -> 判给 0ms
    assert 0 in controller._judged
    assert controller.overlay.waterfall._popups[-1]["text"] == "GOOD"     # 迟到 250ms
    # 回归：「已判定」必须记 score.notes 的下标，而不是 id(note)。
    # 用 id() 会踩 CPython 地址复用（编辑器试听 / 切歌后新音符拿到旧地址），
    # 让玩家按对了却被匹配到后面的音符 -> 莫名 MISS。
    controller._reset_feedback(0.0)
    controller._on_key_hit("Z", controller._jpos(0.0))
    assert controller._judged, "命中后应有已判定记录"
    assert all(isinstance(i, int) and 0 <= i < len(synth.notes)
               for i in controller._judged), "_judged 必须存下标而非 id()"
    # 顶栏偏移读数：4 次命中后出现
    controller._reset_feedback(0.0)
    for i in range(4):
        controller._record_offset(180.0)
    assert controller.overlay.topbar.offset_label.text().startswith("偏移")
    # 改偏移（非 0 -> 0）应清空旧的偏移读数并同步滑杆
    controller._set_judge_offset(30)
    assert controller.settings.judge_offset_ms == 30
    assert controller.panel.offset_slider.value() == 30
    controller._set_judge_offset(0)
    assert controller.settings.judge_offset_ms == 0
    assert controller.overlay.topbar.offset_label.text() == ""
    assert controller.panel.offset_slider.value() == 0
    # 已经是 0 时重复设置 = 空操作（不应写盘、不应改动读数）
    controller._set_judge_offset(0)
    assert controller.settings.judge_offset_ms == 0
    controller.settings._path = _real_path_fb
    controller.engine.set_score(backup_score)
    controller._reset_feedback(0.0)
    print("[OK] 命中反馈（判定/连击/得分/空按/漏音/跳转同步/判定偏移/空按宽容）")

    # 2) 播放引擎时间轴
    engine = controller.engine
    engine.clear_loop_range()
    engine.play()
    timer = QElapsedTimer()
    timer.start()
    while timer.elapsed() < 80:
        pass
    pos = engine.position_ms()
    start = engine.start_ms()
    assert start <= pos < 5000, (start, pos)   # 预备拍阶段位置为负是预期行为
    assert pos > start, "播放后位置应推进"
    engine.reset()
    assert engine.position_ms() <= 0  # 含预备拍，起点为负
    print("[OK] 播放引擎（count-in 起点为负）")

    # 3) 琴键状态机：在长按中段应返回 ACTIVE_HOLD / NEAR_RELEASE
    from harpguide.keys import KeyHintWidget, KeyState
    from harpguide.hintbar import HOTKEY_HINTS
    widget = controller.overlay.keys
    score = controller.engine.score
    hold = next(n for n in score.notes if n.type is NoteType.HOLD)
    mid = (hold.start_ms(score.bpm) + hold.end_ms(score.bpm)) / 2
    widget.tick(mid, 1000.0)
    states = widget._states()
    assert states[hold.key] in (KeyState.ACTIVE_HOLD, KeyState.NEAR_RELEASE), states[hold.key]
    print(f"[OK] 琴键状态机（{hold.key} -> {states[hold.key].name}）")

    # 4) 离屏渲染瀑布流与琴键区
    controller.overlay.resize(600, 480)
    img = controller.overlay.grab()
    assert not img.isNull()
    print(f"[OK] 浮窗离屏渲染 ({img.width()}x{img.height()})")

    # 4b) 启动时自动适配屏幕：窗口必须完整落在可用区域内
    from PySide6.QtGui import QGuiApplication
    screen = QGuiApplication.screenAt(controller.overlay.frameGeometry().center())
    if screen:
        avail = screen.availableGeometry()
        rect = controller.overlay.frameGeometry()
        assert avail.intersects(rect), f"浮窗 {rect} 不在屏幕可用区域 {avail} 内"
        assert rect.width() <= avail.width() + 1 and rect.height() <= avail.height() + 1, \
            f"浮窗 {rect.size()} 大于可用区域 {avail.size()}"
    print("[OK] 浮窗屏幕适配（启动自动 clamp 到可用区域）")

    # 5) 校准模式：几何持久化 + 自由布局渲染 + 瀑布流对齐
    from harpguide.calibration import (CalibrationData, KeyGeom,
                                       default_geometries, resolution_key)
    keys = controller.overlay.keys
    waterfall = controller.overlay.waterfall
    keys.resize(580, 120)

    geoms = default_geometries(580.0)
    geoms[3].x, geoms[3].size = 260.0, 80.0          # V 键移位并放大
    keys.set_geometries(geoms)
    assert keys.geometries() is not None
    cx, nw = keys.column_info(3)
    assert abs(cx - 260.0) < 0.01 and abs(nw - 60.0) < 0.01, (cx, nw)
    col_x, col_w = waterfall._col_rect(3)
    assert abs((col_x + col_w / 2) - 260.0) < 0.01, (col_x, col_w)
    print(f"[OK] 校准几何（V 键中心 x={cx:g}，音轨列已对齐）")

    keys.set_calibrating(True)
    keys.setGeometry(0, 0, 580, 120)
    img2 = keys.grab()
    assert not img2.isNull()
    keys.set_calibrating(False)

    tmp_path = Path(tempfile.gettempdir()) / "harp_cal_test.json"
    cd = CalibrationData()
    cd._path = tmp_path
    cd.set_profile(geoms, res="1920x1080@1.5")
    cd.set_profile(default_geometries(580.0), res="1920x1080@1")
    cd.save()
    cd2 = CalibrationData.load(tmp_path)
    assert len(cd2.profiles) == 2
    p = cd2.profile("1920x1080@1.5")
    assert p is not None and abs(p[3].x - 260.0) < 0.01 and abs(p[3].size - 80.0) < 0.01
    # 不同缩放比必须是不同档案（v0.6：DPI 串档修复）
    assert cd2.profile("1920x1080@1") is not None
    assert cd2.profile("1280x720@1") is None
    tmp_path.unlink(missing_ok=True)
    print("[OK] 校准持久化（按 物理分辨率@缩放比 分档）")

    # DPI 档案键格式
    rk = resolution_key()
    assert isinstance(rk, str) and rk
    assert rk == "default" or "@" in rk, rk
    print(f"[OK] 屏幕档案键 = {rk}")

    keys.set_geometries(None)

    # 6) 乐谱编辑器：创建 / 长按判定 / 撤销重做 / 复制粘贴 / 删除 / 保存往返
    from harpguide.editor import EditorWindow
    ed = EditorWindow()
    ed.load_score(controller.engine.score)
    grid = ed.grid
    n0 = len(grid.notes())
    created = grid._create_note(6.0, 5)          # B 键第 6 拍
    assert len(grid.notes()) == n0 + 1
    assert created.type is NoteType.TAP
    grid._apply_duration(created, 2.0)
    assert created.type is NoteType.HOLD          # >1 拍自动转长按
    grid._delete_note(created)
    assert len(grid.notes()) == n0

    # 复制 + 粘贴（走快照，可撤销）
    grid.select_all()
    assert grid.copy() and grid.has_clipboard()
    assert grid.paste()
    n1 = len(grid.notes())
    assert n1 == n0 * 2, (n0, n1)
    assert grid.can_undo()
    grid.undo()
    assert len(grid.notes()) == n0
    grid.redo()
    assert len(grid.notes()) == n1
    grid.undo()
    assert len(grid.notes()) == n0

    # 删除选中 + 撤销恢复
    grid.select_all()
    assert grid.delete_selection()
    assert len(grid.notes()) == 0
    grid.undo()
    assert len(grid.notes()) == n0

    # 吸附精度：0.3 拍在 1/16 网格上吸附为 0.25
    grid.set_step(0.25)
    assert abs(grid._snap_beat(64.0 + 60.0 * 0.3) - 0.25) < 1e-6
    grid.set_step(0.5)
    assert abs(grid._snap_beat(64.0 + 60.0 * 0.3) - 0.5) < 1e-6

    # 清空 + 撤销
    assert grid.clear_all()
    assert len(grid.notes()) == 0
    grid.undo()
    assert len(grid.notes()) == n0

    ed.name_edit.setText("自检曲目")
    tmpd = Path(tempfile.mkdtemp())
    ed._source_id = ""                            # 当作新曲目
    sid = ed._save(tmpd)
    files = list(tmpd.glob("*.json"))
    assert files, "编辑器未写出 JSON"
    sc = Score.load(files[0])
    assert sc.name == "自检曲目" and sc.bpm > 0
    assert sid == sc.id
    shutil.rmtree(tmpd, ignore_errors=True)
    print(f"[OK] 乐谱编辑器（撤销/重做/复制粘贴/吸附/保存往返 id={sid}）")

    # 7) 曲目目录合并加载 + 音域校验
    merged = controller._load_scores()
    assert len(merged) >= 1
    for s in merged:
        bad = [n.key for n in s.notes
               if n.type is not NoteType.REST and n.key not in s.keymap]
        assert not bad, f"{s.name} 存在超出 8 键音域的音符: {bad}"
        assert s.notes, f"{s.name} 是空谱"
    print(f"[OK] 曲目合并加载（共 {len(merged)} 首，音域均在 8 键内）")

    # 8) A-B 段落循环：回绕 / 暂停不回绕 / reset 回 A / 夹紧 / 清除
    engine.clear_loop_range()
    total = engine.total_ms()
    assert total > 0
    a, b = 0.2 * total, 0.4 * total
    assert engine.set_loop_range(b, a) is True        # 顺序颠倒应自动交换
    assert engine.loop_range == (a, b), engine.loop_range
    assert engine.set_loop_range(1000.0, 1010.0) is False   # 过短拒绝
    engine.seek(0.5 * b)
    engine.play()
    assert a - 1 <= engine.position_ms() <= b + 1
    engine.seek(b + 100)                              # 越过 B 点
    wrapped = engine.position_ms()
    assert a - 1 <= wrapped <= b + 1, ("应回绕进区间", wrapped)
    assert not engine.finished, "A-B 循环不应触发结束"
    engine.pause()
    engine.seek(b + 100)                              # 暂停时如实返回
    assert abs(engine.position_ms() - (b + 100)) < 1.0
    engine.reset()
    assert abs(engine.position_ms() - a) < 0.01, "reset 应回到 A 点"
    engine.clear_loop_range()
    engine.reset()
    assert engine.position_ms() < 0, "清除区间后 reset 应回到曲首（含预备拍）"
    print(f"[OK] A-B 段落循环（A={a:.0f}ms B={b:.0f}ms，回绕与 reset 正确）")

    # 9) 进度条：比例换算 + 点击跳转 + 标记比例注入
    ov = controller.overlay
    bar = ov.progress
    bar.resize(600, 30)
    assert abs(bar._ratio_at(bar.MARGIN)) < 1e-6
    assert abs(bar._ratio_at(bar.width() - bar.MARGIN) - 1.0) < 1e-6
    assert abs(bar._ratio_at(bar.width() / 2) - 0.5) < 0.03
    # 越界拖动被夹紧
    assert bar._ratio_at(-500) == 0.0 and bar._ratio_at(9999) == 1.0

    got = []
    bar.seek_requested.connect(got.append)
    cx_pt = QPointF(bar.width() / 2, 15)
    press = QMouseEvent(QEvent.Type.MouseButtonPress, cx_pt, cx_pt, cx_pt,
                        Qt.MouseButton.LeftButton, Qt.MouseButton.LeftButton,
                        Qt.KeyboardModifier.NoModifier)
    bar.mousePressEvent(press)
    assert got and abs(got[-1] - 0.5) < 0.03, got

    controller._seek_ratio(0.5)
    assert abs(controller.engine.position_ms() - total * 0.5) < 1.0
    controller._refresh_loop_marks()
    ov.update_time(total * 0.5, total)
    assert bar._loop_a is None            # 未设区间时无标记
    ov.set_loop_range(a, b)
    ov.update_time(total * 0.5, total)
    assert bar._loop_a is not None and abs(bar._loop_a - 0.2) < 0.01
    assert bar._loop_b is not None and abs(bar._loop_b - 0.4) < 0.01
    ov.set_loop_range(None, None)
    ov.update_time(total * 0.5, total)
    assert bar._loop_a is None
    img3 = ov.grab()
    assert not img3.isNull()
    print("[OK] 进度条（点击跳转 + A/B 标记比例）")

    # 10) A-B 区间与设置项的持久化往返（临时文件，不碰真实 settings.json）
    from harpguide.config import Settings
    tmp_settings = Path(tempfile.gettempdir()) / "harp_settings_test.json"
    real_path = controller.settings._path
    controller.settings._path = tmp_settings
    controller.settings.loop_ranges = {}
    controller._loop_a_ms, controller._loop_b_ms = a, b
    controller._persist_loop_range()
    sid_now = controller.engine.score.id
    assert controller.settings.loop_ranges.get(sid_now) is not None
    saved = Settings.load(tmp_settings)
    assert saved.lookahead_ms == 2000
    assert len(saved.loop_ranges[sid_now]) == 2
    # 恢复：从磁盘读回并套用
    controller._loop_a_ms = controller._loop_b_ms = None
    controller._restore_loop_range(controller.engine.score)
    assert abs(controller._loop_a_ms - a) < 1.0 and abs(controller._loop_b_ms - b) < 1.0
    controller._clear_loop_range()
    assert controller.settings.loop_ranges.get(sid_now) is None
    # 新字段持久化
    controller.settings.lookahead_ms = 3200
    controller.settings.count_in_beats = 2
    controller.settings.save()
    again = Settings.load(tmp_settings)
    assert again.lookahead_ms == 3200 and again.count_in_beats == 2
    print("[OK] 设置持久化（A-B 区间 / 下落时间 / 预备拍）")

    # 11) 设置面板：新增控件与状态同步 / 热键告警
    panel = controller.panel
    controller._loop_a_ms, controller._loop_b_ms = a, b
    panel.set_loop_status(*controller._loop_status())
    assert "A:" in panel.loop_status.text() and "B:" in panel.loop_status.text()
    assert abs(panel.a_spin.value() - controller._loop_status()[0]) < 0.01
    panel.set_hotkey_warning(["F1 开始/暂停"])
    assert not panel.warn_label.isHidden()
    panel.set_hotkey_warning([])
    assert panel.warn_label.isHidden()
    for w in (panel.lookahead_slider, panel.count_in_slider, panel.lead_slider,
              panel.beat_lines_cb, panel.shine_cb, panel.warn_cb,
              panel.lyrics_cb, panel.hotkeys_hint_cb,
              panel.auto_transpose_cb, panel.hit_feedback_cb,
              panel.a_spin, panel.b_spin):
        assert w is not None
    # 底部热键提示条：开关生效 + 按宽度自适应换行高度
    bar = controller.overlay.hotkeybar
    assert controller.settings.show_hotkeys and not bar.isHidden()
    wide_h = bar.height_for_width(4000)
    narrow_h = bar.height_for_width(120)
    assert narrow_h > wide_h >= 21          # 窄窗口自动多行，宽窗口单行
    assert bar.height_for_width(600) >= wide_h
    controller.overlay.set_hotkeys_visible(False)
    assert not controller.settings.show_hotkeys and bar.isHidden()
    controller.overlay.set_hotkeys_visible(True)
    assert controller.settings.show_hotkeys and not bar.isHidden()
    assert len(HOTKEY_HINTS) >= 10
    print("[OK] 底部热键提示条（开关 / 自适应换行）")
    # 三个辅助窗口都能渲染（面板改可滚动布局后的回归保护）
    for w in (panel, controller.cal_panel, ed):
        shot = w.grab()
        assert not shot.isNull() and shot.width() > 100
    controller._clear_loop_range()

    # 复位为默认值并把设置文件指回真实路径（前面的用例都写在临时文件里）
    controller.settings.lookahead_ms = 2000
    controller.settings.count_in_beats = 4
    controller.settings.loop_ranges = {}
    controller.settings._path = real_path
    tmp_settings.unlink(missing_ok=True)
    engine.clear_loop_range()
    engine.reset()
    print("[OK] 设置面板（A-B 状态同步 / 高级项 / 热键告警）")

    # 11b) 歌词：查找 / 序列化往返 / 显示控件显隐
    from harpguide.models import LyricLine, Score as _Score
    from harpguide.jianpu import parse_jianpu as _parse
    s_lyr = _parse("| 1 2 3- | 4 5 6- |", name="歌词测试", bpm=120, score_id="lyr")
    s_lyr.lyrics = [LyricLine(0, "第一句"), LyricLine(1000, "第二句"),
                    LyricLine(2000, "第三句")]
    assert s_lyr.lyric_at(0) == 0
    assert s_lyr.lyric_at(999) == 0
    assert s_lyr.lyric_at(1000) == 1
    assert s_lyr.lyric_at(5000) == 2
    assert s_lyr.lyric_at(-100) is None          # 负时间无歌词
    import tempfile as _tf
    _lp = Path(_tf.gettempdir()) / "harp_lyric_test.json"
    s_lyr.save(_lp)
    s_lyr2 = _Score.load(_lp)
    assert len(s_lyr2.lyrics) == 3 and s_lyr2.lyrics[1].text == "第二句"
    _lp.unlink(missing_ok=True)
    lw = controller.overlay.lyrics
    lw.set_score(s_lyr)
    assert not lw.isHidden()                        # 有歌词 + 开关默认开
    lw.tick(1500)
    assert not lw.grab().isNull()
    s_empty = _parse("| 1 2 3 |", name="无歌词", bpm=120, score_id="nl")
    lw.set_score(s_empty)
    assert lw.isHidden()                            # 无歌词自动隐藏
    lw.set_score(controller.engine.score)
    print("[OK] 歌词（查找 / 序列化 / 显示控件显隐）")

    # 11c) 窗口 resize：尺寸持久化 / 瀑布流弹性高度 / 滑杆同步
    # （set_waterfall_height 会触发 save，临时切走 _path 避免污染真实 settings.json）
    tmp_resize = Path(tempfile.gettempdir()) / "harp_resize_test.json"
    real_resize_path = controller.settings._path
    controller.settings._path = tmp_resize
    ov = controller.overlay
    ov._settings.window_w = 700
    ov._settings.window_h = 560
    ov._resize_from_settings()
    QApplication.processEvents()
    assert ov.width() == 700 and ov.height() == 560
    assert ov._settings.window_w == 700 and ov._settings.window_h == 560
    wf_expected = ov._waterfall_from_height(560)
    assert ov.waterfall.height() == wf_expected
    assert abs(ov._settings.waterfall_height - wf_expected) < 1
    panel.sync_height_slider(wf_expected)
    assert panel.height_slider.value() == wf_expected
    # 通过设置面板滑杆调整瀑布流高度 -> 反推窗口高度
    ov.set_waterfall_height(300)
    assert ov.height() == ov._height_from_waterfall(300)
    assert ov._settings.window_h == ov.height()
    # 恢复默认尺寸
    ov._settings.window_w = 600
    ov._settings.window_h = 504
    ov._resize_from_settings()
    QApplication.processEvents()
    controller.settings._path = real_resize_path
    tmp_resize.unlink(missing_ok=True)
    print("[OK] 窗口 resize（尺寸持久化 / 瀑布流弹性高度 / 滑杆同步）")

    # 12) 系统托盘：构造 + 信号接线 + 引擎状态变更同步
    from harpguide.tray import TrayController
    tray = TrayController()
    if tray.available:
        from PySide6.QtGui import QIcon as _QI
        tray.install(_QI(), "ManboHakimi-Harp 测试")
        assert tray._menu is not None
        # 触发引擎状态变更，验证 set_playing 不会崩
        controller.engine.play()
        QApplication.processEvents()
        tray.set_playing(True)
        assert tray._act_pause.isChecked()
        tray.set_playing(False)
        assert not tray._act_pause.isChecked()
        tray.shutdown()
        controller.engine.pause()
        print("[OK] 系统托盘（菜单构造 + 状态同步）")
    else:
        # 离屏环境：至少确认 TrayController 不挂
        assert tray._menu is None
        tray.shutdown()
        print("[OK] 系统托盘（当前环境无托盘，回退模式无异常）")

    # 收尾：把设置路径还原成用户真实配置文件（自检全程只写临时文件）
    controller.settings._path = _real_settings_path

    print("SELFTEST PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
