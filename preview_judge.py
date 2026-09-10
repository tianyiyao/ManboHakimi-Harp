# -*- coding: utf-8 -*-
"""命中判定/偏移提示渲染预览（离屏）。"""
import sys
from pathlib import Path

from PySide6.QtWidgets import QApplication

sys.path.insert(0, str(Path(__file__).parent))
from harpguide.app import AppController
from harpguide.theme import THEME

OUT = Path(__file__).parent / "preview"
OUT.mkdir(exist_ok=True)

app = QApplication([])
app.setApplicationName("ManboHakimi-Harp")
ctl = AppController(app)

ctl.overlay.resize(640, 520)
ctl.overlay.show()
ctl.overlay.waterfall.set_feedback_enabled(True)

wf = ctl.overlay.waterfall
keys = ctl.overlay.keys

# 模拟：整体按晚 220ms（顶栏应显示「偏移 +220ms」并呈橙色提示要调偏移）
ctl.settings.judge_offset_ms = 0
for i in range(6):
    ctl._record_offset(220.0)
wf.push_judgment(1, "GOOD", THEME.primary)
wf.push_judgment(4, "GREAT", THEME.success)
wf.set_combo(7, 640)
keys.flash_hit(1, THEME.primary)
keys.flash_hit(4, THEME.success)
wf.set_real_ms(1200.0)
app.processEvents()
ctl.overlay.grab().save(str(OUT / "judge_offset.png"))

# 对齐后（偏移设定 = 实测均值）：顶栏应变绿
ctl._set_judge_offset(220)
for i in range(6):
    ctl._record_offset(18.0)
app.processEvents()
ctl.overlay.grab().save(str(OUT / "judge_offset_aligned.png"))
print("saved judge_offset.png / judge_offset_aligned.png",
      "| 顶栏文字:", repr(ctl.overlay.topbar.offset_label.text()))
