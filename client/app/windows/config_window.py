# -*- coding: utf-8 -*-
"""配置窗口（阶段 2 核心）。

支持编辑:
- 晚自习起止时间（QTimeEdit HH:MM）；
- 科目时间段编辑器（QTableWidget：科目名/开始/结束，增删按钮、≤10 行）；
- 主窗口/悬浮球/配置窗口 3 个透明度滑条（20%–100%）；
- 窗口主题色（卡片背景 / 强调色 / 时间轴底色 / 悬浮球背景，#RRGGBB，取色器选择）；
- 「允许本地修改配置」开关（关闭时二次确认）；
- 空档期显示文本；
- 提示音：总开关、临近阈值秒数(1–3600)、near/end 各自开关与音频文件名下拉
  （来自本地已知集合：near.wav / end.wav / 缓存目录已有 wav）；
- 悬浮球尺寸 QSpinBox(32–128) —— 属本机设置，只写 local_config 不走服务器。

保存链路（业务配置单一数据源 = 服务器）：
- 在线：PUT {server}/api/config（X-Client-Token + body {config}），成功即提示；
- 离线（请求失败/未配置服务器）：写入 pending_updates.json 队列并提示
  「已离线保存，联网后自动同步」；
- 本地缓存 cache/business_config.json 只由轮询/同步更新（阶段 5），本窗口
  不直接改缓存；但保存成功后调用 ``apply_config`` 使 UI 立即生效。

allow_local_edit=false 形态：窗口打开即提示「管理员已禁止本地修改配置，
请使用远程后台」，全部控件置灰，仅允许关闭。
"""

from __future__ import annotations

import os
import re
from typing import Dict, List, Optional, Tuple

from PyQt5.QtCore import Qt, QTime
from PyQt5.QtGui import QColor
from PyQt5.QtWidgets import (
    QCheckBox,
    QColorDialog,
    QComboBox,
    QDialog,
    QFormLayout,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSlider,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QTimeEdit,
    QVBoxLayout,
    QWidget,
)

from .. import theme as theme_mod
from ..config import AppConfig, CACHE_SOUNDS_DIR, LocalConfig, save_pending
from ..logger import get_logger

logger = get_logger("config_window")

#: 默认可用音频集合（阶段 5 将扩展为服务端音频列表）
BUILTIN_AUDIO = ("near.wav", "end.wav")

_HHMM_RE = re.compile(r"^\d{1,2}:\d{2}$")
#: 主题色 #RRGGBB（与业务配置契约一致）
_HEX_RE = re.compile(r"^#[0-9A-Fa-f]{6}$")
#: theme 合法键
_THEME_KEYS = ("card", "accent", "timeline", "ball")
_THEME_LABELS = {
    "card": "卡片背景",
    "accent": "强调色",
    "timeline": "时间轴底色",
    "ball": "悬浮球背景",
}

_INPUT_STYLE = (
    "QLineEdit{border:1px solid #90E0EF;border-radius:6px;padding:5px 8px;"
    "background:#FFFFFF;font-size:13px;}"
)
_GROUP_STYLE = (
    "QGroupBox{font-weight:bold;border:1px solid #ADE8F4;border-radius:8px;"
    "margin-top:12px;padding-top:10px;}"
    "QGroupBox::title{subcontrol-origin:margin;left:10px;padding:0 4px;}"
)


# ---------------------------------------------------------------------------
# 模块级纯函数（便于单测）
# ---------------------------------------------------------------------------


def _valid_hhmm(text: str) -> bool:
    """校验 'HH:MM'（0-23:0-59）。"""
    t = (text or "").strip()
    if not _HHMM_RE.match(t):
        return False
    hh, mm = t.split(":")
    return 0 <= int(hh) <= 23 and 0 <= int(mm) <= 59


def validate_subjects(rows: List[Dict[str, str]]) -> Tuple[bool, str]:
    """校验科目列表（供表单保存前置校验与单测复用）。

    rows: [{"name", "start", "end"}, ...]，须已过滤全空行。
    校验规则：≤10 行、名称非空、时间 HH:MM 合法、start != end。
    """
    if len(rows) > 10:
        return False, "科目总数最多 10 个"
    for i, row in enumerate(rows, start=1):
        name = (row.get("name") or "").strip()
        start = (row.get("start") or "").strip()
        end = (row.get("end") or "").strip()
        if not name:
            return False, "第 %d 行：科目名不能为空" % i
        if not _valid_hhmm(start):
            return False, "第 %d 行：开始时间格式应为 HH:MM，当前为 %r" % (i, start)
        if not _valid_hhmm(end):
            return False, "第 %d 行：结束时间格式应为 HH:MM，当前为 %r" % (i, end)
        if start == end:
            return False, "第 %d 行：开始与结束时间不能相同" % i
    return True, ""


def validate_theme(values: Dict[str, str]) -> Tuple[bool, str]:
    """校验主题色四键（供表单保存前置校验与单测复用）。

    values: {"card", "accent", "timeline", "ball"}，缺键以默认主题补齐后校验。
    规则：每个值必须为 #RRGGBB（大小写不限）。
    """
    merged = dict(theme_mod.DEFAULT_THEME)
    merged.update({k: v for k, v in (values or {}).items() if k in _THEME_KEYS})
    for key in _THEME_KEYS:
        value = merged.get(key)
        if not isinstance(value, str) or not _HEX_RE.match(value.strip()):
            return False, "%s 颜色格式应为 #RRGGBB，当前为 %r" % (
                _THEME_LABELS[key], value
            )
    return True, ""


def save_via_server(
    server_base_url: str,
    client_token: str,
    config: Dict[str, object],
    timeout: float = 5.0,
    put=None,
) -> Tuple[bool, str]:
    """轻量在线保存（阶段 2 占位，api_client 完成后由其接管）。

    返回 ``(ok, message)``：
    - 网络层异常（连接失败/超时）→ (False, 离线原因)，由调用方落入待同步队列；
    - HTTP 2xx → (True, 成功消息)；
    - HTTP 4xx/5xx → (False, 错误消息，不再入队——入队也无法补传成功)。
    """
    import requests  # 已在 requirements.txt

    http_put = put or requests.put
    url = (server_base_url or "").rstrip("/") + "/api/config"
    try:
        resp = http_put(
            url,
            headers={"X-Client-Token": client_token or ""},
            json={"config": config},
            timeout=timeout,
        )
    except requests.exceptions.Timeout:
        return False, "连接服务器超时（%g 秒）" % timeout
    except requests.exceptions.ConnectionError:
        return False, "离线：无法连接服务器"
    except requests.exceptions.RequestException as exc:
        return False, "离线：请求失败（%s）" % exc

    if resp.status_code in (200, 201):
        return True, "保存成功"
    if resp.status_code in (401, 403):
        return False, "Token 无效，保存被拒绝（HTTP %s）" % resp.status_code
    return False, "服务器返回错误（HTTP %s）" % resp.status_code


# ---------------------------------------------------------------------------
# 配置窗口
# ---------------------------------------------------------------------------


class ConfigWindow(QDialog):
    """业务与本机设置编辑窗口。"""

    MAX_SUBJECTS = 10

    def __init__(
        self,
        app_config: AppConfig,
        local_config: LocalConfig,
        parent: Optional[QWidget] = None,
        save_fn=None,
        api_client=None,
    ) -> None:
        super().__init__(parent)
        self.app_config = app_config
        self.local_config = local_config
        #: 阶段 1 注入用 api_client（提供 push_config / get_audio_list）；
        #: 为空时退回模块级 save_via_server 与本地音频列表逻辑（测试/兼容）
        self.api_client = api_client
        #: 注入用保存函数，默认走模块级 save_via_server（测试可替换）
        self._save_fn = save_fn or save_via_server
        if self.api_client is not None:
            self._save_fn = self._push_via_api_client

        self._sliders: Dict[str, Tuple[QSlider, QLabel]] = {}

        self.setWindowTitle("HomeWorkTime — 配置")
        self.setModal(True)
        self.setMinimumWidth(520)

        self._allow_edit = self._resolve_allow_edit()
        self._build_ui()
        self._load_values()
        self._apply_opacity()

        if not self._allow_edit:
            self._enter_readonly_mode()

    # ------------------------------------------------------------------
    # 初始状态
    # ------------------------------------------------------------------
    def _resolve_allow_edit(self) -> bool:
        data = self.app_config.data or {}
        return bool(data.get("allow_local_edit", True))

    def _apply_opacity(self) -> None:
        opacity = float((self.app_config.data.get("opacity") or {}).get("config", 1.0))
        opacity = max(0.2, min(1.0, opacity))
        self.setWindowOpacity(opacity)

    def _enter_readonly_mode(self) -> None:
        """管理员禁止本地修改：提示 + 全部控件禁用。"""
        self.readonly_label = QLabel(
            "管理员已禁止本地修改配置，请使用远程后台。\n"
            "本窗口将以只读方式呈现当前配置。",
            self,
        )
        self.readonly_label.setStyleSheet(
            "QLabel{color:#C0392B;font-size:13px;font-weight:bold;"
            "background:#FDECEA;border:1px solid #F5B7B1;border-radius:6px;"
            "padding:8px;}"
        )
        self.readonly_label.setWordWrap(True)
        if self._form_widget is not None:
            box = self._form_widget.layout()
            if box is not None:
                box.insertWidget(0, self.readonly_label)
        for group in self._groups:
            group.setEnabled(False)
        self.save_btn.setEnabled(False)

    # ------------------------------------------------------------------
    # UI 构建
    # ------------------------------------------------------------------
    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(16, 14, 16, 14)
        root.setSpacing(10)

        # 表单承载容器（只读模式时在此插入提示条）
        self._form_widget = QWidget(self)
        root.addWidget(self._form_widget)
        form = QVBoxLayout(self._form_widget)
        form.setContentsMargins(0, 0, 0, 0)
        form.setSpacing(10)

        self._groups: List[QGroupBox] = []

        # ---- 基本信息 ----
        g1 = QGroupBox("基本信息", self._form_widget)
        g1.setStyleSheet(_GROUP_STYLE)
        g1_form = QFormLayout(g1)
        self.start_edit = QTimeEdit(self)
        self.start_edit.setDisplayFormat("HH:mm")
        self.end_edit = QTimeEdit(self)
        self.end_edit.setDisplayFormat("HH:mm")
        g1_form.addRow("晚自习开始", self.start_edit)
        g1_form.addRow("晚自习结束", self.end_edit)
        self.idle_edit = QLineEdit(self)
        self.idle_edit.setStyleSheet(_INPUT_STYLE)
        g1_form.addRow("空档期显示文本", self.idle_edit)
        self.allow_check = QCheckBox("允许在本地修改配置", self)
        g1_form.addRow("本地编辑开关", self.allow_check)
        form.addWidget(g1)
        self._groups.append(g1)

        # ---- 时间段 ----
        g2 = QGroupBox("时间段（科目 ≤ %d 个）" % self.MAX_SUBJECTS, self._form_widget)
        g2.setStyleSheet(_GROUP_STYLE)
        g2_box = QVBoxLayout(g2)
        self.table = QTableWidget(0, 3, self)
        self.table.setHorizontalHeaderLabels(["科目名", "开始", "结束"])
        self.table.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.Stretch
        )
        self.table.horizontalHeader().setSectionResizeMode(
            1, QHeaderView.ResizeToContents
        )
        self.table.horizontalHeader().setSectionResizeMode(
            2, QHeaderView.ResizeToContents
        )
        self.table.setAlternatingRowColors(True)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        g2_box.addWidget(self.table)
        btn_row = QHBoxLayout()
        self.add_btn = QPushButton("添加科目", self)
        self.del_btn = QPushButton("删除选中", self)
        btn_row.addWidget(self.add_btn)
        btn_row.addWidget(self.del_btn)
        btn_row.addStretch(1)
        g2_box.addLayout(btn_row)
        form.addWidget(g2)
        self._groups.append(g2)
        self.add_btn.clicked.connect(self._on_add_subject)
        self.del_btn.clicked.connect(self._on_delete_subject)

        # ---- 外观（透明度 + 主题色） ----
        g3 = QGroupBox("外观（透明度 / 主题色）", self._form_widget)
        g3.setStyleSheet(_GROUP_STYLE)
        g3_form = QFormLayout(g3)
        for key, label_text in (
            ("main", "主窗口"),
            ("ball", "悬浮球"),
            ("config", "配置窗口"),
        ):
            row = QHBoxLayout()
            slider = QSlider(Qt.Horizontal)
            slider.setRange(20, 100)
            slider.setFixedWidth(180)
            slider.setTickPosition(QSlider.TicksBelow)
            pct = QLabel("85%")
            pct.setFixedWidth(52)
            slider.valueChanged.connect(lambda v, p=pct: p.setText("%d%%" % v))
            row.addWidget(slider)
            row.addWidget(pct)
            row.addStretch(1)
            g3_form.addRow(label_text, row)
            self._sliders[key] = (slider, pct)

        # 主题色（点击色块打开取色器，业务配置 theme 四键）
        self._theme_btns: Dict[str, Tuple[QPushButton, QLabel]] = {}
        for key in _THEME_KEYS:
            row = QHBoxLayout()
            btn = QPushButton(self)
            btn.setFixedSize(36, 24)
            btn.setCursor(Qt.PointingHandCursor)
            btn.setFlat(True)
            btn.clicked.connect(
                lambda _=False, k=key: self._pick_theme_color(k)
            )
            hex_label = QLabel("#023E8A")
            hex_label.setFixedWidth(78)
            row.addWidget(btn)
            row.addWidget(hex_label)
            row.addStretch(1)
            g3_form.addRow(_THEME_LABELS[key], row)
            self._theme_btns[key] = (btn, hex_label)
        form.addWidget(g3)
        self._groups.append(g3)

        # ---- 提示音 ----
        g4 = QGroupBox("提示音", self._form_widget)
        g4.setStyleSheet(_GROUP_STYLE)
        g4_form = QFormLayout(g4)
        self.sound_enabled = QCheckBox("启用提示音", self)
        g4_form.addRow("总开关", self.sound_enabled)
        self.near_spin = QSpinBox(self)
        self.near_spin.setRange(1, 3600)
        self.near_spin.setSuffix(" 秒")
        g4_form.addRow("临近提示阈值", self.near_spin)
        self.near_enabled = QCheckBox("临近提示音", self)
        self.end_enabled = QCheckBox("结束提示音", self)
        g4_form.addRow("临近开关", self.near_enabled)
        g4_form.addRow("结束开关", self.end_enabled)
        self.near_combo = QComboBox(self)
        self.end_combo = QComboBox(self)
        g4_form.addRow("临近音频", self.near_combo)
        g4_form.addRow("结束音频", self.end_combo)
        form.addWidget(g4)
        self._groups.append(g4)

        # ---- 本机设置 ----
        g5 = QGroupBox("本机设置（不同步服务器）", self._form_widget)
        g5.setStyleSheet(_GROUP_STYLE)
        g5_form = QFormLayout(g5)
        self.ball_size_spin = QSpinBox(self)
        self.ball_size_spin.setRange(32, 128)
        self.ball_size_spin.setSuffix(" px")
        g5_form.addRow("悬浮球尺寸", self.ball_size_spin)
        form.addWidget(g5)
        self._groups.append(g5)

        form.addStretch(1)

        # ---- 底部按钮 ----
        bottom = QHBoxLayout()
        bottom.addStretch(1)
        self.save_btn = QPushButton("保存", self)
        self.cancel_btn = QPushButton("取消", self)
        for btn in (self.save_btn, self.cancel_btn):
            btn.setFixedWidth(96)
        bottom.addWidget(self.cancel_btn)
        bottom.addWidget(self.save_btn)
        root.addLayout(bottom)

        self.save_btn.clicked.connect(self._on_save)
        self.cancel_btn.clicked.connect(self.reject)

    # ------------------------------------------------------------------
    # 载入当前值
    # ------------------------------------------------------------------
    def _load_values(self) -> None:
        data = self.app_config.data or {}

        qs = QTime.fromString((data.get("evening_start") or "18:30"), "HH:mm")
        qe = QTime.fromString((data.get("evening_end") or "22:00"), "HH:mm")
        self.start_edit.setTime(qs.isValid() and qs or QTime(18, 30))
        self.end_edit.setTime(qe.isValid() and qe or QTime(22, 0))
        self.idle_edit.setText(data.get("idle_text") or "课间休息")
        self.allow_check.setChecked(self._allow_edit)

        # 科目表
        self.table.setRowCount(0)
        for sub in (data.get("subjects") or []):
            if not isinstance(sub, dict):
                continue
            self._append_subject_row(
                sub.get("name", ""), sub.get("start", ""), sub.get("end", "")
            )

        # 透明度滑条
        opacity = data.get("opacity") or {}
        for key in ("main", "ball", "config"):
            slider, pct = self._sliders[key]
            pct_val = int(round(float(opacity.get(key, 0.85 if key != "config" else 1.0)) * 100))
            pct_val = max(20, min(100, pct_val))
            slider.setValue(pct_val)

        # 主题色（业务配置 theme，缺省回落默认色板）
        theme_cfg = theme_mod.normalize_theme(data.get("theme"))
        for key in _THEME_KEYS:
            self._set_theme_color_ui(key, theme_cfg[key])

        # 提示音
        sound = data.get("sound") or {}
        self.sound_enabled.setChecked(bool(sound.get("enabled", True)))
        self.near_spin.setValue(int(sound.get("near_seconds", 60)))
        self.near_enabled.setChecked(bool(sound.get("near_enabled", True)))
        self.end_enabled.setChecked(bool(sound.get("end_enabled", True)))
        self._fill_audio_combos(data)

        # 本机设置
        self.ball_size_spin.setValue(int(self.local_config.get("ball_size", 64)))

    def _fill_audio_combos(self, data: Dict[str, object]) -> None:
        sound = data.get("sound") or {}
        names = self._server_audio_options()
        if names is None:
            # 服务端音频列表不可用（未注入/网络失败）→ 回落本地逻辑
            names = list(BUILTIN_AUDIO)
            cache_dir = CACHE_SOUNDS_DIR
            if os.path.isdir(cache_dir):
                for f in sorted(os.listdir(cache_dir)):
                    if f.lower().endswith(".wav") and f not in names:
                        names.append(f)
        else:
            # 保证内置项始终可选（打包资源优先，兜底）
            for n in BUILTIN_AUDIO:
                if n not in names:
                    names.append(n)
        for combo, default in (
            (self.near_combo, sound.get("near_audio") or "near.wav"),
            (self.end_combo, sound.get("end_audio") or "end.wav"),
        ):
            current = str(default)
            if current not in names:
                names.append(current)  # 保留缓存已删除但仍在配置中的值
            combo.clear()
            combo.addItems(names)
            combo.setCurrentText(current)

    def _server_audio_options(self) -> Optional[List[str]]:
        """打开窗口时刷新：从服务端拉取音频文件名列表。

        ApiClient.get_audio_list() 成功返回列表否则 None（失败回退本地逻辑）。
        """
        if self.api_client is None:
            return None
        try:
            items = self.api_client.get_audio_list() or []
        except Exception as exc:
            logger.warning("获取服务端音频列表失败，回退本地: %s", exc)
            return None
        names = [
            str(x.get("filename")) for x in items if x and x.get("filename")
        ]
        return names or None

    # ------------------------------------------------------------------
    # 主题色编辑
    # ------------------------------------------------------------------
    def _current_theme(self) -> Dict[str, str]:
        """合并默认主题与当前表单选择（供校验/收集/预览）。"""
        values = dict(theme_mod.DEFAULT_THEME)
        for key in _THEME_KEYS:
            btn, hex_label = self._theme_btns[key]
            values[key] = hex_label.text().strip()
        return values

    def _set_theme_color_ui(self, key: str, hex_color: str) -> None:
        """更新某个主题键的色块与十六进制文本。"""
        color = theme_mod.qcolor_from_hex(hex_color)
        btn, hex_label = self._theme_btns[key]
        btn.setStyleSheet(
            "QPushButton{background:%s;border:1px solid #90E0EF;"
            "border-radius:4px;}" % color.name()
        )
        hex_label.setText(color.name().upper())

    def _pick_theme_color(self, key: str) -> None:
        """点击色块 → 打开系统取色器。"""
        btn, hex_label = self._theme_btns[key]
        initial = theme_mod.qcolor_from_hex(hex_label.text())
        color = QColorDialog.getColor(initial, self, "选择%s" % _THEME_LABELS[key])
        if color.isValid():
            self._set_theme_color_ui(key, color.name())

    # ------------------------------------------------------------------
    # 科目表操作
    # ------------------------------------------------------------------
    def _append_subject_row(self, name: str, start: str, end: str) -> None:
        row = self.table.rowCount()
        self.table.insertRow(row)
        for col, value in enumerate((name, start, end)):
            item = QTableWidgetItem(value or "")
            if col > 0:
                item.setTextAlignment(Qt.AlignCenter)
            self.table.setItem(row, col, item)

    def _on_add_subject(self) -> None:
        if self.table.rowCount() >= self.MAX_SUBJECTS:
            QMessageBox.information(self, "提示", "科目最多 %d 个" % self.MAX_SUBJECTS)
            return
        self._append_subject_row("", "20:00", "21:00")

    def _on_delete_subject(self) -> None:
        rows = sorted({idx.row() for idx in self.table.selectedIndexes()}, reverse=True)
        for r in rows:
            self.table.removeRow(r)
        if not rows and self.table.rowCount() > 0:
            # 未选中任何行时删除最后一行（贴近直觉的兜底操作）
            self.table.removeRow(self.table.rowCount() - 1)

    # ------------------------------------------------------------------
    # 收集与校验
    # ------------------------------------------------------------------
    def _collect_subjects(self) -> List[Dict[str, str]]:
        rows: List[Dict[str, str]] = []
        for r in range(self.table.rowCount()):
            def _text(c: int) -> str:
                item = self.table.item(r, c)
                return item.text().strip() if item is not None else ""

            name, start, end = _text(0), _text(1), _text(2)
            if not (name or start or end):
                continue  # 视为空占位行
            rows.append({"name": name, "start": start, "end": end})
        return rows

    def _collect_config(self, data: Dict[str, object] = None) -> Dict[str, object]:
        """把表单值合并进一份业务配置 dict（以现有配置为底）。"""
        cfg = dict(data or (self.app_config.data or {}))

        cfg["evening_start"] = self.start_edit.time().toString("HH:mm")
        cfg["evening_end"] = self.end_edit.time().toString("HH:mm")
        cfg["subjects"] = self._collect_subjects()
        cfg["allow_local_edit"] = bool(self.allow_check.isChecked())
        cfg["idle_text"] = self.idle_edit.text().strip() or "课间休息"

        opacity = dict(cfg.get("opacity") or {})
        for key in ("main", "ball", "config"):
            slider, _ = self._sliders[key]
            opacity[key] = slider.value() / 100.0
        cfg["opacity"] = opacity

        # 主题色（色块选择结果；非法输入由 _validate 前置拦截）
        cfg["theme"] = {
            key: value.upper()
            for key, value in self._current_theme().items()
        }

        sound = dict(cfg.get("sound") or {})
        sound["enabled"] = bool(self.sound_enabled.isChecked())
        sound["near_seconds"] = int(self.near_spin.value())
        sound["near_enabled"] = bool(self.near_enabled.isChecked())
        sound["near_audio"] = self.near_combo.currentText()
        sound["end_enabled"] = bool(self.end_enabled.isChecked())
        sound["end_audio"] = self.end_combo.currentText()
        cfg["sound"] = sound
        return cfg

    def _validate(self) -> Tuple[bool, str]:
        ok, err = validate_subjects(self._collect_subjects())
        if not ok:
            return False, err
        start = self.start_edit.time().toString("HH:mm")
        end = self.end_edit.time().toString("HH:mm")
        if start == end:
            return False, "晚自习开始与结束时间不能相同"
        ok, err = validate_theme(self._current_theme())
        if not ok:
            return False, err
        return True, ""

    # ------------------------------------------------------------------
    # 保存链路
    # ------------------------------------------------------------------
    def _push_via_api_client(
        self, url: str, token: str, config: Dict[str, object]
    ) -> Tuple[bool, str]:
        """阶段 5：通过注入的 ApiClient 在线保存（替换 save_via_server 占位）。

        签名与模块级 save_via_server 对齐（url/token 参数忽略，以实例配置为准）：
        - push_config 成功 → (True, 成功消息)；
        - 网络不可达 → (False, "离线: ...")，由 _save 落入待同步队列；
        - Token 无效 / HTTP 拒绝 → (False, 具体错误)，由 _save 弹窗提示不入队。
        """
        try:
            ok = self.api_client.push_config(config)
        except Exception as exc:
            return False, "离线：保存调用异常（%s）" % exc
        if ok:
            return True, "保存成功"
        msg = getattr(self.api_client, "last_error", "") or "保存失败"
        if msg.startswith("Token") or msg.startswith("服务器返回错误"):
            return False, msg
        return False, "离线：%s" % msg

    def _on_save(self) -> None:
        if not self._allow_edit:
            return  # 只读形态按钮已禁用，防御

        ok, err = self._validate()
        if not ok:
            QMessageBox.warning(self, "校验失败", err)
            return

        # 「允许本地修改」被自己关掉 → 二次确认
        if self._allow_edit and not self.allow_check.isChecked():
            ret = QMessageBox.question(
                self,
                "确认",
                "关闭本地修改后，配置将只能由管理员在远程后台修改，确定继续吗？",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No,
            )
            if ret != QMessageBox.Yes:
                return

        cfg = self._collect_config()
        self._save(cfg)

    def _save(self, cfg: Dict[str, object]) -> None:
        # 1) 本机设置（悬浮球尺寸）直接写 local_config，不走服务器
        try:
            self.local_config.set("ball_size", int(self.ball_size_spin.value()))
        except Exception as exc:
            logger.warning("悬浮球尺寸保存失败: %s", exc)

        # 2) 业务配置：服务器 → 队列 两态保存
        url = (self.local_config.get("server_base_url") or "").strip()
        token = (self.local_config.get("client_token") or "").strip()
        message: str
        if not url or not token:
            message = self._save_offline(cfg)
        else:
            try:
                ok_save, msg = self._save_fn(url, token, cfg)
            except Exception as exc:
                ok_save, msg = False, "离线：保存调用异常（%s）" % exc
            if ok_save:
                message = "✓ " + msg
            elif "离线" in msg or "超时" in msg:
                # 网络不可达 → 排队补传
                message = self._save_offline(cfg)
            else:
                QMessageBox.warning(self, "保存失败", msg)
                return

        # 保存成功：apply_config 立即使 UI/主窗口等生效（缓存更新由阶段 5 接管）
        try:
            self.app_config.apply_config(cfg)
        except Exception as exc:
            logger.warning("保存后应用配置失败: %s", exc)

        QMessageBox.information(self, "设置已保存", message)
        self.accept()

    def _save_offline(self, cfg: Dict[str, object]) -> str:
        """离线保存：写入待同步队列并提示。"""
        try:
            save_pending(cfg)
        except Exception as exc:
            logger.warning("离线保存队列写入失败: %s", exc)
            return "已离线保存，但队列写入失败：%s" % exc
        logger.info("配置已离线保存，等待联网自动同步")
        return "已离线保存，联网后自动同步"