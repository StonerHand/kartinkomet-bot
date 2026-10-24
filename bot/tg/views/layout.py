"""Shared layout: card(), numbers, names, plurals. Rules of every message live here."""

import re
from html import escape

PHONE_LINE = 32  # characters that surely fit one line on a phone (measured: Telegram iOS, 17 pt, italic and emoji included)
BAR_CELLS = 5
SLOT_COLORS = ("🟥", "🟦", "🟩", "🟨")
MEDALS = ("🥇", "🥈", "🥉")
# Fighters inside text are plain letters; the emoji letters 🅰️🅱️ live on buttons and collages.
DUEL_SLOTS = ("A", "B")
TOURNAMENT_SLOTS = ("1", "2", "3", "4")


def plain(line: str) -> str:
    """What the reader sees: no tags, no entities."""
    return re.sub(r"<[^>]+>", "", line).replace("&lt;", "<").replace("&gt;", ">").replace("&amp;", "&")


def width(line: str) -> float:
    """A line's length in phone characters: capitals are a quarter wider than small letters."""
    text = plain(line)
    return len(text) + sum(char.isupper() for char in text) / 4


def fits(line: str) -> bool:
    """True if the line doesn't wrap on a phone."""
    return width(line) <= PHONE_LINE


def header(head: str) -> str:
    """'🎁 <b>TITLE</b> · meta' too wide for a phone keeps the title on its line and puts the meta
    under it: a wrapped header leaves half a word or a lone timer hanging on the second line."""
    title, dot, meta = head.partition("</b> · ")
    return f"{title}</b>\n{meta}" if dot and not fits(head) else head


def timer(seconds: int) -> str:
    """'0:45', '9:59', '7:59:59' (hours appear only when needed: raids last all evening)."""
    seconds = max(0, seconds)
    if seconds >= 3600:
        return f"{seconds // 3600}:{seconds % 3600 // 60:02d}:{seconds % 60:02d}"
    return f"{seconds // 60}:{seconds % 60:02d}"


def bar(count: int, leader: int, color: str) -> str:
    if count <= 0 or leader <= 0:
        return ""
    return "  " + color * max(1, round(BAR_CELLS * count / leader))


def num(value: int) -> str:
    """10000322 → '10 000 322' (non-breaking spaces, so a number never wraps)."""
    return f"{value:,}".replace(",", "\u00a0")


def money(amount: int) -> str:
    """Coins inside a line are a word, not 🪙: '<b>1 111</b> монет'. One emoji per line, at its start."""
    return f"<b>{num(amount)}</b> {plural(abs(amount), 'монета', 'монеты', 'монет')}"


def bare(name: str) -> str:
    """'🐣 Птенец' → 'Птенец': names of levels, stages, titles and achievements lose their own
    emoji when they sit inside a line."""
    head, _, tail = name.partition(" ")
    return tail if tail and not any(char.isalnum() for char in head) else name


def slot_names(kind: str) -> tuple[str, ...]:
    return DUEL_SLOTS if kind == "duel" else TOURNAMENT_SLOTS


def rating(value: float) -> str:
    return f"{value:.0f}"


def delta(before: float, after: float) -> str:
    diff = round(after - before)
    return f"+{diff}" if diff >= 0 else f"−{abs(diff)}"


def who(label: str) -> str:
    return escape(label)


def card(head: str, flavour: str | None = None, *blocks) -> str:
    """The one layout of every message:

        HEADER · meta       (the meta goes to a line of its own if the two don't fit)
        flavour line (italic)

        block

        block…

    A block is a string or a list of lines; empty lines inside a block and empty blocks are
    dropped, so callers never glue or double the spacing by hand.

    Inside a block, lines that wrap on a phone would merge with their neighbours, so a long line
    is either a block of its own, the description under its item's title, or the italic caption
    that ends a block (like the flavour under the header)."""
    top = header(head) + (f"\n<i>{escape(bare(flavour))}</i>" if flavour else "")  # the header owns the emoji
    parts = [top]
    for block in blocks:
        if isinstance(block, (list, tuple)):
            block = "\n".join(line for line in block if line)
        if block:
            parts.append(block.strip("\n"))
    return "\n\n".join(parts)


def cited(text: str) -> str:
    """Words of a person (last word in court): a real blockquote, then an empty line."""
    return f"<blockquote>{escape(text)}</blockquote>\n"


def plural(value: int, one: str, few: str, many: str) -> str:
    tail = value % 100
    if 11 <= tail <= 14:
        return many
    return {1: one, 2: few, 3: few, 4: few}.get(value % 10, many)


def ago(seconds: int) -> str:
    if seconds < 3600:
        return "только что"
    hours = seconds // 3600
    if hours < 24:
        return f"{hours} ч назад"
    days = hours // 24
    return f"{days} {plural(days, 'день', 'дня', 'дней')} назад"


def duration(seconds: int) -> str:
    """Human wait: '2 ч 5 мин', '14 мин', '40 сек'."""
    seconds = max(0, seconds)
    if seconds >= 3600:
        hours, minutes = divmod(seconds // 60, 60)
        return f"{hours} ч {minutes} мин" if minutes else f"{hours} ч"
    if seconds >= 60:
        return f"{seconds // 60} мин"
    return f"{seconds} сек"


def hp_bar(hp: int, max_hp: int, cells: int = 10) -> str:
    filled = max(0, min(cells, round(cells * hp / max_hp))) if max_hp else 0
    if hp > 0:
        filled = max(1, filled)
    return "▰" * filled + "▱" * (cells - filled)
