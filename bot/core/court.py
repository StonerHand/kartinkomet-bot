"""People's court 2.0 rules."""

COURT_SECONDS = 60
DISLIKES_FOR_COURT = 2
MIN_KILL_VOTES = 2
IMMUNITY_SECONDS = 7 * 24 * 3600
LAST_WORD_LIMIT = 300


def verdict(kill_votes: int, spare_votes: int) -> str:
    """'executed' needs a strict majority and at least MIN_KILL_VOTES. Ties spare."""
    if kill_votes >= MIN_KILL_VOTES and kill_votes > spare_votes:
        return "executed"
    return "pardoned"


def can_be_tried(status: str, immune_until: int | None, now: int) -> bool:
    return status == "alive" and (immune_until is None or immune_until <= now)


def dislikes_trigger_court(previous_dislikes: int, dislikes: int) -> bool:
    """Fire exactly when the dislike count reaches the threshold (or a new multiple of it)."""
    return dislikes > previous_dislikes and dislikes >= DISLIKES_FOR_COURT and (
        dislikes % DISLIKES_FOR_COURT == 0
    )
