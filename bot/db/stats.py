"""Achievements, player stats, tops and weekly crowns."""

import sqlite3
from collections.abc import Sequence

from bot.db.repo.models import UserStats, MIN_EXPERIENCE, LEGEND_POOL_SIZE, _placeholders


class StatsRepo:
    db: sqlite3.Connection

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

    def user_stats(
        self,
        user_id: int,
        night_hours_utc: Sequence[int],
        tz_offset_hours: int = 3,
        now: int = 0,
    ) -> UserStats:
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
        local_hour = f"(CAST(strftime('%H', added_at, 'unixepoch') AS INTEGER) + {tz_offset_hours}) % 24"
        extra = self.db.execute(
            f"""
            SELECT COALESCE(SUM({local_hour} BETWEEN 6 AND 7), 0) AS morning,
                   MIN(added_at) AS first_upload
            FROM pics WHERE added_by = ? AND added_at IS NOT NULL
            """,
            (user_id,),
        ).fetchone()
        hall_top10 = self.db.execute(
            "SELECT COUNT(*) FROM (SELECT added_by FROM pics WHERE status = 'alive' "
            "AND (games + likes + dislikes) >= ? ORDER BY rating DESC LIMIT 10) WHERE added_by = ?",
            (MIN_EXPERIENCE, user_id),
        ).fetchone()[0]
        given = self.db.execute(
            "SELECT COALESCE(SUM(value = 1), 0), COALESCE(SUM(value = -1), 0) FROM reactions WHERE user_id = ?",
            (user_id,),
        ).fetchone()
        player = self.player(user_id)
        first_upload = extra["first_upload"]
        married = self.db.execute("SELECT since FROM marriages WHERE user_id = ?", (user_id,)).fetchone()
        return UserStats(
            married_days=(now - married[0]) // 86400 if married and now else 0,
            morning_uploads=extra["morning"],
            days_since_first_upload=(now - first_upload) // 86400 if first_upload and now else 0,
            hall_top10=hall_top10,
            likes_given=given[0],
            dislikes_given=given[1],
            earned=player[1],
            counters=self.counters_of(user_id),
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

    WEEKLY_QUERIES = {
        "uploads": "SELECT added_by, COUNT(*) FROM pics WHERE added_by IS NOT NULL AND status != 'deleted' "
        "AND added_at >= :since GROUP BY added_by",
        "loved": "SELECT p.added_by, COUNT(*) FROM reactions r JOIN pics p ON p.id = r.pic_id "
        "WHERE r.value = 1 AND r.at >= :since AND p.added_by IS NOT NULL GROUP BY p.added_by",
        "killers": "SELECT v.user_id, COUNT(*) FROM court_votes v JOIN courts c ON c.id = v.court_id "
        "WHERE v.vote = 'kill' AND c.started_at >= :since GROUP BY v.user_id",
        "rich": "SELECT user_id, SUM(amount) FROM ledger WHERE at >= :since AND amount > 0 AND earn = 1 "
        "GROUP BY user_id",
    }

    def top_users(self, board: str, limit: int = 10, since: int | None = None) -> list[tuple[int, int]]:
        """Leaderboard rows (user, value). With `since`, boards that have a weekly variant count
        only what happened after it ("rich" then means coins earned by playing, not the balance)."""
        if since is not None and board in self.WEEKLY_QUERIES:
            rows = self.db.execute(
                f"SELECT * FROM ({self.WEEKLY_QUERIES[board]}) ORDER BY 2 DESC, 1 LIMIT :limit",
                {"since": since, "limit": limit},
            ).fetchall()
            return [(row[0], row[1]) for row in rows if row[1] > 0]
        queries = {
            "uploads": "SELECT added_by, COUNT(*) FROM pics WHERE added_by IS NOT NULL "
            "AND status != 'deleted' GROUP BY added_by",
            "loved": "SELECT added_by, SUM(likes) FROM pics WHERE added_by IS NOT NULL "
            "GROUP BY added_by HAVING SUM(likes) > 0",
            "killers": "SELECT user_id, COUNT(*) FROM court_votes WHERE vote = 'kill' "
            "GROUP BY user_id",
            "streaks": "SELECT added_by, MAX(best_streak) FROM pics WHERE added_by IS NOT NULL "
            "GROUP BY added_by HAVING MAX(best_streak) > 0",
            "rich": "SELECT user_id, coins FROM players WHERE coins > 0",
            "hl": "SELECT user_id, value FROM counters WHERE key = 'hl_best' AND value > 0",
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

    # ── usage for the admin screen ─────────────────────────────────────

    def track(self, name: str, day: int) -> None:
        """Count one use of a mechanic that leaves no other trace (a free wheel spin, a horoscope)."""
        self.incr_counter(0, f"use:{day}:{name}")  # type: ignore[attr-defined]

    def forget_usage(self, before_day: int) -> None:
        with self.db:
            for (key,) in self.db.execute("SELECT key FROM counters WHERE user_id = 0 AND key LIKE 'use:%'").fetchall():
                if int(key.split(":")[1]) < before_day:
                    self.db.execute("DELETE FROM counters WHERE user_id = 0 AND key = ?", (key,))

    def usage(self, since: int, day_start: int, since_day: int) -> dict[str, int]:
        """How the chat played since `since`: players, uploads and every mechanic."""
        one = lambda query, *params: self.db.execute(query, params).fetchone()[0] or 0  # noqa: E731
        stats = {
            "players_week": one(
                "SELECT COUNT(DISTINCT user_id) FROM (SELECT user_id FROM ledger WHERE at >= ? AND earn = 1 "
                "UNION SELECT user_id FROM reactions WHERE at >= ?)", since, since,
            ),
            "players_today": one(
                "SELECT COUNT(DISTINCT user_id) FROM (SELECT user_id FROM ledger WHERE at >= ? AND earn = 1 "
                "UNION SELECT user_id FROM reactions WHERE at >= ?)", day_start, day_start,
            ),
            "uploads": one("SELECT COUNT(*) FROM pics WHERE added_at >= ?", since),
            "likes": one("SELECT COUNT(*) FROM reactions WHERE at >= ? AND value = 1", since),
            "duels": one("SELECT COUNT(*) FROM battles WHERE started_at >= ? AND kind = 'duel' AND mode = ''", since),
            "tournaments": one("SELECT COUNT(*) FROM battles WHERE started_at >= ? AND kind = 'tournament'", since),
            "challenges": one("SELECT COUNT(*) FROM challenges WHERE created_at >= ? AND game = ''", since),
            "dice_duels": one("SELECT COUNT(*) FROM challenges WHERE created_at >= ? AND game != ''", since),
            "courts": one("SELECT COUNT(*) FROM courts WHERE started_at >= ?", since),
            "bosses": one("SELECT COUNT(*) FROM bosses WHERE started_at >= ? AND raid = 0", since),
            "bosses_won": one("SELECT COUNT(*) FROM bosses WHERE started_at >= ? AND status = 'won'", since),
            "raids": one("SELECT COUNT(*) FROM bosses WHERE started_at >= ? AND raid = 1", since),
            "captions": one("SELECT COUNT(*) FROM games WHERE created_at >= ? AND kind = 'caption'", since),
            "whose": one("SELECT COUNT(*) FROM games WHERE created_at >= ? AND kind = 'whose'", since),
            "casino": one("SELECT COUNT(*) FROM ledger WHERE at >= ? AND reason = 'casino_bet'", since),
            "purchases": one("SELECT COUNT(*) FROM ledger WHERE at >= ? AND reason LIKE 'shop_%' AND amount < 0", since),
            "robberies": one("SELECT COUNT(*) FROM ledger WHERE at >= ? AND reason IN ('rob', 'rob_fine') AND amount > 0", since),
            "gifts": one("SELECT COUNT(*) FROM ledger WHERE at >= ? AND reason = 'gift' AND amount > 0", since),
            "daily": one("SELECT COUNT(*) FROM ledger WHERE at >= ? AND reason = 'daily'", since),
        }
        for key, value in self.db.execute("SELECT key, value FROM counters WHERE user_id = 0 AND key LIKE 'use:%'"):
            _, day, name = key.split(":", 2)
            if int(day) >= since_day:
                stats[name] = stats.get(name, 0) + value
        return stats
