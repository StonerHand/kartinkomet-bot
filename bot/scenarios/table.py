"""Table games of the chat: /spy, /mines, /safe, /pieces, and the bids of the daily auction."""

from aiogram import Bot, F, Router
from aiogram.filters import Command, CommandObject
from aiogram.types import BufferedInputFile, CallbackQuery, Message

from bot.game.engine import Game
from bot.live.timers import Live
from bot.rules import auction as auction_rules
from bot.rules import games as game_rules
from bot.rules import table as rules
from bot.telegram import pictures, send
from bot.texts import party as party_texts
from bot.texts.pick import pick
from bot.ui import keyboards, views
from bot.ui.layout import plain

router = Router(name="table")

GROUP_ONLY = "👥 Это игра для группового чата: добавь бота в чат и зови всех туда"
REFUSALS = {
    "spy": ("🎭", {"active": "Шпион уже идёт — смотри выше", "cooldown": "Следующий шпион — через {wait}"}),
    "mines": ("🧨", {"active": "Поле уже лежит — смотри выше", "cooldown": "Новое поле — через {wait}"}),
    "safe": ("🔐", {"active": "Сейф уже стоит — отвечай ему кодом", "cooldown": "Новый сейф привезут через {wait}"}),
    "piece": ("🧩", {"active": "Кусочек уже на столе — смотри выше", "cooldown": "Следующий кусочек — через {wait}",
                     "shortage": "На складе меньше четырёх пикч", "failed": "Не получилось нарезать пикчи. Попробуй ещё"}),
}


def refusal(game: Game, chat_id: int, kind: str, status: str) -> str | None:
    emoji, texts = REFUSALS[kind]
    if status not in texts:
        return None
    left = {"spy": game.spy_cooldown_left, "mines": game.mines_cooldown_left, "safe": game.safe_cooldown_left,
            "piece": game.piece_cooldown_left}[kind](chat_id)
    return views.marked(texts[status].format(wait=views.duration(left)), emoji)


async def post_round(bot: Bot, game: Game, live: Live, found: dict) -> str:
    """Send a new round's card and start watching it: 'started', or 'failed' (the round is gone)."""
    text, markup = live.round_card(found)
    message = await send.send_text(bot, found["chat_id"], text, markup)
    if message is None:
        game.repo.drop_round(found["id"])
        return "failed"
    game.repo.set_round_message(found["id"], message.message_id)
    live.watch_table(found["id"])
    return "started"


async def start(bot: Bot, game: Game, live: Live, chat_id: int, kind: str, user_id: int) -> str:
    """'started' or why not. A round whose clock ran out while the bot was busy is settled first."""
    if kind == "piece":
        return await start_piece(bot, game, live, chat_id)
    starters = {"spy": lambda: game.start_spy(chat_id, user_id, pick(party_texts.CROC_WORDS, chat_id)),
                "mines": lambda: game.start_mines(chat_id), "safe": lambda: game.start_safe(chat_id)}
    status, found = starters[kind]()
    if status == "active" and found is not None and found["ends_at"] <= game.now() and kind != "spy":
        await live.finish_table(found["id"])
        status, found = starters[kind]()
    if status != "started" or found is None:
        return status
    return await post_round(bot, game, live, found)


async def start_piece(bot: Bot, game: Game, live: Live, chat_id: int) -> str:
    status, found = game.start_piece(chat_id)
    if status != "started" or found is None:
        return status
    state = game.piece_state(found)
    pics = game.piece_pics(found)
    board = await pictures.build_pieces(bot, pics, state["answer"], game_rules.PIECE_ZOOMS[0], tuple(state["center"]))
    if board is None:
        game.repo.drop_round(found["id"])
        return "failed"
    text, markup = live.round_card(found)
    message = await send.send_photo(bot, chat_id, BufferedInputFile(board, "pieces.jpg"), text, markup)
    if message is None:
        game.repo.drop_round(found["id"])
        return "failed"
    game.repo.set_round_message(found["id"], message.message_id)
    live.watch_table(found["id"])
    return "started"


async def launch(message: Message, bot: Bot, game: Game, live: Live, kind: str) -> None:
    if message.chat.type == "private":
        await send.reply_personal(bot, message, GROUP_ONLY)
        return
    status = await start(bot, game, live, message.chat.id, kind, message.from_user.id)
    answer = refusal(game, message.chat.id, kind, status)
    if answer:
        await send.reply_personal(bot, message, answer)


@router.message(Command("spy"))
async def spy_command(message: Message, bot: Bot, game: Game, live: Live) -> None:
    await launch(message, bot, game, live, "spy")


@router.message(Command("mines"))
async def mines_command(message: Message, bot: Bot, game: Game, live: Live) -> None:
    await launch(message, bot, game, live, "mines")


@router.message(Command("pieces"))
async def pieces_command(message: Message, bot: Bot, game: Game, live: Live) -> None:
    await launch(message, bot, game, live, "piece")


@router.message(Command("safe"))
async def safe_command(message: Message, command: CommandObject, bot: Bot, game: Game, live: Live) -> None:
    """/safe starts one; /safe 0729 is a try at the one standing."""
    code = (command.args or "").strip()
    found = game.safe_in(message.chat.id) if code and message.chat.type != "private" else None
    if found is not None:
        await try_code(message, bot, game, live, found, code)
        return
    await launch(message, bot, game, live, "safe")


@router.callback_query(F.data.in_({"gm:spy", "gm:mines", "gm:safe", "gm:piece"}), F.message)
async def game_buttons(callback: CallbackQuery, bot: Bot, game: Game, live: Live) -> None:
    chat_id = callback.message.chat.id
    if chat_id > 0:
        await send.answer_quietly_alert(callback, GROUP_ONLY)
        return
    kind = callback.data.split(":", 1)[1]
    status = await start(bot, game, live, chat_id, kind, callback.from_user.id)
    answer = refusal(game, chat_id, kind, status)
    if answer:
        await send.answer_quietly_alert(callback, plain(answer))
    else:
        await send.answer_quietly(callback)


# ── the spy ───────────────────────────────────────────────────────────

JOIN_TOASTS = {
    "ok": "🙋 Ты в игре",
    "already": "🙋 Ты уже в игре",
    "full": f"🎭 Мест нет: играют {rules.SPY_MAX}",
    "started": "🎭 Игра уже началась",
    "gone": "🎭 Этой игры больше нет",
}
VOTE_TOASTS = {
    "ok": "🗳 Голос принят",
    "same": "🗳 Твой голос уже здесь",
    "self": "🎭 За себя голосовать нельзя",
    "not_player": "🎭 Голосуют только игроки",
    "closed": "🎭 Голосование закончилось",
    "gone": "🎭 Этой игры больше нет",
}
SECRETS = {
    "spy": "🕶 Ты шпион. Слова не знаешь: слушай других и не спались",
    "waiting": "🎭 Слово придёт, когда закончится сбор",
    "not_player": "🎭 Ты не в этой игре. Следующую не пропусти",
    "gone": "🎭 Этой игры больше нет",
}


@router.callback_query(F.data.startswith("sy:"))
async def spy_button(callback: CallbackQuery, game: Game, live: Live) -> None:
    parts = callback.data.split(":")
    action, round_id = parts[1], parts[2] if len(parts) > 2 else ""
    if action == "j":
        status = game.join_spy(round_id, callback.from_user.id)
        await send.answer_quietly(callback, JOIN_TOASTS[status])
        if status == "ok":
            live.request_refresh_round(round_id)
    elif action == "w":
        status, word = game.spy_secret(round_id, callback.from_user.id)
        text = f"🤫 Твоё слово: {word}. Не называй его прямо" if status == "word" else SECRETS[status]
        await send.answer_quietly_alert(callback, text)
    else:
        index = parts[3] if len(parts) > 3 else ""
        status = game.vote_spy(round_id, callback.from_user.id, int(index) if index.isdigit() else -1)
        await send.answer_quietly(callback, VOTE_TOASTS[status])
        if status == "ok":
            live.request_refresh_round(round_id)


# ── the minefield ─────────────────────────────────────────────────────


@router.callback_query(F.data.startswith("mn:"))
async def mines_button(callback: CallbackQuery, game: Game, live: Live) -> None:
    _, round_id, raw = (callback.data.split(":", 2) + ["", ""])[:3]
    if raw == "x":
        await send.answer_quietly(callback, "🧨 Это поле уже закрыто")
        return
    if raw == "c":
        status, paid = game.cash_mines(round_id, callback.from_user.id)
        texts = {"ok": f"💰 +{views.coins(paid)} в кошелёк", "empty": "💰 Забирать нечего: открой клетку",
                 "closed": "🧨 Поле уже закрыто", "gone": "🧨 Этого поля больше нет"}
        await send.answer_quietly(callback, texts[status])
        if status == "ok":
            live.request_refresh_round(round_id)
        return
    move = game.open_cell(round_id, callback.from_user.id, int(raw) if raw.isdigit() else -1)
    if move.status == "safe":
        await send.answer_quietly(callback, f"✅ Пусто! +{views.coins(game.reward(move.value))} в твой банк")
        live.request_refresh_round(round_id)
    elif move.status in ("boom", "cleared"):
        await send.answer_quietly(callback, "💥 Мина!" if move.status == "boom" else "🏁 Поле чистое!")
        if move.result is not None:
            await live.settle_mines(move.result)
    else:
        texts = {"open": "✅ Эта клетка уже открыта", "closed": "🧨 Поле уже закрыто", "gone": "🧨 Этого поля больше нет"}
        await send.answer_quietly(callback, texts[move.status])


# ── the safe ──────────────────────────────────────────────────────────


async def answers_safe(message: Message, game: Game) -> bool:
    """A reply to the open safe's card with a code."""
    reply = message.reply_to_message
    if reply is None or not message.text or message.chat.type == "private" or message.from_user is None:
        return False
    if message.text.startswith("/"):
        return False  # a command sent in reply stays a command
    found = game.repo.round_by_message(message.chat.id, reply.message_id)
    return found is not None and found["kind"] == "safe" and found["status"] == "open"


@router.message(answers_safe)
async def safe_reply(message: Message, bot: Bot, game: Game, live: Live) -> None:
    found = game.repo.round_by_message(message.chat.id, message.reply_to_message.message_id)
    await try_code(message, bot, game, live, found, message.text.strip())


async def try_code(message: Message, bot: Bot, game: Game, live: Live, found: dict, code: str) -> None:
    attempt = game.guess_safe(found["id"], message.from_user.id, code)
    refusals = {
        "invalid": f"Код — {rules.SAFE_DIGITS} разные цифры, например 0729",
        "poor": f"Попытка стоит {views.money(game.safe_price())}",
        "wait": f"Следующая попытка — через {attempt.wait} с",
        "closed": "Сейф уже закрыт",
        "gone": "Этого сейфа больше нет",
    }
    if attempt.status in refusals:
        await send.reply_personal(bot, message, views.marked(refusals[attempt.status], "🔐"))
        return
    if attempt.status == "cracked" and attempt.result is not None:
        await send.react(bot, message.chat.id, message.message_id, "🎉", big=True)
        await live.settle_safe(attempt.result)
        return
    await send.react(bot, message.chat.id, message.message_id, "👀")
    live.request_refresh_round(found["id"])


# ── pic by pieces ─────────────────────────────────────────────────────

PIECE_TOASTS = {
    "ok": "🧩 Ответ принят. Итог — когда кусочки кончатся",
    "already": "🧩 Ответ уже есть, он один",
    "closed": "🧩 Раунд закончился",
    "gone": "🧩 Этого раунда больше нет",
}


@router.callback_query(F.data.startswith("pc:"))
async def piece_guess(callback: CallbackQuery, game: Game, live: Live) -> None:
    _, round_id, raw = (callback.data.split(":", 2) + ["", ""])[:3]
    status = game.guess_piece(round_id, callback.from_user.id, int(raw) if raw.isdigit() else -1)
    await send.answer_quietly(callback, PIECE_TOASTS[status])
    if status == "ok":
        live.request_refresh_round(round_id)


# ── the blind auction ─────────────────────────────────────────────────


async def open_auction(bot: Bot, game: Game, chat_id: int) -> bool:
    """OPEN_HOUR: the day's lot; bids until CLOSE_HOUR, local time."""
    closes_at = game.now() + (auction_rules.CLOSE_HOUR - game.local_hour()) * 3600 - game.now() % 3600
    if closes_at <= game.now():
        return False
    status, found = game.open_auction(chat_id, closes_at)
    if status != "opened" or found is None:
        return False
    text = views.auction_card(game.auction_lot(found), 0, game.auction_raises(), game.auction_min_price(), found["id"])
    message = await send.send_text(bot, chat_id, text, keyboards.auction(found["id"], game.auction_raises()))
    if message is None:
        game.repo.drop_round(found["id"])
        return False
    game.repo.set_round_message(found["id"], message.message_id)
    return True


async def settle_auctions(bot: Bot, game: Game, live: Live) -> int:
    """Every schedule tick: auctions past CLOSE_HOUR are sold, their cards say to whom."""
    results = game.settle_due_auctions()
    for result in results:
        found = result.round
        winner = game.repo.user_label(result.winner) if result.winner is not None else None
        text = views.auction_result(result.lot, winner, result.price, result.bidders, found["chat_id"])
        if found["message_id"] is not None:
            await send.edit_text(bot, found["chat_id"], found["message_id"], text, keyboards.more_only())
        else:
            await send.send_text(bot, found["chat_id"], text, keyboards.more_only())
        await live.announce(found["chat_id"], list(result.granted))
    return len(results)


@router.callback_query(F.data.startswith("au:"))
async def auction_button(callback: CallbackQuery, game: Game, live: Live) -> None:
    _, round_id, raw = (callback.data.split(":", 2) + ["", ""])[:3]
    user_id = callback.from_user.id
    gone = {"closed": "🔨 Торги закрыты", "gone": "🔨 Этого аукциона больше нет"}
    if raw == "m":
        bid = game.my_bid(round_id, user_id)
        await send.answer_quietly_alert(
            callback, f"🔨 Твоя ставка: {views.coins(bid)}" if bid else "🔨 Ставки пока нет. Жми «+»"
        )
        return
    if raw == "x":
        status, back = game.withdraw_bid(round_id, user_id)
        texts = {"ok": f"↩️ Вернулось {views.coins(back)}", "empty": "🔨 Ставки нет — забирать нечего", **gone}
        await send.answer_quietly(callback, texts[status])
        if status == "ok":
            live.request_refresh_round(round_id)
        return
    status, amount = game.raise_bid(round_id, user_id, int(raw) if raw.isdigit() else -1)
    texts = {"ok": f"🔨 Твоя ставка теперь {views.coins(amount)}. Её видишь только ты",
             "poor": f"🔨 Не хватает: нужно {views.coins(amount)}", **gone}
    await send.answer_quietly_alert(callback, texts[status])
    if status == "ok":
        live.request_refresh_round(round_id)
