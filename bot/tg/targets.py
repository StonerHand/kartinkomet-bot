"""Commands aimed at a person or an amount: /rob, /give, /marry, /pvp, /challenge.

The person is whoever's message the command answers, a @mention (Telegram attaches the person
even without a username), or a username or first name typed after the command. When the command
leaves out the person or the amount (as it does when picked from the command menu), the bot asks
instead of explaining the syntax: buttons with the chat's recent players or with amounts, and a
reply to the question with a name or a number works too. The question is personal where Telegram
allows it; otherwise it leaves the chat once answered, or after a few minutes."""

import json
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field

from aiogram import Bot, F, Router
from aiogram.types import CallbackQuery, Message

from bot.core import shop
from bot.game import Game
from bot.tg import keyboards, send, views
from bot.tg.timers import Live

router = Router(name="targets")
ASK_SECONDS = 300
PEOPLE = 8
ACTIVE_SECONDS = 30 * 86400
AMOUNTS = (100, 500, 1000, 5000)


@dataclass(frozen=True)
class Action:
    emoji: str
    person: str | None  # the question when the person is missing; None: the action needs nobody
    amount: str | None  # the question when the amount is missing; None: no amount
    hint: str  # how to aim it by hand, for chats where the bot knows nobody yet
    minimum: int = 1


ACTIONS = {
    "rob": Action("😈", "Кого грабим?", None, "Ответь командой на сообщение человека или напиши ник: /rob vasya"),
    "marry": Action("💍", "Кому предложение?", None, "Ответь командой на сообщение человека: /marry"),
    "give": Action("🎁", "Кому дарим?", "Сколько дарим?", "Ответь на сообщение человека: /give 100"),
    "pvp": Action("🎲", None, "Какая ставка?", "Например: /pvp 200", shop.CHALLENGE_MIN),
    "challenge": Action("🤺", None, "Какая ставка?", "Например: /challenge 200", shop.CHALLENGE_MIN),
}

# Runner(bot, game, live, chat_id, author, state) → a refusal, or None once the thing happened.
# The modules owning the commands register theirs.
Runner = Callable[[Bot, Game, Live, int, int, dict], Awaitable[str | None]]
RUNNERS: dict[str, Runner] = {}


@dataclass
class Aim:
    user: int | None = None
    words: list[str] = field(default_factory=list)  # what's left: amounts, a game, a comment
    unknown: str | None = None  # a name nobody in the bot's memory has


def aim(message: Message, game: Game, args: str | None) -> Aim:
    """Who the command is aimed at: a reply wins, then a name among the words."""
    words = (args or "").split()
    reply = message.reply_to_message
    if reply is not None and reply.from_user is not None and not reply.from_user.is_bot:
        return Aim(reply.from_user.id, words)
    return named(message, game, words)


def named(message: Message, game: Game, words: list[str]) -> Aim:
    """The person among the words: a mention Telegram resolved, a username or a first name."""
    for entity in message.entities or ():
        person = entity.user
        if entity.type == "text_mention" and person is not None and not person.is_bot:
            game.repo.remember_user(person.id, person.username, person.first_name, person.last_name, game.now())
            shown = entity.extract_from(message.text or "").split()
            return Aim(person.id, [word for word in words if word not in shown])
    names = [word for word in words if not word.isdigit()]
    if not names:
        return Aim(None, words)
    found = game.repo.find_member(message.chat.id, " ".join(names))  # «/rob Данил Медведев»
    if found is not None:
        return Aim(found, [word for word in words if word.isdigit()])
    for index, word in enumerate(words):
        if not word.isdigit() and (found := game.repo.find_member(message.chat.id, word)) is not None:
            return Aim(found, words[:index] + words[index + 1 :])
    return Aim(None, words, unknown=names[0])


def amount_of(words: list[str]) -> int | None:
    for word in words:
        if word.isdigit():
            return int(word)
    return None


def unknown_note(name: str) -> str:
    return f"Не знаю, кто такой {views.who(name.lstrip('@'))}: бот запоминает людей, когда они пишут в чат"


async def start(bot: Bot, game: Game, live: Live, message: Message, do: str, found: Aim, **extra) -> None:
    """A command arrived: run it, or ask for what it left out."""
    if message.from_user is None:
        return
    action = ACTIONS[do]
    if found.unknown and action.person is None and found.user is None:
        await send.reply_personal(bot, message, f"{action.emoji} {unknown_note(found.unknown)}")
        return
    state = {"to": found.user, "amount": amount_of(found.words), **extra}
    note = unknown_note(found.unknown) if found.unknown and found.user is None else None
    await go(bot, game, live, message.chat.id, message.from_user.id, do, state, message=message, note=note)


async def go(
    bot: Bot,
    game: Game,
    live: Live,
    chat_id: int,
    author: int,
    do: str,
    state: dict,
    *,
    message: Message | None = None,
    callback: CallbackQuery | None = None,
    note: str | None = None,
) -> None:
    action = ACTIONS[do]
    if action.person and state.get("to") is None:
        await ask(bot, game, chat_id, author, do, state, "person", message=message, callback=callback, note=note)
    elif action.amount and state.get("amount") is None:
        await ask(bot, game, chat_id, author, do, state, "amount", message=message, callback=callback)
    elif refusal := await RUNNERS[do](bot, game, live, chat_id, author, state):
        await tell(bot, refusal, message=message, callback=callback)


async def tell(bot: Bot, text: str, *, message: Message | None = None, callback: CallbackQuery | None = None) -> None:
    """A refusal for the one who asked: a pop-up after a button, a personal reply after a message."""
    if callback is not None:
        await send.answer_quietly_alert(callback, text)
    elif message is not None:
        await send.reply_personal(bot, message, text)


async def ask(
    bot: Bot,
    game: Game,
    chat_id: int,
    author: int,
    do: str,
    state: dict,
    need: str,
    *,
    message: Message | None = None,
    callback: CallbackQuery | None = None,
    note: str | None = None,
) -> None:
    action = ACTIONS[do]
    about = game.repo.user_label(state["to"]) if state.get("to") else None
    if need == "person":
        options = (
            game.repo.recent_members(chat_id, game.now() - ACTIVE_SECONDS, exclude=[author], limit=PEOPLE)
            if chat_id < 0 else []
        )
        if not options:  # a private chat, or a group the bot hasn't met yet
            await tell(bot, f"{action.emoji} {action.hint}", message=message, callback=callback)
            return
        labels = [game.repo.user_label(user) for user in options]
        question, hint = action.person, "Жми на имя или ответь ником"
    else:
        balance = game.repo.player(author)[0]
        options = [amount for amount in AMOUNTS if action.minimum <= amount <= balance]
        if not options and balance >= action.minimum:
            options = [balance]
        if not options:
            text = f"{action.emoji} Нужно хотя бы {views.money(action.minimum)}, а у тебя {views.num(balance)}"
            await tell(bot, text, message=message, callback=callback)
            return
        labels = [keyboards.short(amount) for amount in options]
        question, hint = action.amount, "Жми на сумму или ответь числом"
    text = views.ask(action.emoji, question or "", about, hint, note)
    markup = keyboards.ask(chat_id, author, labels)
    if message is not None:
        sent = await send.reply_personal(bot, message, text, markup, seconds=ASK_SECONDS)
    else:
        sent = await send.personal(
            bot, chat_id, author, text, markup, callback.id if callback else None, fleeting_seconds=ASK_SECONDS
        )
    if sent is None:
        return
    state.update(do=do, need=need, options=options, message=sent.message_id, until=game.now() + ASK_SECONDS)
    game.repo.set_meta(key(chat_id, author), json.dumps(state))


def key(chat_id: int, author: int) -> str:
    return f"ask:{chat_id}:{author}"


def pending(game: Game, chat_id: int, author: int) -> dict | None:
    raw = game.repo.meta_str(key(chat_id, author))
    if not raw:
        return None
    state = json.loads(raw)
    return state if state.get("until", 0) > game.now() else None


def forget(game: Game, chat_id: int, author: int) -> None:
    game.repo.set_meta(key(chat_id, author), "")


@router.callback_query(F.data.startswith("ak:"))
async def picked(callback: CallbackQuery, bot: Bot, game: Game, live: Live) -> None:
    _, raw_chat, raw_author, choice = callback.data.split(":", 3)
    chat_id, author = int(raw_chat), int(raw_author)
    if callback.from_user.id != author:
        await send.answer_quietly_alert(callback, "Это вопрос не тебе. Набери команду сам")
        return
    state = pending(game, chat_id, author)
    shown = callback.message if isinstance(callback.message, Message) else None
    await send.remove(bot, chat_id, shown)
    if state is None or choice == "x" or not choice.isdigit() or int(choice) >= len(state["options"]):
        forget(game, chat_id, author)
        await send.answer_quietly(callback, "Отменено" if choice == "x" else "Вопрос устарел. Набери команду ещё раз")
        return
    forget(game, chat_id, author)
    state["to" if state["need"] == "person" else "amount"] = state["options"][int(choice)]
    await go(bot, game, live, chat_id, author, state["do"], state, callback=callback)
    await send.answer_quietly(callback)  # no-op if a refusal already answered it


async def answer(message: Message, bot: Bot, game: Game, live: Live) -> bool:
    """A reply to the bot's question with a name or a number. True if it was one."""
    if message.from_user is None:
        return False
    chat_id, author = message.chat.id, message.from_user.id
    state = pending(game, chat_id, author)
    if state is None:
        return False
    reply = message.reply_to_message
    if reply is not None and reply.message_id != state["message"]:
        return False  # a reply to some other message of the bot: a caption, a last word
    if reply is None and not message.ephemeral_message_id:
        return False
    words = (message.text or "").split()
    if state["need"] == "person":
        found = named(message, game, words)
        if found.user is None:
            await send.reply_personal(bot, message, "Не нашёл такого. Жми на имя в списке")
            return True
        state["to"] = found.user
    else:
        amount = amount_of(words)
        if amount is None:
            await send.reply_personal(bot, message, "Нужна сумма числом, например 500")
            return True
        state["amount"] = amount
    forget(game, chat_id, author)
    if state["message"]:
        await send.delete(bot, chat_id, state["message"])
    await go(bot, game, live, chat_id, author, state["do"], state, message=message)
    return True


@router.message(F.ephemeral_message_id & F.text)
async def ephemeral_answer(message: Message, bot: Bot, game: Game, live: Live) -> None:
    """Answers to a personal question come as personal messages and may lack the reply link."""
    await answer(message, bot, game, live)
