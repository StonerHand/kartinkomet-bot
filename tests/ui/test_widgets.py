"""The HTML widgets against Telegram's limits (widget-sandbox docs/profile-v1.md): the page size,
what a page may not use, and the data that has to fit 1 KB."""

import json
import re
import unittest
import zlib

from bot.ui import widgets

FORBIDDEN = (
    r"\bfetch\(", r"XMLHttpRequest", r"WebSocket", r"<input", r"<form", r"<iframe", r"<video", r"<audio",
    r"<script\s+src", r"\bsrc=\"https?:", r"url\(\s*['\"]?https?:", r"@font-face", r"@import", r"\son\w+=",
)


class WidgetPagesTest(unittest.TestCase):
    def test_every_page_fits_telegrams_limits(self) -> None:
        for kind in widgets.KINDS:
            with self.subTest(kind=kind):
                html = widgets.page(kind).encode()
                self.assertLessEqual(len(html), 32 * 1024)
                self.assertLessEqual(len(zlib.compress(html, 9)), 4096)

    def test_pages_use_nothing_a_widget_cannot(self) -> None:
        for kind in widgets.KINDS:
            html = widgets.page(kind)
            for pattern in FORBIDDEN:
                with self.subTest(kind=kind, pattern=pattern):
                    self.assertIsNone(re.search(pattern, html, re.M))

    def test_pages_talk_to_telegram_and_say_ready(self) -> None:
        for kind in widgets.KINDS:
            with self.subTest(kind=kind):
                html = widgets.page(kind)
                self.assertIn("window.TelegramWidget", html)
                self.assertIn("W.ready()", html)
                self.assertIn(kind, widgets.CAPTIONS)


class WidgetDataTest(unittest.TestCase):
    def test_long_names_and_lists_still_fit_a_kilobyte(self) -> None:
        long = "Очень-очень длинное имя игрока" * 3
        samples = [
            widgets.mines_data(list(range(14)), [14, 15], [(long, 10_000_000)] * 40, 999, 1_800_000_000, 1, long),
            widgets.safe_data([("0123", 2, 1)] * 50, 10**9, 10**6, 1_800_000_000, 1, "0123", long),
            widgets.spy_data("vote", [long] * 8, [3] * 8, 8, 1_800_000_000, {"k": "caught", "spy": long, "w": "кактус"}),
            widgets.rps_data((long, long), (True, False), 3, 1_800_000_000, {"w": long, "k": [0, 1], "late": ""}),
            widgets.ttt_data("XOXOXOXO.", (long, long), 1, 1_800_000_000, {"w": "", "line": [], "late": long}),
            widgets.slots_data([(long, 10**9)] * 50),
            widgets.board_data([(long, 10**9)] * 50, (10**9, 10**9), "23:59"),
        ]
        for data in samples:
            with self.subTest(data=data[:40]):
                self.assertLessEqual(len(data.encode()), 1024)
                json.loads(data)

    def test_names_are_cut_for_the_widget(self) -> None:
        self.assertEqual(widgets.name("коротко"), "коротко")
        self.assertEqual(len(widgets.name("x" * 40)), widgets.NAME)
