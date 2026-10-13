"""Casino rules: Telegram's own animated dice decide, these tables pay.

Every game returns a payout multiplier for the stake. The house keeps a small edge on all of
them except "dice vs bot", which is fair: the chat should lose slowly and have fun doing it.
"""

from dataclasses import dataclass

STAKE_MIN = 10
STAKE_PRESETS = (50, 100, 250, 500)
DEFAULT_STAKE = 50
COOLDOWN_SECONDS = 3.0  # per player: dice animations take a few seconds anyway
LUCKY_DAY_BONUS = 1.5  # "lucky day" multiplies every winning payout

# Telegram's 🎰 returns 1..64: value-1 in base 4 gives three reels, 0 = BAR, 1 = grapes,
# 2 = lemon, 3 = seven. 64 is 7-7-7.
SEVEN = 3


def reels(value: int) -> tuple[int, int, int]:
    index = value - 1
    return index % 4, index // 4 % 4, index // 16 % 4


@dataclass(frozen=True)
class Roll:
    kind: str  # outcome code for texts: jackpot, triple, sevens, pair, miss, bull, near, ring, hit, strike, nine, win, draw, lose
    multiplier: float


def slots(value: int) -> Roll:
    """777 ×20, other triple ×5, two sevens ×1.5, any other pair — half back. EV ≈ 0.97."""
    first, second, third = reels(value)
    if value == 64:
        return Roll("jackpot", 20)
    if first == second == third:
        return Roll("triple", 5)
    symbols = (first, second, third)
    if symbols.count(SEVEN) == 2:
        return Roll("sevens", 1.5)
    if first == second or second == third or first == third:
        return Roll("pair", 0.5)
    return Roll("miss", 0)


def darts(value: int) -> Roll:
    """🎯 1..6: 6 bullseye ×3, 5 ×1.5, 4 stake back. EV ≈ 0.92."""
    return {6: Roll("bull", 3), 5: Roll("near", 1.5), 4: Roll("ring", 1)}.get(value, Roll("miss", 0))


def basket(value: int) -> Roll:
    """🏀 1..5: 4 and 5 go in. ×2.3, EV 0.92."""
    return Roll("hit", 2.3) if value >= 4 else Roll("miss", 0)


def football(value: int) -> Roll:
    """⚽ 1..5: 3, 4, 5 are goals. ×1.5, EV 0.9."""
    return Roll("hit", 1.5) if value >= 3 else Roll("miss", 0)


def bowling(value: int) -> Roll:
    """🎳 1..6: 6 strike ×3, 5 ×1.5, 4 stake back. EV ≈ 0.92."""
    return {6: Roll("strike", 3), 5: Roll("nine", 1.5), 4: Roll("pins", 1)}.get(value, Roll("miss", 0))


def dice_duel(player: int, house: int) -> Roll:
    """🎲 against the bot: higher wins ×2, a tie returns the stake. Fair game."""
    if player > house:
        return Roll("win", 2)
    if player == house:
        return Roll("draw", 1)
    return Roll("lose", 0)


@dataclass(frozen=True)
class CasinoGame:
    code: str
    emoji: str
    name: str
    command: str
    animation: float  # seconds until the dice stops spinning


GAMES = {
    "slots": CasinoGame("slots", "🎰", "Слоты", "spin", 2.8),
    "dice": CasinoGame("dice", "🎲", "Кости", "dice", 3.8),
    "darts": CasinoGame("darts", "🎯", "Дартс", "darts", 3.5),
    "basket": CasinoGame("basket", "🏀", "Баскет", "basket", 4.8),
    "football": CasinoGame("football", "⚽", "Футбол", "football", 4.8),
    "bowling": CasinoGame("bowling", "🎳", "Боулинг", "bowling", 4.8),
}

SINGLE_ROLL = {"slots": slots, "darts": darts, "basket": basket, "football": football, "bowling": bowling}


def payout(stake: int, roll: Roll, lucky: bool = False) -> int:
    """Coins returned to the player (stake included). Lucky day boosts only real wins."""
    multiplier = roll.multiplier
    if lucky and multiplier > 1:
        multiplier *= LUCKY_DAY_BONUS
    return int(stake * multiplier + 1e-9)  # 100 × 2.3 is 229.999… in floats


def parse_stake(raw: str, balance: int, default: int) -> int | None:
    """'/spin 200', '/spin все', '/spin all' → stake. None if it isn't a number."""
    text = raw.strip().casefold()
    if not text:
        return default
    if text in {"all", "все", "всё", "ва-банк", "вабанк", "allin", "max"}:
        return balance
    if text.endswith(("k", "к")) and text[:-1].isdigit():
        return int(text[:-1]) * 1000
    return int(text) if text.isdigit() else None


# ── arena bets: parimutuel ─────────────────────────────────────────────

BET_STEP = 50
BET_MAX = 1000  # per player per battle


def odds(pool: list[int]) -> list[float | None]:
    """Payout per coin for each slot if it wins: total pool / coins on that slot."""
    total = sum(pool)
    return [round(total / amount, 2) if amount else None for amount in pool]


def settle_bets(bets: dict[int, tuple[int, int]], winner: int | None) -> dict[int, int]:
    """Parimutuel: winners split the whole pool by their share. Returns user → coins back.

    A draw refunds everyone. Nobody on the winner — the pool burns (the house eats it).
    """
    if winner is None:
        return {user: amount for user, (_, amount) in bets.items()}
    pool = sum(amount for _, amount in bets.values())
    backing = sum(amount for slot, amount in bets.values() if slot == winner)
    if not backing:
        return {}
    return {user: pool * amount // backing for user, (slot, amount) in bets.items() if slot == winner}
