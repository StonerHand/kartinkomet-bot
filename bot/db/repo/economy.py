"""Coins, the ledger and per-player counters."""

import sqlite3


class EconomyRepo:
    db: sqlite3.Connection

    def player(self, user_id: int) -> tuple[int, int, int]:
        """(coins, earned, level_seen)."""
        row = self.db.execute(
            "SELECT coins, earned, level_seen FROM players WHERE user_id = ?", (user_id,)
        ).fetchone()
        return (row[0], row[1], row[2]) if row else (0, 0, 0)

    def add_coins(self, user_id: int, amount: int, reason: str, now: int, earn: bool = True) -> int:
        """Change the balance (never below zero). Gains count towards the level only with `earn`:
        casino wins, transfers and bonuses move coins without levelling anyone up."""
        with self.db:
            self.db.execute(
                "INSERT INTO players (user_id) VALUES (?) ON CONFLICT(user_id) DO NOTHING", (user_id,)
            )
            self.db.execute(
                "UPDATE players SET coins = MAX(0, coins + ?), earned = earned + MAX(0, ?) WHERE user_id = ?",
                (amount, amount if earn else 0, user_id),
            )
            self.db.execute(
                "INSERT INTO ledger (user_id, amount, reason, at, earn) VALUES (?, ?, ?, ?, ?)",
                (user_id, amount, reason, now, int(earn)),
            )
        return self.player(user_id)[0]

    def spend(self, user_id: int, amount: int, reason: str, now: int) -> bool:
        """Take coins only if the whole amount is there. Atomic: two taps can't overspend."""
        if amount <= 0:
            return True
        with self.db:
            cursor = self.db.execute(
                "UPDATE players SET coins = coins - ? WHERE user_id = ? AND coins >= ?",
                (amount, user_id, amount),
            )
            if cursor.rowcount != 1:
                return False
            self.db.execute(
                "INSERT INTO ledger (user_id, amount, reason, at, earn) VALUES (?, ?, ?, ?, 0)",
                (user_id, -amount, reason, now),
            )
        return True

    def set_level_seen(self, user_id: int, level: int) -> None:
        with self.db:
            self.db.execute(
                "INSERT INTO players (user_id, level_seen) VALUES (?, ?) "
                "ON CONFLICT(user_id) DO UPDATE SET level_seen = excluded.level_seen",
                (user_id, level),
            )

    def counter(self, user_id: int, key: str) -> int:
        row = self.db.execute(
            "SELECT value FROM counters WHERE user_id = ? AND key = ?", (user_id, key)
        ).fetchone()
        return row[0] if row else 0

    def counters_of(self, user_id: int) -> dict[str, int]:
        return {
            row[0]: row[1]
            for row in self.db.execute("SELECT key, value FROM counters WHERE user_id = ?", (user_id,))
        }

    def set_counter(self, user_id: int, key: str, value: int) -> None:
        with self.db:
            self.db.execute(
                "INSERT INTO counters (user_id, key, value) VALUES (?, ?, ?) "
                "ON CONFLICT(user_id, key) DO UPDATE SET value = excluded.value",
                (user_id, key, value),
            )

    def incr_counter(self, user_id: int, key: str, by: int = 1) -> int:
        with self.db:
            self.db.execute(
                "INSERT INTO counters (user_id, key, value) VALUES (?, ?, ?) "
                "ON CONFLICT(user_id, key) DO UPDATE SET value = value + excluded.value",
                (user_id, key, by),
            )
        return self.counter(user_id, key)

    def raise_counter(self, user_id: int, key: str, value: int) -> None:
        """Keep the maximum (for 'best ever' counters)."""
        if value > self.counter(user_id, key):
            self.set_counter(user_id, key, value)

    def executed_since(self, owner_id: int, since: int) -> int:
        return self.db.execute(
            "SELECT COUNT(*) FROM pics WHERE added_by = ? AND status = 'executed' AND removed_at >= ?",
            (owner_id, since),
        ).fetchone()[0]

    def lost_before(self, winner_pic: str, loser_pic: str, before_battle: str) -> bool:
        """Did loser_pic beat winner_pic in an earlier finished duel? (for the revenge achievement)"""
        row = self.db.execute(
            """
            SELECT 1 FROM battles b
            JOIN battle_entries w ON w.battle_id = b.id AND w.pic_id = ?
            JOIN battle_entries l ON l.battle_id = b.id AND l.pic_id = ?
            WHERE b.kind = 'duel' AND b.status = 'done' AND b.id != ? AND b.winner_slot = l.slot
            LIMIT 1
            """,
            (winner_pic, loser_pic, before_battle),
        ).fetchone()
        return row is not None

    def nemesis(self, user_id: int) -> tuple[int, int] | None:
        """(owner, losses): whose pics beat this user's pics in duels most often (2+ times)."""
        row = self.db.execute(
            """
            SELECT pw.added_by, COUNT(*) FROM battles b
            JOIN battle_entries w ON w.battle_id = b.id AND w.slot = b.winner_slot
            JOIN battle_entries l ON l.battle_id = b.id AND l.slot != b.winner_slot
            JOIN pics pw ON pw.id = w.pic_id
            JOIN pics pl ON pl.id = l.pic_id
            WHERE b.kind = 'duel' AND b.status = 'done' AND pl.added_by = ?
              AND pw.added_by IS NOT NULL AND pw.added_by != ?
            GROUP BY pw.added_by HAVING COUNT(*) >= 2 ORDER BY 2 DESC LIMIT 1
            """,
            (user_id, user_id),
        ).fetchone()
        return (row[0], row[1]) if row else None

    def week_crowns(self, since: int) -> dict[str, tuple[int, int]]:
        """Weekly crown holders: kind → (user_id, score)."""
        queries = {
            "uploader": (
                "SELECT added_by, COUNT(*) FROM pics WHERE added_at >= ? AND added_by IS NOT NULL GROUP BY added_by",
                (since,),
            ),
            "executioner": (
                "SELECT v.user_id, COUNT(*) FROM court_votes v JOIN courts c ON c.id = v.court_id "
                "WHERE c.started_at >= ? AND v.vote = 'kill' GROUP BY v.user_id",
                (since,),
            ),
            "advocate": (
                "SELECT v.user_id, COUNT(*) FROM court_votes v JOIN courts c ON c.id = v.court_id "
                "WHERE c.started_at >= ? AND v.vote = 'spare' GROUP BY v.user_id",
                (since,),
            ),
            "oracle": (
                "SELECT user_id, COUNT(*) FROM ledger WHERE at >= ? AND reason = 'guess' GROUP BY user_id",
                (since,),
            ),
            "rich": (
                "SELECT user_id, SUM(amount) FROM ledger WHERE at >= ? AND amount > 0 AND earn = 1 GROUP BY user_id",
                (since,),
            ),
            "lucky": (
                "SELECT user_id, SUM(amount) FROM ledger WHERE at >= ? AND reason LIKE 'casino%' GROUP BY user_id",
                (since,),
            ),
        }
        crowns = {}
        for kind, (query, params) in queries.items():
            row = self.db.execute(f"SELECT * FROM ({query}) ORDER BY 2 DESC, 1 LIMIT 1", params).fetchone()
            if row and row[1] > 0:
                crowns[kind] = (row[0], row[1])
        return crowns

    def achievement_owners(self) -> dict[str, int]:
        return {
            row[0]: row[1]
            for row in self.db.execute("SELECT code, COUNT(*) FROM achievements GROUP BY code")
        }

    def casino_stats(self, user_id: int) -> tuple[int, int, int, int]:
        """(bets, coins staked, coins returned incl. refunds, biggest single payout)."""
        row = self.db.execute(
            """
            SELECT COALESCE(SUM(reason = 'casino_bet'), 0),
                   COALESCE(-SUM(CASE WHEN reason = 'casino_bet' THEN amount END), 0),
                   COALESCE(SUM(CASE WHEN reason IN ('casino_win', 'casino_refund') THEN amount END), 0),
                   COALESCE(MAX(CASE WHEN reason = 'casino_win' THEN amount END), 0)
            FROM ledger WHERE user_id = ? AND reason IN ('casino_bet', 'casino_win', 'casino_refund')
            """,
            (user_id,),
        ).fetchone()
        return row[0], row[1], row[2], row[3]
