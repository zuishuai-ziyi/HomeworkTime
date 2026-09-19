# -*- coding: utf-8 -*-
"""按天滚动的本地日志模块（阶段 2）。

- 日志目录 = ``runtime_dir()/logs``（打包后与 exe 同目录，便于「整包
  拷贝 + 双击」），可用环境变量 ``HOMEWORKTIME_LOG_DIR`` 覆盖为任意
  绝对路径；
- 文件名 ``logs/app_YYYY-MM-DD.log``，跨天自动切换文件；
- INFO 级别，格式含 时间/级别/模块；同时输出到 stderr（方便调试）；
- 磁盘写入失败静默忽略（不抛出、不污染 stderr）；
- ``logs/`` 自动创建；启动清理时仅保留最近 N 天（默认 30）的日志。

用法::

    from app.logger import setup_logging, get_logger
    setup_logging()                       # 幂等，可在入口处调用一次
    logger = get_logger("ui")             # 实际 logger 名为 app.ui
    logger.info("hello")

项目中其它模块已有的 ``logging.getLogger(__name__)``（app.config 等子
logger）会透过 propagate 自动落到本模块的 "app" 根 logger 上，无需改造。
"""

from __future__ import annotations

import logging
import os
import re
import sys
import threading
from datetime import datetime, timedelta
from typing import Optional

from .config import runtime_dir

#: 环境变量：可用绝对路径覆盖日志目录
LOG_DIR_ENV = "HOMEWORKTIME_LOG_DIR"
#: 默认保留天数
DEFAULT_KEEP_DAYS = 30
#: 默认日志目录（运行目录/logs；打包后落在 exe 同级）
DEFAULT_LOG_DIR = os.path.join(runtime_dir(), "logs")

#: 与文件名 app_YYYY-MM-DD.log 匹配
_LOG_FILE_RE = re.compile(r"^app_\d{4}-\d{2}-\d{2}\.log$")

_lock = threading.Lock()
_configured = False


class _DailyFileHandler(logging.Handler):
    """按天滚动文件 handler。

    - 首次构造即建目录 + 清理过期日志；
    - emit 时若跨天则自动切换文件；
    - 打开/写入失败时静默忽略（仅 enqueue 不抛出）。
    """

    def __init__(self, log_dir: str, keep_days: int) -> None:
        super().__init__()
        self._log_dir = log_dir
        self._keep_days = max(1, int(keep_days or DEFAULT_KEEP_DAYS))
        self._stream = None
        self._last_date: Optional[str] = None
        self._cleanup_old()
        self._rotate()

    # -- 文件管理 ----------------------------------------------------------
    def _path_for(self, date_str: str) -> str:
        return os.path.join(self._log_dir, "app_%s.log" % date_str)

    def _rotate(self) -> None:
        """按当天日期切换日志文件。失败时置空流（后续 emit 静默丢弃）。"""
        today = datetime.now().strftime("%Y-%m-%d")
        if self._stream is not None and today == self._last_date:
            return
        if self._stream is not None:
            try:
                self._stream.close()
            except OSError:
                pass
            self._stream = None
        try:
            os.makedirs(self._log_dir, exist_ok=True)
            self._stream = open(self._path_for(today), "a", encoding="utf-8")
            self._last_date = today
        except OSError:
            self._stream = None
            self._last_date = None

    def _cleanup_old(self) -> None:
        """删除 keep_days 天之前（严格早于今天-keep_days）的滚动日志。"""
        try:
            if not os.path.isdir(self._log_dir):
                return
            deadline = datetime.now() - timedelta(days=self._keep_days)
            for name in os.listdir(self._log_dir):
                if not _LOG_FILE_RE.match(name):
                    continue
                try:
                    day = datetime.strptime(name[4:-4], "%Y-%m-%d")
                except ValueError:
                    continue
                if day < deadline:
                    try:
                        os.remove(os.path.join(self._log_dir, name))
                    except OSError:
                        pass
        except OSError:
            pass

    # -- logging.Handler ---------------------------------------------------
    def emit(self, record: logging.LogRecord) -> None:
        try:
            self._rotate()
            if self._stream is None:
                return  # 写入失败：静默忽略
            self._stream.write(self.format(record) + "\n")
            self._stream.flush()
        except Exception:
            # raiseExceptions=False 时 handleError 什么都不做 → 静默
            logging.raiseExceptions = False
            self.handleError(record)

    def close(self) -> None:
        if self._stream is not None:
            try:
                self._stream.close()
            except OSError:
                pass
            self._stream = None
        super().close()


# ---------------------------------------------------------------------------
# 模块级接口
# ---------------------------------------------------------------------------


def setup_logging(
    log_dir: Optional[str] = None,
    level: int = logging.INFO,
    keep_days: Optional[int] = None,
    force: bool = False,
) -> logging.Logger:
    """配置 "app" 根 logger（文件 + stderr 双输出）。

    幂等：已在配置状态时直接返回；``force=True`` 可用于测试重建。
    返回配置完成的 "app" logger。
    """
    global _configured
    log_dir = log_dir or os.environ.get(LOG_DIR_ENV) or DEFAULT_LOG_DIR
    keep_days = keep_days if keep_days is not None else DEFAULT_KEEP_DAYS

    logger = logging.getLogger("app")
    with _lock:
        if _configured and not force:
            return logger

        # 重建时清空旧 handler，避免重复输出 / 残留测试句柄
        for handler in list(logger.handlers):
            try:
                handler.close()
            except Exception:
                pass
            logger.removeHandler(handler)

        logger.setLevel(level)
        logger.propagate = False
        fmt = logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")

        file_handler = _DailyFileHandler(log_dir, keep_days)
        file_handler.setFormatter(fmt)
        logger.addHandler(file_handler)

        stream_handler = logging.StreamHandler(sys.stderr)
        stream_handler.setFormatter(fmt)
        logger.addHandler(stream_handler)

        _configured = True
        return logger


def get_logger(name: Optional[str] = None) -> logging.Logger:
    """返回带本模块输出的 logger（首次调用自动完成日志配置）。

    ``name`` 省略时为 "app"；给出时为 "app.<name>"，便于日志里区分模块。
    """
    setup_logging()
    if not name:
        return logging.getLogger("app")
    return logging.getLogger("app.%s" % name)