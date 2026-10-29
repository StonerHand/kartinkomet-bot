"""Polling watchdog: a bot that can't read updates must not look healthy.

aiogram retries a failing getUpdates forever, so a bot that can no longer parse Telegram's
replies stays "Online" while ignoring every button (it happened: 8 hours on 2026-10-20). The
watchdog sits in the bot session, notes every getUpdates that came back parsed, and when there
was none for STALL_SECONDS it tells the admins (if it still can) and stops polling with a
failure, so Railway restarts the process and shows the crash.
"""

import asyncio
import logging
from collections.abc import Awaitable, Callable
from time import monotonic

from aiogram import Bot
from aiogram.methods import GetUpdates

LOGGER = logging.getLogger(__name__)
STALL_SECONDS = 600  # a long poll returns every 10 s; ten minutes of nothing is not a network blip
CHECK_SECONDS = 60
ALERT_TIMEOUT = 10


class PollingWatchdog:
    def __init__(self, clock: Callable[[], float] = monotonic, stall_seconds: float = STALL_SECONDS) -> None:
        self.clock = clock
        self.stall_seconds = stall_seconds
        self.last_ok = clock()
        self.stalled = False

    async def __call__(self, make_request, bot: Bot, method, *args, **kwargs):
        """Session middleware: the reply is parsed by the time make_request returns."""
        result = await make_request(bot, method, *args, **kwargs)
        if isinstance(method, GetUpdates):
            self.last_ok = self.clock()
        return result

    def silent_for(self) -> float:
        return self.clock() - self.last_ok

    async def watch(self, on_stall: Callable[[], Awaitable[None]], check_seconds: float = CHECK_SECONDS) -> None:
        while self.silent_for() <= self.stall_seconds:
            await asyncio.sleep(check_seconds)
        self.stalled = True
        LOGGER.critical("No updates for %.0f s: stopping so the process restarts", self.silent_for())
        await on_stall()


async def alert_admins(bot: Bot, admins: frozenset[int], text: str) -> None:
    """Best effort: when polling is broken, sending may be broken too."""
    for admin in admins:
        try:
            await asyncio.wait_for(bot.send_message(admin, text), ALERT_TIMEOUT)
        except Exception:  # noqa: BLE001 — whatever broke polling may break this too
            LOGGER.warning("Could not alert admin %s", admin, exc_info=True)
