"""People's court 2.0 rules."""

COURT_SECONDS = 60
DISLIKES_FOR_COURT = 2
MIN_KILL_VOTES = 2
IMMUNITY_SECONDS = 7 * 24 * 3600
LAST_WORD_LIMIT = 300


# Appeal: the uploader pays bail within APPEAL_WINDOW after an execution and gets a second,
# stricter trial. Won — bail back and immunity. Lost — bail burns, the verdict is final.
APPEAL_BAIL = 200
APPEAL_WINDOW = 300
APPEAL_SECONDS = 90
APPEAL_MIN_KILL_VOTES = 3


def verdict(kill_votes: int, spare_votes: int, appeal: bool = False) -> str:
    """'executed' needs a strict majority and at least MIN_KILL_VOTES (3 on appeal). Ties spare."""
    needed = APPEAL_MIN_KILL_VOTES if appeal else MIN_KILL_VOTES
    if kill_votes >= needed and kill_votes > spare_votes:
        return "executed"
    return "pardoned"


def can_be_tried(status: str, immune_until: int | None, now: int) -> bool:
    return status == "alive" and (immune_until is None or immune_until <= now)


def dislikes_trigger_court(previous_dislikes: int, dislikes: int, threshold: int = DISLIKES_FOR_COURT) -> bool:
    """Fire exactly when the dislike count reaches the threshold (or a new multiple of it)."""
    return dislikes > previous_dislikes and dislikes >= threshold and dislikes % threshold == 0
