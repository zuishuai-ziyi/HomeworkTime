# -*- coding: utf-8 -*-
"""阶段 5 ApiClient：轮询、心跳、配置推送、离线队列补传、音频按需下载。

设计要点：
- 单一 requests.Session，所有请求默认超时 5 秒；
- 「心跳与轮询同频」：一次网络 tick 先 heartbeat（内部按返回的 version
  判断是否需要 poll），再由调用方按需 poll；
- 所有网络异常统一捕获，返回哨兵值（None / False），绝不抛出，并写日志；
- 配置版本号持久化在业务配置缓存文件（``runtime_dir()/cache/business_config.json``）的
  version 字段；apply_config 后重新写回缓存，使「配置 + 版本」一致落盘，
  重启后可据此恢复版本号、避免重复 apply；
- 音频缓存目录沿用 config.CACHE_SOUNDS_DIR（``runtime_dir()/cache/sounds/``，
  打包后与 exe 同目录），保证下载后播放器能直接命中；下载后二次 sha256 校验。
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import platform
import threading
from typing import Any, Dict, List, Optional

import requests

from .config import (
    BUSINESS_CONFIG_CACHE,
    CACHE_SOUNDS_DIR,
    AppConfig,
    LocalConfig,
    clear_pending,
    load_pending,
    resource_path,
)
from .version import APP_VERSION

logger = logging.getLogger(__name__)

#: 客户端版本号（心跳上报；单一来源 app/version.py）
CLIENT_VERSION = APP_VERSION
#: 内置音频文件名（打包资源优先；仅当服务端 sha 与本地不一致时才下载覆盖版）
BUILTIN_AUDIO_NAMES = ("near.wav", "end.wav")

_AUTH_HEADER = "X-Client-Token"


def _sha256_file(path: str) -> str:
    """计算文件 sha256（十六进制小写）。"""
    h = hashlib.sha256()
    try:
        with open(path, "rb") as fh:
            for chunk in iter(lambda: fh.read(1 << 16), b""):
                h.update(chunk)
    except OSError:
        return ""
    return h.hexdigest()


def _write_json_atomic(path: str, data: Dict[str, Any]) -> None:
    """原子写 JSON（临时文件 + os.replace）。"""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = "{}.tmp".format(path)
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


def business_config_cache_path(app_config: Optional[AppConfig] = None) -> str:
    """返回业务配置缓存文件路径（优先取 AppConfig 实例自身路径）。"""
    if app_config is not None:
        path = getattr(app_config, "_cache_path", None)
        if path:
            return path
    return BUSINESS_CONFIG_CACHE


def sanitize_config(config: Dict[str, Any]) -> Dict[str, Any]:
    """剔除配置中不属于业务契约的辅助键后返回。

    内置 default_config.json 携带 _comment 说明占位键，AppConfig 深合并后
    会进入业务数据；服务端 validateAndMerge 对未知顶层字段报错。因此推送
    前剥离所有以 "_" 开头的键与 version 标记字段。
    """
    if not isinstance(config, dict):
        return config
    return {
        k: v for k, v in config.items()
        if not k.startswith("_") and k != "version"
    }


def should_sync_pending(server_online: bool, pending_count: int) -> bool:
    """判定本次网络 tick 是否需要尝试补传离线队列（纯函数，便于单测）。

    只要服务器可达且待同步队列非空即返回 True。sync_pending 本身幂等
    （空队列直接成功、失败保留队列顺序），因此补传不应只发生在「从离线
    恢复」那一刻——否则在线期间写入队列、或一次瞬时失败后被判定为仍在
    在线，都会永远错过补传机会。
    """
    if not bool(server_online):
        return False
    try:
        return int(pending_count or 0) > 0
    except (TypeError, ValueError):
        return False


class ApiClient:
    """与 HomeworkTime 服务端通信的客户端封装。"""

    DEFAULT_TIMEOUT = 5

    def __init__(
        self,
        local_config: LocalConfig,
        app_config: AppConfig,
    ) -> None:
        self.local_config = local_config
        self.app_config = app_config
        # 注：base_url / token 在构造时缓存（旧行为）；保存成功后
        # 必须显式调用 reload_credentials()，否则下一次网络 tick 仍
        # 命中旧地址。详见 reload_credentials()。
        self.base_url = (local_config.get("server_base_url") or "").rstrip("/")
        self.token = local_config.get("client_token") or ""
        self.session = requests.Session()
        #: 最近一次 push_config 失败原因（供 ConfigWindow 区分离线/拒绝）
        self.last_error: str = ""
        #: 网络调用互斥锁（音频保障线程与主线程 tick 可能并发访问 session）
        self._net_lock = threading.RLock()
        self._version = self._load_local_version()
        #: 最近一次心跳下发的全量更新信息（无则 None）；
        #: {version, size, sha256, effective_time}，由 Updater 消费
        self.server_update: Optional[Dict[str, Any]] = None
        #: 心跳上报的「已下载待生效版本」（由 AppController 每次心跳前
        #: 从 Updater.pending_version() 刷新；None=无待生效更新）
        self.pending_update_version: Optional[str] = None

    # ------------------------------------------------------------------
    # 凭据热更新
    # ------------------------------------------------------------------
    def reload_credentials(
        self,
        local_config: Optional[LocalConfig] = None,
    ) -> Tuple[str, str, str, str]:
        """重新从 local_config 读取 server_base_url / client_token。

        用途：用户在引导窗口或托盘「服务器设置」里改了地址/Token 后，
        不重启进程即可让下一次网络 tick 命中新地址（base_url / token
        在构造时被缓存，单纯写入 local_config 不会自动生效）。

        返回 ``(old_url, new_url, old_token, new_token)``，便于调用方
        做日志/状态判断（注意：token 由调用方自行决定是否脱敏打印）。
        """
        lc = local_config or self.local_config
        new_url = (lc.get("server_base_url") or "").rstrip("/")
        new_token = lc.get("client_token") or ""
        old_url, old_token = self.base_url, self.token
        self.base_url = new_url
        self.token = new_token
        return (old_url, new_url, old_token, new_token)

    # ------------------------------------------------------------------
    # 版本
    # ------------------------------------------------------------------
    @property
    def version(self) -> int:
        """本地已应用的配置版本号。"""
        return self._version

    def _load_local_version(self) -> int:
        """从业务配置缓存文件读取上次应用的 version（缺失视为 0）。"""
        try:
            with open(
                business_config_cache_path(self.app_config), "r", encoding="utf-8"
            ) as fh:
                raw = json.load(fh)
            v = raw.get("version")
            if isinstance(v, bool):
                return 0
            if isinstance(v, (int, float)):
                return int(v)
            return 0
        except (OSError, ValueError, TypeError):
            return 0

    def _persist_cache_with_version(
        self, config: Dict[str, Any], version: int
    ) -> None:
        """把配置 + version 一并写回业务配置缓存文件。

        AppConfig.apply_config 会先持久化一份不含 version 的配置，
        这里在其后补写 version 字段，使缓存文件成为权威的
        「配置 + 版本」落盘点（重启后据此恢复版本号）。
        """
        try:
            _write_json_atomic(
                business_config_cache_path(self.app_config),
                dict(config, version=version),
            )
        except OSError as exc:
            logger.warning("业务配置缓存(含版本)写入失败: %s", exc)

    # ------------------------------------------------------------------
    # HTTP 基元
    # ------------------------------------------------------------------
    def _request_json(self, method: str, path: str, **kwargs) -> Any:
        """发起带 X-Client-Token 的 JSON 请求；网络异常/非 2xx 返回 None。"""
        if not self.base_url or not self.token:
            return None
        url = "{}{}".format(self.base_url, path)
        headers = dict(kwargs.pop("headers", {}))
        headers[_AUTH_HEADER] = self.token
        try:
            with self._net_lock:
                resp = self.session.request(
                    method,
                    url,
                    headers=headers,
                    timeout=self.DEFAULT_TIMEOUT,
                    **kwargs,
                )
        except requests.exceptions.RequestException as exc:
            logger.info("请求失败 %s %s: %s", method, path, exc)
            return None
        if resp.status_code != 200:
            logger.info("请求返回 HTTP %s: %s", resp.status_code, path)
            return None
        try:
            return resp.json()
        except (ValueError, requests.exceptions.RequestException) as exc:
            logger.warning("响应解析失败 %s: %s", path, exc)
            return None

    # ------------------------------------------------------------------
    # 轮询 / 心跳
    # ------------------------------------------------------------------
    def poll(self) -> bool:
        """拉取远程配置；远程版本更高时写入缓存并 apply_config。

        返回是否发生了配置更新。版本相同/更低直接跳过；网络异常返回 False。
        """
        data = self._request_json("GET", "/api/client/config")
        if not isinstance(data, dict):
            return False
        config = data.get("config")
        if not isinstance(config, dict):
            return False
        raw_version = data.get("version")
        try:
            new_version = int(raw_version) if raw_version is not None else 0
        except (TypeError, ValueError):
            new_version = 0

        if new_version > 0 and new_version <= self._version:
            return False

        try:
            self.app_config.apply_config(config)
        except Exception as exc:
            logger.warning("apply_config 失败: %s", exc)
        self._persist_cache_with_version(config, new_version)
        if new_version > self._version:
            self._version = new_version
            logger.info("业务配置已更新到 v%d", new_version)
        return True

    def heartbeat(self) -> bool:
        """上报心跳；响应 version 高于本地时自动触发 poll()；
        响应 update 字段（服务端已发布的全量更新包信息）存入
        self.server_update，由 AppController 交给 Updater 处理。

        返回本次心跳是否成功（网络通且鉴权通过）。
        """
        body = {
            "device_uuid": self.local_config.get("device_uuid") or "",
            "device_name": platform.node() or "",
            "client_version": CLIENT_VERSION,
            "config_version": self._version,
            "update_pending_version": self.pending_update_version,
        }
        data = self._request_json("POST", "/api/client/heartbeat", json=body)
        if not isinstance(data, dict):
            return False
        raw_version = data.get("version")
        try:
            server_version = int(raw_version) if raw_version is not None else 0
        except (TypeError, ValueError):
            server_version = 0
        if server_version > self._version:
            self.poll()
        update = data.get("update")
        self.server_update = update if isinstance(update, dict) else None
        return True

    def download_update(self, url_path: str, dest_path: str) -> bool:
        """流式下载全量更新包到 dest_path（Updater 后台线程调用）。

        - 不走 ``_net_lock``、不复用 session：大文件下载耗时可达分钟级，
          不能阻塞心跳/轮询/音频保障；
        - 连接超时 10s、读超时 60s（流式期间每块读取都受限）；
        - 只负责落盘，sha256/大小校验由 Updater 完成；
        - 网络异常/HTTP 错误返回 False 且不抛出。
        """
        if not self.base_url or not self.token:
            return False
        url = "{}{}".format(self.base_url, url_path)
        try:
            resp = requests.get(
                url,
                headers={_AUTH_HEADER: self.token},
                stream=True,
                timeout=(10, 60),
            )
        except requests.exceptions.RequestException as exc:
            logger.warning("更新包下载发起失败: %s", exc)
            return False
        try:
            if resp.status_code != 200:
                logger.warning(
                    "更新包下载返回 HTTP %s", resp.status_code
                )
                return False
            try:
                os.makedirs(os.path.dirname(dest_path), exist_ok=True)
                with open(dest_path, "wb") as fh:
                    for chunk in resp.iter_content(chunk_size=256 * 1024):
                        if chunk:
                            fh.write(chunk)
            except OSError as exc:
                logger.warning("更新包写盘失败: %s", exc)
                return False
        finally:
            resp.close()
        logger.info("更新包下载完成: %s", dest_path)
        return True

    # ------------------------------------------------------------------
    # 配置推送（在线保存 / 离线补传）
    # ------------------------------------------------------------------
    def push_config(self, config: Dict[str, Any]) -> bool:
        """PUT /api/config（X-Client-Token），body {config}。

        成功返回 True；网络异常/HTTP 错误返回 False 且不抛出。
        失败原因写入 self.last_error。
        """
        self.last_error = ""
        if not self.base_url or not self.token:
            self.last_error = "未配置服务器或 Token"
            return False
        # 剥离 _comment / version 等辅助键，保证通过服务端配置校验
        config = sanitize_config(config)
        url = "{}/api/config".format(self.base_url)
        try:
            with self._net_lock:
                resp = self.session.put(
                    url,
                    headers={_AUTH_HEADER: self.token},
                    json={"config": config},
                    timeout=self.DEFAULT_TIMEOUT,
                )
        except requests.exceptions.RequestException as exc:
            self.last_error = "网络错误：{}".format(exc)
            logger.info("push_config 网络失败: %s", exc)
            return False
        if resp.status_code in (200, 201):
            return True
        if resp.status_code in (401, 403):
            self.last_error = "Token 无效，保存被拒绝（HTTP {}）".format(
                resp.status_code
            )
        else:
            body = ""
            try:
                body = resp.json().get("error", "")
            except Exception:
                pass
            self.last_error = "服务器返回错误（HTTP {}）{}".format(
                resp.status_code, body
            )
        logger.info("push_config 被拒绝: %s", self.last_error)
        return False

    def sync_pending(self, log_failure: bool = True) -> bool:
        """按序补传离线队列（pending_updates.json）。

        全部成功 → clear_pending() 并返回 True；
        任一失败 → 立即停止（保持队列与顺序）并返回 False。

        log_failure 为 False 时（主循环高频调度场景）失败不逐次打日志，
        由调用方做节流，避免每 tick 刷屏。
        """
        items = load_pending()
        if not items:
            return True
        for idx, item in enumerate(items, start=1):
            cfg = item.get("config") if isinstance(item, dict) else None
            if not isinstance(cfg, dict):
                continue
            if not self.push_config(cfg):
                if log_failure:
                    logger.info("待同步队列第 %d 条补传失败，保留队列等待重试", idx)
                return False
        try:
            cleared = clear_pending()
        except Exception as exc:
            logger.warning("待同步队列清空异常: %s", exc)
            return False
        if cleared:
            logger.info("离线配置补传完成，队列已清空")
        return cleared

    # ------------------------------------------------------------------
    # 音频
    # ------------------------------------------------------------------
    def get_audio_list(self) -> Optional[List[Dict[str, Any]]]:
        """获取服务端音频列表 [{filename, sha256, size, is_builtin}]。

        网络失败返回 None（调用方回退本地逻辑）。
        """
        data = self._request_json("GET", "/api/client/audio")
        if data is None:
            return None
        if isinstance(data, list):
            items = data
        elif isinstance(data, dict) and isinstance(data.get("items"), list):
            items = data["items"]
        else:
            return None
        result: List[Dict[str, Any]] = []
        for item in items:
            if not isinstance(item, dict):
                continue
            result.append(
                {
                    "filename": item.get("filename"),
                    "sha256": item.get("sha256"),
                    "size": item.get("size"),
                    "is_builtin": bool(item.get("is_builtin")),
                }
            )
        return result

    def ensure_audio(self, filename: str) -> Optional[str]:
        """确保指定音频文件本地可用，返回可播放路径或 None。

        - 服务端列表获取失败（离线）→ 回退本地可用（缓存/内置/绝对路径）；
        - 服务端不存在该文件记录 → 同样仅回退本地；
        - 内置文件名（near.wav/end.wav）优先打包资源；仅当服务端 sha256
          存在且与本地内置不一致时才下载覆盖版；
        - 缓存命中且 sha256 匹配 → 直接复用；否则下载到
          ``CACHE_SOUNDS_DIR``（打包后与 exe 同目录），
          下载后二次校验，不符则删除文件并返回 None。
        """
        if not filename:
            return None
        cache_dir = CACHE_SOUNDS_DIR
        cached = os.path.join(cache_dir, filename)
        builtin = resource_path(os.path.join("resources", "sounds", filename))
        is_builtin = filename in BUILTIN_AUDIO_NAMES

        audio_list = self.get_audio_list()
        if audio_list is None:
            # 在线列表不可用（网络异常/未配置）→ 本地兜底
            return self._resolve_playable(filename)

        record = next(
            (x for x in audio_list if x.get("filename") == filename), None
        )
        if record is None:
            return self._resolve_playable(filename)
        target_sha = ((record.get("sha256") or "") or "").strip().lower()

        # 1) 内置文件名：优先打包资源
        if is_builtin and os.path.isfile(builtin):
            if not target_sha or _sha256_file(builtin) == target_sha:
                logger.debug("使用内置音频: %s", builtin)
                return builtin
            # 服务端提供了与内置不一致的覆盖版 → 落入下方下载逻辑
            logger.info("服务端存在内置音频覆盖版，下载: %s", filename)
        elif os.path.isfile(cached):
            # 2) 缓存命中且 sha 匹配 → 直接复用
            if not target_sha or _sha256_file(cached) == target_sha:
                return cached

        # 3) 无 sha 可校验但已有缓存 → 复用
        if not target_sha and os.path.isfile(cached):
            return cached

        # 4) 下载并二次校验
        return self._download_and_verify(filename, cached, target_sha)

    def _download_and_verify(
        self, filename: str, dest: str, target_sha: str
    ) -> Optional[str]:
        """从服务端下载音频到 dest，下载后二次校验 sha256。"""
        if not self.base_url or not self.token:
            return None
        url = "{}/api/client/audio/{}".format(self.base_url, filename)
        try:
            with self._net_lock:
                resp = self.session.get(
                    url,
                    headers={_AUTH_HEADER: self.token},
                    timeout=self.DEFAULT_TIMEOUT,
                )
        except requests.exceptions.RequestException as exc:
            logger.warning("音频下载失败 %s: %s", filename, exc)
            return None
        if resp.status_code != 200:
            logger.warning(
                "音频下载失败 %s (HTTP %s)", filename, resp.status_code
            )
            return None
        try:
            os.makedirs(os.path.dirname(dest), exist_ok=True)
            with open(dest, "wb") as fh:
                fh.write(resp.content)
        except OSError as exc:
            logger.warning("音频写入失败 %s: %s", dest, exc)
            return None
        # 下载后二次校验：不符则删除文件并报错
        if target_sha:
            actual = _sha256_file(dest)
            if actual != target_sha:
                logger.error(
                    "音频 sha256 校验失败，删除下载文件: %s", filename
                )
                try:
                    os.remove(dest)
                except OSError:
                    pass
                return None
        logger.info("音频下载完成: %s -> %s", filename, dest)
        return dest

    def _resolve_playable(self, filename: str) -> Optional[str]:
        """本地兜底解析：绝对路径 > 下载缓存 > 内置资源。"""
        if not filename:
            return None
        if os.path.isabs(filename) and os.path.isfile(filename):
            return filename
        cached = os.path.join(CACHE_SOUNDS_DIR, filename)
        if os.path.isfile(cached):
            return cached
        builtin = resource_path(os.path.join("resources", "sounds", filename))
        if os.path.isfile(builtin):
            return builtin
        return None