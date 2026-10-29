# kartinkomet-bot

Telegram bot for one friends' chat: pics duel, the chat judges, coins flow. aiogram 3.31, Python 3.12,
SQLite. Players see Russian; code, comments and commits are English. Talk to the owner in Russian,
plainly. A push to `main` deploys to Railway: every push reaches real players.

## Structure

Each package's `__init__.py` says what lives there; `docs/ARCHITECTURE.md` holds the flows, data and
every mechanic's rules — read the mechanic's section there before changing it.

```
bot/core/          pure rules (no db, aiogram or clock)
bot/services/      the game: rules + db, one mixin per mechanic, mixed into bot/game.py:Game
bot/db/            schema.sql, repo/ (all SQL)
bot/texts/         phrases
bot/media/         collage, visual hash
bot/tg/handlers/   what a command or button does, one router per mechanic
bot/tg/ui/         views/ (message texts), keyboards.py, screens.py
bot/tg/runtime/    send, live cards (timers), schedule (events), pictures, middleware, watchdog
tests/             harness.py, helpers.py, layout.py + rules/ game/ scenarios/ ui/ runtime/
```

A new mechanic goes down the layers in order:
1. `core/` rule → 2. `db/schema.sql` + `repo/` (new columns: a migration in `repo/models.apply_schema`)
→ 3. `services/` mixin, added to `Game` → 4. `texts/` phrases → 5. `tg/ui/views/` card + `keyboards.py`
→ 6. `tg/handlers/` router, registered in `bot/__main__.build_dispatcher` (scheduled: `runtime/events.JOBS`;
live card: `runtime/timers.Live`) → 7. tests in the mirroring `tests/` folders.
Done when a `tests/scenarios` test drives it end to end and `dump_screens` shows its cards clean.

## Checks

Green before every push:

```bash
.venv/bin/python -m pyflakes bot tests scripts
.venv/bin/python -m unittest discover -s tests -t .
```

After changing any message: `.venv/bin/python scripts/dump_screens.py .screens/all.html` and look at the
changed cards at phone width. After touching handlers' hot paths, sending or live cards:
`.venv/bin/python scripts/load_test.py`.

## House rules

- Every message is built with `views.card` / `views.marked` / `views.note`; `tests/layout.py` holds the
  design system (emoji first, rules in a quote box, 32-character phone lines). When it fails, fix the text.
- Texts are gender-neutral. Names appear without `@` (an `@` pings) and keep their own case.
- Answers that concern one person go through `send.personal` / `send.reply_personal`; a button's answer
  passes `callback.id`, which lets a non-admin bot answer personally.
- Coins the game creates go through `Game.pay` (scaled by the chat's wealth); coins moving between
  players go through `repo.add_coins(..., earn=False)`. One-off grants: `GIFTS` / `GRANTS` in
  `services/progress.py`.
- Live cards redraw through `Live.request_refresh_*`; countdowns ask for a redraw and keep time.
- Secrets stay out of sight: `BOT_TOKEN` is never printed, Railway secrets are never read, `railway ssh`
  is off-limits.

## Shipping

1. Commit, push to `main`.
2. Watch CI and the deployment: `gh run list -R StonerHand/kartinkomet-bot` and
   `gh api "repos/StonerHand/kartinkomet-bot/deployments?sha=<sha>"` → its statuses reach `success`; look
   again five minutes later (the Railway CLI is logged out, there are no logs to read).
3. `gh release create vX.Y.Z` with notes in Russian, written for players.
