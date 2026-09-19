# -*- coding: utf-8 -*-
"""开机自启管理（阶段 2，仅 Windows）。

通过 winreg 写注册表 ``HKCU\\Software\\Microsoft\\Windows\\CurrentVersion\\Run``
下的 ``HomeworkTime`` 键，值为::

    "pythonw.exe" "<client/main.py 绝对路径>"

- ``sys.executable`` 为 python.exe 时优先使用同目录的 pythonw.exe（避免
  启动时弹出黑色控制台窗口）；pythonw.exe 不存在则原样使用 python.exe；
- 非 Windows 平台一律返回 False / 静默忽略；
- 全部异常捕获并记录日志，不影响主流程。

测试友好：``is_autostart_enabled()`` / ``set_autostart()`` 均可注入
registry 对象（默认取模块级 ``winreg``），便于 mock 或无注册表环境验证。
"""

from __future__ import annotations

import logging
import os
import sys
from typing import Optional

logger = logging.getLogger("app.autostart")

try:
    import winreg  # type: ignore  # Windows only
except ImportError:  # pragma: no cover - 非 Windows
    winreg = None  # type: ignore[assignment]

#: 自启动注册表键路径
RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
#: 注册表键名
APP_NAME = "HomeworkTime"


# ---------------------------------------------------------------------------
# 命令构造
# ---------------------------------------------------------------------------


def _entry_script() -> str:
    """client/main.py 的绝对路径（依据本文件位置推导）。"""
    base = os.path.dirname(os.path.abspath(__file__))     # client/app/
    return os.path.join(os.path.dirname(base), "main.py")


def _command() -> str:
    """构造自启动命令行：pythonw(或 python.exe) + client/main.py。"""
    exe = sys.executable or "python"
    if os.path.normcase(os.path.basename(exe)).lower() == "python.exe":
        candidate = os.path.join(os.path.dirname(exe), "pythonw.exe")
        if os.path.isfile(candidate):
            exe = candidate
    return '"%s" "%s"' % (exe, _entry_script())


# ---------------------------------------------------------------------------
# 查询 / 设置
# ---------------------------------------------------------------------------


def is_autostart_enabled(registry: Optional[object] = None) -> bool:
    """查询自启动注册表键是否存在。非 Windows 返回 False。"""
    reg = registry if registry is not None else winreg
    if reg is None:
        return False
    try:
        with reg.OpenKey(reg.HKEY_CURRENT_USER, RUN_KEY) as key:
            reg.QueryValueEx(key, APP_NAME)
        return True
    except OSError:
        return False
    except Exception as exc:
        logger.warning("读取自启注册表失败: %s", exc)
        return False


def set_autostart(enabled: bool, registry: Optional[object] = None) -> bool:
    """写入/删除自启动注册表键。返回是否操作成功。"""
    reg = registry if registry is not None else winreg
    if reg is None:
        return False
    try:
        key = reg.CreateKey(reg.HKEY_CURRENT_USER, RUN_KEY)
        try:
            if enabled:
                reg.SetValueEx(key, APP_NAME, 0, reg.REG_SZ, _command())
            else:
                try:
                    reg.DeleteValue(key, APP_NAME)
                except OSError:
                    pass  # 键本不存在也视为成功
        finally:
            reg.CloseKey(key)
        logger.info("开机自启已%s", "开启" if enabled else "关闭")
        return True
    except Exception as exc:
        logger.warning("设置自启失败(%s): %s", enabled, exc)
        return False