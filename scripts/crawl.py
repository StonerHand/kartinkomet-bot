"""Press everything on a copy of a real database, as the chat would, and report what went wrong.

    python scripts/crawl.py [path/to/backup.sqlite]

Starts the whole bot (dispatcher, live cards, schedule) against the fake Telegram on a copy of the
backup (without one: a made-up chat of 12 players and 400 pics), sends every command, then presses every button the bot shows, again and again (as a
player and as the admin) until nothing new appears. Reports logged errors and warnings, handlers
slower than SLOW_MS, messages that break the layout, and button answers Telegram would reject.
Destructive admin buttons are skipped; the backup itself is never touched.
"""

import asyncio
import importlib
import logging
import re
import shutil
import sys
import tempfile
import time
from collections import deque
from datetime import UTC, datetime
from itertools import count
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
importlib.import_module("tests")  # lean aiogram loading, as in the suite

from aiogram import Bot  # noqa: E402
from aiogram.types import CallbackQuery, Chat, Message, Update  # noqa: E402

from bot.app.main import build_dispatcher  # noqa: E402
from bot.db.repo import Repo  # noqa: E402
from bot.game.engine import Game  # noqa: E402
from bot.live import timers  # noqa: E402
from bot.live.timers import Live  # noqa: E402
from bot.scenarios import casino, challenges, games  # noqa: E402
from bot.scenarios.schedule import Events  # noqa: E402
from tests.harness import BOT_USER, CHECKED_METHODS, EMOJI, FakeSession, user  # noqa: E402
from tests.helpers import Clock  # noqa: E402
from tests.layout import layout_problems  # noqa: E402

SLOW_MS = 150
MAX_PRESSES = 1500
ADMIN = 1
SKIP = ("adm:reset!", "adm:backup")  # wipes stats; sends a file of the whole base
COMMANDS = (
    "/menu", "/games", "/people", "/casino", "/today", "/me", "/top", "/help", "/pic", "/duel", "/tournament",
    "/spy", "/mines", "/safe", "/board", "/machine", "/who", "/bomb", "/croc", "/bet проверка обхода", "/boss",
    "/shop", "/quests", "/daily", "/wheel", "/horoscope", "/whose", "/caption", "/heist", "/cup", "/pieces",
    "/spin 10", "/dice 10", "/rps 100", "/ttt 100", "/pvp 100", "/challenge 100", "/give", "/rob", "/admin",
)


class Recorder(logging.Handler):
    def __init__(self) -> None:
        super().__init__(logging.WARNING)
        self.records: list[str] = []

    def emit(self, record: logging.LogRecord) -> None:
        error = record.exc_info[1] if record.exc_info else None
        self.records.append(f"{record.levelname} {record.name}: {record.getMessage()}" + (f" {error!r}" if error else ""))


def made_up_chat(repo: Repo, now: int) -> None:
    """A chat like the real one: 12 players with coins and history, 400 pics of theirs."""
    for player in range(2, 14):
        repo.remember_user(player, f"player{player}", f"Игрок{player}", None, now)
        repo.touch_chat(-100, "чат", now)
        repo.touch_member(-100, player, now)
        repo.add_coins(player, 500 * player, "vote", now - 3600)
    for index in range(400):
        repo.add_pic(f"file{index}", f"uniq{index}", 2 + index % 12, None, now - index * 600)


def shape(data: str) -> str:
    """A button's kind: ids and numbers collapsed, so each kind is pressed a few times, not forever."""
    return re.sub(r"[0-9a-f]{8,}|\d+", "#", data)


async def main(backup: str) -> None:
    folder = tempfile.TemporaryDirectory(prefix="crawl-")
    database = Path(folder.name) / "copy.sqlite"
    if backup:
        shutil.copy(backup, database)
    repo = Repo(database)
    clock = Clock(time.time())
    game = Game(repo, tz_offset_hours=3, clock=clock)
    if not backup:
        made_up_chat(repo, game.now())
    game.admins = frozenset({ADMIN})
    chat_id = repo.db.execute("SELECT chat_id FROM chat_members GROUP BY chat_id ORDER BY COUNT(*) DESC").fetchone()[0]
    players = [row[0] for row in repo.db.execute("SELECT user_id FROM players ORDER BY coins DESC LIMIT 6")]
    group = Chat(id=chat_id, type="supergroup", title="чат")
    session = FakeSession()
    bot = Bot(token="42:TEST", session=session)
    live = Live(bot, game)
    dispatcher = build_dispatcher(game, live, frozenset({ADMIN}))
    timers.LIVE_EDIT_GAP = 0
    games.DICE_ANIMATION_SECONDS = 0
    casino.ANIMATION_SCALE = 0
    challenges.DICE_ANIMATION_SCALE = 0
    recorder = Recorder()
    logging.getLogger().addHandler(recorder)
    ids = count(1)
    timings: list[tuple[float, str]] = []
    layout: dict[str, str] = {}
    toasts: list[str] = []

    async def feed(update: Update, what: str) -> None:
        started = time.perf_counter()
        try:
            await dispatcher.feed_update(bot, update)
        except Exception as error:  # noqa: BLE001 — the report is the point
            recorder.records.append(f"EXCEPTION {what}: {error!r}")
        timings.append(((time.perf_counter() - started) * 1000, what))

    def message(text: str, sender: int, chat: Chat = group) -> Update:
        return Update(update_id=next(ids), message=Message(
            message_id=next(session.ids), date=datetime.now(UTC), chat=chat, from_user=user(sender), text=text))

    def press(data: str, sender: int, message_id: int) -> Update:
        held = Message(message_id=message_id, date=datetime.now(UTC), chat=group, from_user=BOT_USER)
        return Update(update_id=next(ids), callback_query=CallbackQuery(
            id=str(next(ids)), from_user=user(sender), chat_instance="ci", data=data, message=held))

    seen: dict[str, int] = {}
    queue: deque[tuple[str, int]] = deque()
    checked = 0

    def harvest() -> None:
        """Buttons of everything sent since last time go into the queue; messages get checked."""
        nonlocal checked
        for request in session.requests[checked:]:
            kind = session.kind(request)
            text = getattr(request, "text", None) or getattr(request, "caption", None)
            if isinstance(text, str) and kind in CHECKED_METHODS:
                problems = layout_problems(text)
                if problems:
                    layout.setdefault(problems[0], text[:120])
            if kind == "AnswerCallbackQuery" and request.text:
                if not EMOJI.match(request.text) or len(request.text) > 200 or "<" in request.text:
                    toasts.append(request.text)
            markup = getattr(request, "reply_markup", None)
            for row in getattr(markup, "inline_keyboard", None) or ():
                for button in row:
                    data = button.callback_data
                    if not data or data in SKIP:
                        continue
                    if seen.get(shape(data), 0) < 3:
                        seen[shape(data)] = seen.get(shape(data), 0) + 1
                        queue.append((data, 1000))
        checked = len(session.requests)

    for person in players:
        await feed(message("привет", person), "hello")
    for sender in (players[0], ADMIN):
        for command in COMMANDS:
            await feed(message(command, sender), command)
            harvest()
    presses = 0
    while queue and presses < MAX_PRESSES:
        data, message_id = queue.popleft()
        for sender in (players[presses % len(players)], ADMIN):
            await feed(press(data, sender, message_id), data)
            presses += 1
        harvest()
    # Time passes: two days, an hour at a time. Each hour every live card is picked up afresh, as
    # after a restart, so whatever ran out settles; the schedule runs its jobs.
    for hour in range(48):
        clock.advance(3600)
        await live.stop()
        live = Live(bot, game)
        dispatcher.workflow_data["live"] = live
        events = Events(bot, game, live, frozenset({ADMIN}), tz_offset_hours=3)
        started = time.perf_counter()
        live.restore()
        for _ in range(20):
            await asyncio.sleep(0)
        await events.tick()
        timings.append(((time.perf_counter() - started) * 1000, f"hour {hour}: settle and schedule"))
        harvest()
        if hour % 6 == 0:  # the chat keeps playing
            for command in ("/mines", "/safe", "/spy", "/bomb", "/who", "/duel"):
                await feed(message(command, players[hour % len(players)]), command)
            harvest()
            while queue and presses < MAX_PRESSES * 2:
                data, message_id = queue.popleft()
                await feed(press(data, players[presses % len(players)], message_id), data)
                presses += 1
            harvest()
    await live.stop()
    for router in dispatcher.sub_routers:
        router._parent_router = None
    logging.getLogger().removeHandler(recorder)

    print(f"{len(COMMANDS) * 2} commands, {presses} presses, {len(session.requests)} Telegram requests")
    slow = sorted((t for t in timings if t[0] > SLOW_MS), reverse=True)
    print(f"\nslow handlers (> {SLOW_MS} ms): {len(slow)}")
    for ms, what in slow[:15]:
        print(f"  {ms:7.1f} ms  {what}")
    ordered = sorted(ms for ms, _ in timings)
    print(f"  median {ordered[len(ordered) // 2]:.1f} ms, p95 {ordered[int(len(ordered) * 0.95)]:.1f} ms")
    problems = sorted(set(recorder.records))
    print(f"\nerrors and warnings: {len(problems)}")
    for line in problems[:40]:
        print("  " + line[:300])
    print(f"\nlayout problems: {len(layout)}")
    for problem, text in list(layout.items())[:20]:
        print(f"  {problem}  ← {text!r}")
    stuck = {
        "rounds": repo.db.execute("SELECT kind, COUNT(*) FROM rounds WHERE status = 'open' AND ends_at < ? "
                                  "GROUP BY kind", (game.now(),)).fetchall(),
        "battles": repo.db.execute("SELECT COUNT(*) FROM battles WHERE status = 'active'").fetchone()[0],
        "courts": repo.db.execute("SELECT COUNT(*) FROM courts WHERE status = 'active'").fetchone()[0],
        "bosses": repo.db.execute("SELECT COUNT(*) FROM bosses WHERE status = 'active'").fetchone()[0],
        "games": repo.db.execute("SELECT COUNT(*) FROM games WHERE phase != 'done'").fetchone()[0],
        "challenges": repo.db.execute("SELECT COUNT(*) FROM challenges WHERE status = 'pending'").fetchone()[0],
    }
    print(f"\nstill running two days later (should all be empty): {stuck}")
    print(f"\nbad button answers: {len(toasts)}")
    for text in toasts[:10]:
        print("  " + text)
    repo.close()
    folder.cleanup()


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1] if len(sys.argv) > 1 else ""))
