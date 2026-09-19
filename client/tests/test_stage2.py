# -*- coding: utf-8 -*-
"""阶段 2 本地化能力单元测试（unittest）。

覆盖：
- logger：写文件 / 按天命名 / 过期清理；
- single_instance：同进程两次创建，第二次 is_primary=False；destroy 后可重建；
- autostart：mock winreg 校验逻辑；Windows 上真实写注册表后立即还原；
- pending_updates 队列读写（save_pending / load_pending / clear_pending）；
- config_window.validate_subjects 校验；
- save_via_server（在线/离线/HTTP 错误）与 guide.test_connection（mock 网络）；
- UI 冒烟：GuideWindow、ConfigWindow（允许编辑/只读两态）、Tray 构造不抛异常。

运行方式（项目根目录）：
    python -m unittest client.tests.test_stage2 -v
"""

import os
import sys
import tempfile
import time
import unittest
from unittest import mock

# 无头平台：必须早于 PyQt 导入设置
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

_TEST_DIR = os.path.dirname(os.path.abspath(__file__))
_CLIENT_DIR = os.path.dirname(_TEST_DIR)
if _CLIENT_DIR not in sys.path:
    sys.path.insert(0, _CLIENT_DIR)

import requests  # noqa: E402

from PyQt5.QtCore import QCoreApplication  # noqa: E402
from PyQt5.QtWidgets import QApplication  # noqa: E402

#: 整个模块共用同一个 Qt 应用实例（offscreen）。
# 注意：不能在已创建 QCoreApplication 之后再创建 QApplication（Qt 报
# "Please instantiate the QApplication object first" 并终止），因此此处
# 模块级统一创建一次，所有测试类复用（SingleInstance 逻辑测试同样可
# 通过 QCoreApplication.instance() 复用该实例）。
_QT_APP = QApplication.instance() or QApplication(["stage2"])

from app import autostart  # noqa: E402
from app.config import (  # noqa: E402
    DEFAULT_CONFIG_PATH,
    AppConfig,
    LocalConfig,
    clear_pending,
    load_pending,
    save_pending,
)
from app.logger import get_logger, setup_logging  # noqa: E402
from app.main import _needs_guide, _run_guide_if_needed  # noqa: E402
from app.single_instance import SingleInstance  # noqa: E402
from app.windows.config_window import (  # noqa: E402
    ConfigWindow,
    save_via_server,
    validate_subjects,
)
from app.windows.guide_window import GuideWindow, test_connection  # noqa: E402
from app.windows.tray import Tray  # noqa: E402


def _wait_for(predicate, timeout=2.0, interval=0.02) -> bool:
    """驱动 Qt 事件循环直至谓词成立或超时。"""
    deadline = time.time() + timeout
    app = QCoreApplication.instance()
    while time.time() < deadline:
        if predicate():
            return True
        if app is not None:
            app.processEvents()
        time.sleep(interval)
    return predicate()


# ---------------------------------------------------------------------------
# logger
# ---------------------------------------------------------------------------


class TestLogger(unittest.TestCase):
    """按天日志：写文件、按天命名、过期清理。"""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="ht_log_")

    def test_write_file_and_daily_name(self):
        setup_logging(log_dir=self.tmp, force=True)
        logger = get_logger("stage2")
        logger.info("hello stage2")
        today = time.strftime("%Y-%m-%d")
        path = os.path.join(self.tmp, "app_%s.log" % today)
        self.assertTrue(os.path.exists(path), "日志文件应按天命名")
        with open(path, "r", encoding="utf-8") as fh:
            content = fh.read()
        self.assertIn("hello stage2", content)
        # 格式含时间 / 级别 / 模块
        self.assertIn("INFO", content)
        self.assertRegex(content, r"app\.stage2")

    def test_cleanup_old_files(self):
        # 预置过期日志 / 当天日志 / 未来保留
        old = os.path.join(self.tmp, "app_2020-01-01.log")
        with open(old, "w", encoding="utf-8") as fh:
            fh.write("old")
        today = time.strftime("%Y-%m-%d")
        current = os.path.join(self.tmp, "app_%s.log" % today)
        with open(current, "w", encoding="utf-8") as fh:
            fh.write("today")
        setup_logging(log_dir=self.tmp, force=True)
        self.assertFalse(os.path.exists(old), "过期日志应被清理")
        self.assertTrue(os.path.exists(current), "当天日志保留")
        self.assertTrue(
            get_logger("stage2") is not None, "get_logger 对象可用"
        )


# ---------------------------------------------------------------------------
# single_instance
# ---------------------------------------------------------------------------


class TestSingleInstance(unittest.TestCase):
    """单实例：同进程两次创建 / destroy 后重建。"""

    KEY = "HTTestSingleInstance"

    @classmethod
    def setUpClass(cls):
        cls.core = QCoreApplication.instance()  # 复用模块级 QApplication

    def test_second_instance_is_not_primary(self):
        si1 = SingleInstance(self.KEY)
        self.assertTrue(si1.is_primary, "第一个实例应为主实例")
        try:
            received = []
            si1.new_message.connect(lambda m: received.append(m))
            si2 = SingleInstance(self.KEY)
            self.assertFalse(si2.is_primary, "第二个实例不应是主实例")
            # si2 创建时已向既有实例发送 "show"，等待主实例接收
            self.assertTrue(
                _wait_for(lambda: bool(received), timeout=3.0),
                "主实例应收到唤醒消息",
            )
            self.assertTrue(any("show" in m for m in received))
            si2.destroy()
        finally:
            si1.destroy()

    def test_recreate_after_destroy(self):
        si1 = SingleInstance(self.KEY)
        self.assertTrue(si1.is_primary)
        si1.destroy()
        si2 = SingleInstance(self.KEY)
        self.assertTrue(si2.is_primary, "destroy 后应可重新成为主实例")
        si2.destroy()

    def test_notify_message_payload(self):
        si1 = SingleInstance(self.KEY + "_notify")
        try:
            received = []
            si1.new_message.connect(lambda m: received.append(m))
            si2 = SingleInstance(self.KEY + "_notify")
            self.assertFalse(si2.is_primary)
            si2.notify("show")  # 显式再通知一次
            self.assertTrue(
                _wait_for(lambda: received and received[-1] == "show", timeout=3.0)
            )
            si2.destroy()
        finally:
            si1.destroy()


# ---------------------------------------------------------------------------
# autostart
# ---------------------------------------------------------------------------


class _FakeKey:
    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


class _FakeRegistry:
    """内存版 winreg：记录 HKCU\\...\\Run 的值，便于 mock 断言。"""

    HKEY_CURRENT_USER = 1
    KEY_SET_VALUE = 2
    REG_SZ = 1

    def __init__(self):
        self.values = {}

    def OpenKey(self, root, subkey):
        return _FakeKey()

    def CreateKey(self, root, subkey):
        return _FakeKey()

    def QueryValueEx(self, key, name):
        if name not in self.values:
            raise OSError(2, "No such value")
        return self.values[name], self.REG_SZ

    def SetValueEx(self, key, name, reserved, typ, value):
        self.values[name] = value

    def DeleteValue(self, key, name):
        if name not in self.values:
            raise OSError(2, "No such value")
        del self.values[name]

    def CloseKey(self, key):
        pass


class TestAutostart(unittest.TestCase):
    """开机自启：命令构造 + mock winreg + Windows 真实写还原。"""

    def test_command_contains_main_script(self):
        cmd = autostart._command()
        self.assertIn("main.py", cmd)
        self.assertIn('"', cmd)  # 两侧引号包裹

    def test_mock_registry_roundtrip(self):
        fake = _FakeRegistry()
        with mock.patch.object(autostart, "winreg", fake):
            self.assertFalse(autostart.is_autostart_enabled())
            self.assertTrue(autostart.set_autostart(True))
            self.assertTrue(autostart.is_autostart_enabled())
            self.assertTrue(autostart.set_autostart(False))
            self.assertFalse(autostart.is_autostart_enabled())
            # 键名与值符合要求
            autostart.set_autostart(True)
            self.assertIn("HomeworkTime", fake.values)
            self.assertIn("main.py", fake.values["HomeworkTime"])

    def test_non_windows_returns_false(self):
        with mock.patch.object(autostart, "winreg", None):
            self.assertFalse(autostart.is_autostart_enabled())
            self.assertFalse(autostart.set_autostart(True))

    @unittest.skipUnless(sys.platform == "win32", "仅 Windows 真实注册表")
    def test_real_registry_roundtrip(self):
        before = autostart.is_autostart_enabled()
        try:
            autostart.set_autostart(False)
            self.assertFalse(autostart.is_autostart_enabled())
            autostart.set_autostart(True)
            self.assertTrue(autostart.is_autostart_enabled())
        finally:
            autostart.set_autostart(before)  # 立即还原


# ---------------------------------------------------------------------------
# pending_updates 队列
# ---------------------------------------------------------------------------


class TestPendingUpdates(unittest.TestCase):
    """离线保存队列：append / load / clear。"""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="ht_pending_")
        self.path = os.path.join(self.tmp, "pending_updates.json")

    def test_roundtrip(self):
        save_pending({"evening_start": "18:30"}, path=self.path)
        save_pending({"evening_start": "19:00"}, path=self.path)
        items = load_pending(self.path)
        self.assertEqual(len(items), 2)
        self.assertEqual(items[0]["config"]["evening_start"], "18:30")
        self.assertEqual(items[1]["config"]["evening_start"], "19:00")
        self.assertIn("ts", items[0])
        self.assertTrue(os.path.exists(self.path))

    def test_clear(self):
        save_pending({"a": 1}, path=self.path)
        self.assertTrue(clear_pending(self.path))
        self.assertFalse(os.path.exists(self.path))
        self.assertEqual(load_pending(self.path), [])

    def test_missing_file_returns_empty(self):
        self.assertEqual(load_pending(self.path), [])


# ---------------------------------------------------------------------------
# config_window 純函数：validate_subjects / save_via_server
# ---------------------------------------------------------------------------


class TestValidateSubjects(unittest.TestCase):
    def test_valid_rows(self):
        ok, err = validate_subjects([
            {"name": "语文", "start": "18:30", "end": "19:20"},
            {"name": "数学", "start": "19:20", "end": "20:10"},
        ])
        self.assertTrue(ok, err)

    def test_empty_name(self):
        ok, err = validate_subjects([{"name": " ", "start": "18:30", "end": "19:20"}])
        self.assertFalse(ok)
        self.assertIn("科目名不能为空", err)

    def test_start_equals_end(self):
        ok, err = validate_subjects([{"name": "语文", "start": "18:30", "end": "18:30"}])
        self.assertFalse(ok)
        self.assertIn("不能相同", err)

    def test_invalid_time(self):
        ok, err = validate_subjects([{"name": "语文", "start": "18:99", "end": "19:20"}])
        self.assertFalse(ok)
        self.assertIn("HH:MM", err)

    def test_max_rows(self):
        rows = [
            {"name": "科目%d" % i, "start": "18:%02d" % i, "end": "19:%02d" % i}
            for i in range(11)
        ]
        rows[10]["end"] = "20:00"
        ok, err = validate_subjects(rows)
        self.assertFalse(ok)
        self.assertIn("10", err)


class _FakeResp:
    def __init__(self, status_code, json_data=None):
        self.status_code = status_code
        self._json = json_data

    def json(self):
        if self._json is None:
            raise ValueError("no json body")
        return self._json


class TestSaveViaServer(unittest.TestCase):
    """在线保存：成功 / 超时离线 / 403 / HTTP 5xx。"""

    def test_online_success(self):
        def put(url, headers=None, json=None, timeout=None):
            return _FakeResp(200)

        ok, msg = save_via_server("http://srv", "tok", {"a": 1}, put=put)
        self.assertTrue(ok, msg)

    def test_timeout_goes_offline(self):
        def put(url, headers=None, json=None, timeout=None):
            raise requests.exceptions.ConnectTimeout("slow")

        ok, msg = save_via_server("http://srv", "tok", {"a": 1}, put=put)
        self.assertFalse(ok)
        self.assertIn("超时", msg)

    def test_connection_error_goes_offline(self):
        def put(url, headers=None, json=None, timeout=None):
            raise requests.exceptions.ConnectionError("down")

        ok, msg = save_via_server("http://srv", "tok", {"a": 1}, put=put)
        self.assertFalse(ok)
        self.assertIn("离线", msg)

    def test_403_token_invalid(self):
        def put(url, headers=None, json=None, timeout=None):
            return _FakeResp(403)

        ok, msg = save_via_server("http://srv", "tok", {"a": 1}, put=put)
        self.assertFalse(ok)
        self.assertIn("Token 无效", msg)

    def test_http_500_fails(self):
        def put(url, headers=None, json=None, timeout=None):
            return _FakeResp(500)

        ok, msg = save_via_server("http://srv", "tok", {"a": 1}, put=put)
        self.assertFalse(ok)
        self.assertIn("HTTP 500", msg)

    def test_headers_sent(self):
        captured = {}

        def put(url, headers=None, json=None, timeout=None):
            captured.update(headers=headers, json=json)
            return _FakeResp(200)

        save_via_server("http://srv/", "mytok", {"k": "v"}, put=put)
        self.assertEqual(captured["headers"]["X-Client-Token"], "mytok")
        self.assertEqual(captured["json"], {"config": {"k": "v"}})


# ---------------------------------------------------------------------------
# guide：测试连接
# ---------------------------------------------------------------------------


def _guide_get(resp_or_exc):
    def get(url, headers=None, timeout=None):
        if isinstance(resp_or_exc, Exception):
            raise resp_or_exc
        return resp_or_exc
    return get


class TestGuideConnection(unittest.TestCase):
    def test_success_with_version(self):
        ok, msg = test_connection(
            "http://srv", "tok", get=_guide_get(_FakeResp(200, {"version": 3}))
        )
        self.assertTrue(ok)
        self.assertIn("配置版本 v3", msg)
        self.assertTrue(msg.startswith("✓"))

    def test_success_without_version(self):
        ok, msg = test_connection(
            "http://srv", "tok", get=_guide_get(_FakeResp(200))
        )
        self.assertTrue(ok)

    def test_token_invalid_403(self):
        ok, msg = test_connection(
            "http://srv", "tok", get=_guide_get(_FakeResp(403))
        )
        self.assertFalse(ok)
        self.assertIn("Token 无效", msg)

    def test_timeout(self):
        ok, msg = test_connection(
            "http://srv", "tok",
            get=_guide_get(requests.exceptions.Timeout()),
        )
        self.assertFalse(ok)
        self.assertIn("超时", msg)

    def test_connection_error(self):
        ok, msg = test_connection(
            "http://srv", "tok",
            get=_guide_get(requests.exceptions.ConnectionError("refused")),
        )
        self.assertFalse(ok)
        self.assertIn("无法连接", msg)


# ---------------------------------------------------------------------------
# ConfigWindow 保存链路
# ---------------------------------------------------------------------------


class TestConfigWindowSave(unittest.TestCase):
    """在线 / 离线 两态保存路径（QMessageBox 打桩，避免模态阻塞）。"""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="ht_cfg_save_")
        self.local = LocalConfig(path=os.path.join(self.tmp, "local_config.json"))
        self.biz = AppConfig(
            cache_path=os.path.join(self.tmp, "business_config.json"),
            default_path=DEFAULT_CONFIG_PATH,
            load_now=True,
        )
        self.w = ConfigWindow(self.biz, self.local)

    def tearDown(self):
        self.w.close()

    def test_online_success_uses_save_fn(self):
        self.local.set("client_token", "mytoken")  # 配置 token 走在线分支
        calls = []

        def save_fn(url, token, cfg):
            calls.append((url, token))
            return True, "保存成功"

        self.w._save_fn = save_fn
        with mock.patch("app.windows.config_window.QMessageBox"):
            self.w._save(self.w._collect_config())

        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0][0], "http://127.0.0.1:3000")
        self.assertEqual(calls[0][1], "mytoken")
        # 保存成功后业务配置已 apply（UI 立即生效）
        self.assertEqual(self.biz.data["allow_local_edit"], True)

    def test_offline_connection_error_writes_pending(self):
        def save_fn(url, token, cfg):
            raise requests.exceptions.ConnectionError("off")

        self.w._save_fn = save_fn
        captured = {}

        def fake_pending(cfg, timestamp=None, path=None):
            captured["cfg"] = cfg

        with mock.patch("app.windows.config_window.QMessageBox"), \
                mock.patch("app.windows.config_window.save_pending", fake_pending):
            self.w._save(self.w._collect_config())

        self.assertIn("cfg", captured, "离线时应调用 save_pending 入队")
        self.assertEqual(
            captured["cfg"]["evening_start"],
            self.w.start_edit.time().toString("HH:mm"),
        )

    def test_unconfigured_server_goes_offline(self):
        # 默认 local token 为空 → 即使 URL 存在也直接落队列
        captured = {}

        def fake_pending(cfg, timestamp=None, path=None):
            captured["cfg"] = cfg

        with mock.patch("app.windows.config_window.QMessageBox"), \
                mock.patch("app.windows.config_window.save_pending", fake_pending):
            self.w._save(self.w._collect_config())

        self.assertIn("cfg", captured, "未配置服务器时应离线入队")
        # 队列已写入的消息文案不应丢失业务配置
        self.assertTrue(captured["cfg"]["subjects"])


# ---------------------------------------------------------------------------
# UI 冒烟（offscreen）
# ---------------------------------------------------------------------------


class TestUIWidgets(unittest.TestCase):
    """offscreen 下实例化阶段 2 各窗口不抛异常。"""

    @classmethod
    def setUpClass(cls):
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        cls.app = QApplication.instance()  # 复用模块级 QApplication

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="ht_ui_")
        self.local = LocalConfig(path=os.path.join(self.tmp, "local_config.json"))
        self.biz = AppConfig(
            cache_path=os.path.join(self.tmp, "business_config.json"),
            default_path=DEFAULT_CONFIG_PATH,
            load_now=True,
        )

    def test_guide_window(self):
        g = GuideWindow("http://127.0.0.1:3000", "tok123")
        self.assertEqual(g.current_values(), ("http://127.0.0.1:3000", "tok123"))
        g.close()

    def test_config_window_editable(self):
        w = ConfigWindow(self.biz, self.local)
        self.assertTrue(w.allow_check.isChecked())
        self.assertTrue(w.save_btn.isEnabled())
        self.assertEqual(w.ball_size_spin.value(), 64)
        w.close()

    def test_config_window_readonly_mode(self):
        self.biz.data["allow_local_edit"] = False
        w = ConfigWindow(self.biz, self.local)
        self.assertFalse(w.save_btn.isEnabled(), "只读形态保存按钮应禁用")
        self.assertFalse(w.allow_check.isEnabled(), "只读形态控件应禁用")
        self.assertTrue(hasattr(w, "readonly_label"))
        w.close()

    def test_tray(self):
        tray = Tray()
        calls = []
        checked_state = []
        tray.set_callbacks(
            show_main=lambda: calls.append("show"),
            autostart_toggled=lambda checked: checked_state.append(checked),
        )
        tray.set_autostart_checked(True)
        self.assertTrue(tray.autostart_action.isChecked())
        tray._on_autostart_toggled(True)   # 模拟勾选事件
        tray._on_autostart_toggled(False)
        self.assertEqual(checked_state, [True, False], "自启回调应携带 checked")
        tray.show()
        tray.show_message("标题", "内容")
        tray.close()


# ---------------------------------------------------------------------------
# 引导窗口跳过逻辑（guide_dismissed 持久化）
# ---------------------------------------------------------------------------


class TestGuideDismissed(unittest.TestCase):
    """_needs_guide / _run_guide_if_needed：用户明确选择离线模式后不再骚扰。"""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="ht_guide_")
        self.path = os.path.join(self.tmp, "local_config.json")

    def _make_local(self) -> LocalConfig:
        return LocalConfig(path=self.path)

    def test_dismissed_true_returns_false_even_without_credentials(self):
        """用户已跳过引导 → 即使 url/token 都为空也不再弹出。"""
        local = self._make_local()
        local.set("server_base_url", "")
        local.set("client_token", "")
        local.set("guide_dismissed", True)
        self.assertFalse(
            _needs_guide(local),
            "guide_dismissed=True 时不应再弹引导",
        )

    def test_empty_token_and_dismissed_false_returns_true(self):
        """url 已配但 token 仍空 + 未跳过 → 仍需引导。"""
        local = self._make_local()
        local.set("server_base_url", "http://127.0.0.1:3000")
        local.set("client_token", "")
        # guide_dismissed 默认 False
        self.assertTrue(
            _needs_guide(local),
            "token 空且未跳过时应返回 True",
        )

    def test_full_credentials_and_dismissed_false_returns_false(self):
        """url/token 都齐 + 未跳过 → 不需要引导。"""
        local = self._make_local()
        local.set("server_base_url", "http://127.0.0.1:3000")
        local.set("client_token", "tok123")
        self.assertFalse(_needs_guide(local))

    def test_skip_writes_guide_dismissed(self):
        """_run_guide_if_needed 在用户跳过（Reject）分支写入 guide_dismissed=True。

        直接构造 LocalConfig（临时目录），mock GuideWindow.exec_ 为 Rejected，
        验证写回配置 + 日志行为。
        """
        from PyQt5.QtWidgets import QDialog

        local = self._make_local()
        local.set("server_base_url", "")
        local.set("client_token", "")
        local.set("guide_dismissed", False)
        # 直接断言初始状态
        self.assertFalse(
            bool(local.get("guide_dismissed")),
            "测试前置：guide_dismissed 应为 False",
        )

        with mock.patch(
            "app.main.GuideWindow"
        ) as MockGuide:
            instance = MockGuide.return_value
            instance.exec_.return_value = QDialog.Rejected
            instance.current_values.return_value = ("", "")
            result = _run_guide_if_needed(local)

        self.assertFalse(result, "跳过应返回 False")
        self.assertTrue(
            bool(local.get("guide_dismissed")),
            "跳过分支应写入 guide_dismissed=True",
        )
        # 重启模拟：新建 LocalConfig 实例（同 path）→ 仍能读到 dismissed
        reloaded = LocalConfig(path=self.path)
        self.assertTrue(
            bool(reloaded.get("guide_dismissed")),
            "guide_dismissed 应已持久化到文件",
        )

    def test_accepted_clears_guide_dismissed(self):
        """_run_guide_if_needed 在 Accepted 分支把 guide_dismissed 置回 False。"""
        from PyQt5.QtWidgets import QDialog

        local = self._make_local()
        local.set("server_base_url", "http://old")
        local.set("client_token", "oldtok")
        local.set("guide_dismissed", True)  # 假设上次被跳过

        with mock.patch(
            "app.main.GuideWindow"
        ) as MockGuide:
            instance = MockGuide.return_value
            instance.exec_.return_value = QDialog.Accepted
            instance.current_values.return_value = (
                "http://127.0.0.1:3000",
                "newtok",
            )
            result = _run_guide_if_needed(local)

        self.assertTrue(result, "Accepted 应返回 True")
        self.assertFalse(
            bool(local.get("guide_dismissed")),
            "Accepted 应清除之前的 dismissed 标记",
        )
        self.assertEqual(local.get("server_base_url"), "http://127.0.0.1:3000")
        self.assertEqual(local.get("client_token"), "newtok")


if __name__ == "__main__":
    unittest.main(verbosity=2)