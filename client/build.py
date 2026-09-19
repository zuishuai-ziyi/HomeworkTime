# -*- coding: utf-8 -*-
"""HomeworkTime 客户端打包脚本（PyInstaller，onedir）。

用法（在 client/ 目录下）：
    python build.py          # 直接运行
    build.bat                # Windows 双击

流程：
1. 检查 local_config.preset.json 是否填写 server_base_url / client_token：
   未填写 → 警告并要求确认（产物首次运行将弹出引导窗口）；
2. 检查 PyInstaller 是否可用（python -m PyInstaller --version），
   缺失时打印安装指引（不自动安装）；
3. 以 client/ 为工作目录调用 PyInstaller 打包：
   onedir（启动快、希沃一体机友好）、noconsole、add-data 打包
   resources/ 与 local_config.preset.json；
4. 完成后打印产物路径与部署说明。

仅依赖标准库 + subprocess 调用 PyInstaller，不引入额外依赖。
"""

from __future__ import annotations

import json
import os
import subprocess
import sys

# client/ 根目录（本文件所在目录，跨目录调用亦正确）
_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
# 打包预设文件
PRESET_PATH = os.path.join(_SCRIPT_DIR, "local_config.preset.json")
# 产物目录
DIST_DIR = os.path.join(_SCRIPT_DIR, "dist", "HomeworkTime")


def _sep() -> str:
    """--add-data 的 source:dest 分隔符（Windows 为 ';'，其余为 ':'）。"""
    return ";" if os.name == "nt" else ":"


def _load_preset() -> dict:
    """读取打包预设；缺失 / 损坏返回 {}。"""
    if not os.path.exists(PRESET_PATH):
        return {}
    try:
        with open(PRESET_PATH, "r", encoding="utf-8") as fh:
            raw = json.load(fh)
        return raw if isinstance(raw, dict) else {}
    except (OSError, ValueError) as exc:
        print("[警告] 打包预设解析失败，按未填写处理: %s" % exc)
        return {}


def _check_pyinstaller() -> bool:
    """探测 PyInstaller；不可用时打印安装指引并返回 False。"""
    try:
        proc = subprocess.run(
            [sys.executable, "-m", "PyInstaller", "--version"],
            capture_output=True,
            text=True,
            timeout=60,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        print("[错误] PyInstaller 调用失败: %s" % exc)
        return False
    if proc.returncode != 0:
        print("[错误] PyInstaller 不可用。")
        print("      请先安装，然后重新运行本脚本：")
        print("          pip install pyinstaller")
        return False
    print("[信息] PyInstaller 版本: %s" % proc.stdout.strip())
    return True


def main() -> int:
    preset = _load_preset()
    url = (str(preset.get("server_base_url") or "")).strip()
    token = (str(preset.get("client_token") or "")).strip()

    print("=" * 62)
    print(" HomeworkTime 客户端打包")
    print("=" * 62)
    print(" 打包预设 : %s" % PRESET_PATH)
    print("   server_base_url = %s" % (url or "(未填写)"))
    print("   client_token    = %s" % (("***%s" % token[-4:]) if token else "(未填写)"))

    if not url or not token:
        print()
        print("[警告] 打包预设未填写 server_base_url 或 client_token！")
        print("       产物首次运行将弹出引导窗口，需在目标机器上手动填写")
        print("       服务器地址与 Token 才能正常联网。")
        print("       如需免引导，请先编辑 local_config.preset.json")
        print("       填写真实地址/Token 后重新运行本脚本。")
        answer = input("仍要继续打包吗？(y/N): ").strip().lower()
        if answer not in ("y", "yes"):
            print("已取消打包。")
            return 1

    print()
    if not _check_pyinstaller():
        return 1

    sep = _sep()
    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--noconfirm",
        "--noconsole",
        "--name", "HomeworkTime",
        "--onedir",
        # 资源（音频/图标）→ _MEIPASS/resources
        "--add-data", "resources%sresources" % sep,
        # 内置默认业务配置 → _MEIPASS/app/default_config.json
        "--add-data", os.path.join("app", "default_config.json") + sep + "app",
        # 打包预设 → _MEIPASS/local_config.preset.json（与 resource_path 对齐）
        "--add-data", "local_config.preset.json%s." % sep,
        # 适度排除不必要模块，加快打包
        "--exclude-module", "tkinter",
        "--exclude-module", "unittest",
        "--exclude-module", "pydoc",
        "--exclude-module", "doctest",
        "main.py",
    ]
    print("[信息] 执行 PyInstaller 打包...")
    try:
        subprocess.run(cmd, cwd=_SCRIPT_DIR, check=True)
    except subprocess.CalledProcessError as exc:
        print("[错误] PyInstaller 打包失败: %s" % exc)
        return 1
    except OSError as exc:
        print("[错误] 无法启动 PyInstaller: %s" % exc)
        return 1

    exe_path = os.path.join(DIST_DIR, "HomeworkTime.exe")
    print()
    if os.path.exists(exe_path):
        size_mb = os.path.getsize(exe_path) / 1024.0 / 1024.0
        print("[完成] 打包成功！")
        print("   产物目录 : %s" % DIST_DIR)
        print("   入口程序 : %s （约 %.1f MB）" % (exe_path, size_mb))
        print("   部署方式 : 将整个 HomeworkTime 文件夹拷贝到目标机，")
        print("              双击 HomeworkTime.exe 即可。")
        return 0
    print("[警告] 未找到产物 %s，请检查上方 PyInstaller 输出。" % exe_path)
    return 1


if __name__ == "__main__":
    sys.exit(main())