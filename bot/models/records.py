"""Rows as the game sees them: a pic, a battle, a court, a player's stats. Plain data, no SQL."""

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Pic:
    id: str
    file_id: str
    file_unique_id: str
    added_by: int | None
    added_at: int | None
    visual_hash: str | None
    status: str
    removed_at: int | None
    removed_reason: str | None
    rating: float
    games: int
    wins: int
    losses: int
    loss_streak: int
    best_streak: int
    shown_count: int
    likes: int
    dislikes: int
    immune_until: int | None
    frame: str | None = None  # a cosmetic frame from a chest: drawn around the pic in battles


@dataclass(frozen=True)
class Battle:
    id: str
    chat_id: int
    kind: str
    message_id: int | None
    started_at: int
    ends_at: int
    status: str
    streak: int
    title: str
    winner_slot: int | None
    result_streak: int | None
    card_is_photo: bool
    extended: bool
    pics: tuple[Pic, ...]
    votes: dict[int, int]
    mode: str = ""  # '' regular, 'challenge' player vs player
    bets: dict[int, tuple[int, int]] = field(default_factory=dict)  # user → (slot, amount)

    def vote_counts(self) -> list[int]:
        counts = [0] * len(self.pics)
        for slot in self.votes.values():
            if 0 <= slot < len(counts):
                counts[slot] += 1
        return counts

    def bet_pool(self) -> list[int]:
        pool = [0] * len(self.pics)
        for slot, amount in self.bets.values():
            if 0 <= slot < len(pool):
                pool[slot] += amount
        return pool


@dataclass(frozen=True)
class Court:
    id: str
    chat_id: int
    pic: Pic
    message_id: int | None
    reason: str
    started_by: int | None
    started_at: int
    ends_at: int
    status: str
    title: str
    pic_message_id: int | None
    last_word: str | None
    votes: dict[int, str]
    appeal: bool = False
    bail: int = 0

    def vote_counts(self) -> tuple[int, int]:
        kill = sum(1 for vote in self.votes.values() if vote == "kill")
        return kill, len(self.votes) - kill


@dataclass(frozen=True)
class UserStats:
    uploads: int
    night_uploads: int
    likes_received: int
    dislikes_received: int
    pics_executed: int
    kill_votes: int
    spare_votes: int
    best_streak: int
    legends: int
    pics_alive: int
    morning_uploads: int = 0
    days_since_first_upload: int = 0
    hall_top10: int = 0
    likes_given: int = 0
    dislikes_given: int = 0
    earned: int = 0
    counters: dict[str, int] = field(default_factory=dict)
    married_days: int = 0

    def counter(self, key: str) -> int:
        return self.counters.get(key, 0)
