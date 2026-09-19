# -*- coding: utf-8 -*-
"""时间调度模块（纯函数，无 Qt 依赖，可单测）。

核心模型：
- 所有 HH:MM 时间统一转换为「当天秒数」[0, 86400)。
- 跨天兼容：某个区间 end <= start 时视为跨天，有效结束点 = end + 86400。
- now 是本地 datetime；t = 当天秒数。
- 半小时开区间 [start, end)：包含 start、不包含 end。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

SECONDS_PER_DAY = 24 * 60 * 60

# ---------------------------------------------------------------------------
# 时间字符串与秒互转
# ---------------------------------------------------------------------------


def parse_hhmm(s: str) -> int:
    """'HH:MM' → 当天秒数（如 '18:30' → 66600）。"""
    hh, mm = s.split(":")
    return int(hh) * 3600 + int(mm) * 60


def to_hhmm(sec: int) -> str:
    """当天秒数 → 'HH:MM'（自动对 86400 取模，跨天时间显示次日时刻）。"""
    sec = int(sec) % SECONDS_PER_DAY
    return "%02d:%02d" % (sec // 3600, (sec % 3600) // 60)


def format_seconds(total: int) -> str:
    """秒数 → 'HH:MM:SS'（负数钳制为 0）。"""
    total = max(0, int(total))
    h, rem = divmod(total, 3600)
    m, s = divmod(rem, 60)
    return "%02d:%02d:%02d" % (h, m, s)


def now_sec_of_day(dt: datetime) -> int:
    """datetime → 当天秒数。"""
    return dt.hour * 3600 + dt.minute * 60 + dt.second


# ---------------------------------------------------------------------------
# 区间工具（含跨天）
# ---------------------------------------------------------------------------


def effective_end(start_sec: int, end_sec: int) -> int:
    """计算区间的有效结束秒：end <= start 视为跨天 → end + 86400。

    注意：该返回值是相对「开始时间所在基准日」的结束点。
    """
    if end_sec <= start_sec:
        return end_sec + SECONDS_PER_DAY
    return end_sec


def effective_end_for(t: int, start_sec: int, end_sec: int) -> int:
    """给定时刻 t（当天秒数），将该区间映射到 t 所在的「基准日」。

    跨天区间（end_eff > 86400）存在两个基准日：
    - t >= start_sec：t 在区间当天的部分，结束点 = end + 86400；
    - t < start_sec ：t 在区间的次日部分（如凌晨），结束点在当天即为
      原始 end_sec（不要再加 86400），否则剩余时间会被多算一整天。
    """
    end_eff = effective_end(start_sec, end_sec)
    if end_eff > SECONDS_PER_DAY and t < start_sec:
        return end_sec
    return end_eff


def in_range(t: int, start_sec: int, end_sec: int) -> bool:
    """判断 t 是否落在半开区间 [start, end) 内（end 可跨天）。

    不跨天：[start, end)；跨天：当天 [start, 86400) ∪ 次日 [0, end)。
    """
    end_eff = effective_end(start_sec, end_sec)
    if end_eff <= SECONDS_PER_DAY:
        return start_sec <= t < end_eff
    return (start_sec <= t) or (t < end_eff - SECONDS_PER_DAY)


# ---------------------------------------------------------------------------
# 数据结构
# ---------------------------------------------------------------------------


@dataclass
class SubjectInfo:
    """一个科目时间段。end_sec 为有效结束点（可能大于 86400，表示跨天）。"""

    name: str
    start: str          # 显示用 "HH:MM"
    end: str            # 显示用 "HH:MM"（跨天时为次日结束时刻）
    start_sec: int      # 开始秒（当天）
    end_sec: int        # 结束秒（当天，原始解析值；跨天判断交给 effective_* 函数）
    index: int          # 原始配置下标（供提示音 prev_key 标识段）

    def remaining_at(self, t: int) -> int:
        """距本段结束的剩余秒数（t 为当天秒数，跨天已按基准日算对）。"""
        return effective_end_for(t, self.start_sec, self.end_sec) - t


@dataclass
class ScheduleState:
    """一次调度的分析结果。"""

    in_evening: bool
    phase: str                       # "subject" / "idle" / "outside"
    current_subject: Optional[SubjectInfo]
    remaining_sec: Optional[int]     # phase=subject 时有效（跨天已算对）
    next_event: Dict[str, Any]       # {type, seconds, at, name?}
    sorted_subjects: List[SubjectInfo] = field(default_factory=list)


# ---------------------------------------------------------------------------
# 状态计算
# ---------------------------------------------------------------------------


def get_state(config: Dict[str, Any], now: datetime) -> ScheduleState:
    """根据业务配置与当前时刻计算调度状态。now 为本地 datetime。"""
    es = parse_hhmm(config.get("evening_start", "18:30"))
    ee = parse_hhmm(config.get("evening_end", "22:00"))
    t = now_sec_of_day(now)

    # 科目段解析 + 排序（考虑跨天：均按当天开始秒排序即可）
    subjects: List[SubjectInfo] = []
    raw_subjects = config.get("subjects") or []
    for i, sub in enumerate(raw_subjects):
        s = parse_hhmm(sub["start"])
        e = parse_hhmm(sub["end"])
        subjects.append(
            SubjectInfo(
                name=sub.get("name", ""),
                start=sub["start"],
                end=sub["end"],
                start_sec=s,
                end_sec=e,
                index=i,
            )
        )
    subjects.sort(key=lambda x: x.start_sec)

    in_evening = in_range(t, es, ee)

    current: Optional[SubjectInfo] = None
    for sub in subjects:
        if in_range(t, sub.start_sec, sub.end_sec):
            current = sub
            break

    if not in_evening:
        phase = "outside"
    elif current is not None:
        phase = "subject"
    else:
        phase = "idle"

    remaining = current.remaining_at(t) if current is not None else None
    if remaining is not None and remaining < 0:
        remaining = 0  # 防御：理论上 subject 内不会为负

    return ScheduleState(
        in_evening=in_evening,
        phase=phase,
        current_subject=current,
        remaining_sec=remaining,
        next_event=_next_event(t, es, ee, current, subjects, phase),
        sorted_subjects=subjects,
    )


def _candidate_at_or_after(t: int, event_sec: int) -> int:
    """把事件秒数映射为「>= t 的最小等价时刻」。

    当天秒数存在 86400 回绕：对事件秒数 e，若 e >= t 直接取 e，否则取 e + 86400。
    统一视角后，跨天晚自习（t 已回到凌晨小值）中的事件能正确排序：
    - 昨晚（前一日基准日）的科目开始/结束点会映射到次日同一时刻（+86400），不会被误判为仍在未来；
    - 今天凌晨的跨天科目（00:00 附近）的边界同样落在 t+86400 侧并被选中。
    """
    return event_sec if event_sec >= t else event_sec + SECONDS_PER_DAY


def _next_event(
    t: int,
    es: int,
    ee: int,
    current: Optional[SubjectInfo],
    subjects: List[SubjectInfo],
    phase: str,
) -> Dict[str, Any]:
    """计算下一个事件。seconds 均为相对当前时刻的秒数。

    各分支统一使用「>= t 的最小等价时刻」（见 _candidate_at_or_after）：
    - subject：下一事件为当前科目结束点；
    - idle   ：在「下一科目开始」与「晚自习结束」中取最近者；
    - outside：下一事件为下一次晚自习开始。
    """
    if phase == "subject" and current is not None:
        end_at = _candidate_at_or_after(t, current.end_sec)
        return {
            "type": "subject_end",
            "seconds": max(0, end_at - t),
            "at": to_hhmm(end_at),
            "name": current.name,
        }

    if phase == "idle":
        # 空档期：下一事件为最近一次「科目开始」或「晚自习结束」。
        # 跨天凌晨时，昨夜已过科目的开始点会映射到次日（+86400），
        # 不会被当作未来事件；凌晨跨天科目的开始点也会被正确纳入排序。
        best_at: Optional[int] = None
        best_name = ""
        for sub in subjects:
            at = _candidate_at_or_after(t, sub.start_sec)
            if best_at is None or at < best_at:
                best_at = at
                best_name = sub.name
        evening_end_at = _candidate_at_or_after(t, ee)
        if best_at is None or evening_end_at < best_at:
            return {
                "type": "evening_end",
                "seconds": max(0, evening_end_at - t),
                "at": to_hhmm(evening_end_at),
                "name": "晚自习结束",
            }
        return {
            "type": "subject_start",
            "seconds": max(0, best_at - t),
            "at": to_hhmm(best_at),
            "name": best_name,
        }

    # outside：下一个事件为下一次晚自习开始（映射到 >= t 的最近一次）
    start_at = _candidate_at_or_after(t, es)
    return {
        "type": "evening_start",
        "seconds": max(0, start_at - t),
        "at": to_hhmm(start_at),
        "name": "晚自习开始",
    }


# ---------------------------------------------------------------------------
# 提示音调度（无状态可测）
# ---------------------------------------------------------------------------


def _parse_prev_key(prev_key: str) -> Optional[Tuple[int, int, int]]:
    """解析上一 tick 的 key → (科目下标, 有效结束秒, 上一 tick 当天秒)。

    格式约定（见 get_sound_actions）："科目下标:有效结束秒:上一tick当天秒"，
    无有效段时为空字符串。解析失败返回 None。
    """
    if not prev_key:
        return None
    try:
        idx, end_sec, prev_t = prev_key.split(":")
        return int(idx), int(end_sec), int(prev_t)
    except (ValueError, AttributeError):
        return None


def make_prev_key(state: ScheduleState, now_sec: int) -> str:
    """为当前状态生成下一 tick 用的 prev_key。

    key = "科目下标:有效结束秒(tick时刻的基准日):tick当天秒"。
    有效结束秒采用 effective_end_for 映射到 tick 所在基准日，
    保证跨 00:00 时结束点切换正确。
    """
    if state.phase == "subject" and state.current_subject is not None:
        sub = state.current_subject
        end_tick = effective_end_for(now_sec, sub.start_sec, sub.end_sec)
        return "%d:%d:%d" % (sub.index, end_tick, now_sec)
    return ""


def get_sound_actions(
    config: Dict[str, Any],
    state: ScheduleState,
    now_sec_of_day: int,
    prev_key: str,
) -> Tuple[List[Dict[str, str]], str]:
    """计算本次 tick 应播放的提示音。

    参数：
        config: 业务配置（读取 sound 段）。
        state : get_state 的结果。
        now_sec_of_day: 当前时刻的当天秒数。
        prev_key: 上一 tick 返回的 key（见 make_prev_key）。

    返回：
        (actions, next_prev_key)
        actions 为 list[{"action": "near"/"end", "audio": wav文件名}]。
        next_prev_key 应作为下一次调用的 prev_key 传入，形成无状态链。

    规则：
        - sound.enabled 总开关关闭时不做任何提示；
        - near：phase=subject 且 0 < end_sec - t <= near_seconds 且
          near_enabled → 每秒播放一次；
        - end ：上一 tick 在某个科目段内（prev_key 非空）且该段结束点
          end_sec 落在 (prev_t, now_sec_of_day] 之间且 end_enabled → 播放一次；
        - 段切换：由于 key 携带段标识，新段不会误触 end，天然完成重置。
    """
    sound = config.get("sound") or {}
    key_now = make_prev_key(state, now_sec_of_day)

    if not sound.get("enabled"):
        return [], key_now

    actions: List[Dict[str, str]] = []

    # ---- 临近提示 ----
    if state.phase == "subject" and state.current_subject is not None:
        if sound.get("near_enabled", True):
            near_sec = int(sound.get("near_seconds", 60))
            remaining = effective_end_for(
                now_sec_of_day,
                state.current_subject.start_sec,
                state.current_subject.end_sec,
            ) - now_sec_of_day
            if 0 < remaining <= near_sec:
                actions.append(
                    {"action": "near", "audio": sound.get("near_audio", "near.wav")}
                )

    # ---- 结束提示（与当前相位无关：只要上一 tick 在段内且刚跨过结束点）----
    if sound.get("end_enabled", True):
        info = _parse_prev_key(prev_key)
        if info is not None:
            _idx, end_sec, prev_t = info
            # 把 now 统一到「上一 tick 的基准日」再比较：tick 跨越 00:00 时
            # now 回绕到小值（如 23:59:59 → 00:00:00），直接比较恒假，导致
            # 结束时刻恰为 00:00（有效结束秒 86400）的科目 end 音漏播。
            now_cmp = now_sec_of_day
            if now_cmp < prev_t:
                now_cmp += SECONDS_PER_DAY
            if prev_t < end_sec <= now_cmp:
                actions.append(
                    {"action": "end", "audio": sound.get("end_audio", "end.wav")}
                )

    return actions, key_now