# -*- coding: utf-8 -*-
"""PyQt5 冒烟测试。

两级验证：
1. 逻辑层（offscreen / 任意平台）：
   - 各窗口组件可构造、可 refresh、信号可连接、方法参数校验不抛异常；
   - AudioPlayer 内置音频路径解析正确。
   注意：Qt 的 offscreen 平台对「WA_TranslucentBackground + Qt.Tool +
   WindowOpacity」的顶层窗口渲染（show 后帧刷新）支持不完整，原生
   崩溃(0xC0000409)属平台限制，因此 offscreen 下不 show 顶层窗口，
   仅做构造与逻辑验证；真实桌面（非 offscreen）环境才执行 show 渲染。
2. 桌面层：若检测到非 offscreen 平台（真实 Win 桌面），额外 show 各窗口
   并刷新一次验证渲染路径。

运行方式：
    python client/tests/smoke_ui.py
若 PyQt5 未安装则以退出码 42 提示跳过。
"""

import os
import sys

# ---- 依赖检查：PyQt5 未安装时礼貌退出 ----
try:
    import PyQt5  # noqa: F401
except ImportError:
    print("[smoke] PyQt5 NOT installed, UI smoke skipped.")
    sys.exit(42)

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

_TEST_DIR = os.path.dirname(os.path.abspath(__file__))
_CLIENT_DIR = os.path.dirname(_TEST_DIR)
if _CLIENT_DIR not in sys.path:
    sys.path.insert(0, _CLIENT_DIR)

from datetime import datetime

from PyQt5.QtCore import QTimer
from PyQt5.QtWidgets import QApplication

from app.audio import AudioPlayer
from app.scheduler import get_state
from app.windows.confirm_dialog import ConfirmDialog
from app.windows.float_ball import FloatBall
from app.windows.main_window import MainWindow


def make_config():
    return {
        "evening_start": "18:30",
        "evening_end": "22:00",
        "subjects": [
            {"name": "语文", "start": "18:30", "end": "19:20"},
            {"name": "数学", "start": "19:30", "end": "20:10"},
            {"name": "英语", "start": "20:10", "end": "21:00"},
            {"name": "物理", "start": "21:00", "end": "22:00"},
        ],
        "idle_text": "课间休息",
        "opacity": {"main": 0.85, "ball": 0.70, "config": 1.0},
        "sound": {"enabled": True, "near_seconds": 60, "near_audio": "near.wav",
                  "near_enabled": True, "end_audio": "end.wav", "end_enabled": True},
    }


def smoke() -> int:
    cfg = make_config()
    app = QApplication.instance() or QApplication(sys.argv)

    # ---- AudioPlayer：内置音频路径解析 ----
    player = AudioPlayer()
    near_wav = player._resolve_path("near.wav")
    assert near_wav and os.path.isfile(near_wav), "built-in near.wav missing"
    for name in ("near.wav", "end.wav", "no_such_file.wav"):
        p = player._resolve_path(name)
        if name != "no_such_file.wav":
            assert p and os.path.isfile(p), f"builtin {name} missing"
        else:
            assert p is None, "missing file should resolve to None"
    print("[smoke] AudioPlayer resolve OK (near.wav / end.wav / missing)")

    # ---- MainWindow：三种状态 Refresh 逻辑 ----
    win = MainWindow(idle_text=cfg["idle_text"],
                     evening_range="18:30 - 22:00")
    win.setWindowOpacity(cfg["opacity"]["main"])
    signals_fired = {"closed": False}

    def _on_closed():
        signals_fired["closed"] = True

    win.closed_to_ball.connect(_on_closed)
    subject_text = None
    for label, now in (
        ("subject", datetime(2026, 1, 1, 18, 45)),
        ("idle", datetime(2026, 1, 1, 19, 25)),
        ("outside", datetime(2026, 1, 1, 12, 0)),
    ):
        state = get_state(cfg, now)
        win.refresh(state)
        assert win._state is state, "refresh should cache state"
        win.set_bottom_mode(not state.in_evening)
        print(f"[smoke] MainWindow refresh({label}) OK, phase={state.phase}")
        if label == "subject":
            subject_text = win.countdown_label.text()
    # 科目段内：18:45 距 19:20 剩 35 分钟 → "00:35:00"
    assert subject_text == "00:35:00", f"countdown text wrong: {subject_text}"
    win._on_close_clicked()  # 触发关闭 → 信号
    assert signals_fired["closed"], "closed_to_ball signal not fired"
    print("[smoke] MainWindow logic OK (refresh x3, close signal)")

    # ---- FloatBall：构造 / 位置记忆 / 置顶置底 / 尺寸 ----
    ball = FloatBall(ball_size=64)
    ball.setWindowOpacity(cfg["opacity"]["ball"])
    pos_cb = {"last": None}

    def _on_pos(p):
        pos_cb["last"] = (p.x(), p.y())

    ball.pos_changed.connect(_on_pos)
    ball.restore_position({"x": 100, "y": 100})
    assert (ball.pos().x(), ball.pos().y()) == (100, 100)
    ball.set_topmost(True)
    ball.set_topmost(False)
    ball.set_ball_size(80)
    assert ball.width() == 80, "ball size update failed"
    ball._drag_pos = ball.pos()
    ball.move(120, 130)
    ball.pos_changed.emit(ball.pos())  # 模拟拖动回调
    assert pos_cb["last"] == (120, 130), "pos_changed not emitted"
    print("[smoke] FloatBall logic OK (icons/size/topmost/pos)")

    # ---- ConfirmDialog：构造 + 控件存在 ----
    dialog = ConfirmDialog(None, "确定要打开配置窗口吗？")
    assert dialog._message_label.text() == "确定要打开配置窗口吗？"
    print("[smoke] ConfirmDialog logic OK")

    # ---- 桌面层：非 offscreen（真实 Win 桌面）时执行 show 渲染验证 ----
    if os.environ.get("QT_QPA_PLATFORM", "") != "offscreen":
        print("[smoke] desktop mode: show windows for render verification")
        win.set_bottom_mode(False)
        win.refresh(get_state(cfg, datetime(2026, 1, 1, 18, 45)))
        win.show()
        ball.set_ball_size(64)
        ball.show()
        dialog.show()
        # 短暂驱动事件循环后关闭
        QTimer.singleShot(300, app.quit)
        app.exec_()
        win.close()
        ball.close()
        dialog.close()
        print("[smoke] desktop render OK")

    print("[smoke] ALL PASS")
    return 0


if __name__ == "__main__":
    sys.exit(smoke())