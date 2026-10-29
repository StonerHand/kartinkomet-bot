import unittest

from bot.core.achievements import ALL_CODES
from bot.texts import arena, boss, captions, casino, court, days, events, games, progress, shop, social, toasts, tops, ui
from bot.texts.achievements import ACHIEVEMENTS, UNLOCKED
from bot.texts.pick import pick, reset
from tests.layout import EMOJI, NOT_COUNTED, assert_html, fits

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
    (tops, "LAST_PLACE"): 20,
    (toasts, "LIKE"): 20,
    (toasts, "DISLIKE"): 20,
}


# Pools whose phrases name someone: the one placeholder they may hold.
TEMPLATES = {"bot.texts.social.ROB_GUARDED": "{victim}"}


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

    def test_header_phrases_fit_a_phone_line(self) -> None:
        for phrase in UNLOCKED:  # a bold header of its own: wrapped, it reads as two headers
            self.assertTrue(fits(f"<b>{phrase}</b>"), phrase)

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
                    text = phrase.replace(TEMPLATES.get(pool_name, "\0"), "")
                    self.assertFalse(set(text) & set("<>&{}"), "HTML/format characters")
                    self.assertLess(len(phrase), 200)

    def test_template_phrases_name_their_person_once(self) -> None:
        pools = dict(all_pools())
        for pool_name, placeholder in TEMPLATES.items():
            for phrase in pools[pool_name]:
                self.assertEqual(phrase.count(placeholder), 1, phrase)

    def test_no_generated_gender_mismatch(self) -> None:
        bad = ("Пикча выдал", "Пикча принёс", "Пикча оформил", "пикча выжил", "пикча проиграл ")
        for pool_name, pool in all_pools():
            for phrase in pool:
                for fragment in bad:
                    self.assertNotIn(fragment.casefold(), phrase.casefold(), pool_name)

    def test_emoji_only_at_the_start_of_a_phrase(self) -> None:
        """Phrases become lines of a message: an emoji may open one, never sit inside it."""
        from bot.tg.ui.views import bare

        for pool_name, pool in all_pools():
            for phrase in pool:
                if not any(char.isalpha() for char in phrase):
                    continue  # a bare icon in a data tuple (shop items, chest tiers)
                inner = [char for char in EMOJI.findall(bare(phrase)) if char not in NOT_COUNTED]
                with self.subTest(pool=pool_name, phrase=phrase):
                    self.assertEqual(inner, [])

    def test_every_achievement_has_text(self) -> None:
        self.assertEqual(set(ACHIEVEMENTS), set(ALL_CODES))

    def test_pick_does_not_repeat_within_half_pool(self) -> None:
        reset()
        pool = tuple(str(i) for i in range(10))
        recent = [pick(pool, "chat") for _ in range(200)]
        for index in range(5, len(recent)):
            self.assertNotIn(recent[index], recent[index - 5 : index])


class StaticTextTest(unittest.TestCase):
    def test_static_html(self) -> None:
        for text in (ui.START, ui.HELP, ui.UPLOAD_PRIVATE_ONLY):
            assert_html(text)


if __name__ == "__main__":
    unittest.main()
