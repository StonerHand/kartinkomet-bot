"""Pikchecoins and player levels."""

from dataclasses import dataclass

# Coins per action.
VOTE = 1
GUESS = 3  # voted for the winner of a battle
COURT_VOTE = 1
LIKE_RECEIVED = 2  # someone liked your pic for the first time
UPLOAD = 1
CAPTION_WIN = 15
GOLD = 25


@dataclass(frozen=True)
class Level:
    index: int  # 0-based
    name: str
    threshold: int  # lifetime coins needed


LEVELS = (
    Level(0, "🥚 Залётный", 0),
    Level(1, "🐣 Зритель", 20),
    Level(2, "🙂 Свой", 60),
    Level(3, "😎 Завсегдатай", 150),
    Level(4, "🧠 Мемолог", 300),
    Level(5, "🔥 Задрот", 600),
    Level(6, "💀 Ветеран арены", 1000),
    Level(7, "👑 Аристократ склада", 1600),
    Level(8, "🗿 Живая легенда", 2500),
    Level(9, "🌌 Бог склада", 4000),
)


def level_for(earned: int) -> Level:
    current = LEVELS[0]
    for level in LEVELS:
        if earned >= level.threshold:
            current = level
    return current


def next_level(earned: int) -> Level | None:
    for level in LEVELS:
        if earned < level.threshold:
            return level
    return None


def progress(earned: int, cells: int = 10) -> str:
    """Progress bar to the next level, e.g. ▰▰▰▱▱▱▱▱▱▱ — inside a <code> block it renders evenly."""
    current = level_for(earned)
    upcoming = next_level(earned)
    if upcoming is None:
        return "▰" * cells
    span = upcoming.threshold - current.threshold
    filled = int(cells * (earned - current.threshold) / span) if span else cells
    return "▰" * filled + "▱" * (cells - filled)


# Weekly crowns: kind → (badge, title). Handed out with the Sunday digest, worn for a week.
CROWNS = {
    "uploader": ("👑", "Король загрузок"),
    "executioner": ("🪓", "Палач недели"),
    "advocate": ("😇", "Адвокат недели"),
    "oracle": ("🎯", "Оракул недели"),
    "rich": ("💰", "Богач недели"),
    "lucky": ("🍀", "Везунчик казино"),
}
CROWN_SECONDS = 7 * 24 * 3600


def people_voice(right: int, wrong: int) -> tuple[int, str] | None:
    """Share of votes that matched the winner, with a verdict. None until 5 decided votes."""
    total = right + wrong
    if total < 5:
        return None
    share = round(100 * right / total)
    if share >= 90:
        verdict = "🐑 голос стада"
    elif share >= 60:
        verdict = "🗳 голос народа"
    elif share > 30:
        verdict = "🤷 сам по себе"
    else:
        verdict = "🦄 уникальный вкус"
    return share, verdict


# ── prices that follow the chat's wealth ───────────────────────────────
# Shop prices are set for a chat where a typical player holds ~2 000 coins. When the median
# balance of active players is higher, prices grow with it, so a rich chat still has something
# to save for. Rewards stay fixed: raising them too would only feed the inflation.
BASE_WEALTH = 2000
WEALTH_ACTIVE_DAYS = 14


def wealth_factor(median_balance: int) -> float:
    return max(1.0, median_balance / BASE_WEALTH)


def scaled(price: int, factor: float) -> int:
    """Price × factor rounded to two significant digits: 300 × 7.31 → 2 200."""
    if factor <= 1:
        return price
    value = price * factor
    step = 10 ** max(0, len(str(int(value))) - 2)
    return int(round(value / step) * step)
