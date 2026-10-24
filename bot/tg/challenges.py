"""Challenges between players: /challenge (a pic duel the chat votes on) and /pvp (dice, darts or
bowling 1v1), their answers, the throws and rematches."""

import asyncio
import logging

from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramAPIError
from aiogram.filters import Command, CommandObject
from aiogram.types import CallbackQuery, Message

from bot.core import casino, shop
from bot.game import Game
from bot.texts import social as texts
from bot.texts.pick import pick
from bot.tg import keyboards, send, targets, views
from bot.tg.timers import Live

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
        return CHALLENGE_REFUSALS.get(status, "Не вышло")
    await post_challenge(bot, game, live, chat_id, created)
    return None


CHALLENGE_REFUSALS = {
    "small": f"Минимальная ставка — {shop.CHALLENGE_MIN} монет",
    "self": "Вызвать самого себя? Шизофрения не входит в правила",
    "pending": "У тебя уже висит вызов. Дождись ответа",
    "broke": "Столько у тебя нет",
    "gone": "Этот вызов уже не повторить",
    "not_for_you": "Реванш — дело тех двоих",
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
}


@router.message(Command("pvp"))
async def dice_duel(message: Message, command: CommandObject, bot: Bot, game: Game, live: Live) -> None:
    """/pvp 200 [кости|дартс|боулинг]: a casino duel between two players, no house."""
    words = (command.args or "").split()
    choice = next((GAME_WORDS[word.casefold()] for word in words if word.casefold() in GAME_WORDS), "dice")
    words = [word for word in words if word.casefold() not in GAME_WORDS]
    found = targets.aim(message, game, " ".join(words))
    await targets.start(bot, game, live, message, "pvp", found, kind=choice)


targets.RUNNERS.update(challenge=run_challenge, pvp=run_challenge)
targets.PREPARE["pvp"] = lambda game, author: ({"kind": "dice"}, None)  # from the panel: dice, the classic


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
        await callback.answer(CHALLENGE_REFUSALS.get(status, "Не вышло"), show_alert=True)
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
        "not_for_you": "Вызов не тебе. Брось свой: /challenge",
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
    if result.status == "accepted" and result.challenge.get("game"):
        await callback.answer("🎲 Принято! Бросаем")
        await throw_dice_duel(bot, game, live, chat_id, result.challenge, callback.message.message_id)
        return
    if result.status != "accepted" or result.battle is None:
        await callback.answer("Вызов закрыт, ставка вернулась")
        return
    await callback.answer("🤺 Вызов принят! Собираю арену")
    from bot.tg.arena import launch_battle  # local: arena imports timers, avoid a cycle at import

    if await launch_battle(bot, game, live, result.battle) != "started":
        await send.send_text(bot, chat_id, "Арена не открылась — ставки вернулись")
        game.repo.drop_battle(result.battle.id)
        for user in (result.challenge["from_user"], result.challenge["to_user"]):
            game.repo.add_coins(user, result.challenge["stake"], "challenge_refund", game.now(), earn=False)
