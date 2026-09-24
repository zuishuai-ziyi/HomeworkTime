# -*- coding: utf-8 -*-
"""主程序组装（阶段 1 核心 + 阶段 2 本地化能力 + 阶段 5 网络同步）。

AppController 负责组装 QApplication 外的全部组件，并驱动「每秒一 tick」
的窗口状态机：

- 晚自习内 & 未用户关闭    → 主窗口置顶显示，悬浮球隐藏；
- 晚自习内 & 用户已关闭(×) → 悬浮球置顶显示，主窗口隐藏；
- 晚自习外                  → 悬浮球置底显示；若主窗口被用户点开则置底
                              显示并提示「不在晚自习时间」；
- 退出晚自习瞬间            → 主窗口自动收起为置底悬浮球。

阶段 2 集成：
- Logger 按天滚动本地日志（替代 basicConfig）；
- SingleInstance 单实例守卫（非主实例唤醒既有实例后退出）；
- 首次运行引导 GuideWindow（server_base_url/client_token 为空时）；
- Autostart 开机自启应用；
- 系统托盘 Tray（显示主窗口 / 打开配置 / 自启勾选 / 退出）；
- 配置窗口 ConfigWindow（允许本地修改时从悬浮球右键/托盘打开）。

阶段 5 集成（网络同步，与 UI 1s tick 分离的独立 QTimer）：
- ApiClient 心跳 + 轮询（间隔 poll_interval_sec，默认 10s）；
- 恢复在线 → 离线队列补传 + 立即拉取配置；
- 音频保障：业务配置中 sound.near_audio/end_audio 变化或启动时，
  在后台线程 ensure_audio（下载/校验），完成后再启用播放，找不到回退内置。

远程更新集成（Updater，全量包替换式）：
- 心跳响应携带服务端已发布更新 → Updater 后台下载/校验/解压暂存；
- 每秒 tick 判定生效时机：到管理端指定生效时间且不在晚自习时段时，
  拉起 update.bat 并退出进程，由脚本完成替换与重启；
- 启动时 startup_check 处理上次应用结果（成功清理 / 失败计数保护）。

提示音：每 tick 调用 scheduler.get_sound_actions，播放 near/end。
透明度：读取业务配置 opacity.main / opacity.ball 应用到窗口。
"""

from __future__ import annotations

import sys
import threading
import time
from datetime import datetime
from typing import Optional, Tuple

from PyQt5.QtCore import QTimer
from PyQt5.QtWidgets import QApplication, QDialog

from . import autostart
from .config import AppConfig, LocalConfig, load_pending
from .logger import get_logger
from .scheduler import ScheduleState, get_sound_actions, get_state
from .single_instance import SingleInstance
from .windows.config_window import ConfigWindow
from .windows.float_ball import FloatBall
from .windows.guide_window import GuideWindow
from .windows.main_window import MainWindow
from .windows.tray import Tray

logger = get_logger("main")


def _tick_interval_ms() -> int:
    """默认 1 秒一次 tick。"""
    return 1000


class AppController:
    """客户端主控制器。"""

    def __init__(
        self,
        app: QApplication,
        local_config: Optional[LocalConfig] = None,
        app_config: Optional[AppConfig] = None,
        audio_player=None,
        single_instance: Optional[SingleInstance] = None,
        create_tray: bool = True,
    ) -> None:
        self.app = app
        self.local_config = local_config or LocalConfig()
        self.app_config = app_config or AppConfig()
        self.single_instance = single_instance
        self.tray: Optional[Tray] = None

        cfg = self.app_config.data

        from .audio import AudioPlayer  # 延迟导入，避免构造时依赖平台

        self.audio = audio_player or AudioPlayer()

        self.main_window = MainWindow(
            idle_text=cfg.get("idle_text", "课间休息"),
            warn_seconds=(
                (cfg.get("sound") or {}).get("near_seconds", 60) or 60
            ),
        )
        self.float_ball = FloatBall(
            ball_size=int(self.local_config.get("ball_size", 64))
        )

        # 窗口状态
        self._prev_key: str = ""               # 提示音调度链（上一 tick 标识）
        self._user_closed_main = False         # 用户点击了主窗口 ×
        self._main_opened_by_user = False      # 用户从悬浮球点开了主窗口

        # 信号接线
        self.main_window.closed_to_ball.connect(self._on_main_closed)
        self.float_ball.clicked.connect(self._on_ball_clicked)
        self.float_ball.open_config_requested.connect(self._on_open_config)
        self.float_ball.pos_changed.connect(self._on_ball_pos_changed)
        self.app_config.add_listener(self._on_config_changed)

        # 阶段 5：网络同步（心跳/轮询/离线补传/音频保障）
        self._setup_network()

        # 悬浮球位置恢复
        self.float_ball.restore_position(self.local_config.get("ball_pos"))

        # 透明度（业务配置优先）
        self._apply_opacities(cfg)

        # 单实例消息（"show" → 弹出主窗口）
        if single_instance is not None:
            single_instance.new_message.connect(self._on_single_message)

        # 托盘
        if create_tray:
            self._setup_tray()

        # 定时器
        self.timer = QTimer()
        self.timer.timeout.connect(self._tick)
        self.timer.start(_tick_interval_ms())

    # ------------------------------------------------------------------
    # 阶段 5：网络同步（独立 QTimer，与 UI 1s tick 分离）
    # ------------------------------------------------------------------
    def _setup_network(self) -> None:
        """构造 ApiClient 与 Updater，并按 poll_interval_sec 启动网络 tick。

        启动后立即执行一次网络 tick（首个心跳/拉取 + 音频保障）。
        """
        from .api_client import ApiClient
        from .updater import Updater

        self.api_client = ApiClient(self.local_config, self.app_config)
        #: 远程更新控制器（启动即检查上次应用结果）
        self.updater = Updater()
        try:
            self.updater.startup_check()
        except Exception as exc:
            logger.warning("更新启动检查异常: %s", exc)
        #: 上一轮网络 tick 的在线状态；None 表示尚未确认（首 tick 触发日志）
        self._last_online: Optional[bool] = None
        #: 已保障过的音频文件名元组（变化时才重新 ensure_audio）
        self._ensured_audio: Tuple[str, str] = ()
        #: 离线补传失败节流状态（失败日志最多每 5 分钟记一条，避免每 tick 刷屏）
        self._sync_failed = False
        self._sync_log_at = 0.0

        self._net_timer = QTimer()
        self._net_timer.timeout.connect(self._network_tick)
        interval_ms = self._poll_interval_ms()
        self._net_timer.start(interval_ms)
        logger.info("网络同步定时器已启动（间隔 %d ms）", interval_ms)
        self._network_tick()  # 启动立即执行一次

    def _poll_interval_ms(self) -> int:
        try:
            sec = max(1, int(self.local_config.get("poll_interval_sec", 10) or 10))
        except (TypeError, ValueError):
            sec = 10
        return sec * 1000

    def _network_tick(self) -> None:
        """一次网络 tick：先 heartbeat（内部按 version 判断是否 poll）。

        - 在线：只要存在待同步队列即尝试补传（幂等，见 _sync_pending_if_present）；
                 从离线恢复时再额外立即拉取配置；并检查音频保障。
        - 离线：仅状态变化时记录日志（不刷屏）。
        """
        client = getattr(self, "api_client", None)
        if client is None:
            return
        if not client.base_url or not client.token:
            self._set_online_state(False)
            return
        # 心跳上报前刷新「待生效更新版本」（供后台观察设备更新进度）
        try:
            client.pending_update_version = self.updater.pending_version()
        except Exception:
            client.pending_update_version = None
        try:
            ok = client.heartbeat()
        except Exception as exc:
            logger.warning("网络 tick 心跳异常: %s", exc)
            ok = False
        if ok:
            was_offline = self._last_online is not True
            self._set_online_state(True)
            # 补传：只要心跳成功且队列非空就尝试（幂等）。不再仅限「刚恢复
            # 在线」这一瞬间——否则在线期间写入队列、或一次瞬时失败后被判定
            # 为仍在线，都会永远错过补传机会（was_offline 判定不可靠）。
            self._sync_pending_if_present()
            if was_offline:
                # 恢复在线：先补传（保序），再立即拉取最新配置
                try:
                    self.api_client.poll()
                except Exception as exc:
                    logger.warning("恢复后立即拉取配置异常: %s", exc)
            # 远程更新：按心跳下发的更新信息推进（下载/校验/解压/同步生效时间）
            try:
                self.updater.evaluate(client.server_update, client)
            except Exception as exc:
                logger.warning("远程更新评估异常: %s", exc)
            self._ensure_audio_if_needed()
        else:
            self._set_online_state(False)

    def _sync_pending_if_present(self) -> None:
        """存在待同步队列时尝试补传（幂等）；失败日志做节流。

        - 队列为空 → 无操作；
        - 补传成功 → 若此前处于失败态则记一条恢复日志；
        - 补传失败 → 保留队列等待下次 tick 重试，失败日志最多每 5 分钟
          记一条，避免离线期间每 tick 刷屏。
        """
        from .api_client import should_sync_pending

        try:
            has_pending = should_sync_pending(True, len(load_pending()))
        except Exception as exc:
            logger.warning("读取待同步队列失败: %s", exc)
            return
        if not has_pending:
            return
        try:
            ok = self.api_client.sync_pending(log_failure=False)
        except Exception as exc:
            ok = False
            reason = str(exc)
        else:
            reason = "补传未完成"
        if ok:
            if self._sync_failed:
                logger.info("离线配置补传恢复正常")
            self._sync_failed = False
            self._sync_log_at = 0.0
            return
        self._sync_failed = True
        now = time.monotonic()
        if now - self._sync_log_at >= 300:  # 失败日志节流：最多每 5 分钟一条
            logger.warning("离线配置补传失败，将自动重试: %s", reason)
            self._sync_log_at = now

    def _set_online_state(self, online: bool) -> None:
        """更新在线状态；仅状态变化时记录日志，避免离线时刷屏。"""
        if self._last_online != online:
            logger.info("服务器连接状态: %s", "在线" if online else "离线")
            self._last_online = online
        else:
            self._last_online = online

    def _ensure_audio_if_needed(self) -> None:
        """业务配置中 near/end 音频文件名变化（或首次）时触发后台保障。"""
        cfg = self.app_config.data or {}
        sound = cfg.get("sound") or {}
        names = (
            str(sound.get("near_audio") or "near.wav"),
            str(sound.get("end_audio") or "end.wav"),
        )
        if names == self._ensured_audio:
            return
        self._ensured_audio = names
        threading.Thread(
            target=self._ensure_audio_worker, args=(names,), daemon=True
        ).start()

    def _ensure_audio_worker(self, names: Tuple[str, str]) -> None:
        """后台线程：逐条 ensure_audio（下载/校验），完成后启用播放。"""
        for name in names:
            try:
                path = self.api_client.ensure_audio(name)
                if path:
                    logger.info("音频保障完成: %s -> %s", name, path)
                else:
                    logger.warning("音频不可用，回退内置: %s", name)
            except Exception as exc:
                logger.warning("音频保障失败(%s): %s", name, exc)
        # 保障流程结束（下载成功或回退内置）后启用播放
        try:
            self.audio.set_enabled(True)
        except Exception:
            pass

    # ------------------------------------------------------------------
    # 远程更新
    # ------------------------------------------------------------------
    def _maybe_apply_update(self, state: ScheduleState, now: datetime) -> bool:
        """判定并应用远程更新；应用成功则退出进程（由更新脚本重启）。

        时机条件由 updater.should_apply 纯函数决定：更新包就绪、未超失败
        上限、到管理端指定生效时间、且当前不在晚自习时段（晚自习内顺延，
        结束后下一次 tick 立即执行）。
        """
        updater = getattr(self, "updater", None)
        if updater is None:
            return False
        try:
            applied = updater.maybe_apply(now, state.in_evening)
        except Exception as exc:
            logger.exception("远程更新应用异常: %s", exc)
            return False
        if applied:
            logger.info(
                "开始应用远程更新 v%s，程序退出后由更新脚本完成替换并重启",
                updater.state.get("target_version") or "?",
            )
            self.app.quit()
            return True
        return False

    # ------------------------------------------------------------------
    # 托盘
    # ------------------------------------------------------------------
    def _setup_tray(self) -> None:
        try:
            tray = Tray()
            tray.set_callbacks(
                show_main=self._on_ball_clicked,
                open_config=self._on_open_config,
                server_settings=self._on_server_settings,
                quit_app=self._on_quit_app,
                autostart_toggled=self._on_autostart_toggled,
            )
            tray.set_autostart_checked(
                bool(self.local_config.get("autostart", False))
            )
            tray.show()
            self.tray = tray
        except Exception as exc:
            logger.warning("系统托盘创建失败，已跳过: %s", exc)
            self.tray = None

    def _on_autostart_toggled(self, checked: bool) -> None:
        """托盘自启勾选 → 应用注册表 + 持久化本地配置。"""
        try:
            autostart.set_autostart(bool(checked))
            self.local_config.set("autostart", bool(checked))
        except Exception as exc:
            logger.exception("开机自启切换失败: %s", exc)

    def _on_single_message(self, message: str) -> None:
        """单实例唤醒消息 → 弹出主窗口。"""
        text = (message or "").strip().lower()
        if "show" in text:
            logger.info("收到单实例唤醒消息，弹出主窗口")
            self._on_ball_clicked()

    def _on_quit_app(self) -> None:
        """托盘退出 → 确认后退出。"""
        from .windows.confirm_dialog import ConfirmDialog

        if ConfirmDialog.ask(None, "确定要退出作业时间提醒吗？"):
            logger.info("用户从托盘退出程序")
            self.app.quit()

    # ------------------------------------------------------------------
    # 启动：立即执行一次 tick + 显示
    # ------------------------------------------------------------------
    def start(self) -> None:
        self._tick()
        self.app.setQuitOnLastWindowClosed(False)  # 窗口藏起时进程不退出

    def shutdown(self) -> None:
        """进程退出前的清理（释放单实例占位、停定时器）。"""
        try:
            self.timer.stop()
        except Exception:
            pass
        try:
            self._net_timer.stop()
        except Exception:
            pass
        if self.tray is not None:
            try:
                self.tray.close()
            except Exception:
                pass
        if self.single_instance is not None:
            try:
                self.single_instance.destroy()
            except Exception as exc:
                logger.warning("单实例释放失败: %s", exc)

    # ------------------------------------------------------------------
    # 每秒调度
    # ------------------------------------------------------------------
    def _tick(self) -> None:
        now = datetime.now()
        cfg = self.app_config.data
        state = get_state(cfg, now)
        t = now.hour * 3600 + now.minute * 60 + now.second

        # 0) 远程更新：到生效时间且不在晚自习 → 拉起更新脚本并退出重启
        if self._maybe_apply_update(state, now):
            return

        # 1) 提示音
        self._play_sounds(cfg, state, t)

        # 2) 主窗口展示元数据
        self.main_window.set_idle_text(cfg.get("idle_text", "课间休息"))
        if cfg.get("evening_start") and cfg.get("evening_end"):
            self.main_window.set_evening_range(
                f"{cfg['evening_start']} — {cfg['evening_end']}"
            )
        sound_cfg = cfg.get("sound") or {}
        if sound_cfg.get("near_seconds"):
            self.main_window.set_warn_seconds(int(sound_cfg["near_seconds"]))

        # 3) 窗口状态机
        self._sync_windows(state)

        # 4) 透明度（阶段 2 配置变更时同样会触发）
        self._apply_opacities(cfg)

    def _play_sounds(self, cfg, state: ScheduleState, t: int) -> None:
        try:
            actions, self._prev_key = get_sound_actions(cfg, state, t, self._prev_key)
        except Exception as exc:
            logger.exception("提示音调度出错: %s", exc)
            self._prev_key = ""
            return
        for action in actions:
            self.audio.play(action.get("audio", ""))

    # ------------------------------------------------------------------
    # 窗口状态机
    # ------------------------------------------------------------------
    def _sync_windows(self, state: ScheduleState) -> None:
        if state.in_evening:
            # 晚自习内：主窗口置顶；用户主动关闭过则改为置顶悬浮球
            self._main_opened_by_user = False
            if self._user_closed_main:
                self.float_ball.set_topmost(True)
                self.float_ball.show()
                self.main_window.hide()
            else:
                self.main_window.set_bottom_mode(False)
                self.main_window.refresh(state)
                self.main_window.show()
                self.float_ball.hide()
        else:
            # 晚自习外：悬浮球置底；若主窗口正被用户打开则置底显示
            is_main_open = (
                self._main_opened_by_user and self.main_window.isVisible()
            )
            self.float_ball.set_topmost(False)
            self.float_ball.show()
            if is_main_open:
                self.main_window.set_bottom_mode(True)
                self.main_window.refresh(state)
                self.main_window.show()
            else:
                self.main_window.hide()

    # ------------------------------------------------------------------
    # 信号回调
    # ------------------------------------------------------------------
    def _on_main_closed(self) -> None:
        """用户点击主窗口 ×：隐藏主窗口，今晚转置顶悬浮球。"""
        self._user_closed_main = True
        self._main_opened_by_user = False
        self.main_window.hide()
        self.float_ball.set_topmost(True)
        self.float_ball.show()

    def _on_ball_clicked(self) -> None:
        """悬浮球单击 / 托盘显示：打开主窗口（晚自习外时由下一 tick 置底）。"""
        self._user_closed_main = False
        self._main_opened_by_user = True
        try:
            state = get_state(self.app_config.data, datetime.now())
            self.main_window.refresh(state)
        except Exception as exc:
            logger.exception("打开主窗口刷新失败: %s", exc)
        self.main_window.set_bottom_mode(not getattr(state, "in_evening", True))
        self.main_window.show()

    def _on_open_config(self) -> None:
        """悬浮球右键确认 / 托盘「打开配置」→ 打开配置窗口（模态）。"""
        try:
            dialog = ConfigWindow(
                self.app_config,
                self.local_config,
                api_client=getattr(self, "api_client", None),
            )
            dialog.exec_()
        except Exception as exc:
            logger.exception("打开配置窗口失败: %s", exc)

    def _on_server_settings(self) -> None:
        """托盘「服务器设置」→ 复用首次引导窗口（模态）配置 URL/Token。

        引导被跳过（guide_dismissed=True）后，唯一的服务器配置入口。
        保存成功后：
        - 写回 local_config（已经在 GuideWindow 内完成，但为幂等此处不重写）；
        - 立即调用 ApiClient.reload_credentials() 让下一次网络 tick 命中
          新地址（构造时缓存的 base_url/token 不会自动更新）；
        - 把 guide_dismissed 置回 False，恢复正常引导语义（下次启动若
          url/token 又被清空仍能自动弹引导）。
        - 日志记录新地址，token 仅打印前 4 位 + ***（安全考虑）。
        """
        try:
            dialog = GuideWindow(
                server_base_url=self.local_config.get("server_base_url") or "",
                client_token=self.local_config.get("client_token") or "",
            )
            if dialog.exec_() != QDialog.Accepted:
                logger.info("用户在托盘『服务器设置』中取消，未变更配置")
                return
            url, token = dialog.current_values()
            # 1) 写回本地配置（GuideWindow 内 _run_guide_if_needed 路径
            # 也会写，但托盘入口需要兼容「首次写」/「覆盖写」两种语义）
            try:
                self.local_config.set("server_base_url", url)
                self.local_config.set("client_token", token)
            except Exception as exc:
                logger.warning("服务器设置写回失败: %s", exc)
                return
            # 2) 退出离线模式：保证后续 url/token 被清空时引导仍会弹出
            try:
                self.local_config.set("guide_dismissed", False)
            except Exception:
                pass
            # 3) 热更新 ApiClient 凭据：让下一个网络 tick 即用新地址
            client = getattr(self, "api_client", None)
            if client is not None:
                try:
                    client.reload_credentials(self.local_config)
                except Exception as exc:
                    logger.warning("ApiClient 凭据热更新失败: %s", exc)
            # 4) 日志：地址明文，token 仅前 4 位 + ***（不打印全量）
            token_preview = (token[:4] + "***") if token else "(空)"
            logger.info(
                "服务器设置已更新: server=%s token=%s",
                url or "(空)",
                token_preview,
            )
        except Exception as exc:
            logger.exception("打开服务器设置失败: %s", exc)

    def _on_ball_pos_changed(self, pos) -> None:
        """悬浮球位置变化 → 持久化到 local_config。"""
        try:
            self.local_config.set(
                "ball_pos", {"x": int(pos.x()), "y": int(pos.y())}
            )
        except Exception as exc:
            logger.warning("悬浮球位置持久化失败: %s", exc)

    # ------------------------------------------------------------------
    # 配置变更 / 透明度
    # ------------------------------------------------------------------
    def _on_config_changed(self, cfg: dict) -> None:
        """业务配置变更（阶段 2 起可能来自配置窗口/服务器下发）。"""
        self._apply_opacities(cfg)
        self.main_window.set_idle_text(cfg.get("idle_text", "课间休息"))
        try:
            self.float_ball.set_ball_size(
                int(self.local_config.get("ball_size", 64))
            )
        except (TypeError, ValueError):
            pass

    def _apply_opacities(self, cfg: dict) -> None:
        op = cfg.get("opacity") or {}
        self.main_window.setWindowOpacity(float(op.get("main", 0.85)))
        self.float_ball.setWindowOpacity(float(op.get("ball", 0.70)))


# ---------------------------------------------------------------------------
# 启动流程
# ---------------------------------------------------------------------------


def _needs_guide(local_config: LocalConfig) -> bool:
    """server_base_url 或 client_token 为空 → 需要首次运行引导。

    例外：用户已在引导窗口里选择「跳过（离线模式）」并写入
    ``guide_dismissed=True`` 时不再弹出，避免每次启动都骚扰；
    此时若用户想重新配置服务器，可通过托盘「服务器设置」打开。
    """
    if bool(local_config.get("guide_dismissed")):
        return False
    url = (local_config.get("server_base_url") or "").strip()
    token = (local_config.get("client_token") or "").strip()
    return not url or not token


def _run_guide_if_needed(local_config: LocalConfig) -> bool:
    """按需弹出首次运行引导。

    - 保存并进入（Accepted）→ 写回 URL/Token + 把 guide_dismissed 置回
      False（保证语义干净），返回 True；
    - 跳过（Rejected）→ 写入 guide_dismissed=True + 写日志「已记住跳过，
      可通过托盘『服务器设置』重新打开」，返回 False。
    """
    guide = GuideWindow(
        server_base_url=local_config.get("server_base_url") or "",
        client_token=local_config.get("client_token") or "",
    )
    if guide.exec_() == QDialog.Accepted:
        url, token = guide.current_values()
        try:
            local_config.set("server_base_url", url)
            local_config.set("client_token", token)
            # 保存成功 → 退出离线模式，保证 url/token 被清空时下次仍能
            # 自动弹引导。
            local_config.set("guide_dismissed", False)
            token_preview = (token[:4] + "***") if token else ""
            logger.info(
                "首次引导完成：server=%s token=%s",
                url or "",
                token_preview,
            )
        except Exception as exc:
            logger.warning("引导配置写回失败: %s", exc)
        return True
    # 跳过分支：明确写入「已忽略」标记，下次启动不再骚扰
    try:
        local_config.set("guide_dismissed", True)
    except Exception as exc:
        logger.warning("guide_dismissed 标记写入失败: %s", exc)
    logger.info(
        "用户跳过首次引导，进入离线模式；"
        "已记住跳过，可通过托盘菜单【服务器设置】重新打开"
    )
    return False


def run() -> int:
    """程序入口：单实例 → 引导 → 本地化 → 主控制器。"""
    from .logger import setup_logging  # 局部导入，尽快完成日志初始化

    setup_logging()

    app = QApplication(sys.argv)

    # 1) 单实例守卫（非主实例 → 唤醒既有实例后退出）
    single = SingleInstance()
    if not single.is_primary:
        logger.info("检测到已有实例，通知其弹出主窗口后退出")
        single.notify("show")
        single.destroy()
        return 0

    # 2) 加载本机配置
    local_config = LocalConfig()

    # 3) 首次运行引导（离线允许跳过）
    if _needs_guide(local_config):
        _run_guide_if_needed(local_config)

    # 4) 应用开机自启（autostart 变化由托盘勾选即时应用）
    try:
        autostart.set_autostart(bool(local_config.get("autostart", True)))
    except Exception as exc:
        logger.warning("开机自启应用失败: %s", exc)

    # 5) 主控制器
    controller = AppController(app, local_config=local_config, single_instance=single)
    controller.start()
    try:
        code = app.exec_()
    finally:
        controller.shutdown()
    return code


if __name__ == "__main__":
    sys.exit(run())