# -*- coding: utf-8 -*-
"""AppController（状态机）无头冒烟测试。

- 以临时目录配置实例化 AppController（不写真实 local_config.json）；
- 注入假音频播放器，避免任何实际发音；
- 依次驱动 _sync_windows 的晚自习内 / 晚自习外 / 主窗口关闭等分支，
  验证主窗口与悬浮球的显示隐藏、置顶置底切换不抛异常。

运行方式：
    python client/tests/smoke_controller.py
"""

import os
import sys
import tempfile

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

_TEST_DIR = os.path.dirname(os.path.abspath(__file__))
_CLIENT_DIR = os.path.dirname(_TEST_DIR)
if _CLIENT_DIR not in sys.path:
    sys.path.insert(0, _CLIENT_DIR)

from datetime import datetime

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import QApplication

from app.config import AppConfig, DEFAULT_CONFIG_PATH, LocalConfig
from app.scheduler import get_state


class FakeAudioPlayer:
    """占位音频播放器：记录调用、不发音。"""

    def __init__(self):
        self.calls = []
        self._enabled = True

    def set_enabled(self, enabled):
        self._enabled = enabled

    def play(self, name):
        self.calls.append(name)
        return True


def main() -> int:
    app = QApplication.instance() or QApplication(sys.argv)
    tmp = tempfile.mkdtemp(prefix="ht_smoke_")

    local = LocalConfig(path=os.path.join(tmp, "local_config.json"))
    biz = AppConfig(
        cache_path=os.path.join(tmp, "business_config.json"),
        default_path=DEFAULT_CONFIG_PATH,
        load_now=True,
    )
    fake_audio = FakeAudioPlayer()

    from app.main import AppController

    ctl = AppController(app, local_config=local, app_config=biz,
                        audio_player=fake_audio)
    ctl.timer.stop()  # 冒烟：手动驱动，不启动真实 1s 定时器
    print("[smoke-ctl] AppController constructed OK")

    cfg = biz.data

    # 状态机各分支手动驱动（现在时刻的 got_state 来自北京时间本地时钟，
    # 通过不同配置强制进入晚自习内/外）
    results = []

    # 分支 1：晚自习内（默认配置 18:30-22:00），19:00 段内
    state = get_state(cfg, datetime(2026, 1, 1, 19, 0))
    assert state.in_evening and state.phase == "subject"
    ctl._sync_windows(state)
    assert ctl.main_window.isVisible(), "main window should be visible in evening"
    assert not ctl.float_ball.isVisible(), "ball hidden in evening(auto)"
    assert ctl.main_window.windowFlags() & Qt.WindowStaysOnTopHint
    results.append("evening-auto: main topmost")

    # 分支 2：用户关闭主窗口 → 球置顶显示
    ctl._on_main_closed()
    assert not ctl.main_window.isVisible()
    assert ctl.float_ball.isVisible(), "ball visible after user close"
    state2 = get_state(cfg, datetime(2026, 1, 1, 19, 1))
    ctl._sync_windows(state2)
    assert not ctl.main_window.isVisible(), "main stays hidden after close"
    results.append("user-closed: ball topmost, main hidden")

    # 分支 3：晚自习外 → 球置底显示（主窗口不防水）
    state3 = get_state(cfg, datetime(2026, 1, 1, 12, 0))
    assert not state3.in_evening
    ctl._user_closed_main = False
    ctl._main_opened_by_user = False
    ctl._sync_windows(state3)
    assert ctl.float_ball.isVisible(), "ball visible outside evening"
    assert not ctl.main_window.isVisible(), "main hidden outside evening"
    results.append("outside: ball bottom, main hidden")

    # 分支 4：晚自习外但用户点开了主窗口 → 主窗口置底显示
    ctl._on_ball_clicked()
    ctl._sync_windows(state3)
    assert ctl.main_window.isVisible(), "main visible after user click (outside)"
    assert ctl.float_ball.isVisible(), "ball still visible outside"
    results.append("outside-user-open: main bottom + ball")

    # 分支 5：点开球后进入晚自习 → 自动恢复主窗口置顶
    ctl._sync_windows(state)  # in evening
    assert ctl.main_window.isVisible()
    assert not ctl.float_ball.isVisible()
    results.append("enter-evening-with-user-open: main topmost re-showed")

    # 清理
    ctl.main_window.close()
    ctl.float_ball.close()

    for r in results:
        print(f"[smoke-ctl] state-machine: {r} OK")
    print("[smoke-ctl] ALL PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())