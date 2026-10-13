import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.exceptions import TelegramAPIError
from aiogram.types import BotCommand, BotCommandScopeAllGroupChats, BotCommandScopeAllPrivateChats

from bot.config import load_config
from bot.db.migrate import migrate_if_needed
from bot.db.repo import Repo
from bot.game import Game
from bot.tg import admin, arena, court, fallback, inline, panel, pics, upload
from bot.tg.events import Events
from bot.tg.middleware import RememberUser
from bot.tg.timers import Live

LOGGER = logging.getLogger("kartinkomet")

GROUP_COMMANDS = [
    BotCommand(command="pic", description="🎲 рандомная пикча"),
    BotCommand(command="duel", description="⚔️ дуэль двух пикч"),
    BotCommand(command="tournament", description="🏟 турнир четырёх"),
    BotCommand(command="menu", description="🎛 пульт: слава, дно, кладбище, топы"),
    BotCommand(command="top", description="🏆 топы"),
    BotCommand(command="me", description="👤 моя карточка"),
    BotCommand(command="help", description="❓ правила"),
]
# Uploading works only in private chats, so only they get /upload in the menu.
PRIVATE_COMMANDS = [
    BotCommand(command="upload", description="📥 загрузить пикчи на склад"),
    *GROUP_COMMANDS,
]
SHORT_DESCRIPTION = "Склад пикч для чата: дуэли с рейтингом, турниры, народный суд и зал славы"
DESCRIPTION = (
    "🎲 Общий склад пикч для твоей компании.\n\n"
    "⚔️ Пикчи дерутся на арене и набирают рейтинг\n"
    "⚖️ Неугодных судит народ\n"
    "🏛 Лучшие попадают в зал славы, худшие — на кладбище\n\n"
    "Добавь меня в групповой чат, а пикчи загружай здесь, в личке: /upload"
)


async def set_up_profile(bot: Bot) -> None:
    """Command menus and profile texts. Cosmetic: a failure here must not stop the bot."""
    try:
        await bot.set_my_commands(GROUP_COMMANDS, scope=BotCommandScopeAllGroupChats())
        await bot.set_my_commands(PRIVATE_COMMANDS, scope=BotCommandScopeAllPrivateChats())
        await bot.set_my_commands(GROUP_COMMANDS)
        await bot.set_my_short_description(SHORT_DESCRIPTION)
        await bot.set_my_description(DESCRIPTION)
    except TelegramAPIError:
        LOGGER.warning("Could not update bot commands/description", exc_info=True)


def build_dispatcher(game: Game, live: Live, admin_ids: frozenset[int]) -> Dispatcher:
    dispatcher = Dispatcher(game=game, live=live, admins=admin_ids)
    dispatcher.message.outer_middleware(RememberUser(game))
    dispatcher.callback_query.outer_middleware(RememberUser(game))
    dispatcher.errors.register(fallback.on_error)
    # Order matters: court catches plain replies to the bot, fallback catches every leftover button.
    dispatcher.include_routers(
        panel.router,
        pics.router,
        arena.router,
        upload.router,
        admin.router,
        inline.router,
        court.router,
        fallback.router,
    )
    return dispatcher


async def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    config = load_config()
    if migrate_if_needed(config.legacy_database_path, config.database_path):
        LOGGER.info("Created %s from %s", config.database_path, config.legacy_database_path)

    repo = Repo(config.database_path)
    game = Game(repo, tz_offset_hours=config.tz_offset_hours)
    backfilled = game.backfill_achievements()
    if backfilled:
        LOGGER.info("Silently granted %s already-earned achievements", backfilled)

    bot = Bot(token=config.bot_token)
    live = Live(bot, game)
    dispatcher = build_dispatcher(game, live, config.admin_user_ids)
    repo.seed_chats(game.now())
    events = Events(bot, game, live, config.admin_user_ids, config.tz_offset_hours)
    try:
        await set_up_profile(bot)
        restored = live.restore()
        if restored:
            LOGGER.info("Resumed %s live battles/courts", restored)
        events.start()
        await dispatcher.start_polling(bot)
    finally:
        await events.stop()
        await live.stop()
        await bot.session.close()
        repo.close()


if __name__ == "__main__":
    asyncio.run(main())
