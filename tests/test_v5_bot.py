"""v5 end to end: the new games, dice duels, seasons, raids and screens through the handlers."""

from datetime import UTC, datetime

from aiogram.types import Chat

from bot.core import boss as boss_rules
from bot.core import games as game_rules
from bot.tg import higher as higher_tg
from bot.tg import challenges as challenges_tg
from bot.tg.events import Events
from tests.test_bot import ADMIN
from tests.test_v4_bot import V4BotTest

PRIVATE = Chat(id=5, type="private")


class V5BotTest(V4BotTest):
    async def asyncSetUp(self) -> None:
        await super().asyncSetUp()
        challenges_tg.DICE_ANIMATION_SCALE = 0

    # ── whose pic? ─────────────────────────────────────────────────────

    async def test_whose_round_end_to_end(self) -> None:
        self.game.repo.add_pic("f-x", "u-x", 3, None, self.game.now())
        await self.send("/whose", sender=4)
        card = self.session.of("SendPhoto")[-1]
        self.assertIn("ЧЬЯ ПИКЧА", card.caption)
        guesses = self.buttons(card)
        self.assertEqual(len(guesses), 2)
        round_ = self.game.with_options(self.game.repo.active_game(-100, "whose"))
        author = self.game.repo.get_pic(round_["pic_id"]).added_by
        await self.press(guesses[round_["options"].index(author)], sender=4)
        await self.send("/whose", sender=5)
        self.assertIn("уже идёт", self.session.of("SendEphemeralMessage")[-1].text)
        self.clock.advance(game_rules.WHOSE_SECONDS)
        await self.live.advance_game(round_["id"])
        result = self.session.of("EditMessageCaption")[-1]
        self.assertIn("Угадали", result.caption)
        self.assertEqual(self.coins(4), game_rules.WHOSE_REWARD)

    # ── higher or lower ────────────────────────────────────────────────

    async def test_higher_lower_lives_in_private(self) -> None:
        for index, pic in enumerate(self.game.repo.random_alive(10)):
            self.game.repo.set_rating(pic.id, 1000 + index * 10)
        await self.send("/higher", sender=5)
        invite = self.session.of("SendMessage")[-1]
        self.assertTrue(invite.reply_markup.inline_keyboard[0][0].url.endswith("?start=hl"))
        await self.send("/start hl", sender=5, chat=PRIVATE)
        self.assertIn("/higher", self.session.of("SendMessage")[-1].text)  # the fake Telegram has no images

    async def test_higher_lower_rounds_and_game_over(self) -> None:
        for index, pic in enumerate(self.game.repo.random_alive(10)):
            self.game.repo.set_rating(pic.id, 1000 + index * 10)

        async def collage(bot, pics):
            return b"jpeg"

        higher_tg.build_collage = collage
        self.addCleanup(setattr, higher_tg, "build_collage", __import__("bot.tg.arena", fromlist=["x"]).build_collage)
        await self.send("/higher", sender=5, chat=PRIVATE)
        card = self.session.of("SendPhoto")[-1]
        self.assertIn("ВЫШЕ-НИЖЕ", card.caption)
        token, streak, first, second = self.game.hl_state(5)
        ratings = [self.game.repo.get_pic(first).rating, self.game.repo.get_pic(second).rating]
        right = 0 if ratings[0] > ratings[1] else 1
        await self.press(f"hl:{right}:{token}", sender=5, chat=PRIVATE)
        self.assertEqual(len(self.session.of("EditMessageMedia")), 1)
        token, streak, first, second = self.game.hl_state(5)
        self.assertEqual(streak, 1)
        ratings = [self.game.repo.get_pic(first).rating, self.game.repo.get_pic(second).rating]
        wrong = 1 if ratings[0] > ratings[1] else 0
        await self.press(f"hl:{wrong}:{token}", sender=5, chat=PRIVATE)
        self.assertIn("конец", self.session.of("EditMessageCaption")[-1].caption)

    # ── dice duels ─────────────────────────────────────────────────────

    async def test_dice_duel_and_rematch(self) -> None:
        self.fund(3, 1000)
        self.fund(4, 1000)
        await self.send("/pvp 200 дартс", sender=3, reply_to=self.reply_to(4))
        card = self.session.of("SendMessage")[-1]
        self.assertIn("ДАРТС 1 НА 1", card.text)
        challenge_id = self.buttons(card)[0].split(":")[2]
        self.session.dice_values = [6, 2]
        await self.press(f"cl:y:{challenge_id}", sender=4)
        self.assertEqual(len(self.session.of("SendDice")), 2)
        result = next(sent for sent in self.session.of("SendMessage") if "Личный счёт" in sent.text)
        self.assertIn("забирает <b>400</b>", result.text)
        self.assertEqual((self.coins(3), self.coins(4)), (1200, 800))
        await self.press(self.buttons(result)[0], sender=4)
        self.assertEqual(sum("ДАРТС 1 НА 1</b> · <b>" in sent.text for sent in self.session.of("SendMessage")), 2)
        self.assertEqual(self.coins(4), 600)

    async def test_pvp_without_a_stake_asks_for_one(self) -> None:
        self.fund(3, 1000)
        await self.send("/pvp", sender=3)
        question = self.session.of("SendEphemeralMessage")[-1]
        self.assertIn("КАКАЯ СТАВКА?", question.text)
        before = self.game.repo.player(3)[0]
        await self.press(self.buttons(question)[1], sender=3)  # 500
        self.assertEqual(self.game.repo.player(3)[0], before - 500)
        self.assertIn("КОСТИ 1 НА 1", self.session.of("SendMessage")[-1].text)

    async def test_pic_duel_challenge_offers_a_rematch(self) -> None:
        self.fund(3, 500)
        self.fund(4, 500)
        await self.send("/challenge 100", sender=3, reply_to=self.reply_to(4))
        challenge_id = self.buttons(self.session.of("SendMessage")[-1])[0].split(":")[2]
        await self.press(f"cl:y:{challenge_id}", sender=4)
        battle_id = self.game.repo.active_challenge_battle(-100)
        self.game.vote_battle(battle_id, 5, 0)
        self.clock.advance(70)
        await self.live.finish_battle(battle_id)
        result = (self.session.of("EditMessageCaption") or self.session.of("EditMessageText"))[-1]
        self.assertIn(f"rm:{challenge_id}", self.buttons(result))
        self.assertIn("Личный счёт", getattr(result, "caption", None) or result.text)

    # ── seasons ────────────────────────────────────────────────────────

    async def test_season_results_and_warning(self) -> None:
        repo = self.game.repo
        repo.touch_chat(-100, "чат", self.game.now())
        events = Events(self.bot, self.game, self.live, frozenset({ADMIN}), 0)
        await events.close_season()  # the first tick only starts counting
        self.game.pay(3, 40, "vote")
        self.clock.value = self.game.season_bounds()[1] - 6 * 3600  # noon-ish of the last day
        self.assertTrue(await events.season_warning(-100))
        self.assertIn("ПОСЛЕДНИЙ ДЕНЬ СЕЗОНА", self.session.of("SendMessage")[-1].text)
        self.clock.value = self.game.season_bounds()[1] + 60
        repo.touch_chat(-100, "чат", self.game.now())  # results go to chats active lately
        await events.close_season()
        results = self.session.of("SendMessage")[-1]
        self.assertIn("ИТОГИ СЕЗОНА", results.text)
        self.assertIn("m:seasons", self.buttons(results))
        await self.press("m:seasons")
        self.assertIn("ЗАЛ СЕЗОНОВ", self.screen())

    # ── raids ──────────────────────────────────────────────────────────

    async def test_raid_comes_on_saturday(self) -> None:
        self.game.repo.touch_chat(-100, "чат", self.game.now())
        day = datetime.fromtimestamp(self.game.now(), UTC)
        saturday = day.replace(hour=16, minute=1).timestamp() + ((boss_rules.RAID_WEEKDAY - day.weekday()) % 7) * 86400
        self.clock.value = saturday
        await Events(self.bot, self.game, self.live, frozenset({ADMIN}), 0).tick()
        boss = self.game.repo.active_boss(-100)
        self.assertEqual(boss["raid"], 1)
        self.assertIn("РЕЙД", self.session.of("SendPhoto")[-1].caption)
        self.fund(3, 1000)
        await self.press(f"bs:{boss['id']}", sender=3)
        self.assertEqual(self.coins(3), 1000 - self.game.super_price())

    # ── screens ────────────────────────────────────────────────────────

    async def test_tops_weekly_toggle_and_new_boards(self) -> None:
        await self.send("/menu")
        await self.press("m:top:uploads:w")
        weekly = self.shown()
        self.assertIn("неделя", weekly.text)
        self.assertIn("m:top:uploads", self.buttons(weekly))
        for board in ("season", "hl", "rich:w", "loved:w", "killers:w"):
            await self.press(f"m:top:{board}")

    async def test_admin_stats(self) -> None:
        await self.send("/menu", sender=ADMIN)
        await self.press("adm:stats", sender=ADMIN)
        self.assertIn("СТАТИСТИКА", self.session.of("EditMessageText")[-1].text)

    async def test_casino_share_buttons(self) -> None:
        self.fund(3, 1000)
        await self.press("cs:p25", sender=3)
        self.assertEqual(self.game.stake_for_play(3), 250)
        await self.send("/menu", sender=3)
        await self.press("m:casino", sender=3)
        screen = self.shown()
        self.assertIn("25%", screen.text)
        self.assertIn("cs:p25", self.buttons(screen))

    async def test_profile_shows_season_casino_and_records(self) -> None:
        self.fund(3, 1000)
        self.game.pay(3, 30, "vote")
        await self.send("/spin 100", sender=3)
        self.game.repo.set_counter(3, "hl_best", 7)
        self.session.refuse = {"SendEphemeralMessage"}
        await self.press("m:me", sender=3)
        profile = self.session.of("EditMessageText")[-1].text
        for part in ("Сезон", "Казино", "Рекорды", "Выше-ниже"):
            self.assertIn(part, profile)
