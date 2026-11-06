"""HTML widgets in messages (Bot API 10.4): a message that is a small page, whose data the bot
edits and which asks the bot back when tapped.

aiogram 3.31 speaks Bot API 10.3, so the calls are declared here, and a tap arrives as an update
type aiogram doesn't know: `widget_query` (read by app/middleware.WidgetQueries). The spec:
github.com/TelegramMessenger/widget-sandbox, docs/tgw-format.md and docs/sdk-v1.md. Every call
fails softly (None / False) where Telegram doesn't offer widgets yet: callers fall back to cards.
"""

import json
import logging
from dataclasses import dataclass

from aiogram import Bot
from aiogram.exceptions import TelegramAPIError, TelegramRetryAfter
from aiogram.methods.base import TelegramMethod
from aiogram.types import Message, Update, User

from bot.telegram import send

LOGGER = logging.getLogger(__name__)
QUERY_UPDATES = ("widget_query", "shared_widget_query")
DATA_LIMIT = 1024  # bytes of chat_data, public_data and an answer


class SendWidget(TelegramMethod[Message]):
    __returning__ = Message
    __api_method__ = "sendWidget"

    chat_id: int
    html: str
    width: int = 0
    height: int = 0
    caption: str | None = None
    parse_mode: str | None = None
    chat_data: str | None = None
    public_data: str | None = None
    allow_queries: bool | None = None
    is_shared: bool | None = None
    reply_parameters: dict | None = None


class EditMessageWidgetData(TelegramMethod[bool]):
    __returning__ = bool
    __api_method__ = "editMessageWidgetData"

    chat_id: int
    message_id: int
    chat_data: str | None = None
    public_data: str | None = None


class EditSharedWidgetData(TelegramMethod[bool]):
    __returning__ = bool
    __api_method__ = "editSharedWidgetData"

    widget_id: str
    public_data: str
    cache_time: int | None = None


class AnswerWidgetQuery(TelegramMethod[bool]):
    __returning__ = bool
    __api_method__ = "answerWidgetQuery"

    widget_query_id: str
    result: str | None = None
    data: str | None = None  # the spec names the answer both ways; the server ignores the other


@dataclass(frozen=True)
class WidgetQuery:
    id: str
    user: User
    chat_id: int | None  # None: a tap on a forwarded copy
    message_id: int | None
    data: str
    widget_id: str | None


def parse_query(update: Update) -> WidgetQuery | None:
    """The widget tap in an update, if that is what it carries."""
    extra = update.model_extra or {}
    raw = next((extra[name] for name in QUERY_UPDATES if isinstance(extra.get(name), dict)), None)
    if raw is None or "from" not in raw:
        return None
    chat = raw.get("chat") or (raw.get("message") or {}).get("chat") or {}
    message_id = raw.get("message_id") or (raw.get("message") or {}).get("message_id")
    return WidgetQuery(str(raw.get("id", "")), User.model_validate(raw["from"]), chat.get("id"), message_id,
                       str(raw.get("data", "")), raw.get("widget_id"))


def pack(value: object) -> str:
    """Compact JSON for a widget's data or an answer."""
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def fits(data: str) -> bool:
    return len(data.encode()) <= DATA_LIMIT


async def send_widget(
    bot: Bot, chat_id: int, html: str, caption: str, chat_data: str | None = None,
    public_data: str | None = None, shared: bool = False, reply_to: int | None = None,
) -> Message | None:
    try:
        return await bot(SendWidget(chat_id=chat_id, html=html, caption=caption, parse_mode="HTML",
                                    chat_data=chat_data, public_data=public_data, allow_queries=True,
                                    is_shared=shared or None,
                                    reply_parameters={"message_id": reply_to} if reply_to else None))
    except TelegramAPIError as error:
        LOGGER.warning("Widget refused in %s: %s", chat_id, error)
        return None


def widget_id(message: Message) -> str | None:
    """The shared widget's id, which the sent message carries."""
    widget = (message.model_extra or {}).get("widget") or {}
    return str(widget["id"]) if "id" in widget else None


_drawn: dict[tuple[int, int], str] = {}  # what each widget shows now: an unchanged redraw isn't sent


def is_drawn(chat_id: int, message_id: int, chat_data: str) -> bool:
    return _drawn.get((chat_id, message_id)) == chat_data


async def live_edit_data(bot: Bot, chat_id: int, message_id: int, chat_data: str) -> float:
    """A live widget's redraw, skipped when its data hasn't changed. Returns the flood hold."""
    if _drawn.get((chat_id, message_id)) == chat_data:
        return 0.0
    hold = await edit_data(bot, chat_id, message_id, chat_data)
    if not hold:
        if len(_drawn) > 2000:
            _drawn.clear()
        _drawn[(chat_id, message_id)] = chat_data
    return hold


async def edit_data(bot: Bot, chat_id: int, message_id: int, chat_data: str) -> float:
    """A widget's new state. Returns how long a flood wait asks to hold further edits (0: done)."""
    try:
        await bot(EditMessageWidgetData(chat_id=chat_id, message_id=message_id, chat_data=chat_data))
    except TelegramRetryAfter as error:
        return float(error.retry_after)
    except TelegramAPIError as error:
        if not send.not_modified(error):
            LOGGER.warning("Widget data edit failed %s/%s: %s", chat_id, message_id, error)
    return 0.0


async def edit_shared(bot: Bot, shared_id: str, public_data: str, cache_time: int) -> bool:
    try:
        return bool(await bot(EditSharedWidgetData(widget_id=shared_id, public_data=public_data, cache_time=cache_time)))
    except TelegramAPIError as error:
        LOGGER.warning("Shared widget %s edit failed: %s", shared_id, error)
        return False


async def answer(bot: Bot, query_id: str, result: str) -> None:
    try:
        await bot(AnswerWidgetQuery(widget_query_id=query_id, result=result, data=result))
    except TelegramAPIError as error:
        LOGGER.warning("Widget answer failed: %s", error)
