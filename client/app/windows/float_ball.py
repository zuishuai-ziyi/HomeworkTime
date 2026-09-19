# -*- coding: utf-8 -*-
"""圆形悬浮球窗口。

- 无边框 + WA_TranslucentBackground，图标按 ball_size 缩放显示；
- 单击（移动 ≤5px）→ 发射 clicked() 信号（打开主窗口）；
- 按住左键移动（>5px）→ 拖动窗口，位置变化经 pos_changed 信号上报；
- 右键释放 → 弹确认对话框，确认后发射 open_config_requested()（阶段 2 接配置窗口）；
- set_topmost(bool) 切换置顶/置底（重建窗口标志）。
"""

from __future__ import annotations

from typing import Optional

from PyQt5.QtCore import Qt, QPoint, pyqtSignal
from PyQt5.QtGui import QPixmap
from PyQt5.QtWidgets import QWidget

from ..config import resource_path
from .confirm_dialog import ConfirmDialog

#: 单击与拖动的判定阈值（像素）
CLICK_THRESHOLD_PX = 5
#: 默认图标资源
DEFAULT_ICON = "resources/icons/ball_64.png"


class FloatBall(QWidget):
    """悬浮球。暴露三个事件：clicked / open_config_requested / pos_changed。"""

    clicked = pyqtSignal()               # 单击（打开主窗口）
    open_config_requested = pyqtSignal() # 右键确认后（打开配置窗口，阶段 2）
    pos_changed = pyqtSignal(object)     # 位置变化（参数 QPoint，用于持久化）

    def __init__(
        self,
        ball_size: int = 64,
        icon_path: Optional[str] = None,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(
            parent,
            Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool,
        )
        self.setAttribute(Qt.WA_TranslucentBackground)
        self._ball_size = int(ball_size)
        self._icon_path = icon_path or resource_path(DEFAULT_ICON)

        self._press_pos: Optional[QPoint] = None   # 按下时的窗口位置
        self._press_global: Optional[QPoint] = None  # 按下时的全局鼠标位置
        self._dragging = False

        self.setWindowOpacity(0.70)  # 默认透明度，由控制器按业务配置覆盖
        self.setFixedSize(self._ball_size, self._ball_size)
        self.setToolTip("HomeworkTime 悬浮球")

    # ------------------------------------------------------------------
    # 尺寸 / 位置
    # ------------------------------------------------------------------
    def ball_size(self) -> int:
        return self._ball_size

    def set_ball_size(self, size: int) -> None:
        """更新悬浮球直径，保持中心点不变。"""
        size = max(16, int(size))
        if size == self._ball_size:
            return
        old = self._ball_size
        self._ball_size = size
        self.setFixedSize(size, size)
        # 保持中心：旧位置 + 差异的一半
        if self.pos().x() != 0 or self.pos().y() != 0:
            self.move(
                self.x() + (old - size) // 2,
                self.y() + (old - size) // 2,
            )
        self.update()

    # ------------------------------------------------------------------
    # 绘制
    # ------------------------------------------------------------------
    def paintEvent(self, event) -> None:  # noqa: N802
        """绘制缩放到当前尺寸的圆形图标（带透明圆形底）。"""
        from PyQt5.QtGui import QPainter

        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        pix = QPixmap(self._icon_path)
        if pix.isNull():
            # 图标缺失时画一个纯色圆兜底
            painter.setBrush(self.palette().highlight())
            painter.setPen(Qt.NoPen)
            painter.drawEllipse(self.rect())
        else:
            scaled = pix.scaled(
                self._ball_size, self._ball_size,
                Qt.KeepAspectRatio, Qt.SmoothTransformation,
            )
            x = (self.width() - scaled.width()) // 2
            y = (self.height() - scaled.height()) // 2
            painter.drawPixmap(x, y, scaled)

    # ------------------------------------------------------------------
    # 鼠标交互（单击 / 拖动 / 右键）
    # ------------------------------------------------------------------
    def mousePressEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.LeftButton:
            self._press_global = event.globalPos()
            self._press_pos = self.pos()
            self._dragging = False
        event.accept()

    def mouseMoveEvent(self, event) -> None:  # noqa: N802
        if self._press_global is not None and event.buttons() & Qt.LeftButton:
            delta = event.globalPos() - self._press_global
            # 仅当位移超过阈值才开始拖动，避免不必要移动
            if not self._dragging and (
                abs(delta.x()) > CLICK_THRESHOLD_PX
                or abs(delta.y()) > CLICK_THRESHOLD_PX
            ):
                self._dragging = True
            if self._dragging and self._press_pos is not None:
                new_pos = self._press_pos + delta
                self.move(new_pos)
                self.pos_changed.emit(self.pos())
        event.accept()

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.RightButton:
            self._release_right_click()
        elif event.button() == Qt.LeftButton:
            self._release_left_click(event)
        event.accept()

    def _release_left_click(self, event) -> None:
        moved = False
        if self._press_global is not None:
            delta = event.globalPos() - self._press_global
            moved = (
                abs(delta.x()) > CLICK_THRESHOLD_PX
                or abs(delta.y()) > CLICK_THRESHOLD_PX
            ) or self._dragging
        self._press_global = None
        self._press_pos = None
        self._dragging = False
        if not moved:
            self.clicked.emit()

    def _release_right_click(self) -> None:
        # 右键：确认后触发「打开配置窗口」入口（阶段 2 接入）
        if ConfirmDialog.ask(self, "确定要打开配置窗口吗？"):
            self.open_config_requested.emit()

    # ------------------------------------------------------------------
    # 置顶 / 置底
    # ------------------------------------------------------------------
    def set_topmost(self, topmost: bool) -> None:
        """切换置顶 / 置底显示。重建窗口标志（过程会隐藏窗口，需重新 show）。"""
        hint = Qt.WindowStaysOnTopHint if topmost else Qt.WindowStaysOnBottomHint
        flags = Qt.FramelessWindowHint | Qt.Tool | hint
        if self.windowFlags() == flags:
            return
        was_visible = self.isVisible()
        self.setWindowFlags(flags)
        if was_visible:
            self.show()

    def restore_position(self, pos: Optional[dict]) -> None:
        """从 local_config 恢复记忆位置；None 时放到屏幕右下角。"""
        if pos is not None and "x" in pos and "y" in pos:
            try:
                self.move(int(pos["x"]), int(pos["y"]))
                return
            except (TypeError, ValueError):
                pass
        # 默认：屏幕右下角（留出边距）
        screen = self.screen() or self.window().screen()
        if screen is not None:
            geo = screen.availableGeometry()
            self.move(
                geo.right() - self.width() - 16,
                geo.bottom() - self.height() - 16,
            )
        else:  # 兜底
            self.move(16, 16)