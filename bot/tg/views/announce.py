"""Announcements: achievements, level-ups, quests and chests of one event in one message."""

from html import escape

from bot.core import achievements as rules
from bot.services.types import Granted
from bot.texts.achievements import ACHIEVEMENTS, LEVEL_UP, UNLOCKED
from bot.texts.pick import pick
from bot.texts.progress import quest_name
from bot.tg.views.layout import bare, card, num, who


NOTE_CHESTS = {"wood": "деревянный сундук", "rare": "редкий сундук", "legend": "легендарный сундук"}


def note_line(label: str, note) -> str:
    """Two lines: what happened and to whom, then the details in italics."""
    name = f"<b>{who(label)}</b>"
    if note.kind == "quest":
        return f"📜 Квест выполнен — {name}\n<i>{escape(quest_name(note.code, note.target))} · +{num(note.amount)} монет</i>"
    if note.kind == "quests_all":
        return f"📋 Все квесты дня — {name}\n<i>+{num(note.amount)} монет и {NOTE_CHESTS['wood']}</i>"
    if note.kind == "challenge":
        return (
            f"🏆 Челлендж недели — {name}\n"
            f"<i>{escape(quest_name(note.code, note.target))} · +{num(note.amount)} монет и {NOTE_CHESTS['rare']}</i>"
        )
    if note.kind == "challenges_all":
        return f"💎 Все челленджи недели — {name}\n<i>{NOTE_CHESTS['legend']}</i>"
    return f"🎁 Находка — {name}\n<i>{NOTE_CHESTS.get(note.code, 'сундук')}</i>"


RARITY_WORDS = {"common": "", "rare": "Редкая. ", "legendary": "Легендарная. "}
SHOWN_PEOPLE = 2  # more names than this become "и ещё N": a long list would wrap mid-item


def people_line(labels: list[str]) -> str:
    shown = ", ".join(who(label) for label in labels[:SHOWN_PEOPLE])
    rest = len(labels) - SHOWN_PEOPLE
    return f"{shown} и ещё {rest}" if rest > 0 else shown


def announcement(items: list[tuple[str, Granted]]) -> str:
    """All achievements, level-ups, quests and chests of one event in a single message; the same
    achievement for several people becomes one block."""
    notes = [note_line(label, note) for label, granted in items for note in granted.notes]
    if not any(granted.codes or granted.level_up for _, granted in items):
        return card(*notes) if len(notes) == 1 else "\n\n".join(notes)
    # Every block: a short emoji line, then details — long names and lists of people never wrap
    # into the next item.
    blocks = [
        f"⬆️ <b>Новый уровень</b> · {who(label)}\n<i>«{escape(bare(granted.level_up))}». {escape(pick(LEVEL_UP))}</i>"
        for label, granted in items
        if granted.level_up
    ]
    by_code: dict[str, list[str]] = {}
    for label, granted in items:
        for code in granted.codes:
            by_code.setdefault(code, []).append(label)
    for code in sorted(by_code, key=lambda code: (rules.RARITY_ORDER[rules.rarity(code)], code)):
        name, description = ACHIEVEMENTS.get(code, (code, ""))
        rarity = RARITY_WORDS[rules.rarity(code)]
        emoji, _, title = name.partition(" ")
        blocks.append(
            f"{emoji} <b>{escape(title)}</b>\n{people_line(by_code[code])}\n<i>{rarity}{escape(description)}</i>"
        )
    head = f"🏅 <b>{escape(bare(pick(UNLOCKED)))}</b>" if by_code else "🎉 <b>Есть повышение</b>"
    return card(head, None, *blocks, *notes)


def has_legendary(granted: list[Granted]) -> bool:
    return any(rules.rarity(code) == rules.LEGENDARY for item in granted for code in item.codes)
