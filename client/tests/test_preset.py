# -*- coding: utf-8 -*-
"""打包预设（local_config.preset.json）单元测试。

覆盖：
1. 运行目录已有 local_config.json → 不读 preset；
2. 无 local_config + 有 preset → 生成运行目录文件、uuid 非空、
   _comment/未知键被过滤、缺失字段补默认、ball_pos 保持 null；
3. preset 中 url/token 均有值 → _needs_guide 为 False（免引导）；
4. preset 缺 token → _needs_guide 为 True；
5. preset 文件不存在 → 走默认值路径；
6. find_preset_path() 能定位真实 preset。

运行方式（项目根目录）：
    python -m unittest client.tests.test_preset -v
"""

import json
import os
import sys
import tempfile
import unittest
from unittest import mock

_TEST_DIR = os.path.dirname(os.path.abspath(__file__))
_CLIENT_DIR = os.path.dirname(_TEST_DIR)
if _CLIENT_DIR not in sys.path:
    sys.path.insert(0, _CLIENT_DIR)

# 无头平台：先于 PyQt 导入设置
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from app.config import (  # noqa: E402
    LOCAL_CONFIG_DEFAULTS,
    PRESET_FILENAME,
    LocalConfig,
    find_preset_path,
)
from app.main import _needs_guide  # noqa: E402


def _write_preset(path, **overrides):
    """构造一份打包预设 JSON（含 _comment 与白名单外未知键）。"""
    data = {
        "_comment": "打包预设说明文本",
        "_comment_server_base_url": "字段说明",
        "server_base_url": "",
        "client_token": "",
        "poll_interval_sec": 7,
        "autostart": False,
        "ball_pos": None,
        "ball_size": 64,
        "device_uuid": None,
        "unknown_extra_key": "should_not_leak",
    }
    data.update(overrides)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False)


def _read_json(path):
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)


class TestPreset(unittest.TestCase):
    """打包预设初始化本地配置的各种场景。"""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="ht_preset_")
        self.cfg_path = os.path.join(self.tmp, "local_config.json")

    def _local_with_preset(self, preset_path):
        with mock.patch("app.config.find_preset_path", return_value=preset_path):
            return LocalConfig(path=self.cfg_path)

    def test_existing_local_config_ignores_preset(self):
        """运行目录已有 local_config.json → 以文件为准，不读 preset。"""
        with open(self.cfg_path, "w", encoding="utf-8") as fh:
            json.dump(
                {"server_base_url": "http://custom:9999", "client_token": "mytok"},
                fh,
            )
        preset = os.path.join(self.tmp, "local_config.preset.json")
        _write_preset(preset, server_base_url="http://preset:1", client_token="ptok")
        local = self._local_with_preset(preset)
        # 文件中的自定义值保留（preset 未覆盖）
        self.assertEqual(local.get("server_base_url"), "http://custom:9999")
        self.assertEqual(local.get("client_token"), "mytok")
        # 持久化文件仍以已有配置为准
        raw = _read_json(self.cfg_path)
        self.assertEqual(raw["server_base_url"], "http://custom:9999")
        self.assertNotIn("_comment", raw)

    def test_preset_creates_local_config_and_filters_keys(self):
        """无 local_config + 有 preset → 生成运行目录文件：
        uuid 非空、_comment/未知键被过滤、缺失字段补默认、ball_pos 保持 null。
        """
        preset = os.path.join(self.tmp, "local_config.preset.json")
        _write_preset(
            preset,
            server_base_url="http://preset:3000",
            client_token="",
            ball_pos={"x": 11, "y": 22},  # preset 即使给了也强制 null
        )
        local = self._local_with_preset(preset)

        # 生成了运行目录文件
        self.assertTrue(os.path.exists(self.cfg_path))
        # 非空 preset 值生效
        self.assertEqual(local.get("server_base_url"), "http://preset:3000")
        self.assertEqual(local.get("poll_interval_sec"), 7)
        self.assertEqual(local.get("autostart"), False)
        # 空字符串 url/token → 回落默认值（token 默认即空串）
        self.assertEqual(local.get("client_token"), "")
        # device_uuid 已生成且非空
        self.assertTrue(local.get("device_uuid"))
        # ball_pos 保持 null
        self.assertIsNone(local.get("ball_pos"))
        # _comment / 未知键未写入生成的配置文件
        raw = _read_json(self.cfg_path)
        self.assertNotIn("_comment", raw)
        self.assertNotIn("unknown_extra_key", raw)
        self.assertIsNone(raw.get("ball_pos"))
        self.assertEqual(raw["server_base_url"], "http://preset:3000")

    def test_preset_missing_fields_filled_with_defaults(self):
        """preset 缺失字段用 default 值补全（poll_interval 等）。"""
        preset = os.path.join(self.tmp, "local_config.preset.json")
        with open(preset, "w", encoding="utf-8") as fh:
            json.dump(
                {"server_base_url": "http://preset:3000", "client_token": "tok"}, fh
            )
        local = self._local_with_preset(preset)
        self.assertEqual(
            local.get("poll_interval_sec"), LOCAL_CONFIG_DEFAULTS["poll_interval_sec"]
        )
        self.assertEqual(local.get("ball_size"), LOCAL_CONFIG_DEFAULTS["ball_size"])
        self.assertEqual(
            local.get("autostart"), LOCAL_CONFIG_DEFAULTS["autostart"]
        )

    def test_preset_with_credentials_no_guide(self):
        """preset url/token 均有值 → _needs_guide 为 False（免引导）。"""
        preset = os.path.join(self.tmp, "local_config.preset.json")
        _write_preset(
            preset,
            server_base_url="http://srv:3000",
            client_token="realtoken123",
        )
        local = self._local_with_preset(preset)
        self.assertFalse(_needs_guide(local), "url/token 齐全时应免引导")

    def test_preset_missing_token_needs_guide(self):
        """preset 缺 token（或为空）→ _needs_guide 为 True。"""
        preset = os.path.join(self.tmp, "local_config.preset.json")
        _write_preset(preset, server_base_url="http://srv:3000", client_token="")
        local = self._local_with_preset(preset)
        self.assertTrue(_needs_guide(local), "token 未配置时应弹引导")

    def test_no_preset_uses_defaults(self):
        """preset 文件不存在 → 走默认值路径（示例模板 + 默认值）。"""
        preset = os.path.join(self.tmp, "local_config.preset.json")
        with mock.patch("app.config.find_preset_path", return_value=None):
            local = LocalConfig(path=self.cfg_path)
        self.assertTrue(os.path.exists(self.cfg_path))
        self.assertEqual(
            local.get("server_base_url"), LOCAL_CONFIG_DEFAULTS["server_base_url"]
        )
        self.assertEqual(local.get("client_token"), "")
        self.assertTrue(local.get("device_uuid"))

    def test_find_preset_path_detects_real_preset(self):
        """find_preset_path() 在项目内可定位到真实打包预设。"""
        path = find_preset_path()
        self.assertIsNotNone(path, "client/ 下应存在打包预设")
        self.assertEqual(os.path.basename(path), PRESET_FILENAME)


if __name__ == "__main__":
    unittest.main(verbosity=2)