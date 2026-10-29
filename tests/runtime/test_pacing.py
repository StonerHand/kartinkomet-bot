"""Live cards share a chat's message budget: redraws are paced, unchanged ones skipped, and a
flood wait holds back only the redraws."""

import asyncio
import time

from aiogram.exceptions import TelegramRetryAfter
from aiogram.methods import EditMessageCaption

from bot.core import boss as boss_rules
from bot.tg.runtime import timers
from tests.harness import BotHarness


class PacingTest(BotHarness):
    async def boss(self) -> dict:
        await self.send("/boss", sender=3)
        return self.game.repo.active_boss(-100)

    async def test_an_unchanged_card_is_not_sent_again(self) -> None:
        boss = await self.boss()
        await self.live.refresh_boss(boss["id"])
        await self.live.refresh_boss(boss["id"])
        self.assertEqual(len(self.session.of("EditMessageCaption")), 1)
        await self.press(f"bh:{boss['id']}", sender=4)
        await self.live.refresh_boss(boss["id"])
        self.assertEqual(len(self.session.of("EditMessageCaption")), 2)  # the health changed

    async def test_a_flood_wait_holds_back_redraws_not_the_chat(self) -> None:
        boss = await self.boss()
        flood = TelegramRetryAfter(method=EditMessageCaption(caption="x"), message="Too Many Requests", retry_after=30)
        self.session.errors["EditMessageCaption"] = [flood]
        started = time.monotonic()
        await self.live.refresh_boss(boss["id"])  # refused: not slept through
        self.assertLess(time.monotonic() - started, 1)
        self.assertGreater(self.live._next_edit[-100] - time.monotonic(), 25)  # the next redraw waits
        await self.send("/pic", sender=4)  # people's own commands don't
        self.assertTrue(self.session.of("SendPhoto"))

    async def test_redraws_in_one_chat_are_spaced(self) -> None:
        timers.LIVE_EDIT_GAP = 0.05
        boss = await self.boss()
        before = len(self.session.of("EditMessageCaption"))
        started = time.monotonic()
        for hitter in (4, 5, 6):
            await self.press(f"bh:{boss['id']}", sender=hitter)
            await self.live.refresh_boss(boss["id"])
        self.assertGreaterEqual(time.monotonic() - started, 0.1)  # three redraws, two gaps
        self.assertEqual(len(self.session.of("EditMessageCaption")) - before, 3)

    async def test_a_busy_card_keeps_one_redraw_waiting(self) -> None:
        timers.LIVE_EDIT_GAP, timers.REFRESH_DELAY = 0.5, 0
        self.addCleanup(setattr, timers, "REFRESH_DELAY", 1.5)
        boss = await self.boss()
        for hitter in range(10, 30):
            await self.press(f"bh:{boss['id']}", sender=hitter)
            await asyncio.sleep(0.01)  # each request gets past its delay and waits for the chat's turn
        waiting = [key for key, task in self.live._tasks.items() if key.startswith("rboss:") and not task.done()]
        self.assertLessEqual(len(waiting), 1)  # one redraw covers them all; the queue doesn't grow

    async def test_the_clock_settles_on_time_whatever_the_redraw_queue(self) -> None:
        timers.TICK_SECONDS = 0.01
        self.addCleanup(setattr, timers, "TICK_SECONDS", 15)
        timers.LIVE_EDIT_GAP = 30  # the chat's redraws are far behind
        boss = await self.boss()
        await asyncio.sleep(0.05)  # a few ticks: they only ask for redraws, never wait for one
        self.clock.advance(boss_rules.DURATION_SECONDS + 1)
        for _ in range(100):
            if self.game.repo.get_boss(boss["id"])["status"] != "active":
                break
            await asyncio.sleep(0.01)
        self.assertEqual(self.game.repo.get_boss(boss["id"])["status"], "lost")
