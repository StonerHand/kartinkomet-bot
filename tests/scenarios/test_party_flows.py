"""Games about people end to end: /who polls, the /bomb passed by reply, /bet on life."""

from datetime import UTC, datetime

from aiogram.types import Chat, Message, PhotoSize, Update

from bot.rules import party
from tests.harness import GROUP, BotHarness, user


class PartyFlowsTest(BotHarness):
    async def asyncSetUp(self) -> None:
        await super().asyncSetUp()
        self.remember(*range(2, 8))
        for person in range(2, 7):
            await self.send("привет", sender=person)  # the chat's players, as the bot sees them

    def message_of(self, person: int) -> Message:
        return Message(message_id=700 + person, date=datetime.now(UTC), chat=GROUP, from_user=user(person), text="хм")

    # ── who of us ──────────────────────────────────────────────────────

    async def test_a_poll_from_question_to_title(self) -> None:
        await self.send("/who", sender=2)
        card = self.session.of("SendMessage")[-1]
        self.assertIn("Кто из нас", card.text)
        votes = self.buttons(card)
        self.assertEqual(len(votes), 5)
        found = self.game.repo.open_rounds(-100, "who")[0]
        target = found["options"].index(4)
        for voter in (2, 3, 5):
            await self.press(votes[target], sender=voter)
        await self.send("/who", sender=6)
        self.assertIn("уже идёт", self.session.of("SendEphemeralMessage")[-1].text)
        self.clock.advance(party.WHO_SECONDS)
        await self.live.finish_round(found["id"])
        result = self.session.of("EditMessageText")[-1]
        self.assertIn("итог", result.text)
        self.assertIn("user4", result.text)
        await self.send("/me", sender=4)
        self.assertIn(found["text"].partition("\n")[2], self.texts()[-1] + self.screen())

    async def test_a_question_of_ones_own_costs_coins(self) -> None:
        await self.send("/who кто съест мой йогурт?", sender=3)
        self.assertIn("стоит", self.session.of("SendEphemeralMessage")[-1].text)
        self.fund(3, self.game.who_question_price())
        await self.send("/who кто съест мой йогурт?", sender=3)
        self.assertIn("йогурт", self.session.of("SendMessage")[-1].text)
        self.assertEqual(self.coins(3), 0)

    async def test_the_poll_comes_by_itself_at_one(self) -> None:
        self.at_hour(13)
        await self.events().tick()
        self.assertTrue(any("Кто из нас" in text for text in self.texts()))

    # ── the bomb ───────────────────────────────────────────────────────

    async def test_the_bomb_goes_round_by_reply_and_goes_off(self) -> None:
        await self.send("/bomb", sender=2)
        card = self.session.of("SendMessage")[-1]
        self.assertIn("Бомба", card.text)
        found = self.game.repo.open_rounds(-100, "bomb")[0]
        holder = found["holder"]
        other = next(person for person in range(2, 7) if person != holder)
        await self.send("/rob", sender=holder, reply_to=self.message_of(other))  # a command stays a command
        self.assertEqual(self.game.repo.get_round(found["id"])["holder"], holder)
        await self.send("лови", sender=holder, reply_to=self.message_of(other))
        self.assertEqual(self.game.repo.get_round(found["id"])["holder"], other)
        self.assertTrue(self.session.of("SetMessageReaction"))
        await self.press(f"bm:{found['id']}", sender=holder)  # not theirs any more
        self.assertEqual(self.game.repo.get_round(found["id"])["holder"], other)
        self.clock.advance(party.BOMB_FUSE_SECONDS[1])
        await self.live.finish_round(found["id"])
        self.assertIn("взрыв", self.session.of("EditMessageText")[-1].text)
        self.assertEqual(self.game.badges_of(other), [("bomb", "Жертва бомбы")])

    # ── bets on life ───────────────────────────────────────────────────

    async def test_a_bet_from_claim_to_payout(self) -> None:
        await self.send("/bet", sender=2)
        self.assertIn("О чём спорим", self.session.of("SendEphemeralMessage")[-1].text)
        await self.send("/bet в пятницу половина чата проспит", sender=2)
        card = self.session.of("SendMessage")[-1]
        self.assertIn("проспит", card.text)
        found = self.game.repo.open_rounds(-100, "bet")[0]
        small = self.game.bet_stakes()[0]
        self.fund(3, small)
        self.fund(4, small)
        await self.press(f"sp:{found['id']}:1:0", sender=3)
        await self.press(f"sp:{found['id']}:0:0", sender=4)
        self.assertIn("user3", self.session.of("EditMessageText")[-1].text)
        await self.press(f"sv:{found['id']}:1", sender=3)  # only the author decides
        self.assertEqual(self.game.repo.get_round(found["id"])["status"], "open")
        await self.press(f"sv:{found['id']}:1", sender=2)
        self.assertIn("сбылось", self.session.of("EditMessageText")[-1].text)
        self.assertEqual((self.coins(3), self.coins(4)), (2 * small, 0))

    async def test_a_forgotten_bet_is_called_off_by_the_schedule(self) -> None:
        await self.send("/bet завтра будет снег", sender=2)
        found = self.game.repo.open_rounds(-100, "bet")[0]
        self.fund(3, 500)
        await self.press(f"sp:{found['id']}:1:0", sender=3)
        self.clock.advance(party.BET_DAYS * 86400)
        await self.events().tick()
        self.assertIn("отменён", self.session.of("EditMessageText")[-1].text)
        self.assertEqual(self.coins(3), 500)

    async def test_the_games_need_a_group(self) -> None:
        private = Chat(id=5, type="private")
        await self.send("/bomb", sender=5, chat=private)
        self.assertIn("группового", self.texts()[-1])

    async def test_a_restart_picks_up_open_polls_and_bombs(self) -> None:
        await self.send("/who", sender=2)
        await self.send("/bomb", sender=2)
        await self.live.stop()
        self.assertEqual(self.live.restore(), 2)
        self.assertEqual({key[:2] for key in self.live._tasks}, {"r:"})

    # ── crocodile ──────────────────────────────────────────────────────

    async def test_crocodile_word_for_the_explainer_and_a_guess_in_the_chat(self) -> None:
        await self.send("/croc", sender=2)
        card = self.session.of("SendMessage")[-1]
        self.assertIn("Крокодил", card.text)
        found = self.game.repo.open_rounds(-100, "croc")[0]
        await self.press(f"cw:{found['id']}", sender=3)
        self.assertIn("только тот", self.session.of("AnswerCallbackQuery")[-1].text)
        await self.press(f"cw:{found['id']}", sender=2)
        self.assertIn(found["text"], self.session.of("AnswerCallbackQuery")[-1].text)
        await self.send(found["text"], sender=2)  # the explainer saying it doesn't count
        self.assertEqual(self.game.repo.get_round(found["id"])["status"], "open")
        await self.send("что-то не то", sender=3)
        await self.send(found["text"].upper(), sender=3)
        self.assertEqual(self.game.repo.get_round(found["id"])["status"], "done")
        self.assertIn("угадано", self.session.of("EditMessageText")[-1].text)

    # ── the theme of the day ───────────────────────────────────────────

    async def test_the_theme_from_eleven_to_the_vote(self) -> None:
        self.at_hour(party.THEME_OPEN_HOUR)
        self.game.repo.touch_chat(-100, "чат", self.game.now())
        await self.events().tick()
        found = self.game.repo.open_rounds(-100, "theme")[0]
        theme_card = Message(message_id=found["message_id"], date=datetime.now(UTC), chat=GROUP,
                             from_user=user(999), text="тема")
        for person, file_id in ((3, "ph-3"), (4, "ph-4")):
            photo = Message(message_id=800 + person, date=datetime.now(UTC), chat=GROUP, from_user=user(person),
                            photo=[PhotoSize(file_id=file_id, file_unique_id=file_id, width=1, height=1)],
                            reply_to_message=theme_card)
            await self.dispatcher.feed_update(self.bot, Update(update_id=9000 + person, message=photo))
        self.assertEqual(len(self.game.repo.entries_of(found["id"])), 2)
        self.clock.value = found["ends_at"]
        await self.live.open_theme_vote(found["id"])
        self.assertTrue(self.session.of("SendMediaGroup"))
        await self.press(f"tv:{found['id']}:1", sender=5)
        self.clock.advance(party.THEME_VOTE_SECONDS)
        await self.live.settle_theme(found["id"])
        self.assertIn("итог", self.session.of("EditMessageText")[-1].text)
        self.assertEqual(self.game.badges_of(4), [("theme", "Лучший ответ на тему дня")])

    # ── owning pics ────────────────────────────────────────────────────

    async def test_buying_a_pic_from_its_menu(self) -> None:
        pic = self.game.repo.random_alive(1)[0]
        self.fund(3, self.game.own_price(pic.id))
        await self.press(f"pm:{pic.id}", sender=3)
        menu = self.session.of("SendEphemeralMessage")[-1]
        own = next(data for data in self.buttons(menu) if data.startswith("sh:o:"))
        await self.press(own, sender=3, personal=True)
        self.assertEqual(self.game.repo.owner_of(pic.id)[0], 3)
        self.assertIn("Новый владелец", self.session.of("SendMessage")[-1].text)

    # ── today in the chat ──────────────────────────────────────────────

    async def test_today_shows_the_day_and_what_is_left_for_me(self) -> None:
        self.game.quests_enabled = True
        await self.send("/bomb", sender=2)
        await self.press("m:today", sender=3)
        screen = self.screen()
        self.assertIn("Сегодня в чате", screen)
        self.assertIn("💣 Бомба", screen)
        self.assertIn("бонус дня", screen)
        self.assertIn("daily", self.buttons(self.shown()))
