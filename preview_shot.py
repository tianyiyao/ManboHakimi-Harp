# -*- coding: utf-8 -*-
"""离屏渲染验证：截取关键时间点的浮窗画面。"""
import sys
from pathlib import Path

from PySide6.QtWidgets import QApplication

sys.path.insert(0, str(Path(__file__).parent))
from harpguide.app import AppController
from harpguide.models import NoteType

OUT = Path(__file__).parent / "preview"
OUT.mkdir(exist_ok=True)

app = QApplication([])
app.setApplicationName("ManboHakimi-Harp")
ctl = AppController(app)
score = ctl.engine.score

ctl.overlay.resize(600, 442)

# 时刻1：长按音符进行中（中段）
hold = next(n for n in score.notes if n.type is NoteType.HOLD)
mid = (hold.start_ms(score.bpm) + hold.end_ms(score.bpm)) / 2
ctl.engine.seek(mid)
ctl.overlay.show()
ctl.overlay.keys.tick(mid, 1500.0)
ctl.overlay.update_time(mid, ctl.engine.total_ms())
ctl.overlay.waterfall.update()
app.processEvents()
ctl.overlay.grab().save(str(OUT / "hold_mid.png"))

# 时刻2：接近松开（最后 10%）
near = hold.end_ms(score.bpm) - hold.duration_ms(score.bpm) * 0.1
ctl.engine.seek(near)
ctl.overlay.keys.tick(near, 1600.0)
ctl.overlay.update_time(near, ctl.engine.total_ms())
ctl.overlay.waterfall.update()
app.processEvents()
ctl.overlay.grab().save(str(OUT / "hold_release.png"))

# 时刻3：预备拍
ctl.engine.seek(ctl.engine.start_ms() + 200)
app.processEvents()
ctl.overlay.grab().save(str(OUT / "countin.png"))

# 时刻4：悬浮球
ctl.ball.set_playing(True)
ctl.ball.set_note_char("C")
ctl.ball.tick(800.0)
ctl.ball.show()
app.processEvents()
ctl.ball.grab().save(str(OUT / "ball.png"))

# 设置面板（曲目列表 v0.14 起已迁到左侧边栏，见 preview_sidebar.py）
ctl.panel.show()
app.processEvents()
ctl.panel.grab().save(str(OUT / "panel.png"))

print("saved:", [p.name for p in OUT.glob("*.png")])
