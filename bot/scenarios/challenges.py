"""Challenges between players: /challenge (a pic duel the chat votes on), /pvp (dice, darts or
bowling 1v1), /rps and /ttt (rock-paper-scissors, tic-tac-toe on a board), their answers, the throws,
the moves and rematches."""

import asyncio
import logging

from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramAPIError
from aiogram.filters import Command, CommandObject
from aiogram.types import CallbackQuery, Message

from bot.game.engine import Game
from bot.live.timers import Live
from bot.rules import casino, duels, shop
from bot.scenarios import targets, widgets
from bot.scenarios.arena import launch_battle
from bot.telegram import send
from bot.texts import social as texts
from bot.texts.pick import pick
from bot.ui import keyboards, views

LOGGER = logging.getLogger(__name__)
router = Router(name="challenges")
DICE_ANIMATION_SCALE = 1.0  # tests set 0


@router.message(Command("challenge"))
async def challenge(message: Message, command: CommandObject, bot: Bot, game: Game, live: Live) -> None:
    """/challenge 200: an open pic duel for a stake, or aimed at one person (reply, name)."""
    await targets.start(bot, game, live, message, "challenge", targets.aim(message, game, command.args))


async def run_challenge(bot: Bot, game: Game, live: Live, chat_id: int, author: int, state: dict) -> str | None:
    opponent = state.get("to") or None  # 0: anyone
    status, created = game.create_challenge(chat_id, author, opponent, state["amount"], state.get("kind", ""))
    if status != "ok" or created is None:
        return challenge_refusal(game, status)
    await post_challenge(bot, game, live, chat_id, created)
    return None


def challenge_refusal(game: Game, status: str) -> str:
    return CHALLENGE_REFUSALS.get(status, "🤺 Не вышло").format(minimum=game.scaled(shop.CHALLENGE_MIN))


CHALLENGE_REFUSALS = {
    "small": "🤺 Минимальная ставка — {minimum} монет",
    "self": "🤺 Вызвать самого себя? Шизофрения не входит в правила",
    "pending": "🤺 У тебя уже висит вызов. Дождись ответа",
    "broke": "🤺 Столько у тебя нет",
    "gone": "🤺 Этот вызов уже не повторить",
    "not_for_you": "🤺 Реванш — дело тех двоих",
}


async def post_challenge(bot: Bot, game: Game, live: Live, chat_id: int, created: dict) -> bool:
    """Show a fresh challenge card and start its expiry timer; if it can't be shown, the stake
    goes back."""
    labels = {user: game.repo.user_label(user) for user in (created["from_user"], created["to_user"]) if user}
    sent = await send.send_text(
        bot,
        chat_id,
        views.challenge_card(created, labels, chat_id, created["expires_at"] - game.now()),
        keyboards.challenge(created["id"]),
    )
    if sent is None:
        game.answer_challenge(created["id"], created["from_user"], False)
        return False
    game.repo.set_challenge_message(created["id"], sent.message_id)
    live.watch_challenge(created["id"])
    await live.announce(chat_id, game.flush([created["from_user"]]))
    return True


GAME_WORDS = {
    "кости": "dice", "кубики": "dice", "dice": "dice",
    "дартс": "darts", "darts": "darts",
    "боулинг": "bowling", "кегли": "bowling", "bowling": "bowling",
    "кнб": "rps", "камень": "rps", "rps": "rps",
    "крестики": "ttt", "нолики": "ttt", "ttt": "ttt",
}


@router.message(Command("pvp"))
async def dice_duel(message: Message, command: CommandObject, bot: Bot, game: Game, live: Live) -> None:
    """/pvp 200 [кости|дартс|боулинг]: a casino duel between two players, no house."""
    words = (command.args or "").split()
    choice = next((GAME_WORDS[word.casefold()] for word in words if word.casefold() in GAME_WORDS), "dice")
    words = [word for word in words if word.casefold() not in GAME_WORDS]
    found = targets.aim(message, game, " ".join(words))
    await targets.start(bot, game, live, message, "pvp", found, kind=choice)


@router.message(Command("rps", "ttt"))
async def board_duel(message: Message, command: CommandObject, bot: Bot, game: Game, live: Live) -> None:
    """/rps 200, /ttt 200: rock-paper-scissors or tic-tac-toe on a stake."""
    do = (message.text or "").split()[0].lstrip("/").split("@")[0].casefold()
    await targets.start(bot, game, live, message, do, targets.aim(message, game, command.args), kind=do)


targets.RUNNERS.update(challenge=run_challenge, pvp=run_challenge, rps=run_challenge, ttt=run_challenge)
targets.PREPARE["pvp"] = lambda game, author: ({"kind": "dice"}, None)  # from the panel: dice, the classic
targets.PREPARE["rps"] = lambda game, author: ({"kind": "rps"}, None)
targets.PREPARE["ttt"] = lambda game, author: ({"kind": "ttt"}, None)


async def throw_dice_duel(bot: Bot, game: Game, live: Live, chat_id: int, challenge: dict, card_id: int | None) -> None:
    info = casino.GAMES[challenge["game"]]
    try:
        first = await bot.send_dice(chat_id, emoji=info.emoji, reply_to_message_id=card_id)
        second = await bot.send_dice(chat_id, emoji=info.emoji, reply_to_message_id=card_id)
    except TelegramAPIError:
        LOGGER.warning("Dice duel throws failed in %s", chat_id, exc_info=True)
        game.cancel_dice_duel(challenge)
        await send.send_text(bot, chat_id, "🎲 Telegram не дал бросить кубики. Ставки вернулись")
        return
    await asyncio.sleep(info.animation * DICE_ANIMATION_SCALE)
    duel = game.settle_dice_duel(challenge["id"], (first.dice.value, second.dice.value))
    if duel is None:
        return
    labels = {user: game.repo.user_label(user) for user in (challenge["from_user"], challenge["to_user"])}
    sent = await send.send_text(
        bot,
        chat_id,
        views.dice_duel_result(duel, labels, chat_id),
        keyboards.rematch(challenge["id"], challenge["stake"], dice=True),
        reply_to=second.message_id,
    )
    if sent is not None and duel.winner is not None:
        await send.react(bot, chat_id, sent.message_id, "🏆")
    await live.announce(chat_id, duel.granted)


@router.callback_query(F.data.startswith("rm:"), F.message)
async def rematch(callback: CallbackQuery, bot: Bot, game: Game, live: Live) -> None:
    status, created = game.rematch(callback.data.split(":", 1)[1], callback.from_user.id)
    if status != "ok" or created is None:
        await callback.answer(challenge_refusal(game, status), show_alert=True)
        return
    await callback.answer("🔁 Реванш брошен")
    await post_challenge(bot, game, live, callback.message.chat.id, created)


@router.callback_query(F.data.startswith("cl:"))
async def answer_challenge(callback: CallbackQuery, bot: Bot, game: Game, live: Live) -> None:
    _, answer, challenge_id = callback.data.split(":", 2)
    result = game.answer_challenge(
        challenge_id, callback.from_user.id, answer == "y", title=pick(texts.CHALLENGE_DUEL, challenge_id)
    )
    refusals = {
        "gone": "Вызов уже не актуален",
        "not_for_you": "🤺 Вызов не тебе. Брось свой: /challenge",
        "own": "Принять собственный вызов? Не, так не работает",
        "broke": "Не хватает монет, чтобы ответить на ставку",
        "busy": "На арене уже идёт вызов. Подождите минуту",
        "shortage": "На складе не хватает пикч для боя",
    }
    if result.status in refusals:
        await callback.answer(refusals[result.status], show_alert=True)
        return
    if callback.message is None or result.challenge is None:
        await callback.answer()
        return
    chat_id = callback.message.chat.id
    labels = {result.challenge["from_user"]: game.repo.user_label(result.challenge["from_user"])}
    await send.edit_text(
        bot, chat_id, callback.message.message_id, views.challenge_closed(result.challenge, labels, result.status), None
    )
    if result.status == "accepted" and result.challenge.get("game") in duels.BOARD_GAMES:
        await callback.answer(f"{duels.BOARD_GAMES[result.challenge['game']].emoji} Принято! Играем")
        await deal_board(bot, game, live, chat_id, result.challenge, callback.message.message_id)
        return
    if result.status == "accepted" and result.challenge.get("game"):
        await callback.answer("🎲 Принято! Бросаем")
        await throw_dice_duel(bot, game, live, chat_id, result.challenge, callback.message.message_id)
        return
    if result.status != "accepted" or result.battle is None:
        await callback.answer("🤺 Вызов закрыт, ставка вернулась")
        return
    await callback.answer("🤺 Вызов принят! Собираю арену")

    if await launch_battle(bot, game, live, result.battle) != "started":
        await send.send_text(bot, chat_id, "Арена не открылась — ставки вернулись")
        game.repo.drop_battle(result.battle.id)
        for user in (result.challenge["from_user"], result.challenge["to_user"]):
            game.repo.add_coins(user, result.challenge["stake"], "challenge_refund", game.now(), earn=False)


# ── board duels: rock-paper-scissors, tic-tac-toe ─────────────────────


async def deal_board(bot: Bot, game: Game, live: Live, chat_id: int, challenge: dict, card_id: int | None) -> None:
    """The accepted board duel's card under the challenge (an HTML widget where the chat has them
    on); its clock goes to the live cards."""
    state = game.deal_board(challenge)
    sent = None
    if widgets.enabled(game, chat_id):
        data = live.duel_widget_data(challenge, state)
        sent = await widgets.post(bot, game, chat_id, challenge["game"], challenge["id"], data, reply_to=card_id)
        if sent is not None:
            game.mark_duel_widget(challenge["id"])
    if sent is None:
        text, markup = live.duel_card(challenge["id"])
        sent = await send.send_text(bot, chat_id, text, markup, reply_to=card_id)
    if sent is None:
        game.cancel_dice_duel(challenge)  # nothing was played: both stakes back
        await send.send_text(bot, chat_id, "🤺 Telegram не дал показать доску. Ставки вернулись")
        return
    game.set_duel_message(challenge["id"], sent.message_id)
    live.watch_duel(challenge["id"])


PICK_TOASTS = {
    "already": "✊ Выбор уже сделан, его не поменять",
    "not_player": "✊ Это не твоя игра. Брось свою: /rps",
    "gone": "✊ Эта игра закончилась",
}
MOVE_TOASTS = {
    "not_turn": "⏳ Сейчас не твой ход",
    "taken": "❌ Клетка занята",
    "not_player": "❌ Это не твоя партия. Брось свою: /ttt",
    "gone": "❌ Партия закончилась",
}


@router.callback_query(F.data.startswith("rp:"))
async def rps_pick(callback: CallbackQuery, game: Game, live: Live) -> None:
    _, challenge_id, raw = (callback.data.split(":", 2) + ["", ""])[:3]
    pick_ = int(raw) if raw.isdigit() else -1
    status, duel = game.pick_rps(challenge_id, callback.from_user.id, pick_)
    if status in PICK_TOASTS:
        await send.answer_quietly(callback, PICK_TOASTS[status])
        return
    if status == "ok":
        await send.answer_quietly(callback, f"{duels.RPS[pick_]} Выбрано: {duels.RPS_NAMES[pick_]}. Ждём соперника")
        live.request_refresh_duel(challenge_id)
    elif status == "draw":
        await send.answer_quietly(callback, "🔁 Одинаково! Ещё раунд")
        live.request_refresh_duel(challenge_id)
    else:
        await send.answer_quietly(callback, f"{duels.RPS[pick_]} Руки показаны")
        await live.settle_duel(duel)


@router.callback_query(F.data.startswith("tt:"))
async def ttt_move(callback: CallbackQuery, game: Game, live: Live) -> None:
    _, challenge_id, raw = (callback.data.split(":", 2) + ["", ""])[:3]
    if raw == "x":
        await send.answer_quietly(callback, "❌ Партия закончилась")
        return
    status, duel = game.move_ttt(challenge_id, callback.from_user.id, int(raw) if raw.isdigit() else -1)
    if status in MOVE_TOASTS:
        await send.answer_quietly(callback, MOVE_TOASTS[status])
        return
    await send.answer_quietly(callback)
    if status == "ok":
        await live.refresh_duel(challenge_id)  # the other player waits for this board: no debounce
    else:
        await live.settle_duel(duel)
