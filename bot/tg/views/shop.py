"""Shop: the screen, the 🛒 menu under a pic, purchase notices, wanted posters."""

from html import escape

from bot.core import shop
from bot.db.repo import Pic
from bot.texts import shop as shop_texts
from bot.texts.pick import pick
from bot.tg.views.layout import card, duration, money, rating, who
from bot.tg.views.progress import day_event_line


def shop_screen(label: str, balance: int, prices: dict[str, int], chat_id: int, event: str | None) -> str:
    items = [
        f"{emoji} <b>{name}</b> — {money(prices[code])}\n<i>{escape(about)}</i>"
        for code, (emoji, name, about) in shop_texts.ITEMS.items()
    ]
    bounty = (
        f"🎯 <b>Награда за голову</b> — от {shop.BOUNTY_AMOUNTS[0]} монет\n"
        "<i>получат те, кто казнит пикчу</i>"
    )
    return card(
        "🛒 <b>ЛАВКА</b>",
        pick(shop_texts.HEADERS, chat_id),
        [
            f"💼 <b>{who(label)}</b>: {money(balance)}",
            day_event_line(event) if event in ("inflation", "black_friday", "dead_day") else "",
        ],
        *items,
        bounty,
        [
            "<b>Как купить</b>",
            "Под каждой пикчей есть кнопка с тележкой — там всё, что можно сделать именно с ней. "
            "Воскрешение — на экране «Кладбище», титул — кнопкой ниже.",
        ],
    )


def pic_menu(pic: Pic, uploader: str | None, balance: int, bounty: int, cursed: int, now: int) -> str:
    stage = shop.stage(pic.wins)
    facts = [stage.name, f"рейтинг {rating(pic.rating)}"]
    if uploader:
        facts.append(f"от {uploader}")  # card() escapes the flavour line itself
    status = [
        f"🛡 Под щитом ещё {duration(pic.immune_until - now)}" if pic.immune_until and pic.immune_until > now else "",
        f"🧿 Проклята ещё {duration(cursed - now)}" if cursed else "",
        f"🎯 Награда за голову: {money(bounty)}" if bounty else "",
    ]
    return card(
        "🛒 <b>ЧТО СДЕЛАТЬ С ПИКЧЕЙ</b>",
        " · ".join(facts),
        status,
        f"💼 Твой баланс: {money(balance)}",
    )


def bought(item: str, chat_id: int) -> str:
    return pick(shop_texts.BOUGHT[item], chat_id)


PURCHASE_FACTS = {
    "shield": "пикчу нельзя судить 3 дня",
    "boost": f"+{shop.BOOST_RATING} рейтинга",
    "uncurse": f"порча снята, +{shop.CURSE_RATING} рейтинга вернулись",
}


def purchase_notice(item: str, buyer: str, pic: Pic, chat_id: int) -> str:
    """Public line under the pic after a purchase: what happened, who paid, a dealer joke."""
    emoji, name, _ = shop_texts.ITEMS[item]
    phrase = bought(item, chat_id).split(" ", 1)[1]  # phrases start with the item emoji
    return card(
        f"{emoji} <b>{name.upper()}</b> · {PURCHASE_FACTS[item]}",
        phrase,
        f"За счёт <b>{who(buyer)}</b> · рейтинг теперь {rating(pic.rating)}",
    )


def wanted_poster(pic: Pic, total: int, sponsor: str, chat_id: int) -> str:
    return card(
        f"🎯 <b>РАЗЫСКИВАЕТСЯ</b> · награда {money(total)}",
        pick(shop_texts.BOUNTY, chat_id),
        f"Заказчик: <b>{who(sponsor)}</b>",
        "<i>Деньги получат те, кто её казнит — в суде или на арене</i>",
    )
