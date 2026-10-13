<p align="center">
  <img src="docs/assets/brandmark.png" width="96" alt="Логотип kartinkomet: четыре цветные плитки с цифрами 1–4">
</p>

<h1 align="center">kartinkomet</h1>

<p align="center"><strong>Склад пикч для твоего чата: дуэли с рейтингом, турниры и народный суд.</strong></p>

<p align="center">
  <a href="https://t.me/kartinkomet_bot"><strong>Открыть бота ↗</strong></a> ·
  <a href="#-как-играть">Как играть</a> ·
  <a href="#-своя-копия">Запуск</a> ·
  <a href="docs/ARCHITECTURE.md">Архитектура</a>
</p>

<p align="center">
  <a href="https://github.com/StonerHand/kartinkomet-bot/actions/workflows/ci.yml"><img src="https://img.shields.io/github/actions/workflow/status/StonerHand/kartinkomet-bot/ci.yml?branch=main&amp;style=flat-square&amp;label=CI&amp;color=E53935" alt="Статус CI"></a>
  <a href="https://github.com/StonerHand/kartinkomet-bot/releases"><img src="https://img.shields.io/github/v/release/StonerHand/kartinkomet-bot?style=flat-square&amp;color=E53935&amp;label=release" alt="Последний релиз"></a>
  <a href=".python-version"><img src="https://img.shields.io/badge/Python-3.12-E53935?style=flat-square" alt="Python 3.12"></a>
  <a href="https://docs.aiogram.dev"><img src="https://img.shields.io/badge/aiogram-3.20-E53935?style=flat-square" alt="aiogram 3.20"></a>
  <a href="https://railway.com"><img src="https://img.shields.io/badge/Deploy-Railway-E53935?style=flat-square" alt="Работает на Railway"></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/License-MIT-E53935?style=flat-square" alt="Лицензия MIT"></a>
</p>

<p align="center">
  <img src="docs/assets/hero.png" width="100%" alt="kartinkomet: коллаж турнира из четырёх пикч с цветными метками 1–4">
</p>

## ✨ Что умеет

- 🎲 **Честный рандом.** Колода без повторов, пока не покажут все. Иногда выпадают 🆕 свежие загрузки и 🏛 легенды зала славы.
- ⚔️ **Дуэли и турниры.** Пикчи склеиваются в один коллаж с цветными метками, голосование — кнопками прямо под ним. Победы двигают рейтинг Elo.
- 👑 **Серии чемпиона.** Победительница выходит снова и копит серию; на 3, 5 и 10 победах — объявления.
- ⚖️ **Народный суд.** Два 🖕🏻 — и пикча на скамье подсудимых. Казнить или помиловать решает чат, загрузчик может сказать последнее слово.
- 🏛 **Зал славы, дно и кладбище.** Лучшие по рейтингу, худшие под суд, казнённые с причиной смерти.
- 📅 **Само по расписанию.** Пикча дня, вечерний суд над худшей и итоги недели.
- 🏆 **Топы и 30 ачивок.** Загрузчики, любимцы публики, палачи, серии. Профиль в группе видишь только ты.
- 🔎 **Inline-режим.** `@kartinkomet_bot` в любом чате — пикча со склада.

## 📱 Как выглядит

| Дуэль | Турнир |
| :---: | :---: |
| <img src="docs/assets/duel.jpg" width="400" alt="Коллаж дуэли: две пикчи с метками A и B"> | <img src="docs/assets/tournament.jpg" width="360" alt="Коллаж турнира: четыре пикчи с метками 1–4"> |

Карточка голосования — подпись к коллажу, итог приходит в то же сообщение:

```
⚔️ ДУЭЛЬ · ⏳ 0:54
│ Великая сеча пикч начинается прямо сейчас

🅰️ 1  🟥
🅱️ 3  🟦🟦🟦🟦🟦

🗳 4 голоса · жми кнопку
```

```
⚔️ ИТОГ ДУЭЛИ · 1 : 3

👑 🅱️ stoner · ⭐ 1017 (+17)
▫️ 🅰️ train · ⭐ 1013 (−17)

│ Солнце склада сегодня светит для неё
```

## 🎮 Как играть

1. Добавьте бота в групповой чат.
2. Загрузите пикчи в личке: `/upload`, потом фото, альбомы или пересылки. Дубли бот выкинет сам.
3. В чате — `/pic`, `/duel`, `/tournament` или пульт `/menu`.

| Команда | Что делает |
| --- | --- |
| `/pic` | Случайная пикча |
| `/duel` · `/tournament` | Дуэль двух · турнир четырёх |
| `/menu` | Пульт: зал славы, дно, кладбище, топы, правила |
| `/top` · `/me` | Топы · своя карточка |
| `/upload` | Загрузка в личке |
| `/help` | Правила |
| `/admin` | Для админов: бэкап, health, события, сброс статистики |

## 🛠 Своя копия

Нужны Python 3.12 и токен бота от [@BotFather](https://t.me/BotFather).

```bash
git clone https://github.com/StonerHand/kartinkomet-bot.git
cd kartinkomet-bot
python3.12 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # впишите BOT_TOKEN и свой ID в ADMIN_USER_IDS
python -m bot
```

Inline-режим включается один раз в @BotFather: `/setinline`. Часовой пояс событий — `BOT_TZ_OFFSET` (по умолчанию `3`, Москва).

Для продакшена: Railway, worker `python -m bot` и volume под базу. Бот держится в ~100 МБ памяти и укладывается в бесплатный тариф.

## 🧩 Как устроено

```
Telegram ──▶ aiogram (long polling) ──▶ bot/tg   карточки, кнопки, таймеры, расписание
                                          │
                                          ▼
                                     bot/game.py ──▶ bot/core   колода, Elo, арена, суд, ачивки
                                          │
                                          ▼
                                 bot/db ──▶ SQLite (WAL) на volume
```

Картинки бот не хранит — только Telegram `file_id`, рейтинги и статистику. Активные бои и суды живут в базе и переживают рестарт. CI гоняет линтер и 86 тестов, включая сквозные сценарии с фейковым Telegram. Подробности — в [архитектуре](docs/ARCHITECTURE.md), изменения — в [релизах](https://github.com/StonerHand/kartinkomet-bot/releases).

## 📄 Лицензия

[MIT](LICENSE) © StonerHand

<p align="center"><a href="https://t.me/kartinkomet_bot"><strong>Устроить первую дуэль ↗</strong></a></p>
