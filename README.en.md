# kartinkomet-bot

**A Telegram bot for a shared image vault: random drops, rated duels, tournaments, a people's court, a hall of fame and a graveyard.**

The bot lives in a friends' group chat. It drops random pics from a shared vault, runs duels and tournaments, keeps an Elo rating for every pic, and puts disliked pics on trial. New pics are uploaded in a private chat with the bot. Image files stay on Telegram; the database keeps only `file_id`s, ratings, reactions and stats.

All bot text is Russian and hand-written in several voices (absurd captions, epic arena commentary, cheeky courts and leaderboards).

See [README.md](README.md) for the full feature list (in Russian) and [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for internals.

## Quick start

```bash
python3.12 -m venv .venv
.venv/bin/pip install -r requirements.txt
cp .env.example .env   # set BOT_TOKEN
.venv/bin/python -m bot
```

On first start, if a v1 database (`kartinkomet.sqlite`) is present, the bot builds `kartinkomet_v2.sqlite` from it and leaves the v1 file untouched.

## Tests

```bash
.venv/bin/python -m unittest discover -s tests -t .
```

## Notes

- Runs on Railway (free plan) as a long-polling worker with SQLite on a volume.
- aiogram is pinned to 3.20 on purpose: 3.31 roughly doubles memory use, and memory is what the free plan bills for.
