# -*- coding: utf-8 -*-
"""主窗口：无边框圆角半透明「卡片」。

- 置顶显示当前时段信息、科目大字、倒计时大字 + 可滚动纵向时间轴；
- 鼠标按住可拖动移动窗口；右上角 × 隐藏并发射 closed_to_ball 信号；
- set_bottom_mode() 切换置顶/置底（晚自习外置底显示）；
- Qt.Tool 标志 → 不占任务栏；
- refresh(state) 接收 scheduler.get_state 的结果刷新界面。
"""

from __future__ import annotations

from typing import Optional

from PyQt5.QtCore import Qt, QPoint, QRectF, pyqtSignal
from PyQt5.QtGui import QColor, QFont, QPainter, QPainterPath
from PyQt5.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from ..scheduler import ScheduleState, SubjectInfo, format_seconds

#: 卡片背景（深色半透明）
BG_COLOR = QColor(2, 62, 138, 235)
RADIUS = 16
#: 主窗口默认尺寸
WINDOW_WIDTH = 440
WINDOW_HEIGHT = 620

#: 时间轴配色
TIMELINE_ITEM_STYLE = (
    "QListWidget#timeline{background:transparent;border:none;"
    "font-size:13px;color:#D8DEE9;}"
    "QListWidget#timeline::item{padding:2px 8px;border-radius:6px;}"
)
TIMELINE_CURRENT_BG = "#0077B6"


class MainWindow(QWidget):
    """主窗口卡片。"""

    #: 用户点击 × 关闭后发射（控制器据此切到悬浮球）
    closed_to_ball = pyqtSignal()

    def __init__(
        self,
        idle_text: str = "课间休息",
        evening_range: str = "",
        warn_seconds: int = 60,
    ) -> None:
        super().__init__(
            None,
            Qt.FramelessWindowHint | Qt.Tool | Qt.WindowStaysOnTopHint,
        )
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setFixedSize(WINDOW_WIDTH, WINDOW_HEIGHT)
        self.setWindowOpacity(0.85)  # 默认透明度，由控制器按业务配置覆盖

        self._idle_text = idle_text
        self._evening_range = evening_range
        self._warn_seconds = int(warn_seconds)
        self._bottom_mode = False
        self._drag_pos: Optional[QPoint] = None
        self._state: Optional[ScheduleState] = None

        self._build_ui()

    # ------------------------------------------------------------------
    # UI 构建
    # ------------------------------------------------------------------
    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(24, 28, 24, 20)
        root.setSpacing(8)

        # 顶部时段信息
        self.header_label = QLabel(self)
        self.header_label.setStyleSheet(
            "color:#9BA6B8;font-size:13px;background:transparent;"
        )
        root.addWidget(self.header_label)

        # 科目大字
        self.subject_label = QLabel(self)
        self.subject_label.setAlignment(Qt.AlignCenter)
        self.subject_label.setStyleSheet(
            "color:#FFFFFF;font-size:34px;font-weight:bold;background:transparent;"
        )
        root.addWidget(self.subject_label)

        # 倒计时大字
        self.countdown_label = QLabel(self)
        self.countdown_label.setAlignment(Qt.AlignCenter)
        mono = QFont("Consolas", 46)
        mono.setBold(True)
        self.countdown_label.setFont(mono)
        self.countdown_label.setStyleSheet(
            "color:#FFFFFF;background:transparent;"
        )
        root.addWidget(self.countdown_label)

        # 当前段/下一事件说明（小字）
        self.detail_label = QLabel(self)
        self.detail_label.setAlignment(Qt.AlignCenter)
        self.detail_label.setStyleSheet(
            "color:#A9B2C4;font-size:13px;background:transparent;"
        )
        root.addWidget(self.detail_label)

        # 时间轴标题
        title_row = QHBoxLayout()
        title = QLabel("今晚时间轴（当前时段高亮）", self)
        title.setStyleSheet("color:#8B95A9;font-size:12px;background:transparent;")
        title_row.addWidget(title)
        title_row.addStretch(1)
        root.addLayout(title_row)

        # 可滚动时间轴（超过 10 段自动出现滚动条）
        self.timeline = QListWidget(self)
        self.timeline.setObjectName("timeline")
        self.timeline.setStyleSheet(TIMELINE_ITEM_STYLE)
        self.timeline.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.timeline.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.timeline.setFocusPolicy(Qt.NoFocus)
        self.timeline.setSpacing(2)
        root.addWidget(self.timeline, 1)

        # 右上角关闭按钮（绝对定位）
        self._close_btn = QToolButton(self)
        self._close_btn.setText("×")
        self._close_btn.setCursor(Qt.PointingHandCursor)
        self._close_btn.setFixedSize(30, 30)
        self._close_btn.setStyleSheet(
            "QToolButton{color:#C7CFDD;background:rgba(255,255,255,28);"
            "border:none;border-radius:15px;font-size:20px;font-weight:bold;}"
            "QToolButton:hover{color:#FFFFFF;background:rgba(239,68,68,180);}"
        )
        self._close_btn.clicked.connect(self._on_close_clicked)
        self._close_btn.move(WINDOW_WIDTH - 30 - 16, 12)

    # ------------------------------------------------------------------
    # 样式辅助
    # ------------------------------------------------------------------
    def paintEvent(self, event) -> None:  # noqa: N802
        """自绘圆角深色半透明背景。"""
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        path = QPainterPath()
        path.addRoundedRect(QRectF(self.rect()), RADIUS, RADIUS)
        painter.fillPath(path, BG_COLOR)

    # ------------------------------------------------------------------
    # 外部设置
    # ------------------------------------------------------------------
    def set_idle_text(self, text: str) -> None:
        self._idle_text = text or "课间休息"

    def set_evening_range(self, text: str) -> None:
        self._evening_range = text or ""

    def set_warn_seconds(self, seconds: int) -> None:
        self._warn_seconds = max(1, int(seconds))

    def set_bottom_mode(self, bottom: bool) -> None:
        """切换置顶 / 置底显示（晚自习外置底）。"""
        if bottom == self._bottom_mode:
            return
        self._bottom_mode = bottom
        hint = Qt.WindowStaysOnBottomHint if bottom else Qt.WindowStaysOnTopHint
        flags = Qt.FramelessWindowHint | Qt.Tool | hint
        was_visible = self.isVisible()
        self.setWindowFlags(flags)
        if was_visible:
            self.show()

    # ------------------------------------------------------------------
    # 关闭按钮 → 转悬浮球
    # ------------------------------------------------------------------
    def _on_close_clicked(self) -> None:
        self.hide()
        self.closed_to_ball.emit()

    # ------------------------------------------------------------------
    # 窗口拖动（frameless 常规实现）
    # ------------------------------------------------------------------
    def mousePressEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.LeftButton:
            self._drag_pos = (
                event.globalPos() - self.frameGeometry().topLeft()
            )
        event.accept()

    def mouseMoveEvent(self, event) -> None:  # noqa: N802
        if self._drag_pos is not None and event.buttons() & Qt.LeftButton:
            self.move(event.globalPos() - self._drag_pos)
        event.accept()

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        self._drag_pos = None
        event.accept()

    # ------------------------------------------------------------------
    # 数据刷新
    # ------------------------------------------------------------------
    def refresh(self, state: ScheduleState) -> None:
        """根据 scheduler.get_state 的结果刷新全部界面元素。"""
        self._state = state
        self._refresh_header(state)
        self._refresh_main_area(state)
        self._refresh_timeline(state)

    def _refresh_header(self, state: ScheduleState) -> None:
        if state.in_evening:
            text = "晚自习中"
            if self._evening_range:
                text += f"　{self._evening_range}"
        else:
            text = "不在晚自习时间"
        self.header_label.setText(text)

    def _refresh_main_area(self, state: ScheduleState) -> None:
        ne = state.next_event
        if state.phase == "subject" and state.current_subject is not None:
            sub = state.current_subject
            remaining = state.remaining_sec or 0
            self.subject_label.setText(sub.name)
            self._set_countdown(remaining)
            self._set_countdown_color(remaining)
            self.detail_label.setText(
                f"时段 {sub.start} — {sub.end}　本段结束声音已就绪"
            )
        elif state.phase == "idle":
            self.subject_label.setText(self._idle_text)
            self._set_countdown(ne.get("seconds", 0))
            self._set_countdown_color(999999)  # 空档不警示
            if ne.get("type") == "subject_start":
                self.detail_label.setText(
                    f"「{ne.get('name', '')}」{ne.get('at', '')} 开始，"
                    f"距开始还有 {format_seconds(ne.get('seconds', 0))}"
                )
            else:
                self.detail_label.setText(
                    f"本晚无后续科目，距晚自习结束还有 "
                    f"{format_seconds(ne.get('seconds', 0))}"
                )
        else:  # outside
            self.subject_label.setText("不在晚自习时间")
            self._set_countdown(ne.get("seconds", 0))
            self._set_countdown_color(999999)
            self.detail_label.setText(
                f"「{ne.get('name', '晚自习开始')}」{ne.get('at', '')} 开始，"
                f"距开始还有 {format_seconds(ne.get('seconds', 0))}"
            )

    def _set_countdown(self, seconds: int) -> None:
        self.countdown_label.setText(format_seconds(seconds))

    def _set_countdown_color(self, remaining: int) -> None:
        if remaining <= self._warn_seconds:
            color = "#F59E0B"  # 橙色：临近结束
        else:
            color = "#FFFFFF"
        self.countdown_label.setStyleSheet(
            f"color:{color};background:transparent;"
        )

    def _refresh_timeline(self, state: ScheduleState) -> None:
        current_index = None
        if (
            state.current_subject is not None
            and state.current_subject in state.sorted_subjects
        ):
            current_index = state.sorted_subjects.index(state.current_subject)

        # 数据变化时整体重建（单晚 ≤10 段，性能无压力）
        while self.timeline.count():
            self.timeline.takeItem(0)

        for i, sub in enumerate(state.sorted_subjects):
            is_current = i == current_index
            item = QListWidgetItem(f"{sub.start} — {sub.end}　{sub.name}")
            item.setSizeHint(item.sizeHint())
            if is_current:
                item.setBackground(QColor(TIMELINE_CURRENT_BG))
                item.setForeground(QColor("#FFFFFF"))
                f = item.font()
                f.setBold(True)
                item.setFont(f)
            else:
                item.setBackground(QColor(3, 4, 94, 200))
                item.setForeground(QColor("#D8DEE9"))
            self.timeline.addItem(item)

        if current_index is not None and 0 <= current_index < self.timeline.count():
            self.timeline.scrollToItem(
                self.timeline.item(current_index), QListWidget.PositionAtCenter
            )