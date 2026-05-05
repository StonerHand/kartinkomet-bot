# kartinkomet

Telegram bot for a shared pool of images and jokes: random delivery, private uploads, reactions, leaderboards, personal achievements, meme duels, weather, and duplicate cleanup. The production runtime stays lean: it only installs what the bot needs to run.

[Русская версия](README.md)

## What It Is

`@kartinkomet_bot` works in Telegram groups and channels. It sends a random image from the shared pool through the `🎲 Рандом` button or `/pic`, pulls a random joke through `😂 Анекдот` or `/joke`, runs image and joke duels, and tracks user contributions.

The bot does not store image files on the server. It stores Telegram `file_id` and `file_unique_id`; the actual files stay on Telegram's side.

## Core Idea

- groups are for random images, duels, stats, and leaderboards
- uploads happen only in private chat with the bot, so Telegram Privacy Mode cannot break file intake
- the pool is shared: upload in private chat, use in groups
- jokes live separately from images in `jokes.json`
- exact duplicates are rejected through `file_unique_id`
- text duplicates are rejected through normalized joke text
- visual duplicates can be cleaned with a separate `dHash` script
- heavy visual-cleanup dependencies live in a separate maintenance file
- one user can add up to `1000` new images per hour
- one user can cast one reaction per image, but can switch it
- `2 🖕🏻` remove an image or joke from the pool
- leaderboards and achievements show usernames without `@`, so nobody gets tagged
- image and joke duels are self-healing: timer refreshes and stale duel state is cleared

## Commands

| Command | Action |
| --- | --- |
| `/pic` | Send a random image |
| `/joke` | Send a random joke |
| `/duel` | Start a duel between two random images |
| `/jokeduel` | Start a duel between two random jokes |
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
| `/mood` | Show today's bot mood |
| `/help` | Show help |

There is intentionally no `/upload` command. Upload commands are explicit: `/upload_pidor` for images and `/upload_joke` for jokes.

Hidden maintenance commands:

- `/reset_stats` - resets reactions, views, duel counters, and random memory, admin-only through `ADMIN_USER_IDS`
- `/dedupe_user USER_ID` - removes exact duplicates from one uploader, admin-only
- `/id` - shows Telegram user ID, hidden from the public command menu

## Buttons

Main panel:

```text
🎲 Рандом    😂 Анекдот
⚔️ Пикчи     😂 Дуэль
🌦 Погода    📊 Сводка
👤 Мой вклад 🏆 Топ
📥 Пикчи     📝 Анекдоты
```

Under a random image:

```text
🤙🏻  🖕🏻
🎲 Ещё
```

Under a joke:

```text
🤙🏻  🖕🏻
😂 Ещё анекдот
```

During private upload:

```text
✅ Закончить  ❌ Отмена
```

## Message Design

Messages are compact cards: one title, clear sections, and very little noise. The bot keeps its edge without turning the chat into a blinking billboard.

Leaderboard example:

```text
🏆 Топ загрузчиков пикч

👑 Пьедестал:

🥇 TakaKenshi — 3441 пикч · картинный монополист
🥈 Art_Denisovich — 242 пикч · архитектор мемного склада
🥉 Михаил — 49 пикч · человек с подозрительной галереей

📦 Остальные поставщики

4. asobi_seksu — 46 пикч · человек с подозрительной галереей
5. fata11st — 1 пикч · первый вброс
6. kcifekzhue — 1 пикч · первый вброс
```

Stats example:

```text
📊 Сводка kartinkomet

📦 Пул
• Пикч в запасе: 3823

🎲 Рандом
• Выстрелов пикчами: 2410

😂 Анекдоты
• В блокноте: 128
• Рассказано: 54
• 🤙🏻 Одобрений: 19
• 🖕🏻 Пальцев: 3

⚔️ Дуэли
• Боев: 37
• Казней: 29
• Мирных исходов: 8

🧪 Реакции
• 🤙🏻 Одобрений: 988
• 🖕🏻 Пальцев: 133
```

## Random Selection

The picker is not a plain list shuffle. It:

1. Avoids images recently shown in the current chat.
2. Avoids globally recent images.
3. Prefers images with fewer views.
4. Uses `SystemRandom` for the final choice.

Large pools repeat much less often. Small pools can still repeat, but the bot avoids sending the same image immediately.

Jokes follow the same idea: the bot keeps per-chat delivery history, prefers less-shown entries, and avoids sending the same text twice in a row when there are alternatives.

## Weather

`/weather` and the `🌦 Погода` button show weather only for Mala Tokmachka.

Weather data is fetched without an API key. Users do not pick or type a city.

The response is a clean card with temperature, feels-like value, sky state, daily range, precipitation, and wind. Weather is cached for `10` minutes so repeated button taps do not hit the external API every time.

## Jokes

`/joke` and the `😂 Анекдот` button send a random text from the separate joke pool.

Upload flow:

1. Open private chat with `@kartinkomet_bot`.
2. Press `📝 Анекдоты` or send `/upload_joke`.
3. Send jokes as text, one joke per message.
4. Finish with `/done` or cancel with `/cancel`.

Rules:

- jokes are stored separately in `jokes.json`
- images and jokes never mix
- empty messages and slash commands are not added
- duplicate jokes are rejected through normalized text
- one user can cast one reaction per joke, but can switch it
- `2 🖕🏻` remove the joke from the pool
- `/reset_stats` resets reactions, views, and random memory, but does not delete jokes

## Joke Duels

`/jokeduel` and the `😂 Дуэль` button pick two random jokes and open a `2` minute vote.

Rules mirror the image arena:

- only one active duel of any type can run in a chat
- each user votes once but can switch sides
- joke texts are sent as separate quotes before the vote card
- jokes are not trimmed: long text is split into several messages but kept in full
- winner stays in `jokes.json`
- loser is removed from the joke pool
- ties keep both jokes alive
- final result includes a `😂 Новая дуэль` button

## Uploads

Reliable flow:

1. Open private chat with `@kartinkomet_bot`.
2. Press `📥 Пикчи` or send `/upload_pidor`.
3. Send one image, a batch, a Telegram album, or forwarded images.
4. Press `✅ Закончить` or send `/done`.

In groups, the `📥 Пикчи` button does not enable file intake. It explains that uploads must go through private chat.

The bot does not acknowledge every accepted image. After the first accepted image it sends one compact instruction with finish and cancel buttons.

Tracked upload outcomes:

- successfully added images
- duplicates
- invalid files
- `1000` new images per hour per user limit

## Duels

`/duel` selects two random images, sends them as one album without captions, then opens a `60` second vote.

Rules:

- only one active duel of any type can run in a chat
- each user votes once but can switch sides
- the duel card refreshes score and timer
- winner stays in the pool
- loser is removed
- ties keep both images alive
- final result includes a `⚔️ Новая дуэль` button
- if Telegram/API stumbles, stale duel state is cleared instead of locking the chat

The duel card stays compact: title, status, one-line score, then a separate timer line. Duel images are sent as an album without captions so the chat does not turn into a wall of text.

There are `400` dedicated short duel phrases:

- `100` start titles
- `100` live statuses
- `100` winner phrases
- `100` tie phrases

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

- `1500` random image captions
- `150` upload-start phrases
- `150` upload-finish phrases
- `150` empty-pool phrases
- `50` achievements
- `400` short duel phrases
- separate short phrases for joke duels
- daily mood labels
- jury-rule messages

Image captions are clean, without mood prefixes.

## Storage

Images and jokes are stored in separate JSON files.

Images live in `image_pool.json`. It automatically migrates older plain `file_id` lists to the versioned format.

Example:

```json
{
  "version": 3,
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
    "ties": 8
  }
}
```

Jokes live in `jokes.json`:

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
- image lookup by `id` uses an index
- duplicate checks use a `file_unique_id` set
- user upload counters use an index
- per-user stats use an indexed record list by user ID
- hourly upload limits use a sorted timestamp index
- the `1000` images per hour throttle is decoupled from achievements, so anti-spam settings do not move game titles
- duel pairs are selected through dedicated methods and persist view counters with one JSON write
- active joke duels store only IDs, votes, and timer state, not the full joke texts
- long jokes are split by HTML-safe message size and are never meaning-trimmed
- `Pillow` is not part of the Railway runtime and is only needed for the maintenance script
- reactions are normalized while reading the database
- JSON writes are atomic through a temporary file
- image duel completion removes the loser and writes stats in one save
- joke duel completion removes the losing text from `jokes.json`
- stale duels are cleared on the next start attempt
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

When `RAILWAY_VOLUME_MOUNT_PATH` exists, the bot stores the pool here:

```text
/data/image_pool.json
/data/jokes.json
```

## Project Structure

```text
bot/__main__.py    # aiogram polling and command menu
bot/config.py      # environment variables and paths
bot/handlers.py    # commands, callbacks, and bot workflows
bot/image_pool.py  # JSON storage, random picker, reactions, indexes
bot/joke_pool.py   # separate JSON joke pool
bot/keyboards.py   # inline keyboards
bot/texts.py       # phrases, mood labels, achievements, jury rule
scripts/           # one-off maintenance scripts
tests/             # contract tests
requirements.txt   # production bot dependencies
requirements-maintenance.txt # dependencies for heavy one-off scripts
```
