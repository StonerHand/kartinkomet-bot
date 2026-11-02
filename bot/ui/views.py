"""One import point for every message text: the design system (bot/ui/layout.py) and the cards of
every mechanic (bot/ui/cards/), so callers write views.card(...), views.battle_card(...).

One design system for all of them (see layout.card): a sentence-case title, an italic flavour
line, then blocks that each open with their emoji or a list mark, and rules or hints in a quote
box at the end (layout.note). tests/layout.py checks it on every message.
"""

from bot.ui.cards.announce import NOTE_CHESTS, note_line, RARITY_WORDS, announcement, has_legendary
from bot.ui.cards.arena import (
    vote_lines, bets_line, battle_card, battle_report, battle_result, streak_announcement, bets_result,
    evolution_lines, bounty_line, challenge_card, challenge_closed, challenge_names, challenge_result,
    dice_duel_result, score_line
)
from bot.ui.cards.boss import boss_card, boss_result
from bot.ui.cards.casino import casino_screen, casino_title, casino_result
from bot.ui.cards.court import court_card, court_result, appeal_hint
from bot.ui.cards.games import (
    caption_card, caption_result, caption_cancelled, gold_caption, spin_result, horoscope, whose_card, whose_result,
    hl_card, hl_over, hl_reveal
)
from bot.ui.cards.party import bet_card, bet_hint, bet_result, bomb_card, bomb_result, who_card, who_result
from bot.ui.cards.panel import (
    home, hall, bottom, REMOVAL_REASONS, graveyard, top, upload_hub, upload_progress, admin,
    PEOPLE_SCREEN, admin_stats, games_screen, season_line
)
from bot.ui.cards.people import ask, gift, redistribution, robbery, proposal, wedding, rejected, divorce
from bot.ui.cards.pics import pic_footer, pic_caption
from bot.ui.cards.profile import Wallet, profile
from bot.ui.cards.progress import (
    task_line, quests_screen, daily_result, chest_opening, chest_opened, day_event_line, day_event
)
from bot.ui.cards.seasons import points, podium_lines, season_results, season_warning, seasons_hall, season_badges
from bot.ui.cards.shop import shop_screen, pic_menu, bought, PURCHASE_FACTS, purchase_notice, wanted_poster
from bot.ui.layout import (
    BAR_CELLS, SLOT_COLORS, MEDALS, timer, bar, num, money, bare, DUEL_SLOTS, TOURNAMENT_SLOTS,
    slot_names, rating, delta, who, card, cited, plural, ago, duration, hp_bar, marked, note
)

__all__ = [
    "BAR_CELLS", "DUEL_SLOTS", "PEOPLE_SCREEN", "MEDALS", "NOTE_CHESTS", "PURCHASE_FACTS",
    "RARITY_WORDS", "REMOVAL_REASONS", "SLOT_COLORS", "TOURNAMENT_SLOTS", "Wallet", "admin", "ago",
    "announcement", "appeal_hint", "ask", "marked", "note", "bar", "bare", "battle_card", "battle_report", "battle_result",
    "bets_line", "bets_result", "boss_card", "boss_result", "bottom", "bought", "bounty_line",
    "caption_cancelled", "caption_card", "caption_result", "card", "casino_result", "casino_screen",
    "casino_title", "challenge_card", "challenge_closed", "challenge_names", "challenge_result",
    "chest_opened", "chest_opening", "cited", "court_card", "court_result", "daily_result", "day_event",
    "day_event_line", "delta", "divorce", "duration", "evolution_lines", "gift", "gold_caption",
    "graveyard", "hall", "has_legendary", "home", "horoscope", "hp_bar", "money", "note_line", "num",
    "pic_caption", "pic_footer", "pic_menu", "plural", "podium_lines", "points", "profile", "proposal",
    "purchase_notice", "redistribution", "season_badges", "season_results", "season_warning", "seasons_hall",
    "quests_screen", "rating", "rejected", "robbery", "shop_screen", "slot_names", "spin_result",
    "streak_announcement", "task_line", "timer", "top", "upload_hub", "upload_progress", "vote_lines",
    "wanted_poster", "wedding", "who", "whose_card", "whose_result", "hl_card", "hl_over", "hl_reveal",
    "dice_duel_result", "score_line", "admin_stats", "games_screen", "season_line",
    "who_card", "who_result", "bomb_card", "bomb_result", "bet_card", "bet_result", "bet_hint",
]
