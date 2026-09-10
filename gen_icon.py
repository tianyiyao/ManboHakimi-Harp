# -*- coding: utf-8 -*-
"""生成 ManboHakimi-Harp 图标（64/256px PNG + ICO）。"""
import struct
import sys
from pathlib import Path

from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import (QBrush, QColor, QFont, QImage, QPainter, QPen,
                           QRadialGradient)

sys.path.insert(0, str(Path(__file__).parent))
from harpguide.theme import THEME

OUT = Path(__file__).parent / "assets"
OUT.mkdir(exist_ok=True)


def draw(size: int) -> QImage:
    img = QImage(size, size, QImage.Format.Format_ARGB32)
    img.fill(Qt.GlobalColor.transparent)
    p = QPainter(img)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    c = QPointF(size / 2, size / 2)
    r = size * 0.4

    # 青蓝径向发光
    halo = QRadialGradient(c, size * 0.5)
    halo.setColorAt(0, QColor(0, 229, 255, 60))
    halo.setColorAt(1, QColor(0, 229, 255, 0))
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QBrush(halo))
    p.drawEllipse(c, size * 0.5, size * 0.5)

    # 深色圆球
    p.setBrush(QColor(19, 24, 32, 245))
    p.setPen(QPen(QColor(0, 229, 255), size * 0.03))
    p.drawEllipse(c, r, r)

    # ♪ 音符（字体绘制）
    p.setFont(QFont("Segoe UI Symbol", int(size * 0.42), QFont.Weight.Bold))
    p.setPen(QColor(THEME.primary))
    p.drawText(int(0), int(0), int(size), int(size),
               int(Qt.AlignmentFlag.AlignCenter), "♪")
    p.end()
    return img


png = draw(256)
png_path = OUT / "icon.png"
png.save(str(png_path))

# PNG-in-ICO（Windows Vista+ 支持）
data = png_path.read_bytes()
header = struct.pack("<HHH", 0, 1, 1)
entry = struct.pack("<BBBBHHII", 0, 0, 0, 0, 1, 32,
                    len(data), 6 + 16)
(OUT / "icon.ico").write_bytes(header + entry + data)
print("icon ->", OUT / "icon.ico")
