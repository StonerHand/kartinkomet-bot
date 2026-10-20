"""Every screen and card the bot can show, rendered with rich data and held to the layout rules.

The harness checks every message sent through the fake Telegram (BotHarness.check_outgoing);
views that are hard to reach through handlers are rendered directly and checked here.
"""

import random
from datetime import UTC, datetime

from aiogram.types import Message

from bot.core import days as day_rules
from bot.core import games as game_rules
from bot.core import progress as progress_rules
from bot.core.arena import DUEL_SECONDS
from bot.services.progress import Opened
from bot.tg import casino as casino_tg
from bot.tg import pics as pics_tg
from bot.tg import progress as progress_tg
from bot.tg import views
from bot.tg.events import Events
from tests.test_bot import ADMIN, GROUP, BotHarness, user
from tests.test_texts import assert_html, layout_problems

NAMES = {1: "stoner_hand", 2: "train", 3: "Михаил", 4: "fata11st", 5: "Захар", 6: "kcifekzhue"}


class ScreensTest(BotHarness):
    async def asyncSetUp(self) -> None:
        await super().asyncSetUp()
        casino_tg.ANIMATION_SCALE = 0
        casino_tg._last_play.clear()
        progress_tg.CHEST_PAUSE = 0
        pics_tg._last_drop.clear()
        repo = self.game.repo
        for user_id, name in NAMES.items():
            repo.remember_user(user_id, name, name, None, self.game.now())
            repo.add_coins(user_id, 5000, "test", self.game.now(), earn=False)

    def assert_layout(self, text: str) -> None:
        assert_html(text)
        self.assertEqual(layout_problems(text), [], text)

    def reply_to(self, user_id: int) -> Message:
        return Message(message_id=500, date=datetime.now(UTC), chat=GROUP, from_user=user(user_id), text="…")

    def fill_history(self) -> None:
        game, repo = self.game, self.game.repo
        for _ in range(8):
            battle = game.start_duel(-100).battle
            for voter in (3, 4, 5):
                game.vote_battle(battle.id, voter, 0)
            self.clock.advance(DUEL_SECONDS + 1)
            game.finish_battle(battle.id)
        for pic in repo.pics_of(ADMIN, limit=2, weakest=True):
            repo.remove_pic(pic.id, "executed", "court", game.now())
        repo.marry(ADMIN, 2, game.now() - 5 * 86400)
        game.grant_chest(ADMIN, "wood", announce=False)
        game.grant_chest(ADMIN, "legend", announce=False)
        game.buy_title(ADMIN, "Король кринжа")
        repo.set_meta("crowns", f"uploader:{ADMIN},rich:{ADMIN}")
        repo.set_meta("crowns_until", game.now() + 86400)
        repo.incr_counter(ADMIN, "right_guesses", 8)
        repo.incr_counter(ADMIN, "wrong_guesses", 2)
        repo.set_counter(ADMIN, "jail_until", game.now() + 1800)

    async def test_panel_screens(self) -> None:
        self.fill_history()
        await self.send("/menu", ADMIN)
        for screen in ("m:games", "m:casino", "m:shop", "m:hall", "m:bottom", "m:grave", "m:help", "m:up",
                       "m:adm", "adm:health", "adm:reset", "m:home:refresh"):
            await self.press(screen, sender=ADMIN)
        for board in ("uploads", "loved", "killers", "streaks", "rich"):
            await self.press(f"m:top:{board}", sender=ADMIN)
        self.session.refuse = {"SendEphemeralMessage"}  # personal screens fall back to the panel
        await self.press("m:me", sender=ADMIN)
        await self.press("m:quests", sender=ADMIN)

    async def test_games_and_people(self) -> None:
        self.game.roll_gold = lambda chat_id: True
        await self.send("/pic", 3)
        self.game.roll_gold = lambda chat_id: False
        await self.send("/wheel", 2)
        await self.send("/spin 100", 3)
        self.session.dice_values = [5, 2]
        casino_tg._last_play.clear()
        await self.send("/dice 200", 4)
        await self.send("/horoscope", 4)
        await self.send("/caption", 2)
        await self.send("/give 150", 2, reply_to=self.reply_to(3))
        self.game.rng.random = lambda: 0.1
        await self.send("/rob", 4, reply_to=self.reply_to(2))
        self.game.rng.random = lambda: 0.9
        await self.send("/rob", 5, reply_to=self.reply_to(3))
        self.game.rng = random.Random(7)
        await self.send("/marry", 2, reply_to=self.reply_to(3))
        await self.send("/challenge 200", 4, reply_to=self.reply_to(5))
        await self.send("/daily", 6)
        await self.send("/boss", 2)
        for command in ("/rob", "/give 100", "/marry", "/challenge 10", "/divorce"):
            await self.send(command, 6, reply_to=self.reply_to(6))

    async def test_schedule(self) -> None:
        self.fill_history()
        self.game.repo.touch_chat(-100, "чат", self.game.now())
        events = Events(self.bot, self.game, self.live, frozenset({ADMIN}), 0)
        await events.pic_of_the_day(-100)
        await events.weekly(-100)
        for code in day_rules.CODES:
            self.assert_layout(views.day_event(code, -100, (1500, 300, 4) if code == "tax" else None))

    def test_rare_cards(self) -> None:
        pic = self.game.draw_pic(-100)[0]
        for tier in progress_rules.TIERS:
            for kind in ("coins", "boost", "shield", "chest", "empty"):
                opened = Opened(tier, progress_rules.Loot(kind, 300 if kind == "coins" else 0), pic, [])
                self.assert_layout(views.chest_opened("stoner_hand", opened, -100))
        for kind, coins in game_rules.SPIN_COINS.items():
            spin = game_rules.Spin(kind, coins)
            self.assert_layout(views.spin_result("stoner_hand", spin, pic, 1234, -100))
        for milestone in (3, 5, 10):
            self.assert_layout(views.streak_announcement(milestone, milestone, -100))

    def test_every_achievement_and_level_announcement(self) -> None:
        """Checked one by one: in a live test only a random few of them would come up."""
        from bot.core import achievements, economy
        from bot.services.types import Granted

        many = [(name, Granted(index, [])) for index, name in enumerate(NAMES.values())]
        for code in achievements.ALL_CODES:
            granted = [(label, Granted(item.user_id, [code])) for label, item in many]
            self.assert_layout(views.announcement(granted))
        for level in economy.LEVELS:
            self.assert_layout(views.announcement([("kcifekzhue", Granted(1, [], level.name))]))
