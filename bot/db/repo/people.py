"""Marriages, proposals and custom titles."""

import sqlite3
from uuid import uuid4


class PeopleRepo:
    db: sqlite3.Connection

    def spouse_of(self, user_id: int) -> tuple[int, int] | None:
        """(spouse, since)."""
        row = self.db.execute("SELECT spouse_id, since FROM marriages WHERE user_id = ?", (user_id,)).fetchone()
        return (row[0], row[1]) if row else None

    def marry(self, first: int, second: int, now: int) -> bool:
        try:
            with self.db:
                self.db.execute("INSERT INTO marriages (user_id, spouse_id, since) VALUES (?, ?, ?)", (first, second, now))
                self.db.execute("INSERT INTO marriages (user_id, spouse_id, since) VALUES (?, ?, ?)", (second, first, now))
        except sqlite3.IntegrityError:
            return False
        return True

    def divorce(self, user_id: int) -> int | None:
        spouse = self.spouse_of(user_id)
        if spouse is None:
            return None
        with self.db:
            self.db.execute("DELETE FROM marriages WHERE user_id IN (?, ?)", (user_id, spouse[0]))
        return spouse[0]

    def create_proposal(self, chat_id: int, from_user: int, to_user: int, now: int) -> str:
        proposal_id = uuid4().hex[:12]
        with self.db:
            self.db.execute(
                "INSERT INTO proposals (id, chat_id, from_user, to_user, created_at) VALUES (?, ?, ?, ?, ?)",
                (proposal_id, chat_id, from_user, to_user, now),
            )
        return proposal_id

    def get_proposal(self, proposal_id: str) -> dict | None:
        row = self.db.execute("SELECT * FROM proposals WHERE id = ?", (proposal_id,)).fetchone()
        return dict(row) if row else None

    def close_proposal(self, proposal_id: str, status: str) -> bool:
        with self.db:
            cursor = self.db.execute(
                "UPDATE proposals SET status = ? WHERE id = ? AND status = 'pending'", (status, proposal_id)
            )
        return cursor.rowcount == 1

    def title_of(self, user_id: int) -> str | None:
        row = self.db.execute("SELECT title FROM titles WHERE user_id = ?", (user_id,)).fetchone()
        return row[0] if row else None

    def set_title(self, user_id: int, title: str) -> None:
        with self.db:
            self.db.execute(
                "INSERT INTO titles (user_id, title) VALUES (?, ?) ON CONFLICT(user_id) DO UPDATE SET title = excluded.title",
                (user_id, title),
            )
