"""Load test against the fake Telegram: many people pressing at once.

    python scripts/load_test.py

Every Telegram call takes LATENCY seconds, like a real round trip. Scenarios run with hundreds of
updates in parallel; for each the script prints how long the bot took to handle one update
(median, 95th percentile, worst), how many Telegram requests it made, and checks that the game
state adds up (every vote counted once, the boss lost exactly the damage dealt).
"""

import asyncio
import importlib
import statistics
import sys
import time
from datetime import UTC, datetime
from itertools import count
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
importlib.import_module("tests")  # lean aiogram loading, as in the suite

from aiogram import Bot  # noqa: E402
from aiogram.types import CallbackQuery, Message, Update  # noqa: E402

from bot.__main__ import build_dispatcher  # noqa: E402
from bot.tg import challenges, games, timers  # noqa: E402
from bot.tg.timers import Live  # noqa: E402
from tests.helpers import make_game  # noqa: E402
from tests.test_bot import BOT_USER, GROUP, FakeSession, user  # noqa: E402

LATENCY = 0.04  # seconds per Telegram request


class SlowSession(FakeSession):
    async def make_request(self, bot, method, timeout=None):
        await asyncio.sleep(LATENCY)
        return await super().make_request(bot, method, timeout)


class Rig:
    def __init__(self) -> None:
        self.game, self.clock, self.temp = make_game(pics=40, uploader=1)
        self.session = SlowSession()
        self.bot = Bot(token="42:TEST", session=self.session)
        self.live = Live(self.bot, self.game)
        self.dispatcher = build_dispatcher(self.game, self.live, frozenset({1}))
        self.ids = count(1)

    async def feed(self, update: Update) -> float:
        started = time.perf_counter()
        await self.dispatcher.feed_update(self.bot, update)
        return time.perf_counter() - started

    def press(self, data: str, sender: int, message_id: int = 1) -> Update:
        message = Message(message_id=message_id, date=datetime.now(UTC), chat=GROUP, from_user=BOT_USER)
        callback = CallbackQuery(id=str(next(self.ids)), from_user=user(sender), chat_instance="ci", data=data,
                                 message=message)
        return Update(update_id=next(self.ids), callback_query=callback)

    def say(self, text: str, sender: int) -> Update:
        message = Message(message_id=next(self.ids), date=datetime.now(UTC), chat=GROUP, from_user=user(sender),
                          text=text)
        return Update(update_id=next(self.ids), message=message)

    async def burst(self, name: str, updates: list[Update]) -> None:
        before = len(self.session.requests)
        started = time.perf_counter()
        took = await asyncio.gather(*(self.feed(update) for update in updates))
        wall = time.perf_counter() - started
        took_ms = sorted(seconds * 1000 for seconds in took)
        p95 = took_ms[int(len(took_ms) * 0.95) - 1]
        requests = len(self.session.requests) - before
        print(f"{name:34} {len(updates):4} updates · {wall:5.2f} s · per update: median {statistics.median(took_ms):5.0f} ms,"
              f" p95 {p95:5.0f} ms, worst {took_ms[-1]:5.0f} ms · {requests} Telegram requests")

    async def close(self) -> None:
        await self.live.stop()
        self.temp.cleanup()


async def main() -> None:
    games.DICE_ANIMATION_SECONDS = 0
    challenges.DICE_ANIMATION_SCALE = 0
    rig = Rig()
    game = rig.game
    for player in range(10, 400):
        game.repo.add_coins(player, 5000, "test", game.now(), earn=False)

    await rig.feed(rig.say("/duel", 2))
    battle = game.repo.active_battle(GROUP.id, "duel")
    await rig.burst("200 votes in one duel", [rig.press(f"v:{battle.id}:{index % 2}", 10 + index) for index in range(200)])
    counted = sum(game.repo.get_battle(battle.id).vote_counts())
    assert counted == 200, counted

    await rig.feed(rig.say("/boss", 2))
    boss = game.repo.active_boss(GROUP.id)
    await rig.burst("150 boss hits, 150 people", [rig.press(f"bh:{boss['id']}", 10 + index) for index in range(150)])
    fresh = game.repo.get_boss(boss["id"])
    dealt = sum(fresh["damage"].values())
    assert fresh["hp"] == max(0, boss["max_hp"] - dealt), (fresh["hp"], boss["max_hp"], dealt)

    panel = game.repo.panel_message(GROUP.id)
    await rig.feed(rig.say("/menu", 2))
    panel = game.repo.panel_message(GROUP.id)
    await rig.burst("60 people open the shop", [rig.press("m:shop", 10 + index, panel) for index in range(60)])
    await rig.burst("60 people ask whom to give", [rig.press("pp:give", 100 + index, panel) for index in range(60)])

    edits = len(rig.session.of("EditMessageCaption")) + len(rig.session.of("EditMessageText"))
    print(f"live card redraws in the whole run: {edits} (paced to one per {timers.LIVE_EDIT_GAP} s per chat)")
    await rig.close()


if __name__ == "__main__":
    asyncio.run(main())
