"""Seasons, chat wealth and the monthly coin reset."""

import sqlite3


class SeasonsRepo:
    db: sqlite3.Connection

    def season_scores(self, start: int, end: int, limit: int = 10) -> list[tuple[int, int]]:
        """(user, coins earned by taking part) for the season, best first."""
        rows = self.db.execute(
            "SELECT user_id, SUM(amount) FROM ledger WHERE at >= ? AND at < ? AND earn = 1 AND amount > 0 "
            "GROUP BY user_id ORDER BY 2 DESC, 1 LIMIT ?",
            (start, end, limit),
        ).fetchall()
        return [(row[0], row[1]) for row in rows]

    def season_standing(self, user_id: int, start: int, end: int) -> tuple[int, int | None]:
        """(score, place) of one player; place is None with no score yet."""
        scores = self.season_scores(start, end, limit=10_000)
        for place, (user, score) in enumerate(scores, start=1):
            if user == user_id:
                return score, place
        return 0, None

    def save_podium(self, season: str, podium: list[tuple[int, int]]) -> None:
        with self.db:
            for place, (user_id, score) in enumerate(podium, start=1):
                self.db.execute(
                    "INSERT OR IGNORE INTO seasons (season, place, user_id, score) VALUES (?, ?, ?, ?)",
                    (season, place, user_id, score),
                )

    def podiums(self, limit: int = 12) -> list[tuple[str, list[tuple[int, int]]]]:
        """Finished seasons, latest first: (season, [(user, score) by place])."""
        seasons = [
            row[0] for row in self.db.execute(
                "SELECT DISTINCT season FROM seasons ORDER BY season DESC LIMIT ?", (limit,)
            )
        ]
        result = []
        for season in seasons:
            rows = self.db.execute(
                "SELECT user_id, score FROM seasons WHERE season = ? ORDER BY place", (season,)
            ).fetchall()
            result.append((season, [(row[0], row[1]) for row in rows]))
        return result

    def podiums_of(self, user_id: int) -> list[tuple[str, int]]:
        """(season, place) of every podium this player stood on, latest first."""
        rows = self.db.execute(
            "SELECT season, place FROM seasons WHERE user_id = ? ORDER BY season DESC", (user_id,)
        ).fetchall()
        return [(row[0], row[1]) for row in rows]

    def active_wallets(self, since: int) -> list[tuple[int, int]]:
        """(player, coins) of everyone who earned anything since `since`, admins included."""
        return [
            (row[0], row[1])
            for row in self.db.execute(
                "SELECT user_id, coins FROM players WHERE user_id IN "
                "(SELECT DISTINCT user_id FROM ledger WHERE at >= ? AND earn = 1) ORDER BY user_id",
                (since,),
            )
        ]

    def money_pool(self, since: int) -> tuple[int, int]:
        """(coins, players) of everyone who earned anything since `since`, admins included."""
        row = self.db.execute(
            "SELECT COALESCE(SUM(p.coins), 0), COUNT(*) FROM players p WHERE p.user_id IN "
            "(SELECT DISTINCT user_id FROM ledger WHERE at >= ? AND earn = 1)",
            (since,),
        ).fetchone()
        return row[0], row[1]

    def reset_coins(self, to: int, keep: frozenset[int] | set[int], reason: str, now: int) -> int:
        """Set every balance to `to`, except the players in `keep`. Each change goes to the ledger
        (earn = 0: a reset is neither income nor a level). Returns how many balances changed."""
        changed = 0
        with self.db:
            rows = self.db.execute("SELECT user_id, coins FROM players").fetchall()
            for user_id, coins in rows:
                if user_id in keep or coins == to:
                    continue
                self.db.execute("UPDATE players SET coins = ? WHERE user_id = ?", (to, user_id))
                self.db.execute(
                    "INSERT INTO ledger (user_id, amount, reason, at, earn) VALUES (?, ?, ?, ?, 0)",
                    (user_id, to - coins, reason, now),
                )
                changed += 1
        return changed
