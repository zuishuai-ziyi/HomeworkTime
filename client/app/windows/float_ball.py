# -*- coding: utf-8 -*-
"""圆形悬浮球窗口。

- 无边框 + WA_TranslucentBackground，绘制纯色圆底（业务配置 theme.ball）
  + 铃铛矢量图标（按底色亮度自动白/深蓝反色）；
- 单击（移动 ≤5px）→ 发射 clicked() 信号（打开主窗口）；
- 按住左键移动（>5px）→ 拖动窗口，位置变化经 pos_changed 信号上报；
- 右键释放 → 弹确认对话框，确认后发射 open_config_requested()（阶段 2 接配置窗口）；
- set_topmost(bool) 切换置顶/置底（重建窗口标志）；refresh_theme() 在主题变更后触发重绘。
"""

from __future__ import annotations

from typing import Dict, Optional, Tuple

from PyQt5.QtCore import Qt, QPoint, QRectF, pyqtSignal
from PyQt5.QtGui import QPixmap
from PyQt5.QtWidgets import QWidget

from .. import theme as theme_mod
from ..config import resource_path
from .confirm_dialog import ConfirmDialog

#: 单击与拖动的判定阈值（像素）
CLICK_THRESHOLD_PX = 5
#: 默认图标资源（SVG 内 fill="#1296db" 为占位色，绘制时整体替换为反色结果）
DEFAULT_ICON = "resources/icons/ball_bell.svg"
#: 图标模板占位填充色（与 ball_bell.svg 内一致）
_GLYPH_PLACEHOLDER = b"#1296db"

#: SVG 模板字节缓存（模块级，进程内读一次）
_icon_template: Optional[bytes] = None
#: 铃铛位图缓存：{(尺寸, 图标色): QPixmap}
_icon_pixmaps: Dict[Tuple[int, str], QPixmap] = {}


def _load_icon_template() -> bytes:
    """读取铃铛 SVG 模板（缺失/读失败返回空字节，绘制时仅画纯色圆底）。"""
    global _icon_template
    if _icon_template is None:
        try:
            with open(resource_path(DEFAULT_ICON), "rb") as fh:
                _icon_template = fh.read()
        except OSError:
            _icon_template = b""
    return _icon_template


def _icon_pixmap(size: int, glyph_color: str) -> QPixmap:
    """把 SVG 模板按指定颜色着色并渲染为 size×size 透明位图（带缓存）。

    QtSvg 缺失或渲染失败时返回空 pixmap（保留透明位图，不中断绘制）。
    """
    key = (int(size), glyph_color)
    cached = _icon_pixmaps.get(key)
    if cached is not None:
        return cached
    from PyQt5.QtGui import QPainter

    pix = QPixmap(int(size), int(size))
    pix.fill(Qt.transparent)
    data = _load_icon_template()
    if data:
        try:
            from PyQt5.QtSvg import QSvgRenderer

            renderer = QSvgRenderer(
                data.replace(_GLYPH_PLACEHOLDER, glyph_color.encode("ascii"))
            )
            if renderer.isValid():
                painter = QPainter(pix)
                painter.setRenderHint(QPainter.Antialiasing, True)
                renderer.render(painter, QRectF(0, 0, size, size))
                painter.end()
        except Exception:
            pass  # 图标渲染失败 → 保留透明位图，悬浮球仍显示纯色圆底
    _icon_pixmaps[key] = pix
    return pix


class FloatBall(QWidget):
    """悬浮球。暴露三个事件：clicked / open_config_requested / pos_changed。"""

    clicked = pyqtSignal()               # 单击（打开主窗口）
    open_config_requested = pyqtSignal() # 右键确认后（打开配置窗口，阶段 2）
    pos_changed = pyqtSignal(object)     # 位置变化（参数 QPoint，用于持久化）

    def __init__(
        self,
        ball_size: int = 64,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(
            parent,
            Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool,
        )
        self.setAttribute(Qt.WA_TranslucentBackground)
        self._ball_size = int(ball_size)

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
    def refresh_theme(self) -> None:
        """业务配置主题变更后触发重绘（paintEvent 每次读当前激活主题）。"""
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802
        """绘制纯色圆底 + 居中铃铛图标（图标色按底色亮度自动反色）。"""
        from PyQt5.QtGui import QPainter

        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        painter.setPen(Qt.NoPen)
        painter.setBrush(theme_mod.ball_color())
        painter.drawEllipse(self.rect())
        glyph = theme_mod.ball_glyph_color()
        pix = _icon_pixmap(self._ball_size, glyph)
        if not pix.isNull():
            painter.drawPixmap(
                (self.width() - pix.width()) // 2,
                (self.height() - pix.height()) // 2,
                pix,
            )

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