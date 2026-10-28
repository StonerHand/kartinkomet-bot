"""Polling watchdog and countdowns that survive a broken card."""

import asyncio
import unittest
from unittest import mock

from aiogram import Bot
from aiogram.methods import GetMe, GetUpdates

from bot.tg.timers import Live
from bot.tg.watchdog import PollingWatchdog
from tests.helpers import make_game
from tests.test_bot import FakeSession


class Clock:
    def __init__(self) -> None:
        self.value = 1000.0

    def __call__(self) -> float:
        return self.value


class WatchdogTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.clock = Clock()
        self.watchdog = PollingWatchdog(clock=self.clock, stall_seconds=600)
        self.session = FakeSession()
        self.session.middleware.register(self.watchdog)
        self.bot = Bot(token="42:TEST", session=self.session)

    async def test_only_a_parsed_get_updates_counts(self) -> None:
        self.clock.value += 500
        await self.bot(GetMe())
        self.assertEqual(self.watchdog.silent_for(), 500)
        await self.bot(GetUpdates())
        self.assertEqual(self.watchdog.silent_for(), 0)

    async def test_failing_polls_trip_the_watchdog(self) -> None:
        self.session.refuse = {"GetUpdates"}
        stalls = []

        async def on_stall() -> None:
            stalls.append(self.clock.value)

        with self.assertLogs("bot.tg.watchdog", "CRITICAL"):
            guard = asyncio.create_task(self.watchdog.watch(on_stall, check_seconds=0))
            for _ in range(3):
                with self.assertRaises(Exception):
                    await self.bot(GetUpdates())
                self.clock.value += 300
                await asyncio.sleep(0)
            await asyncio.wait_for(guard, 1)
        self.assertEqual(len(stalls), 1)
        self.assertTrue(self.watchdog.stalled)

    async def test_healthy_polling_never_trips(self) -> None:
        async def on_stall() -> None:
            self.fail("stalled")

        guard = asyncio.create_task(self.watchdog.watch(on_stall, check_seconds=0))
        for _ in range(5):
            self.clock.value += 300
            await self.bot(GetUpdates())
            await asyncio.sleep(0)
        guard.cancel()
        self.assertFalse(self.watchdog.stalled)


class CountdownTest(unittest.IsolatedAsyncioTestCase):
    async def test_a_broken_redraw_does_not_stop_the_settlement(self) -> None:
        game, clock, temp = make_game(pics=4)
        self.addCleanup(temp.cleanup)
        live = Live(Bot(token="42:TEST", session=FakeSession()), game)
        self.addAsyncCleanup(live.stop)
        ends_at = game.now() + 1
        finished = []

        async def refresh() -> None:
            raise ValueError("a view bug")

        def request_refresh() -> None:  # the clock only asks for a redraw, it never waits for one
            clock.advance(5)
            live._debounce("card", refresh)

        async def finish() -> None:
            finished.append(True)

        real_sleep = asyncio.sleep
        with mock.patch.object(asyncio, "sleep", lambda _: real_sleep(0)):
            await asyncio.wait_for(live._countdown(lambda: ends_at, request_refresh, finish), 2)
        self.assertEqual(finished, [True])


if __name__ == "__main__":
    unittest.main()
