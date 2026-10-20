"""Boss card and its outcome."""

from html import escape

from bot.core import boss as boss_rules
from bot.texts import boss as boss_texts
from bot.texts.pick import pick
from bot.tg.views.layout import MEDALS, card, hp_bar, money, num, timer, who


def boss_card(boss: dict, labels: dict[int, str], remaining: int, chat_id: int) -> str:
    health = [
        f"❤️ <b>{boss['hp']}</b> / {boss['max_hp']}",
        f"<code>{hp_bar(boss['hp'], boss['max_hp'])}</code>",
        f"💰 Добыча: {money(boss['loot'])}",
    ]
    damage = []
    if boss["damage"]:
        damage.append("⚔️ <b>Урон</b>")
        for index, (user, dealt) in enumerate(list(boss["damage"].items())[:5]):
            place = MEDALS[index] if index < 3 else f"{index + 1}."
            damage.append(f"{place} {who(labels.get(user, '?'))} — <b>{dealt}</b>")
    return card(
        f"👹 <b>БОСС: {escape(boss['title']).upper()}</b> · <b>{timer(remaining)}</b>",
        pick(boss_texts.STATUS if boss["hits"] else boss_texts.ARRIVE, chat_id),
        health,
        damage,
        [
            f"🗡 <i>Удар — бесплатно, раз в {boss_rules.HIT_COOLDOWN_SECONDS:g} сек</i>",
            f"🔥 <i>Супер-удар — {boss_rules.SUPER_PRICE} монет, бьёт сильнее</i>",
            "🤝 <i>Добычу делят по нанесённому урону</i>",
        ],
    )


def boss_result(report, labels: dict[int, str], chat_id: int) -> str:
    boss = report.boss
    title = escape(boss["title"]).upper()
    if not report.won:
        return card(
            f"👹 <b>БОСС СБЕЖАЛ · {title}</b>",
            pick(boss_texts.ESCAPE, chat_id),
            [
                f"❤️ Осталось <b>{boss['hp']}</b> из {boss['max_hp']}",
                f"⭐ Пикча-босс: +{boss_rules.ESCAPE_RATING_BONUS} рейтинга",
            ],
        )
    loot = [f"💰 <b>Добыча</b> · {money(boss['loot'])} по урону"]
    for index, (user, amount) in enumerate(sorted(report.payouts.items(), key=lambda item: -item[1])[:8]):
        place = MEDALS[index] if index < 3 else f"{index + 1}."
        dealt = boss["damage"].get(user, 0)
        loot.append(f"{place} {who(labels.get(user, '?'))} — <b>+{num(amount)}</b> · <i>урон {dealt}</i>")
    honours = [
        f"💀 Добил: <b>{who(labels.get(report.last_hit, '?'))}</b> (+{boss_rules.LAST_HIT_BONUS})"
        if report.last_hit is not None else "",
        f"🎁 Редкий сундук — <b>{who(labels.get(report.top, '?'))}</b>" if report.top is not None else "",
    ]
    return card(f"🏆 <b>БОСС ПОВЕРЖЕН · {title}</b>", pick(boss_texts.WIN, chat_id), loot, honours)
