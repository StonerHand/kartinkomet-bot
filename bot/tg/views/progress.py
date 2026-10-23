"""Daily bonus, quests, chests and the event of the day."""

from html import escape

from bot.core import progress
from bot.services.progress import Daily, TaskState
from bot.texts import days as day_texts
from bot.texts import progress as progress_texts
from bot.texts.pick import pick
from bot.tg.views.layout import bare, card, money, num, plural, who


def task_line(task: TaskState) -> str:
    name = progress_texts.quest_name(task.kind, task.target)
    if task.finished:
        return f"✅ <s>{escape(name)}</s>\n<i>готово · +{coins(task.reward)}</i>"
    return f"▫️ {escape(name)}\n<i>{min(task.done, task.target)} из {task.target} · награда {coins(task.reward)}</i>"


def coins(amount: int) -> str:
    return f"{num(amount)} {plural(amount, 'монета', 'монеты', 'монет')}"


def quests_screen(
    label: str,
    daily: list[TaskState],
    weekly: list[TaskState],
    chests: dict[str, int],
    daily_ready: bool,
    daily_streak: int,
    chat_id: int,
) -> str:
    bonus = "Можно забрать — кнопка ниже" if daily_ready else (
        f"Забран. Серия: <b>{daily_streak}</b> {plural(daily_streak, 'день', 'дня', 'дней')}"
    )
    owned = [(tier, count) for tier, count in chests.items() if count]
    backpack = (
        "🎁 <b>Сундуки:</b> " + " · ".join(f"{progress_texts.CHESTS[tier][1].split()[0].lower()} — {count}" for tier, count in owned)
        if owned
        else "🎁 <i>Сундуков пока нет: они за квесты, челленджи, серию бонусов и боссов</i>"
    )
    return card(
        f"📜 <b>КВЕСТЫ · {who(label).upper()}</b>",
        pick(progress_texts.QUEST_HEADERS, chat_id),
        ["🎁 <b>Бонус дня</b>", bonus],
        ["📋 <b>Квесты дня</b>", "<i>За все три — деревянный сундук</i>"],
        *[task_line(task) for task in daily],
        ["🏆 <b>Челленджи недели</b>", "<i>За каждый — редкий сундук</i>"],
        *[task_line(task) for task in weekly],
        backpack,
    )


def daily_result(label: str, daily: Daily, chat_id: int) -> str:
    day = daily.streak
    left = progress.DAILY_CHEST_EVERY - day % progress.DAILY_CHEST_EVERY
    return card(
        f"🎁 <b>БОНУС ДНЯ</b> · {who(label)}",
        pick(progress_texts.DAILY, chat_id),
        [
            f"➕ {money(daily.reward)} · серия <b>{day}</b> {plural(day, 'день', 'дня', 'дней')}",
            f"💍 Семейная надбавка: +{daily.family_bonus} тебе и супругу" if daily.family_bonus else "",
            f"🎁 За {progress.DAILY_CHEST_EVERY} дней подряд — <b>редкий сундук</b>" if daily.chest else "",
        ],
        None if daily.chest else f"<i>До редкого сундука: {left} {plural(left, 'день', 'дня', 'дней')}</i>",
    )


def chest_opening(label: str, tier: str, chat_id: int) -> str:
    emoji, name = progress_texts.CHESTS[tier]
    return card(f"{emoji} <b>{name.upper()}</b> · {who(label)}", pick(progress_texts.OPENING, chat_id))


def chest_opened(label: str, opened, chat_id: int) -> str:
    emoji, name = progress_texts.CHESTS[opened.tier]
    loot = opened.loot
    facts = [
        f"➕ {money(loot.coins)}" if loot.coins else "",
        f"⚡ +{progress.CHEST_BOOST_RATING} рейтинга одной из твоих пикч" if loot.kind == "boost" and opened.pic else "",
        f"🛡 Щит на {progress.CHEST_SHIELD_SECONDS // 86400} дня самой слабой твоей пикче"
        if loot.kind == "shield" and opened.pic else "",
        "🎁 +1 деревянный сундук" if loot.kind == "chest" else "",
        f"🖼 Лучшая пикча теперь в {progress.FRAMES[loot.prize][0]} рамке" if loot.kind == "frame" else "",
        f"🏷 Титул «{escape(loot.prize)}»" if loot.kind == "title" else "",
    ]
    return card(f"{emoji} <b>{name.upper()}</b> · {who(label)}", pick(progress_texts.LOOT[loot.kind], chat_id), facts)


def day_event_line(code: str | None) -> str | None:
    if not code:
        return None
    name, rule = day_texts.NAMES[code], day_texts.RULES[code]
    return f"📰 Сегодня {escape(bare(name)).lower()}: {escape(rule[0].lower() + rule[1:])}"


def day_event(code: str, chat_id: int, tax: tuple[int, int, int] | None = None) -> str:
    name, rule = day_texts.NAMES[code], day_texts.RULES[code]
    report = []
    if code == "tax" and tax:
        total, share, people = tax
        report = [
            f"🧾 Собрано с богачей: {money(total)}",
            f"🤲 По {money(share)} получили {people} {plural(people, 'бедняк', 'бедняка', 'бедняков')}",
        ]
    return card(
        f"📰 <b>СОБЫТИЕ ДНЯ: {escape(bare(name)).upper()}</b>",
        pick(day_texts.FLAVOUR[code], chat_id),
        ["⚡ <b>Что меняется</b>", f"{escape(rule)}. <i>До полуночи</i>"],
        report,
    )
