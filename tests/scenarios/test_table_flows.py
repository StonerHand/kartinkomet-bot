"""The menu of ten doors and the new games end to end: /spy, /mines, /safe, /pieces, the auction
and the team week, through the dispatcher and the fake Telegram."""

import json
from datetime import UTC, datetime
from io import BytesIO

from aiogram.types import Message
from PIL import Image

from bot.app.main import GROUP_COMMANDS
from bot.rules import games, table, teams
from tests.harness import GROUP, BotHarness, user


class MenuTest(BotHarness):
    def test_the_menu_has_ten_doors(self) -> None:
        self.assertEqual([command.command for command in GROUP_COMMANDS],
                         ["menu", "pic", "duel", "games", "people", "casino", "today", "me", "top", "help"])

    async def test_each_door_opens_its_screen_for_the_one_who_asked(self) -> None:
        for command, title in (("/games", "Игры"), ("/people", "Люди"), ("/today", "Сегодня в чате")):
            await self.send(command, sender=3)
            screen = self.session.of("SendEphemeralMessage")[-1]
            self.assertIn(title, screen.text)

    async def test_the_games_screen_starts_the_new_games(self) -> None:
        await self.send("/games", sender=3)
        buttons = self.buttons(self.session.of("SendEphemeralMessage")[-1])
        for data in ("gm:spy", "gm:mines", "gm:safe", "gm:piece"):
            self.assertIn(data, buttons)
        await self.press("gm:mines", sender=3)
        self.assertIn("Сапёр", self.session.of("SendMessage")[-1].text)


class TableFlowsTest(BotHarness):
    async def asyncSetUp(self) -> None:
        await super().asyncSetUp()
        self.remember(*range(2, 8))

    def reply(self, message_id: int) -> Message:
        """The bot's card, as a message to reply to."""
        return Message(message_id=message_id, date=datetime.now(UTC), chat=GROUP, from_user=user(999), text="card")

    async def test_the_spy_from_recruiting_to_the_verdict(self) -> None:
        await self.send("/spy", sender=2)
        found = self.game.repo.open_rounds(-100, "spy")[0]
        self.assertIn("Шпион", self.session.of("SendMessage")[-1].text)
        for person in (3, 4):
            await self.press(f"sy:j:{found['id']}", sender=person)
        await self.press(f"sy:w:{found['id']}", sender=3)
        self.assertIn("закончится сбор", self.session.of("AnswerCallbackQuery")[-1].text)
        self.clock.advance(table.SPY_RECRUIT_SECONDS)
        await self.live.advance_spy(found["id"])
        spy = json.loads(self.game.repo.get_round(found["id"])["text"])["spy"]
        await self.press(f"sy:w:{found['id']}", sender=spy)
        self.assertIn("Ты шпион", self.session.of("AnswerCallbackQuery")[-1].text)
        civilian = next(person for person in (2, 3, 4) if person != spy)
        await self.press(f"sy:w:{found['id']}", sender=civilian)
        self.assertIn("Твоё слово", self.session.of("AnswerCallbackQuery")[-1].text)
        self.clock.advance(table.SPY_TALK_SECONDS)
        await self.live.advance_spy(found["id"])
        vote = self.session.of("EditMessageText")[-1]
        self.assertIn("голосование", vote.text)
        players = self.game.spy_players(self.game.repo.get_round(found["id"]))
        for person in players:
            if person != spy:
                await self.press(f"sy:v:{found['id']}:{players.index(spy)}", sender=person)
        self.clock.advance(table.SPY_VOTE_SECONDS)
        await self.live.advance_spy(found["id"])
        result = self.session.of("EditMessageText")[-1].text
        self.assertIn("пойман", result)
        self.assertIn(f"user{spy}", result)

    async def test_the_spy_moves_on_as_soon_as_everyone_is_done(self) -> None:
        await self.send("/spy", sender=2)
        found = self.game.repo.open_rounds(-100, "spy")[0]
        phase = lambda: json.loads(self.game.repo.get_round(found["id"])["text"])["phase"]  # noqa: E731
        await self.press(f"sy:s:{found['id']}", sender=2)
        self.assertIn("хотя бы", self.session.of("AnswerCallbackQuery")[-1].text)
        for person in (3, 4):
            await self.press(f"sy:j:{found['id']}", sender=person)
        await self.press(f"sy:s:{found['id']}", sender=3)
        self.assertIn("только тот", self.session.of("AnswerCallbackQuery")[-1].text)
        await self.press(f"sy:s:{found['id']}", sender=2)  # no clock moved from here on
        self.assertEqual(phase(), "talk")
        for person in (2, 3):
            await self.press(f"sy:r:{found['id']}", sender=person)
        talk, _ = self.live.round_card(self.game.repo.get_round(found["id"]))
        self.assertIn("готовы: <b>2</b> из 3", talk)
        await self.press(f"sy:r:{found['id']}", sender=4)
        self.assertEqual(phase(), "vote")
        players = self.game.spy_players(self.game.repo.get_round(found["id"]))
        for person in players:
            target = next(other for other in players if other != person)
            await self.press(f"sy:v:{found['id']}:{players.index(target)}", sender=person)
        self.assertEqual(self.game.repo.get_round(found["id"])["status"], "done")
        self.assertIn("Шпион", self.session.of("EditMessageText")[-1].text)

    async def test_a_game_button_answers_before_the_card_goes_out(self) -> None:
        buffer = BytesIO()
        Image.new("RGB", (300, 200), (30, 120, 200)).save(buffer, "JPEG")
        self.session.image = buffer.getvalue()
        await self.press("gm:piece", sender=3)
        kinds = [self.session.kind(request) for request in self.session.requests]
        self.assertLess(kinds.index("AnswerCallbackQuery"), kinds.index("SendPhoto"))
        self.assertIn("Режу", self.session.of("AnswerCallbackQuery")[0].text)

    async def test_the_minefield_pays_and_burns(self) -> None:
        await self.send("/mines", sender=2)
        found = self.game.repo.open_rounds(-100, "mines")[0]
        card = self.session.of("SendMessage")[-1]
        self.assertEqual(len(self.buttons(card)), table.MINES_SIDE ** 2 + 1)
        mines = json.loads(found["text"])["mines"]
        safe = [cell for cell in range(table.MINES_SIDE ** 2) if cell not in mines]
        await self.press(f"mn:{found['id']}:{safe[0]}", sender=2)
        self.assertIn("Пусто", self.session.of("AnswerCallbackQuery")[-1].text)
        await self.press(f"mn:{found['id']}:c", sender=2)
        self.assertEqual(self.coins(2), table.cell_value(0))
        await self.press(f"mn:{found['id']}:{safe[1]}", sender=3)
        await self.press(f"mn:{found['id']}:{mines[0]}", sender=4)
        result = self.session.of("EditMessageText")[-1]
        self.assertIn("взрыв", result.text)
        self.assertIn("user3", result.text)  # what burned
        self.assertTrue(all(data.endswith(":x") for data in self.buttons(result)[:table.MINES_SIDE ** 2]))
        await self.press(f"mn:{found['id']}:x", sender=5)
        self.assertIn("закрыто", self.session.of("AnswerCallbackQuery")[-1].text)

    async def test_the_safe_by_replies_and_by_command(self) -> None:
        await self.send("/safe", sender=2)
        found = self.game.repo.open_rounds(-100, "safe")[0]
        code = json.loads(found["text"])["code"]
        card = self.reply(found["message_id"])
        await self.send("12", sender=3, reply_to=card)
        self.assertIn("разные цифры", self.session.of("SendEphemeralMessage")[-1].text)
        self.fund(3, 100)
        await self.send(code[::-1], sender=3, reply_to=card)
        self.assertEqual(self.session.of("SetMessageReaction")[-1].reaction[0].emoji, "👀")
        self.assertEqual(self.coins(3), 100 - table.SAFE_GUESS_PRICE)
        self.fund(4, 100)
        await self.send(f"/safe {code}", sender=4)
        result = self.session.of("EditMessageText")[-1].text
        self.assertIn("вскрыт", result)
        self.assertEqual(self.coins(4), 100 + table.SAFE_GUESS_PRICE + table.SAFE_SEED)  # their try back, and the other one

    async def test_pic_by_pieces_grows_and_settles(self) -> None:
        buffer = BytesIO()
        Image.new("RGB", (300, 200), (30, 120, 200)).save(buffer, "JPEG")
        self.session.image = buffer.getvalue()
        await self.send("/pieces", sender=2)
        found = self.game.repo.open_rounds(-100, "piece")[0]
        self.assertIn("Пикча по кусочку", self.session.of("SendPhoto")[-1].caption)
        answer = self.game.piece_state(found)["answer"]
        await self.press(f"pc:{found['id']}:{answer}", sender=3)
        self.assertIn("Ответ принят", self.session.of("AnswerCallbackQuery")[-1].text)
        for _ in games.PIECE_ZOOMS:
            self.clock.advance(games.PIECE_STAGE_SECONDS)
            await self.live.advance_piece(found["id"])
        edits = self.session.of("EditMessageMedia")
        self.assertEqual(len(edits), len(games.PIECE_ZOOMS))
        self.assertIn("итог", edits[-1].media.caption)
        self.assertIn("user3", edits[-1].media.caption)
        self.assertEqual(self.coins(3), games.PIECE_REWARDS[0])

    async def test_pieces_need_the_pics_to_download(self) -> None:
        await self.send("/pieces", sender=2)
        self.assertIn("Не получилось", self.session.of("SendEphemeralMessage")[-1].text)
        self.assertEqual(self.game.repo.open_rounds(-100, "piece"), [])

    async def test_the_auction_opens_at_three_and_sells_at_ten(self) -> None:
        self.game.repo.touch_chat(-100, "чат", self.game.now())
        self.at_hour(15)
        await self.events().tick()
        card = next(request for request in self.session.of("SendMessage") if "Аукцион" in request.text)
        found = self.game.repo.open_rounds(-100, "auction")[0]
        self.fund(3, 5000)
        await self.press(f"au:{found['id']}:1", sender=3)
        self.assertIn("видишь только ты", self.session.of("AnswerCallbackQuery")[-1].text)
        await self.press(f"au:{found['id']}:m", sender=3)
        self.assertIn("200", self.session.of("AnswerCallbackQuery")[-1].text)
        self.assertIsNotNone(card)
        self.at_hour(22)
        await self.events().tick()
        sold = [request.text for request in self.session.of("EditMessageText") if "продано" in request.text]
        self.assertTrue(sold)
        self.assertEqual(self.coins(3), 5000 - 50)

    async def test_the_team_week_from_monday_to_sunday(self) -> None:
        self.game.repo.touch_chat(-100, "чат", self.game.now())
        for person in range(2, 8):
            await self.send("привет", sender=person)
        self.at_hour(teams.START[1], weekday=teams.START[0])
        await self.events().tick()
        self.assertTrue(any("Командная неделя" in text for text in self.texts()))
        week = self.game.team_week(-100)
        red = next(person for person, colour in week.teams.items() if colour == "red")
        self.game.repo.add_coins(red, 100, "vote", self.game.now())
        await self.send("/today", sender=red)
        self.assertIn("твои", self.session.of("SendEphemeralMessage")[-1].text)
        self.at_hour(teams.END[1], weekday=teams.END[0])
        await self.events().tick()
        self.assertTrue(any("Победили Красные" in text for text in self.texts()))
        self.assertEqual(self.game.badges_of(red), [("team", "Победа в командной неделе")])

    async def test_a_command_in_reply_to_the_safe_stays_a_command(self) -> None:
        await self.send("/safe", sender=2)
        found = self.game.repo.open_rounds(-100, "safe")[0]
        await self.send("/pic", sender=3, reply_to=self.reply(found["message_id"]))
        self.assertFalse(any("разные цифры" in request.text for request in self.session.of("SendEphemeralMessage")))
        self.assertTrue(self.session.of("SendPhoto"))  # the pic came
