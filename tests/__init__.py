"""Tests run with aiogram loaded the way production loads it: lazily (bot/telegram/lean.py)."""

from bot.telegram.lean import load_aiogram

load_aiogram()
