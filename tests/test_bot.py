"""End-to-end handler tests against a fake Telegram session that records every request."""

import json
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
    TelegramObject,
    Update,
    User,
    WebhookInfo,
)

from bot.__main__ import build_dispatcher
from bot.core.arena import DUEL_SECONDS
from bot.core.court import COURT_SECONDS
from bot.tg import arena as arena_tg
from bot.tg import games, pics, send, timers, upload
from bot.tg.events import Events
from bot.tg.timers import Live
from tests.helpers import make_game
from tests.test_texts import assert_html, layout_problems

# Messages people read; callback toasts and alerts are pop-ups with their own rules.
CHECKED_METHODS = {"SendMessage", "SendPhoto", "EditMessageText", "EditMessageCaption", "SendEphemeralMessage"}

BOT_USER = User(id=999, is_bot=True, first_name="kartinkomet", username="kartinkomet_bot")
GROUP = Chat(id=-100, type="supergroup", title="чат")
ADMIN = 1


class FakeSession(BaseSession):
    def __init__(self) -> None:
        super().__init__()
        self.requests: list[TelegramMethod] = []
        self.ids = count(1000)
        self.pending: list[Update] = []  # the update queue Telegram holds for the bot
        self.errors: dict[str, list[Exception]] = {}  # raised one by one before a request succeeds

    async def close(self) -> None:
        pass

    image: bytes | None = None  # served by downloads when a test enables collages
    bot_admin = True  # an admin bot may send ephemeral messages untriggered
    dice_value = 64
    dice_values: list[int] = []  # served first, one per SendDice

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

    @staticmethod
    def kind(method: TelegramMethod) -> str:
        """The request type; a sendMessage only one user sees counts as its own kind."""
        name = type(method).__name__
        if name == "SendMessage" and getattr(method, "ephemeral_message_parameters", None):
            return "SendEphemeralMessage"
        return name

    async def make_request(self, bot, method, timeout=None):
        self.requests.append(method)
        result = self.reply(method)
        # Parsed by aiogram exactly like a real reply, so tests catch what would break in prod.
        return self.check_response(bot, method, 200, json.dumps({"ok": True, "result": wire(result)})).result

    def reply(self, method: TelegramMethod):
        name = self.kind(method)
        if self.errors.get(name):
            raise self.errors[name].pop(0)
        if name in getattr(self, "refuse", set()):
            from aiogram.exceptions import TelegramBadRequest

            raise TelegramBadRequest(method=method, message="Bad Request: not supported")
        if name == "SendEphemeralMessage":
            params = method.ephemeral_message_parameters
            reply = method.reply_parameters
            if not self.bot_admin and not params.callback_query_id and not (reply and reply.ephemeral_message_id):
                from aiogram.exceptions import TelegramBadRequest

                raise TelegramBadRequest(method=method, message="Bad Request: EPHEMERAL_TRIGGER_REQUIRED")
            return self.message(int(method.chat_id)).model_copy(
                update={"message_id": 0, "ephemeral_message_id": next(self.ids),
                        "receiver_user": user(params.receiver_user_id)}
            )
        if name in ("SendMessage", "SendPhoto", "SendDocument"):
            return self.message(int(method.chat_id), photo=name == "SendPhoto")
        if name == "SendDice":
            from aiogram.types import Dice

            message = self.message(int(method.chat_id))
            value = self.dice_values.pop(0) if self.dice_values else self.dice_value
            return message.model_copy(update={"dice": Dice(emoji=method.emoji or "🎲", value=value)})
        if name == "SendMediaGroup":
            return [self.message(int(method.chat_id)) for _ in method.media]
        if name == "GetMe":
            return BOT_USER
        if name == "GetWebhookInfo":
            return WebhookInfo(url="", has_custom_certificate=False, pending_update_count=len(self.pending))
        if name == "GetUpdates":
            return self.pending[: method.limit or 100]
        if name == "DeleteWebhook" and method.drop_pending_updates:
            self.pending = []
        if name == "GetFile":
            return File(file_id=method.file_id, file_unique_id="x", file_path="photos/x.jpg" if self.image else None)
        return True

    def of(self, name: str) -> list[TelegramMethod]:
        return [request for request in self.requests if self.kind(request) == name]


def wire(value):
    """A reply as Telegram would send it: plain JSON."""
    if isinstance(value, list):
        return [wire(item) for item in value]
    if isinstance(value, TelegramObject):
        return value.model_dump(mode="json", by_alias=True, exclude_none=True)
    return value


def user(user_id: int) -> User:
    return User(id=user_id, is_bot=False, first_name=f"user{user_id}", username=f"user{user_id}")


class BotHarness(unittest.IsolatedAsyncioTestCase):
    """Fake Telegram plus helpers; test classes inherit it."""

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
        pics._last_drop.clear()
        games.DICE_ANIMATION_SECONDS = 0
        self.session.dice_values = []
        send._no_ephemeral.clear()
        send._drawn.clear()  # message ids repeat from test to test
        arena_tg._downloads.clear()  # file ids repeat too
        timers.LIVE_EDIT_GAP = 0

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
                # One layout everywhere: no triple line breaks, no trailing blank lines.
                self.assertNotIn("\n\n\n", text)
                self.assertEqual(text, text.strip("\n"))
                if self.session.kind(request) in CHECKED_METHODS:
                    self.assertEqual(layout_problems(text), [], text)
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

    async def press(
        self, data: str, message_id: int = 1, sender: int = 2, chat: Chat = GROUP, personal: bool = False
    ) -> None:
        """personal: the button sits on the sender's own (ephemeral) copy of a screen."""
        message = Message(message_id=0 if personal else message_id, date=datetime.now(UTC), chat=chat,
                          from_user=BOT_USER, ephemeral_message_id=55 if personal else None)
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

    SCREENS = ("EditMessageText", "SendEphemeralMessage", "EditEphemeralMessageText")

    def shown(self):
        """The last screen request: the shared panel redrawn, or someone's personal copy."""
        return [request for request in self.session.requests if self.session.kind(request) in self.SCREENS][-1]

    def screen(self) -> str:
        return self.shown().text


class BotTest(BotHarness):
    async def test_menu_replaces_old_panel_and_navigates(self) -> None:
        await self.send("/menu")
        await self.send("/menu")
        self.assertEqual(len(self.session.of("SendMessage")), 2)
        self.assertEqual(len(self.session.of("DeleteMessage")), 1)
        self.assertNotIn("m:adm", self.buttons(self.session.of("SendMessage")[0]))
        panel = self.game.repo.panel_message(-100)
        for screen in ("m:hall", "m:bottom", "m:grave", "m:top:loved", "m:up", "m:help"):
            await self.press(screen, message_id=panel)  # each opens for the presser only, in the panel's place
        self.assertEqual(len(self.session.of("SendEphemeralMessage")), 6)
        self.assertTrue(all(request.ephemeral_message_parameters.replace_callback_query_message
                            for request in self.session.of("SendEphemeralMessage")))
        await self.press("m:home:refresh", message_id=panel)
        self.assertEqual(len(self.session.of("EditMessageText")), 1)  # the shared panel itself
        await self.press("m:people", message_id=777)  # from a result card: below it, the card stays
        self.assertFalse(self.session.of("SendEphemeralMessage")[-1].ephemeral_message_parameters.replace_callback_query_message)
        await self.press("m:top:rich", personal=True)  # inside a personal copy: redrawn in place
        self.assertIn("Богачи", self.session.of("EditEphemeralMessageText")[-1].text)
        self.assertEqual(len(self.session.of("EditMessageText")), 1)
        self.session.refuse = {"EditEphemeralMessageText"}  # the copy vanished: a fresh one comes
        await self.press("m:shop", personal=True)
        self.assertIn("Лавка", self.session.of("SendEphemeralMessage")[-1].text)
        self.assertEqual(len(self.session.of("EditMessageText")), 1)

    async def test_someones_browsing_doesnt_move_anothers_screen(self) -> None:
        await self.send("/menu")
        await self.press("m:shop", sender=3)
        await self.press("m:casino", sender=4)
        self.assertFalse(self.session.of("EditMessageText"))  # the shared panel never moved
        receivers = [request.ephemeral_message_parameters.receiver_user_id
                     for request in self.session.of("SendEphemeralMessage")]
        self.assertEqual(receivers, [3, 4])

    async def test_casino_is_personal_and_the_stake_mark_follows_the_press(self) -> None:
        await self.send("/casino", sender=3)
        self.assertIn("Казино", self.session.of("SendEphemeralMessage")[-1].text)
        self.assertFalse(self.session.of("SendMessage"))  # nobody else sees one person's coins
        await self.press("cs:p25", sender=3, personal=True)
        redrawn = self.session.of("EditEphemeralMessageText")[-1]
        self.assertIn("✅ 25%", [button.text for row in redrawn.reply_markup.inline_keyboard for button in row])
        await self.press("cs:p50", sender=3)  # on the shared panel: a toast, the panel stays
        self.assertFalse(self.session.of("EditMessageText"))

    async def test_profile_is_private_in_groups(self) -> None:
        await self.press("m:me", sender=3)
        ephemeral = self.session.of("SendEphemeralMessage")
        self.assertEqual(len(ephemeral), 1)
        self.assertEqual(ephemeral[0].ephemeral_message_parameters.receiver_user_id, 3)
        self.assertEqual(self.session.of("EditMessageText"), [])

    async def test_profile_falls_back_to_panel_if_ephemeral_refused(self) -> None:
        self.session.refuse = {"SendEphemeralMessage"}
        await self.press("m:me", sender=3)
        self.assertIn("👤 <b>user3</b>", self.session.of("EditMessageText")[-1].text)  # a name keeps its case

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
        self.assertEqual(buttons[3], "pic")
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
        self.assertIn("казнена", self.session.of("EditMessageCaption")[-1].caption)
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
        self.assertIn("Суд", self.screen())

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
        self.assertIn("Дуэль", card.caption)
        battle_id = self.buttons(card)[0].split(":")[1]
        self.assertTrue(self.game.repo.get_battle(battle_id).card_is_photo)

        await self.press(f"v:{battle_id}:0", sender=3)
        self.clock.advance(DUEL_SECONDS + 1)
        await self.live.finish_battle(battle_id)
        self.assertIn("Итог дуэли", self.session.of("EditMessageCaption")[-1].caption)


    async def test_profile_and_command_menus(self) -> None:
        from bot.__main__ import set_up_profile

        await set_up_profile(self.bot)
        menus = {type(r.scope).__name__ if r.scope else "default": [c.command for c in r.commands] for r in self.session.of("SetMyCommands")}
        self.assertIn("upload", menus["BotCommandScopeAllPrivateChats"])
        self.assertNotIn("upload", menus["BotCommandScopeAllGroupChats"])
        self.assertEqual(len(self.session.of("SetMyDescription")), 1)
        self.assertEqual(len(self.session.of("SetMyShortDescription")), 1)

    async def test_vote_buttons_match_badge_colours(self) -> None:
        await self.send("/tournament")
        card = [r for r in self.session.requests if getattr(r, "reply_markup", None) and "v:" in str(r.reply_markup)][-1]
        styles = [b.model_extra.get("style") if b.model_extra else getattr(b, "style", None) for b in card.reply_markup.inline_keyboard[0]]
        self.assertEqual(styles, ["danger", "primary", "success", None])


    # ── anti-spam, overtime, cleanup ───────────────────────────────────

    async def test_pic_button_cooldown(self) -> None:
        await self.send("/pic")
        await self.press("pic")
        self.assertEqual(len(self.session.of("SendPhoto")), 1)
        self.assertTrue(self.session.of("AnswerCallbackQuery")[-1].text)
        pics._last_drop.clear()
        await self.press("pic")
        self.assertEqual(len(self.session.of("SendPhoto")), 2)

    async def test_empty_battle_gets_one_overtime(self) -> None:
        battle = self.game.start_duel(-100).battle
        self.game.repo.set_battle_message(battle.id, 90)

        original = timers.asyncio.sleep

        async def fake_sleep(seconds: float) -> None:
            for _ in range(10 if seconds else 1):  # a tick lets the redraw it asked for draw first
                await original(0)
            self.clock.advance(seconds)

        timers.asyncio.sleep, timers.REFRESH_DELAY = fake_sleep, 0
        try:
            self.clock.advance(DUEL_SECONDS)
            await self.live.battle_countdown(battle.id)
        finally:
            timers.asyncio.sleep, timers.REFRESH_DELAY = original, 1.5
        finished = self.game.repo.get_battle(battle.id)
        self.assertTrue(finished.extended)
        self.assertEqual(finished.status, "done")
        from bot.texts.events import EXTENDED
        from bot.tg.views import bare

        notices = [bare(phrase) for phrase in EXTENDED]
        cards = [r.text or "" for r in self.session.of("EditMessageText")]
        self.assertTrue(any(notice in text for text in cards for notice in notices))  # the overtime notice

    async def test_new_duel_button_answers_before_the_collage(self) -> None:
        await self.press("d:new")
        answers = [r.text for r in self.session.of("AnswerCallbackQuery")]
        self.assertEqual(answers, ["⚔️ Собираю арену…"])
        first_answer = self.session.requests.index(self.session.of("AnswerCallbackQuery")[0])
        first_send = self.session.requests.index(self.session.of("SendMediaGroup")[0])
        self.assertLess(first_answer, first_send)

    async def test_migration_junk_scopes_are_cleaned_on_start(self) -> None:
        from bot.db.repo import Repo

        pic = self.game.draw_pic(-100)[0]
        self.game.repo.db.execute("INSERT INTO deck_seen VALUES ('pic:duel:-100:left', ?)", (pic.id,))
        self.game.repo.db.commit()
        reopened = Repo(self.game.repo.database_path)
        self.addCleanup(reopened.close)
        junk = reopened.db.execute("SELECT COUNT(*) FROM deck_seen WHERE scope LIKE 'pic:duel:%'").fetchone()[0]
        self.assertEqual(junk, 0)

    # ── scheduled events ───────────────────────────────────────────────

    def events(self) -> Events:
        return Events(self.bot, self.game, self.live, frozenset({ADMIN}), tz_offset_hours=0)

    def at_hour(self, hour: int, weekday: int | None = None) -> None:
        now = int(self.clock())
        day = now - now % 86400
        if weekday is not None:
            current = datetime.fromtimestamp(day, UTC).weekday()
            day += ((weekday - current) % 7) * 86400
        self.clock.value = day + hour * 3600 + 60

    async def test_group_chats_are_tracked(self) -> None:
        await self.send("/menu")
        self.assertEqual(self.game.repo.event_chats(0), [-100])

    async def test_pic_of_the_day_once_per_day(self) -> None:
        self.game.repo.touch_chat(-100, "чат", self.game.now())
        pic = self.game.draw_pic(-100)[0]
        self.game.react(pic.id, 5, 1)
        self.at_hour(12)
        events = self.events()
        await events.tick()
        await events.tick()
        photos = [r for r in self.session.of("SendPhoto") if "Пикча дня" in (r.caption or "")]
        self.assertEqual(len(photos), 1)
        self.assertEqual(photos[0].photo, pic.file_id)

    async def test_nothing_fires_outside_the_window(self) -> None:
        self.game.repo.touch_chat(-100, "чат", self.game.now())
        self.at_hour(15)
        await self.events().tick()
        self.assertEqual(self.session.requests, [])

    async def test_evening_auto_court(self) -> None:
        self.game.repo.touch_chat(-100, "чат", self.game.now())
        pic = self.game.draw_pic(-100)[0]
        for voter in (5, 6, 7):
            self.game.repo.react(pic.id, voter, -1, self.game.now())
        self.game.repo.db.execute("UPDATE pics SET rating = 900 WHERE id = ?", (pic.id,))
        self.game.repo.db.commit()
        self.at_hour(19)
        await self.events().tick()
        self.assertIsNotNone(self.game.repo.active_court_for_pic(pic.id))
        self.assertFalse(self.session.of("SendMessage"))  # the robot speaks inside the court card
        self.assertIn("Народный суд", self.session.of("SendPhoto")[-1].caption)

    async def test_weekly_digest_on_sunday(self) -> None:
        self.game.repo.touch_chat(-100, "чат", self.game.now())
        self.game.add_pic("week", "week-uniq", ADMIN, None)
        self.at_hour(18, weekday=6)
        await self.events().tick()
        texts = [getattr(r, "text", None) or getattr(r, "caption", None) or "" for r in self.session.requests]
        self.assertTrue(any("Итоги недели" in text for text in texts))

    async def test_events_can_be_switched_off_by_admin(self) -> None:
        self.game.repo.touch_chat(-100, "чат", self.game.now())
        await self.press("adm:events", sender=ADMIN)
        self.assertFalse(self.game.repo.chat_events_on(-100))
        self.assertEqual(self.game.repo.event_chats(0), [])

    async def test_daily_backup_goes_to_admins(self) -> None:
        self.at_hour(4)
        await self.events().tick()
        documents = self.session.of("SendDocument")
        self.assertEqual(len(documents), 1)
        self.assertEqual(int(documents[0].chat_id), ADMIN)

    # ── inline ─────────────────────────────────────────────────────────

    async def test_inline_mode_offers_pics(self) -> None:
        from aiogram.types import InlineQuery

        for query_text in ("", "топ"):
            query = InlineQuery(id="q", from_user=user(3), query=query_text, offset="")
            await self.dispatcher.feed_update(self.bot, Update(update_id=next(self.update_ids), inline_query=query))
        random_answer, top_answer = self.session.of("AnswerInlineQuery")
        self.assertEqual(len(random_answer.results), 10)
        self.assertTrue(random_answer.is_personal)
        self.assertEqual(top_answer.results, [])  # no pic has enough history yet


    async def test_achievements_of_one_event_come_in_one_message(self) -> None:
        pic = self.game.draw_pic(-100)[0]
        trial = self.game.start_court(-100, pic.id, "bottom", None).court
        self.game.repo.set_court_message(trial.id, 80)
        await self.press(f"c:k:{trial.id}", sender=3)
        await self.press(f"c:k:{trial.id}", sender=4)
        self.clock.advance(COURT_SECONDS + 1)
        await self.live.finish_court(trial.id)
        announcements = [r for r in self.session.of("SendMessage") if "Первая кровь" in (r.text or "")]
        self.assertEqual(len(announcements), 1)
        self.assertIn("user3", announcements[0].text)
        self.assertIn("user4", announcements[0].text)

    async def test_profile_shows_coins_level_and_showcase(self) -> None:
        self.game.pay(3, 70, "test")
        self.game.repo.grant_achievement(3, "oracle", self.game.now())
        self.session.refuse = {"SendEphemeralMessage"}
        await self.press("m:me", sender=3)
        text = self.session.of("EditMessageText")[-1].text
        self.assertIn("🪙 <b>70</b> монет", text)
        self.assertIn("🙂 Свой", text)
        self.assertIn("\n🎯 Оракул\n", text)

    async def test_rich_top(self) -> None:
        self.game.repo.remember_user(3, "user3", "user3", None, self.game.now())
        self.game.pay(3, 50, "test")
        await self.press("m:top:rich")
        self.assertIn("user3 — <b>50</b> монет", self.screen())


    # ── mini-games ─────────────────────────────────────────────────────

    async def test_caption_contest_end_to_end(self) -> None:
        await self.send("/caption")
        card = self.session.of("SendPhoto")[-1]
        self.assertIn("Подпиши пикчу", card.caption)
        contest = self.game.repo.active_game(-100, "caption")
        message = Message(message_id=contest["message_id"], date=datetime.now(UTC), chat=GROUP, from_user=BOT_USER)
        await self.send("когда бот выдал легенду", sender=3, reply_to=message)
        await self.send("рейтинг 1090 не трогай", sender=4, reply_to=message)
        self.assertEqual([r.reaction[0].emoji for r in self.session.of("SetMessageReaction")], ["✍", "✍"])
        self.clock.advance(61)
        await self.live.advance_game(contest["id"])
        vote_card = self.session.of("EditMessageCaption")[-1]
        self.assertIn("Лучшая подпись", vote_card.caption)
        self.assertEqual(self.buttons(vote_card), [f"cv:{contest['id']}:0", f"cv:{contest['id']}:1"])
        await self.press(f"cv:{contest['id']}:1", sender=5)
        self.clock.advance(46)
        await self.live.advance_game(contest["id"])
        result = self.session.of("EditMessageCaption")[-1].caption
        self.assertIn("Итоги", result)
        self.assertIn("👑 «рейтинг 1090 не трогай»\n<i>user4 · 1 голос</i>", result)

    async def test_wheel_shows_slot_machine_then_prize(self) -> None:
        await self.send("/wheel", sender=3)
        self.assertEqual(self.session.of("SendDice")[0].emoji, "🎰")
        prize = self.session.of("SendMessage")[0]
        self.assertIn("джекпот", prize.text)
        self.assertEqual(self.game.repo.player(3)[0], 100)
        self.assertIn("m:casino", self.buttons(prize))

    async def test_wheel_is_once_a_day(self) -> None:
        self.game.take_free_spin(3)
        await self.send("/wheel", sender=3)
        self.assertEqual(self.session.of("SendDice"), [])

    async def test_horoscope_from_panel(self) -> None:
        await self.press("gm:horo", sender=3)
        self.assertIn("Гороскоп", self.session.of("SendPhoto")[-1].caption)
        await self.press("gm:horo", sender=3)
        self.assertEqual(len(self.session.of("SendPhoto")), 1)

    async def test_golden_pic_is_grabbed_once(self) -> None:
        from io import BytesIO

        from PIL import Image

        buffer = BytesIO()
        Image.new("RGB", (200, 200), (10, 10, 10)).save(buffer, "JPEG")
        self.session.image = buffer.getvalue()
        self.game.roll_gold = lambda chat_id: True
        await self.send("/pic")
        gold = self.session.of("SendPhoto")[-1]
        self.assertIn("Золотая", gold.caption)
        token_data = self.buttons(gold)[0]
        await self.press(token_data, sender=3)
        await self.press(token_data, sender=4)
        self.assertEqual(self.game.repo.player(3)[0], 25)
        self.assertEqual(self.game.repo.player(4)[0], 0)
        self.assertTrue(self.session.of("EditMessageReplyMarkup")[-1].reply_markup.inline_keyboard[0][0].text.startswith("🏆"))

    async def test_games_screen(self) -> None:
        await self.press("m:games")
        self.assertIn("Игры", self.screen())


    async def test_crowns_in_tops_profile_and_digest(self) -> None:
        self.game.repo.touch_chat(-100, "чат", self.game.now())
        self.game.add_pic("crown", "crown-uniq", 3, None)
        self.game.repo.remember_user(3, "user3", "user3", None, self.game.now())
        self.at_hour(18, weekday=6)
        await self.events().tick()
        digest = [r for r in self.session.requests if "Короны недели" in (getattr(r, "text", None) or getattr(r, "caption", None) or "")]
        self.assertEqual(len(digest), 1)
        await self.press("m:top:uploads")
        top = self.screen()
        self.assertIn("uploader", top)  # crowns show in the profile and the digest, not in tops
        self.session.refuse = {"SendEphemeralMessage"}
        await self.press("m:me", sender=ADMIN)
        self.assertIn("👑 Король загрузок", self.screen())


if __name__ == "__main__":
    unittest.main()
