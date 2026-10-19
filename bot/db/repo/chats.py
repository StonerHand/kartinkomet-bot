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
