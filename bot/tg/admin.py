"""Admin tools: health, backup, stat reset with confirmation, pardons."""

import resource
import sys
import tempfile
from html import escape
from pathlib import Path

from aiogram import Bot, F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, FSInputFile, Message

from bot.game import Game
from bot.texts import ui
from bot.tg import keyboards, send, views
from bot.tg import screens
from bot.tg.panel import open_panel

router = Router(name="admin")


def memory_mb() -> float:
    peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return peak / (1024 * 1024) if sys.platform == "darwin" else peak / 1024


def health_text(game: Game) -> str:
    repo = game.repo
    totals = repo.totals()
    size = repo.database_path.stat().st_size / 1024 / 1024 if repo.database_path.exists() else 0
    return views.card(
        "🩺 <b>HEALTH</b>",
        "Состояние бота",
        [
            f"📦 Живых: <b>{totals['alive']}</b>",
            f"⚰️ Казнено: <b>{totals['executed']}</b>",
            f"👥 Юзеров: <b>{repo.count_users()}</b>",
            f"⚔️ Боёв идёт: <b>{len(repo.active_battle_ids())}</b>",
            f"⚖️ Судов идёт: <b>{len(repo.active_court_ids())}</b>",
            f"👹 Боссов: <b>{len(repo.active_boss_ids())}</b>",
        ],
        [
            f"🗄 База: <b>{size:.1f}</b> МБ · <code>{escape(repo.database_path.name)}</code>",
            f"🧠 Пик памяти: <b>{memory_mb():.0f}</b> МБ",
        ],
    )


@router.message(Command("admin"))
async def admin_command(message: Message, bot: Bot, game: Game, admins: frozenset[int]) -> None:
    if message.from_user is None or message.from_user.id not in admins:
        await send.reply_personal(bot, message, ui.ADMIN_ONLY)
        return
    await open_panel(message, bot, game, admins, "adm")


@router.message(Command("health"))
async def health_command(message: Message, bot: Bot, game: Game, admins: frozenset[int]) -> None:
    if message.from_user is None or message.from_user.id not in admins:
        await send.reply_personal(bot, message, ui.ADMIN_ONLY)
        return
    await message.answer(health_text(game), parse_mode="HTML")


@router.callback_query(F.data.startswith("adm:"))
async def admin_buttons(callback: CallbackQuery, bot: Bot, game: Game, admins: frozenset[int]) -> None:
    message = callback.message
    if callback.from_user.id not in admins:
        await callback.answer(ui.ADMIN_ONLY, show_alert=True)
        return
    if message is None:
        await callback.answer()
        return
    chat_id = message.chat.id
    action = callback.data.split(":", 1)[1]

    if action == "events":
        enabled = not game.repo.chat_events_on(chat_id)
        game.repo.set_chat_events(chat_id, enabled, game.now())
        await callback.answer(
            "🔔 Пикча дня, вечерний суд и итоги недели включены" if enabled else "🔕 События по расписанию выключены",
            show_alert=True,
        )
        text, markup = screens.render("adm", screens.Ctx(game, chat_id, callback.from_user.id, True, message.chat.type == "private"))
        await send.edit_text(bot, chat_id, message.message_id, text, markup)
    elif action == "health":
        await callback.answer()
        await send.edit_text(
            bot, chat_id, message.message_id, health_text(game), keyboards.markup(keyboards.back("m:adm"))
        )
    elif action == "stats":
        await callback.answer()
        await send.edit_text(
            bot, chat_id, message.message_id, views.admin_stats(game.usage()), keyboards.markup(keyboards.back("m:adm"))
        )
    elif action == "backup":
        await callback.answer("Собираю бэкап")
        with tempfile.TemporaryDirectory(prefix="kartinkomet-") as temp_dir:
            path = Path(temp_dir) / "kartinkomet_v2.sqlite"
            game.repo.export_backup(path)
            await bot.send_document(
                chat_id, FSInputFile(path, filename=path.name), caption="💾 Снимок всей базы"
            )
    elif action == "reset":
        await callback.answer()
        await send.edit_text(
            bot,
            chat_id,
            message.message_id,
            "🧨 <b>СБРОСИТЬ СТАТИСТИКУ?</b>\n<i>Отменить будет нельзя</i>\n\n"
            "Обнулятся рейтинги, реакции, показы, серии и рекорды. "
            "Пикчи, кладбище и ачивки останутся.",
            keyboards.admin_reset_confirm(),
        )
    elif action == "reset!":
        game.repo.reset_stats()
        await callback.answer("Стата обнулена", show_alert=True)
        text, markup = screens.render("adm", screens.Ctx(game, chat_id, callback.from_user.id, True, message.chat.type == "private"))
        await send.edit_text(bot, chat_id, message.message_id, text, markup)
    elif action.startswith("spare:"):
        pic_id = action.split(":", 1)[1]
        revived = game.pardon(pic_id)
        await callback.answer("🕊 Воскрешена" if revived else "Уже жива или не найдена", show_alert=True)
        text, markup = screens.render("grave", screens.Ctx(game, chat_id, callback.from_user.id, True, message.chat.type == "private"))
        await send.edit_text(bot, chat_id, message.message_id, text, markup)
    else:
        await callback.answer()
