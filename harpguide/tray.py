# -*- coding: utf-8 -*-
"""系统托盘图标：左键切显隐，右键菜单（退出/设置/校准/编辑器…）。

Windows 习惯：用户从任务栏右下角的托盘图标管理后台工具。
挂载在 `QSystemTrayIcon` 上，不强制依赖——无托盘环境（Linux 服务器 / Wayland）
会自动降级为只在浮窗上工作。
"""
from __future__ import annotations

from typing import Optional

from PySide6.QtCore import QObject, Signal
from PySide6.QtGui import QAction, QIcon
from PySide6.QtWidgets import QMenu, QSystemTrayIcon


class TrayController(QObject):
    """托盘图标 + 右键菜单控制器。

    所有动作通过回调接入（避免直接依赖 AppController，方便单测）。
    """

    show_overlay_requested = Signal()           # 显示浮窗
    hide_overlay_requested = Signal()           # 隐藏浮窗
    toggle_visible_requested = Signal()         # 切显隐
    open_settings_requested = Signal()
    toggle_playback_requested = Signal()
    reset_requested = Signal()
    open_calibration_requested = Signal()
    open_editor_requested = Signal()
    reload_scores_requested = Signal()          # 重新扫描曲目目录
    open_scores_folder_requested = Signal()     # 在资源管理器里打开曲目目录
    quit_requested = Signal()

    def __init__(self, parent: Optional[QObject] = None):
        super().__init__(parent)
        self._tray: Optional[QSystemTrayIcon] = None
        self._menu: Optional[QMenu] = None
        self._act_toggle_visible: Optional[QAction] = None
        self._act_pause: Optional[QAction] = None
        self._available = QSystemTrayIcon.isSystemTrayAvailable()

    # ---- 构造 ----
    def install(self, icon: QIcon, tooltip: str = "ManboHakimi-Harp") -> bool:
        """安装托盘图标。返回 True 表示成功。"""
        if not self._available:
            return False
        self._tray = QSystemTrayIcon(icon, self)
        self._tray.setToolTip(tooltip)
        self._menu = self._build_menu()
        self._tray.setContextMenu(self._menu)
        # 左键单击 = 切显隐（双击会同时触发，且 Windows 默认是展开菜单，
        # 所以只挂 activated 的 Trigger 即可）
        self._tray.activated.connect(self._on_activated)
        self._tray.show()
        return True

    def shutdown(self) -> None:
        if self._tray is not None:
            self._tray.hide()
            self._tray.deleteLater()
            self._tray = None
        if self._menu is not None:
            self._menu.deleteLater()
            self._menu = None

    @property
    def available(self) -> bool:
        return self._available

    # ---- 菜单构造 ----
    def _build_menu(self) -> QMenu:
        m = QMenu()

        self._act_toggle_visible = QAction("显示 / 隐藏浮窗", m)
        self._act_toggle_visible.triggered.connect(self.toggle_visible_requested)
        m.addAction(self._act_toggle_visible)

        act_settings = QAction("设置面板…", m)
        act_settings.triggered.connect(self.open_settings_requested)
        m.addAction(act_settings)

        m.addSeparator()

        self._act_pause = QAction("开始 / 暂停", m)
        self._act_pause.setCheckable(True)
        self._act_pause.setChecked(False)
        self._act_pause.triggered.connect(self.toggle_playback_requested)
        m.addAction(self._act_pause)

        act_reset = QAction("重置到开头", m)
        act_reset.triggered.connect(self.reset_requested)
        m.addAction(act_reset)

        m.addSeparator()

        act_calib = QAction("琴键校准…", m)
        act_calib.triggered.connect(self.open_calibration_requested)
        m.addAction(act_calib)

        act_editor = QAction("乐谱编辑器…", m)
        act_editor.triggered.connect(self.open_editor_requested)
        m.addAction(act_editor)

        m.addSeparator()

        # 曲目目录：手工放进 scores/ 的 JSON 原先只能重启程序才会出现，
        # 这两项把「放进去 -> 刷新」和「不知道放哪」两个问题一起解决。
        act_reload = QAction("刷新曲库", m)
        act_reload.triggered.connect(self.reload_scores_requested)
        m.addAction(act_reload)

        act_scores_dir = QAction("打开曲目文件夹…", m)
        act_scores_dir.triggered.connect(self.open_scores_folder_requested)
        m.addAction(act_scores_dir)

        m.addSeparator()

        act_quit = QAction("退出 ManboHakimi-Harp", m)
        act_quit.triggered.connect(self.quit_requested)
        m.addAction(act_quit)
        return m

    # ---- 同步状态 ----
    def set_playing(self, playing: bool) -> None:
        """同步播放状态到菜单勾选（引擎播放状态变化时调用）。"""
        if self._act_pause is not None:
            self._act_pause.setChecked(playing)
            # 文本同步切换更直观
            self._act_pause.setText("暂停" if playing else "开始")

    def show_message(self, title: str, body: str,
                     icon: QSystemTrayIcon.MessageIcon = QSystemTrayIcon.MessageIcon.Information,
                     timeout_ms: int = 4000) -> None:
        """弹 Windows 通知（已最小化时也能看到）。"""
        if self._tray is not None:
            self._tray.showMessage(title, body, icon, timeout_ms)

    # ---- 左键 ----
    def _on_activated(self, reason: QSystemTrayIcon.ActivationReason) -> None:
        # 单击 / 双击都切显隐；右键由 Qt 内部自动弹 contextMenu
        if reason in (QSystemTrayIcon.ActivationReason.Trigger,
                      QSystemTrayIcon.ActivationReason.DoubleClick):
            self.toggle_visible_requested.emit()