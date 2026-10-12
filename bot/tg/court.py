"""People's court: opening trials, votes, the defendant's last word."""

from aiogram import Bot, F, Router
from aiogram.types import CallbackQuery, Message

from bot.game import Game
from bot.texts import court as court_texts
from bot.texts.pick import pick
from bot.tg import keyboards, send, views
from bot.tg.timers import Live

router = Router(name="court")


async def open_court(
    bot: Bot,
    game: Game,
    live: Live,
    chat_id: int,
    pic_id: str,
    reason: str,
    started_by: int | None,
    pic_message_id: int | None = None,
) -> str:
    """Returns 'started' | 'active' | 'immune' | 'gone' | 'failed'."""

    def attempt():
        return game.start_court(
            chat_id,
            pic_id,
            reason,
            started_by,
            title=pick(court_texts.SUMMONS, chat_id),
            pic_message_id=pic_message_id,
        )

    result = attempt()
    if result.status == "active" and result.court and result.court.ends_at <= game.now():
        await live.finish_court(result.court.id)
        result = attempt()
    if result.status != "started" or result.court is None:
        return result.status

    trial = result.court
    message = await send.send_photo(
        bot,
        chat_id,
        trial.pic.file_id,
        views.court_card(trial, trial.ends_at - game.now(), game.repo.user_label(trial.pic.added_by)),
        keyboards.court_vote(trial.id, 0, 0),
        reply_to=pic_message_id,
    )
    if message is None:
        game.cancel_court(trial.id)
        return "failed"
    game.repo.set_court_message(trial.id, message.message_id)
    if pic_message_id is not None:
        await send.edit_markup(bot, chat_id, pic_message_id, keyboards.on_trial())
    live.watch_court(trial.id)
    return "started"


@router.callback_query(F.data.startswith("c:go:"))
async def summon_from_bottom(callback: CallbackQuery, bot: Bot, game: Game, live: Live) -> None:
    if callback.message is None:
        await callback.answer()
        return
    pic_id = callback.data.split(":", 2)[2]
    status = await open_court(
        bot, game, live, callback.message.chat.id, pic_id, "bottom", callback.from_user.id
    )
    answers = {
        "started": court_texts.BOTTOM_SUMMONS_ANSWER,
        "active": court_texts.ALREADY_ON_TRIAL,
        "immune": court_texts.IMMUNE,
    }
    if status in answers:
        await callback.answer(pick(answers[status]), show_alert=status != "started")
    elif status == "gone":
        await callback.answer("Её уже нет в живых", show_alert=True)
    else:
        await callback.answer("Telegram не дал открыть суд, попробуй ещё раз", show_alert=True)


@router.callback_query(F.data.regexp(r"^c:[ks]:"))
async def court_vote(callback: CallbackQuery, game: Game, live: Live) -> None:
    _, kind, court_id = callback.data.split(":", 2)
    vote = "kill" if kind == "k" else "spare"
    status, trial = game.vote_court(court_id, callback.from_user.id, vote)
    if status == "expired":
        await callback.answer("Время вышло, приговор оглашается")
        await live.finish_court(court_id)
        return
    if status in ("gone", "closed"):
        await callback.answer("Суд уже окончен", show_alert=True)
        return
    if status == "same":
        await callback.answer("Ты уже так проголосовал")
        return
    await callback.answer("🪓 Голос за казнь принят" if vote == "kill" else "🕊 Голос за помилование принят")
    live.request_refresh_court(court_id)


@router.callback_query(F.data == "trial")
async def trial_placeholder(callback: CallbackQuery) -> None:
    await callback.answer("Пикча под судом. Голосуй в карточке суда", show_alert=True)


@router.message(F.reply_to_message.from_user.is_bot & F.text)
async def last_word(message: Message, game: Game, live: Live) -> None:
    if message.from_user is None or message.reply_to_message is None:
        return
    trial = game.last_word(
        message.chat.id,
        message.reply_to_message.message_id,
        message.from_user.id,
        message.text or "",
    )
    if trial is None:
        return
    await live.refresh_court(trial.id)
    await message.reply("🗣 Записано в протокол. Присяжные, учтите")
