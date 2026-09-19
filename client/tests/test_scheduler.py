# -*- coding: utf-8 -*-
"""scheduler 纯函数调度模块的单元测试（unittest）。

运行方式（在项目根目录）：
    python -m unittest client.tests.test_scheduler -v
"""

import os
import sys
import unittest
from datetime import datetime

# 使本测试无论从项目根或 client/ 目录运行都能导入 app 包
_TEST_DIR = os.path.dirname(os.path.abspath(__file__))
_CLIENT_DIR = os.path.dirname(_TEST_DIR)
if _CLIENT_DIR not in sys.path:
    sys.path.insert(0, _CLIENT_DIR)

from app.scheduler import (
    format_seconds,
    get_sound_actions,
    get_state,
    make_prev_key,
    parse_hhmm,
    to_hhmm,
)


def dt(h, m=0, s=0):
    """构造测试用 datetime（任意日期，只关心时刻）。"""
    return datetime(2026, 1, 1, h, m, s)


def base_config(**overrides):
    """默认配置：晚自习 18:30-22:00，语文/数学/英语三段无缝衔接。"""
    cfg = {
        "evening_start": "18:30",
        "evening_end": "22:00",
        "subjects": [
            {"name": "语文", "start": "18:30", "end": "19:20"},
            {"name": "数学", "start": "19:20", "end": "20:10"},
            {"name": "英语", "start": "20:10", "end": "21:00"},
        ],
        "idle_text": "课间休息",
        "sound": {
            "enabled": True,
            "near_seconds": 60,
            "near_audio": "near.wav",
            "near_enabled": True,
            "end_audio": "end.wav",
            "end_enabled": True,
        },
    }
    cfg.update(overrides)
    return cfg


class TestTimeConversion(unittest.TestCase):
    """时间字符串与秒互转。"""

    def test_parse_hhmm(self):
        self.assertEqual(parse_hhmm("00:00"), 0)
        self.assertEqual(parse_hhmm("18:30"), 66600)
        self.assertEqual(parse_hhmm("23:59"), 86340)

    def test_to_hhmm_roundtrip(self):
        for s in ("00:00", "06:15", "18:30", "23:59"):
            self.assertEqual(to_hhmm(parse_hhmm(s)), s)

    def test_to_hhmm_cross_midnight_mod(self):
        # 跨天有效结束秒（如 86640 = 次日 00:04）应显示 00:04
        self.assertEqual(to_hhmm(86640), "00:04")

    def test_format_seconds(self):
        self.assertEqual(format_seconds(0), "00:00:00")
        self.assertEqual(format_seconds(3661), "01:01:01")
        # 负数钳制为 0
        self.assertEqual(format_seconds(-5), "00:00:00")


class TestStateBasic(unittest.TestCase):
    """基础状态：段内 / 空档 / 晚自习外。"""

    def test_subject_inside(self):
        state = get_state(base_config(), dt(18, 45))
        self.assertTrue(state.in_evening)
        self.assertEqual(state.phase, "subject")
        self.assertIsNotNone(state.current_subject)
        self.assertEqual(state.current_subject.name, "语文")
        # 18:45 距 19:20 = 35 分钟
        self.assertEqual(state.remaining_sec, 35 * 60)

    def test_boundary_next_subject(self):
        # 19:20:00 整：语文段结束（半开区间不包含 end），数学段立即开始
        state = get_state(base_config(), dt(19, 20))
        self.assertEqual(state.phase, "subject")
        self.assertEqual(state.current_subject.name, "数学")
        self.assertEqual(state.remaining_sec, 50 * 60)

    def test_idle_gap(self):
        # 语文 18:30-19:00 与数学 19:20-20:00 之间存在 20 分钟空档
        cfg = base_config(
            subjects=[
                {"name": "语文", "start": "18:30", "end": "19:00"},
                {"name": "数学", "start": "19:20", "end": "20:00"},
            ]
        )
        state = get_state(cfg, dt(19, 10))
        self.assertTrue(state.in_evening)
        self.assertEqual(state.phase, "idle")
        self.assertIsNone(state.current_subject)
        self.assertIsNone(state.remaining_sec)

    def test_outside_before_evening(self):
        state = get_state(base_config(), dt(17, 0))
        self.assertFalse(state.in_evening)
        self.assertEqual(state.phase, "outside")
        self.assertEqual(state.next_event["type"], "evening_start")
        # 距 18:30 开始 = 1 小时 30 分
        self.assertEqual(state.next_event["seconds"], 5400)

    def test_outside_after_evening_no_cross(self):
        # 23:00 已过 22:00 结束 → 下一个晚自习是次日 18:30
        state = get_state(base_config(), dt(23, 0))
        self.assertEqual(state.phase, "outside")
        self.assertEqual(state.next_event["type"], "evening_start")
        self.assertEqual(state.next_event["seconds"], 3600 + 66600)  # 19.5h


class TestCrossMidnight(unittest.TestCase):
    """跨天兼容。"""

    EVENING_CROSS = base_config(
        evening_start="21:00",
        evening_end="01:00",
        subjects=[{"name": "语文", "start": "21:00", "end": "01:00"}],
    )

    def test_evening_cross_night_side(self):
        state = get_state(self.EVENING_CROSS, dt(23, 30))
        self.assertTrue(state.in_evening)
        self.assertEqual(state.phase, "subject")
        self.assertEqual(state.current_subject.name, "语文")
        # 距次日 01:00 结束 = 1 小时 30 分
        self.assertEqual(state.remaining_sec, 5400)

    def test_evening_cross_after_midnight(self):
        state = get_state(self.EVENING_CROSS, dt(0, 30))
        self.assertTrue(state.in_evening)
        self.assertEqual(state.phase, "subject")
        # 00:30 距 01:00 = 30 分钟（跨天结束点计算正确）
        self.assertEqual(state.remaining_sec, 1800)
        self.assertEqual(state.next_event["type"], "subject_end")
        self.assertEqual(state.next_event["seconds"], 1800)

    def test_evening_cross_outside_late(self):
        # 02:00 已过次日 01:00 → 不在晚自习内
        state = get_state(self.EVENING_CROSS, dt(2, 0))
        self.assertFalse(state.in_evening)
        self.assertEqual(state.phase, "outside")

    def test_subject_cross_midnight(self):
        # 晚自习跨天覆盖深夜 + 科目自身也跨天（22:00 → 次日 00:30）
        cfg = base_config(
            evening_start="18:30",
            evening_end="01:00",
            subjects=[{"name": "数学", "start": "22:00", "end": "00:30"}],
        )
        state = get_state(cfg, dt(0, 15))
        self.assertTrue(state.in_evening)
        self.assertEqual(state.phase, "subject")
        self.assertEqual(state.current_subject.name, "数学")
        self.assertEqual(state.remaining_sec, 900)  # 00:15 → 00:30
        self.assertEqual(state.next_event["seconds"], 900)


class TestSortedAndNextEvent(unittest.TestCase):
    """排序与下一事件。"""

    def test_sorted_subjects_by_start(self):
        cfg = base_config(
            subjects=[
                {"name": "英语", "start": "20:10", "end": "21:00"},
                {"name": "数学", "start": "19:20", "end": "20:10"},
                {"name": "语文", "start": "18:30", "end": "19:20"},
            ]
        )
        state = get_state(cfg, dt(18, 30))
        names = [s.name for s in state.sorted_subjects]
        self.assertEqual(names, ["语文", "数学", "英语"])

    def test_next_event_in_subject(self):
        state = get_state(base_config(), dt(19, 40))
        ne = state.next_event
        self.assertEqual(ne["type"], "subject_end")
        self.assertEqual(ne["seconds"], 30 * 60)  # 数学 20:10 结束
        self.assertEqual(ne["name"], "数学")

    def test_next_event_in_idle_gap(self):
        cfg = base_config(
            subjects=[
                {"name": "语文", "start": "18:30", "end": "19:00"},
                {"name": "数学", "start": "19:20", "end": "20:00"},
            ]
        )
        state = get_state(cfg, dt(19, 10))
        ne = state.next_event
        self.assertEqual(ne["type"], "subject_start")
        self.assertEqual(ne["seconds"], 10 * 60)
        self.assertEqual(ne["name"], "数学")

    def test_next_event_evening_end_when_no_more_subjects(self):
        # 最后一科目结束后、晚自习结束前的空档 → 下一事件为晚自习结束
        cfg = base_config(
            subjects=[{"name": "语文", "start": "18:30", "end": "21:30"}],
        )
        state = get_state(cfg, dt(21, 45))
        self.assertEqual(state.phase, "idle")
        ne = state.next_event
        self.assertEqual(ne["type"], "evening_end")
        self.assertEqual(ne["seconds"], 15 * 60)


class TestSoundActions(unittest.TestCase):
    """near / end 提示音触发。"""

    def _sounds(self, cfg, state, t, prev_key=""):
        actions, _next = get_sound_actions(cfg, state, t, prev_key)
        return [a["action"] for a in actions]

    def test_near_when_within_threshold(self):
        cfg = base_config()
        # 19:19，距语文段 19:20 结束剩 60 秒，等于阈值 → 触发
        state = get_state(cfg, dt(19, 19))
        actions = self._sounds(cfg, state, 19 * 3600 + 19 * 60)
        self.assertIn("near", actions)

    def test_near_exact_threshold(self):
        # 剩余恰好等于阈值也触发
        state = get_state(base_config(), dt(19, 19))  # 剩 60s
        t = 19 * 3600 + 19 * 60
        actions = self._sounds(base_config(), state, t)
        self.assertIn("near", actions)

    def test_near_not_when_over_threshold(self):
        # 剩 61 秒 > 60 → 不触发 near
        state = get_state(base_config(), dt(19, 18, 59))
        t = 19 * 3600 + 18 * 60 + 59
        actions = self._sounds(base_config(), state, t)
        self.assertNotIn("near", actions)

    def test_near_disabled(self):
        cfg = base_config()
        cfg["sound"]["near_enabled"] = False
        state = get_state(cfg, dt(19, 19))
        t = 19 * 3600 + 19 * 60
        actions = self._sounds(cfg, state, t)
        self.assertNotIn("near", actions)

    def test_sound_total_disabled(self):
        cfg = base_config()
        cfg["sound"]["enabled"] = False
        state = get_state(cfg, dt(19, 19))
        # 即使处于可 near 状态也静默
        actions = self._sounds(cfg, state, 19 * 3600 + 19 * 60)
        self.assertEqual(actions, [])

    def test_end_when_crossing_end(self):
        cfg = base_config()
        t1 = 19 * 3600 + 19 * 60          # 19:19（距离结束 60s，段内）
        t2 = 19 * 3600 + 20 * 60          # 19:20（语文结束，进入数学）
        s1 = get_state(cfg, dt(19, 19))
        s2 = get_state(cfg, dt(19, 20))
        prev = make_prev_key(s1, t1)
        # 上一 tick 仍在段内、本 tick 已跨过结束点 → 播放一次 end
        actions, key2 = get_sound_actions(cfg, s2, t2, prev)
        self.assertEqual([a["action"] for a in actions], ["end"])
        self.assertEqual(key2, make_prev_key(s2, t2))

    def test_no_end_on_initial_tick(self):
        # prev_key 为空（首次 tick / 刚启动）→ 即使已到结束也不播放 end
        cfg = base_config()
        t = 19 * 3600 + 22 * 60  # 已过语文结束
        state = get_state(cfg, dt(19, 22))
        actions = self._sounds(cfg, state, t)
        self.assertEqual(actions, [])

    def test_end_not_before_end_point(self):
        # 上一 tick 与本次 tick 都还在段内、未越过结束点 → 不触发 end
        cfg = base_config()
        t1 = 19 * 3600 + 19 * 60          # 19:19（语文段，剩 60s）
        t2 = 19 * 3600 + 19 * 60 + 30     # 19:19:30（仍在语文段内）
        s1 = get_state(cfg, dt(19, 19))
        s2 = get_state(cfg, dt(19, 19, 30))
        prev = make_prev_key(s1, t1)
        actions = self._sounds(cfg, s2, t2, prev)
        # 距离结束尚早 → 不播放 end（但可能播放 near）
        self.assertNotIn("end", actions)

    def test_end_reset_after_segment_switch(self):
        # 跨段后（19:21 已在数学段）：prev 已更新为新段，不重复/误触发 end
        cfg = base_config()
        t1 = 19 * 3600 + 21 * 60          # 19:21 数学段
        t2 = 19 * 3600 + 21 * 60 + 30     # 19:21:30 仍在数学段
        s1 = get_state(cfg, dt(19, 21))
        s2 = get_state(cfg, dt(19, 21, 30))
        prev = make_prev_key(s1, t1)
        actions = self._sounds(cfg, s2, t2, prev)
        # 数学段结束点 20:10 远未到达 → 不触发 end
        self.assertNotIn("end", actions)

    def test_end_when_crossing_subject_with_gap(self):
        # 科目 18:30-19:00 后有间隙，19:00:30 越过结束 → 只播放 end 不播放 near
        cfg = base_config(
            subjects=[
                {"name": "语文", "start": "18:30", "end": "19:00"},
                {"name": "数学", "start": "19:30", "end": "20:10"},
            ]
        )
        t1 = 18 * 3600 + 59 * 60  # 18:59:00（语文段内，剩 60s）
        t2 = 19 * 3600            # 19:00:00（语文结束）
        s1 = get_state(cfg, dt(18, 59))
        s2 = get_state(cfg, dt(19, 0))
        prev = make_prev_key(s1, t1)
        actions, _ = get_sound_actions(cfg, s2, t2, prev)
        actions = [a["action"] for a in actions]
        self.assertEqual(actions, ["end"])

    def test_end_enabled_false(self):
        cfg = base_config()
        cfg["sound"]["end_enabled"] = False
        t1 = 19 * 3600 + 19 * 60
        t2 = 19 * 3600 + 20 * 60
        s1 = get_state(cfg, dt(19, 19))
        s2 = get_state(cfg, dt(19, 20))
        prev = make_prev_key(s1, t1)
        actions = [
            a["action"]
            for a in get_sound_actions(cfg, s2, t2, prev)[0]
        ]
        self.assertNotIn("end", actions)


class TestNextEventCrossMidnightGap(unittest.TestCase):
    """跨天凌晨空档的 next_event 视角（统一「>= t 最小等价时刻」）。"""

    CFG_A = base_config(
        evening_start="21:00",
        evening_end="01:00",
        subjects=[
            {"name": "第一段", "start": "21:00", "end": "22:00"},
            {"name": "第二段", "start": "22:00", "end": "23:00"},
            {"name": "第三段", "start": "23:00", "end": "00:00"},
        ],
    )

    def test_scene_a_after_midnight_idle_next_is_evening_end(self):
        # 场景 A：00:30 处于空档（21:00 起三科连排，00:00 已全部结束）。
        # 凌晨 t 已回绕，昨夜科目应被当作「已过去」而非未来事件，
        # 下一事件应为 01:00 晚自习结束（约 30 分钟后）。
        state = get_state(self.CFG_A, dt(0, 30))
        self.assertEqual(state.phase, "idle")
        ne = state.next_event
        self.assertEqual(ne["type"], "evening_end")
        self.assertEqual(ne["seconds"], 30 * 60)
        self.assertEqual(ne["at"], "01:00")

    def test_scene_b_before_midnight_finds_cross_midnight_subject(self):
        # 场景 B：23:30 空档，存在 00:00-00:40 跨天科目。
        # 旧实现对 start_sec <= t 的科目直接跳过，会漏掉凌晨跨天科目；
        # 修复后应选中该科目开始（约 30 分钟后）。
        cfg = base_config(
            evening_start="21:00",
            evening_end="01:00",
            subjects=[
                {"name": "晚间", "start": "23:00", "end": "23:30"},
                {"name": "跨午夜", "start": "00:00", "end": "00:40"},
            ],
        )
        state = get_state(cfg, dt(23, 30))
        self.assertEqual(state.phase, "idle")
        ne = state.next_event
        self.assertEqual(ne["type"], "subject_start")
        self.assertEqual(ne["name"], "跨午夜")
        self.assertEqual(ne["seconds"], 30 * 60)
        self.assertEqual(ne["at"], "00:00")

    def test_scene_c_normal_gap_not_regressed(self):
        # 场景 C：普通不跨天晚自习内空档 → 下一事件为下一科目开始
        cfg = base_config(
            subjects=[
                {"name": "语文", "start": "18:30", "end": "19:00"},
                {"name": "数学", "start": "19:20", "end": "20:00"},
            ]
        )
        state = get_state(cfg, dt(19, 10))
        ne = state.next_event
        self.assertEqual(ne["type"], "subject_start")
        self.assertEqual(ne["name"], "数学")
        self.assertEqual(ne["seconds"], 10 * 60)

    def test_scene_c2_normal_gap_after_last_subject(self):
        # 场景 C 补充：最后一科目结束后、晚自习结束前的空档 → 晚自习结束
        cfg = base_config(subjects=[{"name": "语文", "start": "18:30", "end": "21:30"}])
        state = get_state(cfg, dt(21, 45))
        ne = state.next_event
        self.assertEqual(ne["type"], "evening_end")
        self.assertEqual(ne["seconds"], 15 * 60)

    def test_scene_d_early_morning_first_segment_is_subject(self):
        # 场景 D：00:15 落在凌晨第一段科目 00:00-00:40 内 → 处于 subject 相位
        cfg = base_config(
            evening_start="22:00",
            evening_end="02:00",
            subjects=[{"name": "凌晨段", "start": "00:00", "end": "00:40"}],
        )
        state = get_state(cfg, dt(0, 15))
        self.assertEqual(state.phase, "subject")
        self.assertIsNotNone(state.current_subject)
        self.assertEqual(state.current_subject.name, "凌晨段")
        self.assertEqual(state.remaining_sec, 25 * 60)
        ne = state.next_event
        self.assertEqual(ne["type"], "subject_end")
        self.assertEqual(ne["seconds"], 25 * 60)


class TestSoundEndAtMidnight(unittest.TestCase):
    """结束时刻恰为 00:00（有效结束秒折算 86400）时 end 提示音触发。"""

    CFG = base_config(
        evening_start="22:00",
        evening_end="01:00",
        subjects=[{"name": "夜自习", "start": "23:00", "end": "00:00"}],
    )

    def test_end_fires_once_when_crossing_exact_midnight(self):
        # prev tick 23:59:59 → now 00:00:00：now 回绕到 0，旧判定恒假。
        # 修复后应恰好触发一次 end，并返回空 prev_key（下一时刻不再重复）。
        s1 = get_state(self.CFG, dt(23, 59, 59))
        t1 = 23 * 3600 + 59 * 60 + 59
        prev = make_prev_key(s1, t1)

        s2 = get_state(self.CFG, dt(0, 0, 0))
        actions, key2 = get_sound_actions(self.CFG, s2, 0, prev)
        self.assertEqual([a["action"] for a in actions], ["end"])
        # 00:00:00 已非 subject（半开区间不含结束点）→ 新 key 为空
        self.assertEqual(key2, "")

    def test_end_not_repeated_next_tick(self):
        # now=00:00:01：使用上一 tick 返回的 key2（已更新为 ""，链式无状态），
        # 不应再次播放 end。
        s1 = get_state(self.CFG, dt(23, 59, 59))
        t1 = 23 * 3600 + 59 * 60 + 59
        key1 = make_prev_key(s1, t1)
        s2 = get_state(self.CFG, dt(0, 0, 0))
        _, key2 = get_sound_actions(self.CFG, s2, 0, key1)
        s3 = get_state(self.CFG, dt(0, 0, 1))
        actions, _ = get_sound_actions(self.CFG, s3, 1, key2)
        self.assertNotIn("end", [a["action"] for a in actions])

    def test_end_fires_normally_without_wraparound(self):
        # 不跨天：正常越过科目结束点仍要触发（回归保护）
        cfg = base_config()
        t1 = 19 * 3600 + 19 * 60          # 19:19
        t2 = 19 * 3600 + 20 * 60          # 19:20
        s1 = get_state(cfg, dt(19, 19))
        s2 = get_state(cfg, dt(19, 20))
        prev = make_prev_key(s1, t1)
        actions, _ = get_sound_actions(cfg, s2, t2, prev)
        self.assertEqual([a["action"] for a in actions], ["end"])


if __name__ == "__main__":
    unittest.main()