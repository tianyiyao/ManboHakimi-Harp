# -*- coding: utf-8 -*-
"""离屏渲染的中文字形修复（预览截图专用，不参与打包）。

问题
----
`QT_QPA_PLATFORM=offscreen` 下，Qt 的 offscreen 插件**不做系统字体枚举**：
`QFontDatabase.families()` 返回空列表。于是业务代码里
`QFont("Microsoft YaHei", 11)`、`QFont("Consolas", 10)` 这类**显式指定族名**
的调用全部匹配失败，一路回退到无字形的 "Sans Serif"，
截图里的中文就渲染成一排方块（豆腐块）。

修复
----
`QFontDatabase.addApplicationFont()` 是**直接读字体文件注册**的，
不依赖系统字体枚举，离屏下同样有效。注册后族名就是文件里的真实族名
（msyh.ttc -> "Microsoft YaHei"），与 `theme.THEME.font_sans` /
`font_mono` 的常量天然对上，因此**业务代码一行都不用改**。

用法
----
    app = QApplication([])
    install_cjk_fonts(app)      # 必须在 QApplication 之后
"""
from __future__ import annotations

from pathlib import Path
from typing import List

from PySide6.QtGui import QFont, QFontDatabase

# 按优先级排列：微软雅黑（界面正文）-> Consolas（数值/键位）-> 黑体（兜底）
_FONT_FILES = [
    r"C:\Windows\Fonts\msyh.ttc",      # Microsoft YaHei
    r"C:\Windows\Fonts\msyhbd.ttc",    # Microsoft YaHei Bold
    r"C:\Windows\Fonts\consola.ttf",   # Consolas
    r"C:\Windows\Fonts\consolab.ttf",  # Consolas Bold
    r"C:\Windows\Fonts\simhei.ttf",    # SimHei
]

# 注册成功后优先用作应用默认字体的族
_PREFERRED = ("Microsoft YaHei", "SimHei")


def install_cjk_fonts(app) -> List[str]:
    """把系统字体文件注册进 Qt，并设为应用默认字体。返回注册到的族名列表。"""
    families: List[str] = []
    for path in _FONT_FILES:
        if not Path(path).exists():
            continue
        fid = QFontDatabase.addApplicationFont(path)
        if fid < 0:
            continue
        for fam in QFontDatabase.applicationFontFamilies(fid):
            if fam and fam not in families:
                families.append(fam)

    for fam in _PREFERRED:
        if fam in families:
            app.setFont(QFont(fam, 9))
            break
    else:
        if families:
            app.setFont(QFont(families[0], 9))

    print(f"[preview] 已注册字体族: {families if families else '（无，中文会显示为方块）'}")
    return families
