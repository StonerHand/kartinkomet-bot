import asyncio
import logging
from datetime import UTC, datetime

from aiogram import Bot, Dispatcher
from aiogram.exceptions import TelegramAPIError
from aiogram.types import BotCommand, BotCommandScopeAllGroupChats, BotCommandScopeAllPrivateChats, CallbackQuery

from bot.config import load_config
from bot.db.repo import Repo
from bot.game import Game
from bot.tg import (
    admin, arena, boss, casino, challenges, court, fallback, games, higher, inline, panel, pics, progress, shop,
    social, upload,
)
from bot.tg.events import Events
from bot.tg.middleware import RememberUser
from bot.tg.timers import Live
from bot.tg.watchdog import STALL_SECONDS, PollingWatchdog, alert_admins

LOGGER = logging.getLogger("kartinkomet")
STALE_BACKLOG_SECONDS = 600  # a restart takes seconds; a backlog this old means the bot was down

GROUP_COMMANDS = [
    BotCommand(command="menu", description="🎛 пульт: всё в одном месте"),
    BotCommand(command="pic", description="🎲 рандомная пикча"),
    BotCommand(command="duel", description="⚔️ дуэль двух пикч"),
    BotCommand(command="tournament", description="🏟 турнир четырёх"),
    BotCommand(command="daily", description="🎁 бонус дня"),
    BotCommand(command="quests", description="📜 квесты и сундуки"),
    BotCommand(command="casino", description="🎰 казино"),
    BotCommand(command="spin", description="🎰 слоты: /spin 100"),
    BotCommand(command="dice", description="🎲 кости против бота: /dice 100"),
    BotCommand(command="shop", description="🛒 лавка"),
    BotCommand(command="boss", description="👹 призвать босса"),
    BotCommand(command="challenge", description="🤺 вызов на дуэль за монеты"),
    BotCommand(command="pvp", description="🎲 кости 1 на 1: /pvp 200"),
    BotCommand(command="whose", description="🕵️ угадай, чья пикча"),
    BotCommand(command="higher", description="🎯 выше-ниже: угадай рейтинг"),
    BotCommand(command="give", description="🎁 подарить монеты"),
    BotCommand(command="rob", description="🕵️ ограбить"),
    BotCommand(command="marry", description="💍 сделать предложение"),
    BotCommand(command="caption", description="🖋 подпиши пикчу"),
    BotCommand(command="wheel", description="🎡 колесо фортуны раз в день"),
    BotCommand(command="horoscope", description="🔮 гороскоп на сегодня"),
    BotCommand(command="top", description="🏆 рейтинги"),
    BotCommand(command="me", description="👤 моя карточка"),
    BotCommand(command="help", description="❓ правила"),
]
# Uploading works only in private chats, so only they get /upload in the menu.
PRIVATE_COMMANDS = [
    BotCommand(command="upload", description="📥 загрузить пикчи на склад"),
    *GROUP_COMMANDS,
]
SHORT_DESCRIPTION = "Склад пикч для чата: дуэли, суды, казино, боссы, свадьбы и ограбления"
DESCRIPTION = (
    "🎲 Общий склад пикч для твоей компании.\n\n"
    "⚔️ Пикчи дерутся на арене и набирают рейтинг\n"
    "⚖️ Неугодных судит народ\n"
    "🎰 Монеты, казино, лавка, боссы и квесты\n"
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


async def drop_stale_backlog(bot: Bot) -> int:
    """After a long outage Telegram still holds every command and button press of it. Replaying
    them all at once would spam the chat and spend coins on bets nobody remembers making, so a
    stale backlog is dropped; a short one (a deploy) is processed as usual. Returns the dropped count."""
    try:
        pending = (await bot.get_webhook_info()).pending_update_count
        if not pending:
            return 0
        oldest = await bot.get_updates(limit=1, timeout=0)  # without an offset nothing is confirmed
        if not oldest:
            return 0
        try:
            event = getattr(oldest[0], oldest[0].event_type)
        except LookupError:
            event = None
        if isinstance(event, CallbackQuery):  # a press has no date; its message is at least as old
            event = event.message
        sent = getattr(event, "date", None)
        if sent is not None and (datetime.now(UTC) - sent).total_seconds() < STALE_BACKLOG_SECONDS:
            return 0
        await bot.delete_webhook(drop_pending_updates=True)
        return pending
    except TelegramAPIError:
        LOGGER.warning("Could not check the update backlog", exc_info=True)
        return 0


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
        games.router,
        higher.router,
        casino.router,
        shop.router,
        social.router,
        challenges.router,
        progress.router,
        boss.router,
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

    repo = Repo(config.database_path)
    game = Game(repo, tz_offset_hours=config.tz_offset_hours)
    game.admins = config.admin_user_ids
    starters = game.give_starters()
    if starters:
        LOGGER.info("Gave the v4 starter bonus to %s players", starters)
    refunded = game.refund_unthrown_dice_duels()
    if refunded:
        LOGGER.info("Refunded %s dice duels left unthrown by a restart", refunded)
    gifted = game.give_gifts()
    if gifted:
        LOGGER.info("Handed out one-time gifts to %s players", gifted)
    backfilled = game.backfill_achievements()
    if backfilled:
        LOGGER.info("Silently granted %s already-earned achievements", backfilled)

    bot = Bot(token=config.bot_token)
    watchdog = PollingWatchdog()
    bot.session.middleware.register(watchdog)
    live = Live(bot, game)
    dispatcher = build_dispatcher(game, live, config.admin_user_ids)
    repo.seed_chats(game.now())
    events = Events(bot, game, live, config.admin_user_ids, config.tz_offset_hours)
    guard: asyncio.Task | None = None
    try:
        await set_up_profile(bot)
        restored = live.restore()
        if restored:
            LOGGER.info("Resumed %s live battles/courts", restored)
        dropped = await drop_stale_backlog(bot)
        if dropped:
            LOGGER.info("Dropped %s stale updates left from downtime", dropped)
        events.start()

        async def on_stall() -> None:
            await alert_admins(
                bot,
                config.admin_user_ids,
                f"⚠️ Бот {STALL_SECONDS // 60} минут не получает обновления от Telegram и перезапускается. "
                "Если это повторяется, загляни в логи Railway",
            )
            await dispatcher.stop_polling()

        guard = asyncio.create_task(watchdog.watch(on_stall))
        await dispatcher.start_polling(bot)
    finally:
        if guard is not None:
            guard.cancel()
        await events.stop()
        await live.stop()
        await bot.session.close()
        repo.close()
    if watchdog.stalled:
        raise SystemExit(1)  # a failure exit: Railway restarts the process and records the crash


if __name__ == "__main__":
    asyncio.run(main())
