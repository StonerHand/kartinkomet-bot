import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.types import BotCommand

from bot.config import load_config
from bot.db.migrate import migrate_if_needed
from bot.db.repo import Repo
from bot.game import Game
from bot.tg import admin, arena, court, fallback, panel, pics, upload
from bot.tg.middleware import RememberUser
from bot.tg.timers import Live

LOGGER = logging.getLogger("kartinkomet")

BOT_COMMANDS = [
    BotCommand(command="pic", description="рандомная пикча"),
    BotCommand(command="duel", description="дуэль двух пикч"),
    BotCommand(command="tournament", description="турнир четырёх"),
    BotCommand(command="menu", description="пульт: зал славы, дно, кладбище"),
    BotCommand(command="top", description="топы"),
    BotCommand(command="me", description="моя карточка"),
    BotCommand(command="upload", description="загрузка пикч в личке"),
    BotCommand(command="help", description="как тут всё устроено"),
]


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
    try:
        await bot.set_my_commands(BOT_COMMANDS)
        restored = live.restore()
        if restored:
            LOGGER.info("Resumed %s live battles/courts", restored)
        await dispatcher.start_polling(bot)
    finally:
        await live.stop()
        await bot.session.close()
        repo.close()


if __name__ == "__main__":
    asyncio.run(main())
