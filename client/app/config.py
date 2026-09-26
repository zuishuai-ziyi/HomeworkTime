# -*- coding: utf-8 -*-
"""配置管理模块（阶段 1 基础版）。

- LocalConfig：本机专属配置（client/local_config.json，不同步服务器）。
- AppConfig   ：业务配置（本地缓存 cache/business_config.json 优先，内置
  default_config.json 兜底；此为基础版，阶段 2 才会接入远程下发与配置窗口）。
- resource_path：资源路径解析，兼容源码运行与 PyInstaller 打包。

本模块不涉及网络功能（阶段 5）与配置窗口（阶段 2）。
"""

from __future__ import annotations

import json
import logging
import os
import sys
import threading
import uuid
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger(__name__)

# client/ 根目录：依据本文件位置推导（client/app/config.py → client/）
# 仅用于解析「打包内的只读资源」（default_config.json / preset / resources/）。
# 运行期可写目录请用 runtime_dir() / RUNTIME_DIR，确保打包后落在 exe 同级。
CLIENT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def runtime_dir() -> str:
    """运行期可写目录（local_config.json 所在目录）。

    - 源码运行：client/ 根目录；
    - PyInstaller 打包（onedir）：exe 所在目录，保证「整包拷贝 + 双击」
      即可工作，配置不落在 sys._MEIPASS 临时展开目录里。

    注意：本模块在 import 阶段会调用一次得到 RUNTIME_DIR，供 CACHE_DIR
    等派生常量使用；其它模块（logger / audio / windows）若仅需目录常量，
    可直接 ``from .config import RUNTIME_DIR`` 而无需关心 frozen 判断。
    """
    if getattr(sys, "frozen", False):
        return os.path.dirname(os.path.abspath(sys.executable))
    return CLIENT_DIR


# 运行期可写目录（模块加载时一次性求值；之后 frozen 状态不会变）。
# 所有用户可写的运行时产物（local_config / cache / logs）都派生自此目录。
RUNTIME_DIR = runtime_dir()

# 业务配置缓存目录（打包后落在 exe 同级，便于「整包拷贝 + 双击」）
CACHE_DIR = os.path.join(RUNTIME_DIR, "cache")
BUSINESS_CONFIG_CACHE = os.path.join(CACHE_DIR, "business_config.json")
# 提示音下载缓存子目录（阶段 5 网络下发音频的落点）
CACHE_SOUNDS_DIR = os.path.join(CACHE_DIR, "sounds")
# 本机专属配置（打包后与 exe 同目录）
LOCAL_CONFIG_PATH = os.path.join(RUNTIME_DIR, "local_config.json")
#: 离线待同步队列（阶段 2 起：本地配置窗口离线保存时的补传清单）
PENDING_UPDATES_PATH = os.path.join(CACHE_DIR, "pending_updates.json")
# 内置默认业务配置
DEFAULT_CONFIG_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "default_config.json"
)
# 本机配置示例模板（打包参考用）
LOCAL_CONFIG_EXAMPLE_PATH = os.path.join(CLIENT_DIR, "local_config.example.json")
#: 打包预设文件名：打包进产物，目标机首次运行据此生成本机配置
PRESET_FILENAME = "local_config.preset.json"
PRESET_PATH = os.path.join(CLIENT_DIR, PRESET_FILENAME)


def resource_path(rel: str) -> str:
    """将相对资源路径（如 resources/icons/ball_bell.svg）解析为绝对路径。

    兼容两种运行形态：
    - 源码运行：相对 client/ 根目录解析；
    - PyInstaller 打包：相对 sys._MEIPASS 解析。
    """
    base = getattr(sys, "_MEIPASS", None) or CLIENT_DIR
    return os.path.join(base, rel)


def find_preset_path() -> Optional[str]:
    """定位打包预设文件 local_config.preset.json。

    命中顺序：源码目录（client/，与 local_config.example.json 同级）→
    PyInstaller 打包环境（sys._MEIPASS，即 resource_path 机制）。
    返回第一个存在的路径；均不存在返回 None。
    """
    candidates: List[str] = []
    src_preset = os.path.join(CLIENT_DIR, PRESET_FILENAME)
    if os.path.exists(src_preset):
        candidates.append(src_preset)
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        bundled = os.path.join(meipass, PRESET_FILENAME)
        if os.path.exists(bundled) and bundled not in candidates:
            candidates.append(bundled)
    return candidates[0] if candidates else None


# ---------------------------------------------------------------------------
# 本机专属配置
# ---------------------------------------------------------------------------

#: 本机专属配置的合法键与默认值（与 local_config.example.json 字段一致）。
LOCAL_CONFIG_DEFAULTS: Dict[str, Any] = {
    "server_base_url": "http://127.0.0.1:3000",
    "client_token": "",
    "poll_interval_sec": 10,
    "autostart": True,
    "ball_pos": None,      # {x, y} 或 None
    "ball_size": 64,
    "device_uuid": None,
    #: 用户是否在引导窗口里选择「跳过（离线模式）」；
    #: True → 不再每次启动都弹引导，可通过托盘「服务器设置」重新打开。
    "guide_dismissed": False,
}


class LocalConfig:
    """读写 client 目录下的 local_config.json。

    首次加载时若文件不存在，按三级顺序初始化：
    ① 运行目录已有配置 → 直接读取；
    ② 打包预设 local_config.preset.json 存在 → 以其为底创建
      （过滤 _comment 等未知键，缺失字段用默认值补齐），
      并写入运行目录 local_config.json；
    ③ 都没有 → 参照 local_config.example.json 的字段生成。
    均会生成 device_uuid 并持久化。写入采用「临时文件 + 原子替换」，
    避免中途断电损坏配置。
    """

    def __init__(self, path: Optional[str] = None, load_now: bool = True) -> None:
        self._path = path or LOCAL_CONFIG_PATH
        self._data: Dict[str, Any] = dict(LOCAL_CONFIG_DEFAULTS)
        # RLock：load() 持锁内部会再调用 save()/set()，需可重入
        self._lock = threading.RLock()
        if load_now:
            self.load()

    # -- 加载 --------------------------------------------------------------
    def load(self) -> None:
        """加载本机配置；缺失时按三级顺序创建并立即持久化：

        ① 运行目录 local_config.json 存在 → 照旧读取；
        ② 不存在但存在打包预设 → 以预设为底初始化；
        ③ 都没有 → 基于示例模板 + 默认值（现状）。
        """
        with self._lock:
            if os.path.exists(self._path):
                try:
                    with open(self._path, "r", encoding="utf-8") as fh:
                        raw = json.load(fh)
                    if isinstance(raw, dict):
                        # 仅保留合法键
                        self._data = {
                            k: raw.get(k, v)
                            for k, v in LOCAL_CONFIG_DEFAULTS.items()
                        }
                except (OSError, ValueError) as exc:
                    logger.warning("local_config 读取失败，使用默认值: %s", exc)
                    self._data = dict(LOCAL_CONFIG_DEFAULTS)
            else:
                preset_path = find_preset_path()
                if preset_path:
                    # ② 打包预设：目标机首次运行据此生成本机配置
                    self._data = self._merge_preset(preset_path)
                    logger.info(
                        "已从打包预设初始化 local_config.json: %s", preset_path
                    )
                else:
                    # ③ 兜底：以 example 模板字段为起点（去除 _comment 键）
                    self._data = self._merge_template(
                        self._load_example_template()
                    )

            # 首次生成 device_uuid 并持久化
            if not self._data.get("device_uuid"):
                self._data["device_uuid"] = str(uuid.uuid4())

            # 确保 dict 结构（ball_pos 应为 {x,y} 或 None）
            if self._data.get("ball_pos") is not None and not isinstance(
                self._data["ball_pos"], dict
            ):
                self._data["ball_pos"] = None

            self.save()

    @staticmethod
    def _merge_template(template: Dict[str, Any]) -> Dict[str, Any]:
        """以默认值为底，模板字段覆盖（None 视为缺失，用默认值兜底）。"""
        merged = dict(LOCAL_CONFIG_DEFAULTS)
        merged.update({k: v for k, v in template.items() if v is not None})
        return merged

    def _merge_preset(self, preset_path: str) -> Dict[str, Any]:
        """以打包预设为底创建本机配置。

        - 仅保留 LOCAL_CONFIG_DEFAULTS 白名单内的键（过滤 _comment 等）；
        - 缺失 / 空字符串字段 → 回落默认值（url/token 留空即「未配置」）；
        - ball_pos 恒为 None（首次位置记忆留给运行期写入）。
        """
        template = self._load_preset(preset_path)
        merged = dict(LOCAL_CONFIG_DEFAULTS)
        for key, default in LOCAL_CONFIG_DEFAULTS.items():
            if key == "ball_pos":
                merged[key] = None
                continue
            value = template.get(key)
            if value is None or (isinstance(value, str) and not value.strip()):
                value = default
            merged[key] = value
        return merged

    def _load_preset(self, preset_path: str) -> Dict[str, Any]:
        """读取打包预设，仅保留白名单键（过滤 _comment 等未知键）。"""
        try:
            with open(preset_path, "r", encoding="utf-8") as fh:
                raw = json.load(fh)
            if not isinstance(raw, dict):
                return {}
            return {k: v for k, v in raw.items() if k in LOCAL_CONFIG_DEFAULTS}
        except (OSError, ValueError):
            logger.warning("打包预设读取失败: %s", preset_path)
            return {}

    def _load_example_template(self) -> Dict[str, Any]:
        """读取 local_config.example.json 的字段（丢弃 _comment 说明键）。"""
        if not os.path.exists(LOCAL_CONFIG_EXAMPLE_PATH):
            return {}
        try:
            with open(LOCAL_CONFIG_EXAMPLE_PATH, "r", encoding="utf-8") as fh:
                raw = json.load(fh)
            if not isinstance(raw, dict):
                return {}
            return {k: v for k, v in raw.items() if not k.startswith("_")}
        except (OSError, ValueError):
            return {}

    # -- 访问 --------------------------------------------------------------
    def get(self, key: str, default: Any = None) -> Any:
        return self._data.get(key, default)

    def set(self, key: str, value: Any, save: bool = True) -> None:
        with self._lock:
            self._data[key] = value
            if save:
                self.save()

    @property
    def data(self) -> Dict[str, Any]:
        return self._data

    # -- 持久化 ------------------------------------------------------------
    def save(self) -> None:
        """原子写回配置文件（临时文件 + os.replace）。"""
        with self._lock:
            try:
                os.makedirs(os.path.dirname(self._path), exist_ok=True)
                tmp = self._path + ".tmp"
                with open(tmp, "w", encoding="utf-8") as fh:
                    json.dump(self._data, fh, ensure_ascii=False, indent=2)
                os.replace(tmp, self._path)
            except OSError as exc:
                logger.warning("local_config 保存失败: %s", exc)


# ---------------------------------------------------------------------------
# 业务配置（服务器下发 + 本地缓存）
# ---------------------------------------------------------------------------


def _deep_merge(base: Dict[str, Any], override: Dict[str, Any]) -> Dict[str, Any]:
    """递归合并；override 优先，base 补齐缺失键。返回新字典。"""
    if not isinstance(base, dict) or not isinstance(override, dict):
        return override
    out = dict(base)
    for k, v in override.items():
        out[k] = _deep_merge(out[k], v) if k in out and isinstance(
            out[k], dict) and isinstance(v, dict) else v
    return out


class AppConfig:
    """业务配置管理。

    加载顺序：本地缓存文件(cache/business_config.json) > 内置
    default_config.json —— 即缓存优先，内置兜底。
    通过 apply_config() 可整体替换配置（阶段 5 服务器下发入口）并写缓存，
    同时触发变更通知（简单回调列表，供主窗口/悬浮球刷新透明度、内容等）。
    此为基础版：仅本地读写，不做网络同步。
    """

    def __init__(
        self,
        cache_path: Optional[str] = None,
        default_path: Optional[str] = None,
        load_now: bool = True,
    ) -> None:
        self._cache_path = cache_path or BUSINESS_CONFIG_CACHE
        self._default_path = default_path or DEFAULT_CONFIG_PATH
        self._data: Dict[str, Any] = {}
        self._listeners: List[Callable[[Dict[str, Any]], None]] = []
        self._lock = threading.RLock()  # 可重入：内部方法间存在锁嵌套调用
        if load_now:
            self.load()

    # -- 加载 --------------------------------------------------------------
    def _load_builtin(self) -> Dict[str, Any]:
        if not os.path.exists(self._default_path):
            logger.warning("内置 default_config.json 缺失: %s", self._default_path)
            return {}
        try:
            with open(self._default_path, "r", encoding="utf-8") as fh:
                raw = json.load(fh)
            return raw if isinstance(raw, dict) else {}
        except (OSError, ValueError) as exc:
            logger.warning("内置默认配置解析失败: %s", exc)
            return {}

    def _load_cache(self) -> Dict[str, Any]:
        if not os.path.exists(self._cache_path):
            return {}
        try:
            with open(self._cache_path, "r", encoding="utf-8") as fh:
                raw = json.load(fh)
            if not isinstance(raw, dict):
                return {}
            # 剔除阶段 5 ApiClient 写入的 version 标记字段，
            # 避免污染业务配置本体（version 不属于配置契约中的字段）。
            return {k: v for k, v in raw.items() if k != "version"}
        except (OSError, ValueError) as exc:
            logger.warning("业务配置缓存读取失败，回退内置默认: %s", exc)
            return {}

    def load(self) -> None:
        """按「缓存 > 内置」顺序加载业务配置。"""
        with self._lock:
            builtin = self._load_builtin()
            cache = self._load_cache()
            self._data = _deep_merge(builtin, cache)

    def _persist(self) -> None:
        try:
            os.makedirs(os.path.dirname(self._cache_path), exist_ok=True)
            tmp = self._cache_path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as fh:
                json.dump(self._data, fh, ensure_ascii=False, indent=2)
            os.replace(tmp, self._cache_path)
        except OSError as exc:
            logger.warning("业务配置缓存写入失败: %s", exc)

    # -- 访问 --------------------------------------------------------------
    @property
    def data(self) -> Dict[str, Any]:
        return self._data

    def get(self, key: str, default: Any = None) -> Any:
        return self._data.get(key, default)

    def set(self, key: str, value: Any, persist: bool = True) -> None:
        """修改单个配置键并持久化、通知。"""
        with self._lock:
            self._data[key] = value
            if persist:
                self._persist()
        self._notify()

    def apply_config(self, new_config: Dict[str, Any]) -> None:
        """整体应用新配置（阶段 5 服务器下发入口）。

        与既有配置递归合并（保留本地尚未下发的键），更新缓存文件，
        并向所有监听者发送变更通知。
        """
        if not isinstance(new_config, dict):
            logger.warning("apply_config 收到非 dict 参数，忽略: %r", new_config)
            return
        with self._lock:
            # 以现有数据为底，新配置覆盖（保留内置结构完整性）
            self._data = _deep_merge(self._data, new_config)
            self._persist()
        self._notify()

    # -- 变更通知 ----------------------------------------------------------
    def add_listener(self, callback: Callable[[Dict[str, Any]], None]) -> None:
        """注册变更监听器；callback 接收当前完整配置 dict。"""
        if callback not in self._listeners:
            self._listeners.append(callback)

    def remove_listener(self, callback: Callable[[Dict[str, Any]], None]) -> None:
        if callback in self._listeners:
            self._listeners.remove(callback)

    def _notify(self) -> None:
        snapshot = dict(self._data)
        for cb in list(self._listeners):
            try:
                cb(snapshot)
            except Exception as exc:  # 监听器异常不影响其他监听器
                logger.exception("配置变更监听器执行失败: %s", exc)


# ---------------------------------------------------------------------------
# 待同步队列（pending_updates.json）
# ---------------------------------------------------------------------------
# 业务配置单一数据源是服务器。本地配置窗口保存时若服务器不可达，先写入
# 此队列（离线保存），联网后由阶段 5 的 api_client 按顺序补传并清除。
# 这里的三个纯函数独立于 UI 与网络，便于单测。

_pending_lock = threading.RLock()


def load_pending(path: Optional[str] = None) -> List[Dict[str, Any]]:
    """读取待同步队列全部条目；文件缺失/损坏返回空列表。"""
    path = path or PENDING_UPDATES_PATH
    with _pending_lock:
        if not os.path.exists(path):
            return []
        try:
            with open(path, "r", encoding="utf-8") as fh:
                data = json.load(fh)
            return data if isinstance(data, list) else []
        except (OSError, ValueError) as exc:
            logger.warning("待同步队列读取失败: %s", exc)
            return []


def save_pending(
    config: Dict[str, Any],
    timestamp: Optional[str] = None,
    path: Optional[str] = None,
) -> None:
    """追加一条待同步配置到队列（列表 append {ts, config}）。"""
    path = path or PENDING_UPDATES_PATH
    ts = timestamp or datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with _pending_lock:
        items = load_pending(path)
        items.append({"ts": ts, "config": config})
        try:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            tmp = path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as fh:
                json.dump(items, fh, ensure_ascii=False, indent=2)
            os.replace(tmp, path)
        except OSError as exc:
            logger.warning("待同步队列写入失败: %s", exc)


def clear_pending(path: Optional[str] = None) -> bool:
    """清空待同步队列（删除文件）。返回是否成功。"""
    path = path or PENDING_UPDATES_PATH
    with _pending_lock:
        try:
            if os.path.exists(path):
                os.remove(path)
            return True
        except OSError as exc:
            logger.warning("待同步队列清空失败: %s", exc)
            return False