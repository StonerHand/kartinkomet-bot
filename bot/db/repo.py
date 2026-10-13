"""All SQL lives here. Everything else talks to the database through Repo."""

import sqlite3
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

SCHEMA_PATH = Path(__file__).with_name("schema.sql")
SCHEMA_VERSION = "2"
LEGEND_POOL_SIZE = 50
MIN_EXPERIENCE = 3  # battles + reactions before a pic can be a legend or bottom-dweller

PIC_COLUMNS = (
    "id, file_id, file_unique_id, added_by, added_at, visual_hash, status, removed_at, "
    "removed_reason, rating, games, wins, losses, loss_streak, best_streak, shown_count, "
    "likes, dislikes, immune_until"
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

    def vote_counts(self) -> list[int]:
        counts = [0] * len(self.pics)
        for slot in self.votes.values():
            if 0 <= slot < len(counts):
                counts[slot] += 1
        return counts


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


class Repo:
    def __init__(self, database_path: Path | str) -> None:
        self.database_path = Path(database_path)
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        self.db = connect(self.database_path)
        apply_schema(self.db)
        self._fix_migrated_reaction_times()
        self._known_users: dict[int, tuple] = {}

    def _fix_migrated_reaction_times(self) -> None:
        """Early v2 migrations stamped v1 reactions with the migration time, which made them look
        like this week's. They happened at an unknown time: reset them to 0, once."""
        if self.meta_str("fixed_v1_reaction_times"):
            return
        migrated_at = self.meta_str("migrated_from_v1_at")
        with self.db:
            if migrated_at:
                self.db.execute("UPDATE reactions SET at = 0 WHERE at = ?", (int(migrated_at),))
            self.db.execute(
                "INSERT INTO meta (key, value) VALUES ('fixed_v1_reaction_times', '1') "
                "ON CONFLICT(key) DO NOTHING"
            )

    def close(self) -> None:
        self.db.close()

    # ── meta ────────────────────────────────────────────────────────────

    def meta_int(self, key: str, default: int = 0) -> int:
        row = self.db.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
        return int(row["value"]) if row else default

    def meta_str(self, key: str) -> str | None:
        row = self.db.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
        return row["value"] if row else None

    def set_meta(self, key: str, value: int | str) -> None:
        with self.db:
            self.db.execute(
                "INSERT INTO meta (key, value) VALUES (?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (key, str(value)),
            )

    def incr_meta(self, key: str, by: int = 1) -> int:
        value = self.meta_int(key) + by
        self.set_meta(key, value)
        return value

    # ── users ───────────────────────────────────────────────────────────

    def remember_user(
        self,
        user_id: int,
        username: str | None,
        first_name: str | None,
        last_name: str | None,
        now: int,
    ) -> None:
        fingerprint = (username, first_name, last_name)
        if self._known_users.get(user_id) == fingerprint:
            return
        with self.db:
            self.db.execute(
                """
                INSERT INTO users (user_id, username, first_name, last_name, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(user_id) DO UPDATE SET
                    username = excluded.username,
                    first_name = excluded.first_name,
                    last_name = excluded.last_name,
                    updated_at = excluded.updated_at
                WHERE users.username IS NOT excluded.username
                   OR users.first_name IS NOT excluded.first_name
                   OR users.last_name IS NOT excluded.last_name
                """,
                (user_id, username, first_name, last_name, now, now),
            )
        self._known_users[user_id] = fingerprint

    def user_label(self, user_id: int | None) -> str:
        if user_id is None:
            return "аноним"
        row = self.db.execute(
            "SELECT username, first_name, last_name FROM users WHERE user_id = ?",
            (user_id,),
        ).fetchone()
        if row is None:
            return str(user_id)
        # Never prefix "@": Telegram turns it into a mention and pings the person every time.
        if row["username"]:
            return str(row["username"]).lstrip("@")
        name = " ".join(part for part in (row["first_name"], row["last_name"]) if part).strip()
        return name or str(user_id)

    def all_user_ids(self) -> list[int]:
        return [
            row[0]
            for row in self.db.execute(
                "SELECT user_id FROM users UNION SELECT added_by FROM pics WHERE added_by IS NOT NULL"
            )
        ]

    def count_users(self) -> int:
        return self.db.execute("SELECT COUNT(*) FROM users").fetchone()[0]

    # ── pics ────────────────────────────────────────────────────────────

    def get_pic(self, pic_id: str) -> Pic | None:
        return _pic(
            self.db.execute(f"SELECT {PIC_COLUMNS} FROM pics WHERE id = ?", (pic_id,)).fetchone()
        )

    def pic_known(self, file_unique_id: str) -> bool:
        row = self.db.execute(
            "SELECT 1 FROM pics WHERE file_unique_id = ?", (file_unique_id,)
        ).fetchone()
        return row is not None

    def visual_hashes(self) -> list[str]:
        return [
            row[0]
            for row in self.db.execute(
                "SELECT visual_hash FROM pics WHERE visual_hash IS NOT NULL"
            )
        ]

    def add_pic(
        self,
        file_id: str,
        file_unique_id: str,
        added_by: int | None,
        visual_hash: str | None,
        now: int,
    ) -> Pic:
        pic_id = uuid4().hex
        with self.db:
            self.db.execute(
                """
                INSERT INTO pics (id, file_id, file_unique_id, added_by, added_at, visual_hash)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (pic_id, file_id, file_unique_id, added_by, now, visual_hash),
            )
        pic = self.get_pic(pic_id)
        assert pic is not None
        return pic

    def count_pics(self, status: str = "alive") -> int:
        return self.db.execute(
            "SELECT COUNT(*) FROM pics WHERE status = ?", (status,)
        ).fetchone()[0]

    def uploads_since(self, user_id: int, since: int) -> int:
        return self.db.execute(
            "SELECT COUNT(*) FROM pics WHERE added_by = ? AND added_at >= ?",
            (user_id, since),
        ).fetchone()[0]

    def draw(
        self,
        scope: str,
        bucket: str,
        now: int,
        limit: int = 1,
        exclude: Iterable[str] = (),
        fresh_seconds: int = 7 * 24 * 3600,
    ) -> list[Pic]:
        """Random alive pics not yet seen in this scope's current deck cycle."""
        excluded = list(exclude)
        conditions = [
            "p.status = 'alive'",
            "NOT EXISTS (SELECT 1 FROM deck_seen d WHERE d.scope = ? AND d.pic_id = p.id)",
        ]
        params: list = [scope]
        if excluded:
            conditions.append(f"p.id NOT IN ({_placeholders(excluded)})")
            params.extend(excluded)
        if bucket == "fresh":
            conditions.append("p.added_at >= ?")
            params.append(now - fresh_seconds)
        elif bucket == "legend":
            conditions.append(
                "p.id IN (SELECT id FROM pics WHERE status = 'alive' AND (games + likes + dislikes) >= ? "
                "ORDER BY rating DESC LIMIT ?)"
            )
            params.extend([MIN_EXPERIENCE, LEGEND_POOL_SIZE])
        params.append(limit)
        rows = self.db.execute(
            f"SELECT {PIC_COLUMNS} FROM pics p WHERE {' AND '.join(conditions)} "
            "ORDER BY random() LIMIT ?",
            params,
        ).fetchall()
        return [_pic(row) for row in rows]

    def random_alive(self, limit: int, exclude: Iterable[str] = ()) -> list[Pic]:
        excluded = list(exclude)
        where = "status = 'alive'"
        if excluded:
            where += f" AND id NOT IN ({_placeholders(excluded)})"
        rows = self.db.execute(
            f"SELECT {PIC_COLUMNS} FROM pics WHERE {where} ORDER BY random() LIMIT ?",
            (*excluded, limit),
        ).fetchall()
        return [_pic(row) for row in rows]

    def clear_seen(self, scope: str) -> None:
        with self.db:
            self.db.execute("DELETE FROM deck_seen WHERE scope = ?", (scope,))

    def mark_shown(self, scope: str, pic_ids: Sequence[str], now: int) -> None:
        with self.db:
            self.db.executemany(
                "INSERT OR IGNORE INTO deck_seen (scope, pic_id) VALUES (?, ?)",
                [(scope, pic_id) for pic_id in pic_ids],
            )
            self.db.executemany(
                "UPDATE pics SET shown_count = shown_count + 1, last_shown_at = ? WHERE id = ?",
                [(now, pic_id) for pic_id in pic_ids],
            )

    def react(self, pic_id: str, user_id: int, value: int, now: int) -> bool:
        """Set a user's reaction. Returns False if it was already the same."""
        row = self.db.execute(
            "SELECT value FROM reactions WHERE pic_id = ? AND user_id = ?",
            (pic_id, user_id),
        ).fetchone()
        previous = row["value"] if row else 0
        if previous == value:
            return False
        likes_delta = (value == 1) - (previous == 1)
        dislikes_delta = (value == -1) - (previous == -1)
        with self.db:
            self.db.execute(
                """
                INSERT INTO reactions (pic_id, user_id, value, at) VALUES (?, ?, ?, ?)
                ON CONFLICT(pic_id, user_id) DO UPDATE SET value = excluded.value, at = excluded.at
                """,
                (pic_id, user_id, value, now),
            )
            self.db.execute(
                "UPDATE pics SET likes = likes + ?, dislikes = dislikes + ? WHERE id = ?",
                (likes_delta, dislikes_delta, pic_id),
            )
        return True

    def top_rated(self, limit: int = 10) -> list[Pic]:
        rows = self.db.execute(
            f"SELECT {PIC_COLUMNS} FROM pics WHERE status = 'alive' AND (games + likes + dislikes) >= ? "
            "ORDER BY rating DESC, wins DESC LIMIT ?",
            (MIN_EXPERIENCE, limit),
        ).fetchall()
        return [_pic(row) for row in rows]

    def bottom_rated(self, limit: int = 10) -> list[Pic]:
        rows = self.db.execute(
            f"SELECT {PIC_COLUMNS} FROM pics WHERE status = 'alive' AND (games + likes + dislikes) >= ? "
            "ORDER BY rating ASC, losses DESC LIMIT ?",
            (MIN_EXPERIENCE, limit),
        ).fetchall()
        return [_pic(row) for row in rows]

    def graveyard(self, limit: int = 5) -> list[Pic]:
        rows = self.db.execute(
            f"SELECT {PIC_COLUMNS} FROM pics WHERE status = 'executed' "
            "ORDER BY removed_at DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return [_pic(row) for row in rows]

    def is_legend(self, pic_id: str) -> bool:
        row = self.db.execute(
            "SELECT 1 FROM (SELECT id FROM pics WHERE status = 'alive' AND (games + likes + dislikes) >= ? "
            "ORDER BY rating DESC LIMIT ?) WHERE id = ?",
            (MIN_EXPERIENCE, LEGEND_POOL_SIZE, pic_id),
        ).fetchone()
        return row is not None

    def remove_pic(self, pic_id: str, status: str, reason: str, now: int) -> bool:
        with self.db:
            cursor = self.db.execute(
                "UPDATE pics SET status = ?, removed_reason = ?, removed_at = ? "
                "WHERE id = ? AND status = 'alive'",
                (status, reason, now, pic_id),
            )
            self.db.execute("DELETE FROM deck_seen WHERE pic_id = ?", (pic_id,))
        return cursor.rowcount == 1

    def revive_pic(self, pic_id: str, immune_until: int) -> bool:
        with self.db:
            cursor = self.db.execute(
                "UPDATE pics SET status = 'alive', removed_reason = NULL, removed_at = NULL, "
                "loss_streak = 0, immune_until = ? WHERE id = ? AND status != 'alive'",
                (immune_until, pic_id),
            )
        return cursor.rowcount == 1

    def set_immunity(self, pic_id: str, immune_until: int) -> None:
        with self.db:
            self.db.execute(
                "UPDATE pics SET immune_until = ? WHERE id = ?", (immune_until, pic_id)
            )

    def apply_battle_result(
        self,
        pic_id: str,
        rating: float,
        outcome: str,
        streak: int | None = None,
    ) -> None:
        """outcome: 'win' | 'loss' | 'draw'."""
        with self.db:
            self.db.execute(
                """
                UPDATE pics SET
                    rating = ?,
                    games = games + 1,
                    wins = wins + (? = 'win'),
                    losses = losses + (? = 'loss'),
                    loss_streak = CASE ? WHEN 'loss' THEN loss_streak + 1
                                         WHEN 'win' THEN 0 ELSE loss_streak END,
                    best_streak = MAX(best_streak, COALESCE(?, 0))
                WHERE id = ?
                """,
                (rating, outcome, outcome, outcome, streak, pic_id),
            )

    # ── battles ─────────────────────────────────────────────────────────

    def create_battle(
        self,
        kind: str,
        chat_id: int,
        pic_ids: Sequence[str],
        now: int,
        duration: int,
        streak: int = 0,
        title: str = "",
    ) -> str:
        battle_id = uuid4().hex[:16]
        with self.db:
            self.db.execute(
                "INSERT INTO battles (id, chat_id, kind, started_at, ends_at, streak, title) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (battle_id, chat_id, kind, now, now + duration, streak, title),
            )
            self.db.executemany(
                "INSERT INTO battle_entries (battle_id, slot, pic_id) VALUES (?, ?, ?)",
                [(battle_id, slot, pic_id) for slot, pic_id in enumerate(pic_ids)],
            )
        return battle_id

    def set_battle_message(self, battle_id: str, message_id: int, is_photo: bool = False) -> None:
        with self.db:
            self.db.execute(
                "UPDATE battles SET message_id = ?, card_is_photo = ? WHERE id = ?",
                (message_id, int(is_photo), battle_id),
            )

    def restart_battle_clock(self, battle_id: str, now: int, duration: int) -> None:
        with self.db:
            self.db.execute(
                "UPDATE battles SET started_at = ?, ends_at = ? WHERE id = ? AND status = 'active'",
                (now, now + duration, battle_id),
            )

    def extend_battle(self, battle_id: str, seconds: int) -> bool:
        """Push the end of a still-active battle once. False if it was already extended."""
        with self.db:
            cursor = self.db.execute(
                "UPDATE battles SET ends_at = ends_at + ?, extended = 1 "
                "WHERE id = ? AND status = 'active' AND extended = 0",
                (seconds, battle_id),
            )
        return cursor.rowcount == 1

    def drop_battle(self, battle_id: str) -> None:
        with self.db:
            self.db.execute("DELETE FROM battles WHERE id = ?", (battle_id,))

    def get_battle(self, battle_id: str) -> Battle | None:
        row = self.db.execute("SELECT * FROM battles WHERE id = ?", (battle_id,)).fetchone()
        if row is None:
            return None
        pics = tuple(
            _pic(pic_row)
            for pic_row in self.db.execute(
                f"SELECT {', '.join('p.' + c.strip() for c in PIC_COLUMNS.split(','))} "
                "FROM battle_entries e JOIN pics p ON p.id = e.pic_id "
                "WHERE e.battle_id = ? ORDER BY e.slot",
                (battle_id,),
            )
        )
        votes = {
            vote_row["user_id"]: vote_row["slot"]
            for vote_row in self.db.execute(
                "SELECT user_id, slot FROM battle_votes WHERE battle_id = ?", (battle_id,)
            )
        }
        return Battle(
            id=row["id"],
            chat_id=row["chat_id"],
            kind=row["kind"],
            message_id=row["message_id"],
            started_at=row["started_at"],
            ends_at=row["ends_at"],
            status=row["status"],
            streak=row["streak"],
            title=row["title"],
            winner_slot=row["winner_slot"],
            result_streak=row["result_streak"],
            card_is_photo=bool(row["card_is_photo"]),
            extended=bool(row["extended"]),
            pics=pics,
            votes=votes,
        )

    def active_battle(self, chat_id: int, kind: str) -> Battle | None:
        row = self.db.execute(
            "SELECT id FROM battles WHERE status = 'active' AND chat_id = ? AND kind = ? "
            "ORDER BY started_at DESC LIMIT 1",
            (chat_id, kind),
        ).fetchone()
        return self.get_battle(row["id"]) if row else None

    def active_battle_ids(self) -> list[str]:
        return [
            row[0] for row in self.db.execute("SELECT id FROM battles WHERE status = 'active'")
        ]

    def vote_battle(self, battle_id: str, user_id: int, slot: int) -> bool:
        row = self.db.execute(
            "SELECT slot FROM battle_votes WHERE battle_id = ? AND user_id = ?",
            (battle_id, user_id),
        ).fetchone()
        if row is not None and row["slot"] == slot:
            return False
        with self.db:
            self.db.execute(
                "INSERT INTO battle_votes (battle_id, user_id, slot) VALUES (?, ?, ?) "
                "ON CONFLICT(battle_id, user_id) DO UPDATE SET slot = excluded.slot",
                (battle_id, user_id, slot),
            )
        return True

    def close_battle(self, battle_id: str) -> bool:
        """Atomically mark a battle done. False if someone already closed it."""
        with self.db:
            cursor = self.db.execute(
                "UPDATE battles SET status = 'done' WHERE id = ? AND status = 'active'",
                (battle_id,),
            )
        return cursor.rowcount == 1

    def set_battle_result(
        self, battle_id: str, winner_slot: int | None, result_streak: int | None
    ) -> None:
        with self.db:
            self.db.execute(
                "UPDATE battles SET winner_slot = ?, result_streak = ? WHERE id = ?",
                (winner_slot, result_streak, battle_id),
            )

    # ── courts ──────────────────────────────────────────────────────────

    def create_court(
        self,
        chat_id: int,
        pic_id: str,
        reason: str,
        started_by: int | None,
        now: int,
        duration: int,
        title: str = "",
        pic_message_id: int | None = None,
    ) -> str:
        court_id = uuid4().hex[:16]
        with self.db:
            self.db.execute(
                "INSERT INTO courts (id, chat_id, pic_id, reason, started_by, started_at, ends_at, "
                "title, pic_message_id) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    court_id,
                    chat_id,
                    pic_id,
                    reason,
                    started_by,
                    now,
                    now + duration,
                    title,
                    pic_message_id,
                ),
            )
        return court_id

    def set_court_message(self, court_id: str, message_id: int) -> None:
        with self.db:
            self.db.execute(
                "UPDATE courts SET message_id = ? WHERE id = ?", (message_id, court_id)
            )

    def drop_court(self, court_id: str) -> None:
        with self.db:
            self.db.execute("DELETE FROM courts WHERE id = ?", (court_id,))

    def get_court(self, court_id: str) -> Court | None:
        row = self.db.execute("SELECT * FROM courts WHERE id = ?", (court_id,)).fetchone()
        if row is None:
            return None
        pic = self.get_pic(row["pic_id"])
        if pic is None:
            return None
        votes = {
            vote_row["user_id"]: vote_row["vote"]
            for vote_row in self.db.execute(
                "SELECT user_id, vote FROM court_votes WHERE court_id = ?", (court_id,)
            )
        }
        return Court(
            id=row["id"],
            chat_id=row["chat_id"],
            pic=pic,
            message_id=row["message_id"],
            reason=row["reason"],
            started_by=row["started_by"],
            started_at=row["started_at"],
            ends_at=row["ends_at"],
            status=row["status"],
            title=row["title"],
            pic_message_id=row["pic_message_id"],
            last_word=row["last_word"],
            votes=votes,
        )

    def active_court_for_pic(self, pic_id: str) -> Court | None:
        row = self.db.execute(
            "SELECT id FROM courts WHERE status = 'active' AND pic_id = ? LIMIT 1", (pic_id,)
        ).fetchone()
        return self.get_court(row["id"]) if row else None

    def court_by_message(self, chat_id: int, message_id: int) -> Court | None:
        row = self.db.execute(
            "SELECT id FROM courts WHERE chat_id = ? AND message_id = ? LIMIT 1",
            (chat_id, message_id),
        ).fetchone()
        return self.get_court(row["id"]) if row else None

    def active_courts_in_chat(self, chat_id: int, now: int) -> list[int]:
        """End times of courts still running in a chat."""
        return [
            row[0]
            for row in self.db.execute(
                "SELECT ends_at FROM courts WHERE status = 'active' AND chat_id = ? AND ends_at > ?",
                (chat_id, now),
            )
        ]

    def active_court_ids(self) -> list[str]:
        return [
            row[0] for row in self.db.execute("SELECT id FROM courts WHERE status = 'active'")
        ]

    def vote_court(self, court_id: str, user_id: int, vote: str) -> bool:
        row = self.db.execute(
            "SELECT vote FROM court_votes WHERE court_id = ? AND user_id = ?",
            (court_id, user_id),
        ).fetchone()
        if row is not None and row["vote"] == vote:
            return False
        with self.db:
            self.db.execute(
                "INSERT INTO court_votes (court_id, user_id, vote) VALUES (?, ?, ?) "
                "ON CONFLICT(court_id, user_id) DO UPDATE SET vote = excluded.vote",
                (court_id, user_id, vote),
            )
        return True

    def set_last_word(self, court_id: str, text: str) -> bool:
        with self.db:
            cursor = self.db.execute(
                "UPDATE courts SET last_word = ? WHERE id = ? AND status = 'active' "
                "AND last_word IS NULL",
                (text, court_id),
            )
        return cursor.rowcount == 1

    def close_court(self, court_id: str, status: str) -> bool:
        with self.db:
            cursor = self.db.execute(
                "UPDATE courts SET status = ? WHERE id = ? AND status = 'active'",
                (status, court_id),
            )
        return cursor.rowcount == 1

    # ── achievements & stats ────────────────────────────────────────────

    def achievements_of(self, user_id: int) -> set[str]:
        return {
            row[0]
            for row in self.db.execute(
                "SELECT code FROM achievements WHERE user_id = ?", (user_id,)
            )
        }

    def grant_achievement(self, user_id: int, code: str, now: int) -> bool:
        with self.db:
            cursor = self.db.execute(
                "INSERT OR IGNORE INTO achievements (user_id, code, earned_at) VALUES (?, ?, ?)",
                (user_id, code, now),
            )
        return cursor.rowcount == 1

    def user_stats(self, user_id: int, night_hours_utc: Sequence[int]) -> UserStats:
        pics = self.db.execute(
            """
            SELECT COUNT(*) AS uploads,
                   COALESCE(SUM(likes), 0) AS likes,
                   COALESCE(SUM(dislikes), 0) AS dislikes,
                   COALESCE(SUM(status = 'executed'), 0) AS executed,
                   COALESCE(SUM(status = 'alive'), 0) AS alive,
                   COALESCE(MAX(best_streak), 0) AS best_streak
            FROM pics WHERE added_by = ?
            """,
            (user_id,),
        ).fetchone()
        hours = list(night_hours_utc)
        night = self.db.execute(
            f"""
            SELECT COUNT(*) FROM pics
            WHERE added_by = ? AND added_at IS NOT NULL
              AND CAST(strftime('%H', added_at, 'unixepoch') AS INTEGER) IN ({_placeholders(hours)})
            """,
            (user_id, *hours),
        ).fetchone()[0]
        votes = self.db.execute(
            """
            SELECT COALESCE(SUM(vote = 'kill'), 0) AS kill, COALESCE(SUM(vote = 'spare'), 0) AS spare
            FROM court_votes WHERE user_id = ?
            """,
            (user_id,),
        ).fetchone()
        legends = self.db.execute(
            "SELECT COUNT(*) FROM (SELECT added_by FROM pics WHERE status = 'alive' "
            "AND (games + likes + dislikes) >= ? ORDER BY rating DESC LIMIT ?) WHERE added_by = ?",
            (MIN_EXPERIENCE, LEGEND_POOL_SIZE, user_id),
        ).fetchone()[0]
        return UserStats(
            uploads=pics["uploads"],
            night_uploads=night,
            likes_received=pics["likes"],
            dislikes_received=pics["dislikes"],
            pics_executed=pics["executed"],
            kill_votes=votes["kill"],
            spare_votes=votes["spare"],
            best_streak=pics["best_streak"],
            legends=legends,
            pics_alive=pics["alive"],
        )

    def top_users(self, board: str, limit: int = 10) -> list[tuple[int, int]]:
        queries = {
            "uploads": "SELECT added_by, COUNT(*) FROM pics WHERE added_by IS NOT NULL "
            "AND status != 'deleted' GROUP BY added_by",
            "loved": "SELECT added_by, SUM(likes) FROM pics WHERE added_by IS NOT NULL "
            "GROUP BY added_by HAVING SUM(likes) > 0",
            "killers": "SELECT user_id, COUNT(*) FROM court_votes WHERE vote = 'kill' "
            "GROUP BY user_id",
            "streaks": "SELECT added_by, MAX(best_streak) FROM pics WHERE added_by IS NOT NULL "
            "GROUP BY added_by HAVING MAX(best_streak) > 0",
        }
        rows = self.db.execute(
            f"SELECT * FROM ({queries[board]}) ORDER BY 2 DESC, 1 LIMIT ?", (limit,)
        ).fetchall()
        return [(row[0], row[1]) for row in rows]

    def totals(self) -> dict[str, int]:
        row = self.db.execute(
            """
            SELECT COALESCE(SUM(status = 'alive'), 0) AS alive,
                   COALESCE(SUM(status = 'executed'), 0) AS executed,
                   COALESCE(SUM(shown_count), 0) AS shows,
                   COALESCE(SUM(likes), 0) AS likes,
                   COALESCE(SUM(dislikes), 0) AS dislikes
            FROM pics
            """
        ).fetchone()
        return {key: row[key] for key in row.keys()}

    # ── chats & scheduled events ───────────────────────────────────────

    def touch_chat(self, chat_id: int, title: str | None, now: int) -> None:
        with self.db:
            self.db.execute(
                "INSERT INTO chats (chat_id, title, last_seen) VALUES (?, ?, ?) "
                "ON CONFLICT(chat_id) DO UPDATE SET title = excluded.title, last_seen = excluded.last_seen",
                (chat_id, title, now),
            )

    def seed_chats(self, now: int) -> None:
        """Groups known from earlier battles/panels, so events work before anyone writes again."""
        with self.db:
            self.db.execute(
                "INSERT OR IGNORE INTO chats (chat_id, last_seen) "
                "SELECT chat_id, ? FROM (SELECT chat_id FROM battles UNION SELECT chat_id FROM panels) "
                "WHERE chat_id < 0",
                (now,),
            )

    def event_chats(self, active_since: int) -> list[int]:
        return [
            row[0]
            for row in self.db.execute(
                "SELECT chat_id FROM chats WHERE events = 1 AND last_seen >= ?", (active_since,)
            )
        ]

    def chat_events_on(self, chat_id: int) -> bool:
        row = self.db.execute("SELECT events FROM chats WHERE chat_id = ?", (chat_id,)).fetchone()
        return bool(row[0]) if row else True

    def set_chat_events(self, chat_id: int, enabled: bool, now: int) -> None:
        with self.db:
            self.db.execute(
                "INSERT INTO chats (chat_id, events, last_seen) VALUES (?, ?, ?) "
                "ON CONFLICT(chat_id) DO UPDATE SET events = excluded.events",
                (chat_id, int(enabled), now),
            )

    def most_liked_since(self, since: int, exclude: Iterable[str] = ()) -> Pic | None:
        excluded = list(exclude)
        extra = f"AND p.id NOT IN ({_placeholders(excluded)})" if excluded else ""
        row = self.db.execute(
            f"""
            SELECT {', '.join('p.' + c.strip() for c in PIC_COLUMNS.split(','))}
            FROM reactions r JOIN pics p ON p.id = r.pic_id
            WHERE r.value = 1 AND r.at >= ? AND p.status = 'alive' {extra}
            GROUP BY p.id ORDER BY COUNT(*) DESC, p.rating DESC LIMIT 1
            """,
            (since, *excluded),
        ).fetchone()
        return _pic(row)

    def worst_triable(self, now: int) -> Pic | None:
        """Lowest-rated pic with some history that is not immune and not on trial."""
        row = self.db.execute(
            f"""
            SELECT {PIC_COLUMNS} FROM pics p
            WHERE status = 'alive' AND (games + likes + dislikes) >= ?
              AND (immune_until IS NULL OR immune_until <= ?)
              AND NOT EXISTS (SELECT 1 FROM courts c WHERE c.pic_id = p.id AND c.status = 'active')
            ORDER BY rating ASC, dislikes DESC LIMIT 1
            """,
            (MIN_EXPERIENCE, now),
        ).fetchone()
        return _pic(row)

    def week_summary(self, chat_id: int, since: int) -> dict:
        uploads = self.db.execute(
            "SELECT added_by, COUNT(*) FROM pics WHERE added_at >= ? AND added_by IS NOT NULL "
            "GROUP BY added_by ORDER BY 2 DESC LIMIT 3",
            (since,),
        ).fetchall()
        battles = self.db.execute(
            "SELECT COUNT(*), COALESCE(MAX(result_streak), 0) FROM battles "
            "WHERE chat_id = ? AND started_at >= ? AND status = 'done'",
            (chat_id, since),
        ).fetchone()
        executed = self.db.execute(
            "SELECT COUNT(*) FROM pics WHERE status = 'executed' AND removed_at >= ?", (since,)
        ).fetchone()[0]
        reactions = self.db.execute(
            "SELECT COALESCE(SUM(value = 1), 0), COALESCE(SUM(value = -1), 0) FROM reactions WHERE at >= ?",
            (since,),
        ).fetchone()
        return {
            "uploads": [(row[0], row[1]) for row in uploads],
            "battles": battles[0],
            "best_streak": battles[1],
            "executed": executed,
            "likes": reactions[0],
            "dislikes": reactions[1],
            "top_pic": self.most_liked_since(since),
        }

    # ── panels ──────────────────────────────────────────────────────────

    def panel_message(self, chat_id: int) -> int | None:
        row = self.db.execute(
            "SELECT message_id FROM panels WHERE chat_id = ?", (chat_id,)
        ).fetchone()
        return row[0] if row else None

    def set_panel_message(self, chat_id: int, message_id: int) -> None:
        with self.db:
            self.db.execute(
                "INSERT INTO panels (chat_id, message_id) VALUES (?, ?) "
                "ON CONFLICT(chat_id) DO UPDATE SET message_id = excluded.message_id",
                (chat_id, message_id),
            )

    # ── admin ───────────────────────────────────────────────────────────

    def reset_stats(self) -> None:
        with self.db:
            self.db.execute(
                "UPDATE pics SET rating = 1000, games = 0, wins = 0, losses = 0, loss_streak = 0, "
                "best_streak = 0, shown_count = 0, last_shown_at = NULL, likes = 0, dislikes = 0"
            )
            self.db.execute("DELETE FROM reactions")
            self.db.execute("DELETE FROM deck_seen")
            self.db.execute("DELETE FROM meta WHERE key != 'schema_version'")

    def export_backup(self, destination: Path) -> None:
        destination.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(destination) as backup:
            self.db.backup(backup)
        backup.close()
