"""Pic boss fights."""

from aiogram import Bot, F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message

from bot.core import boss as rules
from bot.game import Game
from bot.texts import boss as texts
from bot.texts.pick import pick
from bot.tg import keyboards, send, views
from bot.tg.timers import Live

router = Router(name="boss")


async def summon(bot: Bot, game: Game, live: Live, chat_id: int, double: bool = False, forced: bool = False) -> str:
    """'started' | 'active' | 'cooldown' | 'shortage' | 'failed'."""
    status, boss = game.summon_boss(chat_id, pick(texts.NAMES, chat_id), double=double, forced=forced)
    if status == "active" and boss is not None:
        if boss["ends_at"] <= game.now():
            await live.finish_boss(boss["id"])
            status, boss = game.summon_boss(chat_id, pick(texts.NAMES, chat_id), double=double, forced=True)
        else:
            return "active"
    if status != "ok" or boss is None:
        return status
    pic = game.repo.get_pic(boss["pic_id"])
    message = await send.send_photo(
        bot,
        chat_id,
        pic.file_id,
        views.boss_card(boss, {}, boss["ends_at"] - game.now(), chat_id),
        keyboards.boss(boss["id"], rules.SUPER_PRICE),
    )
    if message is None:
        game.repo.drop_boss(boss["id"])
        return "failed"
    game.repo.set_boss_message(boss["id"], message.message_id)
    await send.react(bot, chat_id, message.message_id, "👾", big=True)
    live.watch_boss(boss["id"])
    return "started"


def refusal(game: Game, chat_id: int, status: str) -> str:
    return texts.SUMMON_REFUSED.get(status, "Босс не пришёл. Telegram подвёл").format(
        wait=views.duration(game.boss_cooldown_left(chat_id))
    )


@router.message(Command("boss"))
async def boss_command(message: Message, bot: Bot, game: Game, live: Live) -> None:
    status = await summon(bot, game, live, message.chat.id)
    if status != "started":
        await message.reply(refusal(game, message.chat.id, status))


@router.callback_query(F.data == "boss")
async def boss_button(callback: CallbackQuery, bot: Bot, game: Game, live: Live) -> None:
    if callback.message is None:
        await callback.answer()
        return
    chat_id = callback.message.chat.id
    if game.repo.active_boss(chat_id) is None and game.boss_cooldown_left(chat_id):
        await callback.answer(refusal(game, chat_id, "cooldown"), show_alert=True)
        return
    await send.answer_quietly(callback, "👹 Призываю…")
    status = await summon(bot, game, live, chat_id)
    if status != "started":
        await send.send_text(bot, chat_id, refusal(game, chat_id, status))


@router.callback_query(F.data.regexp(r"^b[hs]:"))
async def hit(callback: CallbackQuery, bot: Bot, game: Game, live: Live) -> None:
    kind, boss_id = callback.data.split(":", 1)
    result = game.hit_boss(boss_id, callback.from_user.id, super_hit=kind == "bs")
    if result.status == "cooldown":
        await callback.answer("Замах ещё не готов. Секунду")
        return
    if result.status == "broke":
        await callback.answer(f"Супер-удар стоит {rules.SUPER_PRICE} 🪙", show_alert=True)
        return
    if result.status in ("over", "gone"):
        await callback.answer("Бой с боссом окончен")
        if result.status == "over":
            await live.finish_boss(boss_id)
        return
    pool = texts.CRIT if result.crit or kind == "bs" else texts.HIT
    await callback.answer(f"{pick(pool)} · −{result.damage} ❤️ (осталось {result.hp})")
    if result.counter_victim is not None and callback.message is not None:
        name = game.repo.user_label(result.counter_victim)
        await send.send_text(
            bot,
            callback.message.chat.id,
            f"👹 {pick(texts.COUNTER)}: <b>{views.who(name)}</b> −{rules.COUNTER_FINE} 🪙 в добычу",
        )
    if result.killed:
        await live.finish_boss(boss_id)
    else:
        live.request_refresh_boss(boss_id)
