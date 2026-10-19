"""Pics: storage, the deck, reactions, removal and revival."""

import sqlite3
from collections.abc import Iterable, Sequence
from uuid import uuid4

from bot.db.repo.models import Pic, PIC_COLUMNS, MIN_EXPERIENCE, LEGEND_POOL_SIZE, _pic, _placeholders


class PicsRepo:
    db: sqlite3.Connection

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

    def react(self, pic_id: str, user_id: int, value: int, now: int) -> int | None:
        """Set a user's reaction. Returns the previous value (0 = none), or None if unchanged."""
        row = self.db.execute(
            "SELECT value FROM reactions WHERE pic_id = ? AND user_id = ?",
            (pic_id, user_id),
        ).fetchone()
        previous = row["value"] if row else 0
        if previous == value:
            return None
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
        return previous

    def reaction_count(self, pic_id: str) -> int:
        return self.db.execute("SELECT COUNT(*) FROM reactions WHERE pic_id = ?", (pic_id,)).fetchone()[0]

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

    def take_counter(self, user_id: int, key: str) -> bool:
        """Decrement a counter if it's above zero (spending an inventory item). Atomic."""
        with self.db:
            cursor = self.db.execute(
                "UPDATE counters SET value = value - 1 WHERE user_id = ? AND key = ? AND value > 0",
                (user_id, key),
            )
        return cursor.rowcount == 1

    def forget_counters(self, prefix: str, keep_prefix: str) -> None:
        """Drop old per-day/per-week progress counters: keys starting with `prefix` but not
        with `keep_prefix` (the current day or week)."""
        with self.db:
            self.db.execute(
                "DELETE FROM counters WHERE key LIKE ? AND key NOT LIKE ?", (f"{prefix}%", f"{keep_prefix}%")
            )

    def forget_meta(self, prefix: str) -> None:
        with self.db:
            self.db.execute("DELETE FROM meta WHERE key LIKE ?", (f"{prefix}%",))

    def balances(self) -> list[tuple[int, int]]:
        return [(row[0], row[1]) for row in self.db.execute("SELECT user_id, coins FROM players")]

    def active_players(self, since: int) -> int:
        """People who did anything paid (votes, likes, games) since a time."""
        return self.db.execute(
            "SELECT COUNT(DISTINCT user_id) FROM ledger WHERE at >= ? AND earn = 1", (since,)
        ).fetchone()[0]

    def pics_of(self, owner_id: int, limit: int = 3, weakest: bool = False) -> list:
        order = "ASC" if weakest else "DESC"
        rows = self.db.execute(
            f"SELECT id FROM pics WHERE added_by = ? AND status = 'alive' ORDER BY rating {order}, id LIMIT ?",
            (owner_id, limit),
        ).fetchall()
        return [self.get_pic(row[0]) for row in rows]  # type: ignore[attr-defined]

    def set_rating(self, pic_id: str, rating: float) -> None:
        with self.db:
            self.db.execute("UPDATE pics SET rating = ? WHERE id = ?", (rating, pic_id))

    def user_by_name(self, name: str) -> int | None:
        clean = name.strip().lstrip("@").casefold()
        if not clean:
            return None
        row = self.db.execute(
            "SELECT user_id FROM users WHERE lower(username) = ? LIMIT 1", (clean,)
        ).fetchone()
        return row[0] if row else None
