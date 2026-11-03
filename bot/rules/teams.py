"""The team week: on Monday the chat splits in two, on Sunday night the team that earned more
wins. A team's score is what its members earned by playing (the season's points), so every game
counts without telling the teams about it."""

import random

TEAMS = ("red", "blue")
START = (0, 10)  # Monday 10:00 local: the draft
END = (6, 22)  # Sunday 22:00 local: the result
SPAN_SECONDS = (END[0] - START[0]) * 86400 + (END[1] - START[1]) * 3600  # from the draft to the result
MIN_PLAYERS = 4
BONUS = 300  # base coins to each member of the winning team
BADGE_SECONDS = 7 * 86400  # the winners wear it till the next result
DRAFT_DAYS = 14  # who gets a team: everyone the chat saw play in two weeks


def draft(players: list[int], rng: random.Random) -> dict[int, str]:
    """players: strongest first (by what they earned lately). A snake draft — A B B A A B B A … —
    keeps the teams even; a coin toss says which colour picks first."""
    first, second = TEAMS if rng.random() < 0.5 else TEAMS[::-1]
    order = (first, second, second, first)
    return {player: order[index % 4] for index, player in enumerate(players)}


def winner(scores: dict[str, int]) -> str | None:
    """The team with more points; a tie has no winner."""
    red, blue = scores.get("red", 0), scores.get("blue", 0)
    if red == blue:
        return None
    return "red" if red > blue else "blue"
