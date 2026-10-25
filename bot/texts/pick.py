"""Phrase picking without short-term repeats."""

import random
import zlib
from collections import OrderedDict, deque
from collections.abc import Sequence

_RNG = random.SystemRandom()
# Least-recently-used memory per (scope, pool); capped so per-battle scopes can't grow forever.
MAX_SCOPES = 1024
_recent: OrderedDict[tuple[object, int], deque[int]] = OrderedDict()


def lines(block: str) -> tuple[str, ...]:
    """Turn a triple-quoted block into phrases: one per line, blank lines and # comments skipped."""
    return tuple(
        line.strip()
        for line in block.strip().splitlines()
        if line.strip() and not line.strip().startswith("#")
    )


def pick(pool: Sequence[str], scope: object = None) -> str:
    """Random phrase that wasn't used in this scope during the last half of the pool."""
    if not pool:
        return ""
    if len(pool) == 1:
        return pool[0]

    key = (scope, id(pool))
    memory = _recent.get(key)
    if memory is None or memory.maxlen != max(1, len(pool) // 2):
        memory = deque(maxlen=max(1, len(pool) // 2))
        _recent[key] = memory
    _recent.move_to_end(key)
    while len(_recent) > MAX_SCOPES:
        _recent.popitem(last=False)

    used = set(memory)
    choices = [index for index in range(len(pool)) if index not in used]
    index = _RNG.choice(choices)
    memory.append(index)
    return pool[index]


def steady(pool: Sequence[str], *key: object) -> str:
    """The same phrase for the same key. Live cards are redrawn every few seconds: a phrase
    picked anew each time made their text jump and cost an edit even when nothing happened.
    Put what should change the phrase into the key (the card's id, its vote count)."""
    if not pool:
        return ""
    return pool[zlib.crc32(repr(key).encode()) % len(pool)]


def reset() -> None:
    _recent.clear()
