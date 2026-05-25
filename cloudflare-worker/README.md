# kartinkomet Cloudflare Worker

Новая серверлесс-версия бота для Cloudflare Workers + D1.

## Что уже внутри

- Webhook `/webhook`
- D1-хранилище через binding `DB`
- `/start`, `/menu`
- `/pic`, `/joke`
- `/count`, `/stats`
- `/upload_pidor`, `/upload_joke`
- `/done`, `/cancel`
- реакции `🤙🏻` и `🖕🏻`
- удаление пикчи/анекдота из пула после 2 `🖕🏻`
- анти-повтор рандома через `random_history`

## Cloudflare

Worker:

```text
https://kartinkomet-bot.artemkhom4enko.workers.dev
```

D1:

```text
kartinkomet-db
```

Binding:

```text
DB
```

Secrets:

```text
BOT_TOKEN
WEBHOOK_SECRET
```

## Первый запуск

Из этой папки:

```bash
npm install
npm run db:apply
npm run deploy
```

Поставить webhook:

```bash
WORKER_URL="https://kartinkomet-bot.artemkhom4enko.workers.dev" \
BOT_TOKEN="123456:telegram-token" \
WEBHOOK_SECRET="your-secret" \
npm run webhook:set
```

После этого Telegram начнёт отправлять апдейты в Cloudflare Worker.

## Важно

Старые Railway JSON-файлы не нужны для новой пустой версии. Пул начнётся с нуля.

Загрузка работает стабильнее в личке:

```text
/upload_pidor
/upload_joke
```

В группах бот только подсказывает, что загрузку надо открыть в личке.
