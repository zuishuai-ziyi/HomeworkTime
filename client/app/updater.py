# -*- coding: utf-8 -*-
"""客户端自更新模块（全量包替换式更新）。

整体流程（与管理端「更新管理」页、服务端 /api/client/update/* 配合）：

1. 心跳响应携带服务端已发布的更新信息
   ``{version, size, sha256, effective_time}``（延迟更新：客户端离线期间
   管理端发布的包，客户端上线后首次心跳即可发现）；
2. ``Updater.evaluate()`` 比对：本地版本 != 服务端版本且该包 sha 尚未安装
   过 → 后台线程流式下载 zip 到 ``cache/update/package.zip`` → sha256 校验
   → 解压到 ``cache/update/staging/``（zip 根级必须含 HomeworkTime.exe）；
3. 应用时机（AppController 每秒 tick 调用 ``maybe_apply``）：
   - staging 就绪（status == ready）；
   - 且当前时间 >= effective_time（管理端指定的生效时间）；
   - 且当前不在晚自习时段（到点时若正处晚自习，顺延至晚自习结束后）；
   - 且同一目标版本连续应用失败次数 < 3（防无限重启循环）；
4. 应用（``apply_now``）：运行时生成 ``cache/update/update.bat``（等待旧
   进程退出 → 旧文件移入 backup → staging 移入程序目录 → 校验失败自动
   回滚 → 重启 exe），写 ``applied.json`` 标记，隐藏拉起 bat，宿主进程随后
   自行退出；
5. 新版本启动时 ``startup_check()``：运行版本 == 目标版本（或 == 包内
   manifest 版本）→ 清理暂存并记录 last_applied_sha；否则视为应用失败，
   fail_count + 1，第 3 次失败后暂停该包的自动应用，直到服务端发布新包。

关键不变量：
- 运行中的 exe 无法覆盖自身，替换动作全部由外部 update.bat 在进程退出后
  完成，bat 由客户端运行时生成（而非打包固定），升级逻辑可随版本演进；
- 本地运行数据（local_config.json / cache / logs）不在更新包内，替换只针对
  更新包中存在的顶层条目，用户数据天然保留；
- 仅在 Windows（os.name == "nt"）执行应用动作，开发机/CI 上安全跳过；
- 更新状态持久化于 ``cache/update/update_state.json``，进程重启后可恢复。
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
import threading
import time
import zipfile
from datetime import datetime
from typing import Any, Dict, Optional, Tuple

from .config import RUNTIME_DIR
from .version import APP_VERSION

logger = logging.getLogger(__name__)

#: 更新包下载接口路径（X-Client-Token 鉴权）
UPDATE_DOWNLOAD_PATH = "/api/client/update/download"
#: 包内 manifest 文件名（build.py 打包时写入 zip 根级）
MANIFEST_NAME = "update_manifest.json"
#: 程序主入口名（zip 根级必须包含）
EXE_NAME = "HomeworkTime.exe"
#: 更新根目录（打包后位于 exe 同级的 cache/update/）
UPDATE_DIR = os.path.join(RUNTIME_DIR, "cache", "update")
#: 下载/解压失败后的重试间隔（秒）
RETRY_INTERVAL_SEC = 60
#: 同一目标版本连续应用失败上限（超过后停止自动应用，防重启循环）
MAX_FAIL_COUNT = 3


def _sha256_file(path: str) -> str:
    """计算文件 sha256（十六进制小写）；读取失败返回空串。"""
    import hashlib

    h = hashlib.sha256()
    try:
        with open(path, "rb") as fh:
            for chunk in iter(lambda: fh.read(1 << 16), b""):
                h.update(chunk)
    except OSError:
        return ""
    return h.hexdigest()


def _read_json(path: str) -> Optional[Any]:
    """读取 JSON 文件；缺失/损坏返回 None（不抛出）。"""
    try:
        with open(path, "r", encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return None


def _write_json_atomic(path: str, data: Dict[str, Any]) -> None:
    """原子写 JSON（临时文件 + os.replace）。"""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = "{}.tmp".format(path)
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


def parse_effective_time(text: Any) -> Optional[datetime]:
    """解析服务端下发的生效时间字符串（纯函数，便于单测）。

    接受 ``YYYY-MM-DD HH:MM:SS`` / ``YYYY-MM-DD HH:MM`` / ISO ``T`` 分隔；
    非法输入返回 None。按本机时区解析（校园与服务端默认同时区）。
    """
    if not isinstance(text, str) or not text.strip():
        return None
    s = text.strip().replace("T", " ")
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M"):
        try:
            return datetime.strptime(s, fmt)
        except ValueError:
            continue
    return None


def should_apply(
    status: Any,
    fail_count: Any,
    effective_time: Any,
    now: datetime,
    in_evening: bool,
    max_fail: int = MAX_FAIL_COUNT,
) -> Tuple[bool, str]:
    """判定当前 tick 是否应执行更新替换（纯函数，便于单测）。

    依次检查：就绪状态 → 失败保护 → 生效时间 → 晚自习保护。
    返回 ``(是否应用, 未应用原因)``。
    """
    if status != "ready":
        return False, "更新包未就绪"
    try:
        fails = int(fail_count or 0)
    except (TypeError, ValueError):
        fails = 0
    if fails >= max_fail:
        return False, "连续应用失败超过 {} 次，已暂停".format(max_fail)
    eff = parse_effective_time(effective_time)
    if eff is None:
        return False, "生效时间缺失或非法"
    if now < eff:
        return False, "未到生效时间"
    if in_evening:
        return False, "晚自习时段保护，顺延至晚自习结束"
    return True, ""


def zip_member_is_unsafe(name: str) -> bool:
    """判断 zip 成员名是否不安全（绝对路径 / 盘符 / 上跳 ..，纯函数）。"""
    n = name.replace("\\", "/")
    if n.startswith("/"):
        return True
    if len(n) > 1 and n[1] == ":":
        return True
    return any(part == ".." for part in n.split("/"))


def build_batch_script(
    root: str,
    staging: str,
    backup: str,
    pid: int,
    exe_name: str = EXE_NAME,
) -> str:
    """生成 update.bat 内容（纯函数，便于单测）。

    逻辑：等待 PID 退出（最多约 30 秒，超时强杀）→ 清空并重建 backup →
    逐个把 staging 顶层条目与 root 下同名旧条目对调（旧→backup、新→root）
    → 校验新 exe 存在，缺失则把 backup 移回 root 回滚 → 启动 exe。

    注意：内容保持纯 ASCII（注释亦然），配合 mbcs 编码写入，
    避免中文路径/编码问题；路径由调用方尽量转为 8.3 短路径。
    """
    return "\n".join([
        "@echo off",
        "rem HomeworkTime auto-update script (generated at runtime, do not edit)",
        "setlocal EnableExtensions",
        "",
        'set "ROOT={}"'.format(root),
        'set "STAGE={}"'.format(staging),
        'set "BACKUP={}"'.format(backup),
        "set PID={}".format(pid),
        "set EXE={}".format(exe_name),
        "",
        "rem ---- 1) wait for app exit (max ~30s, force kill on timeout) ----",
        "set /a WAITED=0",
        ":wait_loop",
        'tasklist /fi "PID eq %PID%" 2>nul | find "%PID%" >nul',
        "if errorlevel 1 goto do_update",
        "if %WAITED% GEQ 30 goto kill_it",
        "ping -n 2 127.0.0.1 >nul 2>&1",
        "set /a WAITED+=1",
        "goto wait_loop",
        ":kill_it",
        "taskkill /f /pid %PID% >nul 2>&1",
        "ping -n 3 127.0.0.1 >nul 2>&1",
        "",
        ":do_update",
        "rem ---- 2) fresh backup dir ----",
        'if exist "%BACKUP%" rd /s /q "%BACKUP%"',
        'mkdir "%BACKUP%" 2>nul',
        "",
        "rem ---- 3) swap top-level entries: old -> backup, staged -> root ----",
        'for /d %%D in ("%STAGE%\\*") do (',
        '  if exist "%ROOT%\\%%~nxD" move /y "%ROOT%\\%%~nxD" "%BACKUP%\\%%~nxD" >nul 2>&1',
        '  move /y "%%D" "%ROOT%\\%%~nxD" >nul 2>&1',
        ")",
        'for %%F in ("%STAGE%\\*") do (',
        '  if exist "%ROOT%\\%%~nxF" move /y "%ROOT%\\%%~nxF" "%BACKUP%\\%%~nxF" >nul 2>&1',
        '  move /y "%%F" "%ROOT%\\%%~nxF" >nul 2>&1',
        ")",
        "",
        "rem ---- 4) verify new exe, rollback if missing ----",
        'if not exist "%ROOT%\\%EXE%" goto rollback',
        "",
        'start "" "%ROOT%\\%EXE%"',
        "endlocal",
        "exit /b 0",
        "",
        ":rollback",
        "rem ---- 5) restore backup entries ----",
        'for /d %%D in ("%BACKUP%\\*") do (',
        '  if exist "%ROOT%\\%%~nxD" rd /s /q "%ROOT%\\%%~nxD" >nul 2>&1',
        '  move /y "%%D" "%ROOT%\\%%~nxD" >nul 2>&1',
        ")",
        'for %%F in ("%BACKUP%\\*") do (',
        '  if exist "%ROOT%\\%%~nxF" del /f /q "%ROOT%\\%%~nxF" >nul 2>&1',
        '  move /y "%%F" "%ROOT%\\%%~nxF" >nul 2>&1',
        ")",
        'if exist "%ROOT%\\%EXE%" start "" "%ROOT%\\%EXE%"',
        "endlocal",
        "exit /b 1",
        "",
    ])


def _short_path(path: str) -> str:
    """尽量转换为 Windows 8.3 短路径（纯 ASCII），失败原样返回。"""
    if os.name != "nt":
        return path
    try:
        import ctypes

        buf = ctypes.create_unicode_buffer(1024)
        n = ctypes.windll.kernel32.GetShortPathNameW(
            os.path.abspath(path), buf, 1024
        )
        if n and n < 1024:
            return buf.value
    except Exception:
        pass
    return path


#: 状态文件默认字段（update_state.json）
DEFAULT_STATE: Dict[str, Any] = {
    "target_version": "",
    "target_sha256": "",
    "target_size": 0,
    "effective_time": "",
    # idle: 无任务；pending: 待下载/解压；downloading: 下载中；
    # ready: 就绪待生效时间；failed: 下载/解压失败（节流重试）
    "status": "idle",
    "fail_count": 0,
    "manifest_version": "",
    "last_applied_sha": "",
    "last_error": "",
    "last_attempt_ts": 0.0,
}


class Updater:
    """客户端自更新控制器（状态持久化 + 后台准备线程 + 时机判定）。"""

    def __init__(
        self,
        base_dir: Optional[str] = None,
        app_root: Optional[str] = None,
    ) -> None:
        base = base_dir or UPDATE_DIR
        self.dir = base
        self.app_root = app_root or RUNTIME_DIR
        self.package_path = os.path.join(base, "package.zip")
        self.staging_dir = os.path.join(base, "staging")
        self.backup_dir = os.path.join(base, "backup")
        self.state_path = os.path.join(base, "update_state.json")
        self.applied_path = os.path.join(base, "applied.json")
        self.bat_path = os.path.join(base, "update.bat")

        self._lock = threading.RLock()
        self._worker_running = False
        self._applying = False
        self.state: Dict[str, Any] = dict(DEFAULT_STATE)
        self._load_state()

    # ------------------------------------------------------------------
    # 状态持久化
    # ------------------------------------------------------------------
    def _load_state(self) -> None:
        data = _read_json(self.state_path)
        if isinstance(data, dict):
            merged = dict(DEFAULT_STATE)
            merged.update({k: v for k, v in data.items() if k in DEFAULT_STATE})
            self.state = merged

    def _save(self) -> None:
        """写回状态文件（调用方需已持锁）。"""
        try:
            _write_json_atomic(self.state_path, self.state)
        except OSError as exc:
            logger.warning("更新状态写入失败: %s", exc)

    # ------------------------------------------------------------------
    # 心跳评估（主线程网络 tick 调用）
    # ------------------------------------------------------------------
    def evaluate(self, update_info: Any, api_client: Any) -> None:
        """根据心跳返回的更新信息推进更新流程。

        - 信息缺失 / 已安装过该 sha → 无操作；
        - 目标未变 → 同步生效时间变化（管理端可发布后修改）；
        - 新目标 → 重置状态（fail_count 归零）并准备下载；
        - pending / failed 且距上次尝试超过节流间隔 → 启动后台准备线程。
        """
        if not isinstance(update_info, dict):
            return
        version = str(update_info.get("version") or "").strip()
        sha = str(update_info.get("sha256") or "").strip().lower()
        if not version or not sha:
            return
        try:
            size = int(update_info.get("size") or 0)
        except (TypeError, ValueError):
            size = 0
        eff = str(update_info.get("effective_time") or "")

        with self._lock:
            if sha == str(self.state.get("last_applied_sha") or ""):
                # 该包已成功安装：服务器 version 标签与包不一致时的
                # 防循环短路（例如管理员手滑把 1.1.0 的包标成 1.0.5）
                return
            if (
                sha == self.state.get("target_sha256")
                and version == self.state.get("target_version")
            ):
                if eff and eff != self.state.get("effective_time"):
                    self.state["effective_time"] = eff
                    self._save()
                    logger.info("服务器调整更新生效时间为: %s", eff)
            else:
                self.state.update({
                    "target_version": version,
                    "target_sha256": sha,
                    "target_size": size,
                    "effective_time": eff,
                    "status": "pending",
                    "fail_count": 0,
                    "manifest_version": "",
                    "last_error": "",
                    "last_attempt_ts": 0.0,
                })
                self._save()
                logger.info(
                    "发现服务端新版本 v%s（%d 字节，生效时间 %s），开始准备更新",
                    version, size, eff or "(未知)",
                )
            status = str(self.state.get("status") or "")
            try:
                last_ts = float(self.state.get("last_attempt_ts") or 0.0)
            except (TypeError, ValueError):
                last_ts = 0.0

        if status in ("pending", "failed") and not self._worker_running:
            if time.time() - last_ts >= RETRY_INTERVAL_SEC:
                self._start_worker(api_client)

    def _start_worker(self, api_client: Any) -> None:
        threading.Thread(
            target=self._worker, args=(api_client,), daemon=True
        ).start()

    def _worker(self, api_client: Any) -> None:
        """后台线程：确保包下载完成并解压到 staging（幂等，可重入）。"""
        self._worker_running = True
        try:
            with self._lock:
                self.state["last_attempt_ts"] = time.time()
                self._save()
            ok, reason = self._ensure_package(api_client)
            if ok:
                ok, reason = self._ensure_staging()
            with self._lock:
                if ok:
                    manifest = _read_json(
                        os.path.join(self.staging_dir, MANIFEST_NAME)
                    )
                    mv = (
                        str(manifest.get("version") or "")
                        if isinstance(manifest, dict)
                        else ""
                    )
                    self.state.update({
                        "status": "ready",
                        "last_error": "",
                        "manifest_version": mv,
                    })
                    logger.info(
                        "更新包就绪：目标 v%s（包内版本 %s），等待生效时间 %s",
                        self.state.get("target_version"),
                        mv or "(未知)",
                        self.state.get("effective_time") or "(未知)",
                    )
                else:
                    self.state.update({
                        "status": "failed",
                        "last_error": reason,
                    })
                    logger.warning("更新包准备失败（将重试）: %s", reason)
                self._save()
        except Exception as exc:
            logger.exception("更新准备线程异常: %s", exc)
            with self._lock:
                self.state.update({
                    "status": "failed",
                    "last_error": str(exc),
                })
                self._save()
        finally:
            self._worker_running = False

    # ------------------------------------------------------------------
    # 准备流水线（下载 + 校验 + 解压，全部幂等）
    # ------------------------------------------------------------------
    def _ensure_package(self, api_client: Any) -> Tuple[bool, str]:
        """确保 package.zip 存在且 sha256 匹配目标；缺失则流式下载。"""
        expected = str(self.state.get("target_sha256") or "")
        if os.path.isfile(self.package_path):
            if _sha256_file(self.package_path) == expected:
                return True, ""
            try:
                os.remove(self.package_path)  # 残留坏包 → 删除重下
            except OSError:
                pass

        with self._lock:
            self.state["status"] = "downloading"
            self._save()

        part = self.package_path + ".part"
        try:
            if os.path.exists(part):
                os.remove(part)  # 丢弃上次下载残留
        except OSError:
            pass
        ok = api_client.download_update(UPDATE_DOWNLOAD_PATH, part)
        if not ok:
            return False, "更新包下载失败（网络异常或鉴权失败）"
        actual = _sha256_file(part)
        if expected and actual != expected:
            try:
                os.remove(part)
            except OSError:
                pass
            return False, "更新包 sha256 校验失败"
        try:
            expected_size = int(self.state.get("target_size") or 0)
        except (TypeError, ValueError):
            expected_size = 0
        if expected_size and os.path.getsize(part) != expected_size:
            try:
                os.remove(part)
            except OSError:
                pass
            return False, "更新包大小不符"
        try:
            os.replace(part, self.package_path)
        except OSError as exc:
            return False, "更新包落盘失败: {}".format(exc)
        return True, ""

    def _ensure_staging(self) -> Tuple[bool, str]:
        """确保 staging 目录有效（根级含 exe）；无效则从 zip 重新解压。"""
        if os.path.isfile(os.path.join(self.staging_dir, EXE_NAME)):
            return True, ""
        tmp = self.staging_dir + ".tmp"
        shutil.rmtree(tmp, ignore_errors=True)
        shutil.rmtree(self.staging_dir, ignore_errors=True)
        os.makedirs(tmp, exist_ok=True)
        try:
            with zipfile.ZipFile(self.package_path) as zf:
                names = zf.namelist()
                bad = next(
                    (n for n in names if zip_member_is_unsafe(n)), None
                )
                if bad is not None:
                    return False, "更新包含不安全路径: {!r}".format(bad)
                if EXE_NAME not in names:
                    return False, "更新包根目录缺少 {}".format(EXE_NAME)
                zf.extractall(tmp)
        except (zipfile.BadZipFile, OSError) as exc:
            return False, "更新包解压失败: {}".format(exc)
        os.replace(tmp, self.staging_dir)
        return True, ""

    # ------------------------------------------------------------------
    # 应用时机与执行（主线程 tick 调用）
    # ------------------------------------------------------------------
    def maybe_apply(self, now: datetime, in_evening: bool) -> bool:
        """判定并执行更新替换；返回 True 表示宿主进程应立即退出。"""
        with self._lock:
            ok, _reason = should_apply(
                self.state.get("status"),
                self.state.get("fail_count"),
                self.state.get("effective_time"),
                now,
                in_evening,
            )
        if not ok or self._applying:
            return False
        # 二次确认 staging 有效（防止状态与磁盘不一致）
        if not os.path.isfile(os.path.join(self.staging_dir, EXE_NAME)):
            with self._lock:
                self.state["status"] = "pending"
                self._save()
            return False
        self._applying = True
        if self.apply_now():
            return True
        self._applying = False
        return False

    def apply_now(self) -> bool:
        """写更新脚本与标记并拉起 bat；成功返回 True（进程随后应退出）。"""
        if os.name != "nt":
            logger.warning("非 Windows 平台，跳过更新应用（开发环境保护）")
            return False
        pid = os.getpid()
        bat_content = build_batch_script(
            _short_path(self.app_root),
            _short_path(self.staging_dir),
            _short_path(self.backup_dir),
            pid,
            EXE_NAME,
        )
        try:
            # mbcs（ANSI）编码 + 默认换行转换（CRLF），cmd 批处理最稳
            with open(self.bat_path, "w", encoding="mbcs") as fh:
                fh.write(bat_content)
        except (LookupError, UnicodeEncodeError, OSError) as exc:
            logger.error("更新脚本写入失败: %s", exc)
            return False

        snapshot = {
            "target_version": self.state.get("target_version"),
            "sha256": self.state.get("target_sha256"),
            "fail_count": self.state.get("fail_count"),
            "ts": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        }
        try:
            _write_json_atomic(self.applied_path, snapshot)
        except OSError as exc:
            logger.error("更新标记写入失败: %s", exc)
            return False

        try:
            # DETACHED_PROCESS | CREATE_NO_WINDOW：脱离宿主独立运行且无黑窗
            flags = 0x00000008 | 0x08000000
            subprocess.Popen(
                ["cmd", "/c", self.bat_path],
                cwd=self.app_root,
                creationflags=flags,
                close_fds=True,
            )
        except OSError as exc:
            logger.error("更新脚本拉起失败: %s", exc)
            try:
                os.remove(self.applied_path)
            except OSError:
                pass
            return False
        logger.info(
            "更新脚本已拉起（目标 v%s），本进程即将退出由脚本完成替换与重启",
            self.state.get("target_version"),
        )
        return True

    # ------------------------------------------------------------------
    # 启动检查（新进程启动时调用一次）
    # ------------------------------------------------------------------
    def startup_check(self) -> None:
        """检查上次更新应用结果：成功则清理并记录；失败则计数保护。"""
        applied = _read_json(self.applied_path)
        if isinstance(applied, dict) and applied.get("target_version"):
            target = str(applied.get("target_version"))
            root_manifest = _read_json(
                os.path.join(self.app_root, MANIFEST_NAME)
            )
            manifest_version = (
                str(root_manifest.get("version") or "")
                if isinstance(root_manifest, dict)
                else ""
            )
            if APP_VERSION == target or APP_VERSION == manifest_version:
                # 应用成功：记录 sha（防重复安装同包），清理全部暂存
                with self._lock:
                    self.state.update({
                        "target_version": "",
                        "target_sha256": "",
                        "target_size": 0,
                        "effective_time": "",
                        "status": "idle",
                        "fail_count": 0,
                        "manifest_version": manifest_version,
                        "last_error": "",
                        "last_applied_sha": str(applied.get("sha256") or ""),
                    })
                    self._save()
                self._cleanup_files()
                logger.info(
                    "远程更新完成，当前运行版本 v%s（目标 v%s）",
                    APP_VERSION, target,
                )
            else:
                # 应用失败（脚本回滚或替换未生效）：计数并允许重新准备
                with self._lock:
                    try:
                        fails = int(applied.get("fail_count") or 0) + 1
                    except (TypeError, ValueError):
                        fails = 1
                    self.state["fail_count"] = fails
                    self.state["status"] = "pending"
                    self.state["last_error"] = (
                        "更新应用失败（重启后仍为 v{}，目标 v{}）".format(
                            APP_VERSION, target
                        )
                    )
                    self._save()
                try:
                    os.remove(self.applied_path)
                except OSError:
                    pass
                shutil.rmtree(self.staging_dir, ignore_errors=True)
                logger.warning(
                    "更新应用失败（目标 v%s，当前仍为 v%s），累计失败 %d 次%s",
                    target,
                    APP_VERSION,
                    self.state.get("fail_count"),
                    "，已达到上限、暂停自动应用"
                    if int(self.state.get("fail_count") or 0) >= MAX_FAIL_COUNT
                    else "",
                )
            return

        # 异常残留：状态 ready 但 staging 缺失（如被手工清理）→ 重新准备
        if str(self.state.get("status")) == "ready" and not os.path.isfile(
            os.path.join(self.staging_dir, EXE_NAME)
        ):
            with self._lock:
                self.state["status"] = "pending"
                self._save()

    def _cleanup_files(self) -> None:
        """更新成功后清理暂存产物（保留 state 文件中的 last_applied_sha）。"""
        shutil.rmtree(self.staging_dir, ignore_errors=True)
        shutil.rmtree(self.backup_dir, ignore_errors=True)
        for path in (self.package_path, self.bat_path, self.applied_path):
            try:
                if os.path.exists(path):
                    os.remove(path)
            except OSError:
                pass

    # ------------------------------------------------------------------
    # 对外查询
    # ------------------------------------------------------------------
    def pending_version(self) -> Optional[str]:
        """当前待生效的目标版本（心跳上报用）；无任务返回 None。"""
        with self._lock:
            if self.state.get("target_version") and str(
                self.state.get("status")
            ) in ("pending", "downloading", "ready", "failed"):
                return str(self.state["target_version"])
        return None
