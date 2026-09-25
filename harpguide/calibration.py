# -*- coding: utf-8 -*-
"""校准数据层：琴键自由布局几何 + 按分辨率持久化。

背景：游戏内键位大小/间距随分辨率与窗口模式变化，固定 8 等分网格无法
完全贴合。校准模式允许用户把每个琴键提示拖到与游戏键位重合的位置，
瀑布流音轨会自动对齐校准后的琴键中心。

坐标系：KeyHintWidget 内部坐标（键中心 x/y + 正方形边长 size）。
浮窗宽度固定 600，所以坐标可直接持久化复用。

文件结构 config/calibration.json：
{
  "version": 1,
  "profiles": {
    "1920x1080": { "keys": [{"x":..,"y":..,"size":..}, ...8 项] }
  }
}
"""
from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

from .config import data_dir
from .storage import write_json_atomic

KEY_COUNT = 8
DEFAULT_KEY_SIZE = 64.0
DEFAULT_KEY_GAP = 10.0
DEFAULT_TOP_Y = 14.0            # 默认网格顶部留白
MIN_KEY_SIZE = 24.0
MAX_KEY_SIZE = 110.0


@dataclass
class KeyGeom:
    """单个琴键提示的几何：中心坐标 + 边长（正方形）。"""
    x: float
    y: float
    size: float


def default_geometries(widget_width: float) -> List[KeyGeom]:
    """默认 8 键网格（与 v0.3 布局一致）。"""
    total = DEFAULT_KEY_SIZE * KEY_COUNT + DEFAULT_KEY_GAP * (KEY_COUNT - 1)
    x0 = (widget_width - total) / 2
    return [
        KeyGeom(
            x=x0 + DEFAULT_KEY_SIZE / 2 + i * (DEFAULT_KEY_SIZE + DEFAULT_KEY_GAP),
            y=DEFAULT_TOP_Y + DEFAULT_KEY_SIZE / 2,
            size=DEFAULT_KEY_SIZE,
        )
        for i in range(KEY_COUNT)
    ]


def resolution_key(widget=None) -> str:
    """当前屏幕标识，如 "1920x1080@1.5"（物理分辨率 @ 缩放比）。

    为什么带上 devicePixelRatio：
    同一块屏在 100% / 125% / 150% 缩放下，Qt 的逻辑坐标尺寸是一样的，
    但浮窗的物理像素尺寸完全不同——如果只按逻辑分辨率分档，换缩放比例
    后旧校准会带着错的像素偏移被套用。带上 DPR 就能各自独立保存。

    优先取浮窗所在屏幕（多显示器时校准的是浮窗那一块屏），
    取不到再退回主屏；离屏环境返回 "default"。
    """
    try:
        from PySide6.QtGui import QGuiApplication
        scr = None
        if widget is not None:
            try:
                scr = widget.screen()
            except Exception:
                scr = None
        if scr is None:
            scr = QGuiApplication.primaryScreen()
        if scr is None:
            return "default"
        g = scr.geometry()
        dpr = float(scr.devicePixelRatio()) or 1.0
        return f"{round(g.width() * dpr)}x{round(g.height() * dpr)}@{dpr:g}"
    except Exception:
        return "default"


def clamp_geom(g: KeyGeom, widget_w: float, widget_h: float) -> KeyGeom:
    """把键几何限制在部件范围内。"""
    size = max(MIN_KEY_SIZE, min(MAX_KEY_SIZE, g.size))
    x = max(size / 2, min(widget_w - size / 2, g.x))
    y = max(size / 2, min(widget_h - size / 2, g.y))
    return KeyGeom(x=x, y=y, size=size)


@dataclass
class CalibrationData:
    """多分辨率校准方案集合。"""
    profiles: Dict[str, List[KeyGeom]] = field(default_factory=dict)
    # 显式指定的档案键（浮窗所在屏幕）。为空时退回主屏检测。
    screen_key: str = ""
    _path: Path = field(default_factory=lambda: data_dir() / "config" / "calibration.json",
                        repr=False, compare=False)

    # ---- 读取 ----
    def current_key(self) -> str:
        return self.screen_key or resolution_key()

    def profile(self, res: Optional[str] = None) -> Optional[List[KeyGeom]]:
        key = res or self.current_key()
        return self.profiles.get(key)

    # ---- 持久化 ----
    def set_profile(self, geoms: List[KeyGeom], res: Optional[str] = None) -> None:
        key = res or self.current_key()
        self.profiles[key] = [KeyGeom(g.x, g.y, g.size) for g in geoms]

    def clear_profile(self, res: Optional[str] = None) -> None:
        key = res or self.current_key()
        self.profiles.pop(key, None)

    def save(self) -> None:
        data = {
            "version": 1,
            "profiles": {
                res: {"keys": [{"x": g.x, "y": g.y, "size": g.size} for g in geoms]}
                for res, geoms in self.profiles.items()
            },
        }
        try:
            write_json_atomic(self._path, data)
        except (OSError, TypeError, ValueError) as e:
            print(f"[Calibration] 保存失败: {e}")

    @classmethod
    def load(cls, path: Optional[Path] = None) -> "CalibrationData":
        cal = cls()
        if path is not None:
            cal._path = Path(path)
        if cal._path.exists():
            try:
                raw = json.loads(cal._path.read_text(encoding="utf-8"))
                profiles = raw.get("profiles", {})
                if not isinstance(profiles, dict):
                    raise ValueError("profiles 必须是对象")
                for res, prof in profiles.items():
                    if not isinstance(prof, dict):
                        continue
                    keys = prof.get("keys", [])
                    if not isinstance(keys, list) or len(keys) != KEY_COUNT:
                        continue
                    try:
                        geoms = [
                            KeyGeom(float(k["x"]), float(k["y"]), float(k["size"]))
                            for k in keys
                        ]
                    except (KeyError, TypeError, ValueError, OverflowError):
                        continue
                    if all(math.isfinite(g.x) and math.isfinite(g.y)
                           and math.isfinite(g.size) and g.size > 0 for g in geoms):
                        cal.profiles[str(res)] = geoms
            except (json.JSONDecodeError, OSError, AttributeError, TypeError, ValueError) as e:
                print(f"[Calibration] 读取失败，忽略校准文件: {e}")
        return cal
