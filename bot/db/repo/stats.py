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

    def top_users(self, board: str, limit: int = 10) -> list[tuple[int, int]]:
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
