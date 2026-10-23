"""Message texts for every card and screen. Pure formatting, no I/O.

One layout for all of them (see layout.card): header, italic flavour line, empty line,
blocks split by empty lines; one emoji per line, at its start; list items fit a phone line.
"""

from bot.tg.views.layout import (
    BAR_CELLS, SLOT_COLORS, MEDALS, timer, bar, num, money, bare, DUEL_SLOTS, TOURNAMENT_SLOTS,
    slot_names, rating, delta, who, card, cited, plural, ago, duration, hp_bar
)
from bot.tg.views.pics import pic_footer, pic_caption
from bot.tg.views.arena import (
    vote_lines, bets_line, battle_card, battle_report, battle_result, streak_announcement, bets_result,
    evolution_lines, bounty_line, challenge_card, challenge_closed, challenge_names, challenge_result,
    dice_duel_result, score_line
)
from bot.tg.views.court import court_card, court_result, appeal_hint
from bot.tg.views.announce import NOTE_CHESTS, note_line, RARITY_WORDS, announcement, has_legendary
from bot.tg.views.panel import (
    home, hall, bottom, REMOVAL_REASONS, graveyard, top, upload_hub, upload_progress, admin,
    GAMES_SCREEN, admin_stats
)
from bot.tg.views.profile import Wallet, profile
from bot.tg.views.games import (
    caption_card, caption_result, caption_cancelled, gold_caption, spin_result, horoscope, whose_card, whose_result,
    hl_card, hl_over, hl_reveal
)
from bot.tg.views.casino import casino_screen, casino_title, casino_result
from bot.tg.views.shop import shop_screen, pic_menu, bought, PURCHASE_FACTS, purchase_notice, wanted_poster
from bot.tg.views.progress import (
    task_line, quests_screen, daily_result, chest_opening, chest_opened, day_event_line, day_event
)
from bot.tg.views.boss import boss_card, boss_result
from bot.tg.views.people import gift, robbery, proposal, wedding, rejected, divorce
from bot.tg.views.seasons import points, podium_lines, season_results, season_warning, seasons_hall, season_badges

__all__ = [
    "BAR_CELLS", "DUEL_SLOTS", "GAMES_SCREEN", "MEDALS", "NOTE_CHESTS", "PURCHASE_FACTS",
    "RARITY_WORDS", "REMOVAL_REASONS", "SLOT_COLORS", "TOURNAMENT_SLOTS", "Wallet", "admin", "ago",
    "announcement", "appeal_hint", "bar", "bare", "battle_card", "battle_report", "battle_result",
    "bets_line", "bets_result", "boss_card", "boss_result", "bottom", "bought", "bounty_line",
    "caption_cancelled", "caption_card", "caption_result", "card", "casino_result", "casino_screen",
    "casino_title", "challenge_card", "challenge_closed", "challenge_names", "challenge_result",
    "chest_opened", "chest_opening", "cited", "court_card", "court_result", "daily_result", "day_event",
    "day_event_line", "delta", "divorce", "duration", "evolution_lines", "gift", "gold_caption",
    "graveyard", "hall", "has_legendary", "home", "horoscope", "hp_bar", "money", "note_line", "num",
    "pic_caption", "pic_footer", "pic_menu", "plural", "podium_lines", "points", "profile", "proposal",
    "purchase_notice", "season_badges", "season_results", "season_warning", "seasons_hall",
    "quests_screen", "rating", "rejected", "robbery", "shop_screen", "slot_names", "spin_result",
    "streak_announcement", "task_line", "timer", "top", "upload_hub", "upload_progress", "vote_lines",
    "wanted_poster", "wedding", "who", "whose_card", "whose_result", "hl_card", "hl_over", "hl_reveal",
    "dice_duel_result", "score_line", "admin_stats"
]
