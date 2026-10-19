"""Duels, tournaments, player challenges and bets on them."""

import sqlite3
from collections.abc import Sequence
from uuid import uuid4

from bot.db.repo.models import Battle, PIC_COLUMNS, _pic


class ArenaRepo:
    db: sqlite3.Connection

    def create_battle(
        self,
        kind: str,
        chat_id: int,
        pic_ids: Sequence[str],
        now: int,
        duration: int,
        streak: int = 0,
        title: str = "",
        mode: str = "",
    ) -> str:
        battle_id = uuid4().hex[:16]
        with self.db:
            self.db.execute(
                "INSERT INTO battles (id, chat_id, kind, started_at, ends_at, streak, title, mode) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (battle_id, chat_id, kind, now, now + duration, streak, title, mode),
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
            mode=row["mode"],
            bets={
                bet["user_id"]: (bet["slot"], bet["amount"])
                for bet in self.db.execute(
                    "SELECT user_id, slot, amount FROM battle_bets WHERE battle_id = ?", (battle_id,)
                )
            },
        )

    def active_battle(self, chat_id: int, kind: str, mode: str = "") -> Battle | None:
        row = self.db.execute(
            "SELECT id FROM battles WHERE status = 'active' AND chat_id = ? AND kind = ? AND mode = ? "
            "ORDER BY started_at DESC LIMIT 1",
            (chat_id, kind, mode),
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

    def place_bet(self, battle_id: str, user_id: int, slot: int, amount: int) -> None:
        with self.db:
            self.db.execute(
                "INSERT INTO battle_bets (battle_id, user_id, slot, amount) VALUES (?, ?, ?, ?) "
                "ON CONFLICT(battle_id, user_id) DO UPDATE SET amount = amount + excluded.amount",
                (battle_id, user_id, slot, amount),
            )

    def create_challenge(
        self, chat_id: int, from_user: int, to_user: int | None, stake: int, now: int, expires_at: int
    ) -> str:
        challenge_id = uuid4().hex[:12]
        with self.db:
            self.db.execute(
                "INSERT INTO challenges (id, chat_id, from_user, to_user, stake, created_at, expires_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (challenge_id, chat_id, from_user, to_user, stake, now, expires_at),
            )
        return challenge_id

    def get_challenge(self, challenge_id: str) -> dict | None:
        row = self.db.execute("SELECT * FROM challenges WHERE id = ?", (challenge_id,)).fetchone()
        return dict(row) if row else None

    def challenge_for_battle(self, battle_id: str) -> dict | None:
        row = self.db.execute("SELECT * FROM challenges WHERE battle_id = ?", (battle_id,)).fetchone()
        return dict(row) if row else None

    def pending_challenge_of(self, user_id: int) -> dict | None:
        row = self.db.execute(
            "SELECT * FROM challenges WHERE from_user = ? AND status = 'pending' LIMIT 1", (user_id,)
        ).fetchone()
        return dict(row) if row else None

    def pending_challenge_ids(self) -> list[str]:
        return [row[0] for row in self.db.execute("SELECT id FROM challenges WHERE status = 'pending'")]

    def set_challenge_message(self, challenge_id: str, message_id: int) -> None:
        with self.db:
            self.db.execute("UPDATE challenges SET message_id = ? WHERE id = ?", (message_id, challenge_id))

    def close_challenge(self, challenge_id: str, status: str, battle_id: str | None = None) -> bool:
        """pending → status, atomically. False if someone got there first."""
        with self.db:
            cursor = self.db.execute(
                "UPDATE challenges SET status = ?, battle_id = COALESCE(?, battle_id) "
                "WHERE id = ? AND status = 'pending'",
                (status, battle_id, challenge_id),
            )
        return cursor.rowcount == 1

    def accept_challenge(self, challenge_id: str, opponent: int) -> bool:
        with self.db:
            cursor = self.db.execute(
                "UPDATE challenges SET status = 'accepted', to_user = ? WHERE id = ? AND status = 'pending'",
                (opponent, challenge_id),
            )
        return cursor.rowcount == 1

    def active_challenge_battle(self, chat_id: int) -> str | None:
        row = self.db.execute(
            "SELECT id FROM battles WHERE chat_id = ? AND mode = 'challenge' AND status = 'active' LIMIT 1",
            (chat_id,),
        ).fetchone()
        return row[0] if row else None

    def set_challenge_battle(self, challenge_id: str, battle_id: str) -> None:
        with self.db:
            self.db.execute("UPDATE challenges SET battle_id = ? WHERE id = ?", (battle_id, challenge_id))
