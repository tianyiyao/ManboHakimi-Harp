# -*- coding: utf-8 -*-
"""命中反馈渲染预览（离屏）。"""
import sys
from pathlib import Path

from PySide6.QtWidgets import QApplication

sys.path.insert(0, str(Path(__file__).parent))
from harpguide.app import AppController
from harpguide.models import NoteType
from harpguide.theme import THEME
from preview_font import install_cjk_fonts

OUT = Path(__file__).parent / "preview"
OUT.mkdir(exist_ok=True)

app = QApplication([])
app.setApplicationName("ManboHakimi-Harp")
# 离屏平台不做系统字体枚举，必须显式挂载中文字体文件，否则截图里中文全是方块
install_cjk_fonts(app)
ctl = AppController(app)
score = ctl.engine.score

ctl.overlay.resize(600, 470)
ctl.overlay.show()
ctl.overlay.waterfall.set_feedback_enabled(True)

# 模拟若干判定反馈
wf = ctl.overlay.waterfall
keys = ctl.overlay.keys
note = next(n for n in score.notes if n.type is not NoteType.HOLD)
pos = note.start_ms(score.bpm)

wf.set_real_ms(1000.0)
ctl.overlay.keys.tick(pos, 1000.0)
ctl.overlay.update_time(pos, ctl.engine.total_ms())

# 三条不同判定 + 连击 + 得分
wf.push_judgment(0, "PERFECT", THEME.gold)
wf.push_judgment(3, "GREAT", THEME.success)
wf.push_judgment(5, "MISS", THEME.danger)
wf.set_combo(12, 1234)
keys.flash_hit(0, THEME.gold)
keys.flash_hit(3, THEME.success)
keys.flash_hit(5, THEME.danger)
wf.update()
app.processEvents()
ctl.overlay.grab().save(str(OUT / "feedback.png"))

# 无反馈对照
wf.clear_feedback()
keys.clear_feedback()
app.processEvents()
ctl.overlay.grab().save(str(OUT / "feedback_off.png"))

print("saved feedback.png / feedback_off.png")
