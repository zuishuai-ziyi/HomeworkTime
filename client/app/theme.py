# -*- coding: utf-8 -*-
"""客户端窗口主题（颜色）模块。

业务配置契约中的 ``theme`` 对象驱动四处可自定义颜色：
- ``card``     卡片背景（主窗口 / 确认框自绘圆角底色）
- ``accent``   强调色（时间轴当前段高亮、确认框主按钮）
- ``timeline`` 时间轴非当前条目底色
- ``ball``     悬浮球纯色圆底（铃铛图标按底色亮度自动白/深蓝反色）

关键不变量：
- 所有取色函数（card_color 等）读取**当前激活主题**（模块级单例），
  AppController 在启动与业务配置变更时调用 set_active_theme() 后，
  各窗口下一次 paintEvent / 刷新即生效，无需重建窗口；
- normalize_theme() 永远返回完整三元 dict：缺失 / 非法键回退默认值
  （默认值 = 项目蓝色调色板，与 docs/开发文档.md 第六章一致），
  保证任何脏配置都不会导致窗口不可读；
- 仅依赖 PyQt5.QtGui.QColor（无需 QApplication 实例），可安全单测。
"""

from __future__ import annotations

import re
import threading
from typing import Any, Dict, Optional

from PyQt5.QtGui import QColor

#: 默认主题（与项目蓝色调色板一致：french-blue / bright-teal-blue / deep-twilight）
DEFAULT_THEME: Dict[str, str] = {
    "card": "#023E8A",
    "accent": "#0077B6",
    "timeline": "#03045E",
    "ball": "#0077B6",
}

#: theme 合法键（契约顺序固定，新增键须同步双端 schema 与校验器）
THEME_KEYS = ("card", "accent", "timeline", "ball")

#: 悬浮球铃铛图标用色：浅色底 → 深蓝铃铛，深色底 → 白色铃铛（与色板一致）
BALL_GLYPH_ON_LIGHT = "#03045E"
BALL_GLYPH_ON_DARK = "#FFFFFF"
#: 背景相对亮度阈值：不低于该值视为浅色底（近似加权亮度，0~1）
BALL_LUMA_LIGHT_THRESHOLD = 0.55

#: 契约颜色格式：#RRGGBB（6 位十六进制）
HEX_RE = re.compile(r"^#[0-9A-Fa-f]{6}$")

_lock = threading.RLock()
_active: Dict[str, str] = dict(DEFAULT_THEME)


def normalize_theme(raw: Any) -> Dict[str, str]:
    """把任意输入归一化为完整主题 dict（纯函数，便于单测）。

    - raw 非 dict → 全默认；
    - 缺失 / 非法（非 #RRGGBB 格式）的键 → 该键回退默认；
    - 合法键保留原值（大小写不敏感，统一转为 #RRGGBB 大写）。
    """
    out: Dict[str, str] = {}
    valid = raw if isinstance(raw, dict) else {}
    for key in THEME_KEYS:
        value = valid.get(key)
        if (
            isinstance(value, str)
            and HEX_RE.match(value.strip())
        ):
            out[key] = value.strip().upper()
        else:
            out[key] = DEFAULT_THEME[key]
    return out


def set_active_theme(raw: Any) -> Dict[str, str]:
    """设置当前激活主题（业务配置变更入口），返回归一化结果。"""
    global _active
    normalized = normalize_theme(raw)
    with _lock:
        _active = normalized
    return normalized


def active_theme() -> Dict[str, str]:
    """返回当前激活主题（归一化后的副本）。"""
    with _lock:
        return dict(_active)


def _color(key: str, alpha: int = 255) -> QColor:
    """按激活主题取 QColor（非法时 normalize 已兜底为默认值）。"""
    color = QColor(active_theme().get(key, DEFAULT_THEME[key]))
    if alpha != 255:
        color.setAlpha(max(0, min(255, int(alpha))))
    return color


def card_color(alpha: int = 255) -> QColor:
    """卡片背景色（主窗口 paintEvent / 确认框 paintEvent）。"""
    return _color("card", alpha)


def accent_color(alpha: int = 255) -> QColor:
    """强调色（时间轴当前段高亮 / 确认框主按钮）。"""
    return _color("accent", alpha)


def timeline_color(alpha: int = 255) -> QColor:
    """时间轴非当前条目底色。"""
    return _color("timeline", alpha)


def ball_color(alpha: int = 255) -> QColor:
    """悬浮球纯色圆底底色。"""
    return _color("ball", alpha)


def glyph_color_for_bg(bg_hex: Optional[str]) -> str:
    """按悬浮球背景色亮度返回铃铛图标用色（纯函数，便于单测）。

    近似相对亮度（加权 RGB）：>= 阈值视为浅色底 → 深蓝铃铛，
    否则（含非法色值，按深底兜底）→ 白色铃铛。
    """
    color = QColor(bg_hex or "")
    luma = 0.0
    if color.isValid():
        luma = (
            0.2126 * color.redF()
            + 0.7152 * color.greenF()
            + 0.0722 * color.blueF()
        )
    if luma >= BALL_LUMA_LIGHT_THRESHOLD:
        return BALL_GLYPH_ON_LIGHT
    return BALL_GLYPH_ON_DARK


def ball_glyph_color() -> str:
    """按当前激活的悬浮球底色返回铃铛图标用色。"""
    return glyph_color_for_bg(ball_color().name())


def darker_hex(hex_color: str, factor: int = 115) -> str:
    """把 #RRGGBB 加深（QColor.darker 语义），返回 #RRGGBB 大写（纯函数）。"""
    color = QColor(hex_color)
    if not color.isValid():
        return hex_color
    return color.darker(factor).name().upper()


def lighten_hex(hex_color: str, factor: int = 130) -> str:
    """把 #RRGGBB 提亮（QColor.lighter 语义），返回 #RRGGBB 大写（纯函数）。"""
    color = QColor(hex_color)
    if not color.isValid():
        return hex_color
    return color.lighter(factor).name().upper()


def qcolor_from_hex(hex_color: Optional[str], alpha: int = 255) -> QColor:
    """从 #RRGGBB 字符串构造 QColor；非法回退默认卡片色（纯函数）。"""
    if isinstance(hex_color, str) and HEX_RE.match(hex_color.strip()):
        color = QColor(hex_color.strip())
    else:
        color = QColor(DEFAULT_THEME["card"])
    if alpha != 255:
        color.setAlpha(max(0, min(255, int(alpha))))
    return color
