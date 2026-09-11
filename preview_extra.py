# -*- coding: utf-8 -*-
"""离屏渲染：乐谱编辑器 / 琴键校准模式。

这两张图的早期生成脚本在项目整理时丢了，README 一直在引用旧图（中文是方块）。
这里补回生成流程，与其它 preview_*.py 保持同一套中文字体修复。
"""
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

# 1) 乐谱编辑器（钢琴卷帘）
ctl.toggle_editor()
app.processEvents()
ed = ctl.editor
ed.resize(980, 420)
app.processEvents()
ed.grab().save(str(OUT / "editor.png"))

# 2) 琴键校准模式：浮窗进入校准态 + 校准面板
ctl.overlay.resize(600, 442)
ctl.overlay.show()
app.processEvents()
ctl._enter_calibration()
app.processEvents()
ctl.overlay.grab().save(str(OUT / "calibration_mode.png"))
ctl._exit_calibration()
app.processEvents()
ctl.overlay.grab().save(str(OUT / "calibrated_play.png"))

print("saved: editor.png / calibration_mode.png / calibrated_play.png")
