"""Rows as dataclasses, the connection and schema migrations."""

import sqlite3
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path


SCHEMA_PATH = Path(__file__).parent.parent / "schema.sql"
SCHEMA_VERSION = "2"
LEGEND_POOL_SIZE = 50
MIN_EXPERIENCE = 3  # battles + reactions before a pic can be a legend or bottom-dweller

PIC_COLUMNS = (
    "id, file_id, file_unique_id, added_by, added_at, visual_hash, status, removed_at, "
    "removed_reason, rating, games, wins, losses, loss_streak, best_streak, shown_count, "
    "likes, dislikes, immune_until, frame"
)


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


def connect(database_path: Path | str) -> sqlite3.Connection:
    connection = sqlite3.connect(database_path, timeout=30)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys=ON")
    connection.execute("PRAGMA journal_mode=WAL")
    connection.execute("PRAGMA synchronous=NORMAL")
    connection.execute("PRAGMA busy_timeout=30000")
    return connection


def apply_schema(connection: sqlite3.Connection) -> None:
    connection.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))
    # Columns added after the first v2 release: CREATE TABLE IF NOT EXISTS won't add them.
    battle_columns = {row[1] for row in connection.execute("PRAGMA table_info(battles)")}
    for column in ("card_is_photo", "extended"):
        if column not in battle_columns:
            connection.execute(f"ALTER TABLE battles ADD COLUMN {column} INTEGER NOT NULL DEFAULT 0")
    if "mode" not in battle_columns:  # v4: '' = regular battle, 'challenge' = player vs player
        connection.execute("ALTER TABLE battles ADD COLUMN mode TEXT NOT NULL DEFAULT ''")
    ledger_columns = {row[1] for row in connection.execute("PRAGMA table_info(ledger)")}
    if "earn" not in ledger_columns:  # v4: 1 = activity income (levels, weekly "rich" crown)
        connection.execute("ALTER TABLE ledger ADD COLUMN earn INTEGER NOT NULL DEFAULT 1")
    court_columns = {row[1] for row in connection.execute("PRAGMA table_info(courts)")}
    for column in ("appeal", "bail"):  # v4: appeal courts and the bail paid for them
        if column not in court_columns:
            connection.execute(f"ALTER TABLE courts ADD COLUMN {column} INTEGER NOT NULL DEFAULT 0")
    # v5: casino duels between players ride on challenges; raid bosses; cosmetic pic frames.
    challenge_columns = {row[1] for row in connection.execute("PRAGMA table_info(challenges)")}
    if "game" not in challenge_columns:  # '' = a pic duel, else the casino game ('dice', 'darts', 'bowling')
        connection.execute("ALTER TABLE challenges ADD COLUMN game TEXT NOT NULL DEFAULT ''")
    if "winner" not in challenge_columns:  # the player who took the pot, for head-to-head scores
        connection.execute("ALTER TABLE challenges ADD COLUMN winner INTEGER")
    boss_columns = {row[1] for row in connection.execute("PRAGMA table_info(bosses)")}
    if "raid" not in boss_columns:
        connection.execute("ALTER TABLE bosses ADD COLUMN raid INTEGER NOT NULL DEFAULT 0")
    if "last_hit_at" not in boss_columns:
        connection.execute("ALTER TABLE bosses ADD COLUMN last_hit_at INTEGER")
    pic_columns = {row[1] for row in connection.execute("PRAGMA table_info(pics)")}
    if "frame" not in pic_columns:
        connection.execute("ALTER TABLE pics ADD COLUMN frame TEXT")
    # v1 kept per-side duel history ("duel:<chat>:left"); the migration filed it under pic scopes.
    connection.execute(
        "DELETE FROM deck_seen WHERE scope LIKE 'pic:duel:%' OR scope LIKE 'pic:tournament:%'"
    )
    connection.execute(
        "INSERT INTO meta (key, value) VALUES ('schema_version', ?) "
        "ON CONFLICT(key) DO NOTHING",
        (SCHEMA_VERSION,),
    )
    connection.commit()


def _pic(row: sqlite3.Row | None) -> Pic | None:
    if row is None:
        return None
    return Pic(**{key: row[key] for key in row.keys()})


def _placeholders(values: Sequence) -> str:
    return ",".join("?" for _ in values)
