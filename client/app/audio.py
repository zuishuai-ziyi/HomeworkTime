# -*- coding: utf-8 -*-
"""提示音播放模块。

AudioPlayer.play(wav_name) 按以下顺序解析音频路径：
    1) 下载缓存目录（``runtime_dir()/cache/sounds/``，阶段 5 服务端下发
       音频的落点；打包后与 exe 同目录，便于「整包拷贝 + 双击」）；
    2) 内置资源目录（resources/sounds/，通过 resource_path 解析，
       打包后位于 _MEIPASS 内）；
    3) wav_name 本身是绝对路径时，直接使用。
Windows 下用 winsound.PlaySound(SND_FILENAME | SND_ASYNC) 异步播放；
非 Windows 平台或播放异常时安全降级（记录日志后忽略）。
"""

from __future__ import annotations

import logging
import os
import threading
from typing import Optional

from .config import CACHE_SOUNDS_DIR, resource_path

logger = logging.getLogger(__name__)

try:  # Windows 专用
    import winsound  # type: ignore
except ImportError:  # pragma: no cover - 非 Windows 平台
    winsound = None


class AudioPlayer:
    """WAV 提示音播放器（线程安全，播放来自主线程 QTimer 即可）。

    set_enabled() 为总开关；被禁用时 play() 直接返回。
    每个音频片段可能被 SND_ASYNC 立即替换为后一个播放，这是预期的。
    """

    def __init__(
        self,
        cache_sounds_dir: Optional[str] = None,
        builtin_sounds_dir: Optional[str] = None,
    ) -> None:
        self._lock = threading.Lock()
        self._enabled = True
        self._cache_dir = cache_sounds_dir or CACHE_SOUNDS_DIR
        self._builtin_dir = builtin_sounds_dir or resource_path("resources/sounds")

    # ------------------------------------------------------------------
    def set_enabled(self, enabled: bool) -> None:
        with self._lock:
            self._enabled = bool(enabled)

    def is_enabled(self) -> bool:
        with self._lock:
            return self._enabled

    # ------------------------------------------------------------------
    def play(self, wav_name: str) -> bool:
        """异步播放指定 WAV。返回是否发起了播放（找不到文件或禁用返回 False）。"""
        if not self.is_enabled() or not wav_name:
            return False
        path = self._resolve_path(wav_name)
        if not path:
            logger.warning("提示音文件不存在，已忽略: %s", wav_name)
            return False
        if winsound is None:
            logger.debug("当前平台无 winsound，跳过播放: %s", wav_name)
            return False
        try:
            with self._lock:
                winsound.PlaySound(path, winsound.SND_FILENAME | winsound.SND_ASYNC)
            logger.debug("播放提示音: %s", path)
            return True
        except Exception as exc:  # 播放异常不应影响主流程
            logger.warning("提示音播放失败(%s): %s", wav_name, exc)
            return False

    # ------------------------------------------------------------------
    def _resolve_path(self, wav_name: str) -> Optional[str]:
        """按「下载缓存 > 内置资源 > 绝对路径」解析 WAV 文件路径。"""
        if not wav_name:
            return None
        if os.path.isabs(wav_name):
            return wav_name if os.path.isfile(wav_name) else None
        # 1) 下载缓存目录
        cached = os.path.join(self._cache_dir, wav_name)
        if os.path.isfile(cached):
            return cached
        # 2) 内置资源目录
        builtin = os.path.join(self._builtin_dir, wav_name)
        if os.path.isfile(builtin):
            return builtin
        return None