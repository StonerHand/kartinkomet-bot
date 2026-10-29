"""The fake Telegram and the bot-level test harness: every scenario test builds on BotHarness.

FakeSession records every request and answers like Telegram (ephemeral messages included, and a
chat where the bot isn't an admin with bot_admin = False). BotHarness wires the real dispatcher
to it, turns animations and pauses off, and checks every message against the design rules
(tests/layout.py) when a test ends."""

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
from bot.tg.handlers import casino, challenges, games, pics, progress, shop, upload
from bot.tg.runtime import pictures, send, timers
from bot.tg.runtime.events import Events
from bot.tg.runtime.timers import Live
from tests.helpers import make_game
from tests.layout import assert_html, layout_problems

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
        pictures._downloads.clear()  # file ids repeat too
        timers.LIVE_EDIT_GAP = 0
        # Animations and suspense are real seconds in the bot; tests don't wait for them.
        casino.ANIMATION_SCALE = 0
        casino._last_play.clear()
        challenges.DICE_ANIMATION_SCALE = 0
        progress.CHEST_PAUSE = 0
        shop._confirm.clear()

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

    def fund(self, user_id: int, amount: int = 1000) -> None:
        self.game.repo.add_coins(user_id, amount, "test", self.game.now(), earn=False)

    def coins(self, user_id: int) -> int:
        return self.game.repo.player(user_id)[0]

    SCREENS = ("EditMessageText", "SendEphemeralMessage", "EditEphemeralMessageText")

    def shown(self):
        """The last screen request: the shared panel redrawn, or someone's personal copy."""
        return [request for request in self.session.requests if self.session.kind(request) in self.SCREENS][-1]

    def screen(self) -> str:
        return self.shown().text

    def remember(self, *user_ids: int) -> None:
        """People the bot already knows by name (user4 → «user4»)."""
        for user_id in user_ids:
            self.game.repo.remember_user(user_id, f"user{user_id}", f"user{user_id}", None, self.game.now())

    def texts(self) -> list[str]:
        """Every text and caption the bot sent, in order."""
        return [getattr(r, "text", None) or getattr(r, "caption", None) or "" for r in self.session.requests]

    def reply_to(self, user_id: int) -> Message:
        """A message of that person in the group, to reply to with a command."""
        return Message(message_id=500, date=datetime.now(UTC), chat=GROUP, from_user=user(user_id), text="привет")

    def events(self) -> Events:
        return Events(self.bot, self.game, self.live, frozenset({ADMIN}), tz_offset_hours=0)

    def at_hour(self, hour: int, weekday: int | None = None) -> None:
        """Move the clock to that hour (UTC = local in events()), on that weekday if given."""
        now = int(self.clock())
        day = now - now % 86400
        if weekday is not None:
            current = datetime.fromtimestamp(day, UTC).weekday()
            day += ((weekday - current) % 7) * 86400
        self.clock.value = day + hour * 3600 + 60
