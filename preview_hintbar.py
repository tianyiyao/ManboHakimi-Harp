# -*- coding: utf-8 -*-
"""底部热键提示条渲染预览（离屏，宽/窄两种宽度）。"""
import sys
from pathlib import Path

from PySide6.QtWidgets import QApplication

sys.path.insert(0, str(Path(__file__).parent))
from harpguide.app import AppController
from preview_font import install_cjk_fonts

OUT = Path(__file__).parent / "preview"
OUT.mkdir(exist_ok=True)

app = QApplication([])
app.setApplicationName("ManboHakimi-Harp")
# 离屏平台不做系统字体枚举，必须显式挂载中文字体文件，否则截图里中文全是方块
install_cjk_fonts(app)
ctl = AppController(app)

# 宽窗口：提示条单行
ctl.overlay.resize(720, 520)
ctl.overlay.show()
app.processEvents()
ctl.overlay.grab().save(str(OUT / "hintbar_wide.png"))

# 窄窗口：提示条自动换行
ctl.overlay.resize(380, 560)
app.processEvents()
ctl.overlay.grab().save(str(OUT / "hintbar_narrow.png"))

# 单独抓提示条本体（放大观看排版）
bar = ctl.overlay.hotkeybar
bar.grab().save(str(OUT / "hintbar_only.png"))

print("saved hintbar_wide.png / hintbar_narrow.png / hintbar_only.png",
      "rows@720 =", bar.height_for_width(700) // 21,
      "rows@380 =", bar.height_for_width(360) // 21)
