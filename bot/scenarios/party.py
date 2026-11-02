"""Games about the people in the chat: /who polls, the /bomb passed by reply, /bet on life."""

from aiogram import Bot, F, Router
from aiogram.filters import Command, CommandObject
from aiogram.types import CallbackQuery, Message

from bot.game.engine import Game
from bot.live.timers import Live
from bot.rules import party as rules
from bot.telegram import send
from bot.texts import party as texts
from bot.texts.pick import pick
from bot.ui import keyboards, views
from bot.ui.layout import plain

router = Router(name="party")

GROUP_ONLY = "👥 Это игра для группового чата: добавь бота в чат и зови всех туда"


# ── who of us ─────────────────────────────────────────────────────────

WHO_REFUSALS = {
    "active": "Опрос уже идёт — голосуй выше",
    "cooldown": "Следующий вопрос — через {wait}. Или задай свой: /who и текст",
    "shortage": "Бот знает меньше двух игроков этого чата. Пусть люди немного поиграют",
    "poor": "Свой вопрос стоит {price}",
    "long": "Вопрос длиннее {limit} символов. Покороче",
}


def who_refusal(game: Game, chat_id: int, status: str) -> str:
    text = WHO_REFUSALS[status].format(
        wait=views.duration(game.who_cooldown_left(chat_id)), price=views.money(game.who_question_price()),
        limit=rules.WHO_QUESTION_MAX,
    )
    return views.marked(text, "🗳")


async def start_who(
    bot: Bot, game: Game, live: Live, chat_id: int, author: int | None = None, own: str | None = None,
    scheduled: bool = False,
) -> str:
    """'started' or why not: the refusal keys above, or 'failed' when the card didn't go out."""
    if own is not None:
        own = " ".join(own.split())
        if len(own) > rules.WHO_QUESTION_MAX:
            return "long"
        question, title = own, texts.WHO_OWN_TITLE
    else:
        question, _, title = pick(texts.WHO_QUESTIONS, chat_id).partition(" | ")
    status, found = game.start_who(chat_id, question, title, author, scheduled)
    if status == "active" and found is not None and found["ends_at"] <= game.now():
        await live.finish_round(found["id"])  # a poll the clock hasn't closed yet
        status, found = game.start_who(chat_id, question, title, author, scheduled)
    if status != "started" or found is None:
        return status
    text, markup = live.round_card(found)
    message = await send.send_text(bot, chat_id, text, markup)
    if message is None:
        game.drop_round(found["id"])
        return "failed"
    game.repo.set_round_message(found["id"], message.message_id)
    live.watch_round(found["id"])
    return "started"


@router.message(Command("who"))
async def who_command(message: Message, command: CommandObject, bot: Bot, game: Game, live: Live) -> None:
    if message.chat.type == "private":
        await send.reply_personal(bot, message, GROUP_ONLY)
        return
    own = command.args.strip() if command.args else None
    status = await start_who(bot, game, live, message.chat.id, message.from_user.id if own else None, own)
    if status in WHO_REFUSALS:
        await send.reply_personal(bot, message, who_refusal(game, message.chat.id, status))


VOTE_TOASTS = {
    "ok": "🗳 Голос принят",
    "same": "Твой голос уже за этого человека",
    "closed": "Опрос закончился",
    "gone": "Этого опроса больше нет",
}


@router.callback_query(F.data.startswith("wq:"))
async def who_vote(callback: CallbackQuery, game: Game, live: Live) -> None:
    _, round_id, raw = callback.data.split(":", 2)
    status = game.vote_who(round_id, callback.from_user.id, int(raw) if raw.isdigit() else -1)
    await send.answer_quietly(callback, VOTE_TOASTS[status])
    if status == "ok":
        live.request_refresh_round(round_id)


# ── the bomb ──────────────────────────────────────────────────────────

BOMB_REFUSALS = {
    "active": "Бомба уже тикает — смотри выше, у кого она",
    "cooldown": "Новая бомба будет готова через {wait}",
    "shortage": "Бомбу некому кидать: бот знает меньше двух игроков, что были здесь за сутки",
}


def bomb_refusal(game: Game, chat_id: int, status: str) -> str:
    return views.marked(BOMB_REFUSALS[status].format(wait=views.duration(game.bomb_cooldown_left(chat_id))), "💣")


async def start_bomb(bot: Bot, game: Game, live: Live, chat_id: int) -> str:
    status, found = game.start_bomb(chat_id)
    if status == "active" and found is not None and found["ends_at"] <= game.now():
        await live.finish_round(found["id"])
        status, found = game.start_bomb(chat_id)
    if status != "started" or found is None:
        return status
    text, markup = live.round_card(found)
    message = await send.send_text(bot, chat_id, text, markup)
    if message is None:
        game.drop_round(found["id"])
        return "failed"
    game.repo.set_round_message(found["id"], message.message_id)
    live.watch_round(found["id"])
    return "started"


@router.message(Command("bomb"))
async def bomb_command(message: Message, bot: Bot, game: Game, live: Live) -> None:
    if message.chat.type == "private":
        await send.reply_personal(bot, message, GROUP_ONLY)
        return
    status = await start_bomb(bot, game, live, message.chat.id)
    if status in BOMB_REFUSALS:
        await send.reply_personal(bot, message, bomb_refusal(game, message.chat.id, status))


async def holds_bomb(message: Message, game: Game) -> bool:
    """A reply to a person's message by whoever holds the chat's bomb right now. Async: aiogram runs a
    plain function filter in a worker thread, and the database belongs to the event loop's."""
    target = message.reply_to_message.from_user if message.reply_to_message else None
    if message.from_user is None or target is None or target.is_bot or message.chat.type == "private":
        return False
    if (message.text or "").startswith("/"):
        return False  # a command aimed at the person (/rob, /give) stays a command
    found = game.bomb_in(message.chat.id)
    return found is not None and found["holder"] == message.from_user.id


@router.message(holds_bomb)
async def bomb_pass(message: Message, bot: Bot, game: Game, live: Live) -> None:
    found = game.bomb_in(message.chat.id)
    target = message.reply_to_message.from_user
    if found is None or target.id == message.from_user.id:
        return
    game.repo.remember_user(target.id, target.username, target.first_name, target.last_name, game.now())
    if game.pass_bomb(found["id"], message.from_user.id, target.id) == "ok":
        await send.react(bot, message.chat.id, message.message_id, "🔥")
        live.request_refresh_round(found["id"])


@router.callback_query(F.data.startswith("bm:"))
async def bomb_random_pass(callback: CallbackQuery, game: Game, live: Live) -> None:
    round_id = callback.data.split(":", 1)[1]
    found = game.repo.get_round(round_id)
    if found is None or found["status"] != "open":
        await send.answer_quietly(callback, "💥 Уже рвануло")
        return
    if found["holder"] != callback.from_user.id:
        await send.answer_quietly(callback, "💣 Бомба не у тебя. Пока")
        return
    people = game.repo.recent_members(
        found["chat_id"], game.now() - rules.BOMB_PLAYERS_SECONDS, exclude=[callback.from_user.id], limit=50
    )
    if not people:
        await send.answer_quietly_alert(callback, "💣 Передать некому: кроме тебя тут никого не было")
        return
    target = people[game.rng.randrange(len(people))]
    status = game.pass_bomb(round_id, callback.from_user.id, target)
    await send.answer_quietly(callback, "💨 Передано" if status == "ok" else "💥 Не успел никто")
    if status == "ok":
        live.request_refresh_round(round_id)


# ── bets on life ──────────────────────────────────────────────────────

BET_REFUSALS = {
    "long": f"Спор длиннее {rules.BET_CLAIM_MAX} символов. Покороче",
    "too_many": f"В чате уже {rules.BET_OPEN_MAX} открытых споров. Сначала решите старые",
}


def bet_view(game: Game, found: dict) -> tuple[str, object]:
    label = game.repo.user_label
    stakes = [(label(user), side, coins) for user, (side, coins) in found["votes"].items()]
    days_left = max(1, -(-(found["ends_at"] - game.now()) // 86400))
    text = views.bet_card(found["text"], label(found["author"]), stakes, days_left, found["id"])
    return text, keyboards.bet(found["id"], game.bet_stakes())


def bet_result_view(game: Game, result) -> str:
    label = game.repo.user_label
    found = result.round
    stakes = [(label(user), side, coins) for user, (side, coins) in found["votes"].items()]
    payouts = {label(user): coins for user, coins in result.payouts.items()}
    return views.bet_result(found["text"], label(found["author"]), result.outcome, stakes, payouts, found["chat_id"])


@router.message(Command("bet"))
async def bet_command(message: Message, command: CommandObject, bot: Bot, game: Game) -> None:
    if message.chat.type == "private":
        await send.reply_personal(bot, message, GROUP_ONLY)
        return
    status, found = game.open_bet(message.chat.id, message.from_user.id, command.args or "")
    if status == "empty":
        await send.reply_personal(bot, message, views.bet_hint())
        return
    if status in BET_REFUSALS:
        await send.reply_personal(bot, message, views.marked(BET_REFUSALS[status], "🤝"))
        return
    text, markup = bet_view(game, found)
    sent = await send.send_text(bot, message.chat.id, text, markup)
    if sent is None:
        game.repo.drop_round(found["id"])
        return
    game.repo.set_round_message(found["id"], sent.message_id)


STAKE_TOASTS = {
    "author": "Автор спора решает, чем кончилось, и сам не ставит",
    "already": "Твоя ставка уже стоит. Одна на спор",
    "closed": "Спор уже решён",
    "gone": "Этого спора больше нет",
}


@router.callback_query(F.data.startswith("sp:"))
async def bet_stake(callback: CallbackQuery, bot: Bot, game: Game) -> None:
    _, round_id, side, index = callback.data.split(":", 3)
    stakes = game.bet_stakes()
    amount = stakes[int(index)] if index.isdigit() and int(index) < len(stakes) else -1
    status = game.stake_bet(round_id, callback.from_user.id, int(side) if side.isdigit() else -1, amount)
    if status == "poor":
        await send.answer_quietly_alert(callback, plain(f"🤝 На ставку нужно {views.money(amount)}"))
        return
    if status != "ok":
        await send.answer_quietly_alert(callback, f"🤝 {STAKE_TOASTS[status]}")
        return
    await send.answer_quietly(callback, "🤝 Ставка принята")
    found = game.repo.get_round(round_id)
    text, markup = bet_view(game, found)
    await send.edit_text(bot, found["chat_id"], found["message_id"], text, markup)


@router.callback_query(F.data.startswith("sv:"))
async def bet_settle(callback: CallbackQuery, bot: Bot, game: Game) -> None:
    _, round_id, raw = callback.data.split(":", 2)
    status, result = game.settle_bet(round_id, callback.from_user.id, int(raw) if raw in ("0", "1") else 9)
    if status == "not_author":
        await send.answer_quietly_alert(callback, "🤝 Чем кончилось, решает автор спора")
        return
    if result is None:
        await send.answer_quietly(callback, "Спор уже решён")
        return
    await send.answer_quietly(callback, "🏁 Спор закрыт")
    found = result.round
    await send.edit_text(bot, found["chat_id"], found["message_id"], bet_result_view(game, result), None)


async def announce_expired_bets(bot: Bot, game: Game) -> int:
    """Bets nobody settled in time: called off, their cards say so."""
    results = game.expire_bets()
    for result in results:
        found = result.round
        if found["message_id"] is not None:
            await send.edit_text(bot, found["chat_id"], found["message_id"], bet_result_view(game, result), None)
    return len(results)


# ── the games menu ────────────────────────────────────────────────────


@router.callback_query(F.data.in_({"gm:who", "gm:bomb", "gm:bet"}), F.message)
async def party_buttons(callback: CallbackQuery, bot: Bot, game: Game, live: Live) -> None:
    chat_id = callback.message.chat.id
    if chat_id > 0:
        await send.answer_quietly_alert(callback, GROUP_ONLY)
        return
    if callback.data == "gm:bet":
        await send.answer_quietly(callback)
        await send.personal(bot, chat_id, callback.from_user.id, views.bet_hint(), callback_query_id=callback.id)
        return
    if callback.data == "gm:who":
        status = await start_who(bot, game, live, chat_id)
        refusal = who_refusal(game, chat_id, status) if status in WHO_REFUSALS else None
    else:
        status = await start_bomb(bot, game, live, chat_id)
        refusal = bomb_refusal(game, chat_id, status) if status in BOMB_REFUSALS else None
    if refusal:
        await send.answer_quietly_alert(callback, plain(refusal))  # alerts show no markup
    else:
        await send.answer_quietly(callback)
