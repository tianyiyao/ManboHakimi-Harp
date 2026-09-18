# -*- coding: utf-8 -*-
"""生成修复后的视觉证据图（离屏渲染，只读工程，不改任何配置）。"""
import os
import sys
import tempfile
from pathlib import Path

os.environ["QT_QPA_PLATFORM"] = "offscreen"
REPO = Path(r"C:\Users\Administrator\WorkBuddy\2026-09-10-08-55-04\ManboHakimi-Harp")
OUT = REPO / "preview"           # 与其它 preview_*.py 的产物放一起（入库）
sys.path.insert(0, str(REPO))

from PySide6.QtCore import QPointF, Qt                   # noqa: E402
from PySide6.QtGui import (QColor, QFont, QFontDatabase, QPainter,  # noqa: E402
                           QPen, QPixmap)
from PySide6.QtWidgets import QApplication               # noqa: E402

from harpguide.app import AppController                  # noqa: E402
from harpguide.theme import THEME                        # noqa: E402

app = QApplication(sys.argv)
# 离屏环境没有系统字体库：注册微软雅黑，否则中文全是方框（豆腐块）
for _f in (r"C:\Windows\Fonts\msyh.ttc", r"C:\Windows\Fonts\msyhbd.ttc",
           r"C:\Windows\Fonts\simhei.ttf"):
    QFontDatabase.addApplicationFont(_f)
controller = AppController(app)
controller.settings._path = Path(tempfile.gettempdir()) / "preview_settings.json"
controller.settings.judge_offset_ms = 0
controller.settings.hit_feedback = True

ov, tb, wf = controller.overlay, controller.overlay.topbar, controller.overlay.waterfall
ov.resize(600, 480)
ov.show()
app.processEvents()

SCALE = 2


def _annotate(p: QPainter, lines, x, y):
    p.setFont(QFont(THEME.font_sans, 10))
    p.setPen(QColor("#E8EDF5"))
    for i, t in enumerate(lines):
        p.drawText(x, y + i * 20, t)


# ---------------------------------------------------------------- 图 1：顶栏
# 注：不能直接 tb.grab()——离屏下子控件抓图会填默认浅色调色板，近白色文字就看不见了。
# 抓整个浮窗（自带深色底）再裁出顶栏那一条。
def _topbar_strip() -> QPixmap:
    app.processEvents()
    return ov.grab().copy(0, 0, ov.topbar.width(), ov.topbar.height())


strips = []
tb.set_score_name(controller.engine.score.name)
tb._hover_gear = False
strips.append(("① 常规：齿轮（浅灰）与时长之间留出 9.4px，末位不再被压住", _topbar_strip()))
tb._hover_gear = True
strips.append(("② 鼠标悬停齿轮：高亮加粗 + 手型光标（点下去直接开设置）", _topbar_strip()))
tb._hover_gear = False
tb.set_score_name("夜空中最亮的星（指弹改编版·降B调·练习用超长曲名测试）")
strips.append(("③ 超长曲名：省略号收尾（225px），BPM / 时长不被挤出窗口", _topbar_strip()))
tb.set_score_name(controller.engine.score.name)

W = max(pm.width() for _l, pm in strips) * SCALE
H = 40 + sum(44 * SCALE + 34 for _ in strips)
img = QPixmap(W, H)
img.fill(QColor(THEME.background))
p = QPainter(img)
y = 10
for label, pm in strips:
    _annotate(p, [label], 16, y + 14)
    y += 24
    p.drawPixmap(0, y, pm.scaled(pm.width() * SCALE, pm.height() * SCALE,
                                 Qt.AspectRatioMode.IgnoreAspectRatio,
                                 Qt.TransformationMode.SmoothTransformation))
    # 标出齿轮中心与时长文字右边界，方便肉眼核对间距
    gx = (tb.width() - 18) * SCALE
    p.setPen(QPen(QColor("#FF5252"), 1.4, Qt.PenStyle.DashLine))
    p.drawLine(gx, y, gx, y + 44 * SCALE)
    y += 44 * SCALE + 10
p.end()
img.save(str(OUT / "topbar_gear_and_time.png"))
print("已生成 preview/topbar_gear_and_time.png")

# ------------------------------------------------------- 图 2：预备拍 / 连击
wf.show()
app.processEvents()
shots = []
# 预备拍：pos < 0，连击不画（否则默认 220px 高的瀑布流里会和倒计时叠字）
wf.set_combo(5, 300)
wf._real_ms = 1000.0
wf._combo_born = 1000.0
png = QPixmap(wf.width(), wf.height())
png.fill(QColor("#00000000"))
p = QPainter(png)
wf._paint_count_in(p, -1200.0)
wf._paint_feedback(p, -1200.0)
p.end()
shots.append(("① 预备拍（pos = -1200ms）：只画倒计时，连击数字不画 -> 不叠字", png))
png2 = QPixmap(wf.width(), wf.height())
png2.fill(QColor("#00000000"))
p = QPainter(png2)
wf._paint_count_in(p, 1200.0)
wf._paint_feedback(p, 1200.0)
p.end()
shots.append(("② 演奏中（pos = 1200ms，连击 5）：只画连击，倒计时自然消失", png2))

W2 = wf.width() * SCALE
H2 = sum(wf.height() * SCALE + 40 for _ in shots) + 20
img2 = QPixmap(W2, H2)
img2.fill(QColor(THEME.background))
p = QPainter(img2)
y = 10
for label, pm in shots:
    _annotate(p, [label], 16, y + 14)
    y += 24
    p.drawPixmap(0, y, pm.scaled(pm.width() * SCALE, pm.height() * SCALE,
                                 Qt.AspectRatioMode.IgnoreAspectRatio,
                                 Qt.TransformationMode.SmoothTransformation))
    y += wf.height() * SCALE + 8
p.end()
img2.save(str(OUT / "countin_no_combo.png"))
print("已生成 preview/countin_no_combo.png")
