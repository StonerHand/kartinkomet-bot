import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.fsm.strategy import FSMStrategy
from aiogram.types import BotCommand

from bot.config import load_config
from bot.handlers import build_router
from bot.image_pool import ImagePool


BOT_COMMANDS = [
    BotCommand(command="pic", description="рандомная пикча"),
    BotCommand(command="upload", description="загрузить пикчи в пул"),
    BotCommand(command="done", description="закончить загрузку"),
    BotCommand(command="cancel", description="отменить загрузку"),
    BotCommand(command="count", description="количество пикч"),
    BotCommand(command="stats", description="статы по реакциям"),
    BotCommand(command="mood", description="режим бота на сегодня"),
    BotCommand(command="menu", description="открыть пульт"),
    BotCommand(command="help", description="список команд"),
]


async def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    config = load_config()
    bot = Bot(token=config.bot_token)
    await bot.set_my_commands(BOT_COMMANDS)
    dispatcher = Dispatcher(fsm_strategy=FSMStrategy.CHAT)
    dispatcher.include_router(
        build_router(
            image_pool=ImagePool(config.image_pool_path),
            target_channel_id=config.target_channel_id,
        )
    )

    await dispatcher.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
