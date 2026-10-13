"""Achievement rules. Names and descriptions live in bot.texts.achievements.

Two kinds:
- metric rules: checked against UserStats after events (uploads, likes, counters…);
- event achievements: granted by the game at the moment something happens
  (EVENT_CODES), e.g. "voted to execute your own pic".
Every code has a rarity; secret ones stay hidden in profiles until earned.
"""

from collections.abc import Callable
from dataclasses import dataclass

from bot.db.repo import UserStats

COMMON, RARE, LEGENDARY = "common", "rare", "legendary"
RARITY_ORDER = {LEGENDARY: 0, RARE: 1, COMMON: 2}


@dataclass(frozen=True)
class Rule:
    code: str
    threshold: int
    metric: Callable[[UserStats], int]


def _tiers(prefix: str, metric: Callable[[UserStats], int], *thresholds: int) -> list[Rule]:
    return [Rule(f"{prefix}_{threshold}", threshold, metric) for threshold in thresholds]


def _counter(key: str) -> Callable[[UserStats], int]:
    return lambda stats: stats.counter(key)


RULES: list[Rule] = [
    *_tiers("up", lambda s: s.uploads, 1, 10, 50, 100, 250, 500, 1000),
    *_tiers("night", lambda s: s.night_uploads, 1, 25, 100),
    *_tiers("liked", lambda s: s.likes_received, 10, 50, 200),
    *_tiers("hated", lambda s: s.dislikes_received, 5, 25, 100),
    *_tiers("exec", lambda s: s.pics_executed, 1, 10, 50),
    *_tiers("killer", lambda s: s.kill_votes, 1, 10, 50),
    *_tiers("lawyer", lambda s: s.spare_votes, 1, 10, 50),
    *_tiers("streak", lambda s: s.best_streak, 3, 5, 10),
    *_tiers("legend", lambda s: s.legends, 1, 5),
    # Reactions given
    Rule("generous", 100, lambda s: s.likes_given),
    Rule("critic", 100, lambda s: s.dislikes_given),
    Rule("weathervane", 10, _counter("reaction_switches")),
    Rule("quickdraw", 20, _counter("first_reacts")),
    # Arena
    Rule("oracle", 5, _counter("best_guess_streak")),
    Rule("contrarian", 5, _counter("wrong_guesses")),
    # Uploads
    Rule("garbage_chute", 10, _counter("best_dup_streak")),
    Rule("early_bird", 1, lambda s: s.morning_uploads),
    Rule("veteran", 365, lambda s: s.days_since_first_upload),
    Rule("dynasty", 3, lambda s: s.hall_top10),
    # Economy and games
    Rule("piggy_bank", 100, lambda s: s.earned),
    Rule("millionaire", 1000, lambda s: s.earned),
    Rule("wit", 1, _counter("caption_wins")),
    Rule("gold_digger", 1, _counter("gold_claims")),
    Rule("croupier", 10, _counter("spins")),
    Rule("astrologer", 7, _counter("horoscopes")),
    # Activity
    Rule("regular", 7, _counter("best_active_streak")),
    Rule("resident", 30, _counter("best_active_streak")),
    # v4: casino and bets
    Rule("gambler", 100, _counter("casino_bets")),
    Rule("sniper", 5, _counter("bullseyes")),
    Rule("sportsman", 1, lambda s: int(s.counter("sports_won") == 0b11111)),
    Rule("bettor", 20, _counter("bets_won")),
    # v4: shop, people, progress
    Rule("shopper", 10, _counter("purchases")),
    Rule("resurrector", 1, _counter("resurrections")),
    Rule("titled", 1, _counter("titled")),
    Rule("glove", 1, _counter("challenges_sent")),
    Rule("duelist", 5, _counter("challenge_wins")),
    Rule("daily_7", 7, _counter("best_daily_streak")),
    Rule("daily_30", 30, _counter("best_daily_streak")),
    Rule("quester", 30, _counter("quests_done")),
    Rule("challenger", 3, _counter("challenges_done")),
    Rule("treasure_hunter", 10, _counter("chests_opened")),
    Rule("monster_hunter", 10, _counter("bosses_beaten")),
    Rule("patron", 1000, _counter("given")),
    Rule("robin_hood", 5, _counter("robberies")),
    Rule("easy_prey", 5, _counter("times_robbed")),
    Rule("golden_wedding", 30, lambda s: s.married_days),
]

# Granted directly by the game when the moment happens.
EVENT_CODES = [
    "self_executioner",  # voted to execute your own pic
    "devils_advocate",  # the only "spare" vote against a crowd of 2+ "kill"
    "last_word_saved",  # pardoned after the uploader's last word
    "necromancer",  # your pic was brought back from the graveyard
    "black_streak",  # 3 of your pics executed within a day
    "lone_warrior",  # the only vote in a battle decided it
    "ice_heart",  # your vote was decisive and the loser died
    "revenge",  # your pic beat the one it lost to before
    "underdog",  # pic under 950 beat a pic of 1050+
    "regicide",  # your pic ended a champion streak of 3+
    "lucky",  # three legends from the random in one day
    "deja_vu",  # the random gave you your own pic
    "ghost",  # came back after a week of silence
    "night_court",  # voted in court between 3 and 5 am
    "draw_of_century",  # took part in a 5:5 (or bigger) draw
    "jackpot",  # your pic of the day won a duel the same day
    # v4
    "all_in",  # bet your whole balance (300+) in the casino
    "bankrupt",  # the casino took your last coin
    "high_roller",  # won 2000+ on a single bet
    "triple_seven",  # 777 on a paid spin
    "dark_horse",  # won an arena bet at odds of ×5 or more
    "appeal_won",  # your pic was pardoned on appeal
    "week_perfect",  # all three weekly challenges
    "empty_chest",  # opened an empty chest
    "boss_slayer",  # top damage against a beaten boss
    "last_hit",  # finished a boss off
    "bounty_hunter",  # collected a bounty
    "wanted",  # 500+ bounty on your pic
    "caught",  # failed a robbery
    "married",  # got married
    "divorced",  # got divorced
    "breeder",  # your pic evolved into a beast
    "dragon",  # your pic became a dragon
]

RARITY: dict[str, str] = {
    **{code: COMMON for code in (
        "up_1", "up_10", "night_1", "liked_10", "hated_5", "exec_1", "killer_1", "lawyer_1",
        "titled", "glove", "empty_chest", "caught", "married",
    )},
    **{code: RARE for code in (
        "up_50", "up_100", "night_25", "liked_50", "hated_25", "exec_10", "killer_10", "lawyer_10",
        "streak_3", "legend_1", "generous", "critic", "weathervane", "quickdraw", "contrarian",
        "garbage_chute", "early_bird", "piggy_bank", "wit", "croupier", "astrologer", "regular",
        "self_executioner", "devils_advocate", "necromancer", "lone_warrior", "deja_vu", "lucky",
        "night_court", "revenge",
        "gambler", "sniper", "sportsman", "bettor", "shopper", "resurrector", "duelist", "daily_7",
        "quester", "challenger", "treasure_hunter", "patron", "robin_hood", "easy_prey", "all_in",
        "bankrupt", "boss_slayer", "last_hit", "bounty_hunter", "wanted", "divorced", "breeder",
    )},
    **{code: LEGENDARY for code in (
        "up_250", "up_500", "up_1000", "night_100", "liked_200", "hated_100", "exec_50", "killer_50",
        "lawyer_50", "streak_5", "streak_10", "legend_5", "oracle", "veteran", "dynasty", "millionaire",
        "gold_digger", "resident", "last_word_saved", "black_streak", "ice_heart", "underdog",
        "regicide", "ghost", "draw_of_century", "jackpot",
        "daily_30", "monster_hunter", "golden_wedding", "high_roller", "triple_seven", "dark_horse",
        "appeal_won", "week_perfect", "dragon",
    )},
}
SECRET = {
    "self_executioner", "deja_vu", "ghost", "night_court", "draw_of_century", "jackpot", "garbage_chute",
    "bankrupt", "empty_chest", "caught", "divorced",
}

RULE_CODES = [rule.code for rule in RULES]
ALL_CODES = RULE_CODES + EVENT_CODES
UPLOAD_RULES = [rule for rule in RULES if rule.code.startswith("up_")]


def rarity(code: str) -> str:
    return RARITY.get(code, COMMON)


def earned(stats: UserStats, owned: set[str]) -> list[str]:
    return [rule.code for rule in RULES if rule.code not in owned and rule.metric(stats) >= rule.threshold]


def showcase(owned: set[str], owners: dict[str, int], limit: int = 3) -> list[str]:
    """Rarest owned achievements first: by rarity, then by how few people have them."""
    return sorted(owned, key=lambda code: (RARITY_ORDER[rarity(code)], owners.get(code, 0), code))[:limit]


def upload_title_code(uploads: int) -> str | None:
    """Current title = highest upload tier reached."""
    reached = [rule.code for rule in UPLOAD_RULES if uploads >= rule.threshold]
    return reached[-1] if reached else None


def next_upload_goal(uploads: int) -> Rule | None:
    for rule in UPLOAD_RULES:
        if uploads < rule.threshold:
            return rule
    return None
