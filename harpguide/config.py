# -*- coding: utf-8 -*-
"""配置持久化：settings.json / 首次启动标记。

数据目录优先使用 EXE 同级目录（便携模式）；不可写时回退 %APPDATA%/ManboHakimi-Harp。
"""
from __future__ import annotations

import json
import os
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Optional


APP_NAME = "ManboHakimi-Harp"
_LEGACY_APP_NAME = "HarpGuide"      # 旧项目名（v0.12 及以前），用于数据目录迁移


def app_root() -> Path:
    """程序根目录：PyInstaller 打包后为 EXE 所在目录，开发时为项目目录。"""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).parent.parent


def _migrate_legacy_dir(base: Path) -> None:
    """把旧名目录（%APPDATA%/HarpGuide）里的数据搬到新名目录，避免升级后丢配置。

    只在「新目录还没有 settings.json」时才搬，且任一环节失败都静默跳过——
    迁移失败最多是回到默认设置，绝不能因此让程序起不来。
    """
    try:
        legacy = base.parent / _LEGACY_APP_NAME
        if legacy == base or not legacy.is_dir():
            return
        if (base / "config" / "settings.json").exists():
            return
        import shutil
        if not (base / "config").exists():
            (base / "config").mkdir(parents=True, exist_ok=True)
        for name in ("config", "scores"):
            src, dst = legacy / name, base / name
            if not src.is_dir():
                continue
            dst.mkdir(parents=True, exist_ok=True)
            for item in src.iterdir():
                if item.is_file() and not (dst / item.name).exists():
                    shutil.copy2(item, dst / item.name)
    except Exception:
        pass


def data_dir() -> Path:
    root = app_root()
    try:
        (root / "config").mkdir(parents=True, exist_ok=True)
        probe = root / "config" / ".probe"
        probe.write_text("", encoding="utf-8")
        probe.unlink()
        # 主路径也要确保 scores/ 存在，用户保存/另存为曲目时会写到这。
        (root / "scores").mkdir(parents=True, exist_ok=True)
        return root
    except OSError:
        base = Path(os.environ.get("APPDATA", str(Path.home()))) / APP_NAME
        (base / "config").mkdir(parents=True, exist_ok=True)
        (base / "scores").mkdir(parents=True, exist_ok=True)
        _migrate_legacy_dir(base)
        return base


@dataclass
class Settings:
    # 播放
    speed_multiplier: float = 1.0
    loop: bool = False
    count_in_beats: int = 4          # 预备拍数（0 = 关闭）
    # 显示
    opacity: float = 0.82            # 浮窗整体不透明度
    waterfall_height: int = 220      # 瀑布流区高度 px（派生自窗口高度，可被滑杆覆盖）
    pixels_per_beat: int = 44        # 每拍对应的像素高度（影响长按音符视觉长度）
    lookahead_ms: int = 2000         # 音符从顶部滑到判定线的耗时（越大越慢）
    show_beat_lines: bool = True
    hold_shine: bool = True          # 长按音符流光动画
    countdown_warning: bool = True   # 松开前橙色预警
    preparation_lead_beats: float = 2.0  # 长按预亮提前量（拍）
    show_lyrics: bool = True         # 显示歌词提示区
    show_hotkeys: bool = True        # 底部热键提示条（键帽 + 说明）
    auto_transpose: bool = False     # 半音阶口风琴：自动跟随歌曲调性档（免手动小键盘切调）
    hit_feedback: bool = True        # 命中反馈：判定/连击/得分（被动轮询 8 键，不拦截按键）
    judge_offset_ms: int = 0         # 判定偏移（ms）：补偿玩家固定偏早/偏晚的手感
    # 窗口
    window_x: int = 240
    window_y: int = 160
    window_w: int = 600              # 浮窗宽度（用户可拖拽调整）
    window_h: int = 504              # 浮窗高度（用户可拖拽调整）
    click_through: bool = False      # 鼠标穿透
    last_score_id: str = ""
    risk_accepted: bool = False      # 风险声明已确认
    # A-B 段落循环：score_id -> [A 拍, B 拍]
    loop_ranges: dict = field(default_factory=dict)

    _path: Path = field(default_factory=lambda: data_dir() / "config" / "settings.json",
                        repr=False, compare=False)

    # ---- 持久化 ----
    def save(self) -> None:
        d = {k: v for k, v in asdict(self).items() if not k.startswith("_")}
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            self._path.write_text(
                json.dumps(d, ensure_ascii=False, indent=2), encoding="utf-8")
        except OSError as e:
            print(f"[Settings] 保存失败: {e}")

    @classmethod
    def load(cls, path: Optional[Path] = None) -> "Settings":
        s = cls()
        if path is not None:
            s._path = Path(path)
        if s._path.exists():
            try:
                data = json.loads(s._path.read_text(encoding="utf-8"))
                for k, v in data.items():
                    if hasattr(s, k):
                        setattr(s, k, v)
            except (json.JSONDecodeError, OSError) as e:
                print(f"[Settings] 读取失败，使用默认配置: {e}")
        # loop_ranges 可能被写坏成非 dict，兜一下
        if not isinstance(s.loop_ranges, dict):
            s.loop_ranges = {}
        return s
