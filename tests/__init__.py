"""Tests run with aiogram loaded the way production loads it: lazily (bot/lean.py)."""

import importlib

importlib.import_module("bot")
