import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.fsm.strategy import FSMStrategy
from aiogram.types import BotCommand

from bot.config import load_config
from bot.handlers import build_router
from bot.image_pool import ImagePool


BOT_COMMANDS = [
    BotCommand(command="start", description="запуск и пульт"),
    BotCommand(command="menu", description="главный пульт"),
    BotCommand(command="pic", description="рандомная пикча"),
    BotCommand(command="duel", description="дуэль двух пикч"),
    BotCommand(command="tournament", description="турнир четырёх пикч"),
    BotCommand(command="upload_pidor", description="загрузка пикч в личке"),
    BotCommand(command="stats", description="сводка склада и арен"),
    BotCommand(command="count", description="быстрый счётчик склада"),
    BotCommand(command="me", description="мой вклад и титул"),
    BotCommand(command="top", description="топ загрузчиков"),
    BotCommand(command="help", description="карта команд"),
]


async def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    config = load_config()
    bot = Bot(token=config.bot_token)
    dispatcher = Dispatcher(fsm_strategy=FSMStrategy.CHAT)
    dispatcher.include_router(
        build_router(
            image_pool=ImagePool(config.image_pool_path, database_path=config.database_path),
            target_channel_id=config.target_channel_id,
            admin_user_ids=config.admin_user_ids,
        )
    )

    try:
        await bot.set_my_commands(BOT_COMMANDS)
        await dispatcher.start_polling(bot)
    finally:
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())
