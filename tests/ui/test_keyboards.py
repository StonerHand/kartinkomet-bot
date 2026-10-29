import unittest

from bot.tg.ui import keyboards

PIC = "f" * 32
BATTLE = "b" * 16
# Rough phone width per button, in visible characters, by buttons per row.
MAX_LABEL = {1: 24, 2: 12, 3: 8}
INVISIBLE = {"️", "‍", "\U0001f3fb", "\U0001f3fc", "\U0001f3fd", "\U0001f3fe", "\U0001f3ff"}


def visible_length(text: str) -> int:
    return sum(1 for char in text if char not in INVISIBLE and not 0x20E3 == ord(char))


def all_keyboards():
    yield "home", keyboards.home(is_admin=True)
    yield "home_user", keyboards.home(is_admin=False)
    yield "pic", keyboards.pic_actions(PIC, 999, 99)
    yield "trial", keyboards.on_trial()
    yield "duel", keyboards.battle_vote(BATTLE, "duel", [99, 99])
    yield "tournament", keyboards.battle_vote(BATTLE, "tournament", [9, 9, 9, 9])
    yield "after_duel", keyboards.after_duel(BATTLE, True)
    yield "after_tournament", keyboards.after_tournament()
    yield "court", keyboards.court_vote(BATTLE, 99, 99)
    yield "hall", keyboards.hall([PIC] * 10)
    yield "bottom", keyboards.bottom([PIC] * 10)
    yield "grave", keyboards.graveyard([PIC] * 5, True)
    for board, _ in keyboards.TOP_BOARDS:
        yield f"tops_{board}", keyboards.tops(board)
    yield "upload_hub", keyboards.upload_hub(True)
    yield "uploading", keyboards.uploading()
    yield "admin", keyboards.admin()
    yield "reset", keyboards.admin_reset_confirm()
    yield "games", keyboards.games_menu()
    yield "caption_vote", keyboards.caption_vote("g" * 16, 8)
    yield "after_caption", keyboards.after_caption()
    yield "gold", keyboards.gold("t" * 12)
    yield "gold_taken", keyboards.gold_taken("averyveryverylongname")
    yield "after_wheel", keyboards.after_wheel()
    yield "casino", keyboards.casino_menu((50, 100, 250, 500))
    yield "casino_again", keyboards.casino_again("football", 99999)
    prices = {"shield": 600, "boost": 800, "court": 500, "uncurse": 300}
    yield "pic_menu", keyboards.pic_menu("a" * 10, True, prices)
    yield "shop", keyboards.shop_menu()
    yield "appeal", keyboards.appeal(BATTLE)
    yield "quests", keyboards.quests_menu(True, {"wood": 1, "rare": 2, "legend": 3})
    yield "quests_ephemeral", keyboards.quests_menu(True, {"wood": 1, "rare": 2, "legend": 3}, -1001234567890)
    yield "chests", keyboards.open_chests(["wood", "rare", "legend"])
    yield "boss", keyboards.boss("b" * 12, 25)
    yield "boss_over", keyboards.boss_over()
    yield "proposal", keyboards.proposal("p" * 12)
    yield "challenge", keyboards.challenge("c" * 12)


class KeyboardTest(unittest.TestCase):
    def test_labels_fit_on_a_phone(self) -> None:
        for name, markup in all_keyboards():
            for row in markup.inline_keyboard:
                limit = MAX_LABEL.get(len(row), 6)
                for button in row:
                    with self.subTest(keyboard=name, label=button.text):
                        self.assertLessEqual(visible_length(button.text), limit)

    def test_callback_data_fits_telegram_limit(self) -> None:
        for name, markup in all_keyboards():
            for row in markup.inline_keyboard:
                for button in row:
                    with self.subTest(keyboard=name, data=button.callback_data):
                        self.assertLessEqual(len(button.callback_data.encode()), 64)

    def test_rows_hold_at_most_three_wide_buttons(self) -> None:
        for name in ("home", "after_duel", "court", "admin", "reset"):
            markup = dict(all_keyboards())[name]
            for row in markup.inline_keyboard:
                self.assertLessEqual(len(row), 2, name)


if __name__ == "__main__":
    unittest.main()
