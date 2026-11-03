"""The team week: who plays for which colour, and what each colour has earned."""

import sqlite3


class TeamsRepo:
    db: sqlite3.Connection

    def set_teams(self, chat_id: int, week: int, teams: dict[int, str]) -> None:
        with self.db:
            self.db.executemany(
                "INSERT OR REPLACE INTO teams (chat_id, week, user_id, team) VALUES (?, ?, ?, ?)",
                [(chat_id, week, user_id, team) for user_id, team in teams.items()],
            )

    def teams_of(self, chat_id: int, week: int) -> dict[int, str]:
        return {row[0]: row[1] for row in self.db.execute(
            "SELECT user_id, team FROM teams WHERE chat_id = ? AND week = ? ORDER BY user_id", (chat_id, week)
        )}

    def team_scores(self, chat_id: int, week: int, since: int, until: int) -> dict[str, int]:
        """Team → coins its members earned by playing in [since, until): the season's points."""
        rows = self.db.execute(
            "SELECT t.team, COALESCE(SUM(l.amount), 0) FROM teams t LEFT JOIN ledger l ON l.user_id = t.user_id "
            "AND l.earn = 1 AND l.amount > 0 AND l.at >= ? AND l.at < ? WHERE t.chat_id = ? AND t.week = ? "
            "GROUP BY t.team",
            (since, until, chat_id, week),
        ).fetchall()
        return {row[0]: row[1] for row in rows}

    def team_members_scores(self, chat_id: int, week: int, since: int, until: int) -> list[tuple[int, str, int]]:
        """(player, team, points) of the week, best first."""
        rows = self.db.execute(
            "SELECT t.user_id, t.team, COALESCE(SUM(l.amount), 0) FROM teams t LEFT JOIN ledger l "
            "ON l.user_id = t.user_id AND l.earn = 1 AND l.amount > 0 AND l.at >= ? AND l.at < ? "
            "WHERE t.chat_id = ? AND t.week = ? GROUP BY t.user_id, t.team ORDER BY 3 DESC, 1",
            (since, until, chat_id, week),
        ).fetchall()
        return [(row[0], row[1], row[2]) for row in rows]
