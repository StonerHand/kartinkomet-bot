"""v4 end to end: handlers against the fake Telegram session."""

from aiogram.types import Message

from bot.core import court
from bot.core.arena import DUEL_SECONDS
from bot.tg import casino as casino_tg
from bot.tg import progress as progress_tg
from bot.tg import shop as shop_tg
from bot.tg.events import Events
from tests.test_bot import ADMIN, BOT_USER, GROUP, BotHarness, user


class V4BotTest(BotHarness):
    async def asyncSetUp(self) -> None:
        await super().asyncSetUp()
        casino_tg.ANIMATION_SCALE = 0
        casino_tg._last_play.clear()
        progress_tg.CHEST_PAUSE = 0
        shop_tg._confirm.clear()
        for user_id in range(2, 8):
            self.game.repo.remember_user(user_id, f"user{user_id}", f"user{user_id}", None, self.game.now())

    def fund(self, user_id: int, amount: int = 1000) -> None:
        self.game.repo.add_coins(user_id, amount, "test", self.game.now(), earn=False)

    def coins(self, user_id: int) -> int:
        return self.game.repo.player(user_id)[0]

    def texts(self) -> list[str]:
        return [getattr(r, "text", None) or getattr(r, "caption", None) or "" for r in self.session.requests]

    def reply_to(self, user_id: int) -> Message:
        from datetime import UTC, datetime

        return Message(message_id=500, date=datetime.now(UTC), chat=GROUP, from_user=user(user_id), text="привет")

    # ── casino ─────────────────────────────────────────────────────────

    async def test_slots_with_a_stake(self) -> None:
        self.fund(3, 500)
        await self.send("/spin 100", sender=3)
        self.assertEqual(self.session.of("SendDice")[0].emoji, "🎰")
        result = next(r for r in self.session.of("SendMessage") if "ДЖЕКПОТ" in r.text)
        self.assertEqual(self.coins(3), 2400)
        self.assertIn("cp:slots:100", self.buttons(result))

    async def test_dice_against_the_bot_rolls_twice(self) -> None:
        self.fund(3, 100)
        self.session.dice_values = [6, 1]
        await self.send("/dice 100", sender=3)
        self.assertEqual(len(self.session.of("SendDice")), 2)
        self.assertIn("Ты: <b>6</b> · бот: <b>1</b>", self.session.of("SendMessage")[-1].text)
        self.assertEqual(self.coins(3), 200)

    async def test_broke_player_gets_a_reply_and_no_dice(self) -> None:
        await self.send("/darts 100", sender=3)
        self.assertEqual(self.session.of("SendDice"), [])

    async def test_casino_screen_and_stake_buttons(self) -> None:
        self.fund(3, 300)
        await self.press("m:casino", sender=3)
        screen = self.session.of("EditMessageText")[-1]
        self.assertIn("КАЗИНО", screen.text)
        await self.press("cs:all", sender=3)
        self.session.dice_values = [5]
        await self.press("cg:basket", sender=3)
        self.assertEqual(self.coins(3), 690)

    # ── arena bets, evolution, challenges ──────────────────────────────

    async def test_bet_button_and_result(self) -> None:
        self.fund(3)
        await self.send("/duel")
        battle = self.game.repo.active_battle(-100, "duel")
        await self.press(f"bt:{battle.id}:0", sender=3)
        await self.press(f"v:{battle.id}:0", sender=4)
        self.clock.advance(DUEL_SECONDS + 1)
        await self.live.finish_battle(battle.id)
        self.assertTrue(any("Ставки" in text for text in self.texts()))
        self.assertTrue(any("эволюционировала" in text for text in self.texts()))
        self.assertEqual(self.coins(3), 1000)  # the only bet on the winner gets its own pool back

    async def test_challenge_accept_starts_a_battle(self) -> None:
        self.fund(3, 500)
        self.fund(4, 500)
        await self.send("/challenge 200", sender=3, reply_to=self.reply_to(4))
        card = self.session.of("SendMessage")[-1]
        self.assertIn("ВЫЗОВ", card.text)
        challenge_id = self.buttons(card)[0].split(":")[2]
        await self.press(f"cl:y:{challenge_id}", sender=5)
        self.assertEqual(self.game.repo.get_challenge(challenge_id)["status"], "pending")
        await self.press(f"cl:y:{challenge_id}", sender=4)
        battle_id = self.game.repo.active_challenge_battle(-100)
        self.assertIsNotNone(battle_id)
        self.assertTrue(any("на кону" in text.lower() for text in self.texts()))

    # ── shop ───────────────────────────────────────────────────────────

    async def test_pic_menu_and_shield(self) -> None:
        self.fund(3)
        pic = self.game.draw_pic(-100)[0]
        await self.press(f"pm:{pic.id}", sender=3)
        menu = self.session.of("SendEphemeralMessage")[-1]
        shield = menu.reply_markup.inline_keyboard[0][0].callback_data
        self.assertTrue(shield.startswith("sh:s:"))
        await self.press(shield, sender=4)  # someone else's menu
        self.assertEqual(self.coins(3), 1000)
        await self.press(shield, sender=3)
        self.assertEqual(self.coins(3), 700)
        self.assertGreater(self.game.repo.get_pic(pic.id).immune_until, self.game.now())

    async def test_ordered_court_opens_a_trial(self) -> None:
        self.fund(3)
        pic = self.game.draw_pic(-100)[0]
        token = shop_tg.menu_token(self.game, pic.id, 3, -100)
        await self.press(f"sh:c:{token}", sender=3)
        self.assertIsNotNone(self.game.repo.active_court_for_pic(pic.id))

    async def test_bounty_poster(self) -> None:
        self.fund(3)
        pic = self.game.draw_pic(-100)[0]
        token = shop_tg.menu_token(self.game, pic.id, 3, -100)
        await self.press(f"sh:h5:{token}", sender=3)
        self.assertIn("РАЗЫСКИВАЕТСЯ", self.session.of("SendPhoto")[-1].caption)

    async def test_resurrection_needs_two_taps(self) -> None:
        self.fund(3)
        pic = self.game.draw_pic(-100)[0]
        self.game.repo.remove_pic(pic.id, "executed", "court", self.game.now())
        await self.press(f"res:{pic.id}", sender=3)
        self.assertEqual(self.game.repo.get_pic(pic.id).status, "executed")
        await self.press(f"res:{pic.id}", sender=3)
        self.assertEqual(self.game.repo.get_pic(pic.id).status, "alive")
        self.assertIn("ВОСКРЕШЕНИЕ", self.session.of("SendPhoto")[-1].caption)

    async def test_title_by_reply(self) -> None:
        from datetime import UTC, datetime

        self.fund(3)
        await self.press("title", sender=3)
        key = self.game.repo.db.execute("SELECT key FROM meta WHERE key LIKE 'title_prompt:%'").fetchone()[0]
        prompt = Message(message_id=int(key.rsplit(":", 1)[1]), date=datetime.now(UTC), chat=GROUP, from_user=BOT_USER)
        await self.send("Король кринжа", sender=4, reply_to=prompt)  # not theirs
        self.assertIsNone(self.game.repo.title_of(4))
        await self.send("Король кринжа", sender=3, reply_to=prompt)
        self.assertEqual(self.game.repo.title_of(3), "Король кринжа")
        self.assertEqual(self.coins(3), 500)

    # ── people ─────────────────────────────────────────────────────────

    async def test_give_by_reply_and_by_name(self) -> None:
        self.fund(3, 300)
        await self.send("/give 100", sender=3, reply_to=self.reply_to(4))
        await self.send("/give user5 50", sender=3)
        self.assertEqual((self.coins(3), self.coins(4), self.coins(5)), (150, 100, 50))
        self.assertIn("ПОДАРОК", self.session.of("SendMessage")[-1].text)

    async def test_marriage_by_buttons(self) -> None:
        self.fund(3)
        self.fund(4)
        await self.send("/marry", sender=3, reply_to=self.reply_to(4))
        card = self.session.of("SendMessage")[-1]
        proposal = self.buttons(card)[0].split(":")[2]
        await self.press(f"mr:y:{proposal}", sender=4)
        self.assertEqual(self.game.repo.spouse_of(3)[0], 4)
        self.assertIn("СВАДЬБА", self.session.of("EditMessageText")[-1].text)
        await self.send("/divorce", sender=4)
        self.assertIsNone(self.game.repo.spouse_of(3))

    async def test_rob_without_target_explains(self) -> None:
        await self.send("/rob", sender=3)
        self.assertEqual(self.session.of("SendMessage")[-1].text.split(":")[0],
                         "Ответь этой командой на сообщение человека или напиши его ник")

    # ── progress ───────────────────────────────────────────────────────

    async def test_daily_and_quests_screen(self) -> None:
        await self.press("daily", sender=3)
        self.assertTrue(any("БОНУС ДНЯ" in text for text in self.texts()))
        self.assertEqual(self.coins(3), 50)
        await self.press("daily", sender=3)
        self.assertEqual(self.coins(3), 50)
        await self.press("m:quests", sender=3)
        quests = self.session.of("SendEphemeralMessage")[-1]
        self.assertIn("КВЕСТЫ", quests.text)

    async def test_chest_opens_with_suspense(self) -> None:
        self.game.grant_chest(3, "legend", announce=False)
        await self.press("ch:legend", sender=3)
        self.assertIn("ЛЕГЕНДАРНЫЙ СУНДУК", self.session.of("EditMessageText")[-1].text)
        self.assertEqual(self.game.chests_of(3)["legend"], 0)
        await self.press("ch:legend", sender=3)
        self.assertEqual(len(self.session.of("EditMessageText")), 1)

    # ── boss ───────────────────────────────────────────────────────────

    async def test_boss_fight(self) -> None:
        await self.send("/boss", sender=3)
        card = self.session.of("SendPhoto")[-1]
        self.assertIn("БОСС", card.caption)
        boss = self.game.repo.active_boss(-100)
        self.game.repo.db.execute("UPDATE bosses SET hp = 1 WHERE id = ?", (boss["id"],))
        self.game.repo.db.commit()
        await self.press(f"bh:{boss['id']}", sender=4)
        self.assertEqual(self.game.repo.get_boss(boss["id"])["status"], "won")
        self.assertTrue(any("ПОВЕРЖЕН" in text for text in self.texts()))
        await self.send("/boss", sender=3)
        self.assertIn("через", self.session.of("SendMessage")[-1].text)

    # ── court appeal ───────────────────────────────────────────────────

    async def test_appeal_button_after_execution(self) -> None:
        pic = self.game.draw_pic(-100)[0]
        trial = self.game.start_court(-100, pic.id, "bottom", None).court
        self.game.repo.set_court_message(trial.id, 80)
        await self.press(f"c:k:{trial.id}", sender=3)
        await self.press(f"c:k:{trial.id}", sender=4)
        self.clock.advance(court.COURT_SECONDS + 1)
        await self.live.finish_court(trial.id)
        verdict = self.session.of("EditMessageCaption")[-1]
        self.assertIn(f"ap:{trial.id}", self.buttons(verdict))
        self.fund(ADMIN, 200)
        await self.press(f"ap:{trial.id}", sender=ADMIN)
        appeal = self.session.of("SendPhoto")[-1]
        self.assertIn("АПЕЛЛЯЦИЯ", appeal.caption)

    # ── schedule ───────────────────────────────────────────────────────

    async def test_day_event(self) -> None:
        self.game.repo.touch_chat(-100, "чат", self.game.now())
        from datetime import UTC, datetime

        day_start = datetime.fromtimestamp(self.game.now(), UTC).replace(hour=10, minute=5)
        self.clock.value = day_start.timestamp()
        await Events(self.bot, self.game, self.live, frozenset({ADMIN}), 0).tick()
        texts = self.texts()
        self.assertTrue(any("СОБЫТИЕ ДНЯ" in text for text in texts))
        self.assertIsNotNone(self.game.day_event())

    async def test_boss_arrives_on_schedule(self) -> None:
        self.game.repo.touch_chat(-100, "чат", self.game.now())
        from datetime import UTC, datetime

        afternoon = datetime.fromtimestamp(self.game.now(), UTC).replace(hour=16, minute=1)
        self.clock.value = afternoon.timestamp()
        await Events(self.bot, self.game, self.live, frozenset({ADMIN}), 0).tick()
        self.assertIsNotNone(self.game.repo.active_boss(-100))
