"""Board duels end to end: /rps and /ttt from the challenge to the pot, the panel buttons, a restart."""

from bot.live.timers import Live
from bot.rules import duels
from tests.harness import BotHarness


class DuelFlowsTest(BotHarness):
    async def asyncSetUp(self) -> None:
        await super().asyncSetUp()
        self.remember(*range(2, 8))
        self.fund(3, 500)
        self.fund(4, 500)

    async def accept(self, command: str) -> str:
        await self.send(command, sender=3, reply_to=self.reply_to(4))
        challenge_id = self.buttons(self.session.of("SendMessage")[-1])[0].split(":")[2]
        await self.press(f"cl:y:{challenge_id}", sender=4)
        return challenge_id

    async def test_rock_paper_scissors_from_the_call_to_the_pot(self) -> None:
        challenge_id = await self.accept("/rps 200")
        board = self.session.of("SendMessage")[-1]
        self.assertIn("Камень, ножницы, бумага", board.text)
        self.assertEqual(len(self.buttons(board)), 3)
        await self.press(f"rp:{challenge_id}:2", sender=3)  # paper
        self.assertIn("Ждём соперника", self.session.of("AnswerCallbackQuery")[-1].text)
        await self.press(f"rp:{challenge_id}:0", sender=5)
        self.assertIn("не твоя", self.session.of("AnswerCallbackQuery")[-1].text)
        await self.press(f"rp:{challenge_id}:0", sender=4)  # rock loses to paper
        result = self.session.of("EditMessageText")[-1].text
        self.assertIn("итог", result)
        self.assertIn("бумага", result)
        self.assertEqual((self.coins(3), self.coins(4)), (700, 300))

    async def test_tic_tac_toe_from_the_call_to_three_in_a_row(self) -> None:
        challenge_id = await self.accept("/pvp 100 крестики")
        board = self.session.of("SendMessage")[-1]
        self.assertIn("Крестики-нолики", board.text)
        self.assertEqual(len(self.buttons(board)), 9)
        await self.press(f"tt:{challenge_id}:4", sender=4)
        self.assertIn("не твой ход", self.session.of("AnswerCallbackQuery")[-1].text)
        for user, cell in ((3, 0), (4, 3), (3, 1), (4, 4)):
            await self.press(f"tt:{challenge_id}:{cell}", sender=user)
        self.assertIn("⭕", [button.text for row in self.session.of("EditMessageText")[-1].reply_markup.inline_keyboard
                            for button in row])  # the board is redrawn after each move
        await self.press(f"tt:{challenge_id}:2", sender=3)
        result = self.session.of("EditMessageText")[-1]
        self.assertIn("забирает", result.text)
        self.assertTrue(all(data.endswith(":x") for data in self.buttons(result)[:9]))
        self.assertIn(f"rm:{challenge_id}", self.buttons(result))
        self.assertEqual((self.coins(3), self.coins(4)), (600, 400))

    async def test_the_clock_decides_a_move_never_made(self) -> None:
        challenge_id = await self.accept("/ttt 100")
        self.clock.advance(duels.TTT_MOVE_SECONDS)
        await self.live._duel_loop(challenge_id)
        self.assertIn("кончилось время", self.session.of("EditMessageText")[-1].text)
        self.assertEqual(self.coins(4), 600)  # X (the challenger) didn't move

    async def test_the_people_screen_starts_them(self) -> None:
        await self.press("pp:rps", sender=3)
        self.assertIn("✊ <b>Какая ставка?</b>", self.screen())  # then whom; the challenge card follows

    async def test_a_restart_picks_the_board_up(self) -> None:
        challenge_id = await self.accept("/rps 100")
        await self.live.stop()
        self.live = Live(self.bot, self.game)
        self.assertGreaterEqual(self.live.restore(), 1)
        self.assertIn(f"du:{challenge_id}", self.live._tasks)
