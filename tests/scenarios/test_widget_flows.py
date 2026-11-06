"""HTML widgets end to end: the admin's switch, every game as a widget, taps routed to the game,
redraws as data edits, results as captions, and the fallback to cards when Telegram refuses."""

import json
from unittest import mock

from aiogram.types import Chat

from bot.app.main import update_types
from bot.rules import table
from tests.harness import ADMIN, BotHarness


class WidgetFlowsTest(BotHarness):
    async def asyncSetUp(self) -> None:
        await super().asyncSetUp()
        self.remember(*range(2, 8))
        for person in range(2, 6):
            await self.send("привет", sender=person)

    async def widgets_on(self) -> None:
        await self.send("/menu", sender=ADMIN)
        await self.press("adm:widgets", sender=ADMIN)
        self.assertIn("Виджеты включены", self.session.of("AnswerCallbackQuery")[-1].text)

    def widget(self) -> tuple[int, dict]:
        """The last widget sent: its message id (from the bot's registry) and its first data."""
        sent = self.session.of("SendWidget")[-1]
        self.assertIn("<script>", sent.html)
        keys = [row[0] for row in self.game.repo.db.execute("SELECT key FROM meta WHERE key LIKE 'wmsg:-100:%'")]
        message_id = max(int(key.rsplit(":", 1)[1]) for key in keys)
        data = sent.chat_data if sent.chat_data is not None else sent.public_data
        return message_id, json.loads(data)

    def last_data(self) -> dict:
        return json.loads(self.session.of("EditMessageWidgetData")[-1].chat_data)

    async def test_the_switch_lives_in_the_groups_admin_panel(self) -> None:
        await self.send("/admin", sender=ADMIN, chat=Chat(id=ADMIN, type="private"))
        private = self.session.of("SendMessage")[-1]
        self.assertNotIn("adm:widgets", self.buttons(private))
        self.assertIn("включаются в /admin группового чата", private.text)
        await self.send("/admin", sender=ADMIN)
        group = self.session.of("SendMessage")[-1]
        self.assertIn("adm:widgets", self.buttons(group))
        self.assertNotIn("группового чата", group.text)

    async def test_games_stay_cards_until_the_admin_switches_widgets_on(self) -> None:
        await self.send("/mines", sender=2)
        self.assertEqual(self.session.of("SendWidget"), [])
        self.assertIn("Сапёр", self.session.of("SendMessage")[-1].text)

    async def test_the_minefield_as_a_widget(self) -> None:
        await self.widgets_on()
        await self.send("/mines", sender=2)
        found = self.game.repo.open_rounds(-100, "mines")[0]
        message_id = found["message_id"]
        self.assertEqual(self.session.of("SendWidget")[-1].caption, "🧨 <b>Сапёр</b>")
        mines = json.loads(found["text"])["mines"]
        safe = next(cell for cell in range(16) if cell not in mines)
        answer = await self.tap_widget(message_id, f"o{safe}", sender=3)
        self.assertEqual(answer, {"s": "safe", "v": table.cell_value(0)})
        await self.live.refresh_round(found["id"])
        self.assertEqual(self.last_data()["o"], [safe])
        self.assertEqual(self.last_data()["p"], [["user3", table.cell_value(0)]])
        self.assertEqual((await self.tap_widget(message_id, f"o{mines[0]}", sender=4))["s"], "boom")
        final = self.last_data()
        self.assertEqual((final["x"], final["b"], sorted(final["m"])), (1, "user4", sorted(mines)))
        self.assertIn("взрыв", self.session.of("EditMessageCaption")[-1].caption)

    async def test_a_refused_widget_becomes_the_usual_card(self) -> None:
        await self.widgets_on()
        self.session.refuse = {"SendWidget"}
        with self.assertLogs("bot.telegram.widgets", "WARNING"):
            await self.send("/safe", sender=2)
        self.assertIn("Сейф", self.session.of("SendMessage")[-1].text)
        self.assertFalse(self.live.is_widget_round(self.game.repo.open_rounds(-100, "safe")[0]["id"]))
        await self.press("adm:health", sender=ADMIN)
        self.assertIn("ещё не открыл", self.screen())

    async def test_the_safe_as_a_widget(self) -> None:
        await self.widgets_on()
        await self.send("/safe", sender=2)
        found = self.game.repo.open_rounds(-100, "safe")[0]
        code = json.loads(found["text"])["code"]
        self.fund(3, 100)
        self.assertEqual((await self.tap_widget(found["message_id"], "t1123", sender=3))["s"], "invalid")
        answer = await self.tap_widget(found["message_id"], f"t{code[::-1]}", sender=3)
        self.assertEqual((answer["s"], answer["e"] + answer["n"]), ("miss", 4))
        self.fund(4, 100)
        self.assertEqual((await self.tap_widget(found["message_id"], f"t{code}", sender=4))["s"], "cracked")
        final = self.last_data()
        self.assertEqual((final["x"], final["k"], final["w"]), (1, code, "user4"))
        self.assertIn("вскрыт", self.session.of("EditMessageCaption")[-1].caption)

    async def test_the_spy_as_a_widget_shows_each_player_their_own_word(self) -> None:
        await self.widgets_on()
        await self.send("/spy", sender=2)
        found = self.game.repo.open_rounds(-100, "spy")[0]
        message_id = found["message_id"]
        for person in (3, 4):
            self.assertEqual(await self.tap_widget(message_id, "j", sender=person), {"s": "ok"})
        self.assertEqual(await self.tap_widget(message_id, "s", sender=2), {"s": "ok"})
        spy = json.loads(self.game.repo.get_round(found["id"])["text"])["spy"]
        self.assertEqual(await self.tap_widget(message_id, "w", sender=spy), {"spy": 1})
        other = next(person for person in (2, 3, 4) if person != spy)
        self.assertIn("w", await self.tap_widget(message_id, "w", sender=other))
        self.assertEqual(await self.tap_widget(message_id, "w", sender=6), {"s": "not_player"})
        self.assertEqual(self.last_data()["f"], "talk")

    async def test_board_duels_as_widgets(self) -> None:
        await self.widgets_on()
        self.fund(3, 500)
        self.fund(4, 500)
        await self.send("/ttt 100", sender=3, reply_to=self.reply_to(4))
        challenge_id = self.buttons(self.session.of("SendMessage")[-1])[0].split(":")[2]
        await self.press(f"cl:y:{challenge_id}", sender=4)
        message_id, data = self.widget()
        self.assertEqual((data["b"], data["n"], data["u"]), (".........", ["user3", "user4"], 0))
        self.assertEqual(await self.tap_widget(message_id, "m4", sender=4), {"s": "not_turn"})
        for user, cell in ((3, 0), (4, 3), (3, 1), (4, 4)):
            self.assertEqual(await self.tap_widget(message_id, f"m{cell}", sender=user), {"s": "ok"})
        await self.live.refresh_duel(challenge_id)
        self.assertEqual(self.last_data()["b"], "XX.OO....")
        self.assertEqual(await self.tap_widget(message_id, "m2", sender=3), {"s": "done"})
        self.assertEqual(self.last_data()["z"], {"w": "user3", "late": "", "line": [0, 1, 2]})
        self.assertEqual(self.coins(3), 600)

    async def test_the_games_screen_offers_the_machine_once_widgets_are_on(self) -> None:
        await self.widgets_on()
        await self.send("/games", sender=3)
        games = self.session.of("SendEphemeralMessage")[-1]
        self.assertIn("gm:machine", self.buttons(games))
        self.assertIn("Виджеты включены", games.text)
        await self.press("gm:machine", sender=3)
        self.assertEqual(self.session.of("SendWidget")[-1].caption, "🎰 <b>Автомат</b>")

    async def test_one_slot_machine_for_the_whole_chat(self) -> None:
        await self.send("/machine", sender=3)
        self.assertIn("выключены", self.session.of("SendEphemeralMessage")[-1].text)
        await self.widgets_on()
        await self.send("/machine", sender=3)
        message_id, data = self.widget()
        self.assertEqual(data, {"f": []})
        self.fund(4, 1000)
        with mock.patch.object(self.game.rng, "randint", return_value=64):  # 7-7-7
            answer = await self.tap_widget(message_id, "s", sender=4)
        self.assertEqual((answer["v"], answer["k"]), (64, 100))
        self.assertEqual(answer["b"], self.coins(4))
        self.assertGreater(answer["w"], answer["k"])
        self.assertEqual(self.last_data()["f"][0][0], "user4")  # a big win goes to the feed
        self.assertEqual(await self.tap_widget(message_id, "s", sender=5), {"e": "broke"})

    async def test_the_live_board(self) -> None:
        await self.send("/board", sender=3)
        self.assertIn("Табло", self.session.of("SendMessage")[-1].text)
        await self.widgets_on()
        await self.send("/board", sender=3)
        sent = self.session.of("SendWidget")[-1]
        self.assertTrue(sent.is_shared)
        shared_id = self.game.repo.meta_str("board:-100")
        self.assertTrue(shared_id)
        self.game.repo.touch_chat(-100, "чат", self.game.now())
        self.game.pay(5, 50, "vote")
        await self.events().tick()
        edit = self.session.of("EditSharedWidgetData")[-1]
        self.assertEqual(edit.widget_id, shared_id)
        self.assertEqual(json.loads(edit.public_data)["s"][0][0], "user5")
        await self.events().tick()  # nothing changed: nothing sent
        self.assertEqual(len(self.session.of("EditSharedWidgetData")), 1)

    async def test_a_tap_on_something_unknown_is_answered(self) -> None:
        self.assertEqual(await self.tap_widget(4242, "o1", sender=3), {"s": "gone"})

    async def test_polling_asks_for_widget_taps_unless_telegram_refuses(self) -> None:
        self.assertIn("widget_query", await update_types(self.bot, self.dispatcher))
        from aiogram.exceptions import TelegramBadRequest
        from aiogram.methods import GetUpdates

        self.session.errors["GetUpdates"] = [TelegramBadRequest(method=GetUpdates(), message="Bad Request: bad type")]
        with self.assertLogs("kartinkomet", "WARNING"):
            types = await update_types(self.bot, self.dispatcher)
        self.assertNotIn("widget_query", types)
        self.assertIn("callback_query", types)
