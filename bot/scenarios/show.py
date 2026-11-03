"""The evening show at 21:00: a bank heist one night, the big cup of eight pics the next."""

from aiogram import Bot, F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message

from bot.game.engine import Game
from bot.game.show import state_of
from bot.live.timers import Live
from bot.rules import show as rules
from bot.scenarios.arena import launch_battle
from bot.telegram import send
from bot.ui import keyboards, views

router = Router(name="show")

GROUP_ONLY = "🎬 Шоу идёт только в групповом чате"
REFUSALS = {
    "active": "Уже идёт — смотри выше",
    "done_today": "Сегодня это шоу уже было. Завтра — снова",
    "shortage": "На складе меньше восьми пикч для турнира",
}


# ── the heist ─────────────────────────────────────────────────────────


async def start_heist(bot: Bot, game: Game, live: Live, chat_id: int) -> str:
    status, found = game.start_heist(chat_id)
    if status != "started" or found is None:
        return status
    text, markup = live.round_card(found)
    message = await send.send_text(bot, chat_id, text, markup)
    if message is None:
        game.repo.drop_round(found["id"])
        return "failed"
    game.repo.set_round_message(found["id"], message.message_id)
    live.watch_heist(found["id"])
    return "started"


@router.message(Command("heist"))
async def heist_command(message: Message, bot: Bot, game: Game, live: Live) -> None:
    if message.chat.type == "private":
        await send.reply_personal(bot, message, GROUP_ONLY)
        return
    status = await start_heist(bot, game, live, message.chat.id)
    if status in REFUSALS:
        await send.reply_personal(bot, message, views.marked(REFUSALS[status], "🏦"))


JOIN_TOASTS = {
    "ok": "🦹 Ты в банде",
    "already": "🦹 Ты уже в банде",
    "full": "🦹 Банда набрана",
    "started": "🏦 Дело уже началось без тебя",
    "jailed": "🚔 Из обезьянника на дело не ходят",
    "gone": "🏦 Этого дела больше нет",
}
VOTE_TOASTS = {
    "ok": "🗳 Голос принят",
    "same": "🗳 Твой голос уже здесь",
    "not_crew": "🏦 Решает только банда",
    "closed": "🏦 Этап закончился",
    "gone": "🏦 Этого дела больше нет",
}


@router.callback_query(F.data.startswith("hj:"))
async def heist_join(callback: CallbackQuery, game: Game, live: Live) -> None:
    round_id = callback.data.split(":", 1)[1]
    status = game.join_heist(round_id, callback.from_user.id)
    await send.answer_quietly(callback, JOIN_TOASTS[status])
    if status == "ok":
        await heist_moved(game, live, round_id)


@router.callback_query(F.data.startswith("hv:"))
async def heist_vote(callback: CallbackQuery, game: Game, live: Live) -> None:
    _, round_id, raw = callback.data.split(":", 2)
    status = game.vote_heist(round_id, callback.from_user.id, int(raw) if raw in ("0", "1") else -1)
    await send.answer_quietly(callback, VOTE_TOASTS[status])
    if status == "ok":
        await heist_moved(game, live, round_id)


async def heist_moved(game: Game, live: Live, round_id: str) -> None:
    """A full crew needn't wait out the recruiting, nor a crew that has all voted its stage."""
    if game.heist_all_in(round_id):
        await live.hurry(round_id)
    else:
        live.request_refresh_round(round_id)


# ── the big cup ───────────────────────────────────────────────────────


async def start_cup(bot: Bot, game: Game, live: Live, chat_id: int) -> str:
    status, found = game.start_cup(chat_id)
    if status != "started" or found is None:
        return status
    pics = [game.repo.get_pic(pic_id) for pic_id in state_of(found)["alive"]]
    uploaders = sorted({game.repo.user_label(pic.added_by) for pic in pics if pic and pic.added_by is not None})
    message = await send.send_text(bot, chat_id, views.cup_intro(uploaders, chat_id, game.reward(rules.CUP_PRIZE)))
    if message is not None:
        game.repo.set_round_message(found["id"], message.message_id)
    await advance_cup(bot, game, live, found["id"])
    return "started"


async def advance_cup(bot: Bot, game: Game, live: Live, round_id: str) -> None:
    """Launch the cup's next match, or crown its champion; nothing while a match is being voted."""
    step = game.cup_step(round_id)
    if step is None:
        return
    chat_id = step.round["chat_id"]
    if step.kind == "match":
        if await launch_battle(bot, game, live, step.battle) == "failed":
            game.cancel_battle(step.battle.id)  # the next tick sends the pair's higher rating on
        return
    if step.champion is None:
        return
    text = views.cup_champion(step.champion, game.repo.user_label(step.champion.added_by), step.prize, chat_id)
    sent = await send.send_photo(bot, chat_id, step.champion.file_id, text, keyboards.more_only())
    if sent is not None:
        await send.react(bot, chat_id, sent.message_id, "🏆", big=True)


async def advance_cups(bot: Bot, game: Game, live: Live) -> None:
    """Every schedule tick: each running cup moves on once its match is over."""
    for round_id in game.open_cup_ids():
        await advance_cup(bot, game, live, round_id)


@router.message(Command("cup"))
async def cup_command(message: Message, bot: Bot, game: Game, live: Live) -> None:
    if message.chat.type == "private":
        await send.reply_personal(bot, message, GROUP_ONLY)
        return
    status = await start_cup(bot, game, live, message.chat.id)
    if status in REFUSALS:
        await send.reply_personal(bot, message, views.marked(REFUSALS[status], "🏆"))


# ── the show ──────────────────────────────────────────────────────────


async def evening_show(bot: Bot, game: Game, live: Live, chat_id: int) -> bool:
    """21:00: tonight's show — they take turns day by day."""
    if rules.show_of(game.local_day()) == "heist":
        return await start_heist(bot, game, live, chat_id) == "started"
    return await start_cup(bot, game, live, chat_id) == "started"
