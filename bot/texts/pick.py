"""Phrase picking without short-term repeats."""

import random
from collections import deque
from collections.abc import Sequence

_RNG = random.SystemRandom()
_recent: dict[tuple[object, int], deque[int]] = {}


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
    if memory is None or memory.maxlen != len(pool) // 2:
        memory = deque(maxlen=max(1, len(pool) // 2))
        _recent[key] = memory

    used = set(memory)
    choices = [index for index in range(len(pool)) if index not in used]
    index = _RNG.choice(choices)
    memory.append(index)
    return pool[index]


def reset() -> None:
    _recent.clear()
