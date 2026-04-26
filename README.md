# kartinkomet

Telegram bot for random images, group chaos, uploads, reactions, anti-repeat random, achievements, and meme captions.

## RU

### Что это

`@kartinkomet_bot` - бот для Telegram-групп и каналов. Он отправляет случайные изображения из общего пула по кнопке `🎲 Рандом` или команде `/pic`.

Бот не хранит сами картинки на сервере. Он сохраняет только Telegram `file_id`, а физические файлы остаются на стороне Telegram.

### Главное

- общий пул изображений для всех чатов
- загрузка доступна всем участникам
- slash-команда загрузки только одна: `/upload_pidor`
- изображения не скачиваются на сервер
- дубликаты отсекаются по Telegram `file_unique_id`
- рандом помнит недавние выдачи по каждому чату
- один пользователь может поставить только одну реакцию на картинку, но может перевыбрать её
- при `5 🖕` картинка удаляется из пула народным судом
- достижения выдаются за личный вклад в пул
- `/reset_stats` защищён через `ADMIN_USER_IDS`

### Команды и кнопки

| Команда или кнопка | Что делает |
| --- | --- |
| `🎲 Рандом`, `/pic` | Отправляет случайную пикчу |
| `🎲 Ещё` | Запрашивает следующую пикчу под текущей |
| `⬆️ Залить пикчи`, `/upload_pidor` | Открывает режим загрузки |
| `✅ Закончить`, `/done` | Завершает загрузку и показывает итог |
| `❌ Отмена`, `/cancel` | Отменяет активную загрузку |
| `/count` | Показывает количество пикч в пуле |
| `/stats` | Показывает показы и реакции |
| `/mood` | Показывает режим бота на сегодня |
| `/menu` | Открывает пульт от ядерки |
| `/help` | Показывает список команд |

`/upload` намеренно не существует. Загрузка открывается через кнопку или только через `/upload_pidor`.

### Рандом

Рандом не просто берёт случайный элемент из списка. Алгоритм делает несколько шагов:

1. Убирает картинки, которые недавно показывались в текущем чате.
2. Убирает глобально свежие выдачи по всему пулу.
3. Отдаёт приоритет картинкам с меньшим количеством показов.
4. Выбирает итоговую пикчу через `SystemRandom`.

Если картинок много, повторов становится заметно меньше. Если картинок мало, повторы возможны, но бот старается не крутить одну и ту же пикчу подряд.

### Загрузка картинок

1. Нажмите `⬆️ Залить пикчи` или отправьте `/upload_pidor`.
2. Отправьте одну картинку, несколько картинок подряд, альбом Telegram или пересланные изображения.
3. Когда закончите, нажмите `✅ Закончить` или отправьте `/done`.

Бот не пишет отбивку на каждую принятую картинку. После первой успешной картинки он один раз подтверждает, что пакет принимается.

Если файл не является изображением, бот не добавляет его в пул. Если картинка уже была в пуле, она считается дубликатом и пропускается.

### Группы и Privacy Mode

В Telegram-группах обычные фото могут не доходить до бота, если включён BotFather Privacy Mode.

Лучший вариант:

1. Откройте `@BotFather`.
2. Выполните `/setprivacy`.
3. Выберите `@kartinkomet_bot`.
4. Выберите `Disable`.

Если Privacy Mode оставлен включённым, открывайте загрузку и прикрепляйте картинки ответом на сообщение бота. Поэтому бот отправляет отдельное ForceReply-сообщение в группах.

### Каналы

Для каналов бот должен быть администратором с правом отправлять сообщения и медиа.

Надёжная схема:

1. Загружать картинки в личке с ботом или в отдельной админ-группе.
2. Указать `TARGET_CHANNEL_ID`.
3. Вызывать `/pic`, чтобы бот публиковал картинку в привязанный канал.

### Реакции

Под каждой картинкой есть:

- `👍`
- `💩`
- `🖕`

Правила:

- один пользователь даёт один голос на одну картинку
- пользователь может изменить реакцию
- голоса разных пользователей складываются
- накрутка одним человеком не работает

Народный суд:

- `3 🖕` - бот предупреждает, что пикча близко к вылету
- `4 🖕` - бот пишет, что пикча на грани
- `5 🖕` - картинка удаляется из пула

### Тексты

Все большие наборы фраз лежат в `bot/texts.py`.

Сейчас внутри:

- `333` caption-фразы для картинок
- `150` стартовых фраз загрузки
- `30` фраз завершения загрузки
- `30` фраз пустого пула
- `24` достижения
- ежедневные mood-режимы
- правила народного суда

Caption под картинкой чистый. Старые mood-префиксы удалены.

### Достижения

Бот выдаёт достижения за количество загруженных пикч конкретным пользователем.

Формат:

```text
🏅 Достижение: первый вброс
@username загрузил пикч: 1
```

В реальном сообщении слово `Достижение:` выделяется жирным.

### Статистика

`/stats` показывает:

- сколько пикч в пуле
- сколько раз бот выдавал картинки
- сколько поставили `👍`
- сколько поставили `💩`
- сколько поставили `🖕`

Служебная команда `/reset_stats` сбрасывает реакции, показы и память рандома. Она не показывается в меню команд и доступна только пользователям из `ADMIN_USER_IDS`.

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

### Производительность

- пул читается в память один раз при запуске
- поиск картинки по `id` работает через индекс
- проверка дублей по `file_unique_id` работает через индекс
- счётчик загрузок пользователя берётся из индекса
- реакции нормализуются при чтении JSON
- запись JSON идёт атомарно через временный файл
- глобальный анти-повтор использует быстрый выбор свежих записей без полной сортировки
- обработчики отделены от больших текстовых пулов

### Структура проекта

```text
bot/__main__.py    # запуск aiogram polling и меню команд
bot/config.py      # переменные окружения и пути
bot/handlers.py    # команды, callback-кнопки и сценарии бота
bot/image_pool.py  # JSON-хранилище, рандом, реакции и индексы
bot/keyboards.py   # inline-клавиатуры
bot/texts.py       # фразы, caption-пулы, mood, достижения и народный суд
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
ADMIN_USER_IDS=
```

`ADMIN_USER_IDS` можно заполнить одним ID или списком через запятую:

```env
ADMIN_USER_IDS=123456789,987654321
```

Узнать свой ID можно командой `/id` в личке с ботом.

Запуск:

```bash
python -m bot
```

Проверка:

```bash
python -m compileall bot tests
python -m unittest discover
```

### Railway

В проекте уже есть:

- `Procfile` - запускает `python -m bot`
- `.python-version` - Python `3.12`

Переменные Railway:

```env
BOT_TOKEN=токен_бота
TARGET_CHANNEL_ID=
ADMIN_USER_IDS=ваш_telegram_user_id
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

`@kartinkomet_bot` is a Telegram bot for groups and channels. It sends random images from a shared pool using `/pic` or the `🎲 Рандом` button.

The bot does not store image files on the server. It stores only Telegram `file_id` values. The real files remain on Telegram's side.

### Core Features

- shared image pool
- uploads are open to everyone
- the only slash upload command is `/upload_pidor`
- no physical image storage on the bot server
- duplicate detection through Telegram `file_unique_id`
- per-chat anti-repeat random memory
- one reaction per user per image, with reaction switching
- automatic image removal after `5 🖕`
- upload achievements
- `/reset_stats` protected by `ADMIN_USER_IDS`

### Commands And Buttons

| Command or Button | Action |
| --- | --- |
| `🎲 Рандом`, `/pic` | Sends a random image |
| `🎲 Ещё` | Sends another image below the current one |
| `⬆️ Залить пикчи`, `/upload_pidor` | Starts upload mode |
| `✅ Закончить`, `/done` | Finishes upload mode and shows a summary |
| `❌ Отмена`, `/cancel` | Cancels the active upload |
| `/count` | Shows the pool size |
| `/stats` | Shows views and reactions |
| `/mood` | Shows today's bot mood |
| `/menu` | Opens the main control panel |
| `/help` | Shows the command list |

There is no `/upload` command by design. Upload mode starts through the button or `/upload_pidor`.

### Random Selection

The random picker is chat-aware:

1. It avoids images recently shown in the current chat.
2. It avoids globally recent images.
3. It prioritizes images with fewer views.
4. It uses `SystemRandom` for the final choice.

Large pools repeat much less often. Small pools can still repeat, but the bot tries not to send the same image immediately.

### Uploading

1. Press `⬆️ Залить пикчи` or send `/upload_pidor`.
2. Send one image, multiple images, a Telegram album, or forwarded images.
3. Press `✅ Закончить` or send `/done`.

The bot confirms batch upload only once after the first accepted image.

Non-image files are rejected. Duplicate images are skipped.

### Groups And Privacy Mode

For group uploads, disable BotFather Privacy Mode:

1. Open `@BotFather`.
2. Run `/setprivacy`.
3. Select `@kartinkomet_bot`.
4. Select `Disable`.

If Privacy Mode remains enabled, Telegram may hide regular group photos from the bot. Start upload mode and attach images as a reply to the bot's ForceReply message.

### Channels

For channels, the bot must be an admin with permission to post messages and media.

The reliable flow is:

1. Upload images in a private chat with the bot or in an admin group.
2. Set `TARGET_CHANNEL_ID`.
3. Call `/pic` to publish into the target channel.

### Reactions

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

- `3 🖕` - warning
- `4 🖕` - final warning
- `5 🖕` - image removed from the pool

### Text Pools

Large text pools live in `bot/texts.py`.

Current counts:

- `333` image captions
- `150` upload-start phrases
- `30` upload-finish phrases
- `30` empty-pool phrases
- `24` achievements
- daily mood labels
- jury threshold messages

Image captions are clean. Mood prefixes were removed from card captions.

### Maintenance

`/reset_stats` resets reactions, view counters, and random memory. It is hidden from the public command menu and works only for users listed in `ADMIN_USER_IDS`.

Use `/id` in a private chat with the bot to get your Telegram user ID.

### Storage And Performance

The pool is stored as JSON and automatically migrates older plain `file_id` lists to the current versioned format.

Performance notes:

- the pool is loaded into memory once at startup
- image lookup by `id` uses an in-memory index
- duplicate checks use an in-memory `file_unique_id` set
- uploaded-count lookup uses an in-memory user index
- reactions are normalized while reading JSON
- JSON writes are atomic
- anti-repeat selection avoids full sorting of the whole pool
- text pools are separated from handlers

### Local Run

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

### Railway

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
