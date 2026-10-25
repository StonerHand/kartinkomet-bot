"""Live cards share a chat's message budget: redraws are paced, unchanged ones skipped, and a
flood wait holds back only the redraws."""

import time

from aiogram.exceptions import TelegramRetryAfter
from aiogram.methods import EditMessageCaption

from bot.tg import timers
from tests.test_bot import BotHarness


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
