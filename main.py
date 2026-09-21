# -*- coding: utf-8 -*-
"""ManboHakimi-Harp 入口。

用法：
    python main.py             启动浮窗
    python main.py --selftest  离屏自检（不弹窗，验证核心逻辑后退出）
"""
from __future__ import annotations

import sys

from PySide6.QtWidgets import QApplication


# ---------------------------------------------------------------- 崩溃日志
# 打包时 console=False：程序一旦抛异常，用户看到的就是"没反应"，
# 既截图不到也描述不清。把未捕获异常连版本/环境写进 config/harpguide.log，
# 出问题让用户把这个文件发过来即可定位。
# 注：PySide6 槽函数里的未捕获异常同样会走 sys.excepthook（已验证），
# 所以一个钩子既管主线程崩溃，也管"点按钮炸了"。
LOG_MAX_BYTES = 512 * 1024      # 超过就轮转成 .1，只留最近两份，不做完整轮转

_LOG_FILE = None                # 自检会覆盖成临时路径，保证不写用户真实目录


def _log_file():
    """日志落盘位置：与 settings.json 同在 data_dir()/config，便携模式行为一致。"""
    from pathlib import Path
    if _LOG_FILE is not None:
        return Path(_LOG_FILE)
    try:
        from harpguide.config import data_dir
        return data_dir() / "config" / "harpguide.log"
    except Exception:           # data_dir 自己出问题时也不能再炸一次
        import tempfile
        return Path(tempfile.gettempdir()) / "ManboHakimi-Harp.log"


def _write_log(text: str) -> None:
    """追加写日志。任何失败都静默放弃——日志绝不能成为新的崩溃源。"""
    from pathlib import Path
    try:
        path = Path(_log_file())
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists() and path.stat().st_size > LOG_MAX_BYTES:
            path.replace(path.with_name(path.name + ".1"))
        with open(path, "a", encoding="utf-8") as f:
            f.write(text)
    except Exception:
        pass


def _install_excepthook() -> None:
    """安装全局异常钩子（进程内只装一次即可，重复调用会覆盖成同样的逻辑）。

    刻意只用 sys / traceback / datetime 这几个必然可用的模块：
    崩溃处理器自己再去 import 别的模块（例如 platform）在冻结态有失败风险，
    「报错时报不出去」比不报更糟。
    """
    import datetime
    import traceback

    def _hook(exc_type, exc, tb) -> None:
        if issubclass(exc_type, KeyboardInterrupt):     # Ctrl+C 不是崩溃
            sys.__excepthook__(exc_type, exc, tb)
            return
        try:
            from harpguide import __version__
        except Exception:
            __version__ = "?"
        try:
            detail = "".join(traceback.format_exception(exc_type, exc, tb))
        except Exception:
            detail = f"{exc_type} / {exc}\n"
        _write_log(
            f"\n===== {datetime.datetime.now():%Y-%m-%d %H:%M:%S} v{__version__} =====\n"
            f"{detail}"
            f"--- Python {sys.version.split()[0]} / {sys.platform} "
            f"/ frozen={getattr(sys, 'frozen', False)}\n")
        sys.__excepthook__(exc_type, exc, tb)           # 控制台行为保持不变

    sys.excepthook = _hook


def _log_startup() -> None:
    """每个正常启动留一行：版本 / 数据目录 / 是否打包。排障时第一眼看的就是它。"""
    import datetime
    try:
        from harpguide import __version__
        from harpguide.config import data_dir
        _write_log(
            f"[{datetime.datetime.now():%Y-%m-%d %H:%M:%S}] 启动 v{__version__} "
            f"frozen={getattr(sys, 'frozen', False)} data_dir={data_dir()}\n")
    except Exception:
        pass


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
    _install_excepthook()       # 越早越好：AppController 构造期的崩溃也要留痕
    _configure_high_dpi()
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(True)
    app.setApplicationName("ManboHakimi-Harp")

    from harpguide.app import AppController
    controller = AppController(app)

    if "--selftest" in sys.argv:
        return _selftest(controller)

    _log_startup()
    controller.start()
    return app.exec()


def _selftest(controller) -> int:
    """离屏自检：数据模型 / 简谱解析 / 播放引擎 / A-B 循环 / 渲染 / 编辑器 / 持久化。"""
    import shutil
    import tempfile
    from pathlib import Path

    from PySide6.QtCore import QElapsedTimer, QEvent, QPointF, Qt
    from PySide6.QtGui import QFontMetrics, QMouseEvent
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
    assert __version__.startswith("0.15"), __version__
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
    _pressed, _held = kw.poll()                  # 被动轮询不上抛（Windows 实测无按键 -> ([], set())）
    assert isinstance(_pressed, list) and isinstance(_held, set)
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
    # 空按（附近没有该键的音符）-> 静默忽略：不判 MISS、不断连击
    # （练习工具里试键 / 摸键位是常态，误报 MISS 只会干扰手感）
    controller._on_key_hit(n_fb.key, n_fb.start_ms(sc_fb.bpm) + 99999)
    assert controller._combo == 1, "空按不该断连击"
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

    # 1c-2) 判定偏移 + 抢拍/拖拍宽容带 + 长按按住判定
    from harpguide.keywatch import GRACE_MS, HOLD_LATE_MS, JUDGE_GOOD_MS
    from harpguide.models import Note as _Note, Score as _SynthScore
    assert MISS_WINDOW_MS > JUDGE_GOOD_MS, "漏音窗口必须比判定窗口宽，否则漏音会抢在命中之前"
    assert GRACE_MS > 0, "必须有抢拍/拖拍宽容带，否则按偏一点就把音符吃掉"
    assert judge_offset(320)[0] == "GOOD" and judge_offset(360)[0] == "MISS"
    synth = _SynthScore(
        id="__selftest_synth__", name="自检·判定偏移", bpm=60.0,
        notes=[_Note("Z", NoteType.TAP, 1.0, 0.0),      # 0 ms
               _Note("Z", NoteType.TAP, 1.0, 0.6),      # 600 ms
               _Note("Z", NoteType.TAP, 1.0, 12.0),     # 12000 ms
               _Note("Z", NoteType.HOLD, 4.0, 20.0)],   # 20000 ms 起，持续 4000ms（长按）
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
    # 第二个音符按点也能命中（偏移统一平移）
    controller._on_key_hit("Z", controller._jpos(250.0 + 600.0))
    assert controller._combo == 2, controller._combo
    assert 1 in controller._judged
    # 附近确实没有音符 -> 空按：静默忽略，不判 MISS、不断连击
    controller._on_key_hit("Z", controller._jpos(250.0 + 4000.0))
    assert controller._combo == 2, "空按不该断连击"

    # 抢拍 / 拖拍宽容带：偏移超出 GOOD 窗口，但仍在 MISS_WINDOW 内 ——
    # 记一次 MISS 提醒，却**不消耗音符**，玩家可以重按救回来。
    # 这是修复「第一次没按好，再按还是 MISS」的关键（旧实现把音符吃掉，
    # 重按既匹配不到原音符、又被判成空按，连吃两个 MISS）。
    controller._set_judge_offset(0)
    controller._reset_feedback(0.0)
    t3 = synth.notes[2].start_ms(synth.bpm)          # 12000 ms
    controller._on_key_hit("Z", t3 + 400.0)          # 晚 400ms（> GOOD 350）
    assert controller._combo == 0, "宽容带内应记一次 MISS"
    assert 2 not in controller._judged, "宽容带不得消耗音符，否则重按就没救了"
    controller._on_key_hit("Z", t3 + 430.0)          # 再按，仍在宽容带 -> 只提醒一次
    assert 2 not in controller._judged and controller._combo == 0
    controller._on_key_hit("Z", t3)                  # 音符还在，正点重按 -> 命中
    assert 2 in controller._judged and controller._combo == 1, "重按必须能救回来"
    # 漏音：起点过了窗口仍未按 -> 自动 MISS
    controller._reset_feedback(0.0)
    controller._process_hits(12000.0 + MISS_WINDOW_MS + 60.0, pressed=[])
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
    # 长按（hold）：玩家常在长音起点**之前**就把键压住（这是正确的长按手法），
    # 那一刻没有新的按键边沿 —— 旧实现只看边沿，会整条长音判 MISS。
    # 新实现按「键处于按住状态 + 与音符区间有重叠」判定。
    hold_n = synth.notes[3]
    h_start = hold_n.start_ms(synth.bpm)      # 20000 ms
    h_end = hold_n.end_ms(synth.bpm)          # 24000 ms
    controller._reset_feedback(h_start - 200.0)          # 把已滑过的音符标记掉
    controller._process_hits(h_start - 200.0, pressed=[], held={"Z"})
    assert 3 in controller._judged, "提前压住的长音必须命中，不能判 MISS"
    assert controller._combo == 1
    assert controller.overlay.waterfall._popups[-1]["text"] == "PERFECT"
    # 长音持续按住期间不得重复判定
    _n_pop = len(controller.overlay.waterfall._popups)
    controller._process_hits(h_start + 800.0, pressed=[], held={"Z"})
    assert len(controller.overlay.waterfall._popups) == _n_pop, "长音不应重复判定"
    # 长音整段没按 -> 漏音 MISS
    controller._reset_feedback(h_start)
    controller._process_hits(h_end + HOLD_LATE_MS + 60.0, pressed=[], held=set())
    assert 3 in controller._judged
    # 最近匹配：两个音符之间按下，判给「在判定窗口内更近」的那个
    controller._reset_feedback(0.0)
    controller._on_key_hit("Z", controller._jpos(250.0))     # 0ms 前、600ms 后 -> 判给 0ms
    assert 0 in controller._judged
    assert controller.overlay.waterfall._popups[-1]["text"] == "GOOD"     # 迟到 250ms
    # 回归：最左 / 最右列的判定文字不得被控件边缘裁掉（PERFECT -> RFECT）。
    # 文字框必须钳在控件内，且留出曲目侧边栏把手（22px）的让位空间。
    from harpguide.waterfall import POPUP_BOX_W
    _wf = controller.overlay.waterfall
    assert _wf.width() >= POPUP_BOX_W, _wf.width()
    _max_x = _wf.width() - POPUP_BOX_W
    for _c in (0, 7):
        _x = _wf._popup_box_x(_c)
        assert 0.0 <= _x <= _max_x, (_c, _x, _max_x)
    _x0 = _wf._popup_box_x(0)
    assert _x0 >= 0.0 and _x0 + POPUP_BOX_W <= _wf.width()
    # 判定浮层真的画得出来：直接调绘制方法（绕开 Qt 虚函数分发）。
    # 走 Qt 的 paintEvent 时，Python 异常会被吞掉、只在 stderr 打一行日志；
    # 直接调用则原样抛出，属性名写错这类低级错误当场就会被自检抓住。
    from PySide6.QtGui import QPainter as _QP, QPixmap as _QPM
    _wf.push_judgment(0, "PERFECT", "#FFD54F")
    _wf.push_judgment(7, "MISS", "#FF5252")
    _wf.set_combo(5, 300)
    _pm = _QPM(max(1, _wf.width()), max(1, _wf.height()))
    _pt = _QP(_pm)
    try:
        _wf._paint_feedback(_pt, 1000.0)
        # 预备拍期间（pos < 0）也要能安全绘制：此时连击不画 —— 连击数字在高度 10%、
        # 倒计时在中间，瀑布流矮（默认 220px）时两者会叠在一起。
        _wf._paint_feedback(_pt, -200.0)
    finally:
        _pt.end()
    print("[OK] 判定文字边界钳制（最左/最右列不被裁 + 浮层绘制不抛异常）")
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
    print("[OK] 命中反馈（判定/连击/得分/空按静默/漏音/跳转同步/判定偏移/抢拍宽容带/长按按住）")

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
    from harpguide.keys import KeyState
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
    from harpguide.calibration import (CalibrationData,
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

    # 11a2) 曲目侧边栏：悬停展开的抽屉，取代设置面板里的曲目列表
    sb = controller.overlay.sidebar
    assert sb.parent() is controller.overlay      # 必须是子部件，才能被父窗口裁剪出"滑出"效果
    assert sb.HANDLE_W < sb.PANEL_W
    # 收起态：只剩把手，纵向范围由浮窗注入（不遮顶栏拖动区）
    sb.set_span(56, 300)
    assert (sb.x(), sb.y(), sb.width(), sb.height()) == (0, 56, sb.HANDLE_W, 300)
    assert not sb.expanded
    # 展开 / 收起：离屏无事件循环，手动把动画推到终点再断言宽度
    sb.expand()
    assert sb.expanded and sb._anim.endValue().width() == sb.PANEL_W
    sb._anim.setCurrentTime(sb._anim.duration())
    assert sb.width() == sb.PANEL_W
    assert sb._body.width() > 0 and sb._body.x() == sb.HANDLE_W
    sb.collapse()
    assert not sb.expanded and sb._anim.endValue().width() == sb.HANDLE_W
    sb._anim.setCurrentTime(sb._anim.duration())
    assert sb.width() == sb.HANDLE_W
    # 曲目列表：数量 / 选中态跟随当前曲目
    sb.set_scores(controller.scores, controller.scores[0].id)
    total = len(controller.scores)
    assert len(sb._score_buttons) == total and total > 0
    assert len(sb._scores) == total          # 把手上的计数从这份缓存来
    assert sb.count_label.text() == f"{total} 首"
    assert sb._score_buttons[0].isChecked()
    # 点第二首 -> 真的换曲，列表选中态跟着走（换曲会重建按钮，取新列表断言）
    _last_id = controller.settings.last_score_id
    sb._score_buttons[1].click()
    assert controller.engine.score.id == controller.scores[1].id
    assert sb._score_buttons[1].isChecked() and not sb._score_buttons[0].isChecked()
    # 选完自动收回（鼠标还按在按钮上，也要收）
    sb._maybe_collapse()
    assert not sb.expanded
    controller.settings.last_score_id = _last_id
    # 鼠标穿透 / 校准时整体撤下：穿透态收不到鼠标事件，留着会让人以为卡住
    controller.overlay.set_sidebar_enabled(False)
    assert sb.isHidden()
    controller.overlay.set_sidebar_enabled(True)
    assert not sb.isHidden()
    # 曲目列表已迁出设置面板
    assert not hasattr(panel, "set_scores")
    shot = sb.grab()
    assert not shot.isNull() and shot.width() >= sb.HANDLE_W - 1
    print("[OK] 曲目侧边栏（悬停展开 / 缩进保留把手 / 列表迁出设置面板）")


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

    # 13) v0.14.2 自查回归：把这一轮扫出来的 6 个 BUG 钉成用例
    #      （1) A/B 设点按钮信号断裂 2) 悬浮球拖动误展开 3) 球模式恢复带出完整浮窗
    #       4) 同名曲目覆盖方向反了 5) 中文曲名 id 塌缩成 user_song 6) _states 空解引用）
    from io import StringIO
    from pathlib import Path as _Path

    from PySide6.QtWidgets import QPushButton
    from harpguide.models import Note as _Note

    # 记下当前可见性，块尾精确还原，免得影响后面几个 grab() 渲染用例
    _pre_visible = [w for w in (controller.overlay, panel, controller.ball)
                    if w.isVisible()]

    # 1) 「设 A 点为当前」按钮：面板 -> 控制器链路必须是通的
    b_a = next(b for b in panel.findChildren(QPushButton)
               if b.text().startswith("设 A 点"))
    controller._loop_a_ms = None
    _err = StringIO()
    _old_stderr, sys.stderr = sys.stderr, _err
    try:
        b_a.click()
    finally:
        sys.stderr = _old_stderr
    assert "AttributeError" not in _err.getvalue(), f"按钮槽函数抛异常: {_err.getvalue()}"
    assert controller._loop_a_ms is not None, "按钮点了没反应：信号没人接"
    controller._clear_loop_range()

    # 2) 悬浮球：拖动后松手不算单击，原地点击才算
    from harpguide.floating_ball import FloatingBall
    ball = FloatingBall()
    clicks = []
    ball.expand_requested.connect(lambda: clicks.append(1))

    def _me(kind, local, glob):
        return QMouseEvent(kind, QPointF(*local), QPointF(*glob),
                           Qt.MouseButton.LeftButton, Qt.MouseButton.LeftButton,
                           Qt.KeyboardModifier.NoModifier)

    ball.move(500, 500)
    ball.mousePressEvent(_me(QEvent.Type.MouseButtonPress, (36, 36), (536, 536)))
    ball.mouseMoveEvent(_me(QEvent.Type.MouseMove, (136, 136), (636, 636)))
    ball.mouseReleaseEvent(_me(QEvent.Type.MouseButtonRelease, (136, 136), (636, 636)))
    assert not clicks, "拖动悬浮球后松手不应展开浮窗"
    ball.move(300, 300)
    ball.mousePressEvent(_me(QEvent.Type.MouseButtonPress, (36, 36), (336, 336)))
    ball.mouseReleaseEvent(_me(QEvent.Type.MouseButtonRelease, (36, 36), (336, 336)))
    assert len(clicks) == 1, "原地单击悬浮球应展开浮窗"
    ball.deleteLater()

    # 3) 悬浮球模式下 隐藏 -> 再显示：只能把球还回来
    controller.show_overlay_mode()
    controller.toggle_ball()
    controller.toggle_visible()
    controller.toggle_visible()
    assert controller.ball.isVisible() and not controller.overlay.isVisible(), \
        "球模式恢复时把完整浮窗也带出来了"
    controller.show_overlay_mode()
    controller.toggle_visible()
    controller.toggle_visible()
    assert controller.overlay.isVisible(), "完整模式恢复后浮窗应可见"

    # 4) 同名曲目：用户目录必须胜出（打包 EXE 下内建在 _MEIPASS，顺序反了就顶掉用户曲目）
    import harpguide.app as _appmod
    from harpguide.models import Score as _Sc
    _u = _Path(tempfile.mkdtemp()) / "user"
    _p = _Path(tempfile.mkdtemp()) / "packed"
    (_u / "scores").mkdir(parents=True)
    (_p / "scores").mkdir(parents=True)
    _Sc(id="dup", name="用户版", bpm=100,
        notes=[_Note("Z", NoteType.TAP, 1.0, 0.0)]).save(_u / "scores" / "dup.json")
    _Sc(id="dup", name="打包版", bpm=100,
        notes=[_Note("X", NoteType.TAP, 1.0, 0.0)]).save(_p / "scores" / "dup.json")
    _orig_dirs = (_appmod.data_dir, _appmod.app_root)
    _appmod.data_dir, _appmod.app_root = (lambda: _u), (lambda: _p)
    try:
        _merged = {s.id: s for s in controller._load_scores()}
        assert _merged["dup"].name == "用户版", "同名曲目被内建版本顶掉了"
        assert _merged["dup"].builtin is False, "用户曲目不该被标成内置只读"
        # 打包（frozen）场景才是最要命的：用户曲目在 EXE 同级、内建在 _MEIPASS 里，
        # 覆盖顺序一旦反了，用户改过的曲目每次启动都会被内置版本悄悄顶掉。
        # 注意：真打包运行时 sys.frozen / sys._MEIPASS 本来就存在，
        # 无条件 del 会把 EXE 的 import 机制打断（之后任何惰性 import 都炸），
        # 所以必须按「原本有没有」来还原。
        _had = (hasattr(sys, "frozen"), hasattr(sys, "_MEIPASS"))
        _was = (getattr(sys, "frozen", None), getattr(sys, "_MEIPASS", None))
        sys.frozen = True
        sys._MEIPASS = str(_p)
        try:
            _frozen = {s.id: s for s in controller._load_scores()}
            assert _frozen["dup"].name == "用户版", "打包模式下用户曲目被内建顶掉了"
            assert _frozen["dup"].builtin is False, "用户曲目不该被标成内置只读"
        finally:
            for _name, _existed, _old in (("frozen", _had[0], _was[0]),
                                          ("_MEIPASS", _had[1], _was[1])):
                if _existed:
                    setattr(sys, _name, _old)
                else:
                    delattr(sys, _name)
        assert (hasattr(sys, "frozen"), hasattr(sys, "_MEIPASS")) == _had, \
            "模拟打包破坏了真实的 sys.frozen / sys._MEIPASS（打包后 EXE 的 import 机制会崩）"
    finally:
        _appmod.data_dir, _appmod.app_root = _orig_dirs
    shutil.rmtree(_u.parent, ignore_errors=True)
    shutil.rmtree(_p.parent, ignore_errors=True)

    # 5) 曲名 -> id：中文名不能再塌缩成同一个 user_song（否则另存为静默覆盖前一首）
    from harpguide.editor import sanitize_id, unique_score_id
    _i1, _i2 = sanitize_id("小星星"), sanitize_id("大星星")
    assert _i1 != _i2 and _i1 == sanitize_id("小星星"), (_i1, _i2)
    assert _i1 != "user_song", "中文曲名的 id 应带稳定哈希后缀，而不是塌缩成 user_song"
    _tmpdir = _Path(tempfile.mkdtemp())
    _Sc(id=_i2, name="别的歌", bpm=100, notes=[]).save(_tmpdir / f"{_i2}.json")
    assert unique_score_id("大星星", _tmpdir) != _i2, "另存为不能覆盖别人的曲目文件"
    _Sc(id=_i2, name="大星星", bpm=100, notes=[]).save(_tmpdir / f"{_i2}.json")
    assert unique_score_id("大星星", _tmpdir) == _i2, "同一首歌重存应沿用原 id"
    shutil.rmtree(_tmpdir, ignore_errors=True)

    # 6) 空曲目下取状态机不应炸（None 检查必须写在解引用之前）
    _kw = controller.overlay.keys
    _saved_score, _kw._score = _kw._score, None
    try:
        assert _kw._states() == {}, "无曲目时应返回空状态表"
    finally:
        _kw._score = _saved_score

    # 7) 内置曲目只读：控制器拒绝重命名 / 删除，侧边栏菜单项置灰
    _fake = _Sc(id="b1", name="内置测试", bpm=90, notes=[], builtin=True)
    controller.scores = controller.scores + [_fake]
    sb.set_scores(controller.scores, "b1")
    assert sb._score_buttons[-1].property("builtin") is True, "内置标记没传到侧边栏按钮"
    controller._rename_score("b1", "改个名")
    controller._delete_score("b1")
    assert not (data_dir() / "scores" / "b1.json").exists(), \
        "内置曲目不该在用户目录留下副本"
    controller.scores = [s for s in controller.scores if s.id != "b1"]

    # 块尾还原：侧边栏曲目表 + 三个窗口的可见性，别影响后面的渲染用例
    sb.set_scores(controller.scores, controller.engine.score.id)
    for w in (controller.overlay, panel, controller.ball):
        if w not in _pre_visible:
            w.hide()
    for w in _pre_visible:
        w.show()
    print("[OK] v0.14.2 自查回归（设点按钮/悬浮球拖拽/切显隐/曲目覆盖顺序/id 唯一化/空曲目）")

    # 14) 崩溃日志：打包 console=False 下异常必须留痕，且自身绝不能成为新的崩溃源
    global _LOG_FILE
    assert sys.excepthook is not sys.__excepthook__, "入口没安装异常钩子"
    _logdir = _Path(tempfile.mkdtemp())
    _old_log_file, _old_hook, _old_stderr = _LOG_FILE, sys.excepthook, sys.stderr
    _LOG_FILE = _logdir / "harpguide.log"
    sys.stderr = StringIO()             # 钩子会调 __excepthook__，别把 traceback 喷进自检输出
    try:
        def _boom_probe() -> None:
            raise RuntimeError("自检模拟崩溃")

        try:
            _boom_probe()
        except RuntimeError:
            sys.excepthook(*sys.exc_info())
        _txt = _LOG_FILE.read_text(encoding="utf-8")
        assert "RuntimeError" in _txt and "自检模拟崩溃" in _txt, "崩溃没写进日志"
        assert "_boom_probe" in _txt, "日志里没有崩溃位置，定位不了"
        assert __version__ in _txt and "frozen=" in _txt, "日志应带版本与环境"

        # Ctrl+C 不是崩溃，不记日志
        _before = _LOG_FILE.read_text(encoding="utf-8")
        try:
            raise KeyboardInterrupt
        except KeyboardInterrupt:
            sys.excepthook(*sys.exc_info())
        assert _LOG_FILE.read_text(encoding="utf-8") == _before, "Ctrl+C 不该写崩溃日志"

        # 超过上限要轮转，日志不能无限长大
        _LOG_FILE.write_text("x" * (LOG_MAX_BYTES + 1), encoding="utf-8")
        try:
            raise ValueError("轮转测试")
        except ValueError:
            sys.excepthook(*sys.exc_info())
        assert (_logdir / "harpguide.log.1").exists(), "超限日志没轮转"
        assert _LOG_FILE.stat().st_size < LOG_MAX_BYTES, "轮转后新日志应是空的"

        # 日志路径不可写时必须静默失败，不能反过来再炸一次
        (_logdir / "blocked").write_text("", encoding="utf-8")
        _LOG_FILE = _logdir / "blocked" / "x.log"       # 父级是文件 -> mkdir 必失败
        try:
            raise OSError("日志路径不可写")
        except OSError:
            sys.excepthook(*sys.exc_info())

        # 落盘位置：与 settings.json 同在 config/ 下；打包态还必须落在 EXE 同级
        # （便携模式：日志要跟程序走，用户一眼找得到，也才能随程序一起挪走）
        _LOG_FILE = None
        _logp = _log_file()
        assert _logp.parent.name == "config", _logp
        if getattr(sys, "frozen", False) and data_dir() == _Path(sys.executable).parent:
            assert _logp == _Path(sys.executable).parent / "config" / "harpguide.log", _logp
    finally:
        _LOG_FILE = _old_log_file
        sys.excepthook = _old_hook
        sys.stderr = _old_stderr
        shutil.rmtree(_logdir, ignore_errors=True)
    print("[OK] 崩溃日志（异常留痕/带版本环境/Ctrl+C 不记/超限轮转/不可写不反炸）")

    # 15) 循环回绕＝新一遍：判定 / 连击 / 得分必须清零
    #     回归的是「A-B 循环第二遍判定停摆」——回绕原先只是 position_ms() 里的一次
    #     纯计算，没人知道新一遍开始了，上一遍的 _judged 继续生效，玩家按对不给分。
    _orig_score = controller.engine.score
    _orig_fb = controller.settings.hit_feedback
    _loop_score = parse_jianpu("| 1 2 3 4 | 5 5 6 7 |", name="loop_probe", bpm=120)
    controller.settings.hit_feedback = True
    controller.engine.set_score(_loop_score)
    controller.overlay.set_score(_loop_score)
    controller.engine.set_loop_range(1000.0, 2500.0)      # A=2拍 B=5拍
    _ins = [i for i, n in enumerate(_loop_score.notes)
            if 1000.0 <= n.start_ms(120) < 2500.0]
    assert len(_ins) == 3, _ins

    def _play_one_pass() -> int:
        """按顺序把区间内每个音符都按对一次，返回判定生效次数。"""
        got = 0
        for i in _ins:
            n = _loop_score.notes[i]
            before = controller._combo
            controller._process_hits(n.start_ms(120) + 10, pressed=[n.key], held=set())
            got += 1 if controller._combo > before else 0
        return got

    def _wrap_once() -> float:
        """模拟播放推进越过 B 点（引擎内部回绕），返回回绕后的位置。"""
        controller.engine._playing = True
        controller.engine._offset_ms = 2501.0
        controller.engine._elapsed.restart()
        pos = controller.engine.position_ms()
        controller.engine._playing = False
        return pos

    _passes = []
    controller.engine.pass_finished.connect(lambda p: _passes.append(p))
    # 与真实流程一致：区间定好后位置被拉到 A 点，从 A 点开始这一遍
    assert controller.engine.position_ms() == 1000.0, controller.engine.position_ms()
    controller._reset_feedback(controller.engine.position_ms())
    # A 点之前的音符属于"这一遍吹不到"：必须已标记，否则每遍开头喷一串 MISS
    assert {0, 1} <= controller._judged, sorted(controller._judged)
    assert _play_one_pass() == 3, "第一遍应判定 3 次"
    assert controller._combo == 3, controller._combo
    _wrapped = _wrap_once()
    assert len(_passes) == 1, f"回绕没发 pass_finished（{_passes}）"
    assert 1000.0 <= _wrapped <= 1100.0, _wrapped
    # 回绕只算一次：位置每帧被读多处，重复发信号会让判定状态反复清零
    for _ in range(3):
        controller.engine.position_ms()
    assert len(_passes) == 1, f"同一个回绕发了 {len(_passes)} 次信号"
    assert _passes[0] == _wrapped, (_passes, _wrapped)
    assert controller._combo == 0 and controller._score == 0, \
        (controller._combo, controller._score)
    assert _play_one_pass() == 3, "循环第二遍判定停摆（本用例就是为它写的）"
    assert controller._combo == 3, controller._combo

    # 16) 顶栏：齿轮点得到 + 不压时长文字 + 长曲名省略
    from harpguide.overlay import TopBar
    _ov, _tb = controller.overlay, controller.overlay.topbar
    _geo = _ov.size()
    _was_visible = _ov.isVisible()
    _ov.show()
    _ov.resize(600, 480)                                  # 默认瀑布流 220px 的常用尺寸
    controller.app.processEvents()
    _fired: list = []
    _tb.settings_clicked.connect(lambda: _fired.append(1))
    # 齿轮在顶栏自己的坐标系里：点下去必须由顶栏处理（旧实现把命中判定写在
    # OverlayWindow 上，而那个位置的最上层控件就是顶栏，父窗口根本收不到点击）
    _gx = _tb.width() - 18
    _gy = _tb.height() / 2
    _hit = _ov.childAt(_tb.mapTo(_ov, _tb.rect().topLeft()).x() + int(_gx), int(_gy))
    assert _hit is _tb or _tb.isAncestorOf(_hit), f"齿轮位置最上层是 {_hit!r}，点不到顶栏"
    for _typ in (QEvent.Type.MouseButtonPress, QEvent.Type.MouseButtonRelease):
        _pt = QPointF(_gx, _gy)
        _tb.mousePressEvent(QMouseEvent(
            _typ, _pt, _pt, Qt.MouseButton.LeftButton, Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier))
    assert _fired, "点击齿轮没有打开设置"
    assert _tb._drag_offset is None, "点齿轮不该同时开始拖动窗口"
    # 悬停高亮
    _tb.mouseMoveEvent(QMouseEvent(
        QEvent.Type.MouseMove, QPointF(_gx, _gy), QPointF(_gx, _gy),
        Qt.MouseButton.NoButton, Qt.MouseButton.NoButton,
        Qt.KeyboardModifier.NoModifier))
    assert _tb._hover_gear is True, "齿轮悬停没有反馈"
    _tb.mouseMoveEvent(QMouseEvent(
        QEvent.Type.MouseMove, QPointF(40.0, _gy), QPointF(40.0, _gy),
        Qt.MouseButton.NoButton, Qt.MouseButton.NoButton,
        Qt.KeyboardModifier.NoModifier))
    assert _tb._hover_gear is False, "移开齿轮后悬停态没复位"
    # 齿轮不能压在时长文字上（末位被吃掉）
    _time_right = _tb.time_label.geometry().right()
    assert _gx - TopBar.GEAR_R > _time_right, \
        f"齿轮左沿 {_gx - TopBar.GEAR_R:.0f} 压住时长文字右边界 {_time_right}"
    _tb.set_score_name("夜空中最亮的星（超长曲名测试）" * 4)
    assert _tb.name_label.text().endswith("…"), _tb.name_label.text()
    _assert_w = QFontMetrics(_tb.name_label.font()).horizontalAdvance(
        _tb.name_label.text())
    assert _assert_w <= TopBar.NAME_MAX_W, f"省略后仍超宽 {_assert_w}"
    _tb.set_score_name(_orig_score.name)
    _ov.resize(_geo)
    _ov._save_timer.stop()                               # 别把自检的临时尺寸写进配置
    if not _was_visible:
        _ov.hide()
    print("[OK] v0.14.3 循环回绕清零 / 顶栏齿轮点击与留位 / 长曲名省略")

    # 17) v0.15.0：粘贴简谱导入 + 曲库刷新 / 打开曲目文件夹
    #     （这两个缺口是"用户真实需求"：EXE 里没有简谱解析入口，抄来一段数字谱只能
    #       一个音一个音点；手工放进 scores/ 的曲目必须重启程序才会出现）
    from harpguide.editor import EXAMPLE_JIANPU, JianpuPasteDialog
    from harpguide.jianpu import normalize_jianpu, scan_tokens

    # 17a) 预检：认不出来的 token 必须被点名（解析器对不认识的 token 是静默跳过的，
    #      不点名用户只会看到"少了一个音"，然后一个音一个音去对数）
    _ok, _bad = scan_tokens("| 1 2 3- 4 | 5 5 6-- 7 |")
    assert len(_ok) == 8 and not _bad, (_ok, _bad)
    _ok2, _bad2 = scan_tokens("| 1 2 Q 3 | ５ ６ ｜ 7 |")
    assert _bad2 == ["Q"], _bad2                 # 全角数字 / 全角竖线不该被算成错误
    assert len(_ok2) == 6, _ok2                  # 半角全角混写都要认
    # 落在最前面的延音线要报错（说明抄漏了它前面的音符）
    _ok3, _bad3 = scan_tokens("- 1 2")
    assert _bad3 == ["-"] and len(_ok3) == 2, (_ok3, _bad3)
    # 全角 / 中文标点自动归一
    assert normalize_jianpu("１、２，３；４").split() == ["1", "2", "3", "4"]
    assert normalize_jianpu("1－3") == "1-3"     # 全角减号 -> 半角延音线
    _s_full = parse_jianpu("｜ １ １ ５ ５ ｜ ６ ６ ５－ ｜", name="全角", bpm=100)
    assert [n.key for n in _s_full.notes] == ["Z", "Z", "B", "B", "N", "N", "B"], \
        [n.key for n in _s_full.notes]
    assert _s_full.notes[6].type is NoteType.HOLD     # ５－ 是长按
    _s_fwfrac = parse_jianpu("０.５:１ ０.５:２", name="全角分数", bpm=100)
    assert [n.duration for n in _s_fwfrac.notes] == [0.5, 0.5]

    # 17b) 粘贴对话框：实时预检 / 结果 Score（不 exec，避免模态阻塞自检）
    _dlg = JianpuPasteDialog(ed, default_name="起风了", default_bpm=88,
                             has_notes=True)
    assert not _dlg.btn_ok.isEnabled(), "空文本时不该允许载入"
    assert "还没有" in _dlg.preview.text()
    _dlg.text_edit.setPlainText(EXAMPLE_JIANPU)
    assert _dlg.btn_ok.isEnabled() and _dlg.append_mode() is False
    assert "识别" in _dlg.preview.text()
    _dlg.append_cb.setChecked(True)
    assert _dlg.append_mode() is True
    _dlg.bpm_spin.setValue(120)
    assert _dlg.preview.text() != "", "改 BPM 后预览必须跟着更新时长"
    _dlg.text_edit.setPlainText("| 1 2 Q 3 |")
    assert "认不出来" in _dlg.preview.text() and "Q" in _dlg.preview.text()
    _dlg.text_edit.setPlainText(EXAMPLE_JIANPU)
    _sc_j = _dlg.result_score()
    assert _sc_j.name == "起风了" and _sc_j.bpm == 120 and len(_sc_j.notes) == 28, \
        (_sc_j.name, _sc_j.bpm, len(_sc_j.notes))
    _dlg.resize(620, 420)
    assert not _dlg.grab().isNull()
    _dlg.deleteLater()

    # 17c) 替换 / 追加：替换可撤销；追加从现有内容末尾对齐整拍接上
    _ed_n0 = len(ed.grid.notes())
    ed.grid.set_notes(parse_jianpu("| 1 2 3 4 |", name="短", bpm=100).notes)
    assert len(ed.grid.notes()) == 4
    assert ed.grid.undo() and len(ed.grid.notes()) == _ed_n0, "粘贴替换必须是可撤销的"
    ed.grid.set_notes(parse_jianpu("| 1 2 3 4 |", name="短", bpm=100).notes)
    ed.grid.set_notes(parse_jianpu("| 5 6 7 8 |", name="尾", bpm=100).notes, append=True)
    _all = ed.grid.notes()
    assert len(_all) == 8, len(_all)
    assert _all[4].beat == 4.0, _all[4].beat      # 前一段占 4 拍 -> 后一段从第 4 拍起
    assert ed.grid.undo() and len(ed.grid.notes()) == 4
    # 空输入是空操作（不该平白往撤销栈里塞一份快照）
    _before_undo = ed.grid.can_undo()
    assert ed.grid.set_notes([]) == 0
    assert ed.grid.can_undo() == _before_undo

    # 17d) 刷新曲库：外部新增的曲目刷新后立刻可见；当前曲目被改过时无缝换入，
    #      位置与播放状态保留（用户改完 JSON 想立刻听效果，不该被打回开头）
    _reload_root = _Path(tempfile.mkdtemp())
    (_reload_root / "scores").mkdir(parents=True)
    _probe_notes = [_Note("Z", NoteType.TAP, 1.0, 0.0),
                    _Note("X", NoteType.TAP, 1.0, 1.0)]
    _Sc(id="probe", name="刷新探针", bpm=100, notes=_probe_notes).save(
        _reload_root / "scores" / "probe.json")
    _orig_dd = (_appmod.data_dir, _appmod.app_root)
    _appmod.data_dir = lambda: _reload_root
    # app_root 也要一起指过去：非打包态的内建目录就是项目目录，
    # 只改 data_dir 会连带把真实项目里的 26 首曲库一起扫进来。
    _appmod.app_root = lambda: _reload_root
    try:
        # 打包态除了用户目录，还会从 sys._MEIPASS 读到 26 首内建曲目，
        # 所以这里只断言"探针被当作用户曲目读进来了"，不依赖曲库总数。
        controller.reload_scores()
        _by_id = {s.id: s for s in controller.scores}
        assert "probe" in _by_id, sorted(_by_id)
        assert _by_id["probe"].builtin is False, "用户目录里的曲目不该被标成内置只读"
        assert _by_id["probe"].name == "刷新探针"
        # 刷新后当前曲目必须仍能从列表里解析出来（要么原样保留，要么退回第一首）
        assert controller._pick_score(controller.engine.score.id) is not None
        # 把它当成"正在吹的那一首"，验证外部改动后的无缝换入
        controller._select_score("probe")
        assert controller._pick_score("probe") is not None
        _Sc(id="probe", name="刷新探针", bpm=120, notes=_probe_notes).save(
            _reload_root / "scores" / "probe.json")
        controller.engine.seek(600.0)
        _pos_before = controller.engine.position_ms()
        controller.reload_scores()
        assert controller.engine.score.bpm == 120, controller.engine.score.bpm
        assert abs(controller.engine.position_ms() - _pos_before) < 1.0, \
            "刷新把播放位置打回开头了"
        # 内容没变时再刷一次：不得重建曲目对象（避免无谓地重置判定状态）
        _same = controller.engine.score
        controller.reload_scores()
        assert controller.engine.score is _same, "内容没变时不该换掉当前曲目"
    finally:
        _appmod.data_dir, _appmod.app_root = _orig_dd
        shutil.rmtree(_reload_root, ignore_errors=True)
        controller.scores = controller._load_scores() or controller._builtin_scores()
        controller.overlay.sidebar.set_scores(controller.scores, _orig_score.id)
        controller.settings.last_score_id = _orig_score.id
    ed.load_score(_orig_score)          # 编辑区还原成常规底稿
    print("[OK] 粘贴简谱（预检点名/全角归一/替换可撤销/追加整拍对齐）+ 曲库刷新（外部改动无缝换入）")

    # 块尾还原：引擎、设置、判定状态
    controller.settings.hit_feedback = _orig_fb
    controller.overlay.waterfall.set_feedback_enabled(_orig_fb)
    controller.engine.set_score(_orig_score)
    controller.overlay.set_score(_orig_score)
    controller._reset_feedback(controller.engine.position_ms())

    # 收尾：把设置路径还原成用户真实配置文件（自检全程只写临时文件）
    controller.settings._path = _real_settings_path

    print("SELFTEST PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
