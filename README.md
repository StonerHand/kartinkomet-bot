# kartinkomet

Telegram bot for random images, group chaos, reactions, uploads, per-chat random memory, and meme-flavored captions.

## RU

### Что это

`@kartinkomet_bot` отправляет случайные картинки из общего пула по команде `/pic` или кнопке `🎲 Рандом`.

Бот не хранит сами изображения на сервере. Он сохраняет только Telegram `file_id`, а физические файлы остаются на стороне Telegram.

### Возможности

| Команда или кнопка | Что делает |
| --- | --- |
| `🎲 Рандом`, `/pic` | Отправляет случайную пикчу |
| `🎲 Ещё` | Запрашивает следующую пикчу прямо под текущей |
| `⬆️ Залить пикчи`, `/upload_pidor` | Включает режим загрузки для всех |
| `✅ Закончить`, `/done` | Завершает загрузку и показывает итог |
| `❌ Отмена`, `/cancel` | Отменяет активную загрузку |
| `/count` | Показывает количество пикч в пуле |
| `/stats` | Показывает показы и реакции |
| `/mood` | Показывает режим бота на сегодня |
| `/menu` | Открывает пульт от ядерки |
| `/reset_stats` | Скрытая утилитная команда для сброса реакций, показов и памяти рандома |

### Рандом

Бот выбирает картинку случайно, но не тупо. Он сначала отсекает картинки, которые недавно показывались именно в текущем чате, потом убирает недавно показанные по общему пулу и отдаёт приоритет тем, которые показывались реже.

Если в пуле много картинок, повторы становятся сильно реже. Если картинок мало, повторы всё равно возможны, но бот старается не повторять последнюю картинку сразу.

### Подписи и настроение

- `333` caption-фразы для картинок
- `150` стартовых фраз для режима загрузки
- `30` фраз завершения загрузки
- `/mood` показывает режим бота на сегодня, но не засоряет caption под картинкой

Пример caption:

```text
Пикча как маленькая катастрофа
```

### Реакции

Под каждой картинкой есть реакции:

- `👍`
- `💩`
- `🖕`

Один пользователь может поставить только одну реакцию на конкретную картинку. Если он нажимает другую реакцию, старая реакция снимается, новая засчитывается. Голоса разных пользователей не затирают друг друга.

Народный суд:

- `3 🖕` — бот предупреждает, что пикча близко к вылету
- `4 🖕` — бот пишет, что пикча на грани
- `5 🖕` — картинка удаляется из пула

### Загрузка картинок

1. Нажмите `⬆️ Залить пикчи` или отправьте `/upload_pidor`.
2. Отправьте одну картинку, несколько картинок подряд, альбом Telegram или пересланные изображения.
3. Когда закончите, нажмите `✅ Закончить` или отправьте `/done`.

Бот не спамит ответом на каждую пикчу. После первой принятой картинки он один раз пишет, что принимает пакет.

Дубликаты не добавляются. Проверка идёт по Telegram `file_unique_id`.

Загружать пикчи может любой участник, который видит кнопку или знает команду `/upload_pidor`.

### Группы и каналы

Для работы в группах с обычными картинками лучше отключить Privacy Mode:

1. Откройте `@BotFather`.
2. Выполните `/setprivacy`.
3. Выберите `@kartinkomet_bot`.
4. Выберите `Disable`.

Если Privacy Mode включён, Telegram может не отдавать боту обычные фото из группы. В этом случае после открытия загрузки прикрепляйте картинки ответом на сообщение бота.

Для каналов бот должен быть администратором с правом отправлять сообщения и медиа. Самый надёжный сценарий для канала: загружать картинки в личке с ботом или отдельной группе, а публиковать в канал через `TARGET_CHANNEL_ID`.

### Хранение

Пул хранится в JSON. Формат автоматически мигрирует со старого списка `file_id` на объект с версией, картинками и памятью чатов.

Пример:

```json
{
  "version": 2,
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
      "fires": 2,
      "dislikes": 0,
      "reactions_by_user": {
        "123456789": "like"
      }
    }
  ],
  "chat_history": {
    "-1001234567890": ["a1b2c3"]
  }
}
```

### Оптимизация

- пул читается в память один раз при запуске
- поиск картинки по `id` работает через индекс
- проверка дублей по `file_unique_id` работает через индекс
- счётчик загрузок пользователя берётся из индекса
- запись JSON идёт атомарно через временный файл
- глобальный анти-повтор использует быстрый выбор последних показов без полной сортировки всего пула
- большие наборы текстов вынесены в `bot/texts.py`, чтобы обработчики оставались читаемыми

### Структура проекта

```text
bot/__main__.py    # запуск aiogram polling
bot/config.py      # переменные окружения и пути
bot/handlers.py    # команды, callback-кнопки и сценарии бота
bot/image_pool.py  # JSON-хранилище, рандом, реакции и индексы
bot/keyboards.py   # inline-клавиатуры
bot/texts.py       # фразы, caption-пулы, mood и правила народного суда
```

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

- `Procfile` — запускает `python -m bot`
- `.python-version` — Python `3.12`

Переменные Railway:

```env
BOT_TOKEN=токен_бота
TARGET_CHANNEL_ID=
```

Для постоянного хранения подключите Railway Volume с mount path:

```text
/data
```

Если `RAILWAY_VOLUME_MOUNT_PATH` есть, бот автоматически хранит пул тут:

```text
/data/image_pool.json
```

## EN

### What It Is

`@kartinkomet_bot` sends random images from a shared pool using `/pic` or the `🎲 Рандом` button.

The bot does not store image files on the server. It stores only Telegram `file_id` values, while the real files remain on Telegram's side.

### Features

| Command or Button | Action |
| --- | --- |
| `🎲 Рандом`, `/pic` | Sends a random image |
| `🎲 Ещё` | Requests another image below the current one |
| `⬆️ Залить пикчи`, `/upload_pidor` | Starts upload mode for everyone |
| `✅ Закончить`, `/done` | Finishes upload mode and shows a summary |
| `❌ Отмена`, `/cancel` | Cancels the active upload session |
| `/count` | Shows how many images are in the pool |
| `/stats` | Shows views and reaction stats |
| `/mood` | Shows the bot's daily mode |
| `/menu` | Opens the main control panel |
| `/reset_stats` | Hidden utility command to reset reactions, views, and random memory |

### Random Selection

Random selection is chat-aware. The bot first avoids images recently shown in the current chat, then avoids globally recent images, then prioritizes images with fewer previous views.

With a large pool, repeats become much less frequent. With a small pool, repeats can still happen, but the bot tries not to repeat the last image immediately.

### Captions And Mood

- `333` image caption phrases
- `150` upload-start phrases
- `30` upload-finish phrases
- `/mood` shows the bot's daily mode, but captions stay clean

Example caption:

```text
Pic as a tiny disaster
```

The real bot text is intentionally Russian-first because the bot UI is Russian.

### Reactions

Each image has:

- `👍`
- `💩`
- `🖕`

One user can cast only one reaction per image. If they choose another reaction, the previous one is removed and the new one is counted. Votes from different users do not overwrite each other.

Jury rule:

- `3 🖕` — the bot warns that the image is close to removal
- `4 🖕` — the bot warns that the image is on the edge
- `5 🖕` — the image is removed from the pool

### Uploading Images

1. Press `⬆️ Залить пикчи` or send `/upload_pidor`.
2. Send one image, multiple images, a Telegram album, or forwarded images.
3. Press `✅ Закончить` or send `/done`.

The bot does not spam a confirmation for every image. It confirms once after the first accepted image in a batch.

Duplicates are ignored using Telegram `file_unique_id`.

Any participant who can see the button or knows `/upload_pidor` can upload images.

### Groups And Channels

For group uploads, it is best to disable BotFather Privacy Mode:

1. Open `@BotFather`.
2. Run `/setprivacy`.
3. Select `@kartinkomet_bot`.
4. Select `Disable`.

If Privacy Mode is enabled, Telegram may hide regular group photos from the bot. In that case, start upload mode and attach images as a reply to the bot's message.

For channels, the bot must be an admin with permission to post messages and media. The most reliable channel flow is to upload images in a private chat with the bot or in a separate group, then publish to the channel with `TARGET_CHANNEL_ID`.

### Storage

The pool is stored in JSON. The format is automatically migrated from the old `file_id` list to a versioned object with images and per-chat random memory.

See the RU storage section above for an example payload.

### Optimization

- the pool is loaded into memory once at startup
- image lookup by `id` uses an in-memory index
- duplicate checks by `file_unique_id` use an in-memory index
- uploaded-count lookup uses an in-memory user index
- JSON writes are atomic through a temporary file
- global anti-repeat uses fast latest-item selection without sorting the full pool
- large text pools live in `bot/texts.py`, keeping handlers readable

### Project Structure

```text
bot/__main__.py    # aiogram polling entrypoint
bot/config.py      # environment variables and storage paths
bot/handlers.py    # commands, callback buttons, and bot flows
bot/image_pool.py  # JSON storage, random selection, reactions, and indexes
bot/keyboards.py   # inline keyboards
bot/texts.py       # phrases, caption pools, mood, and jury rules
```

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
