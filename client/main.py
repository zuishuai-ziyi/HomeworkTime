# -*- coding: utf-8 -*-
"""HomeworkTime 客户端入口。

运行方式（二者均可）：
    python client/main.py          # 从项目根目录
    python main.py                 # 在 client/ 目录下
    python -m app.main             # 在 client/ 目录下（以包方式运行）

sys.path 处理：将本文件所在目录（client/）加入导入路径，使 app 包
无论从何处启动都能被正确导入。
"""

from __future__ import annotations

import os
import sys


def _ensure_utf8_stdio() -> None:
    """将 stdout/stderr 强制设置为 UTF-8，避免控制台中文日志乱码。

    背景：Windows 默认控制台代码页为 936（GBK）或当前系统区域代码页，
    与 Python 3 的 UTF-8 字符串输出端不匹配，导致 logger.info("中文")
    在 PowerShell / cmd 中出现「浣犱笅」「绯荤粨」等乱码。

    关键点：
    1) stdout.reconfigure(encoding="utf-8") 是最根本的修复——它告诉
       Python 写出 UTF-8 字节流，再配合控制台代码页 65001 即可正常显示；
    2) 仅在有真实控制台时才调用 SetConsoleOutputCP（PyInstaller 打包
       后无控制台，或被重定向到文件时不应调用，否则可能抛异常）；
    3) 全部用 try/except 静默——修复失败不应阻塞主流程。
    """
    # 1) 优先用 reconfigure 让 Python 自身以 UTF-8 写出字节流
    for stream_name in ("stdout", "stderr"):
        stream = getattr(sys, stream_name, None)
        if stream is None:
            continue
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is None:
            continue
        try:
            current_enc = getattr(stream, "encoding", None)
            if current_enc and current_enc.lower().replace("-", "") == "utf8":
                # 已经是 utf-8，无需改动
                continue
            reconfigure(encoding="utf-8")
        except Exception:
            # 控制台句柄可能不支持 reconfigure（例如重定向到管道且
            # 已绑定编码），失败时静默——不影响主流程。
            pass

    # 2) 辅助：Windows 控制台代码页设为 65001 (UTF-8)。
    # 仅在 win32 + 存在真实控制台时尝试；reconfigure 是关键，
    # 这里只是兜底，让 Windows 原生命令在 PowerShell / cmd 中
    # 也能直接打印 UTF-8 字节。
    if sys.platform == "win32":
        try:
            import ctypes  # 延迟导入，避免非 Windows 环境开销

            kernel32 = getattr(ctypes, "windll", None)
            if kernel32 is None:
                return
            SetConsoleOutputCP = getattr(
                kernel32, "SetConsoleOutputCP", None
            )
            if SetConsoleOutputCP is None:
                return
            # 仅当 stdout 真实连接到控制台时才调用：
            # 重定向到文件 / 管道时调用也会成功但无意义，且部分环境
            # 可能抛异常，因此加 try 兜底。
            try:
                is_tty = False
                try:
                    is_tty = bool(sys.stdout and sys.stdout.isatty())
                except Exception:
                    is_tty = False
                if is_tty:
                    SetConsoleOutputCP(65001)
            except Exception:
                pass
        except Exception:
            # ctypes 不可用 / 加载失败——静默忽略
            pass


def _prepare_path() -> None:
    client_dir = os.path.dirname(os.path.abspath(__file__))
    if client_dir not in sys.path:
        sys.path.insert(0, client_dir)


def run() -> int:
    # 必须在所有其它 import 与业务逻辑之前调用——
    # 这样 logger 第一次输出中文就能命中 UTF-8。
    _ensure_utf8_stdio()
    _prepare_path()
    from app.main import run as _app_run  # 延迟导入，确保路径已就绪

    return _app_run()


if __name__ == "__main__":
    sys.exit(run())
