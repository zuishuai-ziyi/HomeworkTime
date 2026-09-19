# -*- coding: utf-8 -*-
"""系统托盘图标（阶段 2）。

- 图标：resources/icons/tray_32.png；
- 双击 → 回调 show_main；
- 右键菜单：显示主窗口 / 打开配置 / 开机自启（可勾选，联动
  autostart + local_config）/ 退出；
- 气泡提示：收到 activate 或主程序主动调用时用 ``showMessage``
  （QSystemTrayIcon 的气泡在 Windows 上需任务栏通知区可用，调用失败安全忽略）。

回调通过 ``set_callbacks(...)`` 注入，保持本模块与 AppController 解耦。
"""

from __future__ import annotations

from typing import Callable, Dict, Optional

from PyQt5.QtCore import QObject
from PyQt5.QtGui import QIcon
from PyQt5.QtWidgets import (
    QAction,
    QMenu,
    QSystemTrayIcon,
)

from ..config import resource_path
from ..logger import get_logger

logger = get_logger("tray")

#: 托盘图标默认资源
DEFAULT_ICON = "resources/icons/tray_32.png"


class Tray(QObject):
    """系统托盘封装。

    用法::

        tray = Tray()
        tray.set_callbacks(show_main=..., open_config=..., quit_app=...,
                           autostart_toggled=...)
        tray.set_autostart_checked(local.get("autostart", False))
        tray.show()
    """

    def __init__(
        self,
        icon_path: Optional[str] = None,
        parent: Optional[QObject] = None,
    ) -> None:
        super().__init__(parent)
        self._tray = QSystemTrayIcon(
            QIcon(icon_path or resource_path(DEFAULT_ICON)), self
        )
        self._tray.setToolTip("HomeWorkTime 作业时间提醒")
        self._menu = QMenu()   # QSystemTrayIcon 会接管此菜单的所有权
        self._callbacks: Dict[str, Callable] = {}

        # 菜单
        self.show_action = QAction("显示主窗口", self._menu)
        self.config_action = QAction("打开配置", self._menu)
        # 引导被跳过（用户选择离线模式）后，唯一的服务器配置入口。
        # 引导未跳过时点击则复用 GuideWindow；与引导窗口语义一致：
        # 保存成功 → 立即生效；保存即退出离线模式（guide_dismissed=False）。
        self.server_settings_action = QAction("服务器设置", self._menu)
        self.autostart_action = QAction("开机自启", self._menu)
        self.autostart_action.setCheckable(True)
        self.quit_action = QAction("退出", self._menu)

        self._menu.addAction(self.show_action)
        self._menu.addSeparator()
        self._menu.addAction(self.config_action)
        self._menu.addAction(self.server_settings_action)
        self._menu.addAction(self.autostart_action)
        self._menu.addSeparator()
        self._menu.addAction(self.quit_action)
        self._tray.setContextMenu(self._menu)

        # 信号接线
        self._tray.activated.connect(self._on_activated)
        self.show_action.triggered.connect(lambda: self._invoke("show_main"))
        self.config_action.triggered.connect(lambda: self._invoke("open_config"))
        self.server_settings_action.triggered.connect(
            lambda: self._invoke("server_settings")
        )
        self.autostart_action.toggled.connect(self._on_autostart_toggled)
        self.quit_action.triggered.connect(lambda: self._invoke("quit_app"))

    # ------------------------------------------------------------------
    # 回调注入
    # ------------------------------------------------------------------
    def set_callbacks(self, **callbacks: Callable) -> None:
        """注入回调：show_main / open_config / quit_app / autostart_toggled。"""
        for name, cb in callbacks.items():
            if callable(cb):
                self._callbacks[name] = cb

    def _invoke(self, name: str):
        cb = self._callbacks.get(name)
        if cb is not None:
            try:
                cb()
            except Exception as exc:
                logger.exception("托盘回调 %s 执行失败: %s", name, exc)

    def _on_autostart_toggled(self, checked: bool) -> None:
        """自启勾选变化 → 回调（携带 checked 参数）。"""
        cb = self._callbacks.get("autostart_toggled")
        if cb is not None:
            try:
                cb(checked)
            except Exception as exc:
                logger.exception("托盘自启回调执行失败: %s", exc)

    def _on_activated(self, reason) -> None:
        if reason == QSystemTrayIcon.DoubleClick:
            self._invoke("show_main")
        elif reason == QSystemTrayIcon.Trigger:
            self._invoke("show_main")  # 单击也可唤出主窗口（触摸屏友好）

    # ------------------------------------------------------------------
    # 状态 / 展示
    # ------------------------------------------------------------------
    def set_autostart_checked(self, checked: bool) -> None:
        """同步「开机自启」勾选状态（受控更新，避免误触发事件）。"""
        try:
            self.autostart_action.blockSignals(True)
            self.autostart_action.setChecked(bool(checked))
        finally:
            self.autostart_action.blockSignals(False)

    def show(self) -> None:
        """显示托盘图标（系统不支持时安全忽略）。"""
        try:
            self._tray.show()
        except Exception as exc:
            logger.warning("托盘图标显示失败: %s", exc)

    def hide(self) -> None:
        try:
            self._tray.hide()
        except Exception as exc:
            logger.warning("托盘图标隐藏失败: %s", exc)

    def close(self) -> None:
        """释放托盘与菜单。"""
        try:
            self._menu.close()
        except Exception:
            pass
        self.hide()
        self._tray.deleteLater()

    def show_message(self, title: str, message: str, timeout_ms: int = 3000) -> None:
        """气泡提示（Windows 通知区 API；失败仅为日志，不影响主流程）。"""
        try:
            self._tray.showMessage(
                title, message, QSystemTrayIcon.Information, timeout_ms
            )
        except Exception as exc:
            logger.warning("托盘气泡提示失败: %s", exc)

    @property
    def tray_icon(self) -> QSystemTrayIcon:
        """暴露底层 QSystemTrayIcon（需要精细控制时使用）。"""
        return self._tray