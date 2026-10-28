"""Gifts, robberies, weddings and divorces."""

from bot.core import shop
from bot.texts import social as social_texts
from bot.texts.pick import pick
from bot.tg.views.layout import MEDALS, card, duration, money, note, num, who


def ask(emoji: str, question: str, about: str | None, hint: str, remark: str | None = None) -> str:
    """The bot's question when a command leaves out the person or the amount."""
    head = f"{emoji} <b>{question}</b>" + (f" · {who(about)}" if about else "")
    return card(head, hint, note(remark) if remark else "")


REDISTRIBUTION_SHOWN = 10


def redistribution(victim: str, total: int, shares: list[tuple[str, int]], chat_id: int) -> str:
    """The great redistribution: whose wallet went, and who caught how much of it."""
    from bot.texts.events import REDISTRIBUTION  # local: people's views don't speak the events' voice elsewhere

    caught = []
    for index, (label, amount) in enumerate(shares[:REDISTRIBUTION_SHOWN]):
        place = MEDALS[index] if index < len(MEDALS) else f"{index + 1}."
        caught.append(f"{place} {who(label)} · +<b>{num(amount)}</b>")  # coins: named in the line above
    rest = shares[REDISTRIBUTION_SHOWN:]
    if rest:
        caught.append(f"▫️ Ещё {len(rest)} · +<b>{num(sum(amount for _, amount in rest))}</b>")
    return card(
        "💸 <b>Великий передел</b>",
        pick(REDISTRIBUTION, chat_id),
        f"😱 Кошелёк <b>{who(victim)}</b> · {money(total)}",
        caught,
        note("Каждый день в 18:00 у одного игрока забирают все монеты и раздают тем, кто играл последние "
             "две недели, в случайных долях. Завтра — кто-то другой"),
    )


def gift(giver: str, receiver: str, amount: int, chat_id: int) -> str:
    return card(
        "🎁 <b>Подарок</b>",
        pick(social_texts.GIFT, chat_id),
        f"🎁 <b>{who(giver)}</b> → <b>{who(receiver)}</b> · {money(amount)}",
    )


def robbery(robber: str, victim: str, result, chat_id: int) -> str:
    """Money moves along the arrow: from the victim on success, to the victim on failure."""
    if result.status == "success":
        return card(
            "🕵️ <b>Ограбление</b>",
            pick(social_texts.ROB_SUCCESS, chat_id),
            f"💰 <b>{who(victim)}</b> → <b>{who(robber)}</b> · {money(result.amount)}",
        )
    flavour = (
        pick(social_texts.ROB_GUARDED, chat_id).format(victim=victim)  # the victim is an admin: a trap
        if result.guarded else pick(social_texts.ROB_FAIL, chat_id)
    )
    return card(
        "🚔 <b>Ограбление сорвалось</b>",
        flavour,
        [
            f"💸 <b>{who(robber)}</b> → <b>{who(victim)}</b> · {money(result.amount)}",
            f"⛓ Обезьянник · <b>{duration(result.wait)}</b>",
        ],
    )


def proposal(suitor: str, beloved: str, price: int, chat_id: int) -> str:
    cost = f"Свадьба стоит {num(price)} монет с каждого" if price else "Сегодня свадьба бесплатно"
    return card(
        "💍 <b>Предложение</b>",
        pick(social_texts.PROPOSAL, chat_id),
        f"💍 <b>{who(suitor)}</b> → <b>{who(beloved)}</b>",
        note(f"{cost}. Ответить может только {who(beloved)}, предложение живёт {shop.PROPOSAL_SECONDS // 60} минут"),
    )


def wedding(first: str, second: str, chat_id: int) -> str:
    return card(
        "💒 <b>Свадьба</b>",
        pick(social_texts.WEDDING, chat_id),
        f"💍 <b>{who(first)}</b> + <b>{who(second)}</b>",
        note("Семейный бонус: +20% к /daily, если оба забрали его в один день. При разводе монеты делятся пополам"),
    )


def rejected(suitor: str, beloved: str, chat_id: int) -> str:
    return card(
        "💔 <b>Отказ</b>",
        pick(social_texts.REJECTED, chat_id),
        f"💔 <b>{who(beloved)}</b> → <b>{who(suitor)}</b>: «нет»",
    )


def divorce(first: str, second: str, result, chat_id: int) -> str:
    return card(
        "💔 <b>Развод</b>",
        pick(social_texts.DIVORCE, chat_id),
        [f"🪙 {who(first)} · {money(result.mine)}", f"🪙 {who(second)} · {money(result.theirs)}"],
    )
