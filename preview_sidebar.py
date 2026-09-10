# -*- coding: utf-8 -*-
"""离屏渲染验证：曲目侧边栏的「缩进」与「悬停展开」两种状态。

离屏环境没有事件循环，动画不会自己走完，所以直接
setCurrentTime(duration) 把宽度动画推到终点再截图。
"""
import sys
from pathlib import Path

from PySide6.QtWidgets import QApplication

sys.path.insert(0, str(Path(__file__).parent))
from harpguide.app import AppController

OUT = Path(__file__).parent / "preview"
OUT.mkdir(exist_ok=True)

app = QApplication([])
app.setApplicationName("ManboHakimi-Harp")
ctl = AppController(app)

overlay = ctl.overlay
sb = overlay.sidebar
overlay.resize(600, 480)
overlay.show()
app.processEvents()

# 1) 收起态：只剩 22px 把手
sb.collapse()
sb._anim.setCurrentTime(sb._anim.duration())
app.processEvents()
sb.grab().save(str(OUT / "sidebar_collapsed.png"))

# 2) 悬停展开态
sb.expand()
sb._anim.setCurrentTime(sb._anim.duration())
app.processEvents()
sb.grab().save(str(OUT / "sidebar_expanded.png"))

# 3) 放进浮窗里看整体位置（展开时盖住左侧内容，收起时只留把手）
overlay.grab().save(str(OUT / "sidebar_in_overlay.png"))
sb.collapse()
sb._anim.setCurrentTime(sb._anim.duration())
app.processEvents()
overlay.grab().save(str(OUT / "sidebar_in_overlay_collapsed.png"))

print("saved:", sorted(p.name for p in OUT.glob("sidebar*.png")))
