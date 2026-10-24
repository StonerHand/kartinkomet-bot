"""People: /give, /rob, /marry, /divorce. Who they're aimed at is tg/targets.py's business (a
reply, a mention, a name, or the bot asks); challenges live in tg/challenges.py."""

from aiogram import Bot, F, Router
from aiogram.filters import Command, CommandObject
from aiogram.types import CallbackQuery, Message

from bot.game import Game
from bot.texts import social as texts
from bot.tg import keyboards, send, targets, views
from bot.tg.timers import Live

router = Router(name="social")


@router.message(Command("give"))
async def give(message: Message, command: CommandObject, bot: Bot, game: Game, live: Live) -> None:
    await targets.start(bot, game, live, message, "give", targets.aim(message, game, command.args))


async def run_give(bot: Bot, game: Game, live: Live, chat_id: int, giver: int, state: dict) -> str | None:
    amount = state["amount"]
    status, granted = game.give(giver, state["to"], amount)
    refusals = {"self": "Себе дарить — это просто перекладывать из кармана в карман", "small": "Подарок от 1 🪙",
                "broke": "Столько у тебя нет"}
    if status != "ok":
        return refusals[status]
    labels = (game.repo.user_label(giver), game.repo.user_label(state["to"]))
    await send.send_text(bot, chat_id, views.gift(*labels, amount, chat_id))
    await live.announce(chat_id, granted)
    return None


@router.message(Command("rob"))
async def rob(message: Message, command: CommandObject, bot: Bot, game: Game, live: Live) -> None:
    await targets.start(bot, game, live, message, "rob", targets.aim(message, game, command.args))


async def run_rob(bot: Bot, game: Game, live: Live, chat_id: int, robber: int, state: dict) -> str | None:
    result = game.rob(robber, state["to"])
    if result.status not in ("success", "fail"):
        return texts.ROB_REFUSED[result.status].format(wait=views.duration(result.wait))
    labels = (game.repo.user_label(robber), game.repo.user_label(state["to"]))
    sent = await send.send_text(bot, chat_id, views.robbery(*labels, result, chat_id))
    if sent:
        await send.react(bot, chat_id, sent.message_id, "😈" if result.status == "success" else "🤡")
    await live.announce(chat_id, result.granted)
    return None


# ── marriage ───────────────────────────────────────────────────────────


@router.message(Command("marry"))
async def marry(message: Message, command: CommandObject, bot: Bot, game: Game, live: Live) -> None:
    await targets.start(bot, game, live, message, "marry", targets.aim(message, game, command.args))


async def run_marry(bot: Bot, game: Game, live: Live, chat_id: int, suitor: int, state: dict) -> str | None:
    status, proposal_id = game.propose(chat_id, suitor, state["to"])
    if status != "ok" or proposal_id is None:
        return texts.MARRY_REFUSED[status].format(price=game.wedding_price())
    labels = (game.repo.user_label(suitor), game.repo.user_label(state["to"]))
    await send.send_text(
        bot, chat_id, views.proposal(*labels, game.wedding_price(), chat_id), keyboards.proposal(proposal_id)
    )
    return None


targets.RUNNERS.update(give=run_give, rob=run_rob, marry=run_marry)


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
        text = views.wedding(suitor, beloved, chat_id)
    elif status == "withdrawn":
        text = views.card("💍 <b>ПРЕДЛОЖЕНИЕ</b>", f"{suitor}: предложение отозвано. Бывает")
    else:
        text = views.rejected(suitor, beloved, chat_id)
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
        await send.reply_personal(bot, message, "Ты не в браке. Разводиться не с кем")
        return
    labels = (game.repo.user_label(message.from_user.id), game.repo.user_label(result.spouse))
    sent = await send.send_text(bot, message.chat.id, views.divorce(*labels, result, message.chat.id))
    if sent:
        await send.react(bot, message.chat.id, sent.message_id, "💔")
    await live.announce(message.chat.id, result.granted)
