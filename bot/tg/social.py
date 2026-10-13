"""People: /give, /rob, /marry, /divorce, /challenge. The target is the person whose message you
reply to, or a username after the command: /give vasya 100."""

from aiogram import Bot, F, Router
from aiogram.filters import Command, CommandObject
from aiogram.types import CallbackQuery, Message

from bot.core import shop
from bot.game import Game
from bot.texts import social as texts
from bot.texts.pick import pick
from bot.tg import cards, keyboards, send, views
from bot.tg.timers import Live

router = Router(name="social")


def target_and_rest(message: Message, game: Game, args: str | None) -> tuple[int | None, list[str]]:
    """Who the command is about, plus the remaining words (amounts)."""
    words = (args or "").split()
    reply = message.reply_to_message
    if reply is not None and reply.from_user is not None and not reply.from_user.is_bot:
        return reply.from_user.id, words
    for index, word in enumerate(words):
        if word.isdigit():
            continue
        user_id = game.repo.user_by_name(word)
        if user_id is not None:
            return user_id, words[:index] + words[index + 1 :]
    return None, words


def amount_of(words: list[str]) -> int | None:
    for word in words:
        if word.isdigit():
            return int(word)
    return None


NO_TARGET = "Ответь этой командой на сообщение человека или напиши его ник: {example}"


@router.message(Command("give"))
async def give(message: Message, command: CommandObject, bot: Bot, game: Game, live: Live) -> None:
    if message.from_user is None:
        return
    target, rest = target_and_rest(message, game, command.args)
    amount = amount_of(rest)
    if target is None or amount is None:
        await message.reply(NO_TARGET.format(example="/give vasya 100"))
        return
    status, granted = game.give(message.from_user.id, target, amount)
    refusals = {"self": "Себе дарить — это просто перекладывать из кармана в карман", "small": "Подарок от 1 🪙",
                "broke": "Столько у тебя нет"}
    if status != "ok":
        await message.reply(refusals[status])
        return
    labels = (game.repo.user_label(message.from_user.id), game.repo.user_label(target))
    await send.send_text(bot, message.chat.id, cards.gift(*labels, amount, message.chat.id))
    await live.announce(message.chat.id, granted)


@router.message(Command("rob"))
async def rob(message: Message, command: CommandObject, bot: Bot, game: Game, live: Live) -> None:
    if message.from_user is None:
        return
    target, _ = target_and_rest(message, game, command.args)
    if target is None:
        await message.reply(NO_TARGET.format(example="/rob vasya"))
        return
    result = game.rob(message.from_user.id, target)
    if result.status not in ("success", "fail"):
        await message.reply(texts.ROB_REFUSED[result.status].format(wait=cards.duration(result.wait)))
        return
    labels = (game.repo.user_label(message.from_user.id), game.repo.user_label(target))
    sent = await send.send_text(bot, message.chat.id, cards.robbery(*labels, result, message.chat.id))
    if sent:
        await send.react(bot, message.chat.id, sent.message_id, "😈" if result.status == "success" else "🤡")
    await live.announce(message.chat.id, result.granted)


# ── marriage ───────────────────────────────────────────────────────────


@router.message(Command("marry"))
async def marry(message: Message, command: CommandObject, bot: Bot, game: Game) -> None:
    if message.from_user is None:
        return
    target, _ = target_and_rest(message, game, command.args)
    if target is None:
        await message.reply(NO_TARGET.format(example="/marry vasya"))
        return
    status, proposal_id = game.propose(message.chat.id, message.from_user.id, target)
    if status != "ok" or proposal_id is None:
        await message.reply(texts.MARRY_REFUSED[status].format(price=game.wedding_price()))
        return
    labels = (game.repo.user_label(message.from_user.id), game.repo.user_label(target))
    await send.send_text(
        bot,
        message.chat.id,
        cards.proposal(*labels, game.wedding_price(), message.chat.id),
        keyboards.proposal(proposal_id),
    )


@router.callback_query(F.data.startswith("mr:"))
async def answer_proposal(callback: CallbackQuery, bot: Bot, game: Game, live: Live) -> None:
    _, answer, proposal_id = callback.data.split(":", 2)
    status, proposal, granted = game.answer_proposal(proposal_id, callback.from_user.id, answer == "y")
    refusals = {
        "gone": "Это предложение уже не актуально",
        "not_for_you": "Отвечать не тебе. Не встревай",
        "expired": "Предложение протухло. Кольцо вернули в ломбард",
        "broke": f"На свадьбу нужно {game.wedding_price()} 🪙 с каждого. Не хватает",
        "taken": "Кто-то из вас уже в браке",
    }
    if status in refusals:
        await callback.answer(refusals[status], show_alert=True)
        return
    await callback.answer()
    if callback.message is None or proposal is None:
        return
    chat_id = callback.message.chat.id
    suitor, beloved = game.repo.user_label(proposal["from_user"]), game.repo.user_label(proposal["to_user"])
    if status == "married":
        text = cards.wedding(suitor, beloved, chat_id)
    elif status == "withdrawn":
        text = views.card("💍 <b>ПРЕДЛОЖЕНИЕ</b>", f"{suitor}: предложение отозвано. Бывает")
    else:
        text = cards.rejected(suitor, beloved, chat_id)
    await send.edit_text(bot, chat_id, callback.message.message_id, text, None)
    if status == "married":
        await send.react(bot, chat_id, callback.message.message_id, "❤", big=True)
    await live.announce(chat_id, granted)


@router.message(Command("divorce"))
async def divorce(message: Message, bot: Bot, game: Game, live: Live) -> None:
    if message.from_user is None:
        return
    result = game.divorce(message.from_user.id)
    if result.status != "ok" or result.spouse is None:
        await message.reply("Ты не в браке. Разводиться не с кем")
        return
    labels = (game.repo.user_label(message.from_user.id), game.repo.user_label(result.spouse))
    sent = await send.send_text(bot, message.chat.id, cards.divorce(*labels, result, message.chat.id))
    if sent:
        await send.react(bot, message.chat.id, sent.message_id, "💔")
    await live.announce(message.chat.id, result.granted)


# ── challenges ─────────────────────────────────────────────────────────


@router.message(Command("challenge"))
async def challenge(message: Message, command: CommandObject, bot: Bot, game: Game, live: Live) -> None:
    if message.from_user is None:
        return
    target, rest = target_and_rest(message, game, command.args)
    stake = amount_of(rest)
    if stake is None:
        await message.reply(
            f"Укажи ставку: /challenge 200 — открытый вызов, или ответь так на сообщение человека. "
            f"Минимум {shop.CHALLENGE_MIN} 🪙"
        )
        return
    status, created = game.create_challenge(message.chat.id, message.from_user.id, target, stake)
    refusals = {
        "small": f"Минимальная ставка — {shop.CHALLENGE_MIN} 🪙",
        "self": "Вызвать самого себя? Шизофрения не входит в правила",
        "pending": "У тебя уже висит вызов. Дождись ответа",
        "broke": "Столько у тебя нет",
    }
    if status != "ok" or created is None:
        await message.reply(refusals.get(status, "Не вышло"))
        return
    labels = {user: game.repo.user_label(user) for user in (created["from_user"], created["to_user"]) if user}
    sent = await send.send_text(
        bot,
        message.chat.id,
        cards.challenge_card(created, labels, message.chat.id, created["expires_at"] - game.now()),
        keyboards.challenge(created["id"]),
    )
    if sent is None:
        game.answer_challenge(created["id"], message.from_user.id, False)
        return
    game.repo.set_challenge_message(created["id"], sent.message_id)
    live.watch_challenge(created["id"])
    await live.announce(message.chat.id, game.flush([message.from_user.id]))


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
        bot, chat_id, callback.message.message_id, cards.challenge_closed(result.challenge, labels, result.status), None
    )
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
