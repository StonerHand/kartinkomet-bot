"""Daily bonus, quests, chests."""

import asyncio

from aiogram import Bot, F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message

from bot.core import progress
from bot.game import Game
from bot.texts import progress as texts
from bot.texts.pick import pick
from bot.tg import keyboards, send, views
from bot.tg.timers import Live

router = Router(name="progress")
CHEST_PAUSE = 1.2  # seconds of suspense before the loot; tests set 0


async def claim(bot: Bot, game: Game, live: Live, chat_id: int, user_id: int) -> str | None:
    """Returns a refusal (already claimed) or None when the bonus was paid."""
    daily = game.claim_daily(user_id)
    if daily.status != "ok":
        return f"{pick(texts.DAILY_AGAIN)}. Серия: {daily.streak}"
    label = game.repo.user_label(user_id)
    markup = keyboards.open_chests([progress.RARE]) if daily.chest else None
    await send.send_text(bot, chat_id, views.daily_result(label, daily, chat_id), markup)
    await live.announce(chat_id, daily.granted or [])
    return None


@router.message(Command("daily", "bonus"))
async def daily_command(message: Message, bot: Bot, game: Game, live: Live) -> None:
    if message.from_user is None:
        return
    refusal = await claim(bot, game, live, message.chat.id, message.from_user.id)
    if refusal:
        await message.reply(refusal)


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
    refusal = await claim(bot, game, live, chat_id, callback.from_user.id)
    if refusal:
        await callback.answer(refusal, show_alert=True)
    else:
        await send.answer_quietly(callback, "🎁 Получено")


async def open_one(bot: Bot, game: Game, live: Live, chat_id: int, user_id: int, tier: str) -> bool:
    opened = game.open_chest(user_id, tier)
    if opened is None:
        return False
    label = game.repo.user_label(user_id)
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
    await send.answer_quietly(callback, "🗝 Открываю…")
    await open_one(bot, game, live, chat_id, callback.from_user.id, tier)
