# kartinkomet

Telegram bot for random images, shared pools, batch uploads, reactions, duels, achievements, and meme-flavored chaos.

[Русская версия](README.md)

## What It Is

`@kartinkomet_bot` is a Telegram bot for groups and channels. It sends random images from a shared pool using `/pic` or the `🎲 Рандом` button.

The bot does not store image files on the server. It stores only Telegram `file_id` values. The real files remain on Telegram's side.

## Core Features

- shared image pool
- uploads are open to everyone
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
| `🎲 Ещё` | Sends another image below the current one |
| `⬆️ Залить пикчи`, `/upload_pidor` | Starts upload mode |
| `✅ Закончить`, `/done` | Finishes upload mode and shows a summary |
| `❌ Отмена`, `/cancel` | Cancels the active upload |
| `/count` | Shows the pool size |
| `/stats` | Shows views and reactions |
| `/me` | Shows your uploads and achievements |
| `/top` | Shows the upload leaderboard |
| `/duel` | Starts a one-minute duel between two random images |
| `/mood` | Shows today's bot mood |
| `/menu` | Opens the main control panel |
| `/help` | Shows the command list |

There is no `/upload` command by design. Upload mode starts through the button or `/upload_pidor`.

## Random Selection

The random picker is chat-aware:

1. It avoids images recently shown in the current chat.
2. It avoids globally recent images.
3. It prioritizes images with fewer views.
4. It uses `SystemRandom` for the final choice.

Large pools repeat much less often. Small pools can still repeat, but the bot tries not to send the same image immediately.

## Duels

`/duel` selects two random images, sends them as one album marked `🅰️` and `🅱️`, then opens a `60` second vote.

Duels use `333` dedicated phrases across fight announcements, participant captions, and final verdicts, so battles feel less repetitive.

Rules:

- each user gets one vote but can switch sides
- the bot announces the result after the timer
- the losing image is removed from the pool
- ties keep both images alive
- the result includes a `⚔️ Новая дуэль?` button

## Uploading

1. Press `⬆️ Залить пикчи` or send `/upload_pidor`.
2. Send one image, multiple images, a Telegram album, or forwarded images.
3. Press `✅ Закончить` or send `/done`.

The bot confirms batch upload only once after the first accepted image.

Non-image files are rejected. Duplicate images are skipped.

Script-flood protection: one Telegram user ID can add up to `100` new images per hour. Duplicates and failed files do not spend the limit.

## Groups And Privacy Mode

For group uploads, disable BotFather Privacy Mode:

1. Open `@BotFather`.
2. Run `/setprivacy`.
3. Select `@kartinkomet_bot`.
4. Select `Disable`.

If Privacy Mode remains enabled, Telegram may hide regular group photos from the bot. Start upload mode and attach images as a reply to the bot's ForceReply message.

## Channels

For channels, the bot must be an admin with permission to post messages and media.

The reliable flow is:

1. Upload images in a private chat with the bot or in an admin group.
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
- daily mood labels
- jury threshold messages

Image captions are clean. Old mood prefixes were removed from card captions.

`/me` shows the current user's uploaded image count, current achievement, quality title, combo achievements, and progress to the next achievement.

`/top` shows the upload leaderboard. If the bot has already seen a user, it shows their `@username` or Telegram name. Older records without a saved profile fall back to Telegram user ID until the user presses any command or button again.

## Maintenance

`/reset_stats` resets reactions, view counters, and random memory. It is hidden from the public command menu and works only for users listed in `ADMIN_USER_IDS`.

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
- duel state is cleaned after completion, and Telegram API edit errors do not crash polling
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
