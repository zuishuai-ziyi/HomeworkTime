# -*- coding: utf-8 -*-
"""app.theme（窗口主题色）单元测试。

覆盖：
- normalize_theme：非法输入 / 缺键 / 非法色值回退默认；合法值归一化为大写；
- set_active_theme / active_theme 全局激活态切换与隔离；
- ball_color / glyph_color_for_bg：悬浮球底色取色与铃铛图标反色；
- darker_hex / lighten_hex：合法色变深 / 变亮；非法输入原样返回；
- qcolor_from_hex：合法 6 位色 / 非法输入回退默认卡片色。

运行方式（项目根目录）：
    python -m unittest client.tests.test_theme -v
"""

import os
import sys
import unittest

_TEST_DIR = os.path.dirname(os.path.abspath(__file__))
_CLIENT_DIR = os.path.dirname(_TEST_DIR)
if _CLIENT_DIR not in sys.path:
    sys.path.insert(0, _CLIENT_DIR)

from PyQt5.QtGui import QColor  # noqa: E402

from app.theme import (  # noqa: E402
    DEFAULT_THEME,
    BALL_GLYPH_ON_DARK,
    BALL_GLYPH_ON_LIGHT,
    active_theme,
    accent_color,
    ball_color,
    card_color,
    darker_hex,
    glyph_color_for_bg,
    lighten_hex,
    normalize_theme,
    qcolor_from_hex,
    set_active_theme,
    timeline_color,
)


class TestNormalizeTheme(unittest.TestCase):
    def test_invalid_inputs_fall_back_to_default(self):
        for bad in (None, "x", 123, [], {"card": "red"}, {}, {"card": "#FFF"}):
            self.assertEqual(normalize_theme(bad), dict(DEFAULT_THEME), repr(bad))

    def test_partial_and_case(self):
        out = normalize_theme({"card": "#ff0000"})
        self.assertEqual(out["card"], "#FF0000")
        self.assertEqual(out["accent"], DEFAULT_THEME["accent"])
        self.assertEqual(out["timeline"], DEFAULT_THEME["timeline"])
        self.assertEqual(out["ball"], DEFAULT_THEME["ball"])
        # 非法键被忽略
        out2 = normalize_theme({"card": "#123456", "junk": "#456789"})
        self.assertNotIn("junk", out2)
        self.assertEqual(out2["card"], "#123456")

    def test_valid_full_theme_roundtrip(self):
        raw = {
            "card": "#abcdef", "accent": "#123456",
            "timeline": "#654321", "ball": "#00aabb",
        }
        self.assertEqual(normalize_theme(raw), {
            "card": "#ABCDEF", "accent": "#123456",
            "timeline": "#654321", "ball": "#00AABB",
        })


class TestActiveTheme(unittest.TestCase):
    def tearDown(self):
        set_active_theme(None)  # 恢复默认，避免污染其他用例

    def test_set_and_read(self):
        out = set_active_theme({"card": "#111111"})
        self.assertEqual(out["card"], "#111111")
        self.assertEqual(active_theme()["card"], "#111111")
        # 取色函数跟随激活主题
        self.assertEqual(card_color().name().upper(), "#111111")
        self.assertIsInstance(card_color(), QColor)
        self.assertIsInstance(accent_color(), QColor)
        self.assertIsInstance(timeline_color(), QColor)
        self.assertIsInstance(ball_color(), QColor)

    def test_ball_color_follows_active_theme(self):
        set_active_theme({"ball": "#223344"})
        self.assertEqual(ball_color().name().upper(), "#223344")

    def test_active_returns_copy(self):
        snapshot = active_theme()
        snapshot["card"] = "#999999"
        self.assertNotEqual(active_theme()["card"], "#999999")


class TestBallGlyphColor(unittest.TestCase):
    def test_light_bg_returns_dark_glyph(self):
        self.assertEqual(glyph_color_for_bg("#FFFFFF"), BALL_GLYPH_ON_LIGHT)
        self.assertEqual(glyph_color_for_bg("#48CAE4"), BALL_GLYPH_ON_LIGHT)
        # QColor 兼容 3 位 hex：#FFF 即白色 → 深色铃铛
        self.assertEqual(glyph_color_for_bg("#FFF"), BALL_GLYPH_ON_LIGHT)

    def test_dark_bg_returns_white_glyph(self):
        self.assertEqual(glyph_color_for_bg("#0077B6"), BALL_GLYPH_ON_DARK)
        self.assertEqual(glyph_color_for_bg("#03045E"), BALL_GLYPH_ON_DARK)

    def test_invalid_bg_falls_back_to_white(self):
        for bad in (None, "", "junk", "#12ab"):
            self.assertEqual(glyph_color_for_bg(bad), BALL_GLYPH_ON_DARK, repr(bad))


class TestColorHelpers(unittest.TestCase):
    def test_darker_and_lighten(self):
        base = "#0077B6"
        darker = darker_hex(base, 135)
        lighter = lighten_hex(base, 130)
        self.assertTrue(darker.startswith("#") and len(darker) == 7)
        self.assertTrue(lighter.startswith("#") and len(lighter) == 7)
        self.assertNotEqual(darker, base)
        self.assertNotEqual(lighter, base)
        # 加深后亮度低于原色、提亮后高于原色（以红色通道近似判断）
        dbase, ddark, dlight = (
            QColor(base).lightness(),
            QColor(darker).lightness(),
            QColor(lighter).lightness(),
        )
        self.assertLess(ddark, dbase)
        self.assertGreater(dlight, dbase)

    def test_invalid_hex_passthrough(self):
        self.assertEqual(darker_hex("junk"), "junk")
        self.assertEqual(lighten_hex(""), "")

    def test_qcolor_from_hex(self):
        color = qcolor_from_hex("#023E8A", alpha=235)
        self.assertEqual(color.name().upper(), "#023E8A")
        self.assertEqual(color.alpha(), 235)
        # 非法输入回退默认卡片色
        fallback = qcolor_from_hex("not-a-color", alpha=245)
        self.assertEqual(
            fallback.name().upper(), DEFAULT_THEME["card"]
        )
        self.assertEqual(fallback.alpha(), 245)


if __name__ == "__main__":
    unittest.main()
