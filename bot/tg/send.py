"""Telegram calls with retries and tolerant edits."""

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable
from typing import TypeVar

from aiogram import Bot
from aiogram.exceptions import (
    TelegramAPIError,
    TelegramBadRequest,
    TelegramForbiddenError,
    TelegramNetworkError,
    TelegramRetryAfter,
    TelegramServerError,
)
from aiogram.types import (
    EphemeralMessageParameters,
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


# Longer flood waits aren't worth blocking a handler for: the caller falls back or skips.
MAX_FLOOD_WAIT = 30


async def retry(operation: Callable[[], Awaitable[T]], what: str) -> T:
    for attempt in range(1, RETRIES + 1):
        try:
            return await operation()
        except TelegramRetryAfter as error:
            if attempt == RETRIES or error.retry_after > MAX_FLOOD_WAIT:
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


async def _edit(operation: Callable[[], Awaitable], what: str, chat_id: int, message_id: int) -> bool:
    """True when the message shows the new content (an unchanged edit counts as done)."""
    try:
        await retry(operation, what)
        return True
    except TelegramAPIError as error:
        if not_modified(error):
            return True
        LOGGER.warning("Failed to %s %s/%s: %s", what, chat_id, message_id, error)
        return False


async def edit_text(
    bot: Bot, chat_id: int, message_id: int, text: str, markup: InlineKeyboardMarkup | None
) -> bool:
    return await _edit(
        lambda: bot.edit_message_text(
            chat_id=chat_id, message_id=message_id, text=text, parse_mode="HTML", reply_markup=markup
        ),
        "edit text",
        chat_id,
        message_id,
    )


async def edit_caption(
    bot: Bot, chat_id: int, message_id: int, caption: str, markup: InlineKeyboardMarkup | None
) -> bool:
    return await _edit(
        lambda: bot.edit_message_caption(
            chat_id=chat_id, message_id=message_id, caption=caption, parse_mode="HTML", reply_markup=markup
        ),
        "edit caption",
        chat_id,
        message_id,
    )


_drawn: dict[tuple[int, int], int] = {}  # (chat, message) → what a live card shows now


async def live_edit(
    bot: Bot, chat_id: int, message_id: int, text: str, markup: InlineKeyboardMarkup | None, photo: bool
) -> float:
    """Redraw a live card (timer, votes, health). Unchanged content isn't sent at all. A flood wait
    isn't slept through, the next redraw is newer anyway: returns its seconds so the caller holds
    back this chat's redraws, else 0."""
    key = (chat_id, message_id)
    drawn = hash((text, markup.model_dump_json() if markup else None))
    if _drawn.get(key) == drawn:
        return 0.0
    try:
        if photo:
            await bot.edit_message_caption(
                chat_id=chat_id, message_id=message_id, caption=text, parse_mode="HTML", reply_markup=markup
            )
        else:
            await bot.edit_message_text(
                chat_id=chat_id, message_id=message_id, text=text, parse_mode="HTML", reply_markup=markup
            )
    except TelegramRetryAfter as error:
        LOGGER.info("Live card %s/%s waits %ss: the chat is at its message limit", chat_id, message_id, error.retry_after)
        return float(error.retry_after)
    except TelegramAPIError as error:
        if not not_modified(error):
            LOGGER.warning("Failed to redraw live card %s/%s: %s", chat_id, message_id, error)
            return 0.0
    if len(_drawn) > 5000:  # cards long settled; what's drawn is only a shortcut
        _drawn.clear()
    _drawn[key] = drawn
    return 0.0


async def edit_photo(
    bot: Bot, chat_id: int, message_id: int, photo: InputFile, caption: str, markup: InlineKeyboardMarkup | None
) -> bool:
    """Swap the picture of a photo message in place (the next round of a game)."""
    return await _edit(
        lambda: bot.edit_message_media(
            chat_id=chat_id,
            message_id=message_id,
            media=InputMediaPhoto(media=photo, caption=caption, parse_mode="HTML"),
            reply_markup=markup,
        ),
        "edit photo",
        chat_id,
        message_id,
    )


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


# Telegram lets a bot that isn't a chat admin send an ephemeral message only in answer to a button
# press or to an ephemeral message, within 15 seconds. Chats that refused one without such a
# trigger are skipped for a while instead of paying a doomed request every time.
NO_EPHEMERAL_SECONDS = 1800
_no_ephemeral: dict[int, float] = {}


def ephemeral_allowed_again(chat_id: int) -> None:
    """The bot became an admin (or lost it): ask Telegram again next time."""
    _no_ephemeral.pop(chat_id, None)


async def ephemeral(
    bot: Bot,
    chat_id: int,
    user_id: int,
    text: str,
    callback_query_id: str | None = None,
    markup: InlineKeyboardMarkup | None = None,
    reply_to_ephemeral: int | None = None,
    replace: bool = False,
) -> Message | None:
    """A group message only `user_id` sees, or None if Telegram refused, so callers can fall back.
    replace: shown to them in place of the message whose button they pressed."""
    triggered = callback_query_id is not None or reply_to_ephemeral is not None
    if not triggered and _no_ephemeral.get(chat_id, 0) > time.monotonic():
        return None
    try:
        return await bot.send_message(
            chat_id=chat_id,
            text=text,
            parse_mode="HTML",
            reply_markup=markup,
            reply_parameters=ReplyParameters(ephemeral_message_id=reply_to_ephemeral) if reply_to_ephemeral else None,
            ephemeral_message_parameters=EphemeralMessageParameters(
                receiver_user_id=user_id,
                callback_query_id=callback_query_id,
                replace_callback_query_message=True if replace else None,
            ),
        )
    except TelegramAPIError as error:
        LOGGER.info("Ephemeral message refused in %s: %s", chat_id, error)
        if not triggered and isinstance(error, (TelegramBadRequest, TelegramForbiddenError)):
            _no_ephemeral[chat_id] = time.monotonic() + NO_EPHEMERAL_SECONDS  # a refusal, not a network blip
        return None


async def edit_ephemeral(
    bot: Bot, chat_id: int, user_id: int, ephemeral_id: int, text: str, markup: InlineKeyboardMarkup | None
) -> bool:
    try:
        await bot.edit_ephemeral_message_text(
            chat_id=chat_id,
            receiver_user_id=user_id,
            ephemeral_message_id=ephemeral_id,
            text=text,
            parse_mode="HTML",
            reply_markup=markup,
        )
        return True
    except TelegramAPIError as error:
        if not_modified(error):
            return True
        LOGGER.info("Ephemeral edit refused in %s: %s", chat_id, error)
        return False


async def redraw(bot: Bot, message: Message, user_id: int, text: str, markup: InlineKeyboardMarkup | None) -> bool:
    """Redraw the message a button was pressed on: someone's personal screen, or a shared one."""
    if message.ephemeral_message_id:
        return await edit_ephemeral(bot, message.chat.id, user_id, message.ephemeral_message_id, text, markup)
    return await edit_text(bot, message.chat.id, message.message_id, text, markup)


async def send_ephemeral(
    bot: Bot,
    chat_id: int,
    user_id: int,
    text: str,
    callback_query_id: str | None = None,
    markup: InlineKeyboardMarkup | None = None,
) -> bool:
    """A group message only `user_id` sees. False if Telegram refused, so callers can fall back."""
    return await ephemeral(bot, chat_id, user_id, text, callback_query_id, markup) is not None


async def remove(bot: Bot, chat_id: int, message: Message | None) -> None:
    """Delete a message the bot sent, ephemeral or not. Failures are ignored."""
    if message is None:
        return
    if message.ephemeral_message_id and message.receiver_user is not None:
        try:
            await bot.delete_ephemeral_message(chat_id, message.receiver_user.id, message.ephemeral_message_id)
        except TelegramAPIError:
            pass
    elif message.message_id:
        await delete(bot, chat_id, message.message_id)


# Hints and refusals the chat had to see because nothing personal was possible clean up after
# themselves. Tasks are kept here so the loop doesn't drop them half-way.
FLEETING_SECONDS = 60
_fleeting: set[asyncio.Task] = set()


def fleeting(bot: Bot, chat_id: int, message_ids: list[int | None], seconds: float | None = None) -> None:
    async def later() -> None:
        await asyncio.sleep(FLEETING_SECONDS if seconds is None else seconds)
        for message_id in message_ids:
            if message_id:
                await delete(bot, chat_id, message_id)

    task = asyncio.create_task(later())
    _fleeting.add(task)
    task.add_done_callback(_fleeting.discard)


async def personal(
    bot: Bot,
    chat_id: int,
    user_id: int,
    text: str,
    markup: InlineKeyboardMarkup | None = None,
    callback_query_id: str | None = None,
    fleeting_seconds: float | None = None,
) -> Message | None:
    """A message that concerns one person: in a group only they see it, so the chat stays clean.
    In private chats, or if Telegram refuses an ephemeral one, it is an ordinary message, which
    disappears after `fleeting_seconds` if given."""
    if chat_id < 0:
        sent = await ephemeral(bot, chat_id, user_id, text, callback_query_id, markup)
        if sent is not None:
            return sent
    sent = await send_text(bot, chat_id, text, markup)
    if sent is not None and chat_id < 0 and fleeting_seconds is not None:
        fleeting(bot, chat_id, [sent.message_id], fleeting_seconds)
    return sent


async def reply_personal(
    bot: Bot, message, text: str, markup: InlineKeyboardMarkup | None = None, seconds: float | None = None
) -> Message | None:
    """Answer a command for its author's eyes only (a refusal, a hint how to use it). Where the
    chat has to see it, the answer and the command it answers go away after `seconds`."""
    user = message.from_user
    if message.chat.type == "private" or user is None:
        return await send_text(bot, message.chat.id, text, markup, reply_to=message.message_id)
    sent = await ephemeral(
        bot, message.chat.id, user.id, text, markup=markup, reply_to_ephemeral=message.ephemeral_message_id
    )
    if sent is not None:
        return sent
    sent = await send_text(bot, message.chat.id, text, markup, reply_to=message.message_id or None)
    if sent is not None:
        fleeting(bot, message.chat.id, [sent.message_id, message.message_id], seconds)
    return sent


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


async def answer_quietly_alert(callback, text: str) -> None:
    """A pop-up only the presser sees: refusals that shouldn't spam the chat."""
    try:
        await callback.answer(text, show_alert=True)
    except TelegramAPIError:
        pass


async def chat_action(bot: Bot, chat_id: int, action: str) -> None:
    """'is sending a photo…' indicator while slow work runs. Cosmetic, failures ignored."""
    try:
        await bot.send_chat_action(chat_id=chat_id, action=action)
    except TelegramAPIError:
        pass
