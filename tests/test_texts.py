import re
import unittest
from html.parser import HTMLParser

from bot.core.achievements import ALL_CODES
from bot.texts import arena, boss, captions, casino, court, days, events, games, progress, shop, social, toasts, tops, ui
from bot.texts.achievements import ACHIEVEMENTS
from bot.texts.pick import pick, reset

EXPECTED_SIZES = {
    (captions, "CAPTIONS"): 600,
    (captions, "FRESH"): 40,
    (captions, "LEGEND"): 40,
    (arena, "DUEL_START"): 60,
    (arena, "DUEL_STATUS"): 60,
    (arena, "DUEL_WIN"): 60,
    (arena, "DUEL_DRAW"): 60,
    (arena, "DUEL_EXECUTION"): 60,
    (arena, "STREAK_3"): 20,
    (arena, "STREAK_5"): 20,
    (arena, "STREAK_10"): 20,
    (arena, "TOURNAMENT_START"): 50,
    (arena, "TOURNAMENT_STATUS"): 50,
    (arena, "TOURNAMENT_WIN"): 50,
    (arena, "TOURNAMENT_DRAW"): 50,
    (court, "SUMMONS"): 40,
    (court, "STATUS"): 40,
    (court, "EXECUTED"): 40,
    (court, "PARDONED"): 40,
    (court, "LAST_WORD_INTRO"): 40,
    (tops, "FIRST_PLACE"): 20,
    (tops, "PODIUM"): 20,
    (tops, "MIDDLE"): 20,
    (tops, "LAST_PLACE"): 20,
    (toasts, "LIKE"): 20,
    (toasts, "DISLIKE"): 20,
}


def all_pools():
    for module in (arena, boss, captions, casino, court, days, events, games, progress, shop, social, toasts, tops, ui):
        for name, value in vars(module).items():
            if name.isupper() and isinstance(value, tuple) and value and isinstance(value[0], str):
                yield f"{module.__name__}.{name}", value
            if name.isupper() and isinstance(value, dict):
                for key, pool in value.items():
                    if isinstance(pool, tuple) and all(isinstance(item, str) for item in pool):
                        yield f"{module.__name__}.{name}.{key}", pool


class TextsTest(unittest.TestCase):
    def test_pool_sizes(self) -> None:
        for (module, name), size in EXPECTED_SIZES.items():
            with self.subTest(pool=name):
                self.assertEqual(len(getattr(module, name)), size)

    def test_phrases_are_unique_everywhere(self) -> None:
        seen: dict[str, str] = {}
        for pool_name, pool in all_pools():
            for phrase in pool:
                with self.subTest(phrase=phrase):
                    self.assertNotIn(phrase, seen, f"{pool_name} repeats {seen.get(phrase)}")
                seen[phrase] = pool_name

    def test_phrases_are_plain_text(self) -> None:
        for pool_name, pool in all_pools():
            for phrase in pool:
                with self.subTest(pool=pool_name, phrase=phrase):
                    self.assertFalse(set(phrase) & set("<>&{}"), "HTML/format characters")
                    self.assertLess(len(phrase), 200)

    def test_no_generated_gender_mismatch(self) -> None:
        bad = ("Пикча выдал", "Пикча принёс", "Пикча оформил", "пикча выжил", "пикча проиграл ")
        for pool_name, pool in all_pools():
            for phrase in pool:
                for fragment in bad:
                    self.assertNotIn(fragment.casefold(), phrase.casefold(), pool_name)

    def test_every_achievement_has_text(self) -> None:
        self.assertEqual(set(ACHIEVEMENTS), set(ALL_CODES))

    def test_pick_does_not_repeat_within_half_pool(self) -> None:
        reset()
        pool = tuple(str(i) for i in range(10))
        recent = [pick(pool, "chat") for _ in range(200)]
        for index in range(5, len(recent)):
            self.assertNotIn(recent[index], recent[index - 5 : index])


class HtmlBalance(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.stack: list[str] = []

    def handle_starttag(self, tag, attrs) -> None:
        self.stack.append(tag)

    def handle_endtag(self, tag) -> None:
        assert self.stack and self.stack.pop() == tag, f"unbalanced </{tag}>"


EMOJI = re.compile("[\U0001F300-\U0001FAFF\u2600-\u27BF\u2B50\u2B06\u2194-\u21FF\u2300-\u23FF]")
NOT_COUNTED = set("\U0001F3FB\U0001F3FC🟥🟦🟩🟨")  # skin tones and vote bars
PHONE_LINE = 40  # characters that fit one line of a message on a phone


def layout_problems(text: str) -> list[str]:
    """The message layout rules (see bot/tg/views/layout.py), as checks:
    one emoji per line and at its start; a list item that has neighbours fits one phone line."""
    plain = re.sub(r"<[^>]+>", "", text).replace("&lt;", "<").replace("&gt;", ">").replace("&amp;", "&")
    lines = plain.split("\n")
    problems = []
    for index, line in enumerate(lines):
        emoji = [char for char in EMOJI.findall(line) if char not in NOT_COUNTED]
        if len(emoji) > 1:
            problems.append(f"several emoji: {line}")
        elif emoji and not EMOJI.match(line.lstrip("▫️✅ ")) and not EMOJI.match(line):
            problems.append(f"emoji inside a line: {line}")
        starts_with_emoji = bool(EMOJI.match(line))
        neighbour = (index + 1 < len(lines) and lines[index + 1].strip()) or (
            index and lines[index - 1].strip() and EMOJI.match(lines[index - 1])
        )
        if starts_with_emoji and len(line) > PHONE_LINE and neighbour:
            problems.append(f"list line wraps on a phone: {line}")
    return problems


def assert_html(text: str) -> None:
    parser = HtmlBalance()
    parser.feed(text)
    assert not parser.stack, f"unclosed {parser.stack}"
    assert len(text) <= 4096


class StaticTextTest(unittest.TestCase):
    def test_static_html(self) -> None:
        for text in (ui.START, ui.HELP, ui.UPLOAD_PRIVATE_ONLY):
            assert_html(text)


if __name__ == "__main__":
    unittest.main()
