"""End-to-end handler tests against a fake Telegram session that records every request."""

import unittest
from datetime import UTC, datetime
from itertools import count

from aiogram import Bot
from aiogram.client.session.base import BaseSession
from aiogram.methods import TelegramMethod
from aiogram.types import (
    CallbackQuery,
    Chat,
    File,
    InlineKeyboardMarkup,
    Message,
    PhotoSize,
    Update,
    User,
)

from bot.__main__ import build_dispatcher
from bot.core.arena import DUEL_SECONDS
from bot.core.court import COURT_SECONDS
from bot.tg import upload
from bot.tg.timers import Live
from tests.helpers import make_game
from tests.test_texts import assert_html

BOT_USER = User(id=999, is_bot=True, first_name="kartinkomet", username="kartinkomet_bot")
GROUP = Chat(id=-100, type="supergroup", title="чат")
ADMIN = 1


class FakeSession(BaseSession):
    def __init__(self) -> None:
        super().__init__()
        self.requests: list[TelegramMethod] = []
        self.ids = count(1000)

    async def close(self) -> None:
        pass

    image: bytes | None = None  # served by downloads when a test enables collages

    async def stream_content(self, *args, **kwargs):
        yield self.image or b""

    def message(self, chat_id: int, photo: bool = False) -> Message:
        return Message(
            message_id=next(self.ids),
            date=datetime.now(UTC),
            chat=Chat(id=chat_id, type="private" if chat_id > 0 else "supergroup"),
            from_user=BOT_USER,
            photo=[PhotoSize(file_id="sent", file_unique_id="sent", width=1, height=1)] if photo else None,
        )

    async def make_request(self, bot, method, timeout=None):
        self.requests.append(method)
        name = type(method).__name__
        if name in getattr(self, "refuse", set()):
            from aiogram.exceptions import TelegramBadRequest

            raise TelegramBadRequest(method=method, message="Bad Request: not supported")
        if name == "SendEphemeralMessage":
            return {"message_id": 0}
        if name in ("SendMessage", "SendPhoto", "SendDocument"):
            return self.message(int(method.chat_id), photo=name == "SendPhoto")
        if name == "SendMediaGroup":
            return [self.message(int(method.chat_id)) for _ in method.media]
        if name == "GetMe":
            return BOT_USER
        if name == "GetFile":
            return File(file_id=method.file_id, file_unique_id="x", file_path="photos/x.jpg" if self.image else None)
        return True

    def of(self, name: str) -> list[TelegramMethod]:
        return [request for request in self.requests if type(request).__name__ == name]


def user(user_id: int) -> User:
    return User(id=user_id, is_bot=False, first_name=f"user{user_id}", username=f"user{user_id}")


class BotTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.game, self.clock, temp = make_game(pics=10, uploader=ADMIN)
        self.addCleanup(temp.cleanup)
        self.session = FakeSession()
        self.bot = Bot(token="42:TEST", session=self.session)
        self.live = Live(self.bot, self.game)
        self.dispatcher = build_dispatcher(self.game, self.live, frozenset({ADMIN}))
        self.update_ids = count(1)
        upload.sessions.clear()
        upload._visual_hashes = None

    async def asyncTearDown(self) -> None:
        await self.live.stop()
        # Module-level routers can be attached to one dispatcher only; each test builds a new one.
        for router in self.dispatcher.sub_routers:
            router._parent_router = None
        self.check_outgoing()

    def check_outgoing(self) -> None:
        for request in self.session.requests:
            text = getattr(request, "text", None) or getattr(request, "caption", None)
            if isinstance(text, str):
                assert_html(text)
            markup = getattr(request, "reply_markup", None)
            if isinstance(markup, InlineKeyboardMarkup):
                for row in markup.inline_keyboard:
                    for button in row:
                        if button.callback_data:
                            self.assertLessEqual(len(button.callback_data.encode()), 64, button.callback_data)

    async def send(self, text: str, sender: int = 2, chat: Chat = GROUP, reply_to: Message | None = None) -> None:
        message = Message(
            message_id=next(self.session.ids),
            date=datetime.now(UTC),
            chat=chat,
            from_user=user(sender),
            text=text,
            reply_to_message=reply_to,
        )
        await self.dispatcher.feed_update(self.bot, Update(update_id=next(self.update_ids), message=message))

    async def press(self, data: str, message_id: int = 1, sender: int = 2, chat: Chat = GROUP) -> None:
        message = Message(message_id=message_id, date=datetime.now(UTC), chat=chat, from_user=BOT_USER)
        callback = CallbackQuery(
            id=str(next(self.update_ids)),
            from_user=user(sender),
            chat_instance="ci",
            data=data,
            message=message,
        )
        await self.dispatcher.feed_update(self.bot, Update(update_id=next(self.update_ids), callback_query=callback))

    def buttons(self, request) -> list[str]:
        return [button.callback_data for row in request.reply_markup.inline_keyboard for button in row]

    async def test_menu_replaces_old_panel_and_navigates(self) -> None:
        await self.send("/menu")
        await self.send("/menu")
        self.assertEqual(len(self.session.of("SendMessage")), 2)
        self.assertEqual(len(self.session.of("DeleteMessage")), 1)
        self.assertNotIn("m:adm", self.buttons(self.session.of("SendMessage")[0]))
        for screen in ("m:hall", "m:bottom", "m:grave", "m:top:loved", "m:up", "m:help", "m:home:refresh"):
            await self.press(screen)
        self.assertEqual(len(self.session.of("EditMessageText")), 7)

    async def test_profile_is_private_in_groups(self) -> None:
        await self.press("m:me", sender=3)
        ephemeral = self.session.of("SendEphemeralMessage")
        self.assertEqual(len(ephemeral), 1)
        self.assertEqual(ephemeral[0].ephemeral_message_parameters["receiver_user_id"], 3)
        self.assertEqual(self.session.of("EditMessageText"), [])

    async def test_profile_falls_back_to_panel_if_ephemeral_refused(self) -> None:
        self.session.refuse = {"SendEphemeralMessage"}
        await self.press("m:me", sender=3)
        self.assertIn("USER3", self.session.of("EditMessageText")[-1].text)

    async def test_admin_sees_admin_and_reset_needs_confirmation(self) -> None:
        await self.send("/menu", sender=ADMIN)
        self.assertIn("m:adm", self.buttons(self.session.of("SendMessage")[-1]))
        await self.press("m:adm", sender=2)
        self.assertEqual(self.session.of("EditMessageText"), [])
        await self.press("adm:reset", sender=ADMIN)
        self.assertIn("adm:reset!", self.buttons(self.session.of("EditMessageText")[-1]))

    async def test_pic_reactions_and_court(self) -> None:
        await self.send("/pic")
        photo = self.session.of("SendPhoto")[0]
        buttons = self.buttons(photo)
        self.assertEqual(buttons[2], "pic")
        pic_id = buttons[0].split(":")[2]

        await self.press(f"r:-:{pic_id}", message_id=50, sender=3)
        await self.press(f"r:-:{pic_id}", message_id=50, sender=4)
        court_card = self.session.of("SendPhoto")[-1]
        self.assertTrue(self.buttons(court_card)[0].startswith("c:k:"))
        court_id = self.buttons(court_card)[0].split(":")[2]
        self.assertEqual(self.buttons(self.session.of("EditMessageReplyMarkup")[-1])[0], "trial")

        await self.press(f"c:k:{court_id}", sender=3)
        await self.press(f"c:k:{court_id}", sender=4)
        self.clock.advance(COURT_SECONDS + 1)
        await self.live.finish_court(court_id)
        self.assertIn("КАЗНЕНА", self.session.of("EditMessageCaption")[-1].caption)
        emojis = [r.reaction[0].emoji for r in self.session.of("SetMessageReaction")]
        self.assertIn("🤡", emojis)  # verdict
        self.assertIn("🎉", emojis)  # voters got the "first blood" achievement
        self.assertEqual(self.game.repo.get_pic(pic_id).status, "executed")

    async def test_last_word_from_uploader(self) -> None:
        pic = self.game.draw_pic(-100)[0]
        trial = self.game.start_court(-100, pic.id, "bottom", 2).court
        self.game.repo.set_court_message(trial.id, 77)
        court_message = Message(message_id=77, date=datetime.now(UTC), chat=GROUP, from_user=BOT_USER)
        await self.send("пощадите, она смешная", sender=ADMIN, reply_to=court_message)
        self.assertEqual(self.game.repo.get_court(trial.id).last_word, "пощадите, она смешная")
        await self.send("а я тоже хочу", sender=5, reply_to=court_message)
        self.assertEqual(self.game.repo.get_court(trial.id).last_word, "пощадите, она смешная")

    async def test_duel_and_champion(self) -> None:
        await self.send("/duel")
        self.assertEqual(len(self.session.of("SendMediaGroup")), 1)
        card = self.session.of("SendMessage")[-1]
        battle_id = self.buttons(card)[0].split(":")[1]
        await self.press(f"v:{battle_id}:1", sender=3)
        await self.send("/duel")
        self.assertEqual(len(self.session.of("SendMediaGroup")), 1)
        self.clock.advance(DUEL_SECONDS + 1)
        await self.live.finish_battle(battle_id)
        result = self.session.of("EditMessageText")[-1]
        self.assertIn(f"d:ch:{battle_id}", self.buttons(result))
        await self.press(f"d:ch:{battle_id}")
        self.assertEqual(len(self.session.of("SendMediaGroup")), 2)
        self.assertIn("чемпионка, серия <b>1</b>", self.session.of("SendMessage")[-1].text)
        self.assertEqual(self.session.of("SetMessageReaction")[0].reaction[0].emoji, "🏆")

    async def test_tournament(self) -> None:
        await self.press("t:new")
        self.assertEqual(len(self.session.of("SendMediaGroup")[0].media), 4)

    async def test_upload_in_private(self) -> None:
        private = Chat(id=5, type="private")
        await self.send("/upload", sender=5, chat=private)
        photo = Message(
            message_id=next(self.session.ids),
            date=datetime.now(UTC),
            chat=private,
            from_user=user(5),
            photo=[PhotoSize(file_id="new-file", file_unique_id="new-uniq", width=10, height=10)],
        )
        await self.dispatcher.feed_update(self.bot, Update(update_id=next(self.update_ids), message=photo))
        await self.dispatcher.feed_update(self.bot, Update(update_id=next(self.update_ids), message=photo))
        self.assertTrue(self.game.repo.pic_known("new-uniq"))
        self.assertEqual(upload.sessions[5].added, 1)
        self.assertEqual(upload.sessions[5].duplicates, 1)
        self.assertTrue(any("Первый вброс" in (r.text or "") for r in self.session.of("SendMessage")))
        await self.send("/done", sender=5, chat=private)
        self.assertNotIn(5, upload.sessions)

    async def test_upload_refused_in_group(self) -> None:
        await self.send("/upload")
        self.assertIn("только в личке", self.session.of("SendMessage")[-1].text)


    async def test_v1_reaction_buttons_still_work(self) -> None:
        pic = self.game.draw_pic(-100)[0]
        await self.press(f"react:like:{pic.id}", message_id=60, sender=3)
        self.assertEqual(self.game.repo.get_pic(pic.id).likes, 1)
        self.assertEqual(self.buttons(self.session.of("EditMessageReplyMarkup")[-1])[0], f"r:+:{pic.id}")

    async def test_unknown_buttons_are_answered(self) -> None:
        await self.press("menu_random")
        answer = self.session.of("AnswerCallbackQuery")[-1]
        self.assertIn("/menu", answer.text)

    async def test_dead_timer_does_not_block_the_arena(self) -> None:
        stuck = self.game.start_duel(-100).battle
        self.clock.advance(DUEL_SECONDS + 100)
        await self.send("/duel")
        self.assertEqual(self.game.repo.get_battle(stuck.id).status, "done")
        self.assertIsNotNone(self.game.repo.active_battle(-100, "duel"))

    async def test_votes_are_batched_into_one_edit(self) -> None:
        import bot.tg.timers as timers

        timers.REFRESH_DELAY = 0.05
        self.addCleanup(setattr, timers, "REFRESH_DELAY", 1.5)
        battle = self.game.start_duel(-100).battle
        self.game.repo.set_battle_message(battle.id, 70)
        for voter in range(3, 8):
            await self.press(f"v:{battle.id}:0", sender=voter)
        import asyncio

        await asyncio.sleep(0.2)
        edits = [r for r in self.session.of("EditMessageText") if r.message_id == 70]
        self.assertEqual(len(edits), 1)
        self.assertIn("<b>5</b>", edits[0].text)

    async def test_rules_and_live_line_on_panel(self) -> None:
        self.game.start_duel(-100)
        await self.send("/menu")
        self.assertIn("Сейчас идёт", self.session.of("SendMessage")[-1].text)
        await self.press("m:help")
        self.assertIn("Народный суд", self.session.of("EditMessageText")[-1].text)

    async def test_same_photo_twice_in_parallel_is_one_pic(self) -> None:
        self.assertIsNotNone(self.game.add_pic("same", "same-uniq", 5, None))
        self.assertIsNone(self.game.add_pic("same", "same-uniq", 5, None))


    async def test_duel_is_one_numbered_collage_message(self) -> None:
        from io import BytesIO

        from PIL import Image

        buffer = BytesIO()
        Image.new("RGB", (300, 200), (200, 30, 30)).save(buffer, "JPEG")
        self.session.image = buffer.getvalue()

        await self.send("/duel")
        self.assertEqual(self.session.of("SendMediaGroup"), [])
        card = self.session.of("SendPhoto")[-1]
        self.assertIn("ДУЭЛЬ", card.caption)
        battle_id = self.buttons(card)[0].split(":")[1]
        self.assertTrue(self.game.repo.get_battle(battle_id).card_is_photo)

        await self.press(f"v:{battle_id}:0", sender=3)
        self.clock.advance(DUEL_SECONDS + 1)
        await self.live.finish_battle(battle_id)
        self.assertIn("ИТОГ ДУЭЛИ", self.session.of("EditMessageCaption")[-1].caption)


if __name__ == "__main__":
    unittest.main()
