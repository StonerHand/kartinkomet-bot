"""The connection, schema migrations and the columns rows are read with."""

import sqlite3
from collections.abc import Sequence
from pathlib import Path

from bot.models.records import Pic


SCHEMA_PATH = Path(__file__).parent / "schema.sql"
SCHEMA_VERSION = "2"
LEGEND_POOL_SIZE = 50
MIN_EXPERIENCE = 3  # battles + reactions before a pic can be a legend or bottom-dweller

PIC_COLUMNS = (
    "id, file_id, file_unique_id, added_by, added_at, visual_hash, status, removed_at, "
    "removed_reason, rating, games, wins, losses, loss_streak, best_streak, shown_count, "
    "likes, dislikes, immune_until, frame"
)


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
    seen_columns = {row[1] for row in connection.execute("PRAGMA table_info(deck_seen)")}
    if "at" not in seen_columns:  # v6.8: when a pic was shown, so a new cycle can keep the latest ones out
        connection.execute("ALTER TABLE deck_seen ADD COLUMN at INTEGER NOT NULL DEFAULT 0")
    if connection.execute("SELECT 1 FROM meta WHERE key = 'deck_merged'").fetchone() is None:
        # v6.8: one deck per chat. /pic ('pic:<chat>') and the arena ('arena:<chat>') used to keep
        # separate decks, so a pic seen in one came back in the other.
        connection.execute(
            "INSERT OR IGNORE INTO deck_seen (scope, pic_id, at) "
            "SELECT 'deck:' || substr(scope, instr(scope, ':') + 1), pic_id, at FROM deck_seen "
            "WHERE scope LIKE 'pic:%' OR scope LIKE 'arena:%'"
        )
        connection.execute("DELETE FROM deck_seen WHERE scope LIKE 'pic:%' OR scope LIKE 'arena:%'")
        connection.execute("INSERT INTO meta (key, value) VALUES ('deck_merged', '1')")
    pic_columns = {row[1] for row in connection.execute("PRAGMA table_info(pics)")}
    if "frame" not in pic_columns:
        connection.execute("ALTER TABLE pics ADD COLUMN frame TEXT")
    if connection.execute("SELECT 1 FROM meta WHERE key = 'members_seeded'").fetchone() is None:
        # v5.1: who plays where, recovered from the chats' votes, hits, games and challenges.
        connection.execute(
            """
            INSERT OR IGNORE INTO chat_members (chat_id, user_id, last_seen)
            SELECT chat_id, user_id, MAX(at) FROM (
                SELECT b.chat_id, v.user_id, b.started_at AS at FROM battle_votes v JOIN battles b ON b.id = v.battle_id
                UNION ALL SELECT c.chat_id, v.user_id, c.started_at FROM court_votes v JOIN courts c ON c.id = v.court_id
                UNION ALL SELECT s.chat_id, h.user_id, s.started_at FROM boss_hits h JOIN bosses s ON s.id = h.boss_id
                UNION ALL SELECT g.chat_id, e.user_id, g.created_at FROM game_entries e JOIN games g ON g.id = e.game_id
                UNION ALL SELECT g.chat_id, v.user_id, g.created_at FROM game_votes v JOIN games g ON g.id = v.game_id
                UNION ALL SELECT chat_id, from_user, created_at FROM challenges
                UNION ALL SELECT chat_id, to_user, created_at FROM challenges WHERE to_user IS NOT NULL
                UNION ALL SELECT chat_id, from_user, created_at FROM proposals
                UNION ALL SELECT chat_id, to_user, created_at FROM proposals
            ) WHERE chat_id < 0 GROUP BY chat_id, user_id
            """
        )
        connection.execute("INSERT INTO meta (key, value) VALUES ('members_seeded', '1')")
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
