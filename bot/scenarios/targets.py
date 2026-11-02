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
from bot.tg.runtime import send
from bot.tg.runtime.timers import Live
from bot.tg.ui import keyboards, views

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
    anyone: bool = False  # the person may be "anyone" (an open challenge); asked only if nothing was given
    confirm: str | None = None  # a yes-or-no question before something that can't be undone
    nobody: str | None = None  # when the chat has players but none fits (all poor, all married)
    stakes: str = "Обратно не склеить"  # under a yes-or-no question: what it costs


ACTIONS = {
    "rob": Action(
        "😈", "Кого грабим?", None, "Ответь командой на сообщение человека или напиши ник: /rob vasya",
        nobody="Грабить некого: у всех меньше 100 монет или их только что ограбили",
    ),
    "marry": Action(
        "💍", "Кому предложение?", None, "Ответь командой на сообщение человека: /marry",
        nobody="Свободных людей не видно. Ответь командой на сообщение человека: /marry",
    ),
    "give": Action("🎁", "Кому дарим?", "Сколько дарим?", "Ответь на сообщение человека: /give 100"),
    "pvp": Action("🎲", "С кем играем?", "Какая ставка?", "Например: /pvp 200", shop.CHALLENGE_MIN, anyone=True),
    "challenge": Action(
        "🤺", "Кого вызываем?", "Какая ставка?", "Например: /challenge 200", shop.CHALLENGE_MIN, anyone=True
    ),
    "divorce": Action("💔", None, None, "", confirm="Разводимся?", stakes="Монеты поделятся пополам. Обратно не склеить"),
}
ANYONE = 0  # the person "anyone" in a question's options

# The modules owning the commands register:
# RUNNERS: (bot, game, live, chat_id, author, state) → a refusal, or None once the thing happened;
# PREPARE: (game, author) → the starting state for actions started with nothing typed (panel
#   buttons, /divorce), or None and a refusal;
# CHECKS: (game, author) → why the author can't do it at all right now (jail, no ring money), asked
#   before any question so nobody picks a victim only to hear "you're in jail";
# FILTERS: (game, author, person) → whether the person is worth offering.
Runner = Callable[[Bot, Game, Live, int, int, dict], Awaitable[str | None]]
RUNNERS: dict[str, Runner] = {}
PREPARE: dict[str, Callable[[Game, int], tuple[dict | None, str | None]]] = {}
CHECKS: dict[str, Callable[[Game, int], str | None]] = {}
FILTERS: dict[str, Callable[[Game, int, int], bool]] = {}


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
    return f"Не знаю никого по имени {views.who(name.lstrip('@'))}: бот запоминает людей, когда они пишут в чат"


async def start(bot: Bot, game: Game, live: Live, message: Message, do: str, found: Aim, **extra) -> None:
    """A command arrived: run it, or ask for what it left out."""
    if message.from_user is None:
        return
    action = ACTIONS[do]
    if found.unknown and found.user is None and (action.person is None or action.anyone):  # a typo, not «anyone»
        await send.reply_personal(bot, message, f"{action.emoji} {unknown_note(found.unknown)}")
        return
    if do in CHECKS and (refusal := CHECKS[do](game, message.from_user.id)):
        await send.reply_personal(bot, message, views.marked(refusal, action.emoji))
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
) -> bool:
    """Run the action, or ask for what's missing. True if a button press got answered (a refusal
    pop-up), so the caller doesn't answer it twice."""
    action = ACTIONS[do]
    if action.anyone and state.get("to") is None:
        if state.get("amount") is not None or not candidates(game, chat_id, author, do):
            state["to"] = ANYONE  # «/pvp 200», or nobody to pick: open to anyone, no questions
    if action.person and state.get("to") is None:
        return await ask(bot, game, chat_id, author, do, state, "person", message=message, callback=callback, note=note)
    if action.amount and state.get("amount") is None:
        return await ask(bot, game, chat_id, author, do, state, "amount", message=message, callback=callback)
    if action.confirm and not state.get("sure"):
        return await ask(bot, game, chat_id, author, do, state, "sure", message=message, callback=callback)
    if refusal := await RUNNERS[do](bot, game, live, chat_id, author, state):
        return await tell(bot, views.marked(refusal, action.emoji), message=message, callback=callback)
    return False


async def begin(
    bot: Bot,
    game: Game,
    live: Live,
    chat_id: int,
    author: int,
    do: str,
    *,
    message: Message | None = None,
    callback: CallbackQuery | None = None,
) -> bool:
    """An action started with nothing typed: everything it needs is asked. Returns like go()."""
    state, refusal = PREPARE[do](game, author) if do in PREPARE else ({}, None)
    if state is not None and do in CHECKS and (refusal := CHECKS[do](game, author)):
        state = None
    if state is None:
        return await tell(bot, views.marked(refusal or "Не вышло", ACTIONS[do].emoji), message=message, callback=callback)
    return await go(bot, game, live, chat_id, author, do, state, message=message, callback=callback)


async def tell(bot: Bot, text: str, *, message: Message | None = None, callback: CallbackQuery | None = None) -> bool:
    """A refusal for the one who asked: a pop-up after a button (True: the press is answered), a
    personal reply after a message."""
    if callback is not None:
        await send.answer_quietly_alert(callback, text)
        return True
    if message is not None:
        await send.reply_personal(bot, message, text)
    return False


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
) -> bool:
    """Returns like go()."""
    action = ACTIONS[do]
    about = game.repo.user_label(state["to"]) if state.get("to") else None
    if need == "person":
        options = candidates(game, chat_id, author, do)
        if not options:  # a private chat, a group the bot hasn't met yet, or nobody fits
            known = action.nobody and candidates(game, chat_id, author)
            text = f"{action.emoji} {action.nobody if known else action.hint}"
            return await tell(bot, text, message=message, callback=callback)
        labels = [game.repo.user_label(user) for user in options]
        if action.anyone:
            options, labels = [*options, ANYONE], [*labels, "🌍 Любой"]
        question, hint = action.person, "Жми на имя или ответь ником"
    elif need == "sure":
        options, labels = [1], [f"{action.emoji} Да"]
        question, hint = action.confirm, action.stakes
    else:
        balance = game.repo.player(author)[0]
        options = [amount for amount in AMOUNTS if action.minimum <= amount <= balance]
        if not options and balance >= action.minimum:
            options = [balance]
        if not options:
            text = f"{action.emoji} Нужно хотя бы {views.money(action.minimum)}, а у тебя {views.num(balance)}"
            return await tell(bot, text, message=message, callback=callback)
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
        return False
    state.update(do=do, need=need, options=options, message=sent.message_id, until=game.now() + ASK_SECONDS)
    game.repo.set_meta(key(chat_id, author), json.dumps(state))
    return False


FIELDS = {"person": "to", "amount": "amount", "sure": "sure"}


def candidates(game: Game, chat_id: int, author: int, do: str | None = None) -> list[int]:
    """Whom to offer: the group's recently seen players, the author aside, and for `do` only those
    it can be done to."""
    if chat_id > 0:
        return []
    keep = FILTERS.get(do or "")
    people = game.repo.recent_members(chat_id, game.now() - ACTIVE_SECONDS, exclude=[author], limit=PEOPLE * 4)
    return [person for person in people if keep is None or keep(game, author, person)][:PEOPLE]


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
    state[FIELDS[state["need"]]] = state["options"][int(choice)]
    if not await go(bot, game, live, chat_id, author, state["do"], state, callback=callback):
        await send.answer_quietly(callback)


async def answer(message: Message, bot: Bot, game: Game, live: Live) -> bool:
    """A reply to the bot's question with a name or a number. True if it was one."""
    if message.from_user is None:
        return False
    chat_id, author = message.chat.id, message.from_user.id
    state = pending(game, chat_id, author)
    if state is None or state["need"] == "sure":  # a yes-or-no is answered with its button
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
            await send.reply_personal(bot, message, "🔍 Никого с таким именем. Жми на имя в списке")
            return True
        state["to"] = found.user
    else:
        amount = amount_of(words)
        if amount is None:
            await send.reply_personal(bot, message, "🔢 Нужна сумма числом, например 500")
            return True
        state["amount"] = amount
    forget(game, chat_id, author)
    if state["message"]:
        await send.delete(bot, chat_id, state["message"])
    await go(bot, game, live, chat_id, author, state["do"], state, message=message)
    return True


@router.callback_query(F.data.startswith("pp:"), F.message)
async def panel_button(callback: CallbackQuery, bot: Bot, game: Game, live: Live) -> None:
    """«👥 Люди» in the panel: the press lets the bot ask personally even where it isn't an admin."""
    do = callback.data.split(":", 1)[1]
    if do not in ACTIONS:
        await send.answer_quietly(callback)
        return
    if not await begin(bot, game, live, callback.message.chat.id, callback.from_user.id, do, callback=callback):
        await send.answer_quietly(callback)


@router.message(F.ephemeral_message_id & F.text)
async def ephemeral_answer(message: Message, bot: Bot, game: Game, live: Live) -> None:
    """Answers to a personal question come as personal messages and may lack the reply link."""
    await answer(message, bot, game, live)
