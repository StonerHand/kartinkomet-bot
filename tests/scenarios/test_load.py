"""Many people pressing at once: every press counts once, the state adds up, the chat isn't
flooded with redraws. scripts/load_test.py runs the same with network latency and timings."""

import asyncio
from datetime import UTC, datetime

from aiogram.types import CallbackQuery, Message, Update

from tests.harness import BOT_USER, GROUP, BotHarness, user


class LoadTest(BotHarness):
    def update(self, data: str, sender: int) -> Update:
        message = Message(message_id=1, date=datetime.now(UTC), chat=GROUP, from_user=BOT_USER)
        callback = CallbackQuery(id=f"{sender}:{data}", from_user=user(sender), chat_instance="ci", data=data,
                                 message=message)
        return Update(update_id=next(self.update_ids), callback_query=callback)

    async def burst(self, data: str, senders) -> None:
        await asyncio.gather(*(self.dispatcher.feed_update(self.bot, self.update(data, sender)) for sender in senders))

    async def test_a_hundred_votes_at_once_are_counted_once_each(self) -> None:
        await self.send("/duel")
        battle = self.game.repo.active_battle(-100, "duel")
        await self.burst(f"v:{battle.id}:0", range(10, 110))
        await self.burst(f"v:{battle.id}:0", range(10, 110))  # everyone again: no double votes
        self.assertEqual(sum(self.game.repo.get_battle(battle.id).vote_counts()), 100)

    async def test_a_hundred_hits_at_once_add_up(self) -> None:
        await self.send("/boss", sender=3)
        boss = self.game.repo.active_boss(-100)
        await self.burst(f"bh:{boss['id']}", range(10, 110))
        fresh = self.game.repo.get_boss(boss["id"])
        self.assertEqual(fresh["hp"], max(0, boss["max_hp"] - sum(fresh["damage"].values())))
        self.assertEqual(len(self.session.of("AnswerCallbackQuery")), 100)  # every press got its answer
        self.assertLessEqual(len(self.session.of("EditMessageCaption")), 1)  # redraws are batched, not one per hit
