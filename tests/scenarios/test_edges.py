"""Paths a chat hits sooner or later: refusals, Telegram failures, stale taps, boss counterattacks."""

from unittest import mock

from aiogram.exceptions import TelegramBadRequest
from aiogram.methods import SendDice

from datetime import UTC, datetime

from aiogram.types import Chat, Message

from bot.core import boss as boss_rules
from bot.tg.handlers import challenges as challenges_tg
from bot.tg.handlers import higher as higher_tg
from tests.harness import BOT_USER, GROUP, BotHarness

PRIVATE = Chat(id=5, type="private")


class BossEdgesTest(BotHarness):
    async def summoned(self) -> dict:
        await self.send("/boss", sender=3)
        return self.game.repo.active_boss(-100)

    async def test_cooldown_broke_and_over(self) -> None:
        boss = await self.summoned()
        await self.press(f"bh:{boss['id']}", sender=4)
        await self.press(f"bh:{boss['id']}", sender=4)
        self.assertIn("Замах", self.session.of("AnswerCallbackQuery")[-1].text)
        await self.press(f"bs:{boss['id']}", sender=5)  # no coins
        answer = self.session.of("AnswerCallbackQuery")[-1]
        self.assertTrue(answer.show_alert)
        self.assertIn("Супер-удар стоит", answer.text)
        self.clock.advance(boss_rules.DURATION_SECONDS + 1)
        await self.press(f"bh:{boss['id']}", sender=6)
        self.assertIn("окончен", self.session.of("AnswerCallbackQuery")[-1].text)
        self.assertEqual(self.game.repo.get_boss(boss["id"])["status"], "lost")

    async def test_counterattack_takes_coins_into_the_loot(self) -> None:
        boss = await self.summoned()
        self.fund(4, 500)
        with mock.patch.object(boss_rules, "COUNTER_EVERY", 1):
            await self.press(f"bh:{boss['id']}", sender=4)
        self.assertIn("босс дал сдачи", self.session.of("AnswerCallbackQuery")[-1].text)
        self.assertFalse(any("в добычу" in request.text for request in self.session.of("SendMessage")))  # no chat spam
        await self.live.refresh_boss(boss["id"])
        self.assertIn("😤 <b>user4</b> · −<b>15</b> монет в добычу", self.session.of("EditMessageCaption")[-1].caption)
        self.assertEqual(self.coins(4), 500 - boss_rules.COUNTER_FINE)
        self.assertEqual(self.game.repo.get_boss(boss["id"])["loot"], boss["loot"] + boss_rules.COUNTER_FINE)


class DiceDuelEdgesTest(BotHarness):
    async def test_refusals(self) -> None:
        self.fund(3, 100)
        cases = (("/pvp 10", "Минимальная"), ("/pvp 5000", "Столько у тебя нет"))
        for command, expected in cases:
            await self.send(command, sender=3)
            self.assertIn(expected, self.session.of("SendEphemeralMessage")[-1].text)
        await self.send("/pvp 60", sender=3)
        await self.send("/pvp 60", sender=3)
        self.assertIn("уже висит", self.session.of("SendEphemeralMessage")[-1].text)

    async def test_decline_and_cancel_return_the_stake(self) -> None:
        self.fund(3, 500)
        await self.send("/pvp 200 боулинг", sender=3, reply_to=self.reply_to(4))
        challenge_id = self.buttons(self.session.of("SendMessage")[-1])[0].split(":")[2]
        await self.press(f"cl:n:{challenge_id}", sender=5)
        self.assertIn("не тебе", self.session.of("AnswerCallbackQuery")[-1].text)
        await self.press(f"cl:n:{challenge_id}", sender=4)
        self.assertEqual(self.coins(3), 500)
        self.assertIn("Отказ", self.session.of("EditMessageText")[-1].text)

    async def test_refused_dice_return_both_stakes(self) -> None:
        self.fund(3, 500)
        self.fund(4, 500)
        await self.send("/pvp 200", sender=3, reply_to=self.reply_to(4))
        challenge_id = self.buttons(self.session.of("SendMessage")[-1])[0].split(":")[2]
        self.session.errors["SendDice"] = [TelegramBadRequest(method=SendDice(chat_id=-100), message="Bad Request: no")]
        with self.assertLogs("bot.tg.handlers.challenges", "WARNING"):
            await self.press(f"cl:y:{challenge_id}", sender=4)
        self.assertIn("Ставки вернулись", self.session.of("SendMessage")[-1].text)
        self.assertEqual((self.coins(3), self.coins(4)), (500, 500))
        self.assertEqual(self.game.refund_unthrown_dice_duels(), 0)  # nothing left hanging

    async def test_dice_animation_is_waited(self) -> None:
        self.assertEqual(challenges_tg.DICE_ANIMATION_SCALE, 0)


class HigherEdgesTest(BotHarness):
    async def asyncSetUp(self) -> None:
        await super().asyncSetUp()
        for index, pic in enumerate(self.game.repo.random_alive(10)):
            self.game.repo.set_rating(pic.id, 1000 + index * 10)

        async def collage(bot, pics):
            return b"jpeg"

        patcher = mock.patch.object(higher_tg, "build_collage", collage)
        patcher.start()
        self.addCleanup(patcher.stop)

    async def test_stale_tap_and_a_new_series(self) -> None:
        await self.send("/higher", sender=5, chat=PRIVATE)
        token = self.game.hl_state(5)[0]
        await self.press("hl:0:deadbeef", sender=5, chat=PRIVATE)
        self.assertIn("уже сыгран", self.session.of("AnswerCallbackQuery")[-1].text)
        self.assertEqual(self.game.hl_state(5)[0], token)  # the real round is untouched
        await self.press("hl:new", sender=5, chat=PRIVATE)
        self.assertEqual(len(self.session.of("EditMessageMedia")), 1)
        self.assertNotEqual(self.game.hl_state(5)[0], token)

    async def test_games_button_in_a_group_sends_the_link(self) -> None:
        await self.press("gm:hl", sender=5)
        invite = self.session.of("SendMessage")[-1]
        self.assertIn("личке", invite.text)
        self.assertIsNotNone(invite.reply_markup.inline_keyboard[0][0].url)

    async def test_games_button_in_private_deals(self) -> None:
        await self.press("gm:hl", sender=5, chat=PRIVATE)
        self.assertIn("Выше-ниже", self.session.of("SendPhoto")[-1].caption)


class ButtonRefusalsTest(BotHarness):
    async def test_busy_games_answer_with_a_pop_up(self) -> None:
        self.game.repo.add_pic("f-x", "u-x", 3, None, self.game.now())
        await self.press("gm:whose", sender=4)
        sent = len(self.session.of("SendMessage"))
        await self.press("gm:whose", sender=4)
        answer = self.session.of("AnswerCallbackQuery")[-1]
        self.assertTrue(answer.show_alert)
        self.assertIn("уже идёт", answer.text)
        self.assertEqual(len(self.session.of("SendMessage")), sent)  # nothing new in the chat
        round_ = self.game.repo.active_game(-100, "whose")
        self.clock.advance(31)
        await self.live.advance_game(round_["id"])
        await self.send("/whose", sender=4)
        self.assertIn("через", self.session.of("SendEphemeralMessage")[-1].text)
        await self.press("gm:caption", sender=4)
        await self.press("gm:caption", sender=4)
        self.assertIn("уже идёт", self.session.of("AnswerCallbackQuery")[-1].text)

    async def test_second_horoscope_and_second_boss_are_pop_ups(self) -> None:
        await self.press("gm:horo", sender=4)
        sent = len(self.session.of("SendMessage")) + len(self.session.of("SendPhoto"))
        await self.press("gm:horo", sender=4)
        self.assertTrue(self.session.of("AnswerCallbackQuery")[-1].show_alert)
        await self.press("boss", sender=4)
        await self.press("boss", sender=5)
        answer = self.session.of("AnswerCallbackQuery")[-1]
        self.assertTrue(answer.show_alert)
        self.assertIn("Босс уже тут", answer.text)
        self.assertEqual(len(self.session.of("SendMessage")) + len(self.session.of("SendPhoto")), sent + 1)  # the boss card


class PersonalMessagesTest(BotHarness):
    """What concerns one person reaches only them in a group; the chat sees the events."""

    def public(self) -> list[str]:
        return [request.text for request in self.session.of("SendMessage")]

    async def test_daily_bonus_and_ordinary_chests_are_personal(self) -> None:
        self.game.quests_enabled = True
        await self.send("/daily", sender=4)
        card = self.session.of("SendEphemeralMessage")[-1]
        self.assertIn("Бонус дня", card.text)
        self.assertEqual(card.ephemeral_message_parameters.receiver_user_id, 4)
        self.assertFalse(any("Бонус дня" in text for text in self.public()))
        await self.send("/daily", sender=4)
        self.assertIn("Серия", self.session.of("SendEphemeralMessage")[-1].text)
        self.game.grant_chest(4, "wood", announce=False)
        await self.press("ch:wood:-100", sender=4)
        self.assertIn("Деревянный сундук", self.session.of("SendEphemeralMessage")[-1].text)
        self.assertFalse(any("Сундук" in text for text in self.public()))

    async def test_legendary_chest_is_opened_in_front_of_everyone(self) -> None:
        self.game.grant_chest(4, "legend", announce=False)
        await self.press("ch:legend", sender=4)
        self.assertTrue(any("Легендарный сундук" in text for text in self.public()))

    async def test_falls_back_to_the_chat_if_telegram_refuses(self) -> None:
        self.session.refuse = {"SendEphemeralMessage"}
        self.fund(3, 500)
        await self.send("/rob", sender=3)
        self.assertIn("Ответь командой", self.public()[-1])

    async def test_last_word_gets_a_reaction_not_a_reply(self) -> None:
        pic = self.game.draw_pic(-100)[0]
        trial = self.game.start_court(-100, pic.id, "bottom", None).court
        self.game.repo.set_court_message(trial.id, 777)
        bot_message = Message(message_id=777, date=datetime.now(UTC), chat=GROUP, from_user=BOT_USER, text="суд")
        await self.send("пощадите", sender=1, reply_to=bot_message)
        self.assertEqual(self.session.of("SetMessageReaction")[-1].reaction[0].emoji, "✍")
        self.assertFalse(any("протокол" in text for text in self.public()))
