# kartinkomet

Telegram bot for random images, shared pools, batch uploads, reactions, duels, achievements, and meme-flavored chaos.

[Русская версия](README.md)

## What It Is

`@kartinkomet_bot` is a Telegram bot for groups and channels. It sends random images from a shared pool using `/pic` or the `🎲 Рандом` button.

The bot does not store image files on the server. It stores only Telegram `file_id` values. The real files remain on Telegram's side.

## Core Features

- shared image pool
- uploads are open to everyone, but only in private chat with the bot
- the only slash upload command is `/upload_pidor`
- no physical image storage on the bot server
- duplicate detection through Telegram `file_unique_id`
- uploads are limited to `100` new images per user per hour
- per-chat anti-repeat random memory
- one reaction per user per image, with reaction switching
- automatic image removal after `2 🖕`
- upload achievements
- `/me` shows quality title, reactions on your uploads, and combo achievements
- `/top` shows the upload leaderboard
- `/duel` starts a one-minute image duel and removes the loser
- `/reset_stats` protected by `ADMIN_USER_IDS`
- hidden admin command `/dedupe_user USER_ID` removes exact duplicates from one uploader
- standalone maintenance script removes visual duplicates with `dHash`
- the bot stays silent on regular text mentions without a command

## Commands And Buttons

| Command or Button | Action |
| --- | --- |
| `🎲 Рандом`, `/pic` | Sends a random image |
| `⚔️ Дуэль`, `/duel` | Starts a one-minute duel between two random images |
| `🎲 Ещё` | Sends another image below the current one |
| `⬆️ Загрузка`, `/upload_pidor` | Starts upload mode in private chat, shows a hint in groups |
| `👤 Мой вклад`, `/me` | Shows your uploads and achievements |
| `🏆 Топ`, `/top` | Shows the upload leaderboard |
| `📊 Статы`, `/stats` | Shows pool, random output, duels, and reactions by section |
| `✅ Закончить`, `/done` | Finishes upload mode and shows a summary |
| `❌ Отмена`, `/cancel` | Cancels the active upload |
| `/count` | Shows the pool size |
| `/mood` | Shows today's bot mood |
| `/menu` | Opens the main control panel |
| `/help` | Shows the command list |

There is no `/upload` command by design. Upload mode starts through the button or `/upload_pidor`, but image files are accepted only in private chat with the bot.

## Random Selection

The random picker is chat-aware:

1. It avoids images recently shown in the current chat.
2. It avoids globally recent images.
3. It prioritizes images with fewer views.
4. It uses `SystemRandom` for the final choice.

Large pools repeat much less often. Small pools can still repeat, but the bot tries not to send the same image immediately.

## Duels

`/duel` selects two random images, sends them as one album without captions under the photos, then opens a `60` second vote.

Duels use a compact card: title, live status, score, timer, and current leader. No `file_id`, no long text walls, and no captions under the photos.

Duels have `400` short dedicated phrases:

- `100` start titles
- `100` live voting statuses
- `100` winner phrases
- `100` tie phrases

Rules:

- only one active duel can run in the same chat
- each user gets one vote but can switch sides
- the bot announces the result after the timer
- the losing image is removed from the pool
- ties keep both images alive
- the result includes a `⚔️ Новая дуэль` button

## Uploading

1. Open a private chat with `@kartinkomet_bot`.
2. Press `⬆️ Загрузка` or send `/upload_pidor`.
3. Send one image, multiple images, a Telegram album, or forwarded images.
4. Send `/done` when the batch is complete.

In groups, the `⬆️ Загрузка` button and `/upload_pidor` command do not open file intake mode. The bot shows a hint and sends users to private chat instead. The pool remains shared: upload in private chat, then `/pic`, `/duel`, and reactions keep working in the group.

The bot confirms batch upload only once after the first accepted image and shows `✅ Закончить` and `❌ Отмена` buttons.

If someone presses an old upload button after upload mode has already closed, the bot does not spam the chat with duplicate summaries. It answers with a short Telegram UI notification instead.

Non-image files are rejected. Duplicate images are skipped.

Script-flood protection: one Telegram user ID can add up to `100` new images per hour. Duplicates and failed files do not spend the limit.

## Groups

The bot does not accept pool uploads directly in Telegram groups. This is intentional: Telegram Privacy Mode and group albums can be unreliable for this workflow.

Groups keep the stable actions:

- `🎲 Рандом` and `/pic`
- `⚔️ Дуэль` and `/duel`
- `📊 Статы`, `/count`, `/me`, `/top`
- `⬆️ Загрузка`, which explains that uploads go through private chat

## Channels

For channels, the bot must be an admin with permission to post messages and media.

The reliable flow is:

1. Upload images in a private chat with the bot.
2. Set `TARGET_CHANNEL_ID`.
3. Call `/pic` to publish into the target channel.

## Reactions

Each image has:

- `👍`
- `💩`
- `🖕`

Rules:

- one user can cast one reaction per image
- a user can switch their reaction
- votes from different users are accumulated
- one-user spam does not inflate the score

Jury rule:

- `1 🖕` - no bot message
- `2 🖕` - image removed from the pool, with the removal notice sent as a reply to it

## Text Pools

Large text pools live in `bot/texts.py`.

Current counts:

- `1500` image captions
- `150` upload-start phrases
- `150` upload-finish phrases
- `150` empty-pool phrases
- `50` achievements
- `400` short duel phrases
- daily mood labels
- jury threshold messages

Image captions are clean. Old mood prefixes were removed from card captions.

`/me` shows the current user's uploaded image count, current achievement, quality title, combo achievements, and progress to the next achievement.

`/top` shows the upload leaderboard. If the bot has already seen a user, it shows their `@username` or Telegram name. Older records without a saved profile fall back to Telegram user ID until the user presses any command or button again.

## Statistics

`/stats` shows:

- `📦 Пул`: how many images are in the shared pool
- `🎲 Рандом`: how many random shots were sent
- `⚔️ Дуэли`: total battles, executions, and peaceful outcomes
- `🧪 Реакции`: total `👍`, `💩`, and `🖕` reactions

## Maintenance

`/reset_stats` resets reactions, view counters, duel counters, and random memory. It is hidden from the public command menu and works only for users listed in `ADMIN_USER_IDS`.

Use `/id` in a private chat with the bot to get your Telegram user ID.

## Visual Duplicate Cleanup

If identical images were uploaded as different files, Telegram may assign different `file_unique_id` values. Exact duplicate checks will not catch those records.

Use the maintenance script for visual dedupe:

```bash
python scripts/visual_dedupe.py --user-id 1045485205 --dry-run
```

By default it reads `/data/image_pool.json`, downloads images from Telegram, computes a visual `dHash`, and reports likely duplicates without changing the database.

Apply the cleanup only after the dry run looks right:

```bash
python scripts/visual_dedupe.py --user-id 1045485205 --apply
```

The script creates a backup next to `image_pool.json` before writing changes. Run it as one-off Railway maintenance, preferably outside active chat traffic.

## Storage And Performance

The pool is stored as JSON and automatically migrates older plain `file_id` lists to the current versioned format.

Performance notes:

- the pool is loaded into memory once at startup
- image lookup by `id` uses an in-memory index
- duplicate checks use an in-memory `file_unique_id` set
- uploaded-count lookup uses an in-memory user index
- the `100` uploads-per-hour limit uses a sorted timestamp index instead of scanning the full pool
- reactions are normalized while reading JSON
- JSON writes are atomic and compact to reduce Railway Volume I/O
- anti-repeat selection avoids full sorting of the whole pool
- image deletion rebuilds indexes so `/top`, limits, and counters stay consistent
- duel state is cleaned after completion, and Telegram API errors from stale buttons do not crash polling
- large text pools are built at import time and then used as normal lists

## Local Run

```bash
python3.12 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
python -m bot
```

Required `.env`:

```env
BOT_TOKEN=123456:your-token
IMAGE_POOL_PATH=data/image_pool.json
TARGET_CHANNEL_ID=
ADMIN_USER_IDS=
```

Checks:

```bash
python -m compileall bot tests
python -m unittest discover
```

## Railway

Included files:

- `Procfile` - starts `python -m bot`
- `.python-version` - uses Python `3.12`

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

When `RAILWAY_VOLUME_MOUNT_PATH` exists, the bot stores the pool at:

```text
/data/image_pool.json
```
