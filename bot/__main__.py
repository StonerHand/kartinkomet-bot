import asyncio
import logging

from aiogram import Bot, Dispatcher

from bot.config import load_config
from bot.handlers import build_router
from bot.image_pool import ImagePool


async def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    config = load_config()
    bot = Bot(token=config.bot_token)
    dispatcher = Dispatcher()
    dispatcher.include_router(
        build_router(
            image_pool=ImagePool(config.image_pool_path),
            target_channel_id=config.target_channel_id,
        )
    )

    await dispatcher.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
