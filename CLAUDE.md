# kartinkomet-bot

Telegram bot for one friends' chat: pics duel, the chat judges, coins flow. aiogram 3.31, Python 3.12,
SQLite. Players see Russian; code, comments and commits are English. Talk to the owner in Russian,
plainly. A push to `main` deploys to Railway: every push reaches real players.

## Structure

Sections, top to bottom; a section imports only from the ones below it (`a | b`: neither imports the
other). The order lives in `.importlinter`; CI enforces it with `lint-imports`.

```
bot/__main__.py    python -m bot: lean aiogram, then app.main
bot/app/           config, menu commands, dispatcher, middleware, polling watchdog
bot/scenarios/     what a command, button or the clock sets off: a router per mechanic, schedule.py
bot/live/          live cards (timers.Live): redraws, countdowns, settling
bot/ui/            layout.py (design system), cards/ (texts per mechanic, re-exported by views.py), keyboards, screens
bot/game/          engine.Game + a mixin per mechanic; results in types.py
bot/db | telegram  storage (schema.sql, migrations, SQL mixins, Repo) | sending, pic downloads, lean aiogram
bot/rules | media  pure counting rules | Pillow (collage, visual hash)
bot/models | texts records (Pic, Battle, Court, UserStats) | phrases
```

Where new code goes, section by section, and every mechanic's rules: `docs/ARCHITECTURE.md` (read the
mechanic's section before changing it). Each `__init__.py` holds one sentence about its section and no
imports; imports are absolute.

When a lower section needs code from a higher one, move that code down; an upward import breaks CI.
After changing imports between sections, run `python scripts/layers.py` to redraw the diagram in docs
(`tests/structure` fails while it is stale). A new section goes into `.importlinter` first.

A new mechanic goes up the layers: `rules/` → `db/schema.sql` + a `db/` mixin (new columns: a migration
in `db/schema.apply_schema`) → a `game/` mixin added to `engine.Game` → `texts/` → `ui/cards/` + a line in
`ui/views.py` + `ui/keyboards.py` → a `scenarios/` router registered in `app/main.build_dispatcher`
(by the clock: `scenarios/schedule.JOBS`; a live card: `live/timers.Live`) → tests in the mirroring
`tests/` folder. Done when a `tests/scenarios` test drives it end to end and `dump_screens` shows its
cards clean.

## Checks

Green before every push:

```bash
.venv/bin/python -m pyflakes bot tests scripts
.venv/bin/lint-imports
.venv/bin/python -m unittest discover -s tests -t .
```

After changing any message: `.venv/bin/python scripts/dump_screens.py .screens/all.html` and look at the
changed cards at phone width. After touching scenarios' hot paths, sending or live cards:
`.venv/bin/python scripts/load_test.py`. For a whole-bot check: `.venv/bin/python scripts/crawl.py [backup]`
presses every button as a player and as the admin, lets two days pass, and reports errors, slow
handlers, broken layouts, bad button answers and anything left running.

## House rules

- Every message is built with `views.card` / `views.marked` / `views.note`; `tests/layout.py` holds the
  design system (emoji first, rules in a quote box, 32-character phone lines). When it fails, fix the text.
- Texts are gender-neutral. Names appear without `@` (an `@` pings) and keep their own case.
- A button's answer (toast or alert) opens with its mechanic's emoji, like every message: the test harness
  fails on one that doesn't. Card titles read `emoji <b>Title</b> · detail`, results `· итог`.
- Answers that concern one person go through `send.personal` / `send.reply_personal`; a button's answer
  passes `callback.id`, which lets a non-admin bot answer personally.
- Every amount of coins (a price, reward, fine, minimum, button amount) goes through `game.scaled` /
  `Game.pay`: one factor from the chat's money pool, nothing fixed. Coins moving between
  players go through `repo.add_coins(..., earn=False)`. One-off grants: `GIFTS` / `GRANTS` in
  `game/progress.py`.
- Live cards redraw through `Live.request_refresh_*`; countdowns ask for a redraw and keep time.
- Secrets stay out of sight: `BOT_TOKEN` is never printed, Railway secrets are never read, `railway ssh`
  is off-limits.

## Shipping

1. Commit on a branch, open a PR, merge it once CI is green; merging to `main` deploys.
2. Watch the deployment: `gh run list -R StonerHand/kartinkomet-bot` and
   `gh api "repos/StonerHand/kartinkomet-bot/deployments?sha=<sha>"` → its statuses reach `success`; look
   again five minutes later (the Railway CLI is logged out, there are no logs to read).
3. `gh release create vX.Y.Z` with notes in Russian, written for players.
