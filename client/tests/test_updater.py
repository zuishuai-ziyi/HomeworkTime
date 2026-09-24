# -*- coding: utf-8 -*-
"""Updater（客户端远程更新）单元测试（unittest，临时目录隔离）。

覆盖：
- parse_effective_time：合法格式解析 / 非法输入返回 None；
- should_apply：未就绪 / 失败上限 / 未到生效时间 / 晚自习保护 / 满足条件；
- zip_member_is_unsafe：绝对路径、盘符、上跳 .. 与安全路径；
- build_batch_script：路径与 PID 写入、含等待/替换/回滚段、纯 ASCII；
- Updater 端到端（fake api_client 提供真实 zip）：
  * evaluate 新目标 → 后台下载/校验/解压 → ready，manifest_version 读出；
  * 同目标重复 evaluate → 不重复下载；
  * last_applied_sha 短路（服务器标签错位防循环）；
  * 生效时间热更新；
  * maybe_apply 各时机分支（mock apply_now）；
  * startup_check 成功清理 / 失败计数；
  * _ensure_staging 对缺 exe 的 zip 报错。

运行方式（项目根目录）：
    python -m unittest client.tests.test_updater -v
"""

import hashlib
import json
import os
import shutil
import sys
import tempfile
import time
import unittest
import zipfile
from datetime import datetime
from unittest import mock

_TEST_DIR = os.path.dirname(os.path.abspath(__file__))
_CLIENT_DIR = os.path.dirname(_TEST_DIR)
if _CLIENT_DIR not in sys.path:
    sys.path.insert(0, _CLIENT_DIR)

from app.updater import (  # noqa: E402
    EXE_NAME,
    MANIFEST_NAME,
    Updater,
    build_batch_script,
    parse_effective_time,
    should_apply,
    zip_member_is_unsafe,
)
from app.version import APP_VERSION  # noqa: E402


def _sha256(path: str) -> str:
    """计算测试文件 sha256。"""
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _make_update_zip(path: str, version: str = "9.9.9") -> None:
    """构造合法更新包 zip（根级 exe + manifest + _internal/ 占位）。"""
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(EXE_NAME, "fake exe binary")
        zf.writestr(
            MANIFEST_NAME,
            json.dumps({"version": version, "created_at": "test"}),
        )
        zf.writestr("_internal/pylib.dll", "fake dll")


class FakeApiClient:
    """下载假实现：把预置 zip 拷贝到目标路径，统计调用次数。"""

    def __init__(self, zip_src: str, fail: bool = False) -> None:
        self.zip_src = zip_src
        self.fail = fail
        self.download_calls = 0

    def download_update(self, url_path: str, dest_path: str) -> bool:
        self.download_calls += 1
        if self.fail:
            return False
        shutil.copyfile(self.zip_src, dest_path)
        return True


def _wait_status(updater: Updater, status: str, timeout: float = 5.0) -> bool:
    """轮询等待 updater 状态到达 status（worker 为后台线程）。"""
    deadline = time.time() + timeout
    while time.time() < deadline:
        with updater._lock:
            if updater.state.get("status") == status:
                return True
        time.sleep(0.02)
    return False


class TestPureFunctions(unittest.TestCase):
    def test_parse_effective_time_valid(self):
        dt = parse_effective_time("2026-09-25 08:00:00")
        self.assertEqual((dt.year, dt.month, dt.day, dt.hour), (2026, 9, 25, 8))
        dt2 = parse_effective_time("2026-09-25T08:00")
        self.assertIsNotNone(dt2)
        self.assertEqual(dt2.minute, 0)

    def test_parse_effective_time_invalid(self):
        for bad in ("", None, "2026/09/25 08:00", "abc", "2026-13-01 00:00"):
            self.assertIsNone(parse_effective_time(bad))

    def test_should_apply_branches(self):
        now = datetime(2026, 9, 25, 10, 0, 0)
        eff = "2026-09-25 08:00:00"
        # 未就绪
        ok, why = should_apply("pending", 0, eff, now, False)
        self.assertFalse(ok)
        # 失败上限
        ok, why = should_apply("ready", 3, eff, now, False)
        self.assertFalse(ok)
        self.assertIn("失败", why)
        # 未到生效时间
        ok, why = should_apply("ready", 0, "2026-09-25 12:00:00", now, False)
        self.assertFalse(ok)
        # 晚自习保护（已到生效时间但晚自习内）
        ok, why = should_apply("ready", 0, eff, now, True)
        self.assertFalse(ok)
        self.assertIn("晚自习", why)
        # 全部满足
        ok, why = should_apply("ready", 0, eff, now, False)
        self.assertTrue(ok)
        self.assertEqual(why, "")

    def test_zip_member_is_unsafe(self):
        self.assertTrue(zip_member_is_unsafe("/etc/passwd"))
        self.assertTrue(zip_member_is_unsafe("C:\\Windows\\evil"))
        self.assertTrue(zip_member_is_unsafe("../outside.txt"))
        self.assertTrue(zip_member_is_unsafe("a/../../b"))
        self.assertFalse(zip_member_is_unsafe("HomeworkTime.exe"))
        self.assertFalse(zip_member_is_unsafe("_internal/pylib.dll"))

    def test_build_batch_script_content(self):
        bat = build_batch_script(
            r"C:\HW", r"C:\HW\cache\update\staging",
            r"C:\HW\cache\update\backup", 1234,
        )
        self.assertIn(r'set "ROOT=C:\HW"', bat)
        self.assertIn("set PID=1234", bat)
        for section in (":wait_loop", ":do_update", ":rollback", "taskkill"):
            self.assertIn(section, bat)
        # 纯 ASCII（cmd 批处理编码安全）
        bat.encode("ascii")


class TestUpdaterFlow(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="ht_update_test_")
        self.base = os.path.join(self.tmp, "update")
        self.app_root = os.path.join(self.tmp, "app")
        os.makedirs(self.base, exist_ok=True)
        os.makedirs(self.app_root, exist_ok=True)
        self.zip_src = os.path.join(self.tmp, "pkg.zip")
        _make_update_zip(self.zip_src, version="9.9.9")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _info(self, **kw):
        base = {
            "version": "9.9.9",
            "sha256": _sha256(self.zip_src),
            "size": os.path.getsize(self.zip_src),
            "effective_time": "2099-01-01 00:00:00",
        }
        base.update(kw)
        return base

    def test_evaluate_download_to_ready(self):
        up = Updater(base_dir=self.base, app_root=self.app_root)
        client = FakeApiClient(self.zip_src)
        up.evaluate(self._info(), client)
        self.assertTrue(_wait_status(up, "ready"))
        self.assertEqual(client.download_calls, 1)
        # staging 就绪 + manifest 版本读出
        self.assertTrue(
            os.path.isfile(os.path.join(up.staging_dir, EXE_NAME))
        )
        self.assertEqual(up.state.get("manifest_version"), "9.9.9")
        self.assertEqual(up.pending_version(), "9.9.9")
        # 包已校验落盘
        self.assertTrue(os.path.isfile(up.package_path))

    def test_evaluate_same_target_no_redownload(self):
        up = Updater(base_dir=self.base, app_root=self.app_root)
        client = FakeApiClient(self.zip_src)
        up.evaluate(self._info(), client)
        self.assertTrue(_wait_status(up, "ready"))
        # 再次 evaluate 同目标：不重复下载（worker 幂等短路）
        up.evaluate(self._info(), client)
        time.sleep(0.2)
        self.assertEqual(client.download_calls, 1)

    def test_evaluate_last_applied_sha_short_circuit(self):
        up = Updater(base_dir=self.base, app_root=self.app_root)
        client = FakeApiClient(self.zip_src)
        up.state["last_applied_sha"] = _sha256(self.zip_src)
        up.evaluate(self._info(), client)
        time.sleep(0.2)
        self.assertEqual(up.state.get("status"), "idle")
        self.assertEqual(client.download_calls, 0)

    def test_evaluate_updates_effective_time(self):
        up = Updater(base_dir=self.base, app_root=self.app_root)
        client = FakeApiClient(self.zip_src)
        up.evaluate(self._info(), client)
        self.assertTrue(_wait_status(up, "ready"))
        up.evaluate(self._info(effective_time="2026-12-31 23:00:00"), client)
        self.assertEqual(up.state.get("effective_time"), "2026-12-31 23:00:00")

    def test_download_failure_marks_failed(self):
        up = Updater(base_dir=self.base, app_root=self.app_root)
        client = FakeApiClient(self.zip_src, fail=True)
        up.evaluate(self._info(), client)
        self.assertTrue(_wait_status(up, "failed"))
        self.assertIn("下载", up.state.get("last_error"))

    def test_bad_zip_marks_failed(self):
        # zip 根级无 exe → 解压校验失败
        bad_zip = os.path.join(self.tmp, "bad.zip")
        with zipfile.ZipFile(bad_zip, "w") as zf:
            zf.writestr("readme.txt", "not an app")
        info = self._info(
            size=os.path.getsize(bad_zip), sha256="b" * 64
        )
        up = Updater(base_dir=self.base, app_root=self.app_root)
        # 绕过 sha 校验：直接写好 package 再走 _ensure_staging
        shutil.copyfile(bad_zip, up.package_path)
        up.state.update(info)
        ok, reason = up._ensure_staging()
        self.assertFalse(ok)
        self.assertIn(EXE_NAME, reason)

    def test_maybe_apply_timing(self):
        up = Updater(base_dir=self.base, app_root=self.app_root)
        # 未就绪
        self.assertFalse(
            up.maybe_apply(datetime(2026, 9, 25, 10), False)
        )
        # 就绪但未到生效时间
        up.state.update({
            "status": "ready",
            "fail_count": 0,
            "effective_time": "2026-09-25 12:00:00",
            "target_version": "9.9.9",
        })
        self.assertFalse(
            up.maybe_apply(datetime(2026, 9, 25, 10), False)
        )
        # 到时间但晚自习内 → 顺延
        self.assertFalse(
            up.maybe_apply(datetime(2026, 9, 25, 13), True)
        )
        # 失败上限
        up.state["fail_count"] = 3
        self.assertFalse(
            up.maybe_apply(datetime(2026, 9, 25, 13), False)
        )
        # 满足条件：staging 二次确认（造一个假 exe）+ mock apply_now
        up.state["fail_count"] = 0
        os.makedirs(up.staging_dir, exist_ok=True)
        with open(os.path.join(up.staging_dir, EXE_NAME), "wb") as fh:
            fh.write(b"x")
        with mock.patch.object(up, "apply_now", return_value=True) as m:
            self.assertTrue(
                up.maybe_apply(datetime(2026, 9, 25, 13), False)
            )
            m.assert_called_once_with()
        # staging 缺失（状态与磁盘不一致）→ 回 pending 不应用
        # （独立 base_dir，避免复用上面已造好的 staging 真实触发 apply）
        base2 = os.path.join(self.tmp, "update2")
        up2 = Updater(base_dir=base2, app_root=self.app_root)
        up2.state.update({
            "status": "ready",
            "effective_time": "2026-01-01 00:00:00",
        })
        self.assertFalse(
            up2.maybe_apply(datetime(2026, 9, 25, 13), False)
        )
        self.assertEqual(up2.state.get("status"), "pending")

    def test_startup_check_success(self):
        up = Updater(base_dir=self.base, app_root=self.app_root)
        # 构造「应用成功」现场：applied.json 目标 == 当前版本
        with open(up.applied_path, "w", encoding="utf-8") as fh:
            json.dump({
                "target_version": APP_VERSION,
                "sha256": "c" * 64,
                "fail_count": 0,
            }, fh)
        os.makedirs(up.staging_dir, exist_ok=True)
        open(os.path.join(up.staging_dir, EXE_NAME), "wb").close()
        up.startup_check()
        self.assertEqual(up.state.get("last_applied_sha"), "c" * 64)
        self.assertEqual(up.state.get("status"), "idle")
        self.assertFalse(os.path.exists(up.staging_dir))
        self.assertFalse(os.path.exists(up.applied_path))

    def test_startup_check_failure_counts(self):
        up = Updater(base_dir=self.base, app_root=self.app_root)
        up.state.update({"fail_count": 2})
        with open(up.applied_path, "w", encoding="utf-8") as fh:
            json.dump({
                "target_version": "8.8.8",
                "sha256": "d" * 64,
                "fail_count": 2,
            }, fh)
        os.makedirs(up.staging_dir, exist_ok=True)
        up.startup_check()
        self.assertEqual(up.state.get("fail_count"), 3)
        self.assertEqual(up.state.get("status"), "pending")
        self.assertFalse(os.path.exists(up.applied_path))
        # 达到上限后不再自动应用
        ok, _ = should_apply(
            "ready", up.state.get("fail_count"),
            "2020-01-01 00:00:00", datetime.now(), False,
        )
        self.assertFalse(ok)

    def test_state_persisted_across_instances(self):
        up = Updater(base_dir=self.base, app_root=self.app_root)
        client = FakeApiClient(self.zip_src)
        up.evaluate(self._info(), client)
        self.assertTrue(_wait_status(up, "ready"))
        up2 = Updater(base_dir=self.base, app_root=self.app_root)
        self.assertEqual(up2.state.get("status"), "ready")
        self.assertEqual(up2.state.get("target_version"), "9.9.9")


if __name__ == "__main__":
    unittest.main()
