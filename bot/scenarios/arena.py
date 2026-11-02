"""Duels and tournaments."""

import logging
from collections.abc import Awaitable, Callable

from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramAPIError
from aiogram.filters import Command
from aiogram.types import BufferedInputFile, CallbackQuery, Message

from bot.game import Game
from bot.texts import arena as arena_texts
from bot.texts import toasts, ui
from bot.texts.pick import pick
from bot.tg.runtime import send
from bot.tg.runtime.pictures import build_collage
from bot.tg.runtime.timers import Live
from bot.tg.ui import keyboards, views

LOGGER = logging.getLogger(__name__)
router = Router(name="arena")


async def start_battle(
    bot: Bot,
    game: Game,
    live: Live,
    chat_id: int,
    kind: str,
    champion_of: str | None = None,
    on_started: Callable[[], Awaitable[None]] | None = None,
) -> str:
    """Returns 'started' | 'active' | 'shortage' | 'stale' | 'failed'.

    on_started runs as soon as the battle is reserved, before the slow collage work, so a
    button press gets its answer immediately instead of spinning for seconds.
    """

    def attempt():
        if kind == "duel":
            return game.start_duel(
                chat_id, champion_of=champion_of, title=pick(arena_texts.DUEL_START, chat_id)
            )
        return game.start_tournament(chat_id, title=pick(arena_texts.TOURNAMENT_START, chat_id))

    result = attempt()
    if result.status == "active" and result.battle and result.battle.ends_at <= game.now():
        # Its timer died (crash, lost task): settle it now instead of blocking the arena.
        await live.finish_battle(result.battle.id)
        result = attempt()

    if result.status == "active" and result.battle is not None:
        await live.refresh_battle(result.battle.id)
        return "active"
    if result.status == "shortage":
        await send.send_text(bot, chat_id, f"<b>⚔️ {pick(ui.ARENA_SHORTAGE, chat_id)}</b>")
        return "shortage"
    if result.status != "started" or result.battle is None:
        return result.status

    battle = result.battle
    if on_started is not None:
        await on_started()
    return await launch_battle(bot, game, live, battle)


async def launch_battle(bot: Bot, game: Game, live: Live, battle) -> str:
    """Send the collage card of a battle that already exists and start its timer."""
    chat_id = battle.chat_id
    duration = battle.ends_at - battle.started_at
    markup = keyboards.battle_vote(battle.id, battle.kind, battle.vote_counts(), game.bet_step())
    card = None
    await send.chat_action(bot, chat_id, "upload_photo")
    image = await build_collage(bot, battle.pics)
    text = live.battle_text(battle, duration)
    if image is not None:
        # One message: the numbered collage with the vote card as its caption.
        card = await send.send_photo(
            bot,
            chat_id,
            BufferedInputFile(image, filename="arena.jpg"),
            text,
            markup,
        )
    if card is None:
        # Fallback: plain album + separate text card.
        if not await send.send_album(bot, chat_id, [pic.file_id for pic in battle.pics]):
            game.cancel_battle(battle.id)
            await send.send_text(bot, chat_id, pick(ui.ERRORS))
            return "failed"
        card = await send.send_text(bot, chat_id, text, markup)
        if card is None:
            game.cancel_battle(battle.id)
            return "failed"
    game.repo.set_battle_message(battle.id, card.message_id, is_photo=image is not None and card.photo is not None)
    # Downloads and uploads took a few seconds: the vote starts now.
    game.repo.restart_battle_clock(battle.id, game.now(), duration)
    live.watch_battle(battle.id)
    return "started"


@router.message(Command("duel"))
async def duel_command(message: Message, bot: Bot, game: Game, live: Live) -> None:
    status = await start_battle(bot, game, live, message.chat.id, "duel")
    if status == "active":
        await send.reply_personal(bot, message, "⚔️ Дуэль уже идёт — табло выше обновил")


@router.message(Command("tournament"))
async def tournament_command(message: Message, bot: Bot, game: Game, live: Live) -> None:
    status = await start_battle(bot, game, live, message.chat.id, "tournament")
    if status == "active":
        await send.reply_personal(bot, message, "🏟 Турнир уже идёт — табло выше обновил")


BUTTON_ANSWERS = {
    "started": "Погнали",
    "active": "Уже идёт, табло обновил",
    "shortage": "Мало пикч для арены",
    "stale": "Этот чемпион уже не актуален. Жми «Новая дуэль»",
    "failed": "Telegram подвёл, попробуй ещё раз",
}


@router.callback_query(F.data.in_({"d:new", "t:new"}), F.message)
async def new_battle(callback: CallbackQuery, bot: Bot, game: Game, live: Live) -> None:
    kind = "duel" if callback.data == "d:new" else "tournament"
    answered = False

    async def answer_now() -> None:
        nonlocal answered
        answered = True
        await send.answer_quietly(callback, "⚔️ Собираю арену…")

    status = await start_battle(bot, game, live, callback.message.chat.id, kind, on_started=answer_now)
    if not answered:
        await send.answer_quietly(callback, BUTTON_ANSWERS.get(status, ""))


@router.callback_query(F.data.startswith("d:ch:"), F.message)
async def champion(callback: CallbackQuery, bot: Bot, game: Game, live: Live) -> None:
    battle_id = callback.data.split(":", 2)[2]
    answered = False

    async def answer_now() -> None:
        nonlocal answered
        answered = True
        await send.answer_quietly(callback, "👑 Чемпионка выходит на арену")

    status = await start_battle(
        bot, game, live, callback.message.chat.id, "duel", champion_of=battle_id, on_started=answer_now
    )
    if not answered:
        try:
            await callback.answer(BUTTON_ANSWERS.get(status, ""), show_alert=status == "stale")
        except TelegramAPIError:
            pass


@router.callback_query(F.data.startswith("v:"))
async def vote(callback: CallbackQuery, game: Game, live: Live) -> None:
    _, battle_id, raw_slot = callback.data.split(":", 2)
    try:
        slot = int(raw_slot)
    except ValueError:
        await callback.answer()
        return
    status, _ = game.vote_battle(battle_id, callback.from_user.id, slot)
    if status == "expired":
        await callback.answer("Финальный свисток уже прозвучал")
        await live.finish_battle(battle_id)
        return
    if status in ("gone", "closed"):
        await callback.answer("Бой уже окончен", show_alert=True)
        return
    if status == "fighter":
        await callback.answer("Ты дерёшься в этом вызове. Голосуют только зрители", show_alert=True)
        return
    if status == "same":
        await callback.answer(pick(toasts.ALREADY))
        return
    await callback.answer(pick(toasts.DUEL_VOTE))
    live.request_refresh_battle(battle_id)


BET_ANSWERS = {
    "gone": "Этого боя уже нет",
    "closed": "Ставки закрыты, бой окончен",
    "fighter": "Участникам вызова ставить нельзя. Совесть, всё такое",
    "other_slot": "Твоя ставка уже стоит на другой пикче. Не жадничай",
    "max": "Потолок — {max} 🪙 на бой",
    "broke": "Не хватает монет. Ставка — {step} 🪙",
}


@router.callback_query(F.data.startswith("bt:"))
async def bet(callback: CallbackQuery, game: Game, live: Live) -> None:
    _, battle_id, raw_slot = callback.data.split(":", 2)
    if not raw_slot.isdigit():
        await callback.answer()
        return
    status, total = game.bet_battle(battle_id, callback.from_user.id, int(raw_slot))
    if status != "ok":
        answer = BET_ANSWERS.get(status, "Не вышло").format(step=views.num(game.bet_step()), max=views.num(game.bet_max()))
        await callback.answer(answer, show_alert=status not in ("max",))
        return
    await callback.answer(f"💰 Ставка принята: всего {total} 🪙 на эту пикчу")
    live.request_refresh_battle(battle_id)
