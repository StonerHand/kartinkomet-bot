"""Games about the people in the chat: rounds (polls, bombs, bets), their votes, day-long badges."""

import sqlite3
from uuid import uuid4


class PartyRepo:
    db: sqlite3.Connection

    def create_round(
        self, chat_id: int, kind: str, now: int, ends_at: int, author: int | None = None, text: str = "",
        options: list[int] = (), holder: int | None = None, fuse_at: int | None = None,
    ) -> str:
        round_id = uuid4().hex[:12]
        with self.db:
            self.db.execute(
                "INSERT INTO rounds (id, chat_id, kind, ends_at, author, text, options, holder, fuse_at, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (round_id, chat_id, kind, ends_at, author, text, ",".join(map(str, options)), holder, fuse_at, now),
            )
        return round_id

    def get_round(self, round_id: str) -> dict | None:
        row = self.db.execute("SELECT * FROM rounds WHERE id = ?", (round_id,)).fetchone()
        if row is None:
            return None
        found = dict(row)
        found["options"] = [int(part) for part in found["options"].split(",") if part]
        found["votes"] = {
            user: (choice, stake)
            for user, choice, stake in self.db.execute(
                "SELECT user_id, choice, stake FROM round_votes WHERE round_id = ? ORDER BY user_id", (round_id,)
            )
        }
        return found

    def open_rounds(self, chat_id: int, kind: str) -> list[dict]:
        return [self.get_round(row[0]) for row in self.db.execute(
            "SELECT id FROM rounds WHERE chat_id = ? AND kind = ? AND status = 'open' ORDER BY created_at",
            (chat_id, kind),
        )]

    def open_round_ids(self, kinds: tuple[str, ...]) -> list[str]:
        marks = ", ".join("?" for _ in kinds)
        return [row[0] for row in self.db.execute(
            f"SELECT id FROM rounds WHERE status = 'open' AND kind IN ({marks}) ORDER BY created_at", kinds
        )]

    def due_rounds(self, kind: str, now: int) -> list[str]:
        return [row[0] for row in self.db.execute(
            "SELECT id FROM rounds WHERE status = 'open' AND kind = ? AND ends_at <= ?", (kind, now)
        )]

    def last_round_at(self, chat_id: int, kind: str) -> int:
        row = self.db.execute(
            "SELECT MAX(created_at) FROM rounds WHERE chat_id = ? AND kind = ?", (chat_id, kind)
        ).fetchone()
        return row[0] or 0

    def set_round_message(self, round_id: str, message_id: int) -> None:
        with self.db:
            self.db.execute("UPDATE rounds SET message_id = ? WHERE id = ?", (message_id, round_id))

    def drop_round(self, round_id: str) -> None:
        with self.db:
            self.db.execute("DELETE FROM rounds WHERE id = ?", (round_id,))

    def hand_over(self, round_id: str, holder: int, to: int, ends_at: int) -> bool:
        """The bomb changes hands, only if `holder` still has it."""
        with self.db:
            cursor = self.db.execute(
                "UPDATE rounds SET holder = ?, ends_at = ? WHERE id = ? AND holder = ? AND status = 'open'",
                (to, ends_at, round_id, holder),
            )
        return cursor.rowcount == 1

    def close_round(self, round_id: str, result: int | None) -> bool:
        """Only the first call closes it."""
        with self.db:
            cursor = self.db.execute(
                "UPDATE rounds SET status = 'done', result = ? WHERE id = ? AND status = 'open'", (result, round_id)
            )
        return cursor.rowcount == 1

    def put_round_vote(self, round_id: str, user_id: int, choice: int, stake: int = 0, replace: bool = True) -> bool:
        """replace=False keeps the first vote: False when the user had one already."""
        if not replace:
            with self.db:
                cursor = self.db.execute(
                    "INSERT OR IGNORE INTO round_votes (round_id, user_id, choice, stake) VALUES (?, ?, ?, ?)",
                    (round_id, user_id, choice, stake),
                )
            return cursor.rowcount == 1
        with self.db:
            self.db.execute(
                "INSERT INTO round_votes (round_id, user_id, choice, stake) VALUES (?, ?, ?, ?) "
                "ON CONFLICT(round_id, user_id) DO UPDATE SET choice = excluded.choice, stake = excluded.stake",
                (round_id, user_id, choice, stake),
            )
        return True

    def set_badge(self, user_id: int, kind: str, text: str, until: int) -> None:
        with self.db:
            self.db.execute(
                "INSERT INTO badges (user_id, kind, text, until) VALUES (?, ?, ?, ?) "
                "ON CONFLICT(user_id, kind) DO UPDATE SET text = excluded.text, until = excluded.until",
                (user_id, kind, text, until),
            )

    def badges_of(self, user_id: int, now: int) -> list[tuple[str, str, int]]:
        """(kind, text, until) of the badges the user wears now."""
        return [tuple(row) for row in self.db.execute(
            "SELECT kind, text, until FROM badges WHERE user_id = ? AND until > ? ORDER BY kind", (user_id, now)
        )]
