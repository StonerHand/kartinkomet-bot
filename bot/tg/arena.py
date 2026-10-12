"""Duels and tournaments."""

from aiogram import Bot, F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message

from bot.game import Game
from bot.texts import arena as arena_texts
from bot.texts import ui
from bot.texts.pick import pick
from bot.tg import keyboards, send, views
from bot.tg.timers import Live

router = Router(name="arena")


async def start_battle(
    bot: Bot,
    game: Game,
    live: Live,
    chat_id: int,
    kind: str,
    champion_of: str | None = None,
) -> str:
    """Returns 'started' | 'active' | 'shortage' | 'stale' | 'failed'."""

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
    if not await send.send_album(bot, chat_id, [pic.file_id for pic in battle.pics]):
        game.cancel_battle(battle.id)
        await send.send_text(bot, chat_id, pick(ui.ERRORS))
        return "failed"
    card = await send.send_text(
        bot,
        chat_id,
        views.battle_card(battle, battle.ends_at - game.now(), live.uploaders(battle)),
        keyboards.battle_vote(battle.id, battle.kind, battle.vote_counts()),
    )
    if card is None:
        game.cancel_battle(battle.id)
        return "failed"
    game.repo.set_battle_message(battle.id, card.message_id)
    live.watch_battle(battle.id)
    return "started"


@router.message(Command("duel"))
async def duel_command(message: Message, bot: Bot, game: Game, live: Live) -> None:
    status = await start_battle(bot, game, live, message.chat.id, "duel")
    if status == "active":
        await message.answer("⚔️ Дуэль уже идёт — табло выше обновил")


@router.message(Command("tournament"))
async def tournament_command(message: Message, bot: Bot, game: Game, live: Live) -> None:
    status = await start_battle(bot, game, live, message.chat.id, "tournament")
    if status == "active":
        await message.answer("🏟 Турнир уже идёт — табло выше обновил")


BUTTON_ANSWERS = {
    "started": "Погнали",
    "active": "Уже идёт, табло обновил",
    "shortage": "Мало пикч для арены",
    "stale": "Этот чемпион уже не актуален. Жми «Новая дуэль»",
    "failed": "Telegram подвёл, попробуй ещё раз",
}


@router.callback_query(F.data.in_({"d:new", "t:new"}))
async def new_battle(callback: CallbackQuery, bot: Bot, game: Game, live: Live) -> None:
    if callback.message is None:
        await callback.answer()
        return
    kind = "duel" if callback.data == "d:new" else "tournament"
    status = await start_battle(bot, game, live, callback.message.chat.id, kind)
    await callback.answer(BUTTON_ANSWERS.get(status, ""))


@router.callback_query(F.data.startswith("d:ch:"))
async def champion(callback: CallbackQuery, bot: Bot, game: Game, live: Live) -> None:
    if callback.message is None:
        await callback.answer()
        return
    battle_id = callback.data.split(":", 2)[2]
    status = await start_battle(
        bot, game, live, callback.message.chat.id, "duel", champion_of=battle_id
    )
    answer = "👑 Чемпионка вышла на арену" if status == "started" else BUTTON_ANSWERS.get(status, "")
    await callback.answer(answer, show_alert=status == "stale")


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
    if status == "same":
        await callback.answer("Уже стоит")
        return
    await callback.answer("Голос принят")
    live.request_refresh_battle(battle_id)
