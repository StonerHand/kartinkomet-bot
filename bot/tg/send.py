"""Telegram calls with retries and tolerant edits."""

import asyncio
import logging
from collections.abc import Awaitable, Callable
from typing import TypeVar

from aiogram import Bot
from aiogram.exceptions import (
    TelegramAPIError,
    TelegramBadRequest,
    TelegramNetworkError,
    TelegramRetryAfter,
    TelegramServerError,
)
from aiogram.methods import TelegramMethod
from aiogram.types import (
    InlineKeyboardMarkup,
    InputFile,
    InputMediaPhoto,
    Message,
    ReactionTypeEmoji,
    ReplyParameters,
)

LOGGER = logging.getLogger(__name__)
RETRIES = 3
RETRY_DELAY = 0.5
T = TypeVar("T")


def _reply(message_id: int | None) -> ReplyParameters | None:
    if message_id is None:
        return None
    return ReplyParameters(message_id=message_id, allow_sending_without_reply=True)


async def retry(operation: Callable[[], Awaitable[T]], what: str) -> T:
    for attempt in range(1, RETRIES + 1):
        try:
            return await operation()
        except TelegramRetryAfter as error:
            if attempt == RETRIES:
                raise
            LOGGER.warning("Rate limited during %s, sleeping %ss", what, error.retry_after)
            await asyncio.sleep(float(error.retry_after))
        except (TelegramNetworkError, TelegramServerError):
            if attempt == RETRIES:
                raise
            LOGGER.warning("Temporary Telegram error during %s, retry %s", what, attempt)
            await asyncio.sleep(RETRY_DELAY * attempt)
    raise RuntimeError(f"retry loop ended: {what}")


def not_modified(error: TelegramAPIError) -> bool:
    return "message is not modified" in str(error).casefold()


async def edit_text(
    bot: Bot,
    chat_id: int,
    message_id: int,
    text: str,
    markup: InlineKeyboardMarkup | None,
) -> bool:
    try:
        await retry(
            lambda: bot.edit_message_text(
                chat_id=chat_id,
                message_id=message_id,
                text=text,
                parse_mode="HTML",
                reply_markup=markup,
            ),
            "edit text",
        )
        return True
    except TelegramAPIError as error:
        if not_modified(error):
            return True
        LOGGER.warning("Failed to edit message %s/%s: %s", chat_id, message_id, error)
        return False


async def edit_caption(
    bot: Bot,
    chat_id: int,
    message_id: int,
    caption: str,
    markup: InlineKeyboardMarkup | None,
) -> bool:
    try:
        await retry(
            lambda: bot.edit_message_caption(
                chat_id=chat_id,
                message_id=message_id,
                caption=caption,
                parse_mode="HTML",
                reply_markup=markup,
            ),
            "edit caption",
        )
        return True
    except TelegramAPIError as error:
        if not_modified(error):
            return True
        LOGGER.warning("Failed to edit caption %s/%s: %s", chat_id, message_id, error)
        return False


async def edit_markup(
    bot: Bot, chat_id: int, message_id: int, markup: InlineKeyboardMarkup | None
) -> None:
    try:
        await bot.edit_message_reply_markup(
            chat_id=chat_id, message_id=message_id, reply_markup=markup
        )
    except TelegramAPIError as error:
        if not not_modified(error):
            LOGGER.warning("Failed to edit markup %s/%s: %s", chat_id, message_id, error)


async def send_text(
    bot: Bot,
    chat_id: int,
    text: str,
    markup: InlineKeyboardMarkup | None = None,
    reply_to: int | None = None,
) -> Message | None:
    try:
        return await retry(
            lambda: bot.send_message(
                chat_id=chat_id,
                text=text,
                parse_mode="HTML",
                reply_markup=markup,
                reply_parameters=_reply(reply_to),
            ),
            "send text",
        )
    except TelegramAPIError as error:
        LOGGER.warning("Failed to send text to %s: %s", chat_id, error)
        return None


async def send_photo(
    bot: Bot,
    chat_id: int,
    file_id: str | InputFile,
    caption: str,
    markup: InlineKeyboardMarkup | None = None,
    reply_to: int | None = None,
) -> Message | None:
    try:
        return await retry(
            lambda: bot.send_photo(
                chat_id=chat_id,
                photo=file_id,
                caption=caption,
                parse_mode="HTML",
                reply_markup=markup,
                reply_parameters=_reply(reply_to),
            ),
            "send photo",
        )
    except TelegramBadRequest as error:
        # Pics uploaded as documents can't be sent as photos.
        if not isinstance(file_id, str) or "document" not in str(error).casefold():
            LOGGER.warning("Failed to send photo to %s: %s", chat_id, error)
            return None
    except TelegramAPIError as error:
        LOGGER.warning("Failed to send photo to %s: %s", chat_id, error)
        return None

    try:
        return await retry(
            lambda: bot.send_document(
                chat_id=chat_id,
                document=file_id,
                caption=caption,
                parse_mode="HTML",
                reply_markup=markup,
                reply_parameters=_reply(reply_to),
            ),
            "send document",
        )
    except TelegramAPIError as error:
        LOGGER.warning("Failed to send document to %s: %s", chat_id, error)
        return None


async def send_album(bot: Bot, chat_id: int, file_ids: list[str]) -> bool:
    try:
        await retry(
            lambda: bot.send_media_group(
                chat_id=chat_id,
                media=[InputMediaPhoto(media=file_id) for file_id in file_ids],
            ),
            "send album",
        )
        return True
    except TelegramAPIError:
        LOGGER.warning("Album failed in %s, falling back to single photos", chat_id)

    for index, file_id in enumerate(file_ids, start=1):
        if await send_photo(bot, chat_id, file_id, f"<b>{index}</b>") is None:
            return False
    return True


async def delete(bot: Bot, chat_id: int, message_id: int) -> None:
    try:
        await bot.delete_message(chat_id=chat_id, message_id=message_id)
    except TelegramAPIError:
        pass


async def react(bot: Bot, chat_id: int, message_id: int | None, emoji: str, big: bool = False) -> None:
    """Bot reaction on a message. Chats may restrict reactions, so failures are ignored."""
    if message_id is None:
        return
    try:
        await bot.set_message_reaction(
            chat_id=chat_id,
            message_id=message_id,
            reaction=[ReactionTypeEmoji(emoji=emoji)],
            is_big=big,
        )
    except TelegramAPIError as error:
        LOGGER.info("Reaction %s not allowed in %s: %s", emoji, chat_id, error)


class SendEphemeralMessage(TelegramMethod[dict]):
    """sendMessage with Bot API 10.3 ephemeral_message_parameters (newer than aiogram 3.20).

    The result is read as a plain dict so a newer Message shape can't break parsing.
    """

    __returning__ = dict
    __api_method__ = "sendMessage"

    chat_id: int
    text: str
    parse_mode: str = "HTML"
    ephemeral_message_parameters: dict
    reply_markup: InlineKeyboardMarkup | None = None


async def send_ephemeral(
    bot: Bot,
    chat_id: int,
    user_id: int,
    text: str,
    callback_query_id: str | None = None,
    markup: InlineKeyboardMarkup | None = None,
) -> bool:
    """A group message only `user_id` sees. False if Telegram refused, so callers can fall back."""
    parameters: dict = {"receiver_user_id": user_id}
    if callback_query_id:
        parameters["callback_query_id"] = callback_query_id
    try:
        await bot(
            SendEphemeralMessage(
                chat_id=chat_id,
                text=text,
                ephemeral_message_parameters=parameters,
                reply_markup=markup,
            )
        )
        return True
    except TelegramAPIError as error:
        LOGGER.info("Ephemeral message refused in %s: %s", chat_id, error)
        return False


# Message effects work in private chats only. IDs are Telegram's public effect ids.
EFFECT_PARTY = "5046509860389126442"


async def send_with_effect(bot: Bot, chat_id: int, text: str, effect_id: str) -> None:
    try:
        await bot.send_message(chat_id=chat_id, text=text, parse_mode="HTML", message_effect_id=effect_id)
    except TelegramAPIError:
        await send_text(bot, chat_id, text)


async def answer_quietly(callback, text: str | None = None) -> None:
    """Answer a callback that Telegram may already consider answered."""
    try:
        await callback.answer(text)
    except TelegramAPIError:
        pass
