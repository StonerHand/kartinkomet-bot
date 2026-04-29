# kartinkomet

Telegram bot for a shared image pool: random delivery, private uploads, reactions, leaderboards, personal achievements, meme duels, and duplicate cleanup.

[Русская версия](README.md)

## What It Is

`@kartinkomet_bot` works in Telegram groups and channels. It sends a random image from the shared pool through the `🎲 Рандом` button or `/pic`, runs two-image duels, and tracks user contributions.

The bot does not store image files on the server. It stores Telegram `file_id` and `file_unique_id`; the actual files stay on Telegram's side.

## Core Idea

- groups are for random images, duels, stats, and leaderboards
- uploads happen only in private chat with the bot, so Telegram Privacy Mode cannot break file intake
- the pool is shared: upload in private chat, use in groups
- exact duplicates are rejected through `file_unique_id`
- visual duplicates can be cleaned with a separate `dHash` script
- one user can add up to `100` new images per hour
- one user can cast one reaction per image, but can switch it
- `2 🖕🏻` remove an image from the pool
- leaderboards and achievements show usernames without `@`, so nobody gets tagged
- duels are self-healing: timer refreshes and stale duel state is cleared

## Commands

| Command | Action |
| --- | --- |
| `/pic` | Send a random image |
| `/duel` | Start a duel between two random images |
| `/menu` | Open the main control panel |
| `/upload_pidor` | Start upload mode in private chat |
| `/done` | Finish upload mode |
| `/cancel` | Cancel upload mode |
| `/me` | Show your contribution and achievements |
| `/top` | Show the upload leaderboard |
| `/stats` | Show pool, random, duel, and reaction stats |
| `/count` | Show pool size |
| `/mood` | Show today's bot mood |
| `/help` | Show help |

There is intentionally no `/upload` command. The only slash upload command is `/upload_pidor`.

Hidden maintenance commands:

- `/reset_stats` - resets reactions, views, duel counters, and random memory, admin-only through `ADMIN_USER_IDS`
- `/dedupe_user USER_ID` - removes exact duplicates from one uploader, admin-only
- `/id` - shows Telegram user ID, hidden from the public command menu

## Buttons

Main panel:

```text
🎲 Рандом    ⚔️ Дуэль
⬆️ Загрузка 👤 Мой вклад
🏆 Топ       📊 Сводка
```

Under a random image:

```text
🤙🏻  🖕🏻
🎲 Ещё
```

During private upload:

```text
✅ Закончить  ❌ Отмена
```

## Message Design

Messages are formatted as compact cards with clear sections. Long leaderboard lines are split so Telegram does not wrap everything into a wall of text.

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
• Пикч внутри: 3823

🎲 Рандом
• Выстрелов: 2410

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

## Uploads

Reliable flow:

1. Open private chat with `@kartinkomet_bot`.
2. Press `⬆️ Загрузка` or send `/upload_pidor`.
3. Send one image, a batch, a Telegram album, or forwarded images.
4. Press `✅ Закончить` or send `/done`.

In groups, the `⬆️ Загрузка` button does not enable file intake. It explains that uploads must go through private chat.

The bot does not acknowledge every accepted image. After the first accepted image it sends one compact instruction with finish and cancel buttons.

Tracked upload outcomes:

- successfully added images
- duplicates
- invalid files
- `100` new images per hour per user limit

## Duels

`/duel` selects two random images, sends them as one album without captions, then opens a `60` second vote.

Rules:

- only one active duel can run in a chat
- each user votes once but can switch sides
- the duel card refreshes score and timer
- winner stays in the pool
- loser is removed
- ties keep both images alive
- final result includes a `⚔️ Новая дуэль` button
- if Telegram/API stumbles, stale duel state is cleared instead of locking the chat

There are `400` dedicated short duel phrases:

- `100` start titles
- `100` live statuses
- `100` winner phrases
- `100` tie phrases

## Reactions And Jury Rule

Each image has `🤙🏻` and `🖕🏻`.

Rules:

- one user = one reaction per image
- users can switch reactions
- votes from different users accumulate
- pressing the same reaction again does not inflate counters

Jury rule:

- `1 🖕🏻` - no bot message
- `2 🖕🏻` - image is removed from the pool, and the removal notice replies to that image

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
- daily mood labels
- jury-rule messages

Image captions are clean, without mood prefixes.

## Storage

The pool is stored as JSON and automatically migrates older plain `file_id` lists to the versioned format.

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

## Performance And Reliability

- the pool is loaded into memory once at startup
- image lookup by `id` uses an index
- duplicate checks use a `file_unique_id` set
- user upload counters use an index
- per-user stats use an indexed record list by user ID
- hourly upload limits use a sorted timestamp index
- reactions are normalized while reading the database
- JSON writes are atomic through a temporary file
- duel completion removes the loser and writes stats in one save
- stale duels are cleared on the next start attempt
- Telegram API errors are logged and do not crash polling

## Duplicate Cleanup

Exact duplicates from one user:

```text
/dedupe_user 1045485205
```

Visual duplicates through the maintenance script:

```bash
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
```

## Project Structure

```text
bot/__main__.py    # aiogram polling and command menu
bot/config.py      # environment variables and paths
bot/handlers.py    # commands, callbacks, and bot workflows
bot/image_pool.py  # JSON storage, random picker, reactions, indexes
bot/keyboards.py   # inline keyboards
bot/texts.py       # phrases, mood labels, achievements, jury rule
scripts/           # one-off maintenance scripts
tests/             # contract tests
```
