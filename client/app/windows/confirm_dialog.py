# -*- coding: utf-8 -*-
"""半透明小确认框：消息文本 + 确定/取消，返回用户选择。

用于悬浮球右键「是否打开配置窗口」的二次确认（阶段 2 配置窗口的入口确认）。
窗口为无边框圆角半透明样式，与主窗口视觉一致。
颜色取自 app.theme 当前激活主题（业务配置 theme 下发后自动生效）。
"""

from __future__ import annotations

from PyQt5.QtCore import Qt, QRectF
from PyQt5.QtGui import QPainter, QPainterPath
from PyQt5.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from .. import theme

_RADIUS = 12


class ConfirmDialog(QDialog):
    """半透明无边框确认对话框。

    用法：
        dialog = ConfirmDialog(self, "确定要打开配置窗口吗？")
        if dialog.exec_() == QDialog.Accepted:
            ...
    或直接调用 ConfirmDialog.ask(parent, message) 返回 bool。
    """

    def __init__(self, parent: QWidget, message: str = "确定要继续吗？",
                 title: str = "确认") -> None:
        super().__init__(
            parent, Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Dialog
        )
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setWindowTitle(title)
        self.setFixedWidth(320)
        self.setModal(True)

        # 构造时快照当前强调色（对话框为短生命周期模态，无需动态刷新）
        self._accent_hex = (
            theme.active_theme().get("accent") or theme.DEFAULT_THEME["accent"]
        )

        root = QVBoxLayout(self)
        root.setContentsMargins(20, 18, 20, 16)
        root.setSpacing(12)

        self._message_label = QLabel(message, self)
        self._message_label.setObjectName("confirmMessage")
        self._message_label.setWordWrap(True)
        self._message_label.setAlignment(Qt.AlignCenter)
        self._message_label.setStyleSheet(
            "color:#ECEFF4; font-size:14px; background:transparent;"
        )
        root.addWidget(self._message_label)

        btn_row = QHBoxLayout()
        btn_row.setSpacing(10)

        cancel_btn = QPushButton("取消", self)
        ok_btn = QPushButton("确定", self)
        ok_btn.setDefault(True)
        for btn in (cancel_btn, ok_btn):
            btn.setFixedHeight(32)
            btn.setCursor(Qt.PointingHandCursor)
        cancel_btn.setStyleSheet(self._btn_style(False))
        ok_btn.setStyleSheet(self._btn_style(True))
        cancel_btn.clicked.connect(self.reject)
        ok_btn.clicked.connect(self.accept)

        btn_row.addStretch(1)
        btn_row.addWidget(cancel_btn)
        btn_row.addWidget(ok_btn)
        btn_row.addStretch(1)
        root.addLayout(btn_row)

    def _btn_style(self, primary: bool) -> str:
        if primary:
            accent = self._accent_hex
            return (
                "QPushButton{{background:{accent}; color:white; border:none;"
                "border-radius:6px; font-size:13px;}}"
                "QPushButton:hover{{background:{hover};}}"
                "QPushButton:pressed{{background:{pressed};}}"
            ).format(
                accent=accent,
                hover=theme.darker_hex(accent, 135),
                pressed=theme.darker_hex(accent, 160),
            )
        return (
            "QPushButton{background:rgba(202, 240, 248, 38); color:#CAF0F8; border:none;"
            "border-radius:6px; font-size:13px;}"
            "QPushButton:hover{background:rgba(202, 240, 248, 55);}"
            "QPushButton:pressed{background:rgba(173, 232, 244, 45);}"
        )

    # ------------------------------------------------------------------
    def paintEvent(self, event) -> None:  # noqa: N802 (Qt 命名)
        """自绘圆角半透明背景（颜色 = 业务配置 theme.card）。"""
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        path = QPainterPath()
        path.addRoundedRect(QRectF(self.rect()), _RADIUS, _RADIUS)
        # 保留原卡片色的半透明质感（alpha 245）
        painter.fillPath(path, theme.card_color(245))

    @classmethod
    def ask(cls, parent: QWidget, message: str,
            title: str = "确认") -> bool:
        """便捷方法：弹出确认框并返回是否确定。"""
        dialog = cls(parent, message=message, title=title)
        return dialog.exec_() == QDialog.Accepted
