"""Gifts, robberies, weddings and divorces."""

from bot.core import shop
from bot.texts import social as social_texts
from bot.texts.pick import pick
from bot.tg.views.layout import card, duration, money, num, who


def ask(emoji: str, question: str, about: str | None, hint: str, note: str | None = None) -> str:
    """The bot's question when a command leaves out the person or the amount."""
    head = f"{emoji} <b>{question.upper()}</b>" + (f" · {who(about)}" if about else "")
    return card(head, hint, f"<i>{note}</i>" if note else "")


def gift(giver: str, receiver: str, amount: int, chat_id: int) -> str:
    return card(
        "🎁 <b>ПОДАРОК</b>",
        pick(social_texts.GIFT, chat_id),
        f"<b>{who(giver)}</b> → <b>{who(receiver)}</b>: {money(amount)}",
    )


def robbery(robber: str, victim: str, result, chat_id: int) -> str:
    if result.status == "success":
        return card(
            "🕵️ <b>ОГРАБЛЕНИЕ</b>",
            pick(social_texts.ROB_SUCCESS, chat_id),
            f"Добыча <b>{who(robber)}</b>: {money(result.amount)} из кармана <b>{who(victim)}</b>",
        )
    return card(
        "🚔 <b>ОГРАБЛЕНИЕ СОРВАЛОСЬ</b>",
        pick(social_texts.ROB_FAIL, chat_id),
        f"<b>{who(robber)}</b> платит <b>{who(victim)}</b> штраф {money(result.amount)} и сидит {duration(result.wait)}",
    )


def proposal(suitor: str, beloved: str, price: int, chat_id: int) -> str:
    cost = f"Свадьба стоит {num(price)} монет с каждого" if price else "Сегодня свадьба бесплатно"
    return card(
        "💍 <b>ПРЕДЛОЖЕНИЕ</b>",
        pick(social_texts.PROPOSAL, chat_id),
        f"<b>{who(suitor)}</b> делает предложение <b>{who(beloved)}</b>",
        f"<i>{cost}. Ответить может только {who(beloved)}, предложение живёт {shop.PROPOSAL_SECONDS // 60} минут</i>",
    )


def wedding(first: str, second: str, chat_id: int) -> str:
    return card(
        "💒 <b>СВАДЬБА</b>",
        pick(social_texts.WEDDING, chat_id),
        f"💍 <b>{who(first)}</b> + <b>{who(second)}</b>",
        "<i>Семейный бонус: +20% к /daily, если оба забрали его в один день. "
        "При разводе всё имущество делится пополам</i>",
    )


def rejected(suitor: str, beloved: str, chat_id: int) -> str:
    return card(
        "💔 <b>ОТКАЗ</b>",
        pick(social_texts.REJECTED, chat_id),
        f"<b>{who(beloved)}</b> не хочет за <b>{who(suitor)}</b>",
    )


def divorce(first: str, second: str, result, chat_id: int) -> str:
    return card(
        "💔 <b>РАЗВОД</b>",
        pick(social_texts.DIVORCE, chat_id),
        [f"{who(first)}: {money(result.mine)}", f"{who(second)}: {money(result.theirs)}"],
    )
