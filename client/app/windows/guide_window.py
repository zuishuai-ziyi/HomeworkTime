# -*- coding: utf-8 -*-
"""首次运行引导窗口（阶段 2）。

触发条件：local_config 中 ``server_base_url`` 或 ``client_token`` 为空时由
主程序弹出（模态流程）。

- 小窗口、固定尺寸、普通窗口样式 + 置顶；
- 说明文字 + 服务器地址输入框（默认填 local_config 现值）+ Token 输入框
  （密码模式）+ 「测试连接」按钮 + 「保存并进入」按钮 + 「跳过（离线模式）」
  按钮 + 状态提示 label；
- 测试连接::

      GET {server_base_url}/api/client/config
      Header: X-Client-Token: <token>
      timeout=5s

  成功显示「✓ 连接成功（配置版本 vN）」，失败显示具体错误
  （超时 / 403 Token 无效 / 无法连接等）。

「保存并进入」Accept → 主程序将 URL/Token 写回 local_config 后继续启动；
「跳过（离线模式）」Reject → 直接进入，使用内置默认配置。
"""

from __future__ import annotations

from typing import Optional, Tuple

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ..config import resource_path
from ..logger import get_logger

logger = get_logger("guide")

#: 引导窗口固定尺寸
GUIDE_WIDTH = 460
GUIDE_HEIGHT = 330

_HEADER_STYLE = (
    "QLabel{color:#3B4658;font-size:15px;font-weight:bold;background:transparent;}"
)
_TEXT_STYLE = "QLabel{color:#4A5568;font-size:12px;background:transparent;}"
_INPUT_STYLE = (
    "QLineEdit{border:1px solid #90E0EF;border-radius:6px;padding:6px 8px;"
    "background:#FFFFFF;font-size:13px;}"
    "QLineEdit:focus{border-color:#0077B6;}"
)
_BTN_STYLE = (
    "QPushButton{background:#0077B6;color:#FFFFFF;border:none;border-radius:6px;"
    "padding:8px 14px;font-size:13px;}"
    "QPushButton:hover{background:#00558F;}"
    "QPushButton:disabled{background:#90E0EF;color:#023E8A;}"
)
_SEC_BTN_STYLE = (
    "QPushButton{background:#ADE8F4;color:#023E8A;border:none;border-radius:6px;"
    "padding:8px 14px;font-size:13px;}"
    "QPushButton:hover{background:#90E0EF;}"
)


def test_connection(
    server_base_url: str,
    token: str,
    timeout: float = 5.0,
    get=None,
) -> Tuple[bool, str]:
    """模块级测试连接函数（便于单测注入 ``get``）。

    返回 ``(ok, message)``：
    - 成功且返回 version → (True, "✓ 连接成功（配置版本 vN）")；
    - 超时/无法连接/HTTP 4xx/5xx → (False, 具体原因)。
    """
    import requests  # 已在 requirements.txt

    http_get = get or requests.get
    url = (server_base_url or "").rstrip("/") + "/api/client/config"
    try:
        resp = http_get(
            url,
            headers={"X-Client-Token": token or ""},
            timeout=timeout,
        )
    except requests.exceptions.Timeout:
        return False, "连接超时（%g 秒），请检查网络" % timeout
    except requests.exceptions.ConnectionError:
        return False, "无法连接服务器，请检查地址与端口"
    except requests.exceptions.RequestException as exc:
        return False, "请求失败：%s" % exc

    if resp.status_code == 200:
        version = None
        try:
            version = (resp.json() or {}).get("version")
        except ValueError:
            version = None
        if version is not None:
            return True, "✓ 连接成功（配置版本 v%s）" % version
        return True, "✓ 连接成功"
    if resp.status_code in (401, 403):
        return False, "Token 无效（HTTP %s）" % resp.status_code
    return False, "服务器返回错误（HTTP %s）" % resp.status_code


class GuideWindow(QDialog):
    """首次运行引导窗口。"""

    def __init__(
        self,
        server_base_url: str = "",
        client_token: str = "",
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(
            parent,
            Qt.WindowTitleHint | Qt.WindowSystemMenuHint
            | Qt.WindowCloseButtonHint | Qt.WindowStaysOnTopHint,
        )
        self.setWindowTitle("首次使用引导")
        self.setFixedSize(GUIDE_WIDTH, GUIDE_HEIGHT)
        self.setModal(True)
        self.setStyleSheet("QDialog{background:#CAF0F8;}")

        self._url = server_base_url or ""
        self._token = client_token or ""

        self._build_ui()

    # ------------------------------------------------------------------
    # UI 构建
    # ------------------------------------------------------------------
    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(24, 20, 24, 20)
        root.setSpacing(12)

        header = QLabel("欢迎使用作业时间提醒", self)
        header.setStyleSheet(_HEADER_STYLE)
        root.addWidget(header)

        desc = QLabel(
            "请填写服务器的地址与客户端 Token，完成连接测试后即可开始使用。\n"
            "也可以选择「跳过（离线模式）」稍后配置。",
            self,
        )
        desc.setWordWrap(True)
        desc.setStyleSheet(_TEXT_STYLE)
        root.addWidget(desc)

        # 服务器地址
        url_label = QLabel("服务器地址", self)
        url_label.setStyleSheet(_TEXT_STYLE)
        root.addWidget(url_label)
        self.url_edit = QLineEdit(self._url, self)
        self.url_edit.setPlaceholderText("http://服务器IP:3000")
        self.url_edit.setStyleSheet(_INPUT_STYLE)
        root.addWidget(self.url_edit)

        # Token
        token_label = QLabel("客户端 Token", self)
        token_label.setStyleSheet(_TEXT_STYLE)
        root.addWidget(token_label)
        self.token_edit = QLineEdit(self._token, self)
        self.token_edit.setEchoMode(QLineEdit.Password)
        self.token_edit.setPlaceholderText("由管理后台下发的客户端 Token")
        self.token_edit.setStyleSheet(_INPUT_STYLE)
        root.addWidget(self.token_edit)

        # 按钮行
        btn_row = QHBoxLayout()
        btn_row.setSpacing(10)
        self.test_btn = QPushButton("测试连接", self)
        self.test_btn.setStyleSheet(_SEC_BTN_STYLE)
        self.save_btn = QPushButton("保存并进入", self)
        self.save_btn.setStyleSheet(_BTN_STYLE)
        self.skip_btn = QPushButton("跳过（离线模式）", self)
        self.skip_btn.setStyleSheet(_SEC_BTN_STYLE)
        btn_row.addWidget(self.test_btn)
        btn_row.addWidget(self.save_btn)
        btn_row.addWidget(self.skip_btn)
        root.addLayout(btn_row)

        # 状态提示
        self.status_label = QLabel("", self)
        self.status_label.setWordWrap(True)
        self.status_label.setStyleSheet(
            "QLabel{color:#4A5568;font-size:12px;background:transparent;}"
        )
        root.addWidget(self.status_label)
        root.addStretch(1)

        # 信号
        self.test_btn.clicked.connect(self._on_test)
        self.save_btn.clicked.connect(self._on_save)
        self.skip_btn.clicked.connect(self.reject)

    # ------------------------------------------------------------------
    # 交互
    # ------------------------------------------------------------------
    def _on_test(self) -> None:
        url = self.url_edit.text().strip()
        token = self.token_edit.text().strip()
        if not url:
            self._set_status("请先填写服务器地址", error=True)
            return
        self.test_btn.setEnabled(False)
        self.status_label.setText("正在测试连接…")
        try:
            ok, message = test_connection(url, token)
        except Exception as exc:
            ok, message = False, "测试连接异常：%s" % exc
        finally:
            self.test_btn.setEnabled(True)
        self._set_status(message, error=not ok)

    def _on_save(self) -> None:
        if not self.url_edit.text().strip():
            self._set_status("请先填写服务器地址", error=True)
            return
        self.accept()

    def _set_status(self, message: str, error: bool = False) -> None:
        color = "#16A34A" if not error else "#DC2626"
        self.status_label.setStyleSheet(
            "QLabel{color:%s;font-size:12px;background:transparent;}"
            "font-weight:bold;" % color
        )
        self.status_label.setText(message)

    # ------------------------------------------------------------------
    # 取值
    # ------------------------------------------------------------------
    def current_values(self) -> Tuple[str, str]:
        """返回 (服务器地址, Token) 供主程序写回 local_config。"""
        return (
            self.url_edit.text().strip(),
            self.token_edit.text().strip(),
        )