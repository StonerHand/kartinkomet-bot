"""Telegram bot package. Importing it loads aiogram lazily (see bot/lean.py): ~45 MB less RAM."""

from bot.lean import load_aiogram

load_aiogram()
