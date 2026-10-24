"""v5 paths a chat hits sooner or later: refusals, Telegram failures, stale taps, boss counterattacks."""

from unittest import mock

from aiogram.exceptions import TelegramBadRequest
from aiogram.methods import SendDice

from datetime import UTC, datetime

from aiogram.types import Chat, Message

from bot.core import boss as boss_rules
from bot.tg import challenges as challenges_tg
from bot.tg import higher as higher_tg
from tests.test_bot import GROUP, BotHarness, user

PRIVATE = Chat(id=5, type="private")


class Harness(BotHarness):
    """Helpers only: test classes below inherit no tests from it."""

    async def asyncSetUp(self) -> None:
        await super().asyncSetUp()
        challenges_tg.DICE_ANIMATION_SCALE = 0

    def fund(self, user_id: int, amount: int) -> None:
        self.game.repo.add_coins(user_id, amount, "test", self.game.now(), earn=False)

    def coins(self, user_id: int) -> int:
        return self.game.repo.player(user_id)[0]

    def reply_to(self, user_id: int) -> Message:
        return Message(message_id=500, date=datetime.now(UTC), chat=GROUP, from_user=user(user_id), text="привет")


class BossEdgesTest(Harness):
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
        counter = self.session.of("SendMessage")[-1]
        self.assertIn("в добычу", counter.text)
        self.assertEqual(self.coins(4), 500 - boss_rules.COUNTER_FINE)
        self.assertEqual(self.game.repo.get_boss(boss["id"])["loot"], boss["loot"] + boss_rules.COUNTER_FINE)


class DiceDuelEdgesTest(Harness):
    async def test_refusals(self) -> None:
        self.fund(3, 100)
        cases = (("/pvp 10", "Минимальная"), ("/pvp 5000", "Столько у тебя нет"))
        for command, expected in cases:
            await self.send(command, sender=3)
            self.assertIn(expected, self.session.of("SendMessage")[-1].text)
        await self.send("/pvp 60", sender=3)
        await self.send("/pvp 60", sender=3)
        self.assertIn("уже висит", self.session.of("SendMessage")[-1].text)

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
        with self.assertLogs("bot.tg.challenges", "WARNING"):
            await self.press(f"cl:y:{challenge_id}", sender=4)
        self.assertIn("Ставки вернулись", self.session.of("SendMessage")[-1].text)
        self.assertEqual((self.coins(3), self.coins(4)), (500, 500))
        self.assertEqual(self.game.refund_unthrown_dice_duels(), 0)  # nothing left hanging

    async def test_dice_animation_is_waited(self) -> None:
        self.assertEqual(challenges_tg.DICE_ANIMATION_SCALE, 0)


class HigherEdgesTest(Harness):
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
        self.assertIn("ВЫШЕ-НИЖЕ", self.session.of("SendPhoto")[-1].caption)


class ButtonRefusalsTest(Harness):
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
        self.assertIn("через", self.session.of("SendMessage")[-1].text)
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
