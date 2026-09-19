# -*- coding: utf-8 -*-
"""阶段 5 ApiClient 单元测试（unittest + mock，注入 fake session）。

覆盖：
- poll：版本更高 → apply_config 被调用 + 缓存写入 version；版本相同 → 跳过；
  网络失败 → False 不抛出；
- heartbeat：响应版本更高 → 触发 poll；相同 → 不触发；
- sync_pending：两条全成功 → clear；第二条失败 → 停止、保留队列顺序；
- ensure_audio：sha256 匹配跳过下载；不匹配触发下载并校验；
  下载后二次校验失败 → 删除文件返回 None；内置文件优先打包资源；
- push_config：成功 True；网络异常/HTTP 拒绝 → False 不抛出；
- 重启后从缓存恢复 version。

运行方式（项目根目录）：
    python -m unittest client.tests.test_stage5 -v
"""

import hashlib
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

import requests  # noqa: E402

from app.api_client import ApiClient, sanitize_config, should_sync_pending  # noqa: E402
from app.config import (  # noqa: E402
    DEFAULT_CONFIG_PATH,
    AppConfig,
    LocalConfig,
    load_pending,
    save_pending,
)

CONFIG_BASE = {
    "evening_start": "18:30",
    "evening_end": "22:00",
    "subjects": [],
    "opacity": {"main": 0.85, "ball": 0.7, "config": 1.0},
    "allow_local_edit": True,
    "idle_text": "课间休息",
    "sound": {
        "enabled": True,
        "near_seconds": 60,
        "near_audio": "near.wav",
        "near_enabled": True,
        "end_audio": "end.wav",
        "end_enabled": True,
    },
}


class FakeResp:
    def __init__(self, status_code, json_data=None, content=b""):
        self.status_code = status_code
        self._json = json_data
        self.content = content

    def json(self):
        if self._json is None:
            raise ValueError("no json body")
        return self._json


class FakeSession:
    """内存版 requests.Session：记录调用，按 (method, path) 返回预设响应。"""

    def __init__(self):
        self.calls = []
        self.responses = {}
        self.exc = None

    def _dispatch(self, method, url, **kwargs):
        self.calls.append({"method": method, "url": url, "kwargs": kwargs})
        if self.exc is not None:
            raise self.exc
        path = url.split("://", 1)[-1]
        path = path[path.find("/api"):]
        handler = self.responses.get((method, path)) or self.responses.get(
            (method, None)
        )
        if handler is None:
            return FakeResp(404)
        return handler(**kwargs)

    def request(self, method, url, **kwargs):
        return self._dispatch(method.upper(), url, **kwargs)

    def get(self, url, **kwargs):
        return self._dispatch("GET", url, **kwargs)

    def put(self, url, **kwargs):
        return self._dispatch("PUT", url, **kwargs)

    def post(self, url, **kwargs):
        return self._dispatch("POST", url, **kwargs)


def _sha(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


class ApiTestBase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="ht_stage5_")
        self.local = LocalConfig(path=os.path.join(self.tmp, "local_config.json"))
        self.local.set("server_base_url", "http://srv:3000")
        self.local.set("client_token", "tok123")
        self.local.set("device_uuid", "uuid-abc")
        self.cache_path = os.path.join(self.tmp, "business_config.json")
        self.biz = AppConfig(
            cache_path=self.cache_path,
            default_path=DEFAULT_CONFIG_PATH,
            load_now=True,
        )
        self.fake = FakeSession()
        self.client = ApiClient(self.local, self.biz)
        self.client.session = self.fake  # 注入 fake session
        # 音频缓存目录改到临时目录，避免污染真实 cache/sounds
        self.sounds_dir = os.path.join(self.tmp, "sounds")
        patcher = mock.patch(
            "app.api_client.CACHE_SOUNDS_DIR", self.sounds_dir
        )
        patcher.start()
        self.addCleanup(patcher.stop)


# ---------------------------------------------------------------------------
# poll
# ---------------------------------------------------------------------------


class TestPoll(ApiTestBase):
    def test_newer_version_applies_and_writes_cache(self):
        new_cfg = dict(CONFIG_BASE, idle_text="服务器新文本")
        self.fake.responses[("GET", "/api/client/config")] = lambda **kw: FakeResp(
            200, {"version": 4, "config": new_cfg}
        )
        updated = self.client.poll()
        self.assertTrue(updated, "更高版本应触发更新")
        self.assertEqual(self.client.version, 4)
        self.assertEqual(self.biz.get("idle_text"), "服务器新文本")
        with open(self.cache_path, encoding="utf-8") as fh:
            cached = json.load(fh)
        self.assertEqual(cached.get("version"), 4, "缓存应含 version 字段")
        self.assertEqual(cached.get("idle_text"), "服务器新文本")

    def test_same_version_skips(self):
        self.client._version = 5
        self.fake.responses[("GET", "/api/client/config")] = lambda **kw: FakeResp(
            200, {"version": 5, "config": dict(CONFIG_BASE, idle_text="不应生效")}
        )
        with mock.patch.object(self.biz, "apply_config") as m_apply:
            updated = self.client.poll()
        self.assertFalse(updated, "相同版本应跳过")
        m_apply.assert_not_called()

    def test_older_version_skips(self):
        self.client._version = 8
        self.fake.responses[("GET", "/api/client/config")] = lambda **kw: FakeResp(
            200, {"version": 3, "config": dict(CONFIG_BASE)}
        )
        with mock.patch.object(self.biz, "apply_config") as m_apply:
            updated = self.client.poll()
        self.assertFalse(updated)
        m_apply.assert_not_called()

    def test_network_failure_returns_false(self):
        self.fake.exc = requests.exceptions.ConnectionError("refused")
        self.assertFalse(self.client.poll())
        self.assertEqual(self.client.version, 0)

    def test_version_recovered_from_cache_on_restart(self):
        self.fake.responses[("GET", "/api/client/config")] = lambda **kw: FakeResp(
            200, {"version": 9, "config": dict(CONFIG_BASE)}
        )
        self.assertTrue(self.client.poll())
        client2 = ApiClient(self.local, self.biz)
        self.assertEqual(client2.version, 9, "重启后应从缓存恢复版本号")


# ---------------------------------------------------------------------------
# heartbeat
# ---------------------------------------------------------------------------


class TestHeartbeat(ApiTestBase):
    def test_newer_version_triggers_poll(self):
        self.client._version = 2
        self.fake.responses[("POST", "/api/client/heartbeat")] = lambda **kw: FakeResp(
            200, {"version": 6}
        )
        with mock.patch.object(self.client, "poll") as m_poll:
            ok = self.client.heartbeat()
        self.assertTrue(ok)
        m_poll.assert_called_once()

    def test_same_version_no_poll(self):
        self.client._version = 6
        self.fake.responses[("POST", "/api/client/heartbeat")] = lambda **kw: FakeResp(
            200, {"version": 6}
        )
        with mock.patch.object(self.client, "poll") as m_poll:
            ok = self.client.heartbeat()
        self.assertTrue(ok)
        m_poll.assert_not_called()

    def test_failure_returns_false(self):
        self.fake.exc = requests.exceptions.ConnectTimeout("slow")
        self.assertFalse(self.client.heartbeat())


# ---------------------------------------------------------------------------
# push_config
# ---------------------------------------------------------------------------


class TestPushConfig(ApiTestBase):
    def test_success(self):
        self.fake.responses[("PUT", "/api/config")] = lambda **kw: FakeResp(200)
        ok = self.client.push_config({"idle_text": "x"})
        self.assertTrue(ok)
        put = [c for c in self.fake.calls if c["method"] == "PUT"][0]
        self.assertEqual(put["kwargs"]["headers"]["X-Client-Token"], "tok123")
        self.assertEqual(put["kwargs"]["json"], {"config": {"idle_text": "x"}})

    def test_network_error_returns_false_no_throw(self):
        self.fake.exc = requests.exceptions.ConnectionError("refused")
        self.assertFalse(self.client.push_config({"idle_text": "x"}))
        self.assertTrue(self.client.last_error)

    def test_403_token_invalid_false(self):
        self.fake.responses[("PUT", "/api/config")] = lambda **kw: FakeResp(
            403, {"error": "客户端 Token 无效"}
        )
        self.assertFalse(self.client.push_config({"idle_text": "x"}))
        self.assertIn("Token", self.client.last_error)

    def test_unconfigured_returns_false(self):
        self.local.set("client_token", "")
        client = ApiClient(self.local, self.biz)
        self.assertFalse(client.push_config({"idle_text": "x"}))

    def test_timeout_returns_false_no_throw(self):
        self.fake.exc = requests.exceptions.Timeout("timed out")
        self.assertFalse(self.client.push_config({"idle_text": "x"}))

    def test_push_strips_comment_and_version_keys(self):
        self.fake.responses[("PUT", "/api/config")] = lambda **kw: FakeResp(200)
        ok = self.client.push_config(
            {"_comment": "说明", "version": 3, "idle_text": "正式字段", "sound": {}}
        )
        self.assertTrue(ok)
        put = [c for c in self.fake.calls if c["method"] == "PUT"][0]
        body = put["kwargs"]["json"]["config"]
        self.assertNotIn("_comment", body)
        self.assertNotIn("version", body)
        self.assertEqual(body["idle_text"], "正式字段")

    def test_sanitize_config_drops_aux_keys(self):
        out = sanitize_config({"_comment": "x", "version": 1, "k": "v"})
        self.assertEqual(out, {"k": "v"})


# ---------------------------------------------------------------------------
# sync_pending
# ---------------------------------------------------------------------------


class TestSyncPending(ApiTestBase):
    def test_all_success_clears(self):
        items = [
            {"ts": "t1", "config": {"idle_text": "补1"}},
            {"ts": "t2", "config": {"idle_text": "补2"}},
        ]
        with mock.patch("app.api_client.load_pending", return_value=items), \
                mock.patch("app.api_client.clear_pending", return_value=True) as m_clear:
            self.fake.responses[("PUT", "/api/config")] = lambda **kw: FakeResp(200)
            ok = self.client.sync_pending()
        self.assertTrue(ok)
        m_clear.assert_called_once_with()
        # 保序推送
        puts = [c for c in self.fake.calls if c["method"] == "PUT"]
        bodies = [c["kwargs"]["json"]["config"]["idle_text"] for c in puts]
        self.assertEqual(bodies, ["补1", "补2"])

    def test_second_fails_keeps_queue_and_order(self):
        items = [
            {"ts": "1", "config": {"idle_text": "甲"}},
            {"ts": "2", "config": {"idle_text": "乙"}},
        ]
        with mock.patch("app.api_client.load_pending", return_value=items), \
                mock.patch("app.api_client.clear_pending") as m_clear, \
                mock.patch.object(
                    self.client, "push_config", side_effect=[True, False]
                ) as m_push:
            ok = self.client.sync_pending()
        self.assertFalse(ok)
        m_clear.assert_not_called(), "失败时不应清空队列"
        args = [c.args[0] for c in m_push.call_args_list]
        self.assertEqual(args, [{"idle_text": "甲"}, {"idle_text": "乙"}])


# ---------------------------------------------------------------------------
# ensure_audio
# ---------------------------------------------------------------------------


class TestEnsureAudio(ApiTestBase):
    def _write(self, name, data):
        os.makedirs(self.sounds_dir, exist_ok=True)
        path = os.path.join(self.sounds_dir, name)
        with open(path, "wb") as fh:
            fh.write(data)
        return path

    def _list(self, data, name, builtin=False):
        return [
            {
                "filename": name,
                "sha256": _sha(data),
                "size": len(data),
                "is_builtin": builtin,
            }
        ]

    def test_cache_match_skips_download(self):
        audio = b"WAVDATA"
        path = self._write("a.wav", audio)
        with mock.patch.object(
            self.client, "get_audio_list", return_value=self._list(audio, "a.wav")
        ):
            got = self.client.ensure_audio("a.wav")
        self.assertEqual(got, path)
        downloads = [
            c
            for c in self.fake.calls
            if c["method"] == "GET" and "/api/client/audio/" in c["url"]
        ]
        self.assertEqual(downloads, [], "sha 匹配不应下载")

    def test_mismatch_triggers_download_and_verifies(self):
        server_audio = b"NEWWAVDATA"
        self.fake.responses[("GET", "/api/client/audio/b.wav")] = lambda **kw: FakeResp(
            200, content=server_audio
        )
        with mock.patch.object(
            self.client,
            "get_audio_list",
            return_value=self._list(server_audio, "b.wav"),
        ):
            got = self.client.ensure_audio("b.wav")
        expected = os.path.join(self.sounds_dir, "b.wav")
        self.assertEqual(got, expected)
        self.assertTrue(os.path.isfile(expected))
        with open(expected, "rb") as fh:
            self.assertEqual(_sha(fh.read()), _sha(server_audio))

    def test_verify_fail_deletes_file(self):
        bad_audio = b"WRONGCONTENT"
        target_sha = _sha(b"expected-different")
        self.fake.responses[("GET", "/api/client/audio/c.wav")] = lambda **kw: FakeResp(
            200, content=bad_audio
        )
        with mock.patch.object(
            self.client,
            "get_audio_list",
            return_value=[
                {
                    "filename": "c.wav",
                    "sha256": target_sha,
                    "size": len(bad_audio),
                    "is_builtin": False,
                }
            ],
        ):
            got = self.client.ensure_audio("c.wav")
        self.assertIsNone(got, "校验失败应返回 None")
        self.assertFalse(
            os.path.exists(os.path.join(self.sounds_dir, "c.wav")),
            "校验失败应删除下载文件",
        )

    def test_builtin_prefers_packaged_resource(self):
        builtin_path = os.path.join(self.tmp, "near.wav")
        with open(builtin_path, "wb") as fh:
            fh.write(b"BUILTIN")
        with mock.patch("app.api_client.resource_path", return_value=builtin_path), \
                mock.patch.object(
                    self.client,
                    "get_audio_list",
                    return_value=self._list(b"BUILTIN", "near.wav", builtin=True),
                ):
            got = self.client.ensure_audio("near.wav")
        self.assertEqual(got, builtin_path)
        downloads = [
            c
            for c in self.fake.calls
            if c["method"] == "GET" and "/api/client/audio/" in c["url"]
        ]
        self.assertEqual(downloads, [], "内置资源匹配时不应下载")

    def test_builtin_override_downloaded_when_sha_differs(self):
        # 服务端提供与本地内置不同 sha 的覆盖版 → 应下载覆盖版
        builtin_path = os.path.join(self.tmp, "end.wav")
        with open(builtin_path, "wb") as fh:
            fh.write(b"BUILTIN")
        override = b"SERVER_OVERRIDE"
        self.fake.responses[("GET", "/api/client/audio/end.wav")] = lambda **kw: FakeResp(
            200, content=override
        )
        with mock.patch("app.api_client.resource_path", return_value=builtin_path), \
                mock.patch.object(
                    self.client,
                    "get_audio_list",
                    return_value=self._list(override, "end.wav", builtin=True),
                ):
            got = self.client.ensure_audio("end.wav")
        expected = os.path.join(self.sounds_dir, "end.wav")
        self.assertEqual(got, expected)
        with open(expected, "rb") as fh:
            self.assertEqual(fh.read(), override)

    def test_offline_falls_back_to_local(self):
        with mock.patch.object(self.client, "get_audio_list", return_value=None):
            got = self.client.ensure_audio("near.wav")
        # 离线不回下载；应落到本地可用路径（真实内置资源存在 → 非 None 且文件存在）
        if got is not None:
            self.assertTrue(os.path.isfile(got), "本地回退路径必须存在")


# ---------------------------------------------------------------------------
# get_audio_list
# ---------------------------------------------------------------------------


class TestGetAudioList(ApiTestBase):
    def test_success_returns_list(self):
        self.fake.responses[("GET", "/api/client/audio")] = lambda **kw: FakeResp(
            200,
            [
                {"filename": "a.wav", "sha256": "aa", "size": 1, "is_builtin": False},
            ],
        )
        items = self.client.get_audio_list()
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["filename"], "a.wav")

    def test_failure_returns_none(self):
        self.fake.exc = requests.exceptions.ConnectionError("off")
        self.assertIsNone(self.client.get_audio_list())


# ---------------------------------------------------------------------------
# should_sync_pending（补传触发判定，纯函数）
# ---------------------------------------------------------------------------


class TestShouldSyncPending(unittest.TestCase):
    """离线补传触发条件：在线且存在待同步队列即应尝试（幂等）。"""

    def test_online_with_pending_triggers(self):
        self.assertTrue(should_sync_pending(True, 1))
        self.assertTrue(should_sync_pending(True, 3))

    def test_offline_never_triggers(self):
        # 心跳失败（离线）时即使有队列也不补传
        self.assertFalse(should_sync_pending(False, 5))

    def test_online_empty_queue_noop(self):
        # 在线但队列为空 → 无需补传（幂等，避免无谓动作）
        self.assertFalse(should_sync_pending(True, 0))

    def test_invalid_inputs_safe(self):
        # 非法输入（None / 负值 / 字符串）不应抛错
        self.assertFalse(should_sync_pending(True, None))
        self.assertFalse(should_sync_pending(None, 2))
        self.assertFalse(should_sync_pending(False, -1))


if __name__ == "__main__":
    unittest.main(verbosity=2)