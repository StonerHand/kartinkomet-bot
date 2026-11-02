"""Shop: the 🛒 menu under every pic, resurrection from the graveyard, titles, bounties."""

from html import escape
from secrets import token_hex
from time import monotonic

from aiogram import Bot, F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message

from bot.core import shop
from bot.game import Game
from bot.texts import shop as texts
from bot.tg.handlers.court import open_court
from bot.tg.runtime import send
from bot.tg.runtime.timers import Live
from bot.tg.ui import keyboards, views

router = Router(name="shop")
ITEM_CODES = {"s": "shield", "b": "boost", "c": "court", "u": "uncurse"}
BOUNTY_CODES = {"h1": 0, "h5": 1}  # index into game.bounty_amounts()
CONFIRM_SECONDS = 10.0
_confirm: dict[tuple[int, str], float] = {}


def menu_token(game: Game, pic_id: str, user_id: int, chat_id: int, message_id: int = 0) -> str:
    """Buttons of a pic menu carry a short token; the context lives in meta. Keeps callback
    data well under 64 bytes and works even if an ephemeral callback arrives without a message."""
    token = token_hex(5)
    game.repo.set_meta(f"pm:{token}", f"{pic_id}:{user_id}:{chat_id}:{message_id}")
    return token


def menu_context(game: Game, token: str) -> tuple[str, int, int, int | None] | None:
    """(pic, buyer, chat, message with the pic or None)."""
    raw = game.repo.meta_str(f"pm:{token}")
    if not raw:
        return None
    pic_id, user_id, chat_id, *rest = raw.split(":")
    message_id = int(rest[0]) if rest and rest[0] != "0" else None
    return pic_id, int(user_id), int(chat_id), message_id


def confirmed(user_id: int, key: str) -> bool:
    """Expensive one-tap purchases need a second tap within CONFIRM_SECONDS."""
    now = monotonic()
    started = _confirm.get((user_id, key))
    if started is not None and now - started <= CONFIRM_SECONDS:
        del _confirm[(user_id, key)]
        return True
    _confirm[(user_id, key)] = now
    return False


@router.message(Command("shop"))
async def shop_command(message: Message, bot: Bot, game: Game, admins: frozenset[int]) -> None:
    from bot.tg.handlers.panel import open_screen  # local: panel imports this module's screens

    await open_screen(message, bot, game, admins, "shop")  # it shows the asker's coins


@router.callback_query(F.data.startswith("pm:"), F.message)
async def pic_menu(callback: CallbackQuery, bot: Bot, game: Game) -> None:
    pic = game.repo.get_pic(callback.data.split(":", 1)[1])
    if pic is None or pic.status != "alive":
        await callback.answer("Её уже нет в живых. Воскрешение — на кладбище", show_alert=True)
        return
    user_id = callback.from_user.id
    cursed = game.cursed_until(pic.id)
    text = views.pic_menu(
        pic,
        game.repo.user_label(pic.added_by) if pic.added_by else None,
        game.repo.player(user_id)[0],
        game.repo.bounty_on(pic.id),
        cursed,
        game.now(),
    )
    prices = {item: game.price(item) for item in ("shield", "boost", "court", "uncurse")}
    chat_id = callback.message.chat.id
    token = menu_token(game, pic.id, user_id, chat_id, callback.message.message_id)
    markup = keyboards.pic_menu(token, bool(cursed), prices, game.bounty_amounts())
    if callback.message.chat.type != "private" and await send.ephemeral(
        bot, chat_id, user_id, text, callback.id, markup
    ) is not None:
        await send.answer_quietly(callback)
        return
    await callback.answer()
    await send.send_text(bot, chat_id, text, markup, reply_to=callback.message.message_id)


@router.callback_query(F.data.startswith("sh:"))
async def buy(callback: CallbackQuery, bot: Bot, game: Game, live: Live) -> None:
    _, code, token = callback.data.split(":", 2)
    user_id = callback.from_user.id
    context = menu_context(game, token)
    if context is None:
        await callback.answer("Меню устарело. Нажми 🛒 под пикчей ещё раз", show_alert=True)
        return
    pic_id, owner, chat_id, pic_message = context
    if owner != user_id:
        await callback.answer("Это меню открыл кто-то другой. Жми 🛒 под пикчей сам", show_alert=True)
        return
    label = game.repo.user_label(user_id)
    if code in BOUNTY_CODES:
        amount = game.bounty_amounts()[BOUNTY_CODES[code]]
        status, total = game.put_bounty(user_id, pic_id, amount)
        if status != "ok":
            await callback.answer(texts.REFUSED.get(status, "Не вышло"), show_alert=True)
            return
        await callback.answer(f"🎯 Награда поднята до {total} 🪙")
        pic = game.repo.get_pic(pic_id)
        if pic is not None:
            await send.send_photo(
                bot,
                chat_id,
                pic.file_id,
                views.wanted_poster(total, label, chat_id),
                keyboards.pic_actions(pic.id, pic.likes, pic.dislikes),
            )
            await live.announce(chat_id, game.flush([pic.added_by, user_id]))
        return
    item = ITEM_CODES.get(code)
    if item is None:
        await callback.answer()
        return
    status, pic = game.buy(user_id, item, pic_id)
    if status != "ok":
        await callback.answer(texts.REFUSED.get(status, "Не вышло"), show_alert=True)
        return
    price = game.price(item)
    await callback.answer(f"{views.bought(item, user_id)} · −{price} 🪙")
    if callback.message is not None and callback.message.message_id:
        await send.delete(bot, callback.message.chat.id, callback.message.message_id)
    if pic is None:
        return
    if item == "court":
        status = await open_court(bot, game, live, chat_id, pic.id, "bottom", user_id)
        if status != "started":
            game.refund(user_id, item)
            await send.send_text(bot, chat_id, f"⚖️ Суд не открылся, {price} 🪙 вернулись {views.who(label)}")
        return
    await send.send_text(bot, chat_id, views.purchase_notice(item, label, pic, chat_id), reply_to=pic_message)
    await live.announce(chat_id, game.flush([user_id]))


@router.callback_query(F.data.startswith("res:"))
async def resurrect(callback: CallbackQuery, bot: Bot, game: Game, live: Live) -> None:
    pic_id = callback.data.split(":", 1)[1]
    user_id = callback.from_user.id
    price = game.price("resurrect")
    pic = game.repo.get_pic(pic_id)
    if pic is None or pic.status == "alive":
        await callback.answer(texts.REFUSED["alive"] if pic else texts.REFUSED["gone"], show_alert=True)
        return
    if not confirmed(user_id, f"res:{pic_id}"):
        await callback.answer(f"🧟 Воскресить за {price} 🪙? Нажми ещё раз в течение 10 секунд", show_alert=True)
        return
    status, pic = game.buy(user_id, "resurrect", pic_id)
    if status != "ok" or pic is None:
        await callback.answer(texts.REFUSED.get(status, "Не вышло"), show_alert=True)
        return
    await callback.answer(f"🧟 Воскрешена · −{price} 🪙")
    if callback.message is None:
        return
    chat_id = callback.message.chat.id
    label = game.repo.user_label(user_id)
    uploader = game.repo.user_label(pic.added_by) if pic.added_by else None
    await send.send_photo(
        bot,
        chat_id,
        pic.file_id,
        views.card(
            f"🧟 <b>Воскрешение</b> · спасибо <b>{views.who(label)}</b>",
            views.bought("resurrect", chat_id).split(" ", 1)[1],
            views.pic_footer(pic, uploader),
        ),
        keyboards.pic_actions(pic.id, pic.likes, pic.dislikes),
    )
    await live.announce(chat_id, game.flush([user_id, pic.added_by]))


# ── titles ─────────────────────────────────────────────────────────────

TITLE_PROMPT_SECONDS = 600


@router.callback_query(F.data == "title", F.message)
async def title_button(callback: CallbackQuery, bot: Bot, game: Game) -> None:
    price = game.price("title")
    if game.repo.player(callback.from_user.id)[0] < price:
        await callback.answer(texts.REFUSED["broke"], show_alert=True)
        return
    await callback.answer()
    chat_id = callback.message.chat.id
    label = game.repo.user_label(callback.from_user.id)
    prompt = await send.send_text(
        bot,
        chat_id,
        views.card(
            f"🏷 <b>Свой титул</b> · {views.who(label)}",
            texts.TITLE_PROMPT.format(limit=shop.TITLE_MAX_LENGTH, price=price),
        ),
    )
    if prompt is not None:
        game.repo.set_meta(f"title_prompt:{chat_id}:{prompt.message_id}", callback.from_user.id)
        if chat_id < 0:  # an unanswered prompt doesn't stay in the chat forever
            send.fleeting(bot, chat_id, [prompt.message_id], TITLE_PROMPT_SECONDS)


async def title_reply(message: Message, bot: Bot, game: Game) -> bool:
    """A reply to a title prompt. True if it was one."""
    if message.from_user is None or message.reply_to_message is None:
        return False
    key = f"title_prompt:{message.chat.id}:{message.reply_to_message.message_id}"
    if game.repo.meta_str(key) != str(message.from_user.id):
        return False
    status = game.buy_title(message.from_user.id, message.text or "")
    if status == "broke":
        await send.reply_personal(bot, message, texts.REFUSED["broke"])
        return True
    if status == "empty":
        await send.reply_personal(bot, message, "Титул пустой. Напиши хоть что-нибудь")
        return True
    game.repo.set_meta(key, 0)
    title = game.repo.title_of(message.from_user.id) or ""
    label = game.repo.user_label(message.from_user.id)
    await send.delete(bot, message.chat.id, message.reply_to_message.message_id)  # the prompt did its job
    await send.send_text(
        bot, message.chat.id, texts.TITLE_DONE.format(name=views.who(label), title=escape(title)),
        reply_to=message.message_id,
    )
    await send.react(bot, message.chat.id, message.message_id, "🏆")
    return True
