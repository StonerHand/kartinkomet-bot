"""`python -m bot`: load aiogram lean (bot/telegram/lean.py) before anything imports it, then run."""

import asyncio

from bot.telegram.lean import load_aiogram

load_aiogram()

from bot.app.main import main  # noqa: E402  aiogram has to be loaded lean first

asyncio.run(main())
