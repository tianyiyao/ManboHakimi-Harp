# -*- coding: utf-8 -*-
"""曲目侧边栏：吸附在浮窗左边缘的悬浮抽屉（v0.14）。

替换原先「点设置按钮才能看到曲目列表」的交互：

- 收起态只露出 22px 宽的把手，**永远可见**（保留部分延伸），鼠标够得到
- 鼠标移进把手 -> 自动展开成完整曲目列表；移开 -> 延时自动收回
- 实现方式是 OverlayWindow 的子部件 + 移动自身 geometry，超出父窗口的
  部分由 Qt 自动裁剪，于是形成「从左边滑出 / 缩进」的观感
- 非模态、不抢焦点：不弹窗、不遮游戏按键，纯粹是个抽屉

交互细节：
- 展开是即时的，收起有 450ms 延时，避免鼠标蹭过时反复抽搐
- 收起前会用 QCursor 真实位置二次确认，防止子部件 enter/leave 抖动误收
- 点击曲目后自动收回，选完就走
"""
from __future__ import annotations

from typing import List, Optional

from PySide6.QtCore import (QEasingCurve, QPoint, QPointF, QPropertyAnimation,
                            QRect, QRectF, Qt, QTimer, Signal)
from PySide6.QtGui import (QAction, QColor, QCursor, QFont, QPainter, QPen,
                           QPolygonF)
from PySide6.QtWidgets import (QDialog, QHBoxLayout, QInputDialog, QLabel, QMenu,
                               QMessageBox, QPushButton, QScrollArea,
                               QVBoxLayout, QWidget)

from .config import Settings
from .models import Score
from .theme import THEME


def _exec_topmost(dialog: QWidget) -> int:
    """把模态对话框置顶后 exec，防止被游戏等全屏窗口压在后面。"""
    dialog.setWindowFlags(dialog.windowFlags() | Qt.WindowType.WindowStaysOnTopHint)
    dialog.raise_()
    dialog.activateWindow()
    return dialog.exec()


class ScoreSidebar(QWidget):
    """左侧曲目抽屉。

    geometry 语义：x 恒为 0，y/height 由 OverlayWindow.set_span() 给定，
    动画只改 width —— 22px（把手）<-> PANEL_W（完整列表）。
    """

    score_selected = Signal(str)           # score_id
    score_renamed = Signal(str, str)       # score_id, new_name
    score_deleted = Signal(str)            # score_id
    edit_requested = Signal(str)           # 在编辑器中打开该曲目

    HANDLE_W = 22                # 收起后仍然可见的把手宽度
    PANEL_W = 238                # 展开宽度
    RADIUS = 12
    ANIM_MS = 170
    COLLAPSE_DELAY_MS = 450      # 移开后多久收回（给鼠标一点容错时间）

    def __init__(self, settings: Settings, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self._settings = settings
        self._scores: List[Score] = []
        self._score_buttons: List[QPushButton] = []
        self._current_id = ""

        self._top = 56
        self._h = 400
        self._expanded = False
        self._hover = False
        self._force_collapse = False   # 选中曲目后：无视鼠标位置直接收回

        self.setMouseTracking(True)
        self.setCursor(Qt.CursorShape.ArrowCursor)

        # ---- 抽屉内容（固定按展开尺寸摆放，靠父部件裁剪实现"滑出"）----
        self._build_ui()

        # ---- 展开 / 收起动画 ----
        self._anim = QPropertyAnimation(self, b"geometry", self)
        self._anim.setDuration(self.ANIM_MS)
        self._anim.setEasingCurve(QEasingCurve.Type.OutCubic)

        self._collapse_timer = QTimer(self)
        self._collapse_timer.setSingleShot(True)
        self._collapse_timer.setInterval(self.COLLAPSE_DELAY_MS)
        self._collapse_timer.timeout.connect(self._maybe_collapse)

        self.setGeometry(0, self._top, self.HANDLE_W, self._h)

    # ---------- 构建 ----------
    def _build_ui(self) -> None:
        self.setStyleSheet(f"""
            QWidget#body {{ background: transparent; }}
            QLabel#sectitle {{ color: {THEME.text_secondary}; font-size: 12px;
                font-weight: bold; letter-spacing: 1px; background: transparent; }}
            QLabel#count {{ color: {THEME.primary}; font-size: 11px;
                font-family: '{THEME.font_mono}'; background: transparent; }}
            QLabel#hint {{ color: {THEME.text_secondary}; font-size: 11px;
                background: transparent; }}
            QPushButton#scorebtn {{
                text-align: left; color: {THEME.text_primary};
                background: {THEME.surface_alt}; border: none;
                border-radius: 8px; padding: 8px 10px; }}
            QPushButton#scorebtn:hover {{ background: {THEME.border}; }}
            QPushButton#scorebtn:checked {{
                background: rgba(0,229,255,26); border-left: 2px solid {THEME.primary}; }}
            QScrollArea {{ background: transparent; border: none; }}
            QScrollArea > QWidget > QWidget {{ background: transparent; }}
            QScrollBar:vertical {{ width: 6px; background: transparent; margin: 2px 0; }}
            QScrollBar::handle:vertical {{ background: {THEME.border};
                border-radius: 3px; min-height: 26px; }}
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
            QMenu {{ background: {THEME.surface}; color: {THEME.text_primary};
                border: 1px solid {THEME.border}; border-radius: 8px; padding: 4px; }}
            QMenu::item {{ padding: 6px 18px; border-radius: 5px; }}
            QMenu::item:selected {{ background: rgba(0,229,255,38); }}""")

        self._body = QWidget(self, objectName="body")
        lay = QVBoxLayout(self._body)
        lay.setContentsMargins(12, 12, 8, 12)
        lay.setSpacing(6)

        head = QHBoxLayout()
        head.setSpacing(6)
        title = QLabel("曲目", objectName="sectitle")
        self.count_label = QLabel("", objectName="count")
        head.addWidget(title)
        head.addStretch(1)
        head.addWidget(self.count_label)
        lay.addLayout(head)

        hint = QLabel("右键曲目可编辑 / 重命名 / 删除\n（内置曲目只读，可「另存为」自己的版本）",
                      objectName="hint")
        hint.setWordWrap(True)
        lay.addWidget(hint)

        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        content = QWidget()
        self._score_area = QVBoxLayout(content)
        self._score_area.setContentsMargins(0, 0, 6, 0)
        self._score_area.setSpacing(4)
        self._score_area.addStretch(1)      # 末尾留白，按钮顶到上方
        self._scroll.setWidget(content)
        lay.addWidget(self._scroll, 1)

    # ---------- 由浮窗注入纵向范围 ----------
    def set_span(self, top: int, height: int) -> None:
        """浮窗布局变化时同步抽屉的纵向范围（不带动画）。"""
        self._top = int(top)
        self._h = max(90, int(height))
        w = self.PANEL_W if self._expanded else self.HANDLE_W
        self._anim.stop()
        self.setGeometry(0, self._top, w, self._h)

    def _layout_body(self) -> None:
        """内容按「展开尺寸」摆放，多余部分由父部件裁剪。"""
        if not hasattr(self, "_body"):
            return
        self._body.setGeometry(self.HANDLE_W, 0,
                               max(1, self.PANEL_W - self.HANDLE_W), self._h)
        self._elide_buttons()

    # ---------- 曲目列表 ----------
    def set_scores(self, scores: List[Score], current_id: str) -> None:
        for btn in self._score_buttons:
            # 先解绑父级再 deleteLater：否则旧按钮会留在布局里多占一帧，
            # 换曲时列表会短暂"重影"一下。
            btn.hide()
            btn.setParent(None)
            btn.deleteLater()
        self._score_buttons.clear()
        self._current_id = current_id
        self._scores = list(scores)
        self.count_label.setText(f"{len(scores)} 首")
        # 末尾的 stretch 保持不动，新按钮插到它前面
        tail = self._score_area.count() - 1
        for i, s in enumerate(scores):
            btn = QPushButton()          # 文案交给 _elide_buttons 填（要按实际宽度省略）
            btn.setObjectName("scorebtn")
            btn.setCheckable(True)
            btn.setChecked(s.id == current_id)
            btn.setFixedHeight(44)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.setProperty("fullName", s.name)
            btn.setProperty("bpmText", f"BPM {s.bpm:g}")
            # 内置曲目只读：右键菜单据此置灰重命名 / 删除
            btn.setProperty("builtin", bool(getattr(s, "builtin", False)))
            btn.setToolTip(f"{s.name}\nBPM {s.bpm:g}")
            btn.clicked.connect(lambda _=False, sid=s.id: self._on_pick(sid))
            btn.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
            btn.customContextMenuRequested.connect(
                lambda pos, sid=s.id, name=s.name, b=btn: self._score_menu(pos, sid, name, b))
            self._score_area.insertWidget(tail + i, btn)
            self._score_buttons.append(btn)
        self._elide_buttons()
        self.update()

    def _elide_buttons(self) -> None:
        """曲名超出按钮宽度时用省略号收尾，完整名字留在 tooltip。

        抽屉比原设置面板窄不少，24 字的长曲名（如「未闻花名（secret base·中文版简化版）」）
        不处理会被硬裁掉半截，看着像出错。
        """
        if not self._score_buttons:
            return
        if not hasattr(self, "_scroll"):
            return
        avail = self._scroll.viewport().width()
        if avail <= 40:
            avail = self.PANEL_W - self.HANDLE_W
        avail = max(60, avail - 34)          # 扣掉按钮左右内边距 + 滚动内容右边距
        fm = self._score_buttons[0].fontMetrics()
        for btn in self._score_buttons:
            full = btn.property("fullName") or ""
            bpm = btn.property("bpmText") or ""
            btn.setText(f"{fm.elidedText(str(full), Qt.TextElideMode.ElideRight, avail)}\n{bpm}")

    def _on_pick(self, score_id: str) -> None:
        self.score_selected.emit(score_id)
        # 选完就走：鼠标此时还停在按钮上，所以这次不理会"鼠标还在"的复核
        self._force_collapse = True
        self._collapse_timer.start(240)

    def _score_menu(self, pos: QPoint, score_id: str, name: str, btn: QPushButton) -> None:
        self._collapse_timer.stop()
        is_builtin = bool(btn.property("builtin"))
        menu = QMenu(self)
        act_edit = QAction("在编辑器中编辑", menu)
        act_rename = QAction("重命名…", menu)
        act_delete = QAction("删除（仅用户曲目）", menu)
        if is_builtin:
            # 内置曲目打包在 EXE 内部，文件删不掉也改不了：置灰并说明原因，
            # 免得点了没反应（重命名旧逻辑会在用户目录留一份副本 -> 列表出现两条）
            act_rename.setEnabled(False)
            act_delete.setEnabled(False)
            act_rename.setToolTip("内置曲目只读，请在编辑器里「另存为」自定义曲目")
            act_delete.setToolTip("内置曲目只读，无法删除")
        act_edit.triggered.connect(lambda: self.edit_requested.emit(score_id))
        act_rename.triggered.connect(lambda: self._rename_dialog(score_id, name))
        act_delete.triggered.connect(lambda: self._delete_confirm(score_id, name))
        menu.addAction(act_edit)
        menu.addAction(act_rename)
        menu.addSeparator()
        menu.addAction(act_delete)
        if is_builtin:
            tip = QAction("（内置曲目只读：编辑后可「另存为」自己的版本）", menu)
            tip.setEnabled(False)
            menu.addSeparator()
            menu.addAction(tip)
        menu.exec(btn.mapToGlobal(pos))
        # 菜单关掉后鼠标多半已经不在抽屉上了
        if self.rect().contains(self.mapFromGlobal(QCursor.pos())):
            self._collapse_timer.start()
        else:
            self._collapse()

    def _rename_dialog(self, score_id: str, old_name: str) -> None:
        dlg = QInputDialog(self)
        dlg.setWindowTitle("重命名曲目")
        dlg.setLabelText("新的曲名：")
        dlg.setTextValue(old_name)
        if _exec_topmost(dlg) == QDialog.DialogCode.Accepted:
            new_name = dlg.textValue()
            if new_name.strip() and new_name.strip() != old_name:
                self.score_renamed.emit(score_id, new_name.strip())

    def _delete_confirm(self, score_id: str, name: str) -> None:
        msg = QMessageBox(self)
        msg.setWindowTitle("删除曲目")
        msg.setText(f"确定删除《{name}》吗？")
        msg.setInformativeText("只删除用户曲目目录 scores/ 下的文件，内置曲目不受影响，此操作不可撤销。")
        msg.setStandardButtons(QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        msg.setDefaultButton(QMessageBox.StandardButton.No)
        msg.setIcon(QMessageBox.Icon.Question)
        if _exec_topmost(msg) == QMessageBox.StandardButton.Yes:
            self.score_deleted.emit(score_id)

    # ---------- 展开 / 收起 ----------
    @property
    def expanded(self) -> bool:
        return self._expanded

    def expand(self) -> None:
        self._collapse_timer.stop()
        self._force_collapse = False
        if self._expanded:
            return
        self._expanded = True
        self._animate(self.PANEL_W)

    def collapse(self) -> None:
        if not self._expanded:
            return
        self._expanded = False
        self._animate(self.HANDLE_W)

    def _collapse(self) -> None:
        """立即收起（内部调用，跳过鼠标二次确认）。"""
        self._collapse_timer.stop()
        self._force_collapse = False
        self.collapse()

    def _animate(self, width: int) -> None:
        self._anim.stop()
        self._anim.setStartValue(self.geometry())
        self._anim.setEndValue(QRect(0, self._top, width, self._h))
        self._anim.start()
        self.update()

    def _maybe_collapse(self) -> None:
        """延时结束后的复核：鼠标真的不在抽屉上才收。"""
        if not self._expanded:
            self._force_collapse = False
            return
        if self._force_collapse:
            self._collapse()
            return
        if self.rect().contains(self.mapFromGlobal(QCursor.pos())):
            self._collapse_timer.start()
            return
        self.collapse()

    # ---------- 鼠标 ----------
    def enterEvent(self, e) -> None:  # noqa: N802
        self._collapse_timer.stop()
        self._hover = True
        self.expand()
        self.update()

    def leaveEvent(self, e) -> None:  # noqa: N802
        self._hover = False
        if self._expanded:
            self._collapse_timer.start()
        self.update()

    # ---------- 尺寸变化 ----------
    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        self._layout_body()

    def showEvent(self, event) -> None:  # noqa: N802
        super().showEvent(event)
        self._layout_body()

    # ---------- 绘制 ----------
    def paintEvent(self, event) -> None:  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = float(self.width()), float(self.height())

        # 抽屉底：与设置面板同色，保证文字在任何曲目画面下都读得清
        p.setPen(QPen(QColor(THEME.border), 1.0))
        p.setBrush(QColor(19, 24, 32, 242))
        p.drawRoundedRect(QRectF(0.5, 0.5, w - 1.0, h - 1.0), self.RADIUS, self.RADIUS)

        hx = self.HANDLE_W / 2.0
        accent = THEME.primary

        # 把手被悬停 / 已展开时，把手区淡高亮
        if self._hover or self._expanded:
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(0, 229, 255, 26))
            p.drawRoundedRect(QRectF(1.5, 1.5, self.HANDLE_W - 2.0, h - 3.0),
                              self.RADIUS - 2, self.RADIUS - 2)

        # 展开态：把手与内容之间的分隔线
        if w > self.HANDLE_W + 3:
            p.setPen(QPen(QColor(THEME.border), 1.0))
            p.drawLine(int(self.HANDLE_W), 10, int(self.HANDLE_W), int(h) - 10)

        # 把手顶部：曲目数量
        p.setFont(QFont(THEME.font_mono, 8, QFont.Weight.Bold))
        p.setPen(QColor(accent if self._expanded else THEME.text_secondary))
        p.drawText(QRectF(0, 12, self.HANDLE_W, 14),
                   Qt.AlignmentFlag.AlignCenter, str(len(self._scores)))

        # 把手中部：竖排「曲目」
        p.save()
        p.translate(hx, h / 2.0)
        p.rotate(90)
        p.setFont(QFont(THEME.font_sans, 10, QFont.Weight.Bold))
        p.setPen(QColor(THEME.text_primary if self._hover or self._expanded
                        else THEME.text_secondary))
        p.drawText(QRectF(-46, -9, 92, 18), Qt.AlignmentFlag.AlignCenter, "曲目")
        p.restore()

        # 把手底部：方向箭头（收起时向右=可展开，展开时向左=可收起）
        cy = h - 18.0
        if self._expanded:
            tri = QPolygonF([QPointF(hx + 4, cy - 5), QPointF(hx - 3, cy),
                             QPointF(hx + 4, cy + 5)])
        else:
            tri = QPolygonF([QPointF(hx - 4, cy - 5), QPointF(hx + 3, cy),
                             QPointF(hx - 4, cy + 5)])
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(accent if self._hover or self._expanded
                          else THEME.text_secondary))
        p.drawPolygon(tri)
