"""Group chats and the data scheduled events need."""

import sqlite3
from collections.abc import Iterable

from bot.db.repo.models import Pic, PIC_COLUMNS, MIN_EXPERIENCE, _pic, _placeholders


class ChatsRepo:
    db: sqlite3.Connection

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

    def touch_member(self, chat_id: int, user_id: int, now: int) -> None:
        with self.db:
            self.db.execute(
                "INSERT INTO chat_members (chat_id, user_id, last_seen) VALUES (?, ?, ?) "
                "ON CONFLICT(chat_id, user_id) DO UPDATE SET last_seen = excluded.last_seen",
                (chat_id, user_id, now),
            )

    def recent_members(self, chat_id: int, since: int, exclude: Iterable[int] = (), limit: int = 8) -> list[int]:
        """The chat's players, the most recently seen first."""
        skip = list(exclude)
        but = f"AND user_id NOT IN ({_placeholders(skip)}) " if skip else ""  # NOT IN (NULL) would match nobody
        return [
            row[0]
            for row in self.db.execute(
                f"SELECT user_id FROM chat_members WHERE chat_id = ? AND last_seen >= ? {but}"
                "ORDER BY last_seen DESC LIMIT ?",
                (chat_id, since, *skip, limit),
            )
        ]

    def find_member(self, chat_id: int, name: str) -> int | None:
        """A person by username, or by first or full name among the chat's players (the most
        recently seen wins a tie). Case doesn't matter, nor does a leading @."""
        clean = name.strip().lstrip("@").casefold()
        if not clean:
            return None
        row = self.db.execute("SELECT user_id FROM users WHERE lower(username) = ? LIMIT 1", (clean,)).fetchone()
        if row is not None:  # usernames are ASCII, so SQLite's lower() is enough for them
            return row[0]
        for row in self.db.execute(
            "SELECT u.user_id, u.first_name, u.last_name FROM chat_members m JOIN users u ON u.user_id = m.user_id "
            "WHERE m.chat_id = ? ORDER BY m.last_seen DESC",
            (chat_id,),
        ):
            first = (row["first_name"] or "").casefold()
            full = " ".join(part for part in (row["first_name"], row["last_name"]) if part).casefold()
            if clean in (first, full):
                return row["user_id"]
        return None

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
