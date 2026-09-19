# -*- coding: utf-8 -*-
"""阶段 2 UI 无头冒烟测试。

验证 offscreen 平台下可安全实例化：
- GuideWindow（首次运行引导）；
- ConfigWindow（允许编辑 / 管理员禁用两种形态）；
- Tray（offscreen 下 QSystemTrayIcon 可创建）；
- SingleInstance 单实例守卫（同进程二次创建/重建）。

运行方式：
    python client/tests/smoke_stage2.py
"""

import os
import sys
import tempfile

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

_TEST_DIR = os.path.dirname(os.path.abspath(__file__))
_CLIENT_DIR = os.path.dirname(_TEST_DIR)
if _CLIENT_DIR not in sys.path:
    sys.path.insert(0, _CLIENT_DIR)

from PyQt5.QtCore import QCoreApplication  # noqa: E402
from PyQt5.QtWidgets import QApplication  # noqa: E402

from app.config import DEFAULT_CONFIG_PATH, AppConfig, LocalConfig  # noqa: E402
from app.single_instance import SingleInstance  # noqa: E402
from app.windows.config_window import ConfigWindow  # noqa: E402
from app.windows.guide_window import GuideWindow  # noqa: E402
from app.windows.tray import Tray  # noqa: E402

_results = []


def main() -> int:
    app = QApplication.instance() or QApplication(sys.argv)
    tmp = tempfile.mkdtemp(prefix="ht_smoke2_")

    local = LocalConfig(path=os.path.join(tmp, "local_config.json"))
    biz = AppConfig(
        cache_path=os.path.join(tmp, "business_config.json"),
        default_path=DEFAULT_CONFIG_PATH,
        load_now=True,
    )

    # ---- GuideWindow ----
    guide = GuideWindow("http://127.0.0.1:3000", "tok")
    assert guide.url_edit.text() == "http://127.0.0.1:3000"
    assert guide.token_edit.echoMode() != guide.token_edit.Normal  # 密码模式
    _results.append("GuideWindow construct OK (password echo, values)")
    guide.close()

    # ---- ConfigWindow 可编辑形态 ----
    w1 = ConfigWindow(biz, local)
    assert w1.save_btn.isEnabled()
    assert w1.table.rowCount() == len(biz.data.get("subjects") or [])
    assert w1.ball_size_spin.value() == 64
    _results.append("ConfigWindow editable OK (subjects=%d)" % w1.table.rowCount())

    # 收集后的配置校验
    collect = w1._collect_config()
    ok, err = __import__(
        "app.windows.config_window", fromlist=["validate_subjects"]
    ).validate_subjects(collect.get("subjects") or [])
    assert ok, err
    _results.append("ConfigWindow collect+validate OK")

    # 不保存直接关闭
    w1.reject()
    w1.close()

    # ---- ConfigWindow 只读形态 ----
    biz.data["allow_local_edit"] = False
    w2 = ConfigWindow(biz, local)
    assert not w2.save_btn.isEnabled()
    assert not w2.allow_check.isEnabled()
    assert hasattr(w2, "readonly_label")
    _results.append("ConfigWindow readonly OK (all controls disabled)")
    w2.reject()
    w2.close()

    # 还原（避免影响后续测试）
    biz.data["allow_local_edit"] = True

    # ---- Tray ----
    tray = Tray()
    tray.set_callbacks(show_main=lambda: None, open_config=lambda: None)
    tray.set_autostart_checked(True)
    assert tray.autostart_action.isChecked()
    tray.show()
    assert tray.tray_icon is not None
    _results.append("Tray construct OK (offscreen QSystemTrayIcon)")
    tray.close()

    # ---- SingleInstance（逻辑层守卫） ----
    core = QCoreApplication.instance() or QCoreApplication([])
    si1 = SingleInstance("HTSmoke2Single")
    assert si1.is_primary, "first instance should be primary"
    got = []
    si1.new_message.connect(lambda m: got.append(m))
    si2 = SingleInstance("HTSmoke2Single")
    assert not si2.is_primary, "second instance should not be primary"
    for _ in range(20):
        core.processEvents()
    assert any("show" in m for m in got), "primary instance should receive 'show'"
    si2.destroy()
    si1.destroy()
    si3 = SingleInstance("HTSmoke2Single")
    assert si3.is_primary, "recreate after destroy should be primary"
    si3.destroy()
    _results.append("SingleInstance guard OK (2nd not primary, rebuild ok)")

    for r in _results:
        print("[smoke-stage2] %s" % r)
    print("[smoke-stage2] ALL PASS (%d)" % len(_results))
    return 0


if __name__ == "__main__":
    sys.exit(main())