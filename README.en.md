# kartinkomet

Telegram bot for a shared pool of images and jokes: random delivery, private uploads, reactions, leaderboards, personal achievements, meme duels, tournaments, weather, and duplicate cleanup. The production runtime stays lean: it only installs what the bot needs to run.

[Русская версия](README.md)

## What It Is

`@kartinkomet_bot` works in Telegram groups and channels. It sends a random image from the shared pool through the `🎲 Рандом пикч` button or `/pic`, pulls a random joke through `😂 Рандом шуток` or `/joke`, runs duels, mini-tournaments, and tracks user contributions.

The bot does not store image files on the server. It stores Telegram `file_id` and `file_unique_id`; the actual files stay on Telegram's side.

## Core Idea

- groups are for random images, duels, stats, and leaderboards
- uploads happen only in private chat with the bot, so Telegram Privacy Mode cannot break file intake
- the pool is shared: upload in private chat, use in groups
- data lives in a normalized SQLite database; legacy `image_pool.json` and `jokes.json` are imported automatically on first migration
- image duplicates are rejected through `file_unique_id` plus a fast `file_id` fallback
- text duplicates are rejected through normalized joke text with extra punctuation removed
- visual duplicates can be cleaned with a separate `dHash` script
- heavy visual-cleanup dependencies live in a separate maintenance file
- one user can add up to `1000` new images per hour
- one user can cast one reaction per image, but can switch it
- `2 🖕🏻` remove an image or joke from the pool
- leaderboards and achievements show usernames without `@`, so nobody gets tagged
- duels are split by arena: one image duel and one joke duel can run at the same time
- image tournaments are separate: 4 images, 90 seconds, one champion, no deletion
- duels are self-healing: timer refreshes and stale duel state is cleared

## Commands

| Command | Action |
| --- | --- |
| `/pic` | Send a random image |
| `/joke` | Send a random joke |
| `/duel` | Start a duel between two random images |
| `/jokeduel` | Start a duel between two random jokes |
| `/tournament` | Start a four-image tournament |
| `/weather` | Show weather for Mala Tokmachka |
| `/menu` | Open the main control panel |
| `/upload_pidor` | Start upload mode in private chat |
| `/upload_joke` | Start joke upload mode in private chat |
| `/done` | Finish upload mode |
| `/cancel` | Cancel upload mode |
| `/stats` | Show pool, random, duel, and reaction stats |
| `/me` | Show your contribution and achievements |
| `/top` | Show the upload leaderboard |
| `/count` | Show image and joke counts |
| `/help` | Show help |

There is intentionally no `/upload` command. Upload commands are explicit: `/upload_pidor` for images and `/upload_joke` for jokes.

Hidden maintenance commands:

- `/reset_stats` - resets reactions, views, duel counters, and random memory, admin-only through `ADMIN_USER_IDS`
- `/dedupe_user USER_ID` - removes exact duplicates from one uploader, admin-only
- `/id` - shows Telegram user ID, hidden from the public command menu

## Buttons

Main panel:

```text
🎲 Рандом пикч      😂 Рандом шуток
⚔️ Дуэль пикч       🥊 Дуэль шуток
🏟 Турнир           📊 Сводка склада
🏆 Топ          🌦 Погода
👤 Профиль
📬 Загрузка пикч    📝 Загрузить шутки
```

If an arena is already busy, the button says so:

```text
⚔️ Пикчи · идёт    🥊 Шутки · идёт
🏟 Турнир · идёт
```

In private chat, uploads move to the top:

```text
📥 Загрузить пикчи  📝 Загрузить шутки
🎲 Рандом пикч      😂 Рандом шуток
⚔️ Дуэль пикч       🥊 Дуэль шуток
🏟 Турнир           📊 Сводка склада
🏆 Топ          🌦 Погода
👤 Профиль
```

Under a random image:

```text
🤙🏻  🖕🏻
🎲 Ещё пикчу
```

Under a joke:

```text
🤙🏻  🖕🏻
😂 Ещё шутку
```

During private upload:

```text
✅ Закончить  ❌ Отмена
```

## Message Design

Messages are compact cards: one title, 2-4 readable sections, and very little noise. Random drops, uploads, stats, and arenas now speak in one voice: sharp, readable, and not overloaded.

Leaderboard example:

```text
🏆 Топ загрузчиков пикч

👑 Элита склада

🥇 TakaKenshi — 3441 пикч · картинный монополист
🥈 Art_Denisovich — 242 пикч · архитектор мемного склада
🥉 Михаил — 49 пикч · человек с подозрительной галереей

📦 Рабочий класс

4. asobi_seksu — 46 пикч · человек с подозрительной галереей
5. fata11st — 1 пикч · первый вброс
6. kcifekzhue — 1 пикч · первый вброс
```

Stats example:

```text
📊 Сводка kartinkomet

📦 Склад
Пикчи: 3823
Анекдоты: 128

🎲 Выдача
Пикчи выданы: 2410
Анекдоты выданы: 54

⚔️ Арены
Дуэли: 37
Удалений после дуэлей: 29
Мирных дуэлей: 8
Турниры: 12
Турниры без чемпиона: 3

⚖️ Реакции
Пикчи: 🤙🏻 Одобрено 988 · 🖕🏻 Народный суд 133
Анекдоты: 🤙🏻 Одобрено 19 · 🖕🏻 Народный суд 3

🟢 Активные игры
Дуэль пикч: идёт, 42 сек
Дуэль шуток: свободно
Турнир: свободно
```

Arena example:

```text
⚔️ Арена пикч

Чат вызван в присяжные
Кнопочная демократия в режиме суда

Счёт
🅰️ Первый: 2
🅱️ Второй: 1

Статус
⏱ 45 сек · 🔥 Ведёт 🅰️
```

Duel result example:

```text
⚖️ Приговор арены

Рандом записал приговор. Победитель остаётся на складе

Счёт
🅰️ Первый: 4
🅱️ Второй: 1

Вердикт
🏆 Победитель: 🅰️ первая
🗑 Удалена: 🅱️ вторая
```

Menu example:

```text
🎛 Пульт kartinkomet

📦 Склад
Пикчи: 3823 · Анекдоты: 128

🟢 Арены
Пикчи: свободно · Шутки: идёт, 82 сек
Турнир: свободно

📥 Загрузка
загрузка открывается в личке
```

Joke example:

```text
😂 Анекдот

> Бот спросил у рандома:
> - Ты уверен?
> - Уже поздно
```

Empty pool example:

```text
📭 Склад пикч пуст

Пул на нуле. Склад смотрит в пол

Что делать
Нажмите 📬 Как загрузить пикчи и бот покажет маршрут в личку
```

Upload example:

```text
📥 Приём пикч открыт

Скидывай визуальные улики. Кидайте одну пикчу, пачку, альбом или пересланные изображения

Что кидать
Фото, пачку, альбом или пересланные изображения

Управление
✅ Закончить - сохранить пакет
❌ Отмена - закрыть без отчёта
```

Upload summary example:

```text
✅ Загрузка закрыта
Пикчи припаркованы, контент спрятан в рукаве

📦 Итог пакета
✅ Пикч добавлено: 18
♻️ Дублей: 2
🚫 Не принято: 0
🏅 Новый ранг: архитектор мемного склада
```

## Random Selection

The picker is not a plain list shuffle. It:

1. Avoids images recently shown in the current chat.
2. Avoids globally recent images.
3. Prefers a window of least-shown records instead of one rigid minimum.
4. Uses `SystemRandom` for the final choice.

Large pools repeat much less often. Small pools can still repeat, but the bot avoids sending the same image immediately.

Duels use a separate arena history: the two images from the just-played pair should not immediately form the next pair again.

Tournaments use their own `tournament:{chat_id}` history and pick four less-exhausted images.

Jokes follow the same idea: the bot keeps per-chat delivery history, chooses from a less-shown candidate window, and avoids sending the same text twice in a row when there are alternatives.

## Weather

`/weather` and the `🌦 Погода` button show weather only for Mala Tokmachka.

Weather data is fetched without an API key. Users do not pick or type a city.

The response is a clean card with temperature, feels-like value, sky state, daily range, precipitation, wind, and a short verdict. Weather is cached for `10` minutes so repeated button taps do not hit the external API every time.

## Jokes

`/joke` and the `😂 Анекдот` button send a random text from the separate joke pool.

Upload flow:

1. Open private chat with `@kartinkomet_bot`.
2. Press `📝 Анекдоты` or send `/upload_joke`.
3. Send jokes as text, one joke per message.
4. Finish with `/done` or cancel with `/cancel`.

Rules:

- jokes are stored separately from images in the `jokes`, `joke_reactions`, and `joke_chat_history` SQLite tables
- images and jokes never mix
- empty messages and slash commands are not added
- duplicate jokes are rejected through normalized text
- one user can cast one reaction per joke, but can switch it
- `2 🖕🏻` remove the joke from the pool
- `/reset_stats` resets reactions, views, and random memory, but does not delete jokes

## Joke Duels

`/jokeduel` and the `🥊 Дуэль шуток` button pick two random jokes and open a `2` minute vote.

Rules mirror the image arena:

- one active joke duel can run in a chat
- an image duel can run in parallel with the joke duel
- each user votes once but can switch sides
- joke texts are sent as separate quotes before the vote card
- jokes are not trimmed: long text is split into several messages but kept in full
- winner stays in the joke pool
- loser is removed from the joke pool
- ties keep both jokes alive
- final result includes a `🥊 Реванш шуток` button

## Uploads

Reliable flow:

1. Open private chat with `@kartinkomet_bot`.
2. Press `📥 Загрузить пикчи` or send `/upload_pidor`.
3. Send one image, a batch, a Telegram album, or forwarded images.
4. Press `✅ Закончить` or send `/done`.

In groups, the `📬 Загрузка пикч` button does not enable file intake. It explains that uploads must go through private chat.

The bot does not acknowledge every accepted image. It shows the instruction and finish/cancel buttons immediately when upload starts, then quietly counts the result.

Tracked upload outcomes:

- successfully added images
- duplicates
- invalid files
- `1000` new images per hour per user limit

## Duels

`/duel` selects two random images, sends them as one album without captions, then opens a `60` second vote.

Rules:

- one active image duel can run in a chat
- a joke duel can run in parallel with the image duel
- each user votes once but can switch sides
- the duel card refreshes score and timer
- winner stays in the pool
- loser is removed
- ties keep both images alive
- final result includes a `⚔️ Реванш пикч` button
- if Telegram/API stumbles, stale duel state is cleared instead of locking the chat

The duel card stays compact: title, status, one-line score, then a separate timer line. Duel images are sent as an album without captions so the chat does not turn into a wall of text.

There are `600` dedicated short image-duel phrases:

- `150` start titles
- `150` live statuses
- `150` winner phrases
- `150` tie phrases

## Tournaments

`/tournament` and the `🏟 Турнир` button pick four random images and open a `90` second vote.

Unlike duels, tournaments are non-destructive:

- losers are not removed
- the chat only chooses a showcase champion
- each user votes once, but can switch sides
- if several images share the top score, no champion is assigned
- final result includes a `🏟 Новый турнир` button

In short: duels are the jury rule, tournaments are the showcase.

## Reactions And Jury Rule

Each image and joke has `🤙🏻` and `🖕🏻`.

Rules:

- one user = one reaction per image
- users can switch reactions
- votes from different users accumulate
- pressing the same reaction again does not inflate counters

Jury rule:

- `1 🖕🏻` - no bot message
- `2 🖕🏻` - image or joke is removed from the pool, and the removal notice replies to the original message

## Achievements And Profile

`/me` shows:

- uploaded image count
- current achievement
- reactions on the user's images
- views of the user's images
- quality title
- combo achievements
- progress to the next milestone

Achievements are awarded automatically at upload thresholds. Usernames are shown without `@` to avoid tagging people.

## Text Pools

All phrases live in `bot/texts.py`.

Current counts:

- `1550` random image captions
- `200` upload-start phrases
- `200` upload-finish phrases
- `200` empty-pool phrases
- `100` achievements
- `600` short image-duel phrases
- `80` phrases for every joke-duel stage
- `80` phrases for every tournament stage
- jury-rule messages

Image captions are clean, without extra prefixes.

## Storage

Primary storage is the `kartinkomet.sqlite` SQLite file.

The database uses real tables instead of storing the entire pool as one large JSON document:

- `images` — images, Telegram `file_id`, `file_unique_id`, view counters, and reaction totals
- `image_reactions` — one user's current vote for one image
- `image_chat_history` — per-chat random history
- `image_stats` — duel counters, tournament counters, and schema version
- `users` — usernames and names for leaderboards without Telegram mentions
- `jokes` — jokes and their counters
- `joke_reactions` — reactions on jokes
- `joke_chat_history` — per-chat joke delivery history

Legacy storage is still supported. If SQLite is empty, the bot first checks the old `documents` format inside SQLite, then legacy `image_pool.json` and `jokes.json`, normalizes the data, and writes it into the new tables. Migration does not require a manual import.

The JSON below is the compatible migration and local fallback shape for runs without `DATABASE_PATH`.

Example:

```json
{
  "version": 4,
  "images": [
    {
      "id": "a1b2c3",
      "file_id": "AgACAgIAAxkBA...",
      "file_unique_id": "AQAD...",
      "added_by": 123456789,
      "added_at": "2026-04-25T13:00:00+00:00",
      "shown_count": 3,
      "last_shown_at": "2026-04-25T13:10:00+00:00",
      "likes": 1,
      "dislikes": 0,
      "reactions_by_user": {
        "123456789": "like"
      }
    }
  ],
  "chat_history": {
    "-1001234567890": ["a1b2c3"]
  },
  "users": {},
  "duel_stats": {
    "total": 37,
    "executions": 29,
    "ties": 8,
    "tournaments": 12,
    "tournament_ties": 3
  }
}
```

Joke document:

```json
{
  "version": 1,
  "jokes": [
    {
      "id": "j1",
      "text": "A one-line or multi-line joke",
      "normalized_text": "a one-line or multi-line joke",
      "added_by": 123456789,
      "added_at": "2026-04-29T13:00:00+00:00",
      "shown_count": 2,
      "last_shown_at": "2026-04-29T13:10:00+00:00",
      "likes": 1,
      "dislikes": 0,
      "reactions_by_user": {
        "123456789": "like"
      }
    }
  ],
  "chat_history": {
    "-1001234567890": ["j1"]
  }
}
```

## Performance And Reliability

- the pool is loaded into memory once at startup
- SQLite is the primary durable storage file with separate tables for images, jokes, reactions, history, and users
- old JSON files are used as first-migration sources
- image lookup by `id` uses an index
- duplicate checks use `file_unique_id` and `file_id` sets
- joke duplicates are normalized by case, whitespace, and punctuation
- `/stats`, `/top`, and `/me` use in-memory caches that are invalidated only after pool changes
- random selection picks from a least-shown candidate window through a heap, without sorting the full pool
- duels use shared arena history so a fresh pair does not repeat immediately
- active duels are stored in two per-chat slots: `image` and `joke`
- duplicate starts are blocked only inside their own slot, so image and joke arenas do not block each other
- user upload counters use an index
- per-user stats use an indexed record list by user ID
- hourly upload limits use a sorted timestamp index
- the `1000` images per hour throttle is decoupled from achievements, so anti-spam settings do not move game titles
- duel pairs and tournament quartets are selected through dedicated methods and persist view counters in one operation
- active joke duels store only IDs, votes, and timer state, not the full joke texts
- long jokes are split by HTML-safe message size and are never meaning-trimmed
- `Pillow` is not part of the Railway runtime and is only needed for the maintenance script
- reactions are normalized while reading the database
- SQLite writes go through a normalized storage layer with backward compatibility for old documents
- JSON writes remain only as a fallback for tests and manual local mode without `DATABASE_PATH`
- image duel completion removes the loser and writes stats in one save
- joke duel completion removes the losing text from storage
- tournament completion writes stats but does not delete images
- stale duels are cleared on the next start attempt
- redundant Telegram score edits are skipped, and `message is not modified` no longer pollutes logs
- duel albums and vote cards retry short Telegram network failures and fall back to separate photos when album delivery fails
- Telegram API errors are logged and do not crash polling

## Duplicate Cleanup

Exact duplicates from one user:

```text
/dedupe_user 1045485205
```

Visual duplicates through the maintenance script:

```bash
pip install -r requirements-maintenance.txt
python scripts/visual_dedupe.py --user-id 1045485205 --dry-run
```

Apply after reviewing the report:

```bash
python scripts/visual_dedupe.py --user-id 1045485205 --apply
```

The script creates a backup next to `image_pool.json`. Run it as one-off Railway maintenance, preferably outside active chat traffic.

## Local Run

```bash
python3.12 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

`.env`:

```env
BOT_TOKEN=123456:your-token
DATABASE_PATH=data/kartinkomet.sqlite
IMAGE_POOL_PATH=data/image_pool.json
JOKE_POOL_PATH=data/jokes.json
TARGET_CHANNEL_ID=
ADMIN_USER_IDS=
```

Run:

```bash
python -m bot
```

Checks:

```bash
python -m compileall bot scripts tests
python -m unittest discover
```

For visual duplicate cleanup, also install:

```bash
pip install -r requirements-maintenance.txt
```

## Railway

Included files:

- `Procfile` - starts `python -m bot`
- `.python-version` - Python `3.12`

Railway variables:

```env
BOT_TOKEN=your_bot_token
TARGET_CHANNEL_ID=
ADMIN_USER_IDS=your_telegram_user_id
```

Attach a Railway Volume with mount path:

```text
/data
```

When `RAILWAY_VOLUME_MOUNT_PATH` exists, the bot stores the main database here:

```text
/data/kartinkomet.sqlite
```

If old `/data/image_pool.json` and `/data/jokes.json` files exist nearby, they are used for the first migration.

## Project Structure

```text
bot/__main__.py    # aiogram polling and command menu
bot/config.py      # environment variables and paths
bot/handlers.py    # commands, callbacks, and bot workflows
bot/image_pool.py  # image pool, random picker, reactions, duels, tournaments, indexes
bot/joke_pool.py   # separate joke pool
bot/keyboards.py   # inline keyboards
bot/storage.py     # SQLite storage: tables, migration, and legacy fallback
bot/texts.py       # phrases, achievements, jury rule
scripts/           # one-off maintenance scripts
tests/             # contract tests
requirements.txt   # production bot dependencies
requirements-maintenance.txt # dependencies for heavy one-off scripts
```
