# kartinkomet

Telegram bot for random images, group chaos, reactions, uploads, and meme-flavored captions.

## RU

### Что это

`@kartinkomet_bot` отправляет случайные картинки из общего пула по команде `/pic` или кнопке `🎲 Рандом`.

Бот не хранит сами изображения на сервере. Он сохраняет только Telegram `file_id`, а физические файлы остаются на стороне Telegram.

### Что умеет

- `🎲 Рандом` и `/pic` — отправить случайную пикчу.
- `🎲 Ещё` — запросить следующую пикчу прямо из-под картинки.
- `⬆️ Залить пикчи` и `/upload_pidor` — открыть режим загрузки.
- `✅ Закончить` и `/done` — закрыть загрузку и показать итог.
- `❌ Отмена` и `/cancel` — отменить активную загрузку.
- `/count` — количество пикч в пуле.
- `/stats` — статистика показов и реакций.
- `/mood` — настроение бота на сегодня.
- `/reset_stats` — скрытая утилитная команда для сброса реакций, показов и памяти рандома.

### Рандом

Бот выбирает картинку случайно, но сначала отсекает недавно показанные изображения и отдаёт приоритет тем, которые показывались реже. Если пул большой, повторы становятся заметно реже. Если в пуле мало картинок, повторы всё равно возможны.

К каждой картинке добавляется случайная подпись из `150` вариантов.

### Реакции

Под каждой картинкой есть реакции:

- `👍`
- `💩`
- `🖕`

Один пользователь может поставить только одну реакцию на конкретную картинку. Если он нажимает другую реакцию, старая заменяется.

Если картинка набирает `5` уникальных `🖕`, бот удаляет её из пула.

### Загрузка картинок

1. Нажмите `⬆️ Залить пикчи` или отправьте `/upload_pidor`.
2. Отправьте одну картинку, пачку картинок, альбом Telegram или пересланные изображения.
3. Когда закончите, нажмите `✅ Закончить` или отправьте `/done`.

Бот не спамит ответом на каждую картинку. После первой принятой картинки он один раз пишет, что принимает пакет.

Дубликаты не добавляются. Проверка идёт по Telegram `file_unique_id`.

### Группы и каналы

Для работы в группах с обычными картинками нужно отключить Privacy Mode:

1. Откройте `@BotFather`.
2. Выполните `/setprivacy`.
3. Выберите `@kartinkomet_bot`.
4. Выберите `Disable`.

Если Privacy Mode включён, Telegram может не отдавать боту обычные фото из группы. В этом случае после открытия загрузки прикрепляйте картинки ответом на сообщение бота.

Для каналов бот должен быть добавлен администратором с правом отправлять сообщения и медиа. Если команды и загрузка в самом канале ведут себя нестабильно, самый надёжный сценарий: загружать картинки в личке с ботом или в отдельной группе, а публиковать в канал через `TARGET_CHANNEL_ID`.

### Локальный запуск

```bash
python3.12 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

Заполните `.env`:

```env
BOT_TOKEN=123456:your-token
IMAGE_POOL_PATH=data/image_pool.json
TARGET_CHANNEL_ID=
```

Запуск:

```bash
python -m bot
```

### Railway

В проекте уже есть:

- `Procfile` — команда запуска `python -m bot`
- `.python-version` — Python `3.12`

Переменные Railway:

```env
BOT_TOKEN=токен_бота
TARGET_CHANNEL_ID=
```

Для постоянного хранения пула подключите Railway Volume с mount path:

```text
/data
```

Если `RAILWAY_VOLUME_MOUNT_PATH` есть, бот автоматически хранит пул в:

```text
/data/image_pool.json
```

### Хранение

Пул хранится в JSON. Пример записи:

```json
{
  "id": "a1b2c3",
  "file_id": "AgACAgIAAxkBA...",
  "file_unique_id": "AQAD...",
  "added_by": 123456789,
  "added_at": "2026-04-25T13:00:00+00:00",
  "shown_count": 3,
  "last_shown_at": "2026-04-25T13:10:00+00:00",
  "likes": 1,
  "fires": 2,
  "dislikes": 0,
  "reactions_by_user": {
    "123456789": "like"
  }
}
```

## EN

### What It Is

`@kartinkomet_bot` sends random images from a shared pool using `/pic` or the `🎲 Рандом` button.

The bot does not store image files on the server. It stores only Telegram `file_id` values, while the actual files stay on Telegram's side.

### Features

- `🎲 Рандом` and `/pic` — send a random image.
- `🎲 Ещё` — request another image directly under the current one.
- `⬆️ Залить пикчи` and `/upload_pidor` — start upload mode.
- `✅ Закончить` and `/done` — finish upload mode and show a summary.
- `❌ Отмена` and `/cancel` — cancel the active upload session.
- `/count` — show how many images are in the pool.
- `/stats` — show views and reaction stats.
- `/mood` — show the bot's daily mood.
- `/reset_stats` — hidden utility command to reset reactions, views, and recent-random memory.

### Random Selection

The bot uses random selection, avoids recently shown images when possible, and prioritizes images with fewer previous views. With a larger pool, repeats become much less frequent. With a small pool, repeats can still happen.

Each image gets a random caption from a set of `150` captions.

### Reactions

Each image has:

- `👍`
- `💩`
- `🖕`

One user can cast only one reaction per image. If they press another reaction, the old one is replaced.

If an image gets `5` unique `🖕` reactions, the bot removes it from the pool.

### Uploading Images

1. Press `⬆️ Залить пикчи` or send `/upload_pidor`.
2. Send one image, multiple images, a Telegram album, or forwarded images.
3. Press `✅ Закончить` or send `/done`.

The bot does not spam a confirmation for every image. It confirms once after the first accepted image in a batch.

Duplicates are ignored using Telegram `file_unique_id`.

### Groups And Channels

For group uploads, disable BotFather Privacy Mode:

1. Open `@BotFather`.
2. Run `/setprivacy`.
3. Select `@kartinkomet_bot`.
4. Select `Disable`.

If Privacy Mode is enabled, Telegram may hide regular group photos from the bot. In that case, start upload mode and attach images as a reply to the bot's message.

For channels, the bot must be an admin with permission to post messages and media. If direct channel uploads are unreliable, use the stable flow: upload images in a private chat with the bot or in a separate group, then publish to a channel with `TARGET_CHANNEL_ID`.

### Local Run

```bash
python3.12 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

Fill `.env`:

```env
BOT_TOKEN=123456:your-token
IMAGE_POOL_PATH=data/image_pool.json
TARGET_CHANNEL_ID=
```

Run:

```bash
python -m bot
```

### Railway

Included deployment files:

- `Procfile` — starts `python -m bot`
- `.python-version` — uses Python `3.12`

Railway variables:

```env
BOT_TOKEN=your_bot_token
TARGET_CHANNEL_ID=
```

For persistent storage, attach a Railway Volume with mount path:

```text
/data
```

When `RAILWAY_VOLUME_MOUNT_PATH` is available, the bot automatically stores the pool at:

```text
/data/image_pool.json
```
