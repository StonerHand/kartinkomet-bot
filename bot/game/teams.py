"""The team week: a snake draft on Monday, the earned points of each colour, the result on Sunday."""

from dataclasses import dataclass

from bot.game.types import Granted
from bot.rules import teams


@dataclass(frozen=True)
class TeamWeek:
    week: int
    teams: dict[int, str]  # player → colour
    scores: dict[str, int]  # colour → points so far
    members: list[tuple[int, str, int]]  # (player, colour, points), best first


@dataclass(frozen=True)
class TeamResult:
    week: TeamWeek
    winner: str | None  # None: a tie
    bonus: int  # what each winner got
    granted: tuple[Granted, ...] = ()


class TeamsMixin:
    def _team_since(self, chat_id: int, week: int) -> int:
        return self.repo.meta_int(f"teams_since:{chat_id}:{week}")

    def draft_teams(self, chat_id: int) -> tuple[str, TeamWeek | None]:
        """'drafted' | 'already' | 'few'. Everyone who played in the chat lately, strongest
        first, goes into a snake draft."""
        week = self.local_week()
        if self.repo.teams_of(chat_id, week):
            return "already", self.team_week(chat_id)
        since = self.now() - teams.DRAFT_DAYS * 86400
        players = self.repo.recent_members(chat_id, since, limit=200)
        if len(players) < teams.MIN_PLAYERS:
            return "few", None
        earned = dict(self.repo.season_scores(since, self.now() + 1, limit=10_000))
        strongest = sorted(players, key=lambda user: (-earned.get(user, 0), user))
        self.repo.set_teams(chat_id, week, teams.draft(strongest, self.rng))
        self.repo.set_meta(f"teams_since:{chat_id}:{week}", self.now())
        return "drafted", self.team_week(chat_id)

    def team_week(self, chat_id: int, week: int | None = None) -> TeamWeek | None:
        """This week's teams (or a past week's) with their points; None if the chat has none."""
        current = self.local_week()
        week = current if week is None else week
        drafted = self.repo.teams_of(chat_id, week)
        if not drafted:
            return None
        since = self._team_since(chat_id, week)
        until = self.now() + 1 if week == current else since + teams.SPAN_SECONDS
        return TeamWeek(week, drafted, self.repo.team_scores(chat_id, week, since, until),
                        self.repo.team_members_scores(chat_id, week, since, until))

    def finish_teams(self, chat_id: int, week: int | None = None) -> TeamResult | None:
        """Sunday night: the colour with more points wins; each of its players gets BONUS and
        wears the win for a week. Only the first call settles. week: a past one the bot was down
        for on its Sunday, settled late on Monday."""
        current = self.team_week(chat_id, week)
        key = f"teams_done:{chat_id}:{current.week}" if current else ""
        if current is None or self.repo.meta_int(key):
            return None
        self.repo.set_meta(key, 1)
        winner = teams.winner(current.scores)
        bonus = 0
        winners = [user for user, colour in current.teams.items() if colour == winner]
        for user_id in winners:
            bonus = self.pay(user_id, teams.BONUS, "team")
            self.repo.set_badge(user_id, "team", "Победа в командной неделе", self.now() + teams.BADGE_SECONDS)
            self.repo.incr_counter(user_id, "team_weeks_won")
        return TeamResult(current, winner, bonus, tuple(self.check_achievements(winners)))
