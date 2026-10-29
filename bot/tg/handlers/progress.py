"""Daily bonus, quests, chests."""

import asyncio

from aiogram import Bot, F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message

from bot.core import progress
from bot.game import Game
from bot.texts import progress as texts
from bot.texts.pick import pick
from bot.tg.runtime import send
from bot.tg.runtime.timers import Live
from bot.tg.ui import keyboards, views
from bot.tg.ui.views import plural

router = Router(name="progress")
CHEST_PAUSE = 1.2  # seconds of suspense before the loot; tests set 0
OWN_CARD_SECONDS = 300  # someone's own card the chat had to see goes away after this


async def claim(
    bot: Bot, game: Game, live: Live, chat_id: int, user_id: int, callback_query_id: str | None = None
) -> str | None:
    """Returns a refusal (already claimed) or None when the bonus was paid. callback_query_id: the
    button press that lets even a non-admin bot answer personally."""
    daily = game.claim_daily(user_id)
    if daily.status != "ok":
        days = plural(daily.streak, "день", "дня", "дней")
        return views.marked(f"{pick(texts.DAILY_AGAIN)}. Серия — {daily.streak} {days}, следующий бонус после полуночи", "🎁")
    label = game.repo.user_label(user_id)
    markup = keyboards.open_chests([progress.RARE], chat_id) if daily.chest else None
    # Everyone claims it every day: in a group only its owner sees the card.
    text = views.daily_result(label, daily, chat_id)
    await send.personal(bot, chat_id, user_id, text, markup, callback_query_id, fleeting_seconds=OWN_CARD_SECONDS)
    await live.announce(chat_id, daily.granted or [])
    return None


@router.message(Command("daily", "bonus"))
async def daily_command(message: Message, bot: Bot, game: Game, live: Live) -> None:
    if message.from_user is None:
        return
    refusal = await claim(bot, game, live, message.chat.id, message.from_user.id)
    if refusal:
        await send.reply_personal(bot, message, refusal)


def chat_of(callback: CallbackQuery, parts: list[str]) -> int | None:
    """The chat to post in: the button's message, or the chat id baked into the button."""
    if callback.message is not None:
        return callback.message.chat.id
    raw = parts[-1] if parts else ""
    return int(raw) if raw.lstrip("-").isdigit() else None


@router.callback_query(F.data.regexp(r"^daily(:-?\d+)?$"))
async def daily_button(callback: CallbackQuery, bot: Bot, game: Game, live: Live) -> None:
    chat_id = chat_of(callback, callback.data.split(":")[1:])
    if chat_id is None:
        await callback.answer()
        return
    refusal = await claim(bot, game, live, chat_id, callback.from_user.id, callback.id)
    if refusal:
        await callback.answer(refusal, show_alert=True)
    else:
        await send.answer_quietly(callback, "🎁 Получено")


async def open_one(
    bot: Bot, game: Game, live: Live, chat_id: int, user_id: int, tier: str, callback_query_id: str | None = None
) -> bool:
    opened = game.open_chest(user_id, tier)
    if opened is None:
        return False
    label = game.repo.user_label(user_id)
    if tier != "legend" and chat_id < 0:
        # Wooden and rare chests are opened for their owner only; a legendary one, with all the
        # suspense, in front of the chat.
        left = [tier] if game.chests_of(user_id).get(tier) else []
        text = views.chest_opened(label, opened, chat_id)
        await send.personal(
            bot, chat_id, user_id, text, keyboards.open_chests(left, chat_id), callback_query_id,
            fleeting_seconds=OWN_CARD_SECONDS,
        )
        await live.announce(chat_id, opened.granted)
        return True
    message = await send.send_text(bot, chat_id, views.chest_opening(label, tier, chat_id))
    await asyncio.sleep(CHEST_PAUSE)
    text = views.chest_opened(label, opened, chat_id)
    left = {key: value for key, value in game.chests_of(user_id).items() if key == tier and value}
    markup = keyboards.open_chests(list(left)) if left else None
    shown = message
    if message is None or not await send.edit_text(bot, chat_id, message.message_id, text, markup):
        shown = await send.send_text(bot, chat_id, text, markup)
    if shown is not None and (tier == "legend" or opened.loot.coins >= 1000):
        await send.react(bot, chat_id, shown.message_id, "🎉", big=True)
    await live.announce(chat_id, opened.granted)
    return True


@router.callback_query(F.data.startswith("ch:"))
async def open_chest(callback: CallbackQuery, bot: Bot, game: Game, live: Live) -> None:
    parts = callback.data.split(":")
    tier = parts[1]
    chat_id = chat_of(callback, parts[2:])
    if chat_id is None:
        await callback.answer()
        return
    if not game.chests_of(callback.from_user.id).get(tier):
        name = texts.CHESTS.get(tier, ("", "сундука"))[1].lower()
        await callback.answer(f"У тебя нет: {name}. Сундуки дают за квесты, бонусы и боссов", show_alert=True)
        return
    if tier == "legend":  # the suspense is public: stop the button's spinner first
        await send.answer_quietly(callback, "🗝 Открываю…")
    await open_one(bot, game, live, chat_id, callback.from_user.id, tier, callback.id)
    if tier != "legend":  # the personal card went first: Telegram allows it only while the press is fresh
        await send.answer_quietly(callback)
