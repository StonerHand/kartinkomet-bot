"""People's court and bounties on pics."""

import sqlite3
from uuid import uuid4

from bot.db.repo.models import Court


class CourtRepo:
    db: sqlite3.Connection

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
        appeal: bool = False,
        bail: int = 0,
    ) -> str:
        court_id = uuid4().hex[:16]
        with self.db:
            self.db.execute(
                "INSERT INTO courts (id, chat_id, pic_id, reason, started_by, started_at, ends_at, "
                "title, pic_message_id, appeal, bail) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
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
                    int(appeal),
                    bail,
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
            appeal=bool(row["appeal"]),
            bail=row["bail"],
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

    def add_bounty(self, pic_id: str, user_id: int, amount: int, now: int) -> int:
        with self.db:
            self.db.execute(
                "INSERT INTO bounties (pic_id, user_id, amount, at) VALUES (?, ?, ?, ?)",
                (pic_id, user_id, amount, now),
            )
        return self.bounty_on(pic_id)

    def bounty_on(self, pic_id: str) -> int:
        return self.db.execute(
            "SELECT COALESCE(SUM(amount), 0) FROM bounties WHERE pic_id = ?", (pic_id,)
        ).fetchone()[0]

    def take_bounty(self, pic_id: str) -> int:
        """Remove and return the whole bounty on a pic."""
        with self.db:
            total = self.db.execute(
                "SELECT COALESCE(SUM(amount), 0) FROM bounties WHERE pic_id = ?", (pic_id,)
            ).fetchone()[0]
            self.db.execute("DELETE FROM bounties WHERE pic_id = ?", (pic_id,))
        return total
